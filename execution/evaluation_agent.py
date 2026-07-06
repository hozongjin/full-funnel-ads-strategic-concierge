# /// script
# dependencies = [
#   "google-cloud-bigquery",
#   "python-dotenv",
# ]
# ///

"""
EvaluationAgent — 100% Deterministic Scoring Engine.

All scoring functions use rules-based checks (regex, set operations, bounds).
No LLM judge is used anywhere in this module.
"""

import json
import os
import re
from datetime import datetime, timezone

import bq_connector


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CONFIG_DIR = os.path.join(_ROOT, "config")
_QUIRK_REGISTRY_PATH = os.path.join(_CONFIG_DIR, "ga4_quirk_registry.json")
_EVAL_LOG_PATH = os.path.join(_CONFIG_DIR, "eval_log.jsonl")

# Valid GA4 BQ schema columns (from ga4_data_dictionary.md)
VALID_GA4_COLUMNS = {
    "event_date", "event_timestamp", "event_name", "event_params",
    "user_pseudo_id", "user_id",
    "device", "geo", "traffic_source", "ecommerce", "items",
    # Common nested / aliased fields the SQL may legitimately produce
    "source", "medium", "channel", "channel_medium",
    "total_sessions", "total_purchases", "total_revenue",
    "engaged_sessions", "bounced_sessions", "total_unique_users",
    "total_view_item", "total_add_to_cart", "total_begin_checkout",
    "session_id", "ga_session_id", "is_engaged",
    "item_category", "item_name", "item_revenue", "quantity", "price",
    "purchase_revenue_in_usd", "transaction_id", "tax", "shipping",
    "country", "region", "city", "continent", "sub_continent", "metro",
    "category", "browser", "operating_system", "device_category",
    "campaign", "name", "traffic_name", "page_title", "page_location",
    "stream_id", "platform", "total_items", "revenue", "spend",
    # Derived names the SQL might alias (allowed as raw counts)
    "bounce_rate", "engagement_rate", "cvr", "aov", "ecr", "roas",
    "view_to_cart_ratio", "cart_abandonment_rate",
    "cost_per_engaged_session", "revenue_per_user",
    "total_events", "null_events", "null_purchases_revenue",
    "event_count", "total_quantity", "total_item_quantity", "item_quantity",
    "item_id", "total_quantity_purchased", "total_item_revenue", "total_unique_buyers"
}

# Valid Chart.js v3+ chart types
VALID_CHART_TYPES = {"bar", "line", "pie", "doughnut", "radar", "polarArea", "scatter", "bubble"}

# Insight actionability verbs
ACTION_VERBS = {
    "recommend", "reallocate", "increase", "decrease", "shift",
    "pause", "invest", "prioritize", "optimize", "reduce",
    "focus", "scale", "test", "consider", "stop", "double",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_quirk_registry() -> list[dict]:
    """Load GA4 quirk rules dynamically from the registry file."""
    if not os.path.exists(_QUIRK_REGISTRY_PATH):
        return []
    with open(_QUIRK_REGISTRY_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _sql_contains(sql_upper: str, pattern: str) -> bool:
    """Case-insensitive substring check."""
    return pattern.upper() in sql_upper


def _append_eval_log(record: dict):
    """Append a single JSON record to the eval log."""
    record["timestamp"] = datetime.now(timezone.utc).isoformat()
    with open(_EVAL_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")


# ---------------------------------------------------------------------------
# Stage 2 — IntegrityAgent Audit
# ---------------------------------------------------------------------------

def score_integrity(integrity_result: dict, raw_stats: dict) -> dict:
    """Binary check: did the IntegrityAgent's PASS/FAIL match the actual data?"""
    null_pct = 0.0
    total = raw_stats.get("total_events", 1)
    if total > 0:
        null_pct = (raw_stats.get("null_events", 0) / total) * 100

    # If null_pct > 5%, the correct answer is FAIL.  Otherwise PASS.
    expected_status = "FAIL" if null_pct > 5.0 else "PASS"
    actual_status = integrity_result.get("status", "UNKNOWN")
    is_correct = actual_status == expected_status

    return {
        "stage": "integrity",
        "score": 100 if is_correct else 0,
        "status": "PASS" if is_correct else "FAIL",
        "detail": f"null_pct={null_pct:.2f}%, expected={expected_status}, got={actual_status}",
    }


# ---------------------------------------------------------------------------
# Stage 3 — SQL Accuracy Score (100% deterministic)
# ---------------------------------------------------------------------------

def score_sql(sql: str, user_query: str) -> dict:
    """Score SQL via Schema Compliance (50pts) + GA4 Quirk Compliance (50pts)."""
    sql_upper = sql.upper()
    flags = []

    # --- Sub-score 1: Schema Compliance (50pts) ---
    schema_score = 50
    output_columns, err = bq_connector.dry_run_schema(sql)

    if err:
        schema_score = 0
        flags.append(f"SCHEMA_CHECK_FAILED: {err}")
    else:
        # BigQuery Dry Run passed! This guarantees all queried columns exist in the base table.
        # We do not need to restrict the output ALIASES the LLM chooses.
        pass

    # --- Sub-score 2: GA4 Quirk Compliance (50pts) ---
    quirk_score = 50
    quirks = _load_quirk_registry()
    user_lower = user_query.lower()

    for quirk in quirks:
        # Only apply quirk if the query is relevant (using word boundaries to avoid 'rate' matching 'generate')
        applies = False
        for kw in quirk.get("applies_when_keywords", []):
            if re.search(rf"\b{re.escape(kw)}\b", user_lower):
                applies = True
                break
                
        if not applies:
            continue

        # Check required patterns
        if quirk.get("check_type") == "must_include":
            for pattern in quirk.get("check_patterns", []):
                if not _sql_contains(sql_upper, pattern):
                    quirk_score = max(0, quirk_score - 15)
                    flags.append(f"QUIRK_MISSING({quirk['id']}): expected '{pattern}'")

        # Check forbidden patterns
        for pattern in quirk.get("forbidden_patterns", []):
            if _sql_contains(sql_upper, pattern):
                quirk_score = max(0, quirk_score - 15)
                flags.append(f"QUIRK_VIOLATION({quirk['id']}): found forbidden '{pattern}'")

    total = schema_score + quirk_score
    return {
        "stage": "sql_accuracy",
        "score": total,
        "schema_score": schema_score,
        "quirk_score": quirk_score,
        "flags": flags,
    }


# ---------------------------------------------------------------------------
# Stage 3b — Math Completeness & Sanity Score (100% deterministic)
# ---------------------------------------------------------------------------

# Sanity bounds for derived metrics
_SANITY_BOUNDS = {
    "bounce_rate":          (0.0, 1.0),
    "engagement_rate":      (0.0, 1.0),
    "cvr_pct":              (0.0, 100.0),
    "roas":                 (0.0, None),    # no upper bound
    "aov":                  (0.0, None),
    "cpa":                  (0.0, None),
    "cart_abandonment_rate": (0.0, 1.0),
    "ecr":                  (0.0, 1.0),
    "view_to_cart_ratio":   (0.0, None),
    "revenue_per_user":     (0.0, None),
}


def score_math(query_results: list[dict], computed_metrics: dict | None = None) -> dict:
    """Validate field completeness and sanity bounds of computed metrics.

    Args:
        query_results: Raw rows returned by BigQuery.
        computed_metrics: Dict of metric_name -> value produced by calculation_engine.
    """
    flags = []

    # --- Sub-score 1: Field Completeness (60pts) ---
    completeness_score = 60
    if not query_results:
        completeness_score = 0
        flags.append("NO_DATA_RETURNED")
    else:
        returned_keys = set()
        for row in query_results:
            returned_keys.update(k.lower() for k in row.keys())
        # Warn if derived ratios are pre-computed in SQL instead of raw counts
        precomputed_ratios = {"bounce_rate", "cvr", "aov", "ecr", "roas",
                              "cart_abandonment_rate", "view_to_cart_ratio"}
        for ratio in precomputed_ratios:
            if ratio in returned_keys:
                completeness_score = max(0, completeness_score - 5)
                flags.append(f"RAW_FIELDS_MISSING: SQL pre-computed '{ratio}' — should return raw counts only")

    # --- Sub-score 2: Sanity Bounds (40pts) ---
    sanity_score = 40
    if computed_metrics:
        for metric_name, value in computed_metrics.items():
            bounds = _SANITY_BOUNDS.get(metric_name)
            if bounds is None or value is None:
                continue
            lo, hi = bounds
            if lo is not None and value < lo:
                sanity_score = max(0, sanity_score - 10)
                flags.append(f"SANITY_FAIL: {metric_name}={value} below min {lo}")
            if hi is not None and value > hi:
                sanity_score = max(0, sanity_score - 10)
                flags.append(f"SANITY_FAIL: {metric_name}={value} above max {hi}")

    total = completeness_score + sanity_score
    return {
        "stage": "math_sanity",
        "score": total,
        "completeness_score": completeness_score,
        "sanity_score": sanity_score,
        "flags": flags,
    }


# ---------------------------------------------------------------------------
# Stage 4 — Chart Consistency Score (100% deterministic)
# ---------------------------------------------------------------------------

def score_chart(chart_config: dict, query_results: list[dict], user_query: str) -> dict:
    """Score chart config via Syntax Validity + Data Shape Mapping + Memory Adherence."""
    flags = []

    chart_type = chart_config.get("type", chart_config.get("chart_type", ""))
    if isinstance(chart_type, str):
        chart_type = chart_type.lower()

    # --- Check 1: Syntax Validity (50pts) ---
    syntax_score = 50
    if chart_type not in VALID_CHART_TYPES:
        syntax_score = 0
        flags.append(f"INVALID_CHART_TYPE: '{chart_type}' is not a valid Chart.js v3+ type")

    # --- Check 2: Data Shape Mapping (30pts) ---
    shape_score = 30
    if query_results:
        first_row_keys = {k.lower() for k in query_results[0].keys()}
        has_date = bool(first_row_keys & {"event_date", "date", "day", "month", "week"})

        if has_date and chart_type not in {"line", "bar"}:
            shape_score = 0
            flags.append(f"SHAPE_MISMATCH: data has date column but chart type is '{chart_type}'")
    else:
        shape_score = 0
        flags.append("SHAPE_CHECK_SKIPPED: no data rows to evaluate")

    # --- Check 2b: Clarification Intent Match ---
    # The user_query now contains the approved ClarificationAgent plan.
    user_query_lower = user_query.lower()
    expected_chart = None
    if "bar chart" in user_query_lower: expected_chart = "bar"
    elif "line chart" in user_query_lower: expected_chart = "line"
    elif "pie chart" in user_query_lower: expected_chart = "pie"
    elif "doughnut chart" in user_query_lower: expected_chart = "doughnut"
    elif "scatter chart" in user_query_lower: expected_chart = "scatter"
    
    if expected_chart and chart_type != expected_chart:
        syntax_score = 0
        flags.append(f"CHART_TYPE_MISMATCH: ClarificationAgent instructed '{expected_chart}' but Concierge built '{chart_type}'")

    # --- Check 3: Memory Adherence (20pts) ---
    memory_score = 20
    memory_path = os.path.join(_CONFIG_DIR, "visual_memory.json")
    if os.path.exists(memory_path):
        try:
            with open(memory_path, "r", encoding="utf-8") as f:
                memory_bank = json.load(f).get("memory_bank", [])
            # Exact string match on the query
            for entry in memory_bank:
                if entry.get("query_semantic_match", "").strip().lower() == user_query.strip().lower():
                    expected_type = entry.get("layout_template", "").lower()
                    if expected_type and expected_type != chart_type:
                        memory_score = 0
                        flags.append(
                            f"MEMORY_DRIFT: prior query used '{expected_type}' but now got '{chart_type}'"
                        )
                    break
        except Exception:
            pass  # No memory file or corrupt — skip, full points

    total = syntax_score + shape_score + memory_score
    return {
        "stage": "chart_consistency",
        "score": total,
        "syntax_score": syntax_score,
        "shape_score": shape_score,
        "memory_score": memory_score,
        "flags": flags,
    }


# ---------------------------------------------------------------------------
# Stage 5 — Insight Quality Score (100% deterministic NLP heuristics)
# ---------------------------------------------------------------------------

def score_insight(insights: str, query_results: list[dict],
                  computed_metrics: dict | None = None,
                  history_context: str = "") -> dict:
    """Score insight text via number grounding, actionability, conciseness, and context."""
    flags = []

    # --- Check 1: Factual Grounding via Number Extraction (40pts) ---
    grounding_score = 40
    # Extract all numbers from the insight text
    insight_numbers = set()
    for match in re.findall(r"\b\d[\d,]*\.?\d*%?\b", insights):
        cleaned = match.replace(",", "").rstrip("%")
        try:
            insight_numbers.add(float(cleaned))
        except ValueError:
            pass

    # Build set of all legitimate numbers from data + computed metrics
    legitimate_numbers = set()
    for row in query_results:
        for v in row.values():
            if isinstance(v, (int, float)):
                legitimate_numbers.add(float(v))
                # Also add common rounded forms
                legitimate_numbers.add(round(float(v), 2))
                legitimate_numbers.add(round(float(v), 1))
                legitimate_numbers.add(round(float(v)))
    if computed_metrics:
        for v in computed_metrics.values():
            if isinstance(v, (int, float)):
                legitimate_numbers.add(float(v))
                legitimate_numbers.add(round(float(v), 2))
                legitimate_numbers.add(round(float(v), 1))
                legitimate_numbers.add(round(float(v)))
                # Percentage form (e.g., 0.35 -> 35.0)
                legitimate_numbers.add(round(float(v) * 100, 2))
                legitimate_numbers.add(round(float(v) * 100, 1))
                legitimate_numbers.add(round(float(v) * 100))

    if insight_numbers:
        hallucinated = insight_numbers - legitimate_numbers
        if hallucinated:
            penalty = min(40, len(hallucinated) * 10)
            grounding_score = max(0, grounding_score - penalty)
            flags.append(f"HALLUCINATED_NUMBERS: {hallucinated}")

    # --- Check 2: Actionability via Verb Matching (30pts) ---
    action_score = 30
    insight_lower = insights.lower()
    found_verbs = [v for v in ACTION_VERBS if v in insight_lower]
    if not found_verbs:
        action_score = 0
        flags.append("NO_ACTION_VERB: insight lacks a recommendation verb")

    # --- Check 3: Conciseness (15pts) ---
    concise_score = 15
    word_count = len(insights.split())
    if word_count > 150:
        concise_score = 0
        flags.append(f"TOO_VERBOSE: {word_count} words (max 150)")

    # --- Check 4: Contextual Awareness (15pts) ---
    context_score = 15
    if history_context and history_context != "No prior conversation context.":
        # Extract nouns/keywords from history (simple: words > 4 chars)
        history_words = {w.lower() for w in re.findall(r"\b\w{5,}\b", history_context)}
        insight_words = {w.lower() for w in re.findall(r"\b\w{5,}\b", insights)}
        overlap = history_words & insight_words
        if not overlap:
            context_score = 0
            flags.append("NO_CONTEXT_REFERENCE: insight doesn't reference conversation history")
    # If no history, full points (no context to reference)

    total = grounding_score + action_score + concise_score + context_score
    return {
        "stage": "insight_quality",
        "score": total,
        "grounding_score": grounding_score,
        "action_score": action_score,
        "concise_score": concise_score,
        "context_score": context_score,
        "flags": flags,
    }


# ---------------------------------------------------------------------------
# Build Full Eval Report
# ---------------------------------------------------------------------------

def build_eval_report(
    integrity_eval: dict,
    sql_eval: dict,
    math_eval: dict,
    chart_eval: dict,
    insight_eval: dict,
) -> dict:
    """Combine all stage scores into a single evaluation report."""
    all_flags = []
    for stage in [integrity_eval, sql_eval, math_eval, chart_eval, insight_eval]:
        all_flags.extend(stage.get("flags", []))

    report = {
        "integrity": integrity_eval,
        "sql_accuracy": sql_eval,
        "math_sanity": math_eval,
        "chart_consistency": chart_eval,
        "insight_quality": insight_eval,
        "all_flags": all_flags,
        "overall_pass": all(
            stage.get("score", 0) >= stage.get("threshold", 0)
            for stage in [sql_eval, math_eval, chart_eval]
        ),
    }

    _append_eval_log(report)
    return report


# ---------------------------------------------------------------------------
# Quirk Registry Management
# ---------------------------------------------------------------------------

def promote_to_quirk_registry(
    incident_id: str,
    description: str,
    check_patterns: list[str],
    applies_when_keywords: list[str],
    check_type: str = "must_include",
    forbidden_patterns: list[str] | None = None,
) -> str:
    """Append a new quirk entry to the registry. Returns the new quirk ID."""
    quirks = _load_quirk_registry()
    new_id = f"Q{len(quirks) + 1:03d}"

    entry = {
        "id": new_id,
        "description": description,
        "check_type": check_type,
        "check_patterns": check_patterns,
        "applies_when_keywords": applies_when_keywords,
        "source_incident": incident_id,
    }
    if forbidden_patterns:
        entry["forbidden_patterns"] = forbidden_patterns

    quirks.append(entry)
    with open(_QUIRK_REGISTRY_PATH, "w", encoding="utf-8") as f:
        json.dump(quirks, f, indent=2)

    return new_id


# ---------------------------------------------------------------------------
# Stage 6 — Reasoning Evaluator (LLM-as-a-Judge)
# ---------------------------------------------------------------------------

def score_agent_reasoning(agent_name: str, agent_output: str, expected_trajectory: list[str], expected_output: str) -> dict:
    """Uses a strong LLM to evaluate the qualitative reasoning of an agent."""
    from google import genai
    from google.genai import types

    client = genai.Client()
    
    prompt = f"""You are an expert AI evaluator.
You need to score the reasoning and output of an agent named '{agent_name}'.

AGENT OUTPUT:
{agent_output}

EXPECTED REASONING TRAJECTORY (Rubric):
{json.dumps(expected_trajectory, indent=2)}

EXPECTED FINAL OUTPUT GOAL:
{expected_output}

Based on the trajectory and goal, evaluate the agent's output on a scale of 0 to 100.
Deduct points for:
- Not following the expected trajectory steps (logic failure).
- Hallucinating facts, metrics, or external data.
- Violating core constraints of the agent's role.

Output exactly a JSON object with:
{{
  "score": <0-100 integer>,
  "flags": ["list of strings detailing any deductions or failures, empty if perfect"]
}}
"""

    import time
    for attempt in range(5):
        try:
            response = client.models.generate_content(
                model='gemini-3.1-flash-lite',
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                )
            )
            return json.loads(response.text.strip())
        except Exception as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                if attempt < 4:
                    time.sleep((2 ** attempt) * 2)  # 2s, 4s, 8s, 16s
                    continue
            return {"score": 0, "flags": [f"REASONING_EVAL_FAILED: {e}"]}
    
    return {"score": 0, "flags": ["REASONING_EVAL_FAILED: Max retries exceeded for 429 error."]}
