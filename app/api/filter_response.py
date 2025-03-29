import openai
import os
import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

# ✅ Load API Key from environment
openai.api_key = os.getenv("OPENAI_API_KEY")

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
        response = openai.ChatCompletion.create(
            model="gpt-4-turbo",  # 🔥 Use GPT-4 Turbo for lower cost and faster responses
            messages=[
                {"role": "system", "content": GPT_PROMPT},
                {"role": "user", "content": message}
            ]
        )
        gpt_result = response.choices[0].message.content
        result_json = json.loads(gpt_result)
        
        # ✅ Handle follow-up responses
        extracted_properties = result_json.get("properties", [])
        follow_up_response = result_json.get("response", "")

        return extracted_properties, follow_up_response
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing message with GPT-4: {str(e)}")


# ✅ Updated Main Route: Filter Response with Follow-Up Handling
@router.post("/filter-response", response_model=FilteredResponse)
async def filter_response(user_message: UserMessage):
    message = user_message.message

    # 🔥 Pass message to GPT-4 Turbo to extract properties and get a follow-up response
    extracted_properties, follow_up_response = extract_properties_from_gpt4(message)

    # ✅ Return extracted properties and optional follow-up response
    return {
        "properties": extracted_properties,
        "response": follow_up_response if follow_up_response else "Got it! I'll update your preferences accordingly."
    }

