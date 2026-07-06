# /// script
# dependencies = [
#   "google-genai",
#   "google-cloud-bigquery",
#   "python-dotenv",
#   "pyyaml",
# ]
# ///

"""
Evaluation Runner — Regression Test Harness (On-Demand CLI).

Usage:
    uv run execution/evaluation_runner.py --runs 5

Runs each golden test case N times, records scores, and reports stability.
"""

import argparse
import json
import os
import sys
import statistics

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import agent_orchestrator
import evaluation_agent


_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_GOLDEN_TESTS_PATH = os.path.join(_ROOT, "config", "golden_tests.json")
_EVAL_LOG_PATH = os.path.join(_ROOT, "config", "eval_log.jsonl")


def load_golden_tests() -> list[dict]:
    """Load canonical test cases from golden_tests.json."""
    with open(_GOLDEN_TESTS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def run_single_test(test_case: dict) -> dict:
    """Run a single golden test and return the evaluation scores."""
    query = test_case["natural_language_query"]
    print(f"  Running query: '{query}'")

    # Execute the full pipeline (silently)
    result = agent_orchestrator.orchestrate_flow(query, status_callback=lambda m: None)

    if not result:
        return {
            "test_id": test_case["id"],
            "sql_score": 0, "math_score": 0, "chart_score": 0, "insight_score": 0,
            "flags": ["PIPELINE_FAILED"],
        }

    # Score SQL
    sql_eval = evaluation_agent.score_sql(result.get("sql", ""), query)

    # Check semantic assertions from the golden test
    semantic = test_case.get("semantic_assertions", {})
    sql_text = result.get("sql", "").lower()
    assertion_flags = []

    for kw in semantic.get("required_sql_keywords", []):
        if kw.lower() not in sql_text:
            assertion_flags.append(f"SEMANTIC_MISS: expected keyword '{kw}' in SQL")

    for kw in semantic.get("forbidden_sql_keywords", []):
        if kw and kw.lower() in sql_text:
            assertion_flags.append(f"SEMANTIC_VIOLATION: found forbidden '{kw}' in SQL")

    # Check output columns via dry-run
    output_cols, _ = evaluation_agent.bq_connector.dry_run_schema(result.get("sql", ""))
    output_cols_lower = {c.lower() for c in output_cols}
    for expected_col in semantic.get("required_columns_in_select", []):
        if expected_col.lower() not in output_cols_lower:
            assertion_flags.append(f"COLUMN_MISSING: expected '{expected_col}' in SELECT output")

    # Score Math
    math_eval = evaluation_agent.score_math(result.get("raw_data", []))

    # Score Chart
    chart_eval = evaluation_agent.score_chart(
        result.get("chart_config", {}),
        result.get("raw_data", []),
        query,
    )

    # Check expected chart type from golden test
    expected_chart = test_case.get("expected_chart_type", "")
    actual_chart = result.get("chart_config", {}).get("type", "")
    if expected_chart and actual_chart.lower() != expected_chart.lower():
        assertion_flags.append(
            f"CHART_TYPE_MISMATCH: expected '{expected_chart}', got '{actual_chart}'"
        )

    # Check minimum rows
    expected_min = test_case.get("expected_min_rows", 0)
    actual_rows = len(result.get("raw_data", []))
    if actual_rows < expected_min:
        assertion_flags.append(
            f"ROW_COUNT_LOW: expected >= {expected_min} rows, got {actual_rows}"
        )

    # Score Insight
    insight_eval = evaluation_agent.score_insight(
        result.get("insights", ""),
        result.get("raw_data", []),
    )

    all_flags = sql_eval.get("flags", []) + math_eval.get("flags", []) + \
                chart_eval.get("flags", []) + insight_eval.get("flags", []) + assertion_flags

    scores = {
        "test_id": test_case["id"],
        "sql_score": sql_eval["score"],
        "math_score": math_eval["score"],
        "chart_score": chart_eval["score"],
        "insight_score": insight_eval["score"],
        "assertion_flags": assertion_flags,
        "all_flags": all_flags,
    }

    # Append to eval log
    evaluation_agent._append_eval_log(scores)
    return scores


def run_golden_tests(n_runs: int = 5):
    """Run all golden tests N times and produce a stability report."""
    tests = load_golden_tests()
    print(f"\n{'='*60}")
    print(f" EVALUATION RUNNER — Regression Backtester")
    print(f" Running {len(tests)} golden tests x {n_runs} runs each")
    print(f"{'='*60}\n")

    all_results = {}  # test_id -> [list of score dicts]

    for test in tests:
        test_id = test["id"]
        all_results[test_id] = []
        print(f"\n--- Test: {test_id} ---")

        for run in range(1, n_runs + 1):
            print(f"  Run {run}/{n_runs}...")
            scores = run_single_test(test)
            all_results[test_id].append(scores)
            print(f"    SQL={scores['sql_score']} Math={scores['math_score']} "
                  f"Chart={scores['chart_score']} Insight={scores['insight_score']}")
            if scores.get("assertion_flags"):
                for flag in scores["assertion_flags"]:
                    print(f"    WARNING: {flag}")

    # --- Stability Report ---
    print(f"\n{'='*60}")
    print(f" STABILITY REPORT")
    print(f"{'='*60}")

    any_drift = False
    any_below_threshold = False

    for test in tests:
        test_id = test["id"]
        thresholds = test.get("score_thresholds", {})
        runs = all_results[test_id]

        print(f"\n  [{test_id}]")

        for metric_key, metric_label in [
            ("sql_score", "SQL"),
            ("math_score", "Math"),
            ("chart_score", "Chart"),
            ("insight_score", "Insight"),
        ]:
            values = [r[metric_key] for r in runs]
            avg = statistics.mean(values)
            stdev = statistics.stdev(values) if len(values) > 1 else 0.0
            min_v = min(values)
            max_v = max(values)
            spread = max_v - min_v

            # Get threshold for this metric
            threshold_key = metric_key.replace("_score", "")
            if threshold_key == "math":
                threshold_key = "math_sanity"
            threshold = thresholds.get(threshold_key, 0)

            status = "STABLE"
            if spread > 5:
                status = "DRIFT_DETECTED"
                any_drift = True
            if avg < threshold:
                status = "BELOW_THRESHOLD"
                any_below_threshold = True

            print(f"    {metric_label:8s}: avg={avg:5.1f}  min={min_v:3d}  max={max_v:3d}  "
                  f"stdev={stdev:4.1f}  threshold={threshold:3d}  {status}")

    print(f"\n{'='*60}")
    if any_drift:
        print(" WARNING: DRIFT DETECTED — Score variance exceeds ±5 points across runs.")
        print("    This suggests prompt drift, model version changes, or schema issues.")
    elif any_below_threshold:
        print(" FAILED: THRESHOLD VIOLATIONS — Some scores fell below required minimums.")
    else:
        print(" PASSED: ALL TESTS STABLE — Identical inputs produce consistent scores.")
    print(f"{'='*60}\n")

    # Return exit code for CI/CD
    return 1 if (any_drift or any_below_threshold) else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run evaluation regression tests.")
    parser.add_argument("--runs", type=int, default=5,
                        help="Number of times to run each golden test (default: 5)")
    args = parser.parse_args()

    exit_code = run_golden_tests(n_runs=args.runs)
    sys.exit(exit_code)
