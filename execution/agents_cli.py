# /// script
# dependencies = [
#   "google-genai",
#   "google-cloud-bigquery",
#   "python-dotenv",
#   "pyyaml",
# ]
# ///

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import evaluation_agent

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_GOLDEN_TESTS_PATH = os.path.join(_ROOT, "config", "golden_tests.json")

def load_tests_for_agent(agent_name: str) -> list[dict]:
    with open(_GOLDEN_TESTS_PATH, "r", encoding="utf-8") as f:
        tests = json.load(f)
    if agent_name == "all":
        return tests
    return [t for t in tests if t.get("target_agent") == agent_name]

def get_real_agent_output(agent_name: str, query: str) -> str:
    if agent_name == "clarification":
        import clarification_agent
        return clarification_agent.generate_clarification(query)
    
    elif agent_name == "data_architect":
        import agent_orchestrator
        # Extract target date if mentioned in test
        if "2021" in query:
            start_dt = "20210101"
            end_dt = "20210131"
        else:
            start_dt = "20201101"
            end_dt = "20210131"
        return agent_orchestrator.translate_intent_to_sql(query, start_dt, end_dt)
        
    elif agent_name == "concierge":
        import agent_orchestrator
        import json
        from google import genai
        import os
        client = genai.Client()
        concierge_dir = os.path.join(_ROOT, "directives", "concierge_agent_skill.md")
        with open(concierge_dir, "r", encoding="utf-8") as f:
            concierge_sys = f.read()
        
        # We need mock data because it expects sql results.
        dummy_keys = ["event_date", "source", "total_purchases"] if "channel" in query.lower() else ["item_name", "item_revenue"]
        concierge_prompt = (
            f"User Intent: {query}\n"
            f"Data Shape Keys: {dummy_keys}\n"
            f"Computed Funnel/Financial Metrics: {{}}\n\n"
            f"Visual Memory Bank (Past Queries & Chart Types): {json.dumps([{'query_semantic_match': 'Breakdown products by revenue', 'layout_template': 'pie'}])}\n\n"
            "Return ONLY the raw JSON configuration for Chart.js. DO NOT include the 'data' or 'labels' arrays in the JSON. A downstream script will inject them based on the layout you define."
        )
        resp = agent_orchestrator.call_gemini_with_retry(client, concierge_prompt, {'system_instruction': concierge_sys, 'response_mime_type': 'application/json'})
        return resp.text
        
    elif agent_name == "insights":
        import agent_orchestrator
        import os
        import json
        from google import genai
        client = genai.Client()
        insights_dir = os.path.join(_ROOT, "directives", "insights_agent_skill.md")
        with open(insights_dir, "r", encoding="utf-8") as f:
            insights_sys = f.read()
        
        # Mock data based on query context to allow the insight agent to generate text
        dummy_data = []
        if "cart abandonment" in query.lower():
            dummy_data = [{"source": "google organic", "cart_abandonment_rate": "90%"}]
        elif "revenue" in query.lower():
            dummy_data = [
                {"channel": "Organic Search", "month": "2021-01", "revenue": 1500}, 
                {"channel": "Paid Social", "month": "2021-01", "revenue": 100}
            ]
        else:
            dummy_data = [{"total_purchases": 100}]
            
        insights_prompt = (
            f"User Question: {query}\n"
            f"Raw SQL Data: {json.dumps(dummy_data)}\n"
            f"Computed Funnel/Financial Metrics: {{}}\n\n"
            "Analyze this data based on the question and the context of the conversation. Write a concise, punchy recommendation in plain text (not JSON)."
        )
        resp = agent_orchestrator.call_gemini_with_retry(client, insights_prompt, {'system_instruction': insights_sys})
        return resp.text
        
    elif agent_name == "integrity":
        import agent_orchestrator
        target_date = "20210131"
        if "2020-11-01" in query:
            target_date = "20201101"
        elif "2022-01-01" in query:
            target_date = "20220101"
        
        result = agent_orchestrator.run_integrity_check(query, target_date)
        import json
        return json.dumps(result)
        
    return "Unknown Agent"

def run_reasoning_eval(agent_name: str, runs: int):
    tests = load_tests_for_agent(agent_name)
    if not tests:
        print(f"No tests found for agent: {agent_name}")
        return

    print(f"\n{'='*60}")
    print(f" AGENTS CLI: Reasoning Evaluator")
    print(f" Target: {agent_name.upper()} | Tests: {len(tests)} | Runs: {runs}")
    print(f"{'='*60}\n")

    import statistics
    
    all_scores = {}
    
    for test in tests:
        test_id = test["id"]
        print(f"--- Test: {test_id} ---")
        
        scores = []
        for i in range(1, runs + 1):
            print(f"  Run {i}/{runs}...")
            
            # GET REAL AGENT OUTPUT (with backoff for 429 errors on the agent itself)
            import time
            real_output = "Error"
            for attempt in range(5):
                try:
                    real_output = get_real_agent_output(test.get("target_agent", "unknown"), test["natural_language_query"])
                    break
                except Exception as e:
                    if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                        if attempt < 4:
                            sleep_time = (2 ** attempt) * 5 # 5s, 10s, 20s, 40s
                            print(f"    [Agent Rate Limit] Waiting {sleep_time}s before retry...")
                            time.sleep(sleep_time)
                            continue
                    print(f"    [Agent Failed]: {e}")
                    break
            
            result = evaluation_agent.score_agent_reasoning(
                agent_name=test.get("target_agent", "unknown"),
                agent_output=real_output,
                expected_trajectory=test["expected_trajectory"],
                expected_output=test["expected_output"]
            )
            
            score = result.get("score", 0)
            scores.append(score)
            
            print(f"    Score: {score}")
            if result.get("flags"):
                for flag in result["flags"]:
                    print(f"    FLAG: {flag}")
            
            # Add a larger delay to avoid hitting the free tier 15 RPM limit 
            # (Each loop makes 2 API calls: one for the agent, one for the Judge)
            time.sleep(10)
                    
        all_scores[test_id] = scores
        
    print(f"\n{'='*60}")
    print(f" REASONING STABILITY REPORT")
    print(f"{'='*60}")

    for test in tests:
        test_id = test["id"]
        scores = all_scores[test_id]
        avg = statistics.mean(scores)
        stdev = statistics.stdev(scores) if len(scores) > 1 else 0.0
        
        status = "STABLE" if stdev < 5 else "DRIFT_DETECTED"
        if avg < test.get("score_thresholds", {}).get("reasoning", 85):
            status = "BELOW_THRESHOLD"
            
        print(f"  [{test_id}]")
        print(f"    Avg: {avg:5.1f} | StDev: {stdev:4.1f} | Status: {status}")
        
    print(f"{'='*60}\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Agents CLI for Reasoning Evaluation")
    subparsers = parser.add_subparsers(dest="command")
    
    eval_parser = subparsers.add_parser("eval", help="Evaluation commands")
    eval_subparsers = eval_parser.add_subparsers(dest="subcommand")
    
    run_parser = eval_subparsers.add_parser("run", help="Run the reasoning evaluator")
    run_parser.add_argument("--agent", type=str, default="all", choices=["all", "clarification", "data_architect", "concierge", "insights", "integrity"])
    run_parser.add_argument("--runs", type=int, default=1, help="Number of times to run each test")
    
    args = parser.parse_args()
    
    if args.command == "eval" and args.subcommand == "run":
        run_reasoning_eval(args.agent, args.runs)
    else:
        parser.print_help()
