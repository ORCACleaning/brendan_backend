from openai import OpenAI
import os
import json
import random
import requests
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

load_dotenv()
router = APIRouter()

# === Config ===
api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=api_key)

AIRTABLE_API_KEY = os.getenv("AIRTABLE_API_KEY")
AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID")
TABLE_NAME = "Vacate Quotes"

# === Warm Aussie Brendan Intros ===
INTRO_MESSAGES = [
    "Hey legend! I’m Brendan — your Aussie vacate cleaning wingman from Orca 🐳. This’ll take under 2 mins, no spam, no sneaky upsells. Just let me know your suburb in WA, and I’ll get to work. Oh, and there’s a cheeky seasonal discount running 😉 You can peek at our [privacy policy](https://orcacleaning.com.au/privacy-policy/) if you're wondering how we use your info.",
    "G’day! Brendan here from Orca Cleaning — ready to get your vacate clean sorted, fast and fair. I’m not here to grab your details or sell you junk. Just tell me your suburb to get started, too easy!",
    "Hey there, I’m Brendan 👋 from Orca Cleaning. I’ll help you sort a quote in under 2 minutes. First up — what suburb’s the property in? And no worries — no sign-up, no spam, just help."
    # (you can add 20+ more to this list for variety)
]

# === GPT Prompt ===
GPT_PROMPT = """
You are Brendan, a professional but very friendly Aussie-style quote assistant for Orca Cleaning in WA.
You NEVER start with greetings — the customer has already been welcomed.
Your job is to:
- Collect 1–2 property details at a time (e.g., bedrooms, bathrooms, oven cleaning, etc)
- Always respond clearly and politely.
- Assume suburb nicknames like "Freo" = Fremantle and "Subi" = Subiaco.
- If suburb isn’t in WA (Perth Metro or Mandurah), ask for clarification.
- Never say “Hi”, “Hello”, or “G’day” — they’ve already been greeted!
Always return this JSON:
{
  "properties": [...],
  "response": "..."
}
"""

# === Airtable Helpers ===
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
    res = requests.get(url, headers=headers, params=params).json()
    records = res.get("records", [])
    next_id = int(records[0]["fields"]["quote_id"].split("-")[1]) + 1 if records else 1
    return f"{prefix}-{str(next_id).zfill(6)}"

def get_quote_by_session(session_id):
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{TABLE_NAME}"
    headers = {"Authorization": f"Bearer {AIRTABLE_API_KEY}"}
    params = {"filterByFormula": f"{{session_id}}='{session_id}'"}
    res = requests.get(url, headers=headers, params=params).json()
    if res.get("records"):
        r = res["records"][0]
        return {"record_id": r["id"], "fields": r["fields"], "stage": r["fields"].get("quote_stage", "Gathering Info")}
    return None

def create_new_quote(session_id):
    quote_id = get_next_quote_id()
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{TABLE_NAME}"
    headers = {
        "Authorization": f"Bearer {AIRTABLE_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {"fields": {"session_id": session_id, "quote_id": quote_id, "quote_stage": "Gathering Info"}}
    res = requests.post(url, headers=headers, json=data).json()
    return quote_id, res.get("id")

def update_quote_record(record_id, fields):
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{TABLE_NAME}/{record_id}"
    headers = {
        "Authorization": f"Bearer {AIRTABLE_API_KEY}",
        "Content-Type": "application/json"
    }
    requests.patch(url, headers=headers, json={"fields": fields})

def append_message_log(record_id, msg, sender):
    current = get_quote_by_record_id(record_id).get("fields", {}).get("message_log", "")
    updated = f"{current}\n{sender.upper()}: {msg}"[-5000:]
    update_quote_record(record_id, {"message_log": updated})

def get_quote_by_record_id(record_id):
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{TABLE_NAME}/{record_id}"
    headers = {"Authorization": f"Bearer {AIRTABLE_API_KEY}"}
    return requests.get(url, headers=headers).json()

# === GPT Trigger ===
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
        result_json = json.loads(content)
        return result_json.get("properties", []), result_json.get("response", "")
    except Exception as e:
        print("❌ GPT parsing error:", e)
        return [], "Ah bugger, something didn’t quite work there. Mind trying again?"

# === Endpoint ===
@router.post("/filter-response")
async def filter_response(request: Request):
    try:
        body = await request.json()
        message = body.get("message", "").strip()
        session_id = body.get("session_id")
        if not session_id:
            raise HTTPException(400, "Missing session ID")

        quote_data = get_quote_by_session(session_id)
        if not quote_data:
            quote_id, record_id = create_new_quote(session_id)
            quote_data = {"record_id": record_id, "fields": {}, "stage": "Gathering Info"}
        else:
            record_id = quote_data["record_id"]

        # === INIT MESSAGE (not GPT triggered) ===
        if message == "__init__":
            intro = random.choice(INTRO_MESSAGES)
            append_message_log(quote_data["record_id"], intro, "brendan")
            return JSONResponse({"response": intro, "properties": [], "next_actions": []})

        # === GPT triggered message ===
        append_message_log(record_id, message, "user")
        log = get_quote_by_record_id(record_id).get("fields", {}).get("message_log", "")
        props, reply = extract_properties_from_gpt4(message, log)
        updates = {p["property"]: p["value"] for p in props}
        updates["quote_stage"] = "Gathering Info"
        update_quote_record(record_id, updates)
        append_message_log(record_id, reply, "brendan")

        return JSONResponse({"response": reply, "properties": props, "next_actions": []})

    except Exception as e:
        print("🔥 Unexpected error:", e)
        return JSONResponse(status_code=500, content={"response": "Server had a moment. Mind trying again shortly?"})
