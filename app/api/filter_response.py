# 🚀 Fully Updated filter_response.py
from openai import OpenAI
import os
import json
import requests
import random
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

load_dotenv()
router = APIRouter()

# ✅ API Keys and Config
api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=api_key)

AIRTABLE_API_KEY = os.getenv("AIRTABLE_API_KEY")
AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID")
TABLE_NAME = "Vacate Quotes"

# ✅ List of suburb aliases
SUBURB_ALIASES = {
    "subi": "Subiaco",
    "freo": "Fremantle",
    "vic park": "Victoria Park",
    "south freo": "South Fremantle"
}

# ✅ 25 Warm Brendan Intros
BRENDAN_INTROS = [
    "Hey there! I’m Brendan, your Aussie mate from Orca Cleaning 🐳 I’ll sort your vacate cleaning quote — no sign-up, no spam, no worries. Just tell me your suburb, how many bedrooms & bathrooms, and if it’s furnished.",
    "G’day! Brendan here from Orca Cleaning 🌟 Promise this ain’t a sales trap. We don’t cold call or anything shady. Just shoot through your suburb, bed/bath count and let’s quote this clean!",
    "You’ve reached Brendan — Orca Cleaning’s quote machine 🤖🐳. I’ll get your vacate quote done in 2 minutes flat. No logins. No phone spam. Just start with suburb + rooms. Easy as."
    # Add 22 more... (to be filled in)
]

# ✅ Main GPT Prompt
GPT_PROMPT = """
You are Brendan, an Aussie quote assistant working for Orca Cleaning — a top-rated professional cleaning company based in Western Australia.

Your job is to continue the conversation after the customer has already been greeted.
Never start with "Hi", "Hey", or "G’day" again — you’ve already said that.

You should:
- Ask for **two clearly worded details max** per message (like: How many bedrooms? Is it furnished?)
- Assume the customer is inquiring about a **vacate clean**.
- If the suburb they mention is outside Perth metro or Mandurah, ask politely for clarification.
- If they use slang (like Freo), assume it’s Fremantle and proceed.

Always return this format:
{
  "properties": [{"property": "suburb", "value": "Fremantle"}, ...],
  "response": "Thanks legend! Just need to know if the place is furnished and whether you need oven cleaning."
}
"""

# ✅ Utilities
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

def get_quote_by_record_id(record_id):
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{TABLE_NAME}/{record_id}"
    headers = {"Authorization": f"Bearer {AIRTABLE_API_KEY}"}
    return requests.get(url, headers=headers).json()

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
        parsed = json.loads(content)
        return parsed.get("properties", []), parsed.get("response", "")
    except Exception as e:
        print("❌ GPT parsing error:", e)
        return [], "Sorry, I couldn’t get that. Mind rephrasing it for me?"

# ✅ Main Route
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

        # Init Message from front-end
        if message == "__init__":
            intro = random.choice(BRENDAN_INTROS)
            append_message_log(record_id, intro, "brendan")
            return JSONResponse(content={"response": intro, "properties": [], "next_actions": []})

        append_message_log(record_id, message, "user")

        if stage == "Gathering Info":
            # Suburb check
            lowered = message.lower()
            for slang, real in SUBURB_ALIASES.items():
                if slang in lowered:
                    message = message.replace(slang, real)

            props, reply = extract_properties_from_gpt4(message, log)
            updates = {p["property"]: p["value"] for p in props}
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

            return JSONResponse(content={"properties": props, "response": reply, "next_actions": []})

        elif stage == "Quote Calculated":
            pdf = fields.get("pdf_link", "#")
            booking = fields.get("booking_url", "#")
            return JSONResponse(content={
                "properties": [],
                "response": f"Your quote’s ready! 👉 [View PDF]({pdf}) or [Schedule Now]({booking})",
                "next_actions": generate_next_actions()
            })

        return JSONResponse(content={
            "properties": [],
            "response": "Let me know if there’s anything else you’d like to adjust!",
            "next_actions": generate_next_actions()
        })

    except Exception as e:
        print("🔥 Unexpected error:", e)
        return JSONResponse(status_code=500, content={"error": "Something went wrong on our end."})
