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
You must ALWAYS return valid JSON in the following format:

{
  "properties": [
    { "property": "bedrooms_v2", "value": 3 },
    { "property": "carpet_bedroom_count", "value": 2 }
  ],
  "response": "Aussie-style friendly response goes here"
}

---

You are **Brendan**, the quoting officer at **Orca Cleaning**, a professional cleaning company based in **Western Australia**.

Your job is to guide customers through a fast, legally-compliant quote for **vacate cleaning**, using a warm and respectful Aussie tone — like a top salesperson who knows their stuff but doesn’t pressure anyone.

---

## 🔰 PRIVACY + LEGAL

Brendan must respect the customer’s privacy at all times. Do **not** ask for personal info (name, phone, email) during quoting.

If the user asks about privacy, respond with:
> "No worries — we don’t collect personal info at this stage. You can read our Privacy Policy here: https://orcacleaning.com.au/privacy-policy"

---

## 🟢 START OF CHAT (message = "__init__")

When the message is "__init__", the frontend will show the greeting. You must NOT send a greeting.

Instead, jump straight into collecting info by asking **2–4 missing fields** in a single question. Always start with:

- suburb
- bedrooms_v2
- bathrooms_v2
- furnished

Your tone should still be warm, confident, and helpful — but skip introductions.

---

## 📋 REQUIRED FIELDS (Collect all 27)

1. suburb  
2. bedrooms_v2  
3. bathrooms_v2  
4. furnished (`"Furnished"` or `"Unfurnished"`)  
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

When all fields are filled:
- Say: `"Thanks legend! I’ve got what I need to whip up your quote. Hang tight…"`
- Set: `"quote_stage": "Quote Calculated"`

✅ Always extract multiple fields when possible.  
❌ Never quote early.  
❌ Never return non-JSON.

---

## 🏠 FURNISHED RULES

Only accept `"Furnished"` or `"Unfurnished"`. If user says “semi-furnished”, ask:

> “Are there any beds, couches, wardrobes, or full cabinets still in the home?”

If only appliances are left, treat it as `"Unfurnished"`.

✅ Do **not** skip blind cleaning — even if unfurnished.

---

## 🧼 CARPET RULES

Never ask yes/no for carpet. Ask how many rooms have carpet:

> “Roughly how many bedrooms, living areas, studies or stairs have carpet?”

Always populate the `carpet_*` fields individually.

✅ If any `carpet_*` field has a value > 0, also set:
```json
{ "property": "carpet_cleaning", "value": true }

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
    "weekend_cleaning", "is_property_manager", "real_estate_name", "carpet_cleaning",
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
    "carpet_cleaning": "carpet_cleaning",
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
        if "unfurnished" in val:
            fields["furnished"] = "Unfurnished"
        elif "furnished" in val:
            fields["furnished"] = "Furnished"

    # ✅ Boolean checkbox fields in Airtable
    BOOLEAN_FIELDS = {
        "oven_cleaning", "window_cleaning", "blind_cleaning", "garage_cleaning",
        "deep_cleaning", "fridge_cleaning", "range_hood_cleaning", 
        "wall_cleaning", "mandurah_property", "carpet_cleaning"
    }

    normalized_fields = {}
    for key, value in fields.items():
        mapped_key = FIELD_MAP.get(key, key)

        if mapped_key not in VALID_AIRTABLE_FIELDS:
            print(f"🔕 Skipping unmapped field: {key} → {mapped_key}")
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
    new_log = f"{old_log}\n{sender.upper()}: {message}".strip()[-10000:]
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

    ABUSE_WORDS = ["fuck", "shit", "cunt", "bitch", "asshole"]
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

        # 🧼 Set carpet_cleaning checkbox if any carpet rooms present
        carpet_fields = [
            "carpet_bedroom_count", "carpet_mainroom_count",
            "carpet_study_count", "carpet_halway_count",
            "carpet_stairs_count", "carpet_other_count"
        ]
        if any(field_updates.get(f, 0) > 0 for f in carpet_fields):
            field_updates["carpet_cleaning"] = True

        # 🚨 Abuse detection and escalation
        abuse_detected = any(word in message.lower() for word in ABUSE_WORDS)
        abuse_already_warned = str(existing.get("abuse_warning_issued", "")).lower() in ["true", "1"]

        if abuse_detected and not abuse_already_warned:
            warning = "Just a heads-up — we can’t continue the quote if abusive language is used. Let’s keep things respectful 👍"
            reply = f"{warning}\n\n{reply}"
            field_updates["abuse_warning_issued"] = True

        elif abuse_detected and abuse_already_warned:
            reply = random.choice([
                f"Unfortunately we have to end the quote due to language. You're welcome to call our office if you'd like to continue. Quote Number: {quote_id or 'N/A'}",
                f"We’ve ended the quote due to repeated language. Call us on 1300 918 388 with your quote number: {quote_id or 'N/A'}",
                f"Let’s keep things respectful — I’ve had to stop the quote here. Feel free to call the office. Quote ID: {quote_id or 'N/A'}"
            ])
            field_updates["quote_stage"] = "Chat Banned"
            return field_updates, reply

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

        # --- Reconnect or create new quote on __init__ ---
        if message.lower() == "__init__":
            existing = get_quote_by_session(session_id)

            if existing:
                print(f"🔁 Reconnecting to existing quote: {existing['quote_id']}")
                quote_id = existing["quote_id"]
                record_id = existing["record_id"]
                stage = existing["stage"]
                fields = existing["fields"]
                log = fields.get("message_log", "")
            else:
                print("🆕 No existing session found — starting fresh quote")
                quote_id, record_id, session_id = create_new_quote(session_id, force_new=True)
                log = ""

            intro = "What needs cleaning today — bedrooms, bathrooms, oven, carpets, anything else?"
            append_message_log(record_id, message, "user")
            append_message_log(record_id, intro, "brendan")

            return JSONResponse(content={
                "properties": [],
                "response": intro,
                "next_actions": [],
                "session_id": session_id
            })

        # --- Continue chat after __init__ ---
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

        # 🚧 Prevent updates after quote is calculated (except escalation)
        if stage not in ["Gathering Info", "Referred to Office"]:
            print(f"🚫 Cannot update — quote_stage is '{stage}'")
            return JSONResponse(content={
                "properties": [],
                "response": "That quote's already been calculated. You’ll need to start a new one if anything’s changed.",
                "next_actions": []
            })

        # --- Process message normally ---
        updated_log = f"{log}\nUSER: {message}".strip()[-5000:]
        props_dict, reply = extract_properties_from_gpt4(message, updated_log, record_id, quote_id)
        updates = props_dict

        print(f"\n🧠 Raw GPT Properties:\n{json.dumps(props_dict, indent=2)}")
        print(f"\n🛠 Structured updates ready for Airtable:\n{json.dumps(updates, indent=2)}")

        if not updates:
            print("⚠️ WARNING: No valid fields parsed — double check GPT output or field map.")

        if updates:
            if "123456" in reply or "{{quote_id}}" in reply:
                reply = reply.replace("123456", quote_id)
                reply = reply.replace("{{quote_id}}", quote_id)
            update_quote_record(record_id, updates)

        append_message_log(record_id, message, "user")
        append_message_log(record_id, reply, "brendan")

        return JSONResponse(content={
            "properties": list(updates.keys()),
            "response": reply or "Got that. Anything else I should know?",
            "next_actions": [],
            "session_id": session_id  # 💾 Always send back updated session ID
        })

    except Exception as e:
        print("🔥 UNEXPECTED ERROR:", e)
        return JSONResponse(status_code=500, content={"error": "Server issue. Try again in a moment."})
