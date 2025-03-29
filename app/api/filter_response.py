import openai
import os
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

# ✅ Set up logging to the console for Render
logging.basicConfig(level=logging.INFO)

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
        # 🔥 Log message before sending it to GPT-4
        logging.info(f"Processing message: {message}")

        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": GPT_PROMPT},
                {"role": "user", "content": message}
            ]
        )
        result = response.choices[0].message.content


        # 🔥 Log the raw GPT-4 response
        logging.info(f"GPT-4 Response: {result}")

        return eval(result)  # Convert string response to JSON
    except Exception as e:
        logging.error(f"Error processing message: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error processing message with GPT-4: {str(e)}")

# ✅ Main Route: Filter Response
@router.post("/filter-response", response_model=FilteredResponse)
async def filter_response(user_message: UserMessage):
    message = user_message.message

    # 🔥 Pass message to GPT-4 to extract properties
    gpt_result = extract_properties_from_gpt4(message)

    # ✅ Return extracted properties
    logging.info(f"Extracted Properties: {gpt_result['properties']}")
    return {"properties": gpt_result["properties"]}
