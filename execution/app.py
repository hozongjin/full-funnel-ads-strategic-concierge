# /// script
# dependencies = [
#   "flask",
#   "google-genai",
#   "google-cloud-bigquery",
#   "python-dotenv",
#   "pyyaml",
# ]
# ///

import os
import sys
import json
from flask import Flask, render_template, request, jsonify
from queue import Queue
from threading import Thread
from flask import Response

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from execution import agent_orchestrator
import execution.clarification_agent as clarification_agent
from execution.dashboard_api import get_dashboard_data
from execution.bq_connector import execute_query

app = Flask(__name__)

# Server-side conversation memory: { session_id: [history entries] }
conversation_store = {}
# Session states: { session_id: {"status": "PENDING_CLARIFICATION", "proposed_intent": "..."} }
session_states = {}
MAX_HISTORY = 5  # Number of prior turns to inject into prompts

@app.route("/")
def index():
    """Render the Dynamic Analyst Chat Interface."""
    return render_template("index.html")

@app.route("/api/dashboard", methods=["GET"])
def dashboard():
    """Fetches full-funnel dashboard data for the requested period (days) and optional countries."""
    period = int(request.args.get("period", 30))
    countries_param = request.args.get("countries", "")
    countries = [c.strip() for c in countries_param.split(",")] if countries_param else None

    try:
        data = get_dashboard_data(period, countries)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/countries", methods=["GET"])
def get_countries():
    """Fetches all distinct countries from the dataset."""
    try:
        sql = """
        SELECT DISTINCT geo.country 
        FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*` 
        WHERE _TABLE_SUFFIX BETWEEN '20210101' AND '20210131'
          AND geo.country IS NOT NULL
          AND geo.country != '(not set)'
          AND geo.country != ''
        ORDER BY geo.country ASC
        """
        rows = execute_query(sql)
        countries = [row['country'] for row in rows]
        return jsonify(countries)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/chat", methods=["POST"])
def chat():
    """Takes a user prompt and streams status updates and the final result using SSE."""
    data = request.json
    query = data.get("query", "")
    session_id = data.get("session_id", "default")
    
    if not query:
        return jsonify({"status": "error", "message": "Query cannot be empty."}), 400

    history = conversation_store.get(session_id, [])
    state = session_states.get(session_id, {"status": "READY"})
    
    q = Queue()
    
    def status_callback(msg):
        q.put({"type": "status", "message": msg})
        
    def run_worker():
        try:
            # Check if we are currently waiting for user confirmation
            if state["status"] == "PENDING_CLARIFICATION":
                if query.lower().strip() in ["yes", "y", "looks good", "correct", "proceed"]:
                    # User approved! Pass the clarified intent to the orchestrator.
                    status_callback("User approved clarification. Proceeding to Data Architect...")
                    session_states[session_id] = {"status": "READY"}
                    
                    # Pass the approved intent to the orchestrator instead of the "yes" query
                    approved_intent = state.get("proposed_intent", "")
                    # Add "Execute this exact approved plan" prefix so the orchestrator knows what to do
                    orchestrator_query = f"Execute this exact approved plan:\n{approved_intent}"
                    
                    result = agent_orchestrator.orchestrate_flow(
                        orchestrator_query,
                        status_callback=status_callback,
                        conversation_history=history[-MAX_HISTORY:]
                    )
                    
                    if result:
                        if result.get("status") == "EVAL_FAIL":
                            q.put({"type": "eval_warning", "data": result})
                        else:
                            # Update conversation memory
                            history.append({"role": "user", "content": "Approved intent."})
                            history.append({
                                "role": "assistant",
                                "content": result.get("insights", ""),
                                "sql": result.get("sql", ""),
                                "data_summary": str(result.get("raw_data", [])[:3])
                            })
                            conversation_store[session_id] = history
                            q.put({"type": "result", "data": result})
                    else:
                        q.put({"type": "error", "message": "Pipeline failed to generate a result."})
                else:
                    # User provided a correction instead of "yes"
                    status_callback("Processing user feedback and re-clarifying...")
                    
                    # Format history for clarification context
                    history_str = "\n".join([f"{h['role'].capitalize()}: {h['content']}" for h in history[-MAX_HISTORY:]])
                    history_str += f"\nPrevious Proposal: {state.get('proposed_intent')}\nUser Feedback: {query}"
                    
                    clarified_response = clarification_agent.generate_clarification(query, history_str)
                    
                    # Update state with new proposal
                    session_states[session_id] = {
                        "status": "PENDING_CLARIFICATION",
                        "proposed_intent": clarified_response
                    }
                    
                    q.put({"type": "clarification", "data": clarified_response})
                    
            else:
                # Normal mode: Hit the ClarificationAgent first
                status_callback("Analyzing request and defining exact data parameters...")
                
                history_str = "\n".join([f"{h['role'].capitalize()}: {h['content']}" for h in history[-MAX_HISTORY:]])
                clarified_response = clarification_agent.generate_clarification(query, history_str)
                
                # Enter pending state
                session_states[session_id] = {
                    "status": "PENDING_CLARIFICATION",
                    "proposed_intent": clarified_response
                }
                
                # Append user query to history now so it's tracked
                history.append({"role": "user", "content": query})
                conversation_store[session_id] = history
                
                q.put({"type": "clarification", "data": clarified_response})
                
        except Exception as e:
            q.put({"type": "error", "message": str(e)})
            
    Thread(target=run_worker).start()
    
    def generate():
        while True:
            item = q.get()
            yield f"data: {json.dumps(item, default=str)}\n\n"
            if item["type"] in ["result", "error", "clarification"]:
                break
                
    return Response(generate(), mimetype="text/event-stream")

if __name__ == "__main__":
    app.run(debug=True, port=5000)
