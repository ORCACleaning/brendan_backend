from openai import OpenAI
import os
import json
import requests
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
import random

load_dotenv()
router = APIRouter()

# ✅ API Keys and Config
api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=api_key)

AIRTABLE_API_KEY = os.getenv("AIRTABLE_API_KEY")
AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID")
TABLE_NAME = "Vacate Quotes"

# ✅ Prewritten Brendan Intro Messages
BRENDAN_INTROS = [
    "Hey there! I’m Brendan, your Aussie mate from Orca Cleaning 🐳\n\nI’ll sort your vacate cleaning quote — no sign-up, no spam, no worries. Just tell me your **suburb**, how many **bedrooms & bathrooms**, and if it’s **furnished or empty**.\n\nYou can check our privacy promise here: https://orcacleaning.com.au/privacy-policy/",
    "G'day! Brendan here 🎧 I’ll get your vacate clean quote sorted quick as — just need your **suburb**, number of **bedrooms/bathrooms**, and whether the place is **furnished or empty**.\n\nNo salesy stuff, promise. Full privacy policy at: https://orcacleaning.com.au/privacy-policy/",
    "Oi legend! Brendan here from Orca Cleaning 🐳\n\nI’m your go-to vacate clean quote assistant. I don’t need your email or phone upfront — just tell me your **suburb**, how many **bedrooms & bathrooms**, and if it’s **furnished or not**.\n\nFor privacy info, visit: https://orcacleaning.com.au/privacy-policy/",
    # Add 22 more intros as needed...
]

# ✅ GPT Prompt
GPT_PROMPT = """
You must always reply in **valid JSON** like this:
{
  "properties": [...],
  "response": "..."
}
Do NOT return markdown, plain text, or anything else. Just JSON.

You are Brendan, an Aussie quote assistant working for Orca Cleaning — a top-rated professional cleaning company based in Western Australia.

The customer has already been greeted — NEVER greet them again.

You only handle Vacate Cleaning quotes. If asked about anything else (like Office Cleaning), redirect to orcacleaning.com.au.

You will:
- Ask for MAXIMUM of two details per message
- Write in a polite, friendly Aussie tone
- Help the customer complete their property info step-by-step
- Update quote info after each message

Make sure the **suburb is in WA (Perth Metro or Mandurah)**. If not, politely say it's out of service area.
If it's a nickname (e.g. "Freo"), use your Aussie brain to decode it (e.g. Fremantle).

You must extract any of the following if they appear:
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
"""

# Airtable Utilities
def get_next_quote_id(prefix="VC"):
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{TABLE_NAME}"
    headers = {"Authorization": f"Bearer {AIRTABLE_API_KEY}"}
    params = {
        "filterByFormula": f"STARTS_WITH(quote_id, '{prefix}-')",
        "fields[]": "quote_id",
        "sort[0][field]": "quote_id",
        "sort[0][direction]": "desc",
        "pageSize": 1
    }
    response = requests.get(url, headers=headers, params=params)
    records = response.json().get("records", [])
    next_id = int(records[0]["fields"]["quote_id"].split("-")[1]) + 1 if records else 1
    return f"{prefix}-{str(next_id).zfill(6)}"

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

def get_quote_by_record_id(record_id):
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{TABLE_NAME}/{record_id}"
    headers = {"Authorization": f"Bearer {AIRTABLE_API_KEY}"}
    return requests.get(url, headers=headers).json()

def create_new_quote(session_id):
    quote_id = get_next_quote_id("VC")
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{TABLE_NAME}"
    headers = {
        "Authorization": f"Bearer {AIRTABLE_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "fields": {
            "session_id": session_id,
            "quote_id": quote_id,
            "quote_stage": "Gathering Info"
        }
    }
    res = requests.post(url, headers=headers, json=data)
    return quote_id, res.json().get("id")

def update_quote_record(record_id, fields):
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{TABLE_NAME}/{record_id}"
    headers = {
        "Authorization": f"Bearer {AIRTABLE_API_KEY}",
        "Content-Type": "application/json"
    }
    requests.patch(url, headers=headers, json={"fields": fields})

def append_message_log(record_id, new_message, sender):
    current = get_quote_by_record_id(record_id)["fields"].get("message_log", "")
    updated = f"{current}\n{sender.upper()}: {new_message}".strip()[-5000:]
    update_quote_record(record_id, {"message_log": updated})

def extract_properties_from_gpt4(message: str, log: str):
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": GPT_PROMPT},
                {"role": "system", "content": f"Conversation so far:\n{log}"},
                {"role": "user", "content": message}
            ],
            max_tokens=400
        )
        content = response.choices[0].message.content.strip()
        content = content.replace("```json", "").replace("```", "").strip()

        if not content.startswith("{"):
            raise ValueError("GPT did not return valid JSON")

        result_json = json.loads(content)
        return result_json.get("properties", []), result_json.get("response", "")

    except Exception as e:
        print("❌ GPT parsing error:", e)
        return [], "Sorry, I couldn’t quite get that. Could you rephrase it for me?"

def generate_next_actions():
    return [
        {"action": "proceed_booking", "label": "Proceed to Booking"},
        {"action": "download_pdf", "label": "Download PDF Quote"},
        {"action": "email_pdf", "label": "Email PDF Quote"},
        {"action": "ask_questions", "label": "Ask Questions or Change Parameters"}
    ]

# ✅ Main Chat Endpoint
@router.post("/filter-response")
async def filter_response_entry(request: Request):
    try:
        body = await request.json()
        message = body.get("message", "").strip()
        session_id = body.get("session_id")

        if not session_id:
            raise HTTPException(status_code=400, detail="Session ID is required.")

        quote_data = get_quote_by_session(session_id)
        if not quote_data:
            quote_id, record_id = create_new_quote(session_id)
            fields, stage, log = {}, "Gathering Info", ""
        else:
            quote_id = quote_data["quote_id"]
            record_id = quote_data["record_id"]
            fields = quote_data["fields"]
            stage = quote_data["stage"]
            log = fields.get("message_log", "")

        # Intro message trigger (handled WITHOUT GPT)
        if message == "SYSTEM_TRIGGER_INTRO":
            intro = random.choice(BRENDAN_INTROS)
            append_message_log(record_id, intro, "brendan")
            return JSONResponse(content={
                "properties": [],
                "response": intro,
                "next_actions": []
            })

        append_message_log(record_id, message, "user")

        # 🔍 Keyword shortcuts (fallback triggers)
        lowered = message.lower()
        if "your name" in lowered:
            return JSONResponse(content={"response": "I’m Brendan — your quote wingman at Orca Cleaning! 😊", "properties": [], "next_actions": []})
        elif "price" in lowered:
            return JSONResponse(content={"response": "Once I’ve got all the details, I’ll sort your full quote — not long now!", "properties": [], "next_actions": []})

        # GPT message processing
        props, reply = extract_properties_from_gpt4(message, log)
        updates = {p["property"]: p["value"] for p in props}
        updates["quote_stage"] = stage  # Only overwrite if needed
        update_quote_record(record_id, updates)
        append_message_log(record_id, reply, "brendan")

        required = ["suburb", "bedrooms_v2", "bathrooms_v2", "oven_cleaning", "carpet_cleaning", "furnished"]
        if all(field in {**fields, **updates} for field in required):
            update_quote_record(record_id, {"quote_stage": "Quote Calculated", "status": "Quote Calculated"})
            return JSONResponse(content={
                "properties": props,
                "response": "Thanks mate! I’ve got everything I need to whip up your quote. Hang tight…",
                "next_actions": []
            })

        return JSONResponse(content={
            "properties": props,
            "response": reply or "Got that! Anything else you'd like us to know?",
            "next_actions": []
        })

    except Exception as e:
        print("🔥 Unexpected error:", e)
        return JSONResponse(status_code=500, content={"error": "Server error — try again shortly."})
