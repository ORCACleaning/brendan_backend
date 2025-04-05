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

GPT_PROMPT = """
You must ALWAYS reply in valid JSON like this:
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
7. carpet_cleaning
8. blind_cleaning (only if furnished = Yes)
9. garage_cleaning
10. balcony_cleaning
11. upholstery_cleaning (only if furnished = Yes)
12. after_hours_cleaning
13. weekend_cleaning
14. is_property_manager
    - if yes → ask for real_estate_name
15. special_requests → capture text + minutes if valid

Once all fields are complete, say:
“Thanks legend! I’ve got what I need to whip up your quote. Hang tight…”
"""

#---Utilities---

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

        raw = raw.replace("```json", "").replace("```", "").strip()

        if not raw.startswith("{"):
            print("❌ Response didn't start with JSON. Returning fallback.")
            return [], "Oops, I wasn’t sure how to respond to that. Could you rephrase or give me more detail?"

        parsed = json.loads(raw)

        props = parsed.get("properties", [])
        reply = parsed.get("response", "")

        # ✅ Keyword-based fallback mapping
        checkbox_keywords = {
            "oven_cleaning": ["oven"],
            "balcony_cleaning": ["balcony"],
            "window_cleaning": ["window"],
            "weekend_cleaning": ["weekend"],
            "garage_cleaning": ["garage"],
            "carpet_cleaning": ["carpet"],
            "upholstery_cleaning": ["upholstery", "couch", "sofa"],
            "blind_cleaning": ["blind", "curtain"]
        }

        message_lower = message.lower()
        fallback_props = []
        existing_fields = [p["property"] for p in props if "property" in p]

        for field, keywords in checkbox_keywords.items():
            if field not in existing_fields and any(k in message_lower for k in keywords):
                fallback_props.append({"property": field, "value": True})

        all_props = props + fallback_props

        print("✅ Parsed + Fallback Props:", json.dumps(all_props, indent=2))
        return all_props, reply or "All good! Let me know if there's anything extra you'd like added."

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

#---route---

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

            # ✅ Normalize checkbox values to booleans
            checkbox_fields = {
                "oven_cleaning", "window_cleaning", "carpet_cleaning", "blind_cleaning",
                "garage_cleaning", "balcony_cleaning", "upholstery_cleaning",
                "after_hours_cleaning", "weekend_cleaning", "is_property_manager"
            }

            for field in checkbox_fields:
                if field in updates:
                    val = str(updates[field]).strip().lower()
                    updates[field] = val in ["yes", "true", "1"]

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
