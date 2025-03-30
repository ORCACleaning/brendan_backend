from openai import OpenAI
import os
import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

# ✅ Load API Key securely from environment
api_key = os.getenv("OPENAI_API_KEY")

# ✅ Initialize OpenAI client using Project API Key
client = OpenAI(api_key=api_key)

# ✅ Define request and response models
class UserMessage(BaseModel):
    message: str

class FilteredResponse(BaseModel):
    properties: list[dict]

# ✅ Updated GPT-4 Turbo Property Mapping Prompt
GPT_PROMPT = """
You are an intelligent cleaning service assistant named Brendan. Your task is to:
1. Analyze a customer's message and extract relevant cleaning properties.
2. If a customer mentions a range or is unsure about the number of windows (or similar), take the maximum number in the range.
3. If the message includes a question unrelated to property extraction, provide a natural, helpful response before continuing property extraction.

Here are the possible properties:
- balcony_cleaning (Yes/No)
- wall_cleaning (Yes/No)
- oven_cleaning (Yes/No)
- carpet_cleaning (Yes/No)
- window_v2 (Number of windows, integer)

### Response Format:
Always return a JSON response as follows:
{
    "properties": [
        {"property": "balcony_cleaning", "value": "Yes"},
        {"property": "window_v2", "value": "5"}
    ],
    "response": "Natural and relevant response to the customer’s query (if applicable)."
}
"""

# ✅ Updated GPT-4 Turbo API Call to Process Customer Message
def extract_properties_from_gpt4(message: str):
    try:
        print("🔥 [DEBUG] Received message from customer:", message)

        # ✅ Updated API call for project key
        response = client.chat.completions.create(
            model="gpt-4o",  # ✅ Use GPT-4o with project key
            messages=[
                {"role": "system", "content": GPT_PROMPT},
                {"role": "user", "content": message}
            ],
            max_tokens=200
        )

        print("🚀 [DEBUG] OpenAI API raw response:", response)

        # ✅ Extracting GPT response content
        gpt_result = response.choices[0].message.content
        print("🧠 [DEBUG] GPT-4o Response Content:", gpt_result)

        # ✅ Parse the JSON result from GPT-4o
        result_json = json.loads(gpt_result)

        # ✅ Handle follow-up responses
        extracted_properties = result_json.get("properties", [])
        follow_up_response = result_json.get("response", "")

        print("📊 [DEBUG] Extracted Properties:", extracted_properties)
        print("💬 [DEBUG] Follow-Up Response:", follow_up_response)

        return extracted_properties, follow_up_response
    except Exception as e:
        print("❌ [ERROR] Error processing message with GPT-4:", str(e))
        raise HTTPException(status_code=500, detail=f"Error processing message with GPT-4: {str(e)}")

# ✅ Updated Main Route: Filter Response with Follow-Up Handling
@router.post("/filter-response", response_model=FilteredResponse)
async def filter_response(user_message: UserMessage):
    message = user_message.message
    print("📩 [DEBUG] Incoming request message:", message)

    try:
        # 🔥 Pass message to GPT-4 Turbo to extract properties and get a follow-up response
        extracted_properties, follow_up_response = extract_properties_from_gpt4(message)

        # ✅ Return extracted properties and optional follow-up response
        return {
            "properties": extracted_properties,
            "response": follow_up_response if follow_up_response else "Got it! I'll update your preferences accordingly."
        }
    except Exception as e:
        print("❌ [ERROR] Error in /filter-response endpoint:", str(e))
        raise HTTPException(status_code=500, detail=f"Error processing request: {str(e)}")
