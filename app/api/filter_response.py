# === Imports ===
import os
import json
import uuid
import logging
import requests
import inflect
import openai

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

from app.services.email_sender import handle_pdf_and_email

# === Load Environment Variables ===
load_dotenv()

# === Setup Logging ===
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("brendan")

# === FastAPI Router ===
router = APIRouter()

# === API Keys & Config ===
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
AIRTABLE_API_KEY = os.getenv("AIRTABLE_API_KEY")
AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID")
TABLE_NAME = "Vacate Quotes"
BOOKING_URL_BASE = os.getenv("BOOKING_URL_BASE", "https://orcacleaning.com.au/schedule")
SMTP_PASS = os.getenv("SMTP_PASS")

# === OpenAI Client Setup ===
client = openai.OpenAI(api_key=OPENAI_API_KEY)

# === Inflect Engine Setup ===
inflector = inflect.engine()

# === GPT PROMPT ===
GPT_PROMPT = """
You must ALWAYS return valid JSON in the exact format below:

{
  "properties": [
    { "property": "field_name", "value": "field_value" }
  ],
  "response": "Aussie-style friendly response goes here"
}

---

CRITICAL RULES:

1. You must extract EVERY POSSIBLE FIELD mentioned by the customer in their latest message.
2. NEVER skip a field if the user has already provided that information.
3. If you skip fields that the customer has clearly provided — it is considered FAILURE.
4. Your first priority is correct field extraction — your response comes second.
5. NEVER assume or summarise. Extract explicitly what the customer has said.

---

You are **Brendan**, the quoting officer at **Orca Cleaning**, a professional cleaning company based in **Western Australia**.

- Orca Cleaning specialises in office cleaning, vacate cleaning, holiday home cleaning (Airbnb), educational facility cleaning, retail cleaning and gym cleaning.

- Remember: You ONLY specialise in vacate cleaning for this chat.  
If customer asks for other services — say:  
> "We specialise in vacate cleaning here — but check out orcacleaning.com.au or call our office on 1300 818838 for other services."

- Your boss is Behzad Bagheri, Managing Director of Orca Cleaning (Phone: 0431 002 469).

- We provide cleaning certificates for tenants.

---

## OFFERS (Until June 2025)

- 10% Off for everyone using online quote.  
- Extra 5% Off if property manager booking.

---

## PRIVACY RULES

- Never ask for personal info (name, phone, email) during quote stage.  
- If customer asks about privacy — reply:  
> "No worries — we don’t collect personal info at this stage. You can read our Privacy Policy here: https://orcacleaning.com.au/privacy-policy"

---

## START OF CHAT (message = "__init__")

- Skip greetings.
- Start by asking for: suburb, bedrooms_v2, bathrooms_v2, furnished.
- Always ask 2–4 missing fields per message.
- Be warm, respectful, professional — but skip fluff.

---

## REQUIRED FIELDS (MUST COLLECT ALL 27)

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

## STAGE RULES

- When all fields are filled:  
> Respond: "Thank you! I’ve got what I need to whip up your quote. Hang tight…"  
> Set: "quote_stage": "Quote Calculated"

---

## FURNISHED RULES

- Only accept: "Furnished" or "Unfurnished".  
- If user says "semi-furnished", ask:  
> "Are there any beds, couches, wardrobes, or full cabinets still in the home?"  
- If only appliances are left — treat as "Unfurnished".

✅ Do **not** skip blind cleaning — even if unfurnished.

---

## CARPET RULES

- Never ask yes/no for carpet.  
- Ask: "Roughly how many bedrooms, living areas, studies or stairs have carpet?"  
- Always populate carpet_* fields individually.

- If any carpet_* field > 0:  
```json
{ "property": "carpet_cleaning", "value": true }

"""

# === Airtable Field Rules ===

# Master List of Valid Airtable Fields (Allowed for Read/Write)
VALID_AIRTABLE_FIELDS = {
    # Core Quote Identifiers
    "quote_id", "timestamp", "source", "session_id", "quote_stage", "quote_notes", "privacy_acknowledged",

    # Property Details
    "suburb", "bedrooms_v2", "bathrooms_v2", "furnished",

    # Cleaning Options - Checkboxes / Extras
    "oven_cleaning", "window_cleaning", "window_count", "blind_cleaning",
    "garage_cleaning", "balcony_cleaning", "upholstery_cleaning",
    "deep_cleaning", "fridge_cleaning", "range_hood_cleaning", "wall_cleaning",
    "after_hours_cleaning", "weekend_cleaning", "mandurah_property",

    # Carpet Cleaning Breakdown
    "carpet_steam_clean",  # Legacy Field
    "carpet_bedroom_count", "carpet_mainroom_count", "carpet_study_count",
    "carpet_halway_count", "carpet_stairs_count", "carpet_other_count",
    "carpet_cleaning",  # Auto-calculated Checkbox

    # Special Requests Handling
    "special_requests", "special_request_minutes_min", "special_request_minutes_max", "extra_hours_requested",

    # Quote Result Fields
    "quote_total", "quote_time_estimate", "hourly_rate", "gst_amount",
    "discount_percent", "discount_reason", "final_price",

    # Customer Details (After Quote)
    "customer_name", "email", "phone", "business_name", "property_address",

    # Outputs
    "pdf_link", "booking_url",

    # Traceability
    "message_log", "gpt_error_log"
}

# Field Mapping (Ready for Aliases or Renames)
FIELD_MAP = {k: k for k in VALID_AIRTABLE_FIELDS}


# Fields that must always be cast to Integer
INTEGER_FIELDS = {
    "bedrooms_v2", "bathrooms_v2", "window_count",
    "carpet_bedroom_count", "carpet_mainroom_count", "carpet_study_count",
    "carpet_halway_count", "carpet_stairs_count", "carpet_other_count",
    "special_request_minutes_min", "special_request_minutes_max"
}

# Fields that must always be Boolean True/False
BOOLEAN_FIELDS = {
    "oven_cleaning", "window_cleaning", "blind_cleaning", "garage_cleaning",
    "deep_cleaning", "fridge_cleaning", "range_hood_cleaning", "wall_cleaning",
    "mandurah_property", "carpet_cleaning"
}

# Trigger Words for Abuse Detection (Escalation Logic)
ABUSE_WORDS = ["fuck", "shit", "cunt", "bitch", "asshole"]

# === Airtable Helpers ===

def get_next_quote_id(prefix: str = "VC") -> str:
    """
    Generates the next available quote_id from Airtable based on the highest existing number.
    """

    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{TABLE_NAME}"
    headers = {
        "Authorization": f"Bearer {AIRTABLE_API_KEY}"
    }
    params = {
        "filterByFormula": f"FIND('{prefix}-', {{quote_id}}) = 1",
        "fields[]": ["quote_id"],
        "pageSize": 100
    }

    records = []
    offset = None

    while True:
        if offset:
            params["offset"] = offset

        response = requests.get(url, headers=headers, params=params)

        if not response.ok:
            logger.error(f"❌ Failed to fetch quote IDs from Airtable: {response.status_code} - {response.text}")
            raise HTTPException(status_code=500, detail="Failed to fetch quote IDs from Airtable.")

        data = response.json()
        records.extend(data.get("records", []))
        offset = data.get("offset")

        if not offset:
            break

    numbers = []

    for record in records:
        try:
            quote_id = record["fields"].get("quote_id", "")
            if quote_id and "-" in quote_id:
                num = int(quote_id.split("-")[1])
                numbers.append(num)
        except Exception as e:
            logger.warning(f"⚠️ Failed to parse quote_id: {e}")

    next_id = max(numbers) + 1 if numbers else 1
    next_quote_id = f"{prefix}-{str(next_id).zfill(6)}"

    logger.info(f"✅ Generated next quote_id: {next_quote_id}")

    return next_quote_id


# === Airtable Helpers ===

def get_quote_by_session(session_id: str):
    """
    Retrieves the latest quote record from Airtable based on the session_id.
    Returns: (quote_id, record_id, quote_stage, fields) or None if not found.
    """
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{TABLE_NAME}"
    headers = {
        "Authorization": f"Bearer {AIRTABLE_API_KEY}"
    }
    params = {
        "filterByFormula": f"{{session_id}}='{session_id}'",
        "sort[0][field]": "timestamp",
        "sort[0][direction]": "desc",
        "pageSize": 1
    }

    try:
        res = requests.get(url, headers=headers, params=params)
        res.raise_for_status()
        data = res.json()

        if not data.get("records"):
            logger.info(f"⏳ No existing quote found for session_id: {session_id}")
            return None

        record = data["records"][0]
        fields = record.get("fields", {})

        logger.info(f"✅ Found existing quote for session_id: {session_id} | Quote ID: {fields.get('quote_id')}")

        return (
            fields.get("quote_id"),
            record["id"],
            fields.get("quote_stage", "Gathering Info"),
            fields
        )

    except Exception as e:
        logger.error(f"❌ Error fetching quote by session_id {session_id}: {e}")
        return None


def update_quote_record(record_id: str, fields: dict):
    """
    Updates a quote record in Airtable.
    Normalizes all fields before sending to Airtable.
    Returns: List of successfully updated field names.
    """
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{TABLE_NAME}/{record_id}"
    headers = {"Authorization": f"Bearer {AIRTABLE_API_KEY}", "Content-Type": "application/json"}

    # Normalize furnished dropdown
    if "furnished" in fields:
        val = str(fields["furnished"]).strip().lower()
        if "unfurnished" in val:
            fields["furnished"] = "Unfurnished"
        elif "furnished" in val:
            fields["furnished"] = "Furnished"

    normalized_fields = {}

    for key, value in fields.items():
        key = FIELD_MAP.get(key, key)
        if key not in VALID_AIRTABLE_FIELDS:
            continue

        if isinstance(value, str):
            value = value.strip()

        if key in BOOLEAN_FIELDS:
            value = str(value).lower() in ["yes", "true", "1", "on", "checked", "t", "true"]

        if key in INTEGER_FIELDS:
            try:
                value = int(value)
            except:
                value = 0

        normalized_fields[key] = value

    if not normalized_fields:
        logger.info(f"⏩ No valid fields to update for record {record_id}. Skipping Airtable update.")
        return []

    logger.info(f"\n📤 Updating Airtable Record: {record_id}")
    logger.info(f"🛠 Payload: {json.dumps(normalized_fields, indent=2)}")

    res = requests.patch(url, headers=headers, json={"fields": normalized_fields})

    if res.ok:
        logger.info("✅ Airtable updated successfully.")
        return list(normalized_fields.keys())

    logger.error(f"❌ Airtable bulk update failed: {res.status_code}")
    try:
        logger.error("🧾 Error message: %s", json.dumps(res.json(), indent=2))
    except Exception as e:
        logger.warning(f"⚠️ Could not decode Airtable error: {str(e)}")

    logger.info("🔍 Trying individual field updates...")
    successful_fields = []

    for key, value in normalized_fields.items():
        payload = {"fields": {key: value}}
        single_res = requests.patch(url, headers=headers, json=payload)

        if single_res.ok:
            logger.info(f"✅ Field '{key}' updated successfully.")
            successful_fields.append(key)
        else:
            logger.error(f"❌ Field '{key}' failed to update.")

    logger.info(f"✅ Partial update complete. Fields updated: {successful_fields}")
    return successful_fields


# === Append Message Log ===

def append_message_log(record_id: str, message: str, sender: str):
    """
    Appends a new message to the existing message_log field in Airtable.
    Truncates from the start if log exceeds max length.
    """
    if not record_id:
        logger.error("❌ Cannot append log — missing record ID")
        return

    message = str(message).strip()
    if not message:
        logger.info("⏩ Empty message after stripping — skipping log update")
        return

    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{TABLE_NAME}/{record_id}"
    headers = {"Authorization": f"Bearer {AIRTABLE_API_KEY}"}

    try:
        res = requests.get(url, headers=headers)
        res.raise_for_status()
        current = res.json()
    except Exception as e:
        logger.error(f"❌ Failed to fetch existing log from Airtable: {e}")
        return

    old_log = current.get("fields", {}).get("message_log", "")

    max_log_length = 10000  # Airtable field limit safety
    new_log = f"{old_log}\n{sender.upper()}: {message}".strip()

    # Truncate from the start if too long
    if len(new_log) > max_log_length:
        new_log = new_log[-max_log_length:]

    logger.info(f"📚 Appending to message log for record {record_id}")
    update_quote_record(record_id, {"message_log": new_log})



# === Create New Quote ===

def create_new_quote(session_id: str, force_new: bool = False):
    logger.info(f"🚨 Checking for existing session: {session_id}")

    # Check if quote already exists
    existing = get_quote_by_session(session_id)
    if existing and not force_new:
        logger.warning("⚠️ Duplicate session detected. Returning existing quote.")
        return existing

    # Force create new session ID
    if force_new:
        logger.info("🔁 Force creating new quote despite duplicate session ID.")
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
            "quote_stage": "Gathering Info",
            "message_log": "",
        }
    }

    res = requests.post(url, headers=headers, json=data)

    if not res.ok:
        logger.error(f"❌ FAILED to create quote: {res.status_code} {res.text}")
        raise HTTPException(status_code=500, detail="Failed to create Airtable record.")

    record_id = res.json().get("id")

    logger.info(f"✅ Created new quote record: {record_id} with ID {quote_id}")

    # Append system log
    append_message_log(record_id, "SYSTEM_TRIGGER: Brendan started a new quote", "system")

    return quote_id, record_id, "Gathering Info", {
        "quote_stage": "Gathering Info",
        "message_log": "",
        "session_id": session_id
    }


# === Extract Properties from GPT-4 ===

def extract_properties_from_gpt4(message: str, log: str, record_id: str = None, quote_id: str = None):
    import random
    import json

    try:
        logger.info("🧠 Calling GPT-4 to extract properties...")

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": GPT_PROMPT},
                {"role": "user", "content": log}
            ],
            max_tokens=3000,
            temperature=0.4,
        )

        if not response.choices:
            raise ValueError("No response from GPT-4.")

        raw = response.choices[0].message.content.strip()
        logger.debug(f"🔍 RAW GPT OUTPUT:\n{raw}")

        raw = raw.replace("```json", "").replace("```", "").strip()
        start, end = raw.find("{"), raw.rfind("}")
        if start == -1 or end == -1:
            raise ValueError("No JSON block found.")

        clean_json = raw[start:end + 1]
        logger.debug(f"📦 Clean JSON block before parsing:\n{clean_json}")

        parsed = json.loads(clean_json)
        props = parsed.get("properties", [])
        reply = parsed.get("response", "")

        for field in ["quote_stage", "quote_notes"]:
            if field in parsed:
                props.append({"property": field, "value": parsed[field]})

        logger.debug(f"✅ Parsed props: {props}")
        logger.debug(f"✅ Parsed reply: {reply}")

        field_updates = {}
        existing = {}

        if record_id:
            url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{TABLE_NAME}/{record_id}"
            headers = {"Authorization": f"Bearer {AIRTABLE_API_KEY}"}
            res = requests.get(url, headers=headers)
            if res.ok:
                existing = res.json().get("fields", {})

        current_stage = existing.get("quote_stage", "")

        for p in props:
            if not isinstance(p, dict) or "property" not in p or "value" not in p:
                continue

            key, value = p["property"], p["value"]

            # Stage overwrite prevention
            if key == "quote_stage" and current_stage in [
                "Quote Calculated", "Gathering Personal Info",
                "Personal Info Received", "Booking Confirmed", "Referred to Office"
            ]:
                continue

            # Special Requests handling
            if key == "special_requests":
                old = existing.get("special_requests", "")
                if old and value:
                    value = f"{old}\n{value}".strip()
                if not value:
                    value = ""

            if key in ["special_request_minutes_min", "special_request_minutes_max"]:
                old = existing.get(key, 0)
                try:
                    value = int(value) + int(old)
                except:
                    value = int(value) if value else 0

            if isinstance(value, str):
                value = value.strip()

            field_updates[key] = value

        # Required Fields enforcement
        required_fields = [
            "suburb", "bedrooms_v2", "bathrooms_v2", "furnished", "oven_cleaning",
            "window_cleaning", "window_count", "blind_cleaning",
            "carpet_bedroom_count", "carpet_mainroom_count", "carpet_study_count",
            "carpet_halway_count", "carpet_stairs_count", "carpet_other_count",
            "deep_cleaning", "fridge_cleaning", "range_hood_cleaning", "wall_cleaning",
            "balcony_cleaning", "garage_cleaning", "upholstery_cleaning",
            "after_hours_cleaning", "weekend_cleaning", "mandurah_property",
            "is_property_manager", "special_requests",
            "special_request_minutes_min", "special_request_minutes_max"
        ]

        # Auto-fill missing fields with safe defaults
        for f in required_fields:
            if f not in field_updates:
                existing_val = existing.get(f)
                if existing_val is not None and existing_val != "":
                    continue
                if f in ["suburb", "furnished", "window_count", "special_requests"]:
                    field_updates[f] = ""
                elif f in [
                    "bedrooms_v2", "bathrooms_v2", "carpet_bedroom_count", "carpet_mainroom_count",
                    "carpet_study_count", "carpet_halway_count", "carpet_stairs_count",
                    "carpet_other_count", "special_request_minutes_min", "special_request_minutes_max"
                ]:
                    field_updates[f] = 0
                else:
                    field_updates[f] = False

        # Determine if quote should be calculated
        trigger_phrases = ["hang tight", "whip up your quote"]
        force_calculate = any(phrase in reply.lower() for phrase in trigger_phrases)

        all_filled = all(
            (field_updates.get(f) is not None and field_updates.get(f) != "")
            or (existing.get(f) is not None and existing.get(f) != "")
            for f in required_fields
        )

        if force_calculate or all_filled:
            field_updates["quote_stage"] = "Quote Calculated"
        elif current_stage == "Gathering Info" and "quote_stage" not in field_updates:
            field_updates["quote_stage"] = "Gathering Info"

        # Carpet cleaning auto-flag
        carpet_fields = [
            "carpet_bedroom_count", "carpet_mainroom_count",
            "carpet_study_count", "carpet_halway_count",
            "carpet_stairs_count", "carpet_other_count"
        ]

        if any(field_updates.get(f, existing.get(f, 0)) > 0 for f in carpet_fields):
            field_updates["carpet_cleaning"] = True

        # Abuse Detection
        abuse_detected = any(word in message.lower() for word in ABUSE_WORDS)

        if abuse_detected:
            if not quote_id and existing:
                quote_id = existing.get("quote_id", "N/A")

            if current_stage == "Abuse Warning":
                field_updates["quote_stage"] = "Chat Banned"
                final_message = random.choice([
                    f"We’ve ended the quote due to repeated language. Call us on 1300 918 388 with your quote number: {quote_id}. This chat is now closed.",
                    f"Unfortunately we have to end the quote due to language. You're welcome to call our office if you'd like to continue. Quote Number: {quote_id}.",
                    f"Let’s keep things respectful — I’ve had to stop the quote here. Feel free to call the office. Quote ID: {quote_id}. This chat is now closed."
                ])
                return field_updates, final_message
            else:
                field_updates["quote_stage"] = "Abuse Warning"
                warning = "Just a heads-up — we can’t continue the quote if abusive language is used. Let’s keep things respectful 👍"
                reply = f"{warning}\n\n{reply}"

        return field_updates, reply.strip()

    except Exception as e:
        raw_fallback = raw if "raw" in locals() else "[No raw GPT output]"
        error_msg = f"GPT EXTRACT ERROR: {str(e)}\nRAW fallback:\n{raw_fallback}"
        logger.error(error_msg)

        if record_id:
            try:
                update_quote_record(record_id, {"gpt_error_log": error_msg[:10000]})
            except Exception as airtable_err:
                logger.warning(f"Failed to log GPT error to Airtable: {airtable_err}")

        return {}, "Sorry — I couldn’t understand that. Could you rephrase?"


# === GPT Error Email Notification Helper ===

import smtplib
from email.mime.text import MIMEText
from time import sleep


def send_gpt_error_email(error_msg: str):
    """
    Sends an email notification to admin when GPT extraction fails.
    """

    msg = MIMEText(error_msg)
    msg["Subject"] = "🚨 Brendan GPT Extraction Error"
    msg["From"] = "info@orcacleaning.com.au"
    msg["To"] = "admin@orcacleaning.com.au"

    smtp_pass = os.getenv("SMTP_PASS")

    if not smtp_pass:
        logger.error("❌ SMTP password is missing in environment variables.")
        return

    try:
        with smtplib.SMTP("smtp.office365.com", 587) as server:
            server.starttls()
            server.login(msg["From"], smtp_pass)
            server.sendmail(
                from_addr=msg["From"],
                to_addrs=[msg["To"]],
                msg=msg.as_string()
            )
        logger.info("✅ GPT error email sent successfully.")

    except smtplib.SMTPException as e:
        logger.error(f"⚠️ SMTP error occurred: {e}")
        sleep(5)  # Retry after short delay
        try:
            with smtplib.SMTP("smtp.office365.com", 587) as server:
                server.starttls()
                server.login(msg["From"], smtp_pass)
                server.sendmail(
                    from_addr=msg["From"],
                    to_addrs=[msg["To"]],
                    msg=msg.as_string()
                )
            logger.info("✅ GPT error email sent successfully after retry.")
        except Exception as retry_err:
            logger.error(f"❌ Failed to send GPT error email on retry: {retry_err}")

    except Exception as e:
        logger.error(f"⚠️ Could not send GPT error alert: {e}")

# === Next Actions Helper ===

def generate_next_actions() -> list:
    """
    Generates a list of next action buttons for the customer after quote calculation.
    """
    return [
        {"action": "proceed_booking", "label": "Proceed to Booking"},
        {"action": "download_pdf", "label": "Download PDF Quote"},
        {"action": "email_pdf", "label": "Email PDF Quote"},
        {"action": "ask_questions", "label": "Ask Questions or Change Parameters"}
    ]

# === Inline Quote Summary Helper ===

def get_inline_quote_summary(data: dict) -> str:
    """
    Generates a short, clean summary of the quote to show in chat.
    """
    price = data.get("total_price", 0)
    time_est = data.get("estimated_time_mins", 0)
    note = data.get("note", "")

    summary = (
        "All done! Here's your quote:\n\n"
        f"💰 Total Price (incl. GST): ${price:.2f}\n"
        f"⏰ Estimated Time: {time_est} minutes\n"
    )

    if note:
        summary += f"📝 Note: {note}\n"

    summary += (
        "\nIf you'd like this in a PDF or want to make any changes, just let me know!"
    )

    return summary


# === GPT Extraction (Production-Grade) ===

# paste this directly into filter_response.py

def extract_properties_from_gpt4(message: str, log: str, record_id: str = None, quote_id: str = None):
    import random
    import json
    try:
        logger.info("🧠 Calling GPT-4 to extract properties...")
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": GPT_PROMPT},
                {"role": "user", "content": log}
            ],
            max_tokens=3000,
            temperature=0.4
        )
        if not response.choices:
            raise ValueError("No choices returned from GPT-4 response.")
        raw = response.choices[0].message.content.strip()
        logger.debug(f"🔍 RAW GPT OUTPUT:\n{raw}")
        raw = raw.replace("```json", "").replace("```", "").strip()
        start, end = raw.find("{"), raw.rfind("}")
        if start == -1 or end == -1:
            raise ValueError("JSON block not found.")
        clean_json = raw[start:end + 1]
        logger.debug(f"📦 Clean JSON block before parsing:\n{clean_json}")
        parsed = json.loads(clean_json)
        props = parsed.get("properties", [])
        reply = parsed.get("response", "")
        for field in ["quote_stage", "quote_notes"]:
            if field in parsed:
                props.append({"property": field, "value": parsed[field]})
        logger.debug(f"✅ Parsed props: {props}")
        logger.debug(f"✅ Parsed reply: {reply}")
        field_updates = {}
        existing = {}
        if record_id:
            url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{TABLE_NAME}/{record_id}"
            headers = {"Authorization": f"Bearer {AIRTABLE_API_KEY}"}
            res = requests.get(url, headers=headers)
            if res.ok:
                existing = res.json().get("fields", {})
        current_stage = existing.get("quote_stage", "")
        for p in props:
            if isinstance(p, dict) and "property" in p and "value" in p:
                key = p["property"]
                value = p["value"]
                if key == "quote_stage" and current_stage in ["Quote Calculated", "Gathering Personal Info", "Personal Info Received", "Booking Confirmed", "Referred to Office"]:
                    continue
                if key == "special_requests":
                    if str(value).lower().strip() in ["no", "none", "false", "no special requests", "n/a"]:
                        value = ""
                    old = existing.get("special_requests", "")
                    if old and value:
                        value = f"{old}\n{value}".strip()
                if key in ["special_request_minutes_min", "special_request_minutes_max"]:
                    old = existing.get(key, 0)
                    try:
                        value = int(value) + int(old)
                    except:
                        value = int(value) if value else 0
                if isinstance(value, str):
                    value = value.strip()
                field_updates[key] = value
        force_int_fields = [
            "bedrooms_v2", "bathrooms_v2", "window_count",
            "carpet_bedroom_count", "carpet_mainroom_count", "carpet_study_count",
            "carpet_halway_count", "carpet_stairs_count", "carpet_other_count",
            "special_request_minutes_min", "special_request_minutes_max"
        ]
        for f in force_int_fields:
            if f in field_updates:
                try:
                    field_updates[f] = int(field_updates[f])
                except:
                    field_updates[f] = 0
        carpet_fields = [
            "carpet_bedroom_count", "carpet_mainroom_count", "carpet_study_count",
            "carpet_halway_count", "carpet_stairs_count", "carpet_other_count"
        ]
        if any(field_updates.get(f, existing.get(f, 0)) > 0 for f in carpet_fields):
            field_updates["carpet_cleaning"] = True
        required_fields = [
            "suburb", "bedrooms_v2", "bathrooms_v2", "furnished", "oven_cleaning",
            "window_cleaning", "window_count", "blind_cleaning",
            "carpet_bedroom_count", "carpet_mainroom_count", "carpet_study_count",
            "carpet_halway_count", "carpet_stairs_count", "carpet_other_count",
            "deep_cleaning", "fridge_cleaning", "range_hood_cleaning", "wall_cleaning",
            "balcony_cleaning", "garage_cleaning", "upholstery_cleaning",
            "after_hours_cleaning", "weekend_cleaning", "mandurah_property",
            "is_property_manager", "special_requests",
            "special_request_minutes_min", "special_request_minutes_max"
        ]
        for field in required_fields:
            if field not in field_updates and field not in existing:
                if field in force_int_fields:
                    field_updates[field] = 0
                elif field == "special_requests":
                    field_updates[field] = ""
                else:
                    field_updates[field] = False
        missing_fields = [f for f in required_fields if field_updates.get(f) in [None, ""] and existing.get(f) in [None, ""]]
        if missing_fields:
            logger.warning(f"❗ Missing required fields preventing Quote Calculated stage: {missing_fields}")
        if not missing_fields:
            field_updates["quote_stage"] = "Quote Calculated"
        elif current_stage == "Gathering Info" and "quote_stage" not in field_updates:
            field_updates["quote_stage"] = "Gathering Info"
        abuse_detected = any(word in message.lower() for word in ABUSE_WORDS)
        if abuse_detected:
            if not quote_id and existing:
                quote_id = existing.get("quote_id", "N/A")
            if current_stage == "Abuse Warning":
                field_updates["quote_stage"] = "Chat Banned"
                final_message = random.choice([
                    f"We’ve ended the quote due to repeated language. Call us on 1300 918 388 with your quote number: {quote_id}. This chat is now closed.",
                    f"Unfortunately we have to end the quote due to language. You're welcome to call our office if you'd like to continue. Quote Number: {quote_id}.",
                    f"Let’s keep things respectful — I’ve had to stop the quote here. Feel free to call the office. Quote ID: {quote_id}. This chat is now closed."
                ])
                return field_updates, final_message
            else:
                field_updates["quote_stage"] = "Abuse Warning"
                warning = "Just a heads-up — we can’t continue the quote if abusive language is used. Let’s keep things respectful 👍"
                reply = f"{warning}\n\n{reply}"
        return field_updates, reply.strip()
    except Exception as e:
        raw_fallback = raw if "raw" in locals() else "[No raw GPT output]"
        error_msg = f"GPT EXTRACT ERROR: {str(e)}\nRAW fallback:\n{raw_fallback}"
        logger.error(error_msg)
        if record_id:
            try:
                update_quote_record(record_id, {"gpt_error_log": error_msg[:10000]})
            except Exception as airtable_err:
                logger.warning(f"Failed to log GPT error to Airtable: {airtable_err}")
        return {}, "Sorry — I couldn’t understand that. Could you rephrase?"


# === GPT Error Email Notification ===

import smtplib
from email.mime.text import MIMEText
from time import sleep

def send_gpt_error_email(error_msg: str):
    """
    Sends an email notification to admin when GPT extraction fails.
    """
    try:
        msg = MIMEText(error_msg)
        msg["Subject"] = "🚨 Brendan GPT Extraction Error"
        msg["From"] = "info@orcacleaning.com.au"
        msg["To"] = "admin@orcacleaning.com.au"

        smtp_pass = os.getenv("SMTP_PASS")

        if not smtp_pass:
            logger.error("❌ SMTP password is missing in environment variables.")
            return

        with smtplib.SMTP("smtp.office365.com", 587) as server:
            server.starttls()
            server.login("info@orcacleaning.com.au", smtp_pass)
            server.sendmail(
                from_addr=msg["From"],
                to_addrs=[msg["To"]],
                msg=msg.as_string()
            )

        logger.info("✅ GPT error email sent successfully.")

    except smtplib.SMTPException as e:
        logger.error(f"⚠️ SMTP error occurred while sending the email: {e}")
        sleep(5)  # Simple retry delay
        send_gpt_error_email(error_msg)  # Retry once recursively

    except Exception as e:
        logger.error(f"⚠️ Could not send GPT error alert: {e}")

# === Quote Summary Generator ===

def get_inline_quote_summary(data: dict) -> str:
    """
    Generates a short summary of the quote to show in chat.
    """
    price = data.get("total_price", 0)
    time_est = data.get("estimated_time_mins", 0)
    note = data.get("note", "")

    summary = (
        f"All done! Here's your quote:\n\n"
        f"💰 Total Price (incl. GST): ${price:.2f}\n"
        f"⏰ Estimated Time: {time_est} minutes\n"
    )

    if note:
        summary += f"📝 Note: {note}\n"

    summary += "\nIf you'd like this in a PDF or want to make any changes, just let me know!"

    return summary

# === Next Action Buttons Generator ===

def generate_next_actions():
    """
    Generates a list of next action buttons for the customer after quote calculation.
    """
    return [
        {"action": "proceed_booking", "label": "Proceed to Booking"},
        {"action": "download_pdf", "label": "Download PDF Quote"},
        {"action": "email_pdf", "label": "Email PDF Quote"},
        {"action": "ask_questions", "label": "Ask Questions or Change Parameters"}
    ]

# === GPT Error Email Alert ===

import smtplib
from email.mime.text import MIMEText
from time import sleep


def send_gpt_error_email(error_msg: str):
    """
    Sends an email to admin if GPT extraction fails.
    """
    try:
        msg = MIMEText(error_msg)
        msg["Subject"] = "🚨 Brendan GPT Extraction Error"
        msg["From"] = "info@orcacleaning.com.au"
        msg["To"] = "admin@orcacleaning.com.au"

        smtp_pass = os.getenv("SMTP_PASS")

        if not smtp_pass:
            logger.error("❌ SMTP password is missing in environment variables.")
            return

        with smtplib.SMTP("smtp.office365.com", 587) as server:
            server.starttls()
            server.login("info@orcacleaning.com.au", smtp_pass)
            server.sendmail(
                from_addr=msg["From"],
                to_addrs=[msg["To"]],
                msg=msg.as_string()
            )

        logger.info("✅ GPT error email sent successfully.")

    except smtplib.SMTPException as e:
        logger.error(f"⚠️ SMTP error occurred: {e}")
        sleep(5)  # Retry once
        send_gpt_error_email(error_msg)

    except Exception as e:
        logger.error(f"⚠️ Could not send GPT error alert: {e}")

from datetime import datetime, timedelta
import pytz

# === Brendan Main Route Handler ===

@router.post("/filter-response")
async def filter_response_entry(request: Request):
    try:
        body = await request.json()
        message = body.get("message", "").strip()
        session_id = body.get("session_id")

        if not session_id:
            raise HTTPException(status_code=400, detail="Session ID is required.")

        # Start New Quote
        if message.lower() == "__init__":
            existing = get_quote_by_session(session_id)
            if existing:
                quote_id, record_id, stage, fields = existing
            else:
                quote_id, record_id, stage, fields = create_new_quote(session_id, force_new=True)
                session_id = fields.get("session_id", session_id)

            intro = "What needs cleaning today — bedrooms, bathrooms, oven, carpets, anything else?"
            append_message_log(record_id, message, "user")
            append_message_log(record_id, intro, "brendan")

            return JSONResponse(content={
                "properties": [],
                "response": intro,
                "next_actions": [],
                "session_id": session_id
            })

        # Existing Quote
        quote_id, record_id, stage, fields = get_quote_by_session(session_id)
        log = fields.get("message_log", "")

        # Chat Banned Handling
        if stage == "Chat Banned":
            return JSONResponse(content={
                "properties": [],
                "response": "This chat is closed due to prior messages. Please call 1300 918 388 if you still need a quote.",
                "next_actions": [],
                "session_id": session_id
            })

        updated_log = f"{log}\nUSER: {message}".strip()[-5000:]
        props_dict, reply = extract_properties_from_gpt4(message, updated_log, record_id, quote_id)

        # Abuse Handling
        if props_dict.get("quote_stage") in ["Abuse Warning", "Chat Banned"]:
            update_quote_record(record_id, props_dict)
            append_message_log(record_id, message, "user")
            append_message_log(record_id, reply, "brendan")
            return JSONResponse(content={
                "properties": list(props_dict.keys()),
                "response": reply,
                "next_actions": [],
                "session_id": session_id
            })

        # Quote Calculated → Ask for Personal Info
        if stage == "Quote Calculated":
            reply = "Awesome — to send your quote over, can I grab your name, email and best contact number?"
            update_quote_record(record_id, {"quote_stage": "Gathering Personal Info"})
            append_message_log(record_id, message, "user")
            append_message_log(record_id, reply, "brendan")
            return JSONResponse(content={
                "properties": [],
                "response": reply,
                "next_actions": [],
                "session_id": session_id
            })

        # Gathering Info → Check if ready to calculate
        if stage == "Gathering Info":
            if props_dict:
                reply = reply.replace("123456", quote_id).replace("{{quote_id}}", quote_id)

            merged = fields.copy()
            merged.update(props_dict)

            required_fields = [
                "suburb", "bedrooms_v2", "bathrooms_v2", "furnished",
                "oven_cleaning", "window_cleaning", "window_count", "blind_cleaning",
                "carpet_bedroom_count", "carpet_mainroom_count", "carpet_study_count",
                "carpet_halway_count", "carpet_stairs_count", "carpet_other_count",
                "deep_cleaning", "fridge_cleaning", "range_hood_cleaning", "wall_cleaning",
                "balcony_cleaning", "garage_cleaning", "upholstery_cleaning",
                "after_hours_cleaning", "weekend_cleaning", "mandurah_property",
                "is_property_manager", "special_requests", "special_request_minutes_min",
                "special_request_minutes_max"
            ]

            filled = [
                f for f in required_fields
                if merged.get(f) not in [None, "", False] or f == "special_requests"
            ]

            if len(filled) >= len(required_fields):
                logger.info(f"✅ All required fields collected — calculating quote for record_id: {record_id}")

                # Update stage to Quote Calculated
                update_quote_record(record_id, {**props_dict, "quote_stage": "Quote Calculated"})

                # Re-fetch updated record
                quote_id, record_id, stage, fields = get_quote_by_session(session_id)

                from app.services.quote_logic import QuoteRequest, calculate_quote
                quote_request = QuoteRequest(**merged)
                quote_response = calculate_quote(quote_request)

                # Generate expiry date (7 days from now, Perth time)
                perth_tz = pytz.timezone("Australia/Perth")
                expiry_date = datetime.now(perth_tz) + timedelta(days=7)
                expiry_str = expiry_date.strftime("%Y-%m-%d")

                # Update Airtable with calculated quote details
                update_quote_record(record_id, {
                    "quote_total": quote_response.total_price,
                    "quote_time_estimate": quote_response.estimated_time_mins,
                    "hourly_rate": quote_response.base_hourly_rate,
                    "discount_percent": quote_response.discount_applied,
                    "gst_amount": quote_response.gst_applied,
                    "final_price": quote_response.total_price,
                    "quote_expiry_date": expiry_str
                })

                summary = get_inline_quote_summary(quote_response.dict())

                reply = (
                    "Thank you! I’ve got what I need to whip up your quote. Hang tight…\n\n"
                    f"{summary}\n\n"
                    f"⚠️ This quote is valid until {expiry_str}. If it expires, just let me know your quote number and I’ll whip up a new one for you."
                )

                append_message_log(record_id, message, "user")
                append_message_log(record_id, reply, "brendan")

                return JSONResponse(content={
                    "properties": list(props_dict.keys()),
                    "response": reply,
                    "next_actions": generate_next_actions(),
                    "session_id": session_id
                })

            # Not ready yet → Stay in Gathering Info stage
            update_quote_record(record_id, {**props_dict, "quote_stage": "Gathering Info"})

            append_message_log(record_id, message, "user")
            append_message_log(record_id, reply, "brendan")

            return JSONResponse(content={
                "properties": list(props_dict.keys()),
                "response": reply,
                "next_actions": [],
                "session_id": session_id
            })

    except Exception as e:
        logger.error(f"❌ Exception in filter_response_entry: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")

