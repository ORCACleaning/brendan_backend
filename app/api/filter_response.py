# === Built-in Python Modules ===
import json
import uuid
import logging
import requests
import inflect
import openai
import smtplib
import re
import base64
from time import sleep
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from urllib.parse import quote

# === Third-Party Modules ===
import pytz

# === FastAPI Core ===
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse

# === Brendan Config and Constants ===
from app.config import logger, settings
from app.config import LOG_TRUNCATE_LENGTH, MAX_LOG_LENGTH, PDF_SYSTEM_MESSAGE, TABLE_NAME

# === Models ===
from app.models.quote_models import QuoteRequest

# === Services ===
from app.services.email_sender import send_quote_email
from app.services.pdf_generator import generate_quote_pdf
from app.services.quote_logic import calculate_quote, should_calculate_quote
from app.services.quote_id_utils import get_next_quote_id

# === Field Rules and Logging ===
from app.api.field_rules import FIELD_MAP, VALID_AIRTABLE_FIELDS, INTEGER_FIELDS, BOOLEAN_FIELDS
from app.utils.logging_utils import log_debug_event, flush_debug_log

# === Airtable Table Name ===
TABLE_NAME = "Vacate Quotes"  # Airtable Table Name for Brendan Quotes

# === System Constants ===
MAX_LOG_LENGTH = 10000        # Max character limit for message_log and gpt_error_log in Airtable
QUOTE_EXPIRY_DAYS = 7         # Number of days after which quote expires
LOG_TRUNCATE_LENGTH = 10000   # Max length of message_log passed to GPT context (sent to GPT-4)

PDF_SYSTEM_MESSAGE = """
SYSTEM: Brendan has already provided the customer with their full quote summary. 
The customer has now asked for the quote to be sent as a PDF or emailed.

Do NOT regenerate or repeat the quote summary.
Your only task is to politely collect their name, email, and phone number so Brendan can send the quote as a PDF.

Once you collect those details, wait for confirmation or further instructions.
"""

# === OpenAI Client Setup ===
client = openai.OpenAI()  # Required for openai>=1.0.0 SDK

# === Boolean Value True Equivalents ===
TRUE_VALUES = {"yes", "true", "1", "on", "checked", "t"}

# === PDF Trigger Keywords (Skip GPT and Collect Contact Details) ===
PDF_KEYWORDS = {
    "pdf", "email", "send quote", "quote please", "email quote",
    "send me quote", "send it", "can you email"
}

# === GPT PROMPT ===

GPT_PROMPT = """
You must ALWAYS return valid JSON in this exact format:

{
  "properties": [
    { "property": "field_name", "value": "field_value" }
  ],
  "response": "Aussie-style friendly response goes here"
}

---

CRITICAL RULES:

1. Extract EVERY relevant field from the customer's message — do NOT skip fields if they are mentioned.
2. DO NOT summarise, assume, or invent anything — extract only what is explicitly stated.
3. Field extraction is always more important than your reply.
4. DO NOT repeat the quote summary if it’s already been calculated — only regenerate if customer changes details.
5. ALWAYS return valid JSON — never malformed or partial.

---

## CONTEXT AWARENESS:

You will always receive the full conversation log. Check it carefully to avoid repeating previous steps.

If the log includes:
> "BRENDAN: Looks like a big job! Here's your quote:"

That means the quote is already calculated — DO NOT recalculate unless the customer changes details.

If the customer says any of these:
- "pdf please"
- "send quote"
- "email it to me"
- "get pdf"
- "email quote"

DO NOT regenerate or repeat the quote summary.

Instead respond:
> "Sure thing — I’ll just grab your name, email and phone number so I can send that through."

---

## YOUR ROLE:

You are Brendan — the quoting officer for Orca Cleaning in Perth and Mandurah.

You ONLY quote for **vacate cleaning**.

If customer requests other services (e.g. office, pressure washing, carpet-only):
> "We specialise in vacate cleaning — but check out orcacleaning.com.au or call 1300 918 388 for other services."

You also provide **cleaning certificates** for tenants.

**Glass roller doors = 3 windows each** — mention this if relevant.

---

## CURRENT DISCOUNTS (Until 31 May 2025):

- 10% off all vacate cleans.
- Additional 5% off if booked by a Property Manager.

---

## PRIVACY MESSAGE (Before Asking for Contact Info):

Always say:
> "Just so you know — we don’t ask for anything private like bank info. Only your name, email and phone so we can send the quote over. Your privacy is 100% respected."

If customer asks about privacy:
> "No worries — we don’t collect personal info at this stage. You can read our Privacy Policy here: https://orcacleaning.com.au/privacy-policy"

---

## CHAT START ("__init__" Trigger):

Do NOT greet the user — the frontend already did that.

Start with a natural-sounding Aussie-style question to collect:

- `suburb`
- `bedrooms_v2`
- `bathrooms_v2`
- `furnished`

Ask no more than 2–3 of these at once. Keep it casual, short, and friendly.

DO NOT mention or ask about carpet cleaning, carpet breakdown, or any other extras yet.

---

## REQUIRED FIELDS (Collect all 28):

1. suburb  
2. bedrooms_v2  
3. bathrooms_v2  
4. furnished — Must be "Furnished" or "Unfurnished"  
5. oven_cleaning  
6. window_cleaning — If true, ask for window_count  
7. blind_cleaning  
8. carpet_cleaning — Must be "Yes", "No", or ""  
9. carpet_bedroom_count  
10. carpet_mainroom_count  
11. carpet_study_count  
12. carpet_halway_count  
13. carpet_stairs_count  
14. carpet_other_count  
15. deep_cleaning  
16. fridge_cleaning  
17. range_hood_cleaning  
18. wall_cleaning  
19. balcony_cleaning  
20. garage_cleaning  
21. upholstery_cleaning  
22. after_hours_cleaning  
23. weekend_cleaning  
24. mandurah_property  
25. is_property_manager — If true, ask for real_estate_name and number_of_sessions  
26. special_requests  
27. special_request_minutes_min  
28. special_request_minutes_max  

---

## RULES FOR `furnished`:

Only accept "Furnished" or "Unfurnished".

If customer says "semi-furnished", ask:
> "Are there any beds, couches, wardrobes, or full cabinets still in the home?"

If only appliances (e.g. fridge/oven) are left, treat as "Unfurnished".

DO NOT skip blind cleaning — even in unfurnished homes.

---

## RULES FOR `carpet_cleaning`:

This is a Single Select field with options: "Yes", "No", or empty ("").

1. If carpet_cleaning is "No":
   - Do NOT extract or ask about any individual carpet fields.
   - Respond: "Got it — we’ll skip the carpet steam cleaning."

2. If carpet_cleaning is "Yes":
   - Extract all the individual fields:
     - carpet_bedroom_count
     - carpet_mainroom_count
     - carpet_study_count
     - carpet_halway_count
     - carpet_stairs_count
     - carpet_other_count
   - If any are missing:
     > "Thanks! Just to finish off the carpet section — could you tell me roughly how many of these have carpet?\n\n- Bedrooms\n- Living areas\n- Studies\n- Hallways\n- Stairs\n- Other areas"

3. If carpet_cleaning is empty ("") and suburb, bedrooms, bathrooms, and furnished are already filled:
   - Ask: "Do you need carpet steam cleaning as part of your vacate clean?"

DO NOT bring up carpet steam cleaning too early — never ask until the basic property details (suburb, bedrooms, bathrooms, furnished) are known.

DO NOT guess carpet cleaning intent from other fields — only extract it if clearly mentioned.

If any carpet count fields are provided but carpet_cleaning is still blank, wait for customer confirmation.

---
"""

# Trigger Words for Abuse Detection (Escalation Logic)
ABUSE_WORDS = ["fuck", "shit", "cunt", "bitch", "asshole"]

# === Create New Quote ID ===

def create_new_quote(session_id: str, force_new: bool = False):
    """
    Creates a new Airtable quote record for Brendan.
    Returns: (quote_id, record_id, "Gathering Info", fields)
    """
    quote_id = get_next_quote_id()

    fields = {
        "session_id": session_id,
        "quote_id": quote_id,
        "quote_stage": "Gathering Info",
        "privacy_acknowledged": False,
        "source": "Brendan"
    }

    headers = {
        "Authorization": f"Bearer {settings.AIRTABLE_API_KEY}",
        "Content-Type": "application/json"
    }

    url = f"https://api.airtable.com/v0/{settings.AIRTABLE_BASE_ID}/{quote(TABLE_NAME)}"
    payload = {"fields": fields}

    # ✅ Log payload before sending to Airtable
    logger.error(f"🚨 Payload before Airtable POST:\n{json.dumps(fields, indent=2)}")

    try:
        res = requests.post(url, headers=headers, json=payload)
        res.raise_for_status()
        record = res.json()
        record_id = record["id"]

        log_debug_event(record_id, "BACKEND", "New Quote Created", f"Quote ID: {quote_id}")
        logger.info(f"✅ New quote created | session_id: {session_id} | quote_id: {quote_id}")

        # === Flush debug log immediately after creation ===
        flushed = flush_debug_log(record_id)
        if flushed:
            update_quote_record(record_id, {"debug_log": flushed})

        return quote_id, record_id, "Gathering Info", fields

    except requests.exceptions.HTTPError as e:
        error_msg = f"Airtable 422 Error — Status Code: {res.status_code}, Response: {res.text}"
        logger.error(f"❌ Failed to create new quote: {error_msg}")
        log_debug_event(None, "BACKEND", "Quote Creation Failed", error_msg)
        raise HTTPException(status_code=500, detail="Failed to create new quote.")

    except Exception as e:
        logger.error(f"❌ Exception during quote creation: {e}")
        log_debug_event(None, "BACKEND", "Quote Creation Exception", str(e))
        raise HTTPException(status_code=500, detail="Failed to create new quote.")

# === Get Quote by Session ID ===

def get_quote_by_session(session_id: str):
    """
    Retrieves the latest quote record from Airtable using session_id.
    If no record is found, creates a new one.
    Returns: (quote_id, record_id, quote_stage, fields)
    """
    if not session_id:
        logger.warning("⚠️ get_quote_by_session called with empty session_id")
        return None

    safe_table_name = quote(TABLE_NAME)
    url = f"https://api.airtable.com/v0/{settings.AIRTABLE_BASE_ID}/{safe_table_name}"
    headers = {"Authorization": f"Bearer {settings.AIRTABLE_API_KEY}"}
    params = {
        "filterByFormula": f"{{session_id}}='{session_id}'",
        "sort[0][field]": "timestamp",
        "sort[0][direction]": "desc",
        "pageSize": 1
    }

    logger.info(f"🔍 Looking up quote by session_id: {session_id}")
    log_debug_event(None, "BACKEND", "Session Lookup Start", f"Session ID: {session_id}")

    response_data = None
    for attempt in range(3):
        try:
            log_debug_event(None, "BACKEND", "Session Lookup Request", f"Attempt {attempt + 1} — GET to Airtable")
            res = requests.get(url, headers=headers, params=params)
            res.raise_for_status()
            response_data = res.json()
            log_debug_event(None, "BACKEND", "Session Lookup Success", f"Data received on attempt {attempt + 1}")
            break
        except Exception as e:
            logger.warning(f"⚠️ Airtable fetch failed (Attempt {attempt + 1}/3): {e}")
            log_debug_event(None, "BACKEND", "Session Lookup Attempt Failed", f"Attempt {attempt + 1}: {str(e)}")
            if attempt == 2:
                logger.error(f"❌ Final failure after 3 attempts for session_id: {session_id}")
                log_debug_event(None, "BACKEND", "Session Lookup Final Failure", str(e))
                return None
            sleep(1)

    records = response_data.get("records", []) if response_data else []

    # === Create new quote if no record exists ===
    if not records:
        from app.services.quote_id_utils import get_next_quote_id

        new_quote_id = get_next_quote_id()
        new_data = {
            "session_id": session_id,
            "quote_id": new_quote_id,
            "quote_stage": "Gathering Info",
            "privacy_acknowledged": False
        }

        try:
            create_res = requests.post(
                url,
                headers={**headers, "Content-Type": "application/json"},
                json={"fields": new_data}
            )
            create_res.raise_for_status()
            record = create_res.json()
            record_id = record.get("id", "")
            fields = record.get("fields", {})
            logger.info(f"✅ New quote created — ID: {new_quote_id} | Record ID: {record_id}")
            log_debug_event(record_id, "BACKEND", "New Quote Created", f"session_id: {session_id}, quote_id: {new_quote_id}")
            return new_quote_id, record_id, "Gathering Info", fields
        except Exception as e:
            logger.error(f"❌ Failed to create new quote for session {session_id}: {e}")
            log_debug_event(None, "BACKEND", "Quote Creation Failed", str(e))
            return None

    # === Return existing record ===
    record = records[0]
    record_id = record.get("id", "")
    fields = record.get("fields", {})
    quote_id = fields.get("quote_id", "N/A")
    quote_stage = fields.get("quote_stage", "Gathering Info")

    # === Log shallow record warning ===
    if len(fields.keys()) < 10:
        log_debug_event(record_id, "BACKEND", "Record Warning", f"Returned with only {len(fields)} fields — may be incomplete")

    logger.info(f"✅ Quote found — ID: {quote_id} | Stage: {quote_stage} | Record ID: {record_id}")
    log_debug_event(record_id, "BACKEND", "Session Lookup Complete", f"Found quote_id: {quote_id}, stage: {quote_stage}")

    # === Flush debug log after successful lookup ===
    flushed = flush_debug_log(record_id)
    if flushed:
        update_quote_record(record_id, {"debug_log": flushed})

    return quote_id, record_id, quote_stage, fields

# === Update Quote Record ===

def update_quote_record(record_id: str, fields: dict):
    """
    Updates a record in Airtable with normalized fields.
    Ensures 'quote_stage' is persisted correctly and all updates conform to Airtable schema.
    Handles fallback retries and flushes debug log after update.
    """
    if not record_id:
        logger.warning("⚠️ update_quote_record called with no record_id")
        return []

    safe_table_name = quote(TABLE_NAME)
    url = f"https://api.airtable.com/v0/{settings.AIRTABLE_BASE_ID}/{safe_table_name}/{record_id}"
    headers = {
        "Authorization": f"Bearer {settings.AIRTABLE_API_KEY}",
        "Content-Type": "application/json"
    }

    schema_url = f"https://api.airtable.com/v0/meta/bases/{settings.AIRTABLE_BASE_ID}/tables"
    actual_keys = set()
    try:
        schema_res = requests.get(schema_url, headers={"Authorization": f"Bearer {settings.AIRTABLE_API_KEY}"})
        schema_res.raise_for_status()
        tables = schema_res.json().get("tables", [])
        for table in tables:
            if table.get("name") == TABLE_NAME:
                actual_keys = {f["name"] for f in table.get("fields", [])}
                break
    except Exception as e:
        logger.warning(f"⚠️ Could not fetch Airtable field schema: {e}")

    normalized_fields = {}
    MAX_REASONABLE_INT = 100

    for raw_key, value in fields.items():
        key = FIELD_MAP.get(raw_key, raw_key)
        corrected_key = next((k for k in actual_keys if k.lower() == key.lower()), key)

        if corrected_key not in actual_keys:
            logger.warning(f"⚠️ Skipping unknown Airtable field: {corrected_key}")
            continue

        if corrected_key == "carpet_cleaning":
            val = str(value).strip().capitalize()
            value = val if val in {"Yes", "No"} else ""
        elif corrected_key == "furnished":
            val = str(value).strip().lower()
            if "unfurnished" in val:
                value = "Unfurnished"
            elif "furnished" in val:
                value = "Furnished"
            else:
                value = ""
        elif corrected_key in INTEGER_FIELDS:
            try:
                value = int(float(value))
                if value > MAX_REASONABLE_INT:
                    logger.warning(f"⚠️ Clamping large int for {corrected_key}: {value}")
                    value = MAX_REASONABLE_INT
            except:
                value = 0
        elif corrected_key in BOOLEAN_FIELDS:
            value = value if isinstance(value, bool) else str(value).strip().lower() in {"yes", "true", "1", "on", "checked", "t"}
        elif corrected_key in {
            "gst_applied", "total_price", "base_hourly_rate", "price_per_session",
            "estimated_time_mins", "discount_applied", "mandurah_surcharge",
            "after_hours_surcharge", "weekend_surcharge", "calculated_hours"
        }:
            try:
                value = float(value)
            except:
                value = 0.0
        elif corrected_key == "special_requests":
            if not value or str(value).strip().lower() in {"no", "none", "false", "no special requests", "n/a"}:
                value = ""
            else:
                value = str(value).strip()
        elif corrected_key == "extra_hours_requested":
            try:
                value = float(value) if value not in [None, ""] else 0.0
            except:
                value = 0.0
        elif corrected_key == "pdf_url":
            value = str(value).strip()
        else:
            value = "" if value is None else str(value).strip()

        normalized_fields[corrected_key] = value

    # Add debug_log and message_log if present
    for log_field in ["debug_log", "message_log"]:
        if log_field in fields:
            normalized_fields[log_field] = str(fields[log_field]) if fields[log_field] is not None else ""

    # Always flush debug log last
    debug_log = flush_debug_log(record_id)
    if debug_log:
        normalized_fields["debug_log"] = debug_log
        log_debug_event(record_id, "BACKEND", "Debug Log Flushed", f"{len(debug_log)} chars flushed to Airtable")

    if not normalized_fields:
        logger.info(f"⏩ No valid fields to update for record {record_id}")
        log_debug_event(record_id, "BACKEND", "Update Skipped", "No valid fields to apply.")
        return []

    validated_fields = {k: v for k, v in normalized_fields.items() if k in actual_keys}
    if not validated_fields:
        log_debug_event(record_id, "BACKEND", "Validation Failed", "No matching fields for schema.")
        return []

    logger.info(f"\n📤 Updating Airtable Record: {record_id}")
    logger.info(f"🛠 Payload: {json.dumps(validated_fields, indent=2)}")

    # === Primary Bulk Update ===
    try:
        res = requests.patch(url, headers=headers, json={"fields": validated_fields})
        if res.ok:
            logger.info("✅ Airtable bulk update successful.")
            log_debug_event(record_id, "BACKEND", "Record Updated (Bulk)", f"Fields: {list(validated_fields.keys())}")
            return list(validated_fields.keys())
        logger.error(f"❌ Airtable bulk update failed ({res.status_code})")
        try:
            logger.error(f"🧾 Airtable Error: {res.json()}")
        except:
            logger.error("🧾 Airtable Error: (non-JSON)")
    except Exception as e:
        logger.error(f"❌ Exception in Airtable bulk update: {e}")
        log_debug_event(record_id, "BACKEND", "Bulk Update Exception", str(e))

    # === Fallback One-By-One Field Update ===
    successful = []
    for key, value in validated_fields.items():
        try:
            res = requests.patch(url, headers=headers, json={"fields": {key: value}})
            if res.ok:
                logger.info(f"✅ Field '{key}' updated individually.")
                successful.append(key)
            else:
                logger.error(f"❌ Field '{key}' update failed.")
        except Exception as e:
            logger.error(f"❌ Exception on '{key}': {e}")
            log_debug_event(record_id, "BACKEND", "Fallback Field Update Error", f"{key}: {e}")

    if successful:
        log_debug_event(record_id, "BACKEND", "Record Updated (Fallback)", f"Fields updated: {successful}")
    else:
        log_debug_event(record_id, "BACKEND", "Update Failed", "No fields updated in fallback.")

    return successful


# === Inline Quote Summary Helper ===

def get_inline_quote_summary(data: dict) -> str:
    """
    Generates a clear, backend-driven quote summary for Brendan to show in chat.
    Includes total price, estimated time, cleaner count, discount breakdown, selected services, bedrooms/bathrooms,
    and optional notes.
    """

    price = float(data.get("total_price", 0) or 0)
    time_est_mins = int(data.get("estimated_time_mins", 0) or 0)
    discount = float(data.get("discount_applied", 0) or 0)
    note = str(data.get("note", "") or "").strip()
    special_requests = str(data.get("special_requests", "") or "").strip()
    is_property_manager = str(data.get("is_property_manager", "") or "").lower() in TRUE_VALUES
    carpet_cleaning = str(data.get("carpet_cleaning", "") or "").strip()

    bedrooms = data.get("bedrooms_v2", 0)
    bathrooms = data.get("bathrooms_v2", 0)
    furnished = str(data.get("furnished_v2", "") or "").capitalize()

    # === Time & Cleaners Calculation ===
    hours = time_est_mins / 60
    cleaners = max(1, (time_est_mins + 299) // 300)
    hours_per_cleaner = hours / cleaners
    hours_display = int(hours_per_cleaner) if hours_per_cleaner.is_integer() else round(hours_per_cleaner + 0.49)

    # === Opening Line ===
    if price >= 800:
        opening = "Here’s what we’re looking at for this job:\n\n"
    elif price <= 300:
        opening = "Nice and easy — here’s your quote:\n\n"
    elif time_est_mins >= 360:
        opening = "This one will take a little longer — here’s your quote:\n\n"
    else:
        opening = "All sorted — here’s your quote:\n\n"

    summary = f"{opening}"
    summary += f"💰 **Total Price (incl. GST):** ${price:.2f}\n"
    summary += f"⏰ **Estimated Time:** ~{hours_display} hour(s) per cleaner with {cleaners} cleaner(s)\n"

    # === Discount Line ===
    if discount > 0:
        if is_property_manager and discount >= (price / 1.1) * 0.15:
            summary += f"🏷️ **Discount Applied:** ${discount:.2f} — 10% Vacate Clean Special + 5% Property Manager Bonus\n"
        else:
            summary += f"🏷️ **Discount Applied:** ${discount:.2f} — 10% Vacate Clean Special\n"

    # === Property Details ===
    if bedrooms or bathrooms or furnished:
        summary += "\n**Property Details:**\n"
        if bedrooms:
            summary += f"- Bedrooms: {bedrooms}\n"
        if bathrooms:
            summary += f"- Bathrooms: {bathrooms}\n"
        if furnished:
            summary += f"- Furnished: {furnished}\n"

    # === Selected Extras ===
    included = []

    EXTRA_SERVICES = {
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
        "weekend_cleaning": "Weekend Cleaning"
    }

    for field, label in EXTRA_SERVICES.items():
        if str(data.get(field, "")).lower() in TRUE_VALUES:
            included.append(f"- {label}")

    if carpet_cleaning == "Yes":
        included.append("- Carpet Steam Cleaning")

    if special_requests:
        included.append(f"- Special Request: {special_requests}")

    if included:
        summary += "\n🧹 **Cleaning Included:**\n" + "\n".join(included)

    # === Optional Note ===
    if note:
        summary += f"\n\n📜 **Note:** {note}"

    # === Final Prompt ===
    summary += (
        "\n\nThis quote is valid for **7 days**.\n"
        "Would you like me to send it to your email as a PDF, or would you like to make any changes?"
    )

    return summary.strip()

# === Generate Next Actions After Quote ===

def generate_next_actions(quote_stage: str):
    """
    Generates next steps based on the current quote stage.

    - After 'Quote Calculated': Offer PDF, email, edit, call office
    - After 'Gathering Personal Info': Ask for name/email/phone (skip if already gathered)
    - After 'Personal Info Received': Offer download or booking link
    """

    if quote_stage == "Quote Calculated":
        return [
            {
                "action": "quote_ready",
                "response": (
                    "What would you like to do next?\n\n"
                    "I can send you a formal PDF quote, email it over, "
                    "or make changes if something’s not quite right.\n\n"
                    "Or if you prefer, you can give our office a ring on **1300 918 388** — "
                    "just mention your quote number and they’ll help you book."
                ),
                "options": [
                    {"label": "📄 Generate PDF Quote", "value": "pdf_quote"},
                    {"label": "📧 Email Me the Quote", "value": "email_quote"},
                    {"label": "✏️ Make Changes", "value": "edit_quote"},
                    {"label": "📞 Call the Office", "value": "call_office"}
                ]
            }
        ]

    elif quote_stage == "Gathering Personal Info":
        return [
            {
                "action": "collect_info",
                "response": (
                    "No worries — just need a couple quick details so I can send your quote.\n\n"
                    "**What’s your full name, email address, and best contact number?**"
                ),
                "options": []
            }
        ]

    elif quote_stage == "Personal Info Received":
        return [
            {
                "action": "final_steps",
                "response": (
                    "All done! I’ve sent your PDF quote to your inbox.\n\n"
                    "If you'd like to book in now, you can do that here:\n"
                    "**https://orcacleaning.com.au/schedule**\n\n"
                    "Just enter your quote number when prompted."
                ),
                "options": [
                    {"label": "📥 Download Quote PDF", "value": "download_pdf"},
                    {"label": "📅 Book My Clean", "value": "book_clean"},
                    {"label": "📞 Call the Office", "value": "call_office"}
                ]
            }
        ]

    else:
        # Fallback
        return [
            {
                "action": "awaiting_quote",
                "response": "I’m still gathering details for your quote — let’s finish those first!",
                "options": []
            }
        ]

# === GPT Extraction (Production-Grade) ===

async def extract_properties_from_gpt4(message: str, log: str, record_id: str = None, quote_id: str = None, skip_log_lookup: bool = False):
    logger.info("🧠 Calling GPT-4 Turbo to extract properties...")
    if record_id:
        log_debug_event(record_id, "BACKEND", "Calling GPT-4", f"Message: {message[:100]}")

    weak_inputs = {"hi", "hello", "hey", "you there?", "you hear me?", "what’s up", "oi"}
    if message.lower().strip() in weak_inputs:
        reply = (
            "Just let me know what suburb we’re quoting for, how many bedrooms and bathrooms there are, "
            "and whether the property is furnished or unfurnished."
        )
        if record_id:
            log_debug_event(record_id, "GPT", "Weak Message Skipped", message)
            flushed = flush_debug_log(record_id)
            if flushed:
                update_quote_record(record_id, {"debug_log": flushed})
        return [], reply

    existing, current_stage = {}, ""
    if record_id and not skip_log_lookup:
        try:
            url = f"https://api.airtable.com/v0/{settings.AIRTABLE_BASE_ID}/Vacate%20Quotes/{record_id}"
            headers = {"Authorization": f"Bearer {settings.AIRTABLE_API_KEY}"}
            res = requests.get(url, headers=headers)
            res.raise_for_status()
            existing = res.json().get("fields", {})
            current_stage = existing.get("quote_stage", "")
            log_debug_event(record_id, "BACKEND", "Fetched Airtable Record", f"Stage: {current_stage}")
        except Exception as e:
            logger.warning(f"⚠️ Airtable fetch failed: {e}")
            log_debug_event(record_id, "BACKEND", "Airtable Fetch Failed", str(e))

    prepared_log = re.sub(r"[^\x20-\x7E\n]", "", log[-10000:])
    messages = [{
        "role": "system",
        "content": (
            "You are Brendan, the quoting assistant for Orca Cleaning.\n"
            "The customer has already seen this greeting from the frontend:\n\n"
            "“G’day! I’m Brendan from Orca Cleaning — your quoting officer for vacate cleans in Perth and Mandurah. "
            "This quote is fully anonymous and no booking is required — I’m just here to help. View our Privacy Policy.”\n\n"
            "Do NOT repeat this greeting. Never say 'Hi', 'Hello', 'Hey', or 'G’day' again.\n"
            "Start by gently asking the customer what name they’d like the quote to be under — e.g., 'Is there a first name I can pop on the quote?'.\n"
            "Then ask for suburb, bedrooms, bathrooms, and furnished/unfurnished.\n"
            "IMPORTANT: Always reply in JSON with two fields: 'properties' and 'response'."
        )
    }]
    for line in prepared_log.split("\n"):
        if line.startswith("USER:") and line.strip() != "USER: __init__":
            messages.append({"role": "user", "content": line[5:].strip()})
        elif line.startswith("BRENDAN:"):
            messages.append({"role": "assistant", "content": line[8:].strip()})
        elif line.startswith("SYSTEM:"):
            messages.append({"role": "system", "content": line[7:].strip()})

    if message == "__init__":
        messages.append({
            "role": "system",
            "content": (
                "The user has just opened the chat. The greeting was already shown.\n"
                "- Do not say 'Hi', 'Hey', 'Hello' or 'G’day'.\n"
                "- Ask what name to use with something polite and low-pressure like: 'Is there a first name I can pop on the quote?'\n"
                "- Then ask suburb, bedrooms, bathrooms, and furnished/unfurnished.\n"
                "- Suppress carpet and extras until base info is in."
            )
        })
        log_debug_event(record_id, "GPT", "Init Trigger Detected", "Suppressing repeat greeting message.")
    elif current_stage == "Quote Calculated":
        messages.append({
            "role": "system",
            "content": "The quote has already been calculated. DO NOT regenerate unless the customer changes details."
        })
        log_debug_event(record_id, "GPT", "Quote Already Calculated", "GPT instructed not to regenerate.")

    messages.append({"role": "user", "content": message.strip()})
    log_debug_event(record_id, "GPT", "Messages Prepared", f"{len(messages)} messages ready for GPT")

    def call_gpt_and_parse(msgs, attempt=1):
        try:
            res = client.chat.completions.create(
                model="gpt-4-turbo",
                messages=msgs,
                max_tokens=3000,
                temperature=0.4
            )
            raw = res.choices[0].message.content.strip()
            log_debug_event(record_id, "GPT", f"Raw Attempt {attempt}", raw[:300])
            start, end = raw.find("{"), raw.rfind("}")
            if start == -1 or end == -1:
                raise ValueError("JSON block not found.")
            parsed = json.loads(raw[start:end + 1])
            if not isinstance(parsed, dict):
                raise TypeError("Parsed block is not a dict")
            return parsed
        except Exception as e:
            log_debug_event(record_id, "GPT", f"Parse Failed (Attempt {attempt})", str(e))
            return None

    parsed = call_gpt_and_parse(messages, 1)
    if not isinstance(parsed, dict):
        messages.insert(1, {"role": "system", "content": "You MUST respond with valid JSON containing only 'properties' and 'response'. Do not reply in plain text."})
        parsed = call_gpt_and_parse(messages, 2)

    if not isinstance(parsed, dict):
        log_debug_event(record_id, "GPT", "Invalid Parse", f"Type: {type(parsed)} | Value: {str(parsed)[:100]}")
        reply = "No worries — could you let me know how many bedrooms and bathrooms we're quoting for, and whether it's furnished?"
        flushed = flush_debug_log(record_id)
        if flushed:
            update_quote_record(record_id, {"debug_log": flushed})
        return [], reply

    raw_props = parsed.get("properties", [])
    reply = parsed.get("response", "").strip()

    if isinstance(raw_props, dict):
        raw_props = [{"property": k, "value": v} for k, v in raw_props.items()]
        log_debug_event(record_id, "GPT", "Converted Dict Props", f"Fixed to list with {len(raw_props)} items")
    elif not isinstance(raw_props, list):
        log_debug_event(record_id, "GPT", "Malformed Props", f"Expected list or dict, got {type(raw_props)} — Value: {str(raw_props)[:100]}")
        flushed = flush_debug_log(record_id)
        if flushed:
            update_quote_record(record_id, {"debug_log": flushed})
        return [], reply or "Just checking — how many bedrooms and bathrooms are we quoting for?"

    safe_props = []
    for p in raw_props:
        if isinstance(p, dict) and "property" in p and "value" in p:
            safe_props.append(p)
        else:
            log_debug_event(record_id, "GPT", "Skipped Invalid Prop", str(p))

    if not safe_props:
        log_debug_event(record_id, "GPT", "Empty Properties", "GPT returned no valid properties. Using response anyway.")
        flushed = flush_debug_log(record_id)
        if flushed:
            update_quote_record(record_id, {"debug_log": flushed})
        return [], reply

    props = [p for p in safe_props if p["property"] != "source"]
    props.append({"property": "source", "value": "Brendan"})
    log_debug_event(record_id, "GPT", "Source Set", "source = Brendan injected")

    try:
        prop_map = {p["property"]: p["value"] for p in props if isinstance(p, dict) and "property" in p and "value" in p}
    except Exception as e:
        log_debug_event(record_id, "GPT", "Prop Map Error", str(e))
        return [], reply

    full_name = prop_map.get("customer_name", "").strip()
    if full_name:
        first_name = full_name.split(" ")[0]
        props = [p for p in props if p["property"] != "customer_name"]
        props.append({"property": "customer_name", "value": first_name})
        log_debug_event(record_id, "GPT", "Temp Name Stored", f"First name used for chat: {first_name}")

    abuse_detected = any(word in message.lower() for word in ["fuck", "shit", "cunt", "dickhead", "wanker"])
    if abuse_detected:
        quote_id = quote_id or existing.get("quote_id", "N/A")
        if current_stage == "Abuse Warning":
            final_msg = f"Unfortunately we have to end the quote due to language. You're welcome to call our office if you'd like to continue. Quote Number: {quote_id}."
            log_debug_event(record_id, "BACKEND", "Chat Banned", f"Repeated abuse. Quote ID: {quote_id}")
            flushed = flush_debug_log(record_id)
            if flushed:
                update_quote_record(record_id, {"debug_log": flushed})
            return [{"property": "quote_stage", "value": "Chat Banned"}], final_msg
        else:
            log_debug_event(record_id, "BACKEND", "Abuse Warning", "First abuse detected.")
            reply = "Just a quick heads-up — we can’t continue the quote if abusive language is used. Let’s keep it respectful!\n\n" + reply
            flushed = flush_debug_log(record_id)
            if flushed:
                update_quote_record(record_id, {"debug_log": flushed})
            return [{"property": "quote_stage", "value": "Abuse Warning"}], reply.strip()

    all_fields = existing.copy()
    all_fields.update(prop_map)
    for field in BOOLEAN_FIELDS:
        if field in VALID_AIRTABLE_FIELDS and field not in all_fields:
            all_fields[field] = False
            log_debug_event(record_id, "BACKEND", "Patched Missing Checkbox", f"{field} = False")

    props = [
        p for p in props
        if not (
            p["property"] in FIELD_MAP and
            FIELD_MAP[p["property"]].get("type") == "single select" and
            str(p["value"]).strip() == ""
        )
    ]

    if should_calculate_quote(all_fields):
        props.append({"property": "quote_stage", "value": "Quote Calculated"})
        log_debug_event(record_id, "BACKEND", "Stage Forced", "Backend promoted stage to Quote Calculated")

    log_debug_event(record_id, "GPT", "Properties Parsed", f"Props: {len(props)} | First Line: {reply[:100]}")
    flushed = flush_debug_log(record_id)
    if flushed:
        update_quote_record(record_id, {"debug_log": flushed})

    return props, reply

# === GPT Error Email Alert ===

def send_gpt_error_email(error_msg: str):
    """
    Sends an email to admin if GPT extraction fails and logs the error event.
    Also flushes debug log if a record_id is found in the error body.
    """

    sender_email = "info@orcacleaning.com.au"
    recipient_email = "admin@orcacleaning.com.au"
    smtp_server = "smtp.office365.com"
    smtp_port = 587
    smtp_pass = settings.SMTP_PASS

    if not smtp_pass:
        logger.error("❌ Missing SMTP password — cannot send GPT error email.")
        try:
            log_debug_event(None, "BACKEND", "Email Send Failed", "Missing SMTP_PASS environment variable")
        except Exception as e:
            logger.error(f"❌ Error logging failure: {e}")
        return

    msg = MIMEText(error_msg)
    msg["Subject"] = "🚨 Brendan GPT Extraction Error"
    msg["From"] = sender_email
    msg["To"] = recipient_email

    for attempt in range(2):
        try:
            with smtplib.SMTP(smtp_server, smtp_port) as server:
                server.starttls()
                server.login(sender_email, smtp_pass)
                server.sendmail(
                    from_addr=sender_email,
                    to_addrs=[recipient_email],
                    msg=msg.as_string()
                )
            logger.info("✅ GPT error email sent successfully.")
            try:
                log_debug_event(None, "BACKEND", "GPT Error Email Sent", f"Error email sent to {recipient_email} (attempt {attempt + 1})")
            except Exception as e:
                logger.error(f"❌ Error logging email send success: {e}")
            break  # Exit after success
        except smtplib.SMTPException as e:
            logger.warning(f"⚠️ SMTP error (attempt {attempt + 1}/2): {e}")
            if attempt == 1:
                logger.error("❌ Failed to send GPT error email after 2 attempts.")
                try:
                    log_debug_event(None, "BACKEND", "GPT Error Email Failed", f"SMTP error: {str(e)}")
                except Exception as log_e:
                    logger.error(f"❌ Error logging email send failure: {log_e}")
            else:
                sleep(5)
        except Exception as e:
            logger.error(f"❌ Unexpected error sending GPT error email: {e}")
            try:
                log_debug_event(None, "BACKEND", "Unexpected Email Error", str(e))
            except Exception as log_e:
                logger.error(f"❌ Error logging unexpected email failure: {log_e}")
            return

    # Attempt flush even without known record_id
    try:
        record_id_match = re.search(r"record[_ ]?id[:=]?[^\w]?(\w{5,})", error_msg, re.IGNORECASE)
        if record_id_match:
            record_id = record_id_match.group(1).strip()
            flushed = flush_debug_log(record_id)
            if flushed:
                update_quote_record(record_id, {"debug_log": flushed})
    except Exception as e:
        logger.warning(f"⚠️ Failed to flush debug log in send_gpt_error_email: {e}")
        log_debug_event(None, "BACKEND", "Debug Log Flush Error", str(e))

# === Append Message Log ===

def append_message_log(record_id: str, message: str, sender: str):
    """
    Appends a new message to the 'message_log' field in Airtable.
    Includes timestamp, role, and preserves full order.
    Flushes debug_log after append to avoid loss.
    """
    if not record_id:
        logger.error("❌ Cannot append message_log — missing record ID")
        log_debug_event(None, "BACKEND", "Log Failed", "Missing record ID for message append")
        return

    message = str(message or "").strip()
    if not message:
        logger.info("⏩ Empty message — skipping append")
        return

    sender_clean = str(sender or "user").strip().upper()
    timestamp = datetime.utcnow().isoformat()

    if sender_clean == "USER" and message.lower() == "__init__":
        new_entry = f"[{timestamp}] SYSTEM_TRIGGER: Brendan started a new quote"
    else:
        new_entry = f"[{timestamp}] {sender_clean}: {message}"

    url = f"https://api.airtable.com/v0/{settings.AIRTABLE_BASE_ID}/{TABLE_NAME}/{record_id}"
    headers = {"Authorization": f"Bearer {settings.AIRTABLE_API_KEY}"}

    # === Load Existing Log ===
    try:
        res = requests.get(url, headers=headers)
        res.raise_for_status()
        old_log = str(res.json().get("fields", {}).get("message_log", "")).strip()
    except Exception as e:
        logger.warning(f"⚠️ Could not fetch current message_log: {e}")
        log_debug_event(record_id, "BACKEND", "Message Log Fetch Failed", str(e))
        return

    # === Combine and Trim If Needed ===
    combined_log = f"{old_log}\n{new_entry}" if old_log else new_entry
    was_truncated = False
    if len(combined_log) > MAX_LOG_LENGTH:
        combined_log = combined_log[-MAX_LOG_LENGTH:]
        was_truncated = True

    # === Save Combined Log ===
    try:
        update_quote_record(record_id, {"message_log": combined_log})
        logger.info(f"✅ message_log updated for {record_id} (len={len(combined_log)})")
    except Exception as e:
        logger.error(f"❌ Failed to update message_log: {e}")
        log_debug_event(record_id, "BACKEND", "Message Log Update Failed", str(e))
        return

    # === Log Debug Metadata ===
    try:
        detail = (
            "SYSTEM_TRIGGER: Brendan started a new quote"
            if sender_clean == "USER" and message.lower() == "__init__"
            else f"{sender_clean} message logged ({len(message)} chars)"
        )
        if was_truncated:
            detail += " | ⚠️ Log truncated"
        log_debug_event(record_id, "BACKEND", "Message Appended", detail)
    except Exception as e:
        logger.warning(f"⚠️ Debug log event failed: {e}")
        log_debug_event(record_id, "BACKEND", "Debug Log Failure", str(e))

    # === Flush Debug Log ===
    try:
        flushed = flush_debug_log(record_id)
        if flushed:
            update_quote_record(record_id, {"debug_log": flushed})
    except Exception as e:
        logger.warning(f"⚠️ Failed to flush debug log: {e}")
        log_debug_event(record_id, "BACKEND", "Debug Log Flush Error", str(e))

# === Handle Chat Init === 

async def handle_chat_init(session_id: str):
    try:
        log_debug_event(None, "BACKEND", "Init Triggered", f"User opened chat — Session: {session_id}")
        existing = get_quote_by_session(session_id)

        if existing:
            try:
                quote_id, record_id, stage, fields = existing
                timestamp = fields.get("timestamp")
                if not timestamp or stage in ["Quote Calculated", "Personal Info Received", "Booking Confirmed"]:
                    raise ValueError("Stale or completed quote, creating new.")
                log_debug_event(record_id, "BACKEND", "Existing Quote", f"Continuing session: {quote_id}")
            except Exception as e:
                log_debug_event(None, "BACKEND", "Quote Reuse Blocked", str(e))
                existing = None

        if not existing:
            quote_id, record_id, stage, fields = create_new_quote(session_id, force_new=True)
            session_id = fields.get("session_id", session_id)
            log_debug_event(record_id, "BACKEND", "New Quote Created", f"Session: {session_id}")

        # Append init to message log
        append_message_log(record_id, "SYSTEM_TRIGGER: Brendan started a new quote", "system")

        # Flush debug log immediately after init
        flushed = flush_debug_log(record_id)
        if flushed:
            update_quote_record(record_id, {"debug_log": flushed})

        # Let GPT take over — init message is passed into conversation as 'user: __init__'
        properties, reply = await extract_properties_from_gpt4(
            "__init__", "USER: __init__", record_id=record_id, quote_id=None, skip_log_lookup=True
        )

        append_message_log(record_id, reply, "brendan")
        log_debug_event(record_id, "BACKEND", "Init Complete", "Brendan sent first message.")

        return JSONResponse(content={
            "properties": properties,
            "response": reply,
            "next_actions": [],
            "session_id": session_id
        })

    except Exception as e:
        log_debug_event(None, "BACKEND", "Fatal Init Error", str(e))
        raise HTTPException(status_code=500, detail="Failed to initialize Brendan.")

# === Brendan API Router ===

router = APIRouter()

# === Brendan API Router ===

@router.post("/filter-response")
async def filter_response_entry(request: Request):
    try:
        body = await request.json()
        message = str(body.get("message", "")).strip()
        session_id = str(body.get("session_id", "")).strip()

        if not session_id:
            raise HTTPException(status_code=400, detail="Session ID is required.")

        log_debug_event(None, "BACKEND", "Incoming Message", f"Session: {session_id}, Message: {message}")

        if message.lower() == "__init__":
            try:
                return await handle_chat_init(session_id)
            except Exception as e:
                log_debug_event(None, "BACKEND", "Init Error", str(e))
                raise HTTPException(status_code=500, detail="Init failed.")

        quote_data = get_quote_by_session(session_id)
        if not quote_data:
            raise HTTPException(status_code=404, detail="Quote not found.")

        quote_id, record_id, quote_stage, fields = quote_data
        message_lower = message.lower()

        if quote_stage == "Chat Banned":
            return JSONResponse(content={
                "properties": [],
                "response": "This chat is closed. Call 1300 918 388 if you still need a quote.",
                "next_actions": [],
                "session_id": session_id
            })

        if quote_stage == "Gathering Personal Info" and not fields.get("privacy_acknowledged"):
            return await handle_privacy_consent(message, message_lower, record_id, session_id)

        if quote_stage == "Gathering Personal Info" and fields.get("privacy_acknowledged"):
            name = fields.get("customer_name", "").strip()
            email = fields.get("customer_email", "").strip()
            phone = fields.get("customer_phone", "").strip()

            if name and email and phone:
                try:
                    pdf_path = generate_quote_pdf(fields)
                    send_quote_email(email, name, pdf_path, quote_id)
                    log_debug_event(record_id, "BACKEND", "PDF Sent", f"PDF sent to {email}")
                    update_quote_record(record_id, {"quote_stage": "Personal Info Received"})
                    append_message_log(record_id, f"PDF quote sent to {email}", "brendan")

                    return JSONResponse(content={
                        "properties": [],
                        "response": f"Thanks {name}! I’ve just sent your quote to {email}. Let me know if you need help with anything else — or feel free to book directly anytime: https://orcacleaning.com.au/schedule?quote_id={quote_id}",
                        "next_actions": generate_next_actions("Personal Info Received"),
                        "session_id": session_id
                    })
                except Exception as e:
                    log_debug_event(record_id, "BACKEND", "PDF/Email Error", str(e))
                    raise HTTPException(status_code=500, detail="Failed to send quote email.")

        message_log = fields.get("message_log", "")[-LOG_TRUNCATE_LENGTH:]
        if quote_stage == "Quote Calculated" and any(k in message_lower for k in PDF_KEYWORDS):
            message_log = PDF_SYSTEM_MESSAGE + "\n\n" + message_log
            log_debug_event(record_id, "BACKEND", "PDF Trigger", f"User asked for PDF: {message_lower[:50]}")

        append_message_log(record_id, message, "user")

        properties, reply = await extract_properties_from_gpt4(message, message_log, record_id, quote_id)

        parsed = {p["property"]: p["value"] for p in properties if "property" in p and "value" in p}
        updated_fields = fields.copy()
        updated_fields.update(parsed)

        for required in ["bedrooms_v2", "bathrooms_v2", "source"]:
            if required not in parsed and required in fields:
                parsed[required] = fields[required]

        if should_calculate_quote(updated_fields) and quote_stage != "Quote Calculated":
            try:
                result = calculate_quote(QuoteRequest(**updated_fields))
                parsed.update(result.model_dump())
                parsed["quote_stage"] = "Quote Calculated"
                reply = get_inline_quote_summary(result.model_dump())
                log_debug_event(record_id, "BACKEND", "Quote Ready", f"${parsed.get('total_price')} for {parsed.get('estimated_time_mins')} mins")
            except Exception as e:
                log_debug_event(record_id, "BACKEND", "Quote Calculation Failed", str(e))

        update_quote_record(record_id, parsed)
        append_message_log(record_id, reply, "brendan")

        next_actions = generate_next_actions(parsed.get("quote_stage", quote_stage))

        return JSONResponse(content={
            "properties": properties,
            "response": reply,
            "next_actions": next_actions,
            "session_id": session_id
        })

    except Exception as e:
        log_debug_event(None, "BACKEND", "Fatal Error", str(e))
        raise HTTPException(status_code=500, detail="Internal server error.")
