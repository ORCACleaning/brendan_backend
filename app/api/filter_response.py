from openai import OpenAI
import os
import json
import requests
import uuid
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

# ✅ Load .env variables
load_dotenv()

router = APIRouter()

# ✅ API Keys
api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=api_key)

AIRTABLE_API_KEY = os.getenv("AIRTABLE_API_KEY")
AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID")
TABLE_NAME = "Vacate Quotes"

# ✅ Required fields to complete quote
REQUIRED_FIELDS = [
    "suburb", "bedrooms_v2", "bathrooms_v2",
    "furnished", "oven_cleaning", "carpet_cleaning"
]

# ✅ GPT Prompt
GPT_PROMPT = """
You are Brendan, an Aussie vacate cleaning assistant for Orca Cleaning. Your job is to:
1. Extract useful cleaning-related properties from the customer's message.
2. If the customer mentions a range (e.g., "3–4 bedrooms"), use the higher value.
3. If they say something vague (like "a few windows"), default to the closest reasonable number.
4. If they mention any special requests (e.g. "clean behind fridge", "extra deep shower scrub"), include it as special_requests.
5. Reply in a casual, friendly Aussie tone that continues the conversation without repeating greetings like "G'day" every time.

Extract the following properties **only if they are mentioned**:
- suburb (Text)
- bedrooms_v2 (Integer)
- bathrooms_v2 (Integer)
- furnished (Yes/No)
- oven_cleaning (Yes/No)
- carpet_cleaning (Yes/No)
- deep_cleaning (Yes/No)
- wall_cleaning (Yes/No)
- fridge_cleaning (Yes/No)
- garage_cleaning (Yes/No)
- window_tracks (Yes/No)
- windows_v2 (Integer)
- balcony_cleaning (Yes/No)
- range_hood_cleaning (Yes/No)
- special_requests (Text)
- user_message (Text)

Respond using this JSON format:
{
  "properties": [
    {"property": "suburb", "value": "Perth"},
    {"property": "bedrooms_v2", "value": "3"},
    {"property": "oven_cleaning", "value": "Yes"}
  ],
  "response": "Got it mate, sounds like a standard 3x1 — I’ll pop that in!"
}
"""

# ✅ Airtable utilities
def get_quote_by_session(session_id):
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{TABLE_NAME}"
    headers = {"Authorization": f"Bearer {AIRTABLE_API_KEY}"}
    params = {"filterByFormula": f"{{session_id}}='{session_id}'"}
    res = requests.get(url, headers=headers, params=params)
    data = res.json()
    if data.get("records"):
        record = data["records"][0]
        return {
            "record_id": record["id"],
            "fields": record["fields"],
            "stage": record["fields"].get("quote_stage", "Gathering Info"),
            "quote_id": record["fields"].get("quote_id")
        }
    return None

def create_new_quote(session_id):
    quote_id = f"VAC-{uuid.uuid4().hex[:8]}"
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{TABLE_NAME}"
    headers = {
        "Authorization": f"Bearer {AIRTABLE_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "fields": {
            "session_id": session_id,
            "quote_id": quote_id
        }
    }
    res = requests.post(url, headers=headers, json=data)
    record = res.json().get("id")
    return quote_id, record

def update_quote_record(record_id, fields):
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{TABLE_NAME}/{record_id}"
    headers = {
        "Authorization": f"Bearer {AIRTABLE_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {"fields": fields}
    requests.patch(url, headers=headers, json=data)

def extract_properties_from_gpt4(message: str):
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": GPT_PROMPT},
            {"role": "user", "content": message}
        ],
        max_tokens=300
    )
    content = response.choices[0].message.content.strip()
    content = content.replace("```json", "").replace("```", "").strip()
    result_json = json.loads(content)
    return result_json.get("properties", []), result_json.get("response", "")

def generate_next_actions():
    return [
        {"action": "proceed_booking", "label": "Proceed to Booking"},
        {"action": "download_pdf", "label": "Download PDF Quote"},
        {"action": "email_pdf", "label": "Email PDF Quote"},
        {"action": "ask_questions", "label": "Ask Questions or Change Parameters"}
    ]

@router.post("/filter-response")
async def filter_response_entry(request: Request):
    try:
        body = await request.json()
        message = body.get("message", "")
        session_id = body.get("session_id")

        if not session_id:
            raise HTTPException(status_code=400, detail="Session ID is required.")

        quote_data = get_quote_by_session(session_id)

        if not quote_data:
            quote_id, record_id = create_new_quote(session_id)
            fields = {}
            stage = "Gathering Info"
        else:
            quote_id = quote_data["quote_id"]
            record_id = quote_data["record_id"]
            fields = quote_data["fields"]
            stage = quote_data["stage"]

        props, reply = extract_properties_from_gpt4(message)
        updates = {p["property"]: p["value"] for p in props}

        # Avoid updating restricted select fields like 'quote_stage' if values are not in list
        update_quote_record(record_id, updates)

        # Merge known fields with new ones for validation
        combined = {**fields, **updates}
        missing = [field for field in REQUIRED_FIELDS if field not in combined]

        if not missing:
            update_quote_record(record_id, {"quote_stage": "step_5_quote_summary", "status": "quote_ready"})
            return JSONResponse(
                content={
                    "properties": props,
                    "response": "Thanks heaps! I’ve got what I need to whip up your quote — one sec…",
                    "next_actions": []
                }
            )

        return JSONResponse(
            content={
                "properties": props,
                "response": reply or "Got that! Anything else you’d like us to know?",
                "next_actions": []
            }
        )

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
