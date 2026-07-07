# /// script
# dependencies = [
#   "google-genai",
#   "python-dotenv",
# ]
# ///
import os
from google import genai
from dotenv import load_dotenv

load_dotenv()
api_key = os.environ.get("GEMINI_API_KEY")
print(f"API Key loaded: {api_key[:5]}...{api_key[-5:]}" if api_key else "NO KEY")

try:
    client = genai.Client()
    # Test model 1
    try:
        response = client.models.generate_content(
            model='gemini-3.1-flash-lite',
            contents='Hello'
        )
        print("SUCCESS gemini-3.1-flash-lite")
    except Exception as e:
        print(f"FAILED gemini-3.1-flash-lite: {e}")

    # Test model 2
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents='Hello'
        )
        print("SUCCESS gemini-2.5-flash")
    except Exception as e:
        print(f"FAILED gemini-2.5-flash: {e}")

except Exception as e:
    print(f"ERROR: {e}")
