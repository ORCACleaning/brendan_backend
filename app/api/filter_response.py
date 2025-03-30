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
    response: str


# ✅ Updated GPT-4 Turbo Property Mapping Prompt
GPT_PROMPT = """
You are Brendan, an Aussie vacate cleaning assistant for Orca Cleaning. Your task is to:
1. Analyze the customer's message and identify relevant cleaning properties.
2. If a customer mentions a range or is unsure about a quantity (e.g., number of windows), take the maximum value.
3. If the customer asks something unrelated, provide a natural and helpful response.

### Extractable Properties:
- balcony_cleaning (Yes/No)
- bathrooms_v2 (Integer)
- bedrooms_v2 (Integer)
- carpet_cleaning (Yes/No)
- fridge_cleaning (Yes/No)
- furnished (Yes/No)
- garage_cleaning (Yes/No)
- oven_cleaning (Yes/No)
- range_hood_cleaning (Yes/No)
- special_requests (Text)
- suburb (Text)
- user_message (Text)
- wall_cleaning (Yes/No)
- window_tracks (Yes/No)
- deep_cleaning (Yes/No)
- windows_v2 (Integer)

### Response Format:
Return a JSON with the following structure:
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

# ✅ Required properties for completing the loop
REQUIRED_PROPERTIES = [
    "suburb",
    "bedrooms_v2",
    "bathrooms_v2",
    "oven_cleaning",
    "carpet_cleaning",
    "furnished",
    "special_requests"
]


# ✅ GPT-4 API Call to Process Customer Message
def extract_properties_from_gpt4(message: str):
    try:
        print("🔥 [DEBUG] Received message from customer:", message)

        # ✅ API call to GPT-4 to extract properties
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": GPT_PROMPT},
                {"role": "user", "content": message}
            ],
            max_tokens=300
        )

        print("🚀 [DEBUG] OpenAI API raw response:", response)

        # ✅ Extracting GPT response content
        gpt_result = response.choices[0].message.content.strip()

        # ✅ Clean response (remove backticks if present)
        if gpt_result.startswith("```json"):
            gpt_result = gpt_result[7:-3].strip()
        elif gpt_result.startswith("```"):
            gpt_result = gpt_result[3:-3].strip()

        # ✅ Parse JSON from GPT-4
        try:
            result_json = json.loads(gpt_result)
            print("✅ [DEBUG] Parsed JSON Successfully:", result_json)
        except json.JSONDecodeError as e:
            print("❌ [ERROR] JSON Parsing Failed:", str(e))
            raise HTTPException(status_code=500, detail=f"Error parsing GPT-4 response: {str(e)}")

        # ✅ Extract properties and follow-up response
        extracted_properties = result_json.get("properties", [])
        follow_up_response = result_json.get("response", "")

        print("📊 [DEBUG] Extracted Properties:", extracted_properties)
        print("💬 [DEBUG] Follow-Up Response:", follow_up_response)

        return extracted_properties, follow_up_response
    except Exception as e:
        print("❌ [ERROR] Error processing message with GPT-4:", str(e))
        raise HTTPException(status_code=500, detail=f"Error processing message with GPT-4: {str(e)}")


# ✅ Check if all required properties are collected
def check_properties(properties):
    collected_properties = {prop["property"] for prop in properties}
    missing_properties = [prop for prop in REQUIRED_PROPERTIES if prop not in collected_properties]

    if not missing_properties:
        return "PROPERTY_DATA_COMPLETE", ""

    # ✅ Generate a follow-up question dynamically
    follow_up_question = generate_followup_question(missing_properties)
    return "ASK_FOLLOWUP", follow_up_question


# ✅ Generate a dynamic follow-up question for missing properties
def generate_followup_question(missing_properties):
    if len(missing_properties) == 1:
        question = f"Just one more thing! Can you tell me about {missing_properties[0].replace('_v2', '').replace('_', ' ')}?"
    else:
        question = f"We’re almost there! Could you also tell me about {', '.join(missing_properties[:-1])} and {missing_properties[-1]}?"

    return question


# ✅ Updated Main Route: Filter Response with Follow-Up Handling
@router.post("/filter-response", response_model=FilteredResponse)
async def filter_response(user_message: UserMessage):
    message = user_message.message
    print("📩 [DEBUG] Incoming request message:", message)

    try:
        # ✅ Extract properties and check for completeness
        extracted_properties, follow_up_response = extract_properties_from_gpt4(message)
        status, follow_up_question = check_properties(extracted_properties)

        if status == "PROPERTY_DATA_COMPLETE":
            return {
                "properties": extracted_properties,
                "response": "PROPERTY_DATA_COMPLETE"
            }
        else:
            return {
                "properties": extracted_properties,
                "response": follow_up_question
            }
    except Exception as e:
        print("❌ [ERROR] Error processing request:", str(e))
        raise HTTPException(status_code=500, detail=f"Error processing request: {str(e)}")
