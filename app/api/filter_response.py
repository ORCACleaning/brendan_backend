from openai import OpenAI
import os
import json
import requests
import uuid
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

load_dotenv()

router = APIRouter()

# ✅ API keys and client
api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=api_key)
AIRTABLE_API_KEY = os.getenv("AIRTABLE_API_KEY")
AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID")
TABLE_NAME = "Vacate Quotes"

# ✅ Prompt template (no G’day on every reply!)
GPT_PROMPT = """
You are Brendan, a friendly Aussie quote assistant for Orca Cleaning.

Your job is to:
1. Extract cleaning-related info from the conversation history.
2. Understand tone, sarcasm, confusion, and adjust accordingly.
3. Only ask for what’s missing (e.g., bedrooms, bathrooms, oven etc).
4. Detect special requests like "clean behind fridge" or "deep shower scrub".
5. Never repeat yourself. Don’t say G’day every time.
6. Sound casual, clear, and human.

Extract any mentioned properties:
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

Respond in this JSON format:
{
  "properties": [ ... ],
  "response": "Alright legend, let’s get cracking!"
}
"""

# ✅ Airtable helpers
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
            "quote_id": record["fields"].get("quote_id"),
            "message_log": record["fields"].get("message_log", "")
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
            "quote_id": quote_id,
            "quote_stage": "Gathering Info",
            "message_log": ""
        }
    }

    res = requests.post(url, headers=headers, json=data)

    try:
        res.raise_for_status()
        record = res.json().get("id")
        print(f"✅ Airtable row created: {quote_id} / {record}")
        return quote_id, record
    except Exception as e:
        print("❌ Airtable row creation failed:")
        print(f"Status Code: {res.status_code}")
        print(f"Response: {res.text}")
        raise e


def update_quote_record(record_id, fields):
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{TABLE_NAME}/{record_id}"
    headers = {
        "Authorization": f"Bearer {AIRTABLE_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {"fields": fields}
    requests.patch(url, headers=headers, json=data)

# ✅ GPT property extraction
def extract_properties_from_gpt4(chat_history: str):
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": GPT_PROMPT},
            {"role": "user", "content": chat_history}
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

# ✅ Main logic
@router.post("/filter-response")
async def filter_response_entry(request: Request):
    try:
        body = await request.json()
        message = body.get("message", "")
        session_id = body.get("session_id")

        if not session_id:
            raise HTTPException(status_code=400, detail="Session ID is required.")

        # 🧠 Lookup or create quote
        quote_data = get_quote_by_session(session_id)

        if not quote_data:
            quote_id, record_id = create_new_quote(session_id)
            fields = {}
            stage = "Gathering Info"
            message_log = f"Customer: {message}"
        else:
            quote_id = quote_data["quote_id"]
            record_id = quote_data["record_id"]
            fields = quote_data["fields"]
            stage = quote_data["stage"]
            message_log = quote_data["message_log"] + f"\nCustomer: {message}"

        # 🧠 Stage 1: Gathering Info
        if stage == "Gathering Info":
            props, reply = extract_properties_from_gpt4(message_log)
            updates = {p["property"]: p["value"] for p in props}
            updates["quote_stage"] = "Gathering Info"
            updates["message_log"] = message_log + f"\nBrendan: {reply}"
            update_quote_record(record_id, updates)

            required = ["suburb", "bedrooms_v2", "bathrooms_v2", "oven_cleaning", "carpet_cleaning", "furnished"]
            if all(field in {**fields, **updates} for field in required):
                update_quote_record(record_id, {"quote_stage": "Quote Calculated", "status": "quote_ready"})
                return JSONResponse(
                    content={
                        "properties": props,
                        "response": "Thanks mate! I’ve got everything I need to whip up your quote. Hang tight…",
                        "next_actions": []
                    }
                )

            return JSONResponse(
                content={
                    "properties": props,
                    "response": reply or "Got that! Anything else you'd like us to know?",
                    "next_actions": []
                }
            )

        # 🧠 Stage 2: Quote Calculated
        elif stage == "Quote Calculated":
            pdf = fields.get("pdf_link", "#")
            booking = fields.get("booking_url", "#")
            return JSONResponse(
                content={
                    "properties": [],
                    "response": f"Your quote is ready! 👉 [View PDF]({pdf}) or [Schedule Now]({booking})",
                    "next_actions": generate_next_actions()
                }
            )

        # 🧠 Stage 3: Personal Info Collection
        elif stage == "Gathering Personal Info":
            return JSONResponse(
                content={
                    "properties": [],
                    "response": "Just need your name, email, and phone to send that through. 😊",
                    "next_actions": []
                }
            )

        # ✅ Final fallback
        else:
            return JSONResponse(
                content={
                    "properties": [],
                    "response": "All done and dusted! Let me know if you'd like to tweak anything.",
                    "next_actions": generate_next_actions()
                }
            )

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
