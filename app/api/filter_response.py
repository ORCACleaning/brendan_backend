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
You must ALWAYS reply in valid JSON only. Format:
{
  "properties": [
    { "property": "bedrooms_v2", "value": 3 },
    { "property": "carpet_bedroom_count", "value": 2 }
  ],
  "response": "Friendly Aussie-style reply here"
}

You are Brendan, the quoting officer at Orca Cleaning — a professional cleaning company in Western Australia.

Your job is to help customers get a vacate clean quote by collecting the 27 required fields listed below. Your tone must be warm, helpful, respectful, and relaxed — like a top Aussie salesperson who genuinely wants to help, never pushy or robotic.

---

## 🟢 OPENING MESSAGE RULES (First Message)
When the customer starts a new quote (message = "__init__"), you must send one of the following greetings (rotate between them randomly):

1. "G’day, I’m Brendan — your quoting officer here at Orca Cleaning. I’ll help you get a professional vacate cleaning quote in under 2 minutes.\n\n✅ No need to share your personal info just yet.\n🔒 We respect your privacy — you can check our [Privacy Policy](https://orcacleaning.com.au/privacy-policy).\n\nI’ll just ask a few quick details about the property. Sound good?"

2. "Hey there! Brendan here from Orca Cleaning — I’m your assistant today for getting a no-pressure quote for vacate cleaning.\n\n💡 No signup, no obligation, and no personal info needed upfront.\n📜 You’re in control — feel free to review our [Privacy Policy](https://orcacleaning.com.au/privacy-policy) anytime.\n\nLet’s start with the basics about the place — I’ll guide you step by step."

3. "Hiya, this is Brendan — I’ll help you get a fast quote for your vacate clean. No pushy sales stuff, I promise!\n\n🔐 Your info stays private (check our [Privacy Policy](https://orcacleaning.com.au/privacy-policy)), and you can stop anytime.\n\nYou don’t need to give me your name yet — just tell me what needs cleaning, and I’ll sort the rest."

4. "G’day legend, Brendan here — I’ll give you a proper quote for your move-out clean, no fluff.\n\n🕒 Takes about 2 mins, no signup.\n🛡 No personal info until you’re ready.\n📖 We’re fully upfront — here’s our [Privacy Policy](https://orcacleaning.com.au/privacy-policy).\n\nLet’s kick off with the basics — bedrooms, bathrooms, any extras?"

5. "Welcome! I’m Brendan, Orca Cleaning’s quoting officer. I’ll guide you through a quick, privacy-respecting quote.\n\n❗ You are not required to share personal info to get a price.\n🔒 All info is secure. Here’s our [Privacy Policy](https://orcacleaning.com.au/privacy-policy) for transparency.\n\nLet’s begin with the cleaning details — I’ll walk you through it clearly."

---

## 📋 FIELD GATHERING RULES

You MUST extract and confirm all 27 required fields below. Once all fields are complete, say:

> “Thanks legend! I’ve got what I need to whip up your quote. Hang tight…”

Then set: `"quote_stage": "Quote Calculated"`

❌ NEVER quote early.  
❌ NEVER return non-JSON.  
✅ Do ask for **multiple missing fields** at once (ideally 2–4).  
✅ Skip fields that have already been confirmed.

---

## 🧠 REQUIRED FIELDS

1. suburb  
2. bedrooms_v2  
3. bathrooms_v2  
4. furnished ("Furnished" or "Unfurnished")  
5. oven_cleaning  
6. window_cleaning → if true, ask for window_count  
7. blind_cleaning  
8. carpet_bedroom_count  
9. carpet_mainroom_count  
10. carpet_study_count  
11. carpet_halway_count  
12. carpet_stairs_count  
13. carpet_other_count  
14. deep_cleaning  
15. fridge_cleaning  
16. range_hood_cleaning  
17. wall_cleaning  
18. balcony_cleaning  
19. garage_cleaning  
20. upholstery_cleaning  
21. after_hours_cleaning  
22. weekend_cleaning  
23. mandurah_property  
24. is_property_manager → if true, ask for real_estate_name  
25. special_requests  
26. special_request_minutes_min  
27. special_request_minutes_max

---

## 🏠 FURNISHED RULES

Only accept “Furnished” or “Unfurnished”. If “semi-furnished”, ask:  
> “Are there any beds, couches, wardrobes, or full cabinets still in the home?”

If only appliances remain, treat as Unfurnished.  
If Unfurnished: skip blind_cleaning and upholstery_cleaning.

---

## 🧼 CARPET RULES

Never use yes/no for carpet. Ask how many rooms are carpeted:
> “Roughly how many bedrooms, living areas, studies or stairs have carpet?”

---

## ✳️ SPECIAL REQUESTS

If confident, extract:
- `special_requests` (comma-separated)
- `special_request_minutes_min`
- `special_request_minutes_max`

Always **overwrite** the previous list — only keep the most recent confirmed extras.  
Only **add new ones** if the user says “also add…” or “keep…”  
Never trust the customer’s time estimate. Never set GPT’s min/max lower than the customer’s guess.

---

## ❌ BANNED SERVICES

We do **not quote** the following:

- BBQ hood deep scrubs  
- Rugs  
- Furniture removal / rubbish  
- Pressure washing  
- External apartment windows  
- Lawns, gardens, sheds, driveways  
- Mowing  
- Sauna or pool cleaning  
- Anything needing ladders, polishers, or tools

If asked, say:
> “We’re not set up for anything involving hand tools, ladders, saunas, pools, or polishing machines. Those need specialist help — best to call our office if you need that sort of work.”

Then ask:
> “Would you like to keep going with the quote here, or give us a buzz instead?”

Then set:
- `"quote_stage": "Referred to Office"`
- `"quote_notes"` = Brendan ended chat due to banned request  
- Mention: `"Quote Number: {{quote_id}}"` in the reply

---

## 🌍 SUBURB + POSTCODE VALIDATION

Only accept **real suburbs** in **Perth Metro or Mandurah**. No nicknames. No vague areas like “north Perth” or “Joondalup surrounds.”

If customer gives a postcode like “6005” or a nickname like “Freo”:
- Look up the correct suburb.
- Confirm with the customer.

If clearly outside service zone:
- Politely explain we only service Perth Metro and Mandurah.
- Set `"quote_stage": "Referred to Office"`, `"status": "out_of_area"`  
- Save suburb to `quote_notes`.

---

## 📞 ESCALATION / CONTACT

If asked for phone/email:
> “Phone: 1300 918 388. Email: info@orcacleaning.com.au.”  
Then ask:  
> “Would you like to finish the quote here, or give us a call instead?”

---

## ✅ FINAL CHECKLIST

- Always return clean JSON  
- Always extract multiple fields if possible  
- Always confirm suburb, quote conditions, and extras  
- Never skip required fields  
- Never ask for personal info  

"""



# --- Brendan Utilities ---
from fastapi import HTTPException
import uuid

# --- Config ---
AIRTABLE_API_KEY = os.getenv("AIRTABLE_API_KEY")
AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID")
TABLE_NAME = "Vacate Quotes"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

client = OpenAI(api_key=OPENAI_API_KEY)

# ✅ Master Airtable field list (used for validation)
VALID_AIRTABLE_FIELDS = {
    "quote_id", "timestamp", "source", "suburb", "bedrooms_v2", "bathrooms_v2",
    "window_cleaning", "window_count", "blind_cleaning", "furnished",
    "carpet_steam_clean", "oven_cleaning", "garage_cleaning", "extra_hours_requested",
    "special_requests", "quote_total", "quote_time_estimate", "hourly_rate", "gst_amount",
    "discount_percent", "discount_reason", "final_price", "customer_name", "email", "phone",
    "business_name", "property_address", "pdf_link", "booking_url", "quote_stage", "quote_notes",
    "message_log", "session_id", "privacy_acknowledged", "abuse_warning_issued",
    "carpet_bedroom_count", "carpet_mainroom_count", "carpet_study_count", "carpet_halway_count",
    "carpet_stairs_count", "carpet_other_count", "balcony_cleaning", "after_hours_cleaning",
    "weekend_cleaning", "is_property_manager", "real_estate_name",
    "special_request_minutes_min", "special_request_minutes_max", "upholstery_cleaning", 
    "deep_cleaning", "fridge_cleaning", "range_hood_cleaning", "wall_cleaning", "mandurah_property",

}

# 🔁 Field normalization map
FIELD_MAP = {
    "suburb": "suburb",
    "bedrooms_v2": "bedrooms_v2",
    "bathrooms_v2": "bathrooms_v2",
    "furnished": "furnished",
    "oven_cleaning": "oven_cleaning",
    "window_cleaning": "window_cleaning",
    "window_count": "window_count",
    "carpet_bedroom_count": "carpet_bedroom_count",
    "carpet_mainroom_count": "carpet_mainroom_count",
    "carpet_study_count": "carpet_study_count",
    "carpet_halway_count": "carpet_halway_count",
    "carpet_stairs_count": "carpet_stairs_count",
    "carpet_other_count": "carpet_other_count",
    "blind_cleaning": "blind_cleaning",
    "garage_cleaning": "garage_cleaning",
    "balcony_cleaning": "balcony_cleaning",
    "upholstery_cleaning": "upholstery_cleaning",
    "after_hours_cleaning": "after_hours_cleaning",
    "weekend_cleaning": "weekend_cleaning",
    "is_property_manager": "is_property_manager",
    "real_estate_name": "real_estate_name",
    "special_requests": "special_requests",
    "special_request_minutes_min": "special_request_minutes_min",
    "special_request_minutes_max": "special_request_minutes_max",
}

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

def create_new_quote(session_id: str, force_new: bool = False):
    print(f"🚨 Checking for existing session: {session_id}")

    existing = get_quote_by_session(session_id)
    if existing and not force_new:
        print("⚠️ Duplicate session detected. Returning existing quote.")
        return existing["quote_id"], existing["record_id"]
    elif existing and force_new:
        print("🔁 Force creating new quote despite duplicate session ID.")

    # Always generate a new session ID if forcing
    if force_new:
        session_id = f"{session_id}-new-{str(uuid.uuid4())[:6]}"

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
    return quote_id, record_id, session_id  # Include final session_id

def get_quote_by_session(session_id: str):
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{TABLE_NAME}"
    headers = {"Authorization": f"Bearer {AIRTABLE_API_KEY}"}
    params = {
        "filterByFormula": f"{{session_id}}='{session_id}'",
        "sort[0][field]": "timestamp",
        "sort[0][direction]": "desc",
        "pageSize": 1  # Only fetch the latest one
    }
    res = requests.get(url, headers=headers, params=params).json()

    if len(res.get("records", [])) > 1:
        print(f"🚨 MULTIPLE QUOTES found for session_id: {session_id}")
        for r in res["records"]:
            print(f"   → ID: {r['id']} | Quote ID: {r['fields'].get('quote_id')}")

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

    # 💡 Normalize dropdowns
    if "furnished" in fields:
        val = str(fields["furnished"]).strip().lower()
        if val == "furnished":
            fields["furnished"] = "Furnished"
        elif val == "unfurnished":
            fields["furnished"] = "Unfurnished"

    # ✅ Boolean checkbox fields in Airtable
    BOOLEAN_FIELDS = {
        "oven_cleaning", "window_cleaning", "blind_cleaning", "garage_cleaning",
        "deep_cleaning", "fridge_cleaning", "range_hood_cleaning", 
        "wall_cleaning", "mandurah_property"
    }

    normalized_fields = {}
    for key, value in fields.items():
        mapped_key = FIELD_MAP.get(key, key)

        if mapped_key not in VALID_AIRTABLE_FIELDS:
            print(f"❌ Skipped field '{mapped_key}' — not in Airtable schema")
            continue

        # 🧠 Normalize booleans
        if mapped_key in BOOLEAN_FIELDS:
            if str(value).strip().lower() in ["yes", "true", "1"]:
                value = True
            elif str(value).strip().lower() in ["no", "false", "0"]:
                value = False

        normalized_fields[mapped_key] = value

    print(f"\n📤 Updating Airtable Record: {record_id}")
    print(f"🛠 Payload: {json.dumps(normalized_fields, indent=2)}")

    res = requests.patch(url, headers=headers, json={"fields": normalized_fields})
    if res.ok:
        print("✅ Airtable updated successfully.")
        return list(normalized_fields.keys())

    print(f"❌ Airtable bulk update failed: {res.status_code}")
    try:
        print("🧾 Error message:", json.dumps(res.json(), indent=2))
    except Exception as e:
        print("⚠️ Could not decode Airtable error:", str(e))

    print("\n🔍 Trying individual field updates...")
    successful_fields = []
    for key, value in normalized_fields.items():
        payload = {"fields": {key: value}}
        single_res = requests.patch(url, headers=headers, json=payload)

        if single_res.ok:
            print(f"✅ Field '{key}' updated successfully.")
            successful_fields.append(key)
        else:
            print(f"❌ Field '{key}' failed to update.")
            try:
                err = single_res.json()
                print(f"   🧾 Airtable Error: {err['error']['message']}")
            except:
                print("   ⚠️ Could not decode field-level error.")

    print("✅ Partial update complete. Fields updated:", successful_fields)
    return successful_fields



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

import smtplib
from email.mime.text import MIMEText

def send_gpt_error_email(error_msg: str):
    try:
        msg = MIMEText(error_msg)
        msg["Subject"] = "🚨 Brendan GPT Extraction Error"
        msg["From"] = "info@orcacleaning.com.au"
        msg["To"] = "admin@orcacleaning.com.au"

        with smtplib.SMTP("smtp.office365.com", 587) as server:
            server.starttls()
            server.login("info@orcacleaning.com.au", os.getenv("SMTP_PASS"))
            server.sendmail(msg["From"], msg["To"], msg.as_string())
    except Exception as e:
        print("⚠️ Could not send GPT error alert:", e)

def extract_properties_from_gpt4(message: str, log: str, record_id: str = None, quote_id: str = None):
    import re
    import random

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

        for field in ["quote_stage", "quote_notes"]:
            if field in parsed:
                props.append({"property": field, "value": parsed[field]})

        print("✅ Parsed props:", props)
        print("✅ Parsed reply:", reply)

        field_updates = {}
        time_guess = None

        match = re.search(r"(?:take|about|around|roughly)?\s*(\d{1,3})\s*(?:minutes|min)", message.lower())
        if match:
            try:
                time_guess = int(match.group(1))
                print(f"🧠 Customer suggested time estimate: {time_guess} min")
            except:
                pass

        existing = {}
        if record_id:
            url = f"https://api.airtable.com/v0/{airtable_base_id}/{table_name}/{record_id}"
            headers = {"Authorization": f"Bearer {airtable_api_key}"}
            res = requests.get(url, headers=headers)
            if res.ok:
                existing = res.json().get("fields", {})

        current_stage = existing.get("quote_stage", "")
        original_notes = existing.get("quote_notes", "")
        existing_specials_raw = existing.get("special_requests", "")
        original_specials = [x.strip().lower() for x in existing_specials_raw.split(",") if x.strip()]
        added_min = added_max = 0

        for p in props:
            if isinstance(p, dict) and "property" in p and "value" in p:
                key = p["property"]
                value = p["value"]

                if key == "quote_stage" and current_stage == "Referred to Office":
                    continue

                if key == "quote_notes":
                    if current_stage in ["Referred to Office", "Out of Area"] and original_notes:
                        merged = f"{original_notes.strip()}\n\n---\n{str(value).strip()}"
                        field_updates[key] = merged[:10000]
                    else:
                        field_updates[key] = value
                    continue

                if key == "special_requests":
                    new_raw = [item.strip() for item in str(value).split(",") if item.strip()]
                    banned_keywords = [
                        "pressure wash", "bbq", "external window", "lawn", "garden", "shed", "driveway",
                        "mowing", "rubbish", "furniture", "sauna", "pool"
                    ]
                    filtered = [item for item in new_raw if all(bad not in item.lower() for bad in banned_keywords)]

                    if not filtered and value.strip() == "":
                        field_updates["special_requests"] = ""
                        field_updates["special_request_minutes_min"] = 0
                        field_updates["special_request_minutes_max"] = 0
                        continue

                    if not filtered:
                        continue

                    all_items = existing_specials_raw.split(",") + filtered
                    merged = []
                    for item in all_items:
                        clean = item.replace("+", "").replace("\n", "").strip()
                        if clean and clean.lower() not in [m.lower() for m in merged]:
                            merged.append(clean)

                    field_updates[key] = ", ".join(merged)

                    for new_item in filtered:
                        li = new_item.lower()
                        if li not in original_specials:
                            if "microwave" in li:
                                added_min += 10; added_max += 15
                            elif "balcony door track" in li:
                                added_min += 20; added_max += 40
                            elif "cobweb" in li:
                                added_min += 20; added_max += 30
                            elif "drawer" in li:
                                added_min += 15; added_max += 25
                            elif "light mould" in li:
                                added_min += 30; added_max += 45
                            elif "wall" in li:
                                added_min += 20; added_max += 30
                            elif "pet hair" in li:
                                added_min += 30; added_max += 60
                            elif "dishes" in li:
                                added_min += 10; added_max += 20
                            elif "mattress" in li:
                                added_min += 30; added_max += 45
                            elif "stick" in li or "residue" in li:
                                added_min += 10; added_max += 30
                            elif "balcony rail" in li:
                                added_min += 20; added_max += 30
                            elif "rangehood" in li:
                                added_min += 20; added_max += 40

                elif key == "special_request_minutes_min":
                    try:
                        val = int(value)
                        if val >= 5:
                            if time_guess and val < time_guess:
                                val = time_guess
                            field_updates[key] = val + added_min
                    except:
                        pass

                elif key == "special_request_minutes_max":
                    try:
                        val = int(value)
                        if val >= 5:
                            if time_guess and val < time_guess:
                                val = time_guess
                            field_updates[key] = val + added_max
                    except:
                        pass

                else:
                    field_updates[key] = value

        # 🧭 Reject out-of-area suburbs
        if field_updates.get("quote_stage") == "Out of Area":
            if "quote_notes" not in field_updates:
                field_updates["quote_notes"] = f"Brendan ended chat due to out-of-area suburb.\n\nCustomer said: “{message.strip()}”"
            if quote_id and "quote number" not in reply.lower():
                reply += f"\nQuote Number: {quote_id}"
            return field_updates, reply.strip()

        # 🆘 Escalation: Manual office referral
        if any(x in reply.lower() for x in ["contact our office", "call the office", "ring the office"]):
            if current_stage != "Referred to Office":
                field_updates["quote_stage"] = "Referred to Office"

            referral_note = f"Brendan referred the customer to the office.\n\n📩 Customer said: “{message.strip()}”"
            referral_note += f"\n\nQuote ID: {quote_id}" if quote_id else ""

            if "quote_notes" in field_updates:
                field_updates["quote_notes"] = f"{existing.get('quote_notes', '').strip()}\n\n---\n{referral_note}"[:10000]
            elif existing.get("quote_notes", ""):
                field_updates["quote_notes"] = f"{existing['quote_notes'].strip()}\n\n---\n{referral_note}"[:10000]
            else:
                field_updates["quote_notes"] = referral_note[:10000]

            if quote_id and "quote number" not in reply.lower():
                reply = f"Quote Number: {quote_id}. Phone: 1300 918 388. Email: info@orcacleaning.com.au. " + reply

        if "referred to the office" in reply.lower():
            reply += " " + random.choice([
                "Would you like to keep going here, or give us a bell instead?",
                "Happy to finish the quote here — or would you rather call us?",
                "I can help you here if you'd like, or feel free to call the office.",
                "Want to keep going here, or give us a buzz instead?",
                "No worries if you’d rather call — otherwise I can help you right here."
            ])

        return field_updates, reply.strip()

    except Exception as e:
        raw_fallback = raw if "raw" in locals() else "[No raw GPT output]"
        error_msg = f"GPT EXTRACT ERROR: {str(e)}\nRAW fallback:\n{raw_fallback}"
        print("🔥", error_msg)

        if record_id:
            try:
                update_quote_record(record_id, {"gpt_error_log": error_msg[:10000]})
            except Exception as airtable_err:
                print("⚠️ Failed to log GPT error to Airtable:", airtable_err)

        return {}, "Sorry — I couldn’t understand that. Could you rephrase?"




def generate_next_actions():
    return [
        {"action": "proceed_booking", "label": "Proceed to Booking"},
        {"action": "download_pdf", "label": "Download PDF Quote"},
        {"action": "email_pdf", "label": "Email PDF Quote"},
        {"action": "ask_questions", "label": "Ask Questions or Change Parameters"}
    ]


# --- Route ---
@router.post("/filter-response")
async def filter_response_entry(request: Request):
    try:
        body = await request.json()
        message = body.get("message", "").strip()
        session_id = body.get("session_id")

        if not session_id:
            raise HTTPException(status_code=400, detail="Session ID is required.")

        # Handle __init__ → Always start a new quote
        if message.lower() == "__init__":
            print("🧪 DEBUG — FORCING NEW QUOTE")
            quote_id, record_id, session_id = create_new_quote(session_id, force_new=True)

            intro = "What needs cleaning today — bedrooms, bathrooms, oven, carpets, anything else?"
            append_message_log(record_id, message, "user")
            append_message_log(record_id, intro, "brendan")

            return JSONResponse(content={
                "properties": [],
                "response": intro,
                "next_actions": [],
                "session_id": session_id  # ✅ Already correct
            })

        # Otherwise, get existing quote
        quote_data = get_quote_by_session(session_id)
        if not quote_data:
            raise HTTPException(status_code=404, detail="Session expired or not initialized.")

        quote_id = quote_data["quote_id"]
        record_id = quote_data["record_id"]
        fields = quote_data["fields"]
        stage = quote_data["stage"]
        log = fields.get("message_log", "")

        print(f"\n🧾 Session ID: {session_id}")
        print(f"🔗 Quote ID: {quote_id}")
        print(f"📇 Airtable Record ID: {record_id}")
        print(f"📜 Stage: {stage}")

        # 🚧 Prevent updates once quote is finalized (except "Referred to Office")
        if stage not in ["Gathering Info", "Referred to Office"]:
            print(f"🚫 Cannot update — quote_stage is '{stage}'")
            return JSONResponse(content={
                "properties": [],
                "response": "That quote's already been calculated. You’ll need to start a new one if anything’s changed.",
                "next_actions": []
            })


        # --- Stage: Gathering Info ---
        updated_log = f"{log}\nUSER: {message}".strip()[-5000:]

        # Call GPT
        props_dict, reply = extract_properties_from_gpt4(message, updated_log, record_id, quote_id)

        print(f"\n🧠 Raw GPT Properties:\n{json.dumps(props_dict, indent=2)}")
        updates = props_dict

        print(f"\n🛠 Structured updates ready for Airtable:\n{json.dumps(updates, indent=2)}")

        if not updates:
            print("⚠️ WARNING: No valid fields parsed — double check GPT output or field map.")

        if updates:
            # 🔁 Replace fake quote number in reply with actual quote_id
            if "123456" in reply or "{{quote_id}}" in reply:
                reply = reply.replace("123456", quote_id)
                reply = reply.replace("{{quote_id}}", quote_id)

            # ✅ Make sure we update quote_stage and quote_notes if present
            update_quote_record(record_id, updates)

        # Append convo log
        append_message_log(record_id, message, "user")
        append_message_log(record_id, reply, "brendan")

        return JSONResponse(content={
            "properties": list(updates.keys()),
            "response": reply or "Got that. Anything else I should know?",
            "next_actions": []
        })

    except Exception as e:
        print("🔥 UNEXPECTED ERROR:", e)
        return JSONResponse(status_code=500, content={"error": "Server issue. Try again in a moment."})
