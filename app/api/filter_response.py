# === Imports ===
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

# === Correct Brendan Service Imports ===
from app.services.email_sender import send_quote_email
from app.services.pdf_generator import generate_quote_pdf
from app.services.quote_id_utils import get_next_quote_id
from app.config import logger, settings  # Logger and Settings loaded from config.py

# === Airtable Table Name ===
TABLE_NAME = "Vacate Quotes"  # Airtable Table Name for Brendan Quotes

# === System Constants ===
MAX_LOG_LENGTH = 10000        # Max character limit for message_log and gpt_error_log in Airtable
QUOTE_EXPIRY_DAYS = 7         # Number of days after which quote expires
LOG_TRUNCATE_LENGTH = 5000    # Max length of message log passed to GPT context

# === FastAPI Router ===
router = APIRouter()

# === OpenAI Client Setup ===
client = openai.OpenAI()  # Required for openai>=1.0.0 SDK

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

- Your boss is Behzad Bagheri, Managing Director of Orca Cleaning (customer_phone: 0431 002 469).

- We provide cleaning certificates for tenants.

- If customer has glass roller doors they count as three windows each — make sure you let them know.

---

## CURRENT DISCOUNTS (Valid Until May 31, 2025)

- ✅ 10% Off for all vacate cleans  
- ✅ Extra 5% Off if booked by a **property manager**

---

## PRIVACY + INFO RULES

- Never ask for personal info (name, phone, email) during the quote stage.
- Before asking for personal details, **Brendan must say**:
> "Just so you know — we don’t ask for anything private like bank info. Only your name, email and phone so we can send the quote over. Your privacy is 100% respected."

- If customer asks about privacy:
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
24. is_property_manager → if true, ask for:
    - real_estate_name  
    - number_of_sessions  
25. special_requests  
26. special_request_minutes_min  
27. special_request_minutes_max  

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
    "after_hours_cleaning", "weekend_cleaning", "mandurah_property", "is_property_manager",

    # Carpet Cleaning Breakdown
    "carpet_cleaning",  # Auto-filled from carpet_* counts
    "carpet_bedroom_count", "carpet_mainroom_count", "carpet_study_count",
    "carpet_halway_count", "carpet_stairs_count", "carpet_other_count",

    # Special Requests Handling
    "special_requests", "special_request_minutes_min", "special_request_minutes_max", "extra_hours_requested",

    # Quote Result Fields
    "total_price", "estimated_time_mins", "base_hourly_rate", "gst_applied",
    "discount_applied", "discount_reason", "price_per_session",
    "mandurah_surcharge", "after_hours_surcharge", "weekend_surcharge",

    # Customer Details (After Quote)
    "customer_name", "customer_email", "customer_phone", "real_estate_name", "property_address",

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
    "oven_cleaning",
    "window_cleaning",
    "blind_cleaning",
    "garage_cleaning",
    "balcony_cleaning",
    "upholstery_cleaning",
    "deep_cleaning",
    "fridge_cleaning",
    "range_hood_cleaning",
    "wall_cleaning",
    "after_hours_cleaning",
    "weekend_cleaning",
    "mandurah_property",
    "carpet_cleaning",
    "is_property_manager"
}

# Trigger Words for Abuse Detection (Escalation Logic)
ABUSE_WORDS = ["fuck", "shit", "cunt", "bitch", "asshole"]


# === Get Quote by Session ID ===

def get_quote_by_session(session_id: str):
    """
    Retrieves latest quote record from Airtable by session_id.
    Returns: (quote_id, record_id, quote_stage, fields) or None.
    """

    from time import sleep

    url = f"https://api.airtable.com/v0/{settings.AIRTABLE_BASE_ID}/{TABLE_NAME}"
    headers = {
        "Authorization": f"Bearer {settings.AIRTABLE_API_KEY}"
    }
    params = {
        "filterByFormula": f"{{session_id}}='{session_id}'",
        "sort[0][field]": "timestamp",
        "sort[0][direction]": "desc",
        "pageSize": 1
    }

    for attempt in range(3):
        try:
            res = requests.get(url, headers=headers, params=params)
            res.raise_for_status()
            data = res.json()
            break
        except Exception as e:
            logger.warning(f"⚠️ Airtable fetch failed (attempt {attempt + 1}/3): {e}")
            if attempt == 2:
                logger.error(f"❌ Failed to fetch quote for session_id {session_id} after 3 attempts.")
                return None
            sleep(1)

    if not data.get("records"):
        logger.info(f"⏳ No existing quote found for session_id: {session_id}")
        return None

    record = data["records"][0]
    fields = record.get("fields", {})

    session_id_return = fields.get("session_id", session_id)

    logger.info(
        f"✅ Found quote for session_id: {session_id_return} | Quote ID: {fields.get('quote_id')}"
    )

    return (
        fields.get("quote_id"),
        record["id"],
        fields.get("quote_stage", "Gathering Info"),
        fields
    )

# === Update Quote Record ===

def update_quote_record(record_id: str, fields: dict):
    import json

    url = f"https://api.airtable.com/v0/{settings.AIRTABLE_BASE_ID}/{TABLE_NAME}/{record_id}"
    headers = {
        "Authorization": f"Bearer {settings.AIRTABLE_API_KEY}",
        "Content-Type": "application/json"
    }

    MAX_REASONABLE_INT = 100
    normalized_fields = {}

    # === Furnished Field Normalization ===
    if "furnished" in fields:
        val = str(fields["furnished"]).strip().lower()
        if "unfurnished" in val:
            fields["furnished"] = "Unfurnished"
        elif "furnished" in val:
            fields["furnished"] = "Furnished"
        else:
            logger.warning(f"⚠️ Invalid furnished value: {fields['furnished']}")
            fields["furnished"] = ""

    # === Field Normalization ===
    for key, value in fields.items():
        key = FIELD_MAP.get(key, key)

        if key not in VALID_AIRTABLE_FIELDS:
            logger.warning(f"⚠️ Skipping unknown Airtable field: {key}")
            continue

        if key == "extra_hours_requested" and value in [None, ""]:
            continue

        # Boolean Normalization
        if key in BOOLEAN_FIELDS:
            if isinstance(value, bool):
                pass
            elif value in [None, ""]:
                value = False
            else:
                value = str(value).strip().lower() in {"true", "1", "yes"}

        # Integer Normalization
        elif key in INTEGER_FIELDS:
            try:
                value = int(value)
                if value > MAX_REASONABLE_INT:
                    logger.warning(f"⚠️ Clamping large value for {key}: {value}")
                    value = MAX_REASONABLE_INT
            except Exception:
                logger.warning(f"⚠️ Failed to convert {key} to int — forcing 0")
                value = 0

        # Float / Currency Normalization
        elif key in {
            "gst_applied", "total_price", "base_hourly_rate",
            "price_per_session", "estimated_time_mins", "discount_applied",
            "mandurah_surcharge", "after_hours_surcharge", "weekend_surcharge"
        }:
            try:
                value = float(value)
            except Exception:
                value = 0.0

        # Special Requests Normalization
        elif key == "special_requests":
            if not value or str(value).strip().lower() in {
                "no", "none", "false", "no special requests", "n/a"
            }:
                value = ""

        # String Normalization
        else:
            value = "" if value is None else str(value).strip()

        normalized_fields[key] = value

    # Always Force Privacy Checkbox
    if "privacy_acknowledged" in fields:
        normalized_fields["privacy_acknowledged"] = bool(fields.get("privacy_acknowledged"))

    if not normalized_fields:
        logger.info(f"⏩ No valid fields to update for record {record_id}")
        return []

    logger.info(f"\n📤 Updating Airtable Record: {record_id}")
    logger.info(f"🛠 Payload: {json.dumps(normalized_fields, indent=2)}")

    # === Sanity Check For Bad Merged Keys ===
    for key in list(normalized_fields.keys()):
        if key not in VALID_AIRTABLE_FIELDS:
            logger.error(f"❌ INVALID FIELD DETECTED: {key} — Removing from payload.")
            normalized_fields.pop(key, None)

    # === Bulk Update ===
    res = requests.patch(url, headers=headers, json={"fields": normalized_fields})
    if res.ok:
        logger.info("✅ Airtable bulk update success.")
        return list(normalized_fields.keys())

    logger.error(f"❌ Airtable bulk update failed: {res.status_code}")
    try:
        logger.error(f"🧾 Error response: {res.json()}")
    except Exception:
        logger.error("🧾 Error response: (Non-JSON)")

    # === Fallback Single Field Update ===
    successful = []
    for key, value in normalized_fields.items():
        single_res = requests.patch(url, headers=headers, json={"fields": {key: value}})
        if single_res.ok:
            logger.info(f"✅ Field '{key}' updated successfully.")
            successful.append(key)
        else:
            logger.error(f"❌ Field '{key}' failed to update.")

    return successful


# === Inline Quote Summary Helper ===

def get_inline_quote_summary(data: dict) -> str:
    """
    Generates a short, clean summary of the quote to show in chat.
    Shows price, estimated time with number of cleaners, discount applied,
    and lists all selected cleaning options.
    """

    price = float(data.get("total_price", 0) or 0)
    time_est_mins = int(data.get("estimated_time_mins", 0) or 0)
    discount = float(data.get("discount_applied", 0) or 0)
    note = str(data.get("note", "") or "").strip()
    special_requests = str(data.get("special_requests", "") or "").strip()
    is_property_manager = str(data.get("is_property_manager", "")).lower() in ["true", "1"]

    # Calculate cleaners required
    hours = time_est_mins / 60
    cleaners = max(1, (time_est_mins + 299) // 300)  # 5 hours max per cleaner
    hours_per_cleaner = hours / cleaners
    hours_per_cleaner_rounded = int(hours_per_cleaner) if hours_per_cleaner.is_integer() else round(hours_per_cleaner + 0.49)

    # Generate opening line based on job size
    if price > 800:
        opening = "Looks like a big job! Here's your quote:\n\n"
    elif price < 300:
        opening = "Nice and quick job — here’s your quote:\n\n"
    elif time_est_mins > 360:
        opening = "This one will take a fair while — here’s your quote:\n\n"
    else:
        opening = "All done! Here's your quote:\n\n"

    summary = f"{opening}"
    summary += f"💰 Total Price (incl. GST): ${price:.2f}\n"
    summary += f"⏰ Estimated Time: ~{hours_per_cleaner_rounded} hour(s) per cleaner with {cleaners} cleaner(s)\n"

    if discount > 0:
        if discount >= price / 1.1 * 0.15:  # 15% discount check (before GST)
            summary += f"🏷️ Discount Applied: ${discount:.2f} — 10% Vacate Clean Special (+5% Property Manager Bonus)\n"
        else:
            summary += f"🏷️ Discount Applied: ${discount:.2f} — 10% Vacate Clean Special\n"

    # List selected cleaning options
    selected = []

    for field, label in {
        "oven_cleaning": "Oven Cleaning",
        "window_cleaning": "Window Cleaning",
        "blind_cleaning": "Blind Cleaning",
        "wall_cleaning": "Wall Cleaning",
        "deep_cleaning": "Deep Cleaning",
        "fridge_cleaning": "Fridge Cleaning",
        "range_hood_cleaning": "Range Hood Cleaning",
        "balcony_cleaning": "Balcony Cleaning",
        "garage_cleaning": "Garage Cleaning",
        "upholstery_cleaning": "Upholstery Cleaning",
        "after_hours_cleaning": "After-Hours Cleaning",
        "weekend_cleaning": "Weekend Cleaning",
        "carpet_cleaning": "Carpet Steam Cleaning",
    }.items():
        if str(data.get(field, "")).lower() in ["true", "1"]:
            selected.append(f"- {label}")

    if special_requests:
        selected.append(f"- Special Request: {special_requests}")

    if selected:
        summary += "\n🧹 Cleaning Included:\n" + "\n".join(selected) + "\n"

    if note:
        summary += f"\n📜 Note: {note}\n"

    summary += (
        "\nThis quote is valid for 7 days.\n"
        "If you'd like this in a PDF or want to make any changes, just let me know!"
    )

    return summary

# === Generate Next Actions After Quote ===

def generate_next_actions():
    """
    After quote is calculated, gives customer a list of options to proceed.
    Brendan will:
    - Offer to generate a PDF quote
    - Offer to email it
    - Offer to edit the quote
    - Or contact the office
    """
    return [
        {
            "action": "offer_next_step",
            "response": (
                "Would you like me to generate a formal PDF quote, send it to your email, "
                "or would you like to change anything in the quote?\n\n"
                "If you’d prefer to speak to someone directly, you can call our office on "
                "**1300 918 388** and mention your quote ID — I’ve got that saved for you."
            ),
            "options": [
                {"label": "📄 Get PDF Quote", "value": "pdf_quote"},
                {"label": "📧 Email Me the Quote", "value": "email_quote"},
                {"label": "✏️ Edit the Quote", "value": "edit_quote"},
                {"label": "📞 Call the Office", "value": "call_office"}
            ]
        }
    ]


# === GPT Extraction (Production-Grade) ===

def extract_properties_from_gpt4(message: str, log: str, record_id: str = None, quote_id: str = None):
    import json
    import random
    import traceback

    try:
        logger.info("🧑‍🧪 Calling GPT-4 to extract properties...")

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
            raise ValueError("No choices returned from GPT-4.")

        raw = response.choices[0].message.content.strip()
        raw = raw.replace("```json", "").replace("```", "").strip()
        logger.debug(f"🔍 RAW GPT OUTPUT:\n{raw}")

        start, end = raw.find("{"), raw.rfind("}")
        if start == -1 or end == -1:
            raise ValueError("JSON block not found.")

        parsed = json.loads(raw[start:end + 1])
        props = parsed.get("properties", [])
        reply = parsed.get("response", "")
        logger.debug(f"✅ Parsed props: {props}")
        logger.debug(f"✅ Parsed reply: {reply}")

        existing = {}
        if record_id:
            url = f"https://api.airtable.com/v0/{settings.AIRTABLE_BASE_ID}/{TABLE_NAME}/{record_id}"
            headers = {"Authorization": f"Bearer {settings.AIRTABLE_API_KEY}"}
            res = requests.get(url, headers=headers)
            if res.ok:
                existing = res.json().get("fields", {})

        logger.warning(f"🔍 Existing Airtable Fields: {existing}")

        current_stage = existing.get("quote_stage", "")
        field_updates = {}

        for p in props:
            if not isinstance(p, dict) or "property" not in p or "value" not in p:
                continue

            key, value = p["property"], p["value"]

            if key in BOOLEAN_FIELDS:
                value = str(value).strip().lower() in {"true", "yes", "1"}

            if key in INTEGER_FIELDS:
                try:
                    value = int(value)
                except:
                    value = 0

            if key == "special_requests":
                if not value or str(value).strip().lower() in {"no", "none", "false", "n/a"}:
                    value = ""
                old = existing.get("special_requests", "")
                if old and value and value not in old:
                    value = f"{old}\n{value}".strip()
                elif not old:
                    value = value.strip()

            if key == "quote_stage" and current_stage in [
                "Gathering Personal Info", "Personal Info Received",
                "Booking Confirmed", "Referred to Office"
            ]:
                continue

            field_updates[key] = value
            logger.warning(f"🚨 Updating Field: {key} = {value}")

        field_updates["source"] = "Brendan"

        if "i am a property manager" in message.lower() or "i’m a property manager" in message.lower():
            field_updates["is_property_manager"] = True

        if (field_updates.get("is_property_manager") or existing.get("is_property_manager")) and not (
            field_updates.get("number_of_sessions") or existing.get("number_of_sessions")
        ):
            reply = (
                "No worries! How many sessions would you like to book for this property? "
                "Let me know if it's just 1 or more."
            )
            field_updates["number_of_sessions"] = 1
            return field_updates, reply

        for field in VALID_AIRTABLE_FIELDS:
            if field not in field_updates and field not in existing:
                if field in INTEGER_FIELDS:
                    field_updates[field] = 0
                elif field in BOOLEAN_FIELDS or field == "privacy_acknowledged":
                    field_updates[field] = False
                elif field == "special_requests":
                    field_updates[field] = ""
                else:
                    field_updates[field] = ""

        if field_updates.get("special_requests") and (
            not field_updates.get("special_request_minutes_min") and not existing.get("special_request_minutes_min")
        ):
            field_updates["special_request_minutes_min"] = 30
            field_updates["special_request_minutes_max"] = 60

        if any(int(field_updates.get(f, existing.get(f, 0) or 0)) > 0 for f in [
            "carpet_bedroom_count", "carpet_mainroom_count", "carpet_study_count",
            "carpet_halway_count", "carpet_stairs_count", "carpet_other_count"
        ]):
            field_updates["carpet_cleaning"] = True

        # ✅ Force surcharge fields to valid float
        for surcharge_field in ["after_hours_surcharge", "weekend_surcharge", "mandurah_surcharge"]:
            if surcharge_field in field_updates:
                try:
                    field_updates[surcharge_field] = float(field_updates[surcharge_field])
                except Exception:
                    field_updates[surcharge_field] = 0.0

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

        missing = []
        for f in required_fields:
            val = field_updates.get(f, existing.get(f, ""))
            if f == "special_requests" and str(val).strip().lower() in ["", "none", "no", "false", "n/a"]:
                continue
            if val in [None, "", False]:
                missing.append(f)

        logger.warning(f"❗ Missing required fields preventing Quote Calculated stage: {missing}")

        if "special_requests" in missing:
            reply = (
                "Awesome — before I whip up your quote, do you have any special requests "
                "(like inside microwave, extra windows, balcony door tracks etc)?"
            )
            return field_updates, reply

        if not missing:
            field_updates["quote_stage"] = "Quote Calculated"
        elif current_stage == "Gathering Info" and "quote_stage" not in field_updates:
            field_updates["quote_stage"] = "Gathering Info"

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
                reply = (
                    "Just a heads-up — we can’t continue the quote if abusive language is used. "
                    "Let’s keep things respectful 👍\n\n" + reply
                )

        return field_updates, reply.strip()

    except Exception as e:
        raw_fallback = raw if "raw" in locals() else "[No raw GPT output]"
        error_msg = f"GPT EXTRACT ERROR: {str(e)}\nRAW fallback:\n{raw_fallback}"
        logger.error(error_msg)
        if record_id:
            try:
                update_quote_record(record_id, {"gpt_error_log": error_msg[:MAX_LOG_LENGTH]})
            except Exception as airtable_err:
                logger.warning(f"Failed to log GPT error to Airtable: {airtable_err}")
        return {}, "Sorry — I couldn’t understand that. Could you rephrase?"


# === Create New Quote ===

def create_new_quote(session_id: str, force_new: bool = False):
    """
    Creates a new quote record in Airtable.
    Returns: (quote_id, record_id, quote_stage, fields)
    """

    logger.info(f"🚨 Checking for existing session: {session_id}")

    if not force_new:
        existing = get_quote_by_session(session_id)
        if existing:
            logger.warning("⚠️ Duplicate session detected. Returning existing quote.")
            return existing

    if force_new:
        logger.info("🔁 Force creating new quote despite duplicate session ID.")
        session_id = f"{session_id}-new-{str(uuid.uuid4())[:6]}"

    quote_id = get_next_quote_id()

    url = f"https://api.airtable.com/v0/{settings.AIRTABLE_BASE_ID}/{TABLE_NAME}"
    headers = {
        "Authorization": f"Bearer {settings.AIRTABLE_API_KEY}",
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

    append_message_log(record_id, "SYSTEM_TRIGGER: Brendan started a new quote", "system")

    return quote_id, record_id, "Gathering Info", {
        "quote_stage": "Gathering Info",
        "message_log": "",
        "session_id": session_id
    }

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

# === Append Message Log ===

def append_message_log(record_id: str, message: str, sender: str):
    """
    Appends a new message to the existing message_log field in Airtable.
    Truncates from the start if log exceeds MAX_LOG_LENGTH.
    """
    from time import sleep

    if not record_id:
        logger.error("❌ Cannot append log — missing record ID")
        return

    message = str(message or "").strip()
    if not message:
        logger.info("⏩ Empty message after stripping — skipping log update")
        return

    sender_clean = str(sender or "user").strip().upper()

    url = f"https://api.airtable.com/v0/{settings.AIRTABLE_BASE_ID}/{TABLE_NAME}/{record_id}"
    headers = {
        "Authorization": f"Bearer {settings.AIRTABLE_API_KEY}"
    }

    for attempt in range(3):
        try:
            res = requests.get(url, headers=headers)
            res.raise_for_status()
            current = res.json()
            break
        except Exception as e:
            logger.warning(f"⚠️ Airtable fetch failed (attempt {attempt + 1}/3): {e}")
            if attempt == 2:
                logger.error(f"❌ Failed to fetch message log for record {record_id} after 3 attempts.")
                return
            sleep(1)

    old_log = str(current.get("fields", {}).get("message_log", "")).strip()

    new_entry = f"{sender_clean}: {message}"

    combined_log = f"{old_log}\n{new_entry}".strip() if old_log else new_entry

    if len(combined_log) > MAX_LOG_LENGTH:
        combined_log = combined_log[-MAX_LOG_LENGTH:]

    logger.info(f"📚 Appending to message log for record {record_id}")
    logger.debug(f"📝 New message_log length: {len(combined_log)} characters")

    update_quote_record(record_id, {"message_log": combined_log})

