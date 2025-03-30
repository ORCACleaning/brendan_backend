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
You are Brendan, an AI cleaning assistant. Your task is to:
- Analyze customer messages and extract relevant properties.
- Select the maximum value if a range is mentioned (e.g., windows).
- Respond naturally if a question unrelated to property extraction is asked.

### Extractable Properties:
- balcony_cleaning (Yes/No): Clean balcony.
- bathrooms_v2 (Integer): Number of bathrooms.
- bedrooms_v2 (Integer): Number of bedrooms.
- carpet_cleaning (Yes/No): Clean carpets.
- fridge_cleaning (Yes/No): Clean fridge.
- furnished (Yes/No): Is the property furnished?
- garage_cleaning (Yes/No): Clean garage.
- oven_cleaning (Yes/No): Clean oven.
- range_hood_cleaning (Yes/No): Clean range hood.
- special_requests (Text): Additional customer requests.
- suburb (Text): Customer’s suburb.
- user_message (Text): Original message.
- wall_cleaning (Yes/No): Clean walls.
- window_tracks (Yes/No): Clean window tracks.
- deep_cleaning (Yes/No): Deep cleaning required.
- windows_v2 (Integer): Number of windows.

### Response Format:
Return a JSON with:
{
  "properties": [
    {"property": "balcony_cleaning", "value": "Yes"},
    {"property": "bathrooms_v2", "value": "2"},
    {"property": "bedrooms_v2", "value": "3"},
    {"property": "carpet_cleaning", "value": "No"},
    {"property": "fridge_cleaning", "value": "Yes"},
    {"property": "furnished", "value": "No"},
    {"property": "garage_cleaning", "value": "No"},
    {"property": "oven_cleaning", "value": "Yes"},
    {"property": "range_hood_cleaning", "value": "No"},
    {"property": "special_requests", "value": "Clean behind the fridge."},
    {"property": "suburb", "value": "Perth"},
    {"property": "user_message", "value": "We have 3 bedrooms and want a deep clean."},
    {"property": "wall_cleaning", "value": "No"},
    {"property": "window_tracks", "value": "Yes"},
    {"property": "deep_cleaning", "value": "Yes"},
    {"property": "windows_v2", "value": "5"}
  ],
  "response": "Natural response if needed, otherwise an empty string."
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

        # ✅ Remove surrounding backticks and json keyword if present
        if gpt_result.startswith("```json"):
            gpt_result = gpt_result[7:-3].strip()
        elif gpt_result.startswith("```"):
            gpt_result = gpt_result[3:-3].strip()

        # ✅ Parse the JSON result from GPT-4o
        try:
            result_json = json.loads(gpt_result)
            print("✅ [DEBUG] Parsed JSON Successfully:", result_json)
        except json.JSONDecodeError as e:
            print("❌ [ERROR] JSON Parsing Failed:", str(e))
            raise HTTPException(status_code=500, detail=f"Error parsing GPT-4 response: {str(e)}")

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
