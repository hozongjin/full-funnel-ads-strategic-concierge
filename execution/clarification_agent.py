import os
import json
from google import genai
from google.genai import types

def generate_clarification(user_query: str, history_context: str = "") -> str:
    """Uses the LLM to clarify user intent against the GA4 schema before generating SQL."""
    
    # Load the directive
    directive_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "directives", "clarification_agent_skill.md")
    with open(directive_path, "r", encoding="utf-8") as f:
        directive = f.read()

    # Load the GA4 data dictionary
    dict_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ga4_data_dictionary.md")
    try:
        with open(dict_path, "r", encoding="utf-8") as f:
            data_dict = f.read()
    except Exception:
        data_dict = "Data dictionary not found."

    system_prompt = (
        f"{directive}\n\n"
        f"--- GA4 DATA DICTIONARY ---\n"
        f"{data_dict}\n\n"
        f"--- CONVERSATION HISTORY ---\n"
        f"{history_context}\n"
    )

    client = genai.Client()
    response = client.models.generate_content(
        model='gemini-3.1-flash-lite',
        contents=user_query,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=0.4,
        ),
    )
    
    return response.text
