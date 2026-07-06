# /// script
# dependencies = [
#   "google-genai",
#   "google-cloud-bigquery",
#   "python-dotenv",
#   "pyyaml",
# ]
# ///

import os
import sys
import time
import datetime
from google import genai
from google.genai import types
import bq_connector
import config_loader
import calculation_engine
import evaluation_agent

# Load local environment variables from .env if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

def get_gemini_client():
    """Initializes the GenAI client using GEMINI_API_KEY from environment."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Warning: GEMINI_API_KEY environment variable is not set.")
    # Initialize client; will automatically pick up GEMINI_API_KEY
    return genai.Client()

def load_skill_instructions(skill_filename: str) -> str:
    """Reads the contents of the agent skill markdown instructions from directives/."""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    directives_dir = os.path.join(os.path.dirname(current_dir), "directives")
    skill_path = os.path.join(directives_dir, skill_filename)
    
    if not os.path.exists(skill_path):
        return ""
    with open(skill_path, "r", encoding="utf-8") as f:
        return f.read()

def call_gemini_with_retry(client, prompt: str, config=None, max_retries=3, delay=30):
    """Wrapper to call Gemini API with backoff to handle 429 Resource Exhausted quotas."""
    for attempt in range(max_retries):
        try:
            if config:
                return client.models.generate_content(
                    model='gemini-3.1-flash-lite',
                    contents=prompt,
                    config=config,
                )
            else:
                return client.models.generate_content(
                    model='gemini-3.1-flash-lite',
                    contents=prompt,
                )
        except Exception as e:
            if "429" in str(e) or "quota" in str(e).lower() or "resource_exhausted" in str(e).lower():
                if attempt < max_retries - 1:
                    print(f"   [API Rate Limit] Waiting {delay}s before retry ({attempt+1}/{max_retries})...")
                    time.sleep(delay)
                    continue
            raise e

def run_integrity_check(user_query: str, target_date: str = "20210131") -> dict:
    """Runs the IntegrityAgent step to assess data health."""
    instructions = load_skill_instructions("integrity_agent_skill.md")
    client = get_gemini_client()
    
    # 1. Fetch data quality sample from BigQuery
    sample_query = f"""
        SELECT 
          COUNT(1) as total_events,
          COUNTIF(event_name IS NULL) as null_events,
          COUNTIF(ecommerce.purchase_revenue_in_usd IS NULL AND event_name = 'purchase') as null_purchases_revenue
        FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`
        WHERE _TABLE_SUFFIX = '{target_date}'
    """
    
    try:
        results = bq_connector.execute_query(sample_query)
        data_stats = results[0] if results else {"total_events": 0, "null_events": 0, "null_purchases_revenue": 0}
    except Exception as e:
        return {"status": "FAIL", "reason": f"Failed to execute BQ health check query: {e}"}

    # 2. Let IntegrityAgent evaluate the stats
    prompt = f"""
    You are the IntegrityAgent (The Forensic Specialist).
    Your instructions:
    {instructions}
    
    We did a baseline health check on the dataset for date 2021-01-31. Here are the stats:
    - Total Events: {data_stats.get('total_events')}
    - Null Events: {data_stats.get('null_events')}
    - Null Purchase Revenue: {data_stats.get('null_purchases_revenue')}
    
    User Query Context: "{user_query}"
    
    Based on your instructions, output a JSON response with two keys:
    1. "status": "PASS" or "FAIL"
    2. "reason": A brief explanation of your decision.
    """
    
    try:
        response = call_gemini_with_retry(
            client=client,
            prompt=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
            )
        )
        import json
        return json.loads(response.text.strip())
    except Exception as e:
        return {"status": "FAIL", "reason": f"IntegrityAgent evaluation failed: {e}"}

def translate_intent_to_sql(user_query: str, start_date: str, end_date: str, history_context: str = "") -> str:
    """Runs the DataArchitectAgent step to generate BigQuery SQL."""
    instructions = load_skill_instructions("data_architect_agent_skill.md")
    client = get_gemini_client()
    
    history_section = ""
    if history_context and history_context != "No prior conversation context.":
        history_section = f"""
    CONVERSATION CONTEXT (prior turns in this session):
    {history_context}

    If the user's current question references prior results (e.g. 'now break that down', 'compare to that', 'those categories'), 
    use the above context to resolve what 'that' or 'those' refers to and write the SQL accordingly.
    """
    
    prompt = f"""    You are the DataArchitectAgent (The SQL Specialist).
    Your instructions:
    {instructions}
    {history_section}
    Translate the following user intent into a precise BigQuery SQL query targeting the GA4 ecommerce dataset:
    User Intent: "{user_query}"
    
    DEFAULT DATE RANGE: {start_date} to {end_date}. 
    CRITICAL: If the user explicitly requests a different time period (e.g., '92 days', 'entire time period', 'November'), you MUST adapt the `_TABLE_SUFFIX` logic accordingly (the GA4 public dataset covers 20201101 to 20210131). Otherwise, strictly use `_TABLE_SUFFIX BETWEEN '{start_date}' AND '{end_date}'`.
    
    Return ONLY the raw SQL code block. Do not include markdown formatting or explanations.
    """
    
    try:
        response = call_gemini_with_retry(client, prompt)
        return response.text.strip().replace("```sql", "").replace("```", "")
    except Exception as e:
        return f"-- Error generating SQL: {e}"

def self_heal_sql(failed_sql: str, error_message: str, user_query: str) -> str:
    """Invokes the DataArchitectAgent to self-heal a failed SQL query using the BQ error feedback."""
    instructions = load_skill_instructions("data_architect_agent_skill.md")
    client = get_gemini_client()
    
    prompt = f"""
    You are the DataArchitectAgent (The SQL Specialist).
    Your instructions:
    {instructions}
    
    A SQL query you generated failed validation in BigQuery.
    
    User Intent: "{user_query}"
    Failed SQL:
    ```sql
    {failed_sql}
    ```
    
    BigQuery Error Message:
    {error_message}
    
    Please correct the SQL query to resolve this error. Ensure all table names with hyphens or wildcards are correctly enclosed in backticks, e.g. `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`.
    Return ONLY the raw corrected SQL query. Do not include markdown code fences or explanations.
    """
    try:
        response = call_gemini_with_retry(client, prompt)
        return response.text.strip().replace("```sql", "").replace("```", "").strip()
    except Exception as e:
        return f"-- Self-healing failed to generate content: {e}"

def orchestrate_flow(user_query: str, target_date: str = "20210131", max_retries: int = 3, status_callback=None, conversation_history: list = None):
    """Orchestrates the full multi-agent flow: Integrity → SQL → Execution → Calculation."""
    if conversation_history is None:
        conversation_history = []
        
    def log(msg):
        print(msg)
        if status_callback:
            status_callback(msg)

    log(f"\n{'='*60}")
    log(f" ORCHESTRATOR — Full Flow")
    log(f" Query: {user_query}")
    log(f"{'='*60}\n")
    
    # Stage 2: Forensic Data Check
    log("[Stage 2: IntegrityAgent] Checking data trust...")
    integrity_result = run_integrity_check(user_query, target_date)
    log(f"Result: {integrity_result.get('status')} - {integrity_result.get('reason')}\n")
    
    if integrity_result.get("status") == "FAIL":
        print("Orchestration PAUSED: Data trust threshold not met.")
        return
        
    # Load config to determine date range before generating SQL
    try:
        master_data = config_loader.load_master_data()
    except FileNotFoundError as e:
        print(f"[FAIL] {e}")
        return

    # By default, use the entire dataset time period (92 days).
    start_date = "20201101"
    end_date = "20210131"
    
    # Simple regex fallback to detect "Jan 2021" overrides in prompt
    import re
    if re.search(r"jan(uary)?(\s+)?2021", user_query.lower()):
        start_date = "20210101"
        end_date = "20210131"
        
    start_dt = datetime.datetime.strptime(start_date, "%Y%m%d")
    end_dt = datetime.datetime.strptime(end_date, "%Y%m%d")

    # Build a readable conversation context string for agent prompts
    def format_history_for_prompt(history):
        if not history:
            return "No prior conversation context."
        lines = []
        for entry in history:
            if entry["role"] == "user":
                lines.append(f"User asked: {entry['content']}")
            elif entry["role"] == "assistant":
                if entry.get("sql"):
                    lines.append(f"SQL used: {entry['sql']}")
                if entry.get("data_summary"):
                    lines.append(f"Data snapshot (first 3 rows): {entry['data_summary']}")
                if entry.get("content"):
                    lines.append(f"Insight given: {entry['content'][:300]}")
        return "\n".join(lines)

    history_context = format_history_for_prompt(conversation_history)

    # Stage 3: SQL Translation + Self-Healing
    log("[Stage 3: DataArchitectAgent] Translating intent to BigQuery SQL...")
    generated_sql = translate_intent_to_sql(user_query, start_date, end_date, history_context=history_context)
    
    attempts = []
    is_valid = False
    sql_eval = {}
    
    for attempt in range(1, max_retries + 1):
        log(f"[Orchestrator] Validating SQL syntax & schema (Attempt {attempt}/{max_retries})...")
        syntax_valid, error_msg = bq_connector.validate_query(generated_sql)
        
        if not syntax_valid:
            log(f"[FAIL] Syntax error: {error_msg}")
            eval_flags = [f"SYNTAX_ERROR: {error_msg}"]
        else:
            # Score deterministic SQL rules (100 required)
            sql_eval = evaluation_agent.score_sql(generated_sql, user_query)
            eval_flags = sql_eval.get("flags", [])
            if sql_eval.get("score", 0) == 100:
                is_valid = True
                log("[OK] SQL passed deterministic evaluation (100/100)!")
                break
            else:
                log(f"[FAIL] Evaluation failed (Score {sql_eval.get('score')}): {eval_flags}")

        attempts.append(f"Attempt {attempt} failed:\nFlags: {eval_flags}\nSQL:\n{generated_sql}")
        
        if attempt < max_retries:
            log("[Orchestrator] Triggering autonomous self-healing loop...")
            generated_sql = self_heal_sql(generated_sql, "\n".join(eval_flags), user_query)
            
    if not is_valid:
        log("\n" + "=" * 60)
        log("[FAIL] SELF-HEALING DIAGNOSIS REPORT")
        log("=" * 60)
        log(f"Failed to generate a valid, compliant query after {max_retries} attempts.")
        log("Proceeding with pipeline paused for Human-In-The-Loop evaluation.")
        return {"status": "EVAL_FAIL", "flags": sql_eval.get("flags", ["SYNTAX_ERROR"])}
        
    log("\n--- Generated BigQuery SQL (HITL Audit) ---")
    log(generated_sql)
    log("-------------------------------------------\n")
    
    # Stage 3b: Execute the validated SQL
    log("[Stage 3b] Executing validated SQL against BigQuery...")
    try:
        query_results = bq_connector.execute_query(generated_sql)
        log(f"[OK] Query returned {len(query_results)} rows.")
    except Exception as e:
        log(f"[FAIL] Query execution failed: {e}")
        return {"status": "EVAL_FAIL", "flags": [f"EXECUTION_ERROR: {e}"]}
        
    # Process derived metrics using the deterministic calculation engine
    computed_metrics = {}
    import copy
    raw_data_for_eval = copy.deepcopy(query_results) if query_results else []
    
    if query_results:
        log("[Stage 3b] Computing deterministic funnel & financial metrics...")
        try:
            for row in query_results:
                row.update(calculation_engine.calculate_upper_funnel_metrics(row))
                row.update(calculation_engine.calculate_mid_funnel_metrics(row))
                row.update(calculation_engine.calculate_lower_funnel_metrics(row))
            # Keep a reference to the first row's metrics for the math sanity check
            computed_metrics = {k: query_results[0][k] for k in query_results[0] if k not in ["event_date", "channel", "medium", "source"]}
        except Exception as e:
            log(f"[WARN] Calculation engine failed (missing data?): {e}")

    # Evaluate Math Completeness and Sanity
    log("[Orchestrator] Evaluating Math Sanity...")
    math_eval = evaluation_agent.score_math(raw_data_for_eval, computed_metrics)
    if math_eval.get("score", 0) < 100:
        log(f"[FAIL] Math Sanity Evaluation failed: {math_eval.get('flags')}")
        return {"status": "EVAL_FAIL", "flags": math_eval.get("flags")}
    log(f"[OK] Math Sanity passed (100/100).")


    import json
    from google import genai
    import os
    
    # Initialize client for dynamic analysis
    client = genai.Client()

    # Dynamic Analysis (Concierge & Insights)
    log("[Stage 4: ConciergeAgent] Generating Dynamic Chart Configuration...")
    concierge_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "directives", "concierge_agent_skill.md")
    with open(concierge_dir, "r", encoding="utf-8") as f:
        concierge_sys = f.read()
        
    memory_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "visual_memory.json")
    visual_memory = []
    if os.path.exists(memory_path):
        try:
            with open(memory_path, "r", encoding="utf-8") as f:
                visual_memory = json.load(f).get("memory_bank", [])
        except:
            pass
    
    import chart_data_injector
    
    concierge_prompt = (
        f"User Intent: {user_query}\n"
        f"Data Shape Keys: {list(query_results[0].keys()) if query_results else []}\n"
        f"Computed Funnel/Financial Metrics:\n{json.dumps(computed_metrics, default=str)}\n\n"
        f"Visual Memory Bank (Past Queries & Chart Types):\n{json.dumps(visual_memory)}\n\n"
        "Return ONLY the raw JSON configuration for Chart.js. DO NOT include the 'data' or 'labels' arrays in the JSON. A downstream script will inject them based on the layout you define."
    )
    
    try:
        config = {'system_instruction': concierge_sys, 'response_mime_type': 'application/json'}
        resp = call_gemini_with_retry(client, concierge_prompt, config)
        chart_config = json.loads(resp.text)
        
        # Deterministically inject the raw data into the chart config
        chart_config = chart_data_injector.inject_chart_data(chart_config, query_results)
        
        # Evaluate Chart Consistency
        log("[Orchestrator] Evaluating Chart Consistency...")
        chart_eval = evaluation_agent.score_chart(chart_config, query_results, user_query)
        if chart_eval.get("score", 0) < 100:
            log(f"[WARN] Chart Consistency below 100: {chart_eval.get('flags')}")
        else:
            log("[OK] Chart Consistency passed (100/100).")
        
        # Save to memory bank to enforce future consistency
        chart_type = chart_config.get("type", chart_config.get("chart_type", "unknown"))
        visual_memory.append({"query_semantic_match": user_query, "layout_template": chart_type})
        if len(visual_memory) > 20:
            visual_memory = visual_memory[-20:] # Keep last 20 queries
        with open(memory_path, "w", encoding="utf-8") as f:
            json.dump({"memory_bank": visual_memory}, f, indent=4)
            
    except Exception as e:
        log(f"[FAIL] ConciergeAgent failed: {e}")
        chart_config = {}
        chart_eval = {"score": 0, "flags": [f"CONCIERGE_FAIL: {e}"]}

    log("[Stage 5: InsightsAgent] Generating Strategic Analyst Insights...")
    insights_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "directives", "insights_agent_skill.md")
    with open(insights_dir, "r", encoding="utf-8") as f:
        insights_sys = f.read()
    
    insights_prompt = (
        f"User Question: {user_query}\n"
        f"Raw SQL Data:\n{json.dumps(query_results, default=str)}\n"
        f"Computed Funnel/Financial Metrics:\n{json.dumps(computed_metrics, default=str)}\n\n"
        f"CONVERSATION CONTEXT:\n{history_context}\n\n"
        "Analyze this data based on the question and the context of the conversation. Write a concise, punchy recommendation in plain text (not JSON)."
    )
    try:
        resp = call_gemini_with_retry(client, insights_prompt, {'system_instruction': insights_sys})
        insights = resp.text.strip()
        
        # Evaluate Insight Quality
        log("[Orchestrator] Evaluating Insight Quality...")
        insight_eval = evaluation_agent.score_insight(insights, query_results, computed_metrics, history_context)
        if insight_eval.get("score", 0) < 85:
            log(f"[WARN] Insight Quality below 85: {insight_eval.get('flags')}")
        else:
            log(f"[OK] Insight Quality passed ({insight_eval.get('score')}/100).")
            
    except Exception as e:
        log(f"[FAIL] InsightsAgent failed: {e}")
        insights = "Analysis unavailable."
        insight_eval = {"score": 0, "flags": [f"INSIGHT_FAIL: {e}"]}

    # Build final report
    eval_report = evaluation_agent.build_eval_report(
        integrity_eval=integrity_result,
        sql_eval=sql_eval,
        math_eval=math_eval,
        chart_eval=chart_eval,
        insight_eval=insight_eval,
    )

    return {
        "status": "SUCCESS",
        "sql": generated_sql, 
        "raw_data": query_results, 
        "computed_metrics": computed_metrics,
        "chart_config": chart_config, 
        "insights": insights,
        "eval_report": eval_report,
    }

if __name__ == "__main__":
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
    else:
        query = "Which top-converting product categories generate the highest revenue?"
    orchestrate_flow(query)
