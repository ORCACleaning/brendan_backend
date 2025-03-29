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

# ✅ GPT-4 Property Mapping Prompt
GPT_PROMPT = """
You are an intelligent cleaning service assistant. Your task is to analyze a customer's message and extract relevant cleaning properties. Return a list of properties with their values in JSON format.

Here are the possible properties:
- balcony_cleaning (Yes/No)
- wall_cleaning (Yes/No)
- oven_cleaning (Yes/No)
- carpet_cleaning (Yes/No)
- window_v2 (Number of windows, integer)

Respond ONLY in this JSON format:
{
    "properties": [
        {"property": "balcony_cleaning", "value": "Yes"},
        {"property": "window_v2", "value": "5"}
    ]
}
"""

# ✅ GPT-4 API Call to Process Customer Message
def extract_properties_from_gpt4(message: str):
    try:
        response = openai.chat.completions.create(
            model="gpt-4-turbo",
            messages=[
                {"role": "system", "content": GPT_PROMPT},
                {"role": "user", "content": message}
            ]
        )
        gpt_result = response.choices[0].message.content
        return json.loads(gpt_result)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing message with GPT-4: {str(e)}")

# ✅ Main Route: Filter Response
@router.post("/filter-response", response_model=FilteredResponse)
async def filter_response(user_message: UserMessage):
    message = user_message.message

    # 🔥 Pass message to GPT-4 to extract properties
    gpt_result = extract_properties_from_gpt4(message)

    # ✅ Return extracted properties
    return {"properties": gpt_result["properties"]}
