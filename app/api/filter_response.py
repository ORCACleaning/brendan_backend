from openai import OpenAI
import os
import json
import requests
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

# ✅ Load API Key securely
api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=api_key)

# ✅ Airtable Config
AIRTABLE_API_KEY = os.getenv("AIRTABLE_API_KEY")
AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID")
TABLE_NAME = "Vacate Quotes"

# ✅ Request/Response Models
class TidioPayload(BaseModel):
    message: str
    quote_id: str

class FilteredResponse(BaseModel):
    properties: list[dict]
    response: str
    next_actions: list[dict]

# ✅ Airtable Fetch Helper
def get_quote_record(quote_id):
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{TABLE_NAME}"
    headers = {
        "Authorization": f"Bearer {AIRTABLE_API_KEY}"
    }
    params = {
        "filterByFormula": f"{{quote_id}}='{quote_id}'"
    }

    res = requests.get(url, headers=headers, params=params)
    data = res.json()

    if data.get("records"):
        record = data["records"][0]
        return {
            "record_id": record["id"],
            "fields": record["fields"],
            "stage": record["fields"].get("quote_stage", "Gathering Info"),
        }
    return None

# ✅ Update Quote Record in Airtable
def update_quote_record(record_id, fields):
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{TABLE_NAME}/{record_id}"
    headers = {
        "Authorization": f"Bearer {AIRTABLE_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "fields": fields
    }
    requests.patch(url, headers=headers, json=data)

# ✅ OpenAI Property Extractor
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

    # Clean & Parse
    if content.startswith("```json"):
        content = content.replace("```json", "").replace("```", "").strip()
    elif content.startswith("```"):
        content = content.replace("```", "").strip()

    result_json = json.loads(content)
    properties = result_json.get("properties", [])
    follow_up = result_json.get("response", "")
    return properties, follow_up

# ✅ Dynamic Next Actions
def generate_next_actions():
    return [
        {"action": "proceed_booking", "label": "Proceed to Booking"},
        {"action": "download_pdf", "label": "Download PDF Quote"},
        {"action": "email_pdf", "label": "Email PDF Quote"},
        {"action": "ask_questions", "label": "Ask Questions or Change Parameters"}
    ]

# ✅ Main Route
@router.post("/filter-response", response_model=FilteredResponse)
async def filter_response(payload: TidioPayload):
    message = payload.message
    quote_id = payload.quote_id

    quote_data = get_quote_record(quote_id)
    if not quote_data:
        raise HTTPException(status_code=404, detail="Quote ID not found.")

    stage = quote_data["stage"]
    record_id = quote_data["record_id"]
    existing_fields = quote_data["fields"]

    # ✅ Stage 1: Gathering Info
    if stage == "Gathering Info":
        props, follow_up = extract_properties_from_gpt4(message)

        # Update each extracted property
        update_fields = {prop["property"]: prop["value"] for prop in props}
        update_fields["quote_stage"] = "Gathering Info"  # Keep stage until fully gathered
        update_quote_record(record_id, update_fields)

        # Determine if all required fields are now present
        required = ["suburb", "bedrooms_v2", "bathrooms_v2", "oven_cleaning", "carpet_cleaning", "furnished"]
        if all(field in {**existing_fields, **update_fields} for field in required):
            update_quote_record(record_id, {"quote_stage": "Quote Calculated", "status": "quote_ready"})
            return {
                "properties": props,
                "response": "Thanks! I’ve got everything I need to calculate your quote. One sec…",
                "next_actions": []
            }

        return {
            "properties": props,
            "response": follow_up or "Got that! Anything else you'd like us to know?",
            "next_actions": []
        }

    # ✅ Stage 2: Quote Calculated
    elif stage == "Quote Calculated":
        return {
            "properties": [],
            "response": "Your quote is ready! Want me to send it to your email or book a time?",
            "next_actions": generate_next_actions()
        }

    # ✅ Stage 3: Gathering Personal Info
    elif stage == "Gathering Personal Info":
        return {
            "properties": [],
            "response": "Thanks! Just need your name, email and phone number to send this through.",
            "next_actions": []
        }

    # ✅ Stage 4+: Everything done
    else:
        return {
            "properties": [],
            "response": "All sorted! Let me know if you'd like to make any changes.",
            "next_actions": generate_next_actions()
        }
