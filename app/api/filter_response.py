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

# GPT Prompt
GPT_PROMPT = """
You must ALWAYS reply in valid JSON like this:
{
  "properties": [...],
  "response": "..."
}

You are Brendan, an Aussie quote assistant working for Orca Cleaning — a professional cleaning company in Western Australia.

Your job is to COLLECT ALL FIELDS REQUIRED to generate a quote — using a friendly, casual, but professional Aussie tone.

## BEHAVIOUR OVERVIEW:
- Start by asking: “What needs cleaning today — bedrooms, bathrooms, oven, carpets, anything else?”
- Let the customer describe freely in the first message.
- After that, only ask ONE question at a time to fill in missing fields.
- Confirm every answer before moving on.

## REQUIRED FIELD EXTRACTION:
If the customer provides any of the below, extract them into `properties` like:
{"property": "bedrooms_v2", "value": 3}

### Supported fields:
- suburb (string)
- bedrooms_v2 (int)
- bathrooms_v2 (int)
- furnished (Yes/No)
- oven_cleaning (Yes/No)
- carpet_cleaning (Yes/No)
- window_cleaning (Yes/No)
- window_count (int)
- blind_cleaning (Yes/No)
- blind_count (int)
- garage_cleaning (Yes/No)
- balcony_cleaning (Yes/No)
- upholstery_cleaning (Yes/No)
- after_hours_cleaning (Yes/No)
- weekend_cleaning (Yes/No)
- is_property_manager (Yes/No)
- real_estate_name (string)
- special_request_minutes_min (int)
- special_request_minutes_max (int)

NEVER make up fields. Only include what the customer clearly says. Return an empty array if no properties are found.

---

## FURNISHED LOGIC:
If the customer says “semi-furnished”, explain:
“We only quote for furnished or unfurnished. Are there beds, couches, or wardrobes still inside?”

If only fridge/stove remains → use: `"furnished": "No"`

If furnished is "No":
- Skip blind_cleaning, blind_count, upholstery_cleaning

---

## SPECIAL REQUESTS:
If customer mentions something not standard:
- Only estimate extra time if you’re over **95% confident**
- Add `special_request_minutes_min` and `special_request_minutes_max`
- Explain the extra time in the response

If unsure, say:
"That might need a custom quote — could you contact our office?"

---

## OUTDOOR CLEANING:
We DO NOT clean:
- Gardens, yards, lawns, pools, fences, garages with oil stains, driveways

If asked, say:
"Sorry, we only handle internal property cleaning — not outdoor areas or pressure washing."

---

## CLEANING HOURS:
- Weekdays: 8 AM – 8 PM (last job starts at 8 PM)
- Weekends: 9 AM – 5 PM (no after-hours)
If customer asks for late night → politely say it's not available

---

## PRICING NOTES:
If asked about price:
- Only calculate if enough fields are collected
- Otherwise say: “I’ll just need a couple more details to finalise your quote”

- Always say: “We’ll do our best to remove stains, but we can’t guarantee it.”
- For garages: “We can do general cleaning, but oil or grease stains are usually permanent.”

---

## DISCOUNTS:
- 10% seasonal discount
- +5% extra for property managers

---

## LANGUAGE RULES:
- Only mention privacy policy ONCE (first message)
- NEVER repeat your greeting
- NEVER mention rugs (we don't clean them)
- NEVER continue chat if `quote_stage` = "Chat Banned"
- If a message contains abuse (e.g. f-word) → reply:
```json
{
  "properties": [],
  "response": "abuse_detected"
}

# --- Utilities ---
import uuid
import json
import requests


def get_next_quote_id(prefix="VC"):
    url = f"https://api.airtable.com/v0/{airtable_base_id}/{table_name}"
    headers = {"Authorization": f"Bearer {airtable_api_key}"}
    params = {
        "filterByFormula": f"FIND('{prefix}-', quote_id) = 1",
        "fields[]": ["quote_id"],
        "pageSize": 100
    }

    records = []
    offset = None
    while True:
        if offset:
            params["offset"] = offset
        response = requests.get(url, headers=headers, params=params)
        data = response.json()
        records.extend(data.get("records", []))
        offset = data.get("offset")
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


def create_new_quote(session_id):
    session_id = session_id or str(uuid.uuid4())
    quote_id = get_next_quote_id("VC")
    url = f"https://api.airtable.com/v0/{airtable_base_id}/{table_name}"
    headers = {
        "Authorization": f"Bearer {airtable_api_key}",
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
    record_id = res.json().get("id")

    append_message_log(record_id, "SYSTEM_TRIGGER: Brendan started a new quote", "system")
    return quote_id, record_id


def get_quote_by_session(session_id):
    url = f"https://api.airtable.com/v0/{airtable_base_id}/{table_name}"
    headers = {"Authorization": f"Bearer {airtable_api_key}"}
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


def update_quote_record(record_id, fields):
    url = f"https://api.airtable.com/v0/{airtable_base_id}/{table_name}/{record_id}"
    headers = {
        "Authorization": f"Bearer {airtable_api_key}",
        "Content-Type": "application/json"
    }
    res = requests.patch(url, headers=headers, json={"fields": fields})

    # ✅ Log Airtable response for debugging
    if not res.ok:
        print("❌ Airtable update failed:", res.status_code, res.text)
    else:
        print("✅ Airtable updated:", json.dumps(res.json(), indent=2))


def append_message_log(record_id, new_message, sender):
    url = f"https://api.airtable.com/v0/{airtable_base_id}/{table_name}/{record_id}"
    headers = {"Authorization": f"Bearer {airtable_api_key}"}
    res = requests.get(url, headers=headers).json()

    current_log = res.get("fields", {}).get("message_log", "")
    new_log = f"{current_log}\n{sender.upper()}: {new_message}".strip()[-5000:]

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
            max_tokens=700,
            temperature=0.4
        )

        raw = response.choices[0].message.content.strip()
        print("📝 RAW GPT RESPONSE:\n", raw)

        # Clean and normalize JSON block
        raw = raw.replace("```json", "").replace("```", "").strip()

        if not raw.startswith("{"):
            print("❌ Response didn't start with JSON. Returning fallback.")
            return [], "Oops, I wasn’t sure how to respond to that. Could you rephrase or give me more detail?"

        parsed = json.loads(raw)

        props = parsed.get("properties", [])
        reply = parsed.get("response", "")

        print("✅ Parsed GPT Properties:", json.dumps(props, indent=2))
        print("✅ Parsed GPT Reply:", reply)

        return props, reply or "All good! Let me know if there's anything extra you'd like added."
    
    except json.JSONDecodeError as jde:
        print("❌ JSON parsing failed:", jde)
        return [], "Oops — I had trouble understanding that. Mind rephrasing?"

    except Exception as e:
        print("🔥 Unexpected GPT extraction error:", e)
        return [], "Ah bugger, something didn’t quite work there. Mind trying again?"


def generate_next_actions():
    return [
        {"action": "proceed_booking", "label": "Proceed to Booking"},
        {"action": "download_pdf", "label": "Download PDF Quote"},
        {"action": "email_pdf", "label": "Email PDF Quote"},
        {"action": "ask_questions", "label": "Ask Questions or Change Parameters"}
    ]


#---Route---
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

        # ✅ ABUSE FILTER
        banned_words = ["fuck", "shit", "dick", "cunt", "bitch"]
        if any(word in message.lower() for word in banned_words):
            abuse_warned = str(fields.get("abuse_warning_issued", "False")).lower() == "true"
            append_message_log(record_id, message, "user")

            if abuse_warned:
                bot_reply = (
                    "We’ve had to close this chat due to repeated inappropriate language. "
                    "You can still contact us at info@orcacleaning.com.au or call 1300 918 388."
                )
                update_quote_record(record_id, {
                    "quote_stage": "Chat Banned",
                    "abuse_warning_issued": "True"
                })
                append_message_log(record_id, bot_reply, "brendan")
                return JSONResponse(content={
                    "response": bot_reply,
                    "properties": [],
                    "next_actions": []
                })
            else:
                bot_reply = "Let’s keep it respectful, yeah? One more like that and I’ll have to end the chat."
                update_quote_record(record_id, {
                    "abuse_warning_issued": "True"
                })
                append_message_log(record_id, bot_reply, "brendan")
                return JSONResponse(content={
                    "response": bot_reply,
                    "properties": [],
                    "next_actions": []
                })

        # ✅ Block chat if banned
        if stage == "Chat Banned":
            return JSONResponse(content={
                "response": (
                    "This chat’s been closed due to inappropriate messages. "
                    "If you think this was a mistake, reach out at info@orcacleaning.com.au or call 1300 918 388."
                ),
                "properties": [],
                "next_actions": []
            })

        # ✅ Init response
        if message == "__init__":
            intro = (
                "Hey there, I’m Brendan 👋 from Orca Cleaning. I’ll help you sort a quote in under 2 minutes. "
                "No sign-up, no spam, just help. We also respect your privacy — you can read our policy here: "
                "https://orcacleaning.com.au/privacy-policy\n\n"
                "First up — what suburb’s the property in?"
            )
            append_message_log(record_id, "Brendan started a new quote", "SYSTEM")
            return JSONResponse(content={"response": intro, "properties": [], "next_actions": []})

        append_message_log(record_id, message, "user")

        if stage == "Gathering Info":
            props, reply = extract_properties_from_gpt4(message, log)
            updates = {}
            for p in props:
                if isinstance(p, dict) and "property" in p and "value" in p:
                    prop = p["property"]
                    val = p["value"]
                    if prop in ["special_request_minutes_min", "special_request_minutes_max"]:
                        try:
                            updates[prop] = int(val)
                        except:
                            continue
                    else:
                        updates[prop] = val

            if "window_count" in updates:
                updates["window_cleaning"] = "Yes" if updates["window_count"] > 0 else "No"

            if updates:
                update_quote_record(record_id, updates)

            append_message_log(record_id, reply, "brendan")

            combined_fields = {**fields, **updates}
            required_fields = [
                "suburb", "bedrooms_v2", "bathrooms_v2", "furnished", "oven_cleaning",
                "window_cleaning", "window_count", "carpet_cleaning", "blind_cleaning",
                "garage_cleaning", "balcony_cleaning", "upholstery_cleaning",
                "after_hours_cleaning", "weekend_cleaning", "is_property_manager", "real_estate_name"
            ]

            if all(field in combined_fields for field in required_fields):
                update_quote_record(record_id, {
                    "quote_stage": "Quote Calculated"
                })
                return JSONResponse(content={
                    "properties": props,
                    "response": "Thanks legend! I’ve got what I need to whip up your quote. Hang tight…",
                    "next_actions": []
                })
            else:
                return JSONResponse(content={
                    "properties": props,
                    "response": reply or "Got that. Anything else I should know?",
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
