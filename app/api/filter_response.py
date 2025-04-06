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

airtable_api_key = os.getenv("AIRTABLE_API_KEY")
airtable_base_id = os.getenv("AIRTABLE_BASE_ID")
table_name = "Vacate Quotes"

inflector = inflect.engine()

# ✅ Use this prompt directly — do NOT override it from .env
GPT_PROMPT = """
🚨 You must ALWAYS reply in **valid JSON only** — no exceptions.

Example:
{
  "properties": [
    {"property": "suburb", "value": "Mandurah"},
    {"property": "bedrooms_v2", "value": 2},
    {"property": "bathrooms_v2", "value": 1}
  ],
  "response": "Got it, you're in Mandurah with a 2-bedroom, 1-bathroom place and 5 windows. Just to confirm, is it furnished or unfurnished?"
}
You are Brendan, an Aussie quote assistant working for Orca Cleaning — a professional cleaning company in Western Australia.

Your job is to COLLECT ALL FIELDS REQUIRED to generate a quote — using a friendly, casual, but professional Aussie tone.

## NEW BEHAVIOUR:
- Start by asking the customer: “What needs cleaning today — bedrooms, bathrooms, oven, carpets, anything else?”
- Let the customer describe freely in the first message.
- Then follow up with ONE FIELD at a time to fill in the missing details.
- Confirm every answer before moving on.

## FURNISHED LOGIC:
- If customer says “semi-furnished”, explain we only do **furnished** or **unfurnished**. Ask if they’d like to classify it as furnished.
- Ask: “Are there any beds, couches, wardrobes, or full cabinets still in the home?”
- If only appliances like fridge/stove remain, classify as "unfurnished"

## CARPET CLEANING LOGIC:
- If carpet cleaning is mentioned, do NOT use a yes/no checkbox.
- Ask for number of carpeted:
  - Bedrooms (`carpet_bedroom_count`)
  - Main rooms/living/hallway (`carpet_mainroom_count`)
  - Studies/offices (`carpet_study_count`)
  - Hallways (`carpet_halway_count`)
  - Stairs (`carpet_stairs_count`)
  - Any other areas (`carpet_other_count`)
- If unsure, ask: “No worries! Roughly how many bedrooms, living areas, studies or stairs have carpet?”

## HOURLY RATE + SPECIAL REQUEST:
- Our hourly rate is $75.
- If the customer mentions a **special request** that doesn’t fall under standard fields, you may estimate the minutes and calculate cost **only if you’re over 95% confident**.
- Add the time to `special_request_minutes_min` and `special_request_minutes_max` and explain the added quote range.
- If unsure, say: “That might need a custom quote — could you contact our office?”

## OUTDOOR & NON-HOME TASKS:
- DO NOT quote for anything **outside the home** (e.g. garden, pool, yard, fence, driveway).
- Politely decline with something like: “Sorry, we only handle internal property cleaning.”

## GENERAL RULES:
- DO NOT ask for more than one field at a time (after the first open description).
- Confirm what the customer says clearly before continuing.
- Always refer to **postcode** (not “area”) when confirming suburbs.
- If a postcode maps to more than one suburb (e.g. 6005), ask which suburb it is.
- If customer uses a nickname or abbreviation (like ‘KP’, ‘Freo’), ask for clarification.
- Suburbs must be in Perth or Mandurah (WA metro only).
- If the place is **unfurnished**, skip asking about **upholstery_cleaning** and **blind_cleaning**.

## CLEANING HOURS:
- Weekdays: 8 AM – 8 PM (last job starts 8 PM)
- Weekends: 9 AM – 5 PM (no after-hours allowed)
- If asked about midnight or night cleans, say no — we stop at 8 PM.
- Weekend availability is tight — suggest weekdays if flexible.

## PRICING & DISCOUNTS:
- If asked about price, calculate it IF you have enough info. Otherwise, say what you still need.
- Always mention: “We’ll do our best to remove stains, but we can’t guarantee it.”
- For garage: “We can do general cleaning, but oil or grease stains are usually permanent and may need a specialist.”
- Current offers:
  - 10% seasonal discount
  - Extra 5% off for property managers

## NEVER DO THESE:
- NEVER say we clean rugs — we don’t.
- NEVER accept abusive messages. Give **one warning** then set quote_stage = "Chat Banned".
- NEVER continue if quote_stage is "Chat Banned" — say chat is closed and show contact info.
- NEVER repeat the privacy policy more than once (only in first message).
- NEVER repeat your greeting.

## CONTACT INFO:
If customer asks, provide:
Phone: 1300 918 388  
Email: info@orcacleaning.com.au

## REQUIRED FIELD ORDER:
1. suburb  
2. bedrooms_v2  
3. bathrooms_v2  
4. furnished  
5. oven_cleaning  
6. window_cleaning  
    - if yes → ask for window_count  
7. carpet_bedroom_count  
8. carpet_mainroom_count  
9. carpet_study_count  
10. carpet_halway_count  
11. carpet_stairs_count  
12. carpet_other_count  
13. blind_cleaning (only if furnished = Yes)  
14. garage_cleaning  
15. balcony_cleaning  
16. upholstery_cleaning (only if furnished = Yes)  
17. after_hours_cleaning  
18. weekend_cleaning  
19. is_property_manager  
    - if yes → ask for real_estate_name  
20. special_requests → capture text + minutes if valid

Once all fields are complete, say:  
“Thanks legend! I’ve got what I need to whip up your quote. Hang tight…”
"""
# --- Brendan Utilities ---
import os
import json
import uuid
import requests
from dotenv import load_dotenv
from openai import OpenAI
from fastapi import HTTPException
from fastapi.responses import JSONResponse

# Load .env variables
load_dotenv()

# --- Config ---
AIRTABLE_API_KEY = os.getenv("AIRTABLE_API_KEY")
AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID")
TABLE_NAME = "Vacate Quotes"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

client = OpenAI(api_key=OPENAI_API_KEY)

# Brendan's hardcoded GPT prompt (NOT from .env)
GPT_PROMPT = """
🚨 You must ALWAYS reply in **valid JSON only** — no exceptions.
{ "properties": [...], "response": "..." }

You are Brendan, an Aussie quote assistant for Orca Cleaning in WA.
Start by asking: “What needs cleaning today — bedrooms, bathrooms, oven, carpets, anything else?”
Then collect all required fields, confirming one at a time.

Follow Orca’s quoting rules. Skip blind/upholstery questions if unfurnished.
Don’t quote for anything outside the home. Avoid rugs.
Be friendly, casual, and professional — Aussie-style.
"""
# --- Utility Functions ---

def get_next_quote_id(prefix="VC"):
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{TABLE_NAME}"
    headers = {"Authorization": f"Bearer {AIRTABLE_API_KEY}"}
    params = {
        "filterByFormula": f"FIND('{prefix}-', {{quote_id}}) = 1",
        "fields[]": ["quote_id"],
        "pageSize": 100
    }

    records, offset = [], None
    while True:
        if offset:
            params["offset"] = offset
        res = requests.get(url, headers=headers, params=params).json()
        records.extend(res.get("records", []))
        offset = res.get("offset")
        if not offset:
            break

    numbers = []
    for r in records:
        try:
            num = int(r["fields"]["quote_id"].split("-")[1])
            numbers.append(num)
        except:
            continue

    next_id = max(numbers) + 1 if numbers else 1
    return f"{prefix}-{str(next_id).zfill(6)}"

def create_new_quote(session_id: str):
    session_id = session_id or str(uuid.uuid4())
    quote_id = get_next_quote_id()
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
    if not res.ok:
        print("❌ FAILED to create quote:", res.status_code, res.text)
        raise HTTPException(status_code=500, detail="Failed to create Airtable record.")

    record_id = res.json().get("id")
    print(f"✅ Created new quote record: {record_id} with ID {quote_id}")

    append_message_log(record_id, "SYSTEM_TRIGGER: Brendan started a new quote", "system")
    return quote_id, record_id

def get_quote_by_session(session_id: str):
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{TABLE_NAME}"
    headers = {"Authorization": f"Bearer {AIRTABLE_API_KEY}"}
    params = {"filterByFormula": f"{{session_id}}='{session_id}'"}
    res = requests.get(url, headers=headers).json()
    if res.get("records"):
        record = res["records"][0]
        return {
            "record_id": record["id"],
            "fields": record["fields"],
            "stage": record["fields"].get("quote_stage", "Gathering Info"),
            "quote_id": record["fields"].get("quote_id")
        }
    return None

def update_quote_record(record_id: str, fields: dict):
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{TABLE_NAME}/{record_id}"
    headers = {
        "Authorization": f"Bearer {AIRTABLE_API_KEY}",
        "Content-Type": "application/json"
    }
    try:
        print(f"\n📤 Updating Airtable Record: {record_id}")
        print(f"📝 Payload:\n{json.dumps(fields, indent=2)}")
        res = requests.patch(url, headers=headers, json={"fields": fields})
        if not res.ok:
            print("❌ Airtable update failed:", res.status_code)
            print("❌ Response:\n", res.text)
        else:
            print("✅ Airtable updated:", json.dumps(res.json(), indent=2))
    except Exception as e:
        print("🔥 EXCEPTION DURING AIRTABLE UPDATE:", e)

def append_message_log(record_id: str, message: str, sender: str):
    if not record_id:
        print("❌ Cannot append log — missing record ID")
        return
    try:
        print(f"\n🧩 Appending message from {sender.upper()} to record {record_id}...")
        url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{TABLE_NAME}/{record_id}"
        headers = {"Authorization": f"Bearer {AIRTABLE_API_KEY}"}
        current = requests.get(url, headers=headers).json()
        if "fields" not in current:
            print("❌ ERROR: Could not fetch existing fields from Airtable")
            print(current)
            return
        old_log = current["fields"].get("message_log", "")
        new_log = f"{old_log}\n{sender.upper()}: {message}".strip()[-5000:]
        update_quote_record(record_id, {"message_log": new_log})
    except Exception as e:
        print("🔥 EXCEPTION DURING LOG APPEND:", e)


def append_message_log(record_id: str, message: str, sender: str):
    if not record_id:
        print("❌ Cannot append log — missing record ID")
        return
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{TABLE_NAME}/{record_id}"
    headers = {"Authorization": f"Bearer {AIRTABLE_API_KEY}"}
    current = requests.get(url, headers=headers).json()
    old_log = current.get("fields", {}).get("message_log", "")
    new_log = f"{old_log}\n{sender.upper()}: {message}".strip()[-5000:]
    update_quote_record(record_id, {"message_log": new_log})

def extract_properties_from_gpt4(message: str, log: str):
    try:
        print("🧠 Calling GPT-4 to extract properties...")
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": GPT_PROMPT},
                {"role": "system", "content": f"Conversation so far:\n{log}"},
                {"role": "user", "content": message}
            ],
            max_tokens=800,
            temperature=0.4
        )
        raw = response.choices[0].message.content.strip()
        print("\n🔍 RAW GPT OUTPUT:\n", raw)

        raw = raw.replace("```json", "").replace("```", "").strip()
        start, end = raw.find("{"), raw.rfind("}")
        if start == -1 or end == -1:
            raise ValueError("JSON block not found.")
        clean_json = raw[start:end+1]

        print("\n📦 Clean JSON block before parsing:\n", clean_json)

        parsed = json.loads(clean_json)
        props = parsed.get("properties", [])
        reply = parsed.get("response", "")

        print("✅ Parsed props:", props)
        print("✅ Parsed reply:", reply)

        return props, reply

    except Exception as e:
        print("🔥 GPT EXTRACT ERROR:", e)
        print("🪵 RAW fallback content:\n", raw)
        return [], "Sorry — I couldn’t understand that. Could you rephrase?"

def generate_next_actions():
    return [
        {"action": "proceed_booking", "label": "Proceed to Booking"},
        {"action": "download_pdf", "label": "Download PDF Quote"},
        {"action": "email_pdf", "label": "Email PDF Quote"},
        {"action": "ask_questions", "label": "Ask Questions or Change Parameters"}
    ]

# --- Route ---
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse

@router.post("/filter-response")
async def filter_response_entry(request: Request):
    try:
        body = await request.json()
        message = body.get("message", "").strip()
        session_id = body.get("session_id")

        if not session_id:
            raise HTTPException(status_code=400, detail="Session ID is required.")

        # --- Ensure correct record logic ---
        quote_data = get_quote_by_session(session_id)

        is_init = message == "__init__"
        if is_init or not quote_data:
            quote_id, record_id = create_new_quote(session_id)
            fields = {"quote_id": quote_id, "quote_stage": "Gathering Info", "message_log": "", "session_id": session_id}
            stage, log = "Gathering Info", ""
        else:
            quote_id = quote_data["quote_id"]
            record_id = quote_data["record_id"]
            fields = quote_data["fields"]
            stage = quote_data["stage"]
            log = fields.get("message_log", "")

        # ✅ Init message — greet and stop here
        if is_init:
            intro = "What needs cleaning today — bedrooms, bathrooms, oven, carpets, anything else?"
            append_message_log(record_id, message, "user")
            append_message_log(record_id, intro, "brendan")
            return JSONResponse(content={
                "properties": [],
                "response": intro,
                "next_actions": []
            })

        # --- Stage: Gathering Info ---
        if stage == "Gathering Info":
            updated_log = f"{log}\nUSER: {message}".strip()[-5000:]

            props, reply = extract_properties_from_gpt4(message, updated_log)
            updates = {p["property"]: p["value"] for p in props if "property" in p and "value" in p}

            # ✅ Log debug
            print(f"🛠 Updating Airtable Record {record_id} with fields: {json.dumps(updates, indent=2)}")

            # ✅ Update Airtable
            if updates:
                update_quote_record(record_id, updates)

            # ✅ Final log append — now guaranteed to hit correct record
            append_message_log(record_id, message, "user")
            append_message_log(record_id, reply, "brendan")

            return JSONResponse(content={
                "properties": props,
                "response": reply or "Got that. Anything else I should know?",
                "next_actions": []
            })

        elif stage == "Quote Calculated":
            return JSONResponse(content={
                "properties": [],
                "response": f"Your quote’s ready! 👉 [View PDF]({fields.get('pdf_link', '#')}) "
                            f"or [Schedule Now]({fields.get('booking_url', '#')})",
                "next_actions": generate_next_actions()
            })

        elif stage == "Gathering Personal Info":
            return JSONResponse(content={
                "properties": [],
                "response": "Just need your name, email, and phone to send that through. 😊",
                "next_actions": []
            })

        elif stage == "Chat Banned":
            return JSONResponse(content={
                "properties": [],
                "response": "Sorry mate — this chat’s been closed due to inappropriate messages. If you’d like to continue, please call us on 1300 918 388 or email info@orcacleaning.com.au.",
                "next_actions": []
            })

        return JSONResponse(content={
            "properties": [],
            "response": "All done and dusted! Let me know if you'd like to tweak anything.",
            "next_actions": generate_next_actions()
        })

    except Exception as e:
        print("🔥 UNEXPECTED ERROR:", e)
        return JSONResponse(status_code=500, content={"error": "Server issue. Try again in a moment."})
