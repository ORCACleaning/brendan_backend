from openai import OpenAI
import os
import json
import requests
import inflect
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

load_dotenv()
router = APIRouter()

# API Keys and Config
api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=api_key)

AIRTABLE_API_KEY = os.getenv("AIRTABLE_API_KEY")
AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID")
TABLE_NAME = "Vacate Quotes"

inflect_engine = inflect.engine()

# GPT Prompt Template
GPT_PROMPT = """
You must always reply in valid JSON like this:
{
  "properties": [...],
  "response": "..."
}
Do NOT return markdown, plain text, or anything else. Just JSON.

You are Brendan, a friendly Aussie quote assistant working for Orca Cleaning, a top-tier vacate cleaning company in WA. The user has already been welcomed, so don’t say hi again.

Make sure to:
- Validate suburbs: Only WA metro and Mandurah suburbs are accepted.
- Recognise informal suburb names (e.g. "Freo" = "Fremantle", "Subi" = "Subiaco").
- If user enters a **postcode**, ask for the suburb instead.
- Ask a max of two questions at a time.
- Speak in a warm, helpful tone.
- Collect: suburb, bedrooms, bathrooms, oven_cleaning, carpet_cleaning, furnished, and other extras.
- After all info is gathered, confirm the quote will be calculated.

Privacy note: We never spam or share info. Privacy policy at https://orcacleaning.com.au/privacy-policy/
"""

# Utilities
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
    fields = get_quote_by_record_id(record_id).get("fields", {})
    current = fields.get("message_log", "")
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
        print("\U0001F4E4 Raw GPT Output:\n", content)
        content = content.replace("```json", "").replace("```", "").strip()

        result_json = json.loads(content)
        if not isinstance(result_json, dict):
            raise ValueError("Expected JSON object")

        return result_json.get("properties", []), result_json.get("response", "")

    except Exception as e:
        print("❌ GPT parsing error:", e)
        return [], "Ah bugger, something didn’t quite work there. Mind trying again?"

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

        append_message_log(record_id, message, "user")

        if message == "__init__":
            intro = "Hey there, I’m Brendan 👋 from Orca Cleaning. I’ll help you sort a quote in under 2 minutes. First up — what suburb’s the property in? And no worries — no sign-up, no spam, just help."
            followup = "Could ya let me know the suburb you’re in and if the property is furnished or not? This’ll help in providing an accurate quote."
            append_message_log(record_id, intro, "brendan")
            append_message_log(record_id, followup, "brendan")
            return JSONResponse(content={"response": intro + "\n\n" + followup, "properties": [], "next_actions": []})

        if stage == "Gathering Info":
            props, reply = extract_properties_from_gpt4(message, log)
            updates = {}
            for p in props:
                key, val = p.get("property"), p.get("value")
                if key and val is not None:
                    if isinstance(val, str) and val.isalpha():
                        val = inflect_engine.number_to_words(val.lower()) or val
                    updates[key] = val
            updates["quote_stage"] = "Gathering Info"
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

        elif stage == "Quote Calculated":
            pdf = fields.get("pdf_link", "#")
            booking = fields.get("booking_url", "#")
            return JSONResponse(content={
                "properties": [],
                "response": f"Your quote’s ready! 👉 [View PDF]({pdf}) or [Schedule Now]({booking})",
                "next_actions": generate_next_actions()
            })

        elif stage == "Gathering Personal Info":
            return JSONResponse(content={
                "properties": [],
                "response": "Just need your name, email, and phone to send that through. 😊",
                "next_actions": []
            })

        return JSONResponse(content={
            "properties": [],
            "response": "All done and dusted! Let me know if you'd like to tweak anything.",
            "next_actions": generate_next_actions()
        })

    except Exception as e:
        print("🔥 Unexpected error:", e)
        return JSONResponse(status_code=500, content={"error": "Server issue. Try again in a moment."})
