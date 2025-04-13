# === Imports ===
import os
import json
import uuid
import logging
import requests
import inflect
import openai

from datetime import datetime, timedelta
import pytz

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseSettings

from app.services.email_sender import handle_pdf_and_email
from app.services.quote_id_utils import get_next_quote_id

# === Settings Class for ENV Vars ===
class Settings(BaseSettings):
    OPENAI_API_KEY: str
    AIRTABLE_API_KEY: str
    AIRTABLE_BASE_ID: str
    BOOKING_URL_BASE: str = "https://orcacleaning.com.au/schedule"
    SMTP_PASS: str

    class Config:
        env_file = ".env"

settings = Settings()

# === Setup Logging ===
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("brendan")

# === ENV Safety Check ===
if not settings.OPENAI_API_KEY or not settings.AIRTABLE_API_KEY or not settings.AIRTABLE_BASE_ID:
    logger.error("❌ Critical ENV variables missing.")
    raise RuntimeError("Missing critical ENV variables.")

# === System Constants ===
MAX_LOG_LENGTH = 10000        # Airtable message_log field limit
QUOTE_EXPIRY_DAYS = 7        # Quote expiry in days
LOG_TRUNCATE_LENGTH = 5000   # Max length of log passed to GPT-4 for context

# === FastAPI Router ===
router = APIRouter()

# === OpenAI API Key Setup ===
openai.api_key = settings.OPENAI_API_KEY

# === Inflect Engine Setup ===
inflector = inflect.engine()

# === Boolean Value True Equivalents ===
TRUE_VALUES = {"yes", "true", "1", "on", "checked", "t"}

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
    "carpet_steam_clean",  # Legacy Field — auto-filled from carpet_* counts
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

# === Get Quote by Session ID ===

def get_quote_by_session(session_id: str):
    """
    Retrieves latest quote record from Airtable by session_id.
    Returns: (quote_id, record_id, quote_stage, fields) or None.
    """

    import traceback
    
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{TABLE_NAME}"
    headers = {"Authorization": f"Bearer {AIRTABLE_API_KEY}"}
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

        logger.info(f"✅ Found quote for session_id: {session_id} | Quote ID: {fields.get('quote_id')}")

        return (
            fields.get("quote_id"),
            record["id"],
            fields.get("quote_stage", "Gathering Info"),
            fields
        )

    except Exception as e:
        logger.error(f"❌ Error fetching quote for session_id {session_id}: {e}")
        return None
# === Update Quote Record ===

def update_quote_record(record_id: str, fields: dict):
    """
    Updates a quote record in Airtable.
    Auto-normalizes all fields.
    Returns: List of successfully updated field names.
    """
    import traceback
    
    url = f"https://api.airtable.com/v0/{settings.AIRTABLE_BASE_ID}/{TABLE_NAME}"
    headers = {
        "Authorization": f"Bearer {settings.AIRTABLE_API_KEY}",
        "Content-Type": "application/json"
    }


    # Normalize furnished for dropdown
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
            continue  # Skip unknown fields

        if isinstance(value, str):
            value = value.strip()

        if key in BOOLEAN_FIELDS:
            value = str(value).strip().lower() in TRUE_VALUES

        if key in INTEGER_FIELDS:
            try:
                value = int(value)
            except Exception:
                value = 0

        normalized_fields[key] = value

    if not normalized_fields:
        logger.info(f"⏩ No valid fields to update for record {record_id}")
        return []

    logger.info(f"\n📤 Updating Airtable Record: {record_id}")
    logger.info(f"🛠 Payload: {json.dumps(normalized_fields, indent=2)}")

    # Attempt Bulk Update
    res = requests.patch(url, headers=headers, json={"fields": normalized_fields})

    if res.ok:
        logger.info("✅ Airtable bulk update success.")
        return list(normalized_fields.keys())

    logger.error(f"❌ Airtable bulk update failed: {res.status_code}")
    try:
        logger.error("🧾 Error response: %s", json.dumps(res.json(), indent=2))
    except Exception as e:
        logger.warning(f"⚠️ Failed to decode Airtable error: {e}")

    logger.info("🔍 Attempting field-by-field update fallback...")

    successful_fields = []

    for key, value in normalized_fields.items():
        single_res = requests.patch(url, headers=headers, json={"fields": {key: value}})
        if single_res.ok:
            logger.info(f"✅ Field '{key}' updated successfully.")
            successful_fields.append(key)
        else:
            logger.error(f"❌ Field '{key}' failed to update.")

    logger.info(f"✅ Field-by-field update complete. Success fields: {successful_fields}")
    return successful_fields


# === Append Message Log ===

def append_message_log(record_id: str, message: str, sender: str):
    """
    Appends a new message to the existing message_log field in Airtable.
    Truncates from the start if log exceeds max length.
    """

    import traceback 
    
    if not record_id:
        logger.error("❌ Cannot append log — missing record ID")
        return

    message = str(message).strip()
    if not message:
        logger.info("⏩ Empty message after stripping — skipping log update")
        return

    url = f"https://api.airtable.com/v0/{settings.AIRTABLE_BASE_ID}/{TABLE_NAME}"
    headers = {"Authorization": f"Bearer {settings.AIRTABLE_API_KEY}"}


    try:
        res = requests.get(url, headers=headers)
        res.raise_for_status()
        current = res.json()
    except Exception as e:
        logger.error(f"❌ Failed to fetch existing log from Airtable: {e}")
        return

    old_log = current.get("fields", {}).get("message_log", "")

    sender_clean = sender.strip().upper()
    new_log = f"{old_log}\n{sender_clean}: {message}".strip()

    if len(new_log) > MAX_LOG_LENGTH:
        new_log = new_log[-MAX_LOG_LENGTH:]


    logger.info(f"📚 Appending to message log for record {record_id}")
    logger.debug(f"📝 New message_log length: {len(new_log)} characters")

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


# === GPT Extraction (Production-Grade) ===

def extract_properties_from_gpt4(message: str, log: str, record_id: str = None, quote_id: str = None):
    import random
    import json
    import traceback

    try:
        logger.info("🧠 Calling GPT-4 to extract properties...")
        response = openai.ChatCompletion.create(
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
        raw = raw.replace("```json", "").replace("```", "").strip()
        logger.debug(f"🔍 RAW GPT OUTPUT:\n{raw}")

        start, end = raw.find("{"), raw.rfind("}")
        if start == -1 or end == -1:
            raise ValueError("JSON block not found.")

        clean_json = raw[start:end + 1]
        parsed = json.loads(clean_json)

        props = parsed.get("properties", [])
        reply = parsed.get("response", "")
        logger.debug(f"✅ Parsed props: {props}")
        logger.debug(f"✅ Parsed reply: {reply}")

        existing = {}
        if record_id:
            url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{TABLE_NAME}/{record_id}"
            headers = {"Authorization": f"Bearer {AIRTABLE_API_KEY}"}
            res = requests.get(url, headers=headers)
            if res.ok:
                existing = res.json().get("fields", {})

        field_updates = {}
        current_stage = existing.get("quote_stage", "")

        for p in props:
            if isinstance(p, dict) and "property" in p and "value" in p:
                key, value = p["property"], p["value"]

                if key == "quote_stage" and current_stage in [
                    "Quote Calculated", "Gathering Personal Info", "Personal Info Received",
                    "Booking Confirmed", "Referred to Office"
                ]:
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

        # Force safe defaults for missing required fields
        for field in VALID_AIRTABLE_FIELDS:
            if field not in field_updates and field not in existing:
                if field in INTEGER_FIELDS:
                    field_updates[field] = 0
                elif field == "special_requests":
                    field_updates[field] = ""
                elif field in BOOLEAN_FIELDS:
                    field_updates[field] = False

        # Auto set carpet_cleaning = True if any carpet count > 0
        if any(
            int(field_updates.get(f, existing.get(f, 0) or 0)) > 0
            for f in [
                "carpet_bedroom_count",
                "carpet_mainroom_count",
                "carpet_study_count",
                "carpet_halway_count",
                "carpet_stairs_count",
                "carpet_other_count",
            ]
        ):
            field_updates["carpet_cleaning"] = True

        # Determine if quote is ready
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

        missing_fields = [
            f for f in required_fields
            if field_updates.get(f) in [None, ""] and existing.get(f) in [None, ""]
        ]

        if missing_fields:
            logger.warning(f"❗ Missing required fields preventing Quote Calculated stage: {missing_fields}")

        if not missing_fields:
            field_updates["quote_stage"] = "Quote Calculated"
        elif current_stage == "Gathering Info" and "quote_stage" not in field_updates:
            field_updates["quote_stage"] = "Gathering Info"

        # Abuse Detection
        abuse_detected = any(word in message.lower() for word in ABUSE_WORDS)
        if abuse_detected:
            if not quote_id and existing:
                quote_id = existing.get("quote_id", "N/A")
            if current_stage == "Abuse Warning":
                field_updates["quote_stage"] = "Chat Banned"
                reply = random.choice([
                    f"We’ve ended the quote due to repeated language. Call us on 1300 918 388 with your quote number: {quote_id}. This chat is now closed.",
                    f"Unfortunately we have to end the quote due to language. You're welcome to call our office if you'd like to continue. Quote Number: {quote_id}.",
                    f"Let’s keep things respectful — I’ve had to stop the quote here. Feel free to call the office. Quote ID: {quote_id}. This chat is now closed."
                ])
                return field_updates, reply
            else:
                field_updates["quote_stage"] = "Abuse Warning"
                reply = f"Just a heads-up — we can’t continue the quote if abusive language is used. Let’s keep things respectful 👍\n\n{reply}"

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

# === Inline Quote Summary Helper ===

def get_inline_quote_summary(data: dict) -> str:
    """
    Generates a short, clean summary of the quote to show in chat.
    """
    price = float(data.get("total_price", 0) or 0)
    time_est = int(data.get("estimated_time_mins", 0) or 0)
    note = str(data.get("note", "") or "").strip()

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

        smtp_pass = settings.SMTP_PASS

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

        # If GPT says all info is collected, force stage to Quote Calculated
        if props_dict.get("quote_stage") == "Quote Calculated":
            from app.services.quote_logic import QuoteRequest, calculate_quote

            merged = fields.copy()
            merged.update(props_dict)

            quote_request = QuoteRequest(**merged)
            quote_response = calculate_quote(quote_request)

            perth_tz = pytz.timezone("Australia/Perth")
            expiry_date = datetime.now(perth_tz) + timedelta(days=7)
            expiry_str = expiry_date.strftime("%Y-%m-%d")

            update_quote_record(record_id, {
                **props_dict,
                "quote_total": quote_response.total_price,
                "quote_time_estimate": quote_response.estimated_time_mins,
                "hourly_rate": quote_response.base_hourly_rate,
                "discount_percent": quote_response.discount_applied,
                "gst_amount": quote_response.gst_applied,
                "final_price": quote_response.total_price,
                "quote_expiry_date": expiry_str
            })

            if not quote_response:
                logger.error("❌ Quote Response missing during summary generation.")
                raise HTTPException(status_code=500, detail="Failed to calculate quote.")

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

        # Stay in Gathering Info
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
