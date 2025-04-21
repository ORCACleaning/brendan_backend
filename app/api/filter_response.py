# === Built-in Python Modules ===
import os
import re
import json
import uuid
import base64
import smtplib
import logging
import requests
import inflect
import traceback  # ✅ required for error reporting
from time import sleep
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from urllib.parse import quote

# === Third-Party Modules ===
import pytz
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

# === OpenAI Client Setup ===
from openai import OpenAI

if not os.getenv("OPENAI_API_KEY"):
    logger.error("❌ Missing OPENAI_API_KEY — Brendan will crash if GPT is called.")
else:
    print("✅ Brendan backend loaded and OpenAI key detected")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# === Global Schema Cache ===
AIRTABLE_SCHEMA_CACHE = {
    "fetched": False,
    "actual_keys": [],
    "valid_fields": []
}

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
    try:
        quote_id = get_next_quote_id()
        url = f"https://api.airtable.com/v0/{settings.AIRTABLE_BASE_ID}/{quote(TABLE_NAME)}"
        headers = {
            "Authorization": f"Bearer {settings.AIRTABLE_API_KEY}",
            "Content-Type": "application/json"
        }

        timestamp = datetime.utcnow().isoformat()  # ✅ keep for logs only — do not include in Airtable
        fields = {
            "session_id": session_id,
            "quote_id": quote_id,
            "quote_stage": "Gathering Info",
            "privacy_acknowledged": False,
            "source": "Brendan"
        }

        logger.info(f"📤 Creating new quote with payload:\n{json.dumps(fields, indent=2)}")
        log_debug_event(None, "BACKEND", "Function Start", f"create_new_quote(session_id={session_id}, force_new={force_new})")
        log_debug_event(None, "BACKEND", "Creating New Quote", f"Session: {session_id}, Quote ID: {quote_id}, Timestamp: {timestamp} (not sent)")
        log_debug_event(None, "BACKEND", "Injected Source Field", "source = Brendan")

        payload = {"fields": fields}
        res = requests.post(url, headers=headers, json=payload)
        res.raise_for_status()

        response = res.json()
        record_id = response.get("id", "")
        returned_fields = response.get("fields", {})

        logger.info(f"✅ New quote created — session_id: {session_id} | quote_id: {quote_id} | record_id: {record_id}")
        log_debug_event(record_id, "BACKEND", "New Quote Created", f"Record ID: {record_id}, Fields: {list(returned_fields.keys())}")

        # Extra validation
        required = ["session_id", "quote_id", "quote_stage", "source"]
        for r in required:
            if r not in returned_fields:
                log_debug_event(record_id, "BACKEND", "Missing Field After Creation", f"{r} is missing in returned_fields")

        # Flush and store debug log
        flushed = flush_debug_log(record_id)
        if flushed:
            update_quote_record(record_id, {"debug_log": flushed})
            log_debug_event(record_id, "BACKEND", "Debug Log Flushed", f"{len(flushed)} chars flushed post-create")

        return quote_id, record_id, "Gathering Info", returned_fields

    except requests.exceptions.HTTPError as e:
        error_msg = f"Airtable Error — Status Code: {res.status_code}, Response: {res.text}"
        logger.error(f"❌ Airtable quote creation failed: {error_msg}")
        log_debug_event(None, "BACKEND", "Quote Creation Failed", error_msg)
        raise HTTPException(status_code=500, detail="Quote creation failed — Airtable error.")

    except Exception as e:
        logger.error(f"❌ Unexpected exception during quote creation: {e}")
        log_debug_event(None, "BACKEND", "Quote Creation Exception", str(e))
        raise HTTPException(status_code=500, detail="Quote creation failed — unexpected error.")


# === Get Quote by Session ===

def get_quote_by_session(session_id: str):
    """
    Looks up existing quote in Airtable by session_id.
    Returns dict with quote_id, record_id, quote_stage, fields.
    Logs all paths for successful, partial, or failed lookups.
    Ensures customer_name is included in the fields.
    """
    try:
        if not session_id:
            raise ValueError("Empty session_id passed to get_quote_by_session")

        log_debug_event(None, "BACKEND", "Session Lookup Start", f"session_id={session_id}")

        safe_table_name = quote(TABLE_NAME)
        url = f"https://api.airtable.com/v0/{settings.AIRTABLE_BASE_ID}/{safe_table_name}"
        headers = {"Authorization": f"Bearer {settings.AIRTABLE_API_KEY}"}
        params = {
            "filterByFormula": f"{{session_id}} = '{session_id}'",
            "maxRecords": 1
        }

        res = requests.get(url, headers=headers, params=params)
        res.raise_for_status()

        records = res.json().get("records", [])
        if not records:
            log_debug_event(None, "BACKEND", "Session Not Found", f"No Airtable record found for {session_id}")
            return None

        record = records[0]
        fields = record.get("fields", {})
        record_id = record.get("id", "")

        # Ensure customer_name is included in the fields response
        customer_name = fields.get("customer_name", "").strip()
        if customer_name:
            fields["customer_name"] = customer_name

        quote_id = fields.get("quote_id", "")
        quote_stage = fields.get("quote_stage", "Gathering Info")

        if not record_id or not fields:
            log_debug_event(None, "BACKEND", "Session Found But Incomplete", f"record_id or fields missing for {session_id}")
            return None

        result = {
            "quote_id": quote_id,
            "record_id": record_id,
            "quote_stage": quote_stage,
            "fields": fields
        }

        log_debug_event(record_id, "BACKEND", "Session Found", f"Quote ID: {quote_id}, Stage: {quote_stage}, Fields: {list(fields.keys())}")
        return result

    except Exception as e:
        logger.warning(f"⚠️ get_quote_by_session() failed: {e}")
        log_debug_event(None, "BACKEND", "Session Lookup Error", str(e))
        return None


# === Update Quote Record ====

def update_quote_record(record_id: str, fields: dict):
    """
    Updates a record in Airtable with normalized fields.
    Handles batching, safe select handling, debug flushing, and fallback logic.
    Logs full trace for validation, normalization, payload, success, and failures.
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

    log_debug_event(record_id, "BACKEND", "Function Start", f"update_quote_record(record_id={record_id}, fields={list(fields.keys())})")

    actual_keys = AIRTABLE_SCHEMA_CACHE.get("actual_keys", set())
    if not AIRTABLE_SCHEMA_CACHE.get("fetched"):
        try:
            schema_url = f"https://api.airtable.com/v0/meta/bases/{settings.AIRTABLE_BASE_ID}/tables"
            schema_res = requests.get(schema_url, headers={"Authorization": f"Bearer {settings.AIRTABLE_API_KEY}"})
            schema_res.raise_for_status()
            tables = schema_res.json().get("tables", [])
            for table in tables:
                if table.get("name") == TABLE_NAME:
                    actual_keys = {f["name"] for f in table.get("fields", [])}
                    AIRTABLE_SCHEMA_CACHE["actual_keys"] = actual_keys
                    AIRTABLE_SCHEMA_CACHE["fetched"] = True
                    log_debug_event(record_id, "BACKEND", "Schema Cached", f"{len(actual_keys)} fields loaded from Airtable schema")
                    break
        except Exception as e:
            logger.warning(f"⚠️ Could not fetch Airtable field schema: {e}")
            log_debug_event(record_id, "BACKEND", "Schema Fetch Failed", str(e))

    if not AIRTABLE_SCHEMA_CACHE.get("fetched") or "debug_log" not in actual_keys:
        if "debug_log" in fields:
            fields.pop("debug_log", None)
            log_debug_event(record_id, "BACKEND", "Debug Field Skipped", "debug_log not in schema or schema not fetched")

    normalized_fields = {}
    MAX_REASONABLE_INT = 100
    SELECT_FIELDS = {"carpet_cleaning", "furnished", "quote_stage"}

    for raw_key, value in fields.items():
        key = FIELD_MAP.get(raw_key, raw_key)
        corrected_key = next((k for k in actual_keys if k.lower() == key.lower()), key)

        log_debug_event(record_id, "BACKEND", "Raw Field Input", f"{raw_key} → {corrected_key} = {value}")

        if corrected_key not in actual_keys or corrected_key not in VALID_AIRTABLE_FIELDS:
            logger.warning(f"⚠️ Skipping invalid field: {corrected_key}")
            log_debug_event(record_id, "BACKEND", "Field Skipped", f"{corrected_key} is not in schema or allowed fields")
            continue

        if corrected_key in {"carpet_cleaning", "quote_stage", "source"} and raw_key not in fields:
            log_debug_event(record_id, "BACKEND", "Protected Field Skipped", f"{corrected_key} not explicitly passed")
            continue

        try:
            if corrected_key == "carpet_cleaning":
                val = str(value).strip().capitalize()
                value = val if val in {"Yes", "No"} else ""
            elif corrected_key == "furnished":
                val = str(value).strip().capitalize()
                value = val if val in {"Furnished", "Unfurnished"} else ""
            elif corrected_key == "quote_stage":
                allowed = {
                    "Gathering Info", "Quote Calculated", "Gathering Personal Info",
                    "Personal Info Received", "Booking Confirmed", "Abuse Warning", "Chat Banned"
                }
                if str(value).strip() not in allowed:
                    log_debug_event(record_id, "BACKEND", "Quote Stage Rejected", f"{value} not in {allowed}")
                    continue
            elif corrected_key in INTEGER_FIELDS:
                if not isinstance(value, (int, float)):
                    value = int(float(value))
                if value > MAX_REASONABLE_INT:
                    logger.warning(f"⚠️ Clamping large int for {corrected_key}: {value}")
                    log_debug_event(record_id, "BACKEND", "Int Clamped", f"{corrected_key}: {value}")
                    value = MAX_REASONABLE_INT
            elif corrected_key in BOOLEAN_FIELDS:
                if not isinstance(value, bool):
                    original = value
                    value = str(value).strip().lower() in {"yes", "true", "1", "on", "checked", "t"}
                    log_debug_event(record_id, "BACKEND", "Bool Normalized", f"{corrected_key}: {original} → {value}")
            elif corrected_key in {
                "gst_applied", "total_price", "base_hourly_rate", "price_per_session",
                "estimated_time_mins", "discount_applied", "mandurah_surcharge",
                "after_hours_surcharge", "weekend_surcharge", "calculated_hours"
            }:
                value = float(value)
            elif corrected_key == "special_requests":
                if not value or str(value).strip().lower() in {"no", "none", "false", "no special requests", "n/a"}:
                    value = ""
                else:
                    value = str(value).strip()
            elif corrected_key == "extra_hours_requested":
                value = float(value) if value not in [None, ""] else 0.0
            elif corrected_key == "pdf_url":
                value = str(value).strip()
            else:
                if not isinstance(value, (int, float, bool)):
                    value = "" if value is None else str(value).strip()

        except Exception as e:
            logger.warning(f"⚠️ Failed to normalize {corrected_key}: {e}")
            log_debug_event(record_id, "BACKEND", "Normalization Error", f"{corrected_key}: {e}")
            continue

        if corrected_key in SELECT_FIELDS and value == "":
            logger.warning(f"⚠️ Skipping empty select field: {corrected_key}")
            log_debug_event(record_id, "BACKEND", "Empty Select Skipped", corrected_key)
            continue

        normalized_fields[corrected_key] = value

    for log_field in ["debug_log", "message_log"]:
        if log_field in fields and log_field not in normalized_fields:
            normalized_fields[log_field] = str(fields[log_field]) if fields[log_field] else ""

    debug_log = flush_debug_log(record_id)
    if debug_log and "debug_log" in actual_keys:
        normalized_fields["debug_log"] = debug_log
        log_debug_event(record_id, "BACKEND", "Debug Log Flushed", f"{len(debug_log)} chars flushed to Airtable")

    if not normalized_fields:
        log_debug_event(record_id, "BACKEND", "Update Skipped", "No normalized fields to update.")
        return []

    validated_fields = {k: v for k, v in normalized_fields.items() if k in actual_keys and k in VALID_AIRTABLE_FIELDS}
    if not validated_fields:
        log_debug_event(record_id, "BACKEND", "Validation Failed", "All fields invalid after schema + rules filtering.")
        return []

    logger.info(f"\n📤 Updating Airtable Record: {record_id}")
    logger.info(f"🛠 Payload: {json.dumps(validated_fields, indent=2)}")

    try:
        res = requests.patch(url, headers=headers, json={"fields": validated_fields})
        if res.ok:
            logger.info("✅ Airtable bulk update successful.")
            log_debug_event(record_id, "BACKEND", "Record Updated (Bulk)", f"Fields: {list(validated_fields.keys())}")
            return list(validated_fields.keys())

        logger.error(f"❌ Airtable bulk update failed ({res.status_code})")
        try:
            logger.error(f"🧾 Airtable Error: {res.json()}")
            log_debug_event(record_id, "BACKEND", "Airtable Error", str(res.json()))
        except:
            logger.error("🧾 Airtable Error: (non-JSON)")
            log_debug_event(record_id, "BACKEND", "Airtable Error", "Non-JSON response")

    except Exception as e:
        logger.error(f"❌ Exception in Airtable bulk update: {e}")
        log_debug_event(record_id, "BACKEND", "Bulk Update Exception", str(e))

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
    and optional notes. Always generated from backend — never GPT.
    """
    record_id = data.get("record_id", "")  # optional, passed only if available for logging

    price = float(data.get("total_price", 0) or 0)
    time_est_mins = int(data.get("estimated_time_mins", 0) or 0)
    discount = float(data.get("discount_applied", 0) or 0)
    note = str(data.get("note", "") or "").strip()
    special_requests = str(data.get("special_requests", "") or "").strip()
    is_property_manager = str(data.get("is_property_manager", "") or "").lower() in TRUE_VALUES
    carpet_cleaning = str(data.get("carpet_cleaning", "") or "").strip()

    bedrooms = data.get("bedrooms_v2", 0)
    bathrooms = data.get("bathrooms_v2", 0)

    # Handle both furnished_v2 and furnished_status
    furnished_raw = data.get("furnished_v2") or data.get("furnished_status") or ""
    furnished = str(furnished_raw).strip().capitalize()

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
    property_lines = []
    if bedrooms:
        property_lines.append(f"- Bedrooms: {bedrooms}")
    if bathrooms:
        property_lines.append(f"- Bathrooms: {bathrooms}")
    if furnished:
        property_lines.append(f"- Furnished: {furnished}")

    if property_lines:
        summary += "\n**Property Details:**\n" + "\n".join(property_lines)

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
        summary += "\n\n🧹 **Cleaning Included:**\n" + "\n".join(included)

    # === Optional Note ===
    if note:
        summary += f"\n\n📜 **Note:** {note}"

    # === Final Prompt ===
    summary += (
        "\n\nThis quote is valid for **7 days**.\n"
        "Would you like me to send it to your email as a PDF, or would you like to make any changes?"
    )

    final_summary = summary.strip()

    # === Log summary output ===
    try:
        log_debug_event(record_id, "BACKEND", "Inline Quote Summary Generated", final_summary[:300])
    except Exception:
        pass  # fail silently if record_id missing

    return final_summary


# === Generate Next Actions After Quote ===

def generate_next_actions(quote_stage: str, fields: dict):
    """
    Generates next step button sets based on the current quote stage.
    Backend controls all button logic — GPT no longer decides.
    
    Stages:
    - Quote Calculated → Show PDF/email/edit/call buttons
    - Gathering Personal Info → Ask for name/email/phone (no buttons)
    - Personal Info Received → Show download, booking, call buttons
    - Other → Prompt user to continue
    """
    
    # Clean stage input
    stage = str(quote_stage or "").strip()
    log_debug_event(None, "BACKEND", "generate_next_actions()", f"Generating actions for quote_stage = '{stage}'")

    # Check if customer_name is already filled
    customer_name_filled = bool(fields.get("customer_name", "").strip())

    if stage == "Quote Calculated":
        actions = [
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
        log_debug_event(None, "BACKEND", "Next Actions Generated", "Stage: Quote Calculated → 4 quote-ready buttons")
        return actions

    elif stage == "Gathering Personal Info":
        # Skip asking for customer name if it's already filled
        if customer_name_filled:
            actions = [
                {
                    "action": "collect_info",
                    "response": (
                        "No worries — just need a couple more quick details so I can send your quote.\n\n"
                        "**Please provide your email address and best contact number.**"
                    ),
                    "options": []
                }
            ]
            log_debug_event(None, "BACKEND", "Next Actions Generated", "Stage: Gathering Personal Info → Asking for email/phone (name already filled)")
        else:
            actions = [
                {
                    "action": "collect_info",
                    "response": (
                        "No worries — just need a couple quick details so I can send your quote.\n\n"
                        "**What’s your full name, email address, and best contact number?**"
                    ),
                    "options": []
                }
            ]
            log_debug_event(None, "BACKEND", "Next Actions Generated", "Stage: Gathering Personal Info → Asking for name/email/phone")
        
        return actions

    elif stage == "Personal Info Received":
        actions = [
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
        log_debug_event(None, "BACKEND", "Next Actions Generated", "Stage: Personal Info Received → Booking options shown")
        return actions

    else:
        fallback = [
            {
                "action": "awaiting_quote",
                "response": "I’m still gathering details for your quote — let’s finish those first!",
                "options": []
            }
        ]
        log_debug_event(None, "BACKEND", "Next Actions Fallback", f"Unrecognized stage: '{stage}' → Using fallback response")
        return fallback


# === GPT Extraction (Production-Grade) ===

async def extract_properties_from_gpt4(message: str, log: str, record_id: str = None, quote_id: str = None, skip_log_lookup: bool = False):
    logger.info(f"🟡 extract_properties_from_gpt4() called — record_id: {record_id}, message: {message}")
    if record_id:
        log_debug_event(record_id, "BACKEND", "Function Start", f"extract_properties_from_gpt4(message={message[:100]})")

    if message.strip() == "__init__":
        log_debug_event(record_id, "GPT", "Init Skipped", "Suppressing GPT call on __init__")
        return [{"property": "source", "value": "Brendan"}], "Just a moment while I get us started..."

    weak_inputs = {
        "hi", "hello", "hey", "you there", "you there?", "you hear me", "you hear me?", "what’s up",
        "ok", "okay", "what’s next", "next", "oi", "yo", "?", "test"
    }
    if message.lower().strip() in weak_inputs:
        reply = "Could you let me know how many bedrooms and bathrooms we’re quoting for, and whether the property is furnished?"
        log_debug_event(record_id, "GPT", "Weak Message Skipped", message)
        flushed = flush_debug_log(record_id)
        if flushed:
            update_quote_record(record_id, {"debug_log": flushed, "source": "Brendan"})
        log_debug_event(record_id, "GPT", "Final Reply", reply)
        return [{"property": "source", "value": "Brendan"}], reply

    existing_fields = {}
    if record_id and not skip_log_lookup:
        try:
            session_data = get_quote_by_session(record_id)
            if isinstance(session_data, dict):
                existing_fields = session_data.get("fields", {})
                log_debug_event(record_id, "GPT", "Existing Fields Fetched", str(existing_fields))
        except Exception as e:
            log_debug_event(record_id, "GPT", "Record Fetch Failed", str(e))

    # === Check if name was just asked ===
    already_asked_name = "what name should i put on the quote" in log.lower()[-300:]
    name_already_filled = existing_fields.get("customer_name", "").strip() != ""
    if name_already_filled and already_asked_name:
        log_debug_event(record_id, "GPT", "Suppressed Repeat Name Prompt", "Already asked & name is filled")
        return [{"property": "source", "value": "Brendan"}], "Thanks Brad! Let’s keep going."

    prepared_log = re.sub(r"[^\x20-\x7E\n]", "", log[-10000:])
    messages = [{
        "role": "system",
        "content": (
            "You are Brendan, the quoting assistant for Orca Cleaning.\n"
            "The customer has already seen this greeting from the frontend:\n\n"
            "“G’day! I’m Brendan from Orca Cleaning — your quoting officer for vacate cleans in Perth and Mandurah. "
            "This quote is fully anonymous and no booking is required — I’m just here to help. View our Privacy Policy.”\n\n"
            "Do NOT repeat this greeting or say 'Hi', 'Hello', or 'G’day'.\n"
            "Always respond with a JSON object containing only:\n"
            "{ \"properties\": [...], \"response\": \"...\" }"
        )
    }]

    for line in prepared_log.split("\n"):
        if line.startswith("USER:") and line.strip() != "USER: __init__":
            messages.append({"role": "user", "content": line[5:].strip()})
        elif line.startswith("BRENDAN:"):
            messages.append({"role": "assistant", "content": line[8:].strip()})
        elif line.startswith("SYSTEM:"):
            messages.append({"role": "system", "content": line[7:].strip()})

    messages.append({"role": "user", "content": message.strip()})
    log_debug_event(record_id, "GPT", "Messages Prepared", f"{len(messages)} messages ready")

    def call_gpt_and_parse(attempt=1):
        try:
            res = client.chat.completions.create(
                model="gpt-4-turbo",
                messages=messages,
                max_tokens=3000,
                temperature=0.4
            )
            raw = res.choices[0].message.content.strip()
            log_debug_event(record_id, "GPT", f"Raw Response {attempt}", raw[:300])
            log_debug_event(record_id, "GPT", "Full GPT Response", raw[:3000])
            start, end = raw.find("{"), raw.rfind("}")
            parsed = json.loads(raw[start:end + 1])
            return parsed
        except Exception as e:
            log_debug_event(record_id, "GPT", f"Parse Failed Attempt {attempt}", str(e))
            return None

    parsed = call_gpt_and_parse(1)
    if not isinstance(parsed, dict):
        messages.insert(1, {
            "role": "system",
            "content": "You MUST respond with valid JSON containing only 'properties' and 'response'. Do not reply in plain text."
        })
        parsed = call_gpt_and_parse(2)

    if not isinstance(parsed, dict) or "properties" not in parsed or "response" not in parsed:
        log_debug_event(record_id, "GPT", "Schema Validation Failed", str(parsed))
        fallback = "Could you let me know how many bedrooms and bathrooms we’re quoting for, and whether the property is furnished?"
        log_debug_event(record_id, "GPT", "Final Reply", fallback)
        flushed = flush_debug_log(record_id)
        if flushed:
            update_quote_record(record_id, {"debug_log": flushed, "source": "Brendan"})
        return [{"property": "source", "value": "Brendan"}], fallback

    raw_props = parsed.get("properties", [])
    reply = parsed.get("response", "").strip()

    if isinstance(raw_props, list) and all(isinstance(p, str) for p in raw_props):
        log_debug_event(record_id, "GPT", "Malformed Prop Format", f"Discarded list of strings: {raw_props}")
        fallback = "Could you let me know how many bedrooms and bathrooms we’re quoting for, and whether the property is furnished?"
        log_debug_event(record_id, "GPT", "Final Reply", fallback)
        flushed = flush_debug_log(record_id)
        if flushed:
            update_quote_record(record_id, {"debug_log": flushed, "source": "Brendan"})
        return [{"property": "source", "value": "Brendan"}], fallback

    if isinstance(raw_props, dict):
        raw_props = [{"property": k, "value": v} for k, v in raw_props.items()]
        log_debug_event(record_id, "GPT", "Converted Dict Props", f"Fixed to list with {len(raw_props)} items")
    elif not isinstance(raw_props, list):
        log_debug_event(record_id, "GPT", "Malformed Props", f"Type: {type(raw_props)}")
        raw_props = []

    log_debug_event(record_id, "GPT", "Parsed GPT Response", f"Reply: {reply[:100]} | Props: {len(raw_props)}")

    safe_props = []
    for p in raw_props:
        if not isinstance(p, dict) or "property" not in p or "value" not in p:
            log_debug_event(record_id, "GPT", "Skipped Invalid Prop", str(p))
            continue
        field, value = p["property"], p["value"]
        if field == "name" or field == "first_name":
            field = "customer_name"
            if value:
                # Store customer name in Airtable immediately
                update_quote_record(record_id, {"customer_name": value})
                log_debug_event(record_id, "GPT", "Customer Name Captured", f"Stored customer name: {value}")
        elif field == "bedrooms":
            field = "bedrooms_v2"
        elif field == "bathrooms":
            field = "bathrooms_v2"
        elif field == "furnished":
            field = "furnished_status"
        if field in VALID_AIRTABLE_FIELDS:
            safe_props.append({"property": field, "value": value})
        else:
            log_debug_event(record_id, "GPT", "Unknown Field Skipped", f"{field} = {value}")

    safe_props = [p for p in safe_props if p["property"] != "source"]
    safe_props.append({"property": "source", "value": "Brendan"})
    log_debug_event(record_id, "GPT", "Final Props Injected", str(safe_props))
    log_debug_event(record_id, "GPT", "Final Reply", reply)
    log_debug_event(record_id, "GPT", "Function Return Payload", str(safe_props))

    flushed = flush_debug_log(record_id)
    if flushed:
        update_quote_record(record_id, {"debug_log": flushed})

    if not safe_props or all(p["property"] == "source" for p in safe_props):
        if len(message.split()) == 1 and message.isalpha():
            guessed_name = message.strip().title()
            log_debug_event(record_id, "GPT", "Name Fallback Injected", f"customer_name = {guessed_name}")
            log_debug_event(record_id, "GPT", "Final Reply", f"Thanks {guessed_name}! Let’s keep going.")
            if flushed:
                update_quote_record(record_id, {"debug_log": flushed})
            return [
                {"property": "customer_name", "value": guessed_name},
                {"property": "source", "value": "Brendan"}
            ], f"Thanks {guessed_name}! Let’s keep going."

    return safe_props, reply


# === GPT Error Email Alert ===

def send_gpt_error_email(error_msg: str):
    """
    Sends a critical error email if GPT extraction fails.
    If logging or email fails, logs to Render console as fallback.
    """
    from app.main import client  # ✅ Fix 1: use shared client definition if ever needed

    try:
        sender_email = "info@orcacleaning.com.au"
        recipient_email = "admin@orcacleaning.com.au"
        smtp_server = "smtp.office365.com"
        smtp_port = 587
        smtp_pass = settings.SMTP_PASS

        if not smtp_pass:
            logger.error("❌ Missing SMTP_PASS — cannot send GPT error email.")
            try:
                log_debug_event(None, "BACKEND", "Email Send Failed", "Missing SMTP_PASS environment variable")
            except Exception as e:
                logger.error(f"❌ Failed to log missing SMTP_PASS: {e}")
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
                    server.sendmail(sender_email, [recipient_email], msg.as_string())

                logger.info("✅ GPT error email sent successfully.")
                try:
                    log_debug_event(None, "BACKEND", "GPT Error Email Sent", f"Sent to {recipient_email} (attempt {attempt + 1})")
                except Exception as log_success:
                    logger.warning(f"⚠️ Logging success failed: {log_success}")
                break

            except smtplib.SMTPException as smtp_error:
                logger.warning(f"⚠️ SMTP error (attempt {attempt + 1}/2): {smtp_error}")
                if attempt == 1:
                    logger.error("❌ Failed to send GPT error email after 2 attempts.")
                    try:
                        log_debug_event(None, "BACKEND", "GPT Error Email Failed", f"SMTP error: {smtp_error}")
                    except Exception as log_fail:
                        logger.error(f"❌ Failed to log SMTP error: {log_fail}")
                else:
                    sleep(5)

            except Exception as e:
                logger.error(f"❌ Unexpected error sending GPT error email: {e}")
                try:
                    log_debug_event(None, "BACKEND", "Unexpected Email Error", str(e))
                except Exception as log_e:
                    logger.error(f"❌ Failed to log unexpected email error: {log_e}")
                return

        # === Flush debug log from record_id inside error body ===
        try:
            match = re.search(
                r"(?i)record[_\s]?id\s*[:=]?\s*['\"]?([a-zA-Z0-9]{5,})['\"]?",
                error_msg,
                re.MULTILINE
            )
            if match:
                record_id = match.group(1).strip()
                flushed = flush_debug_log(record_id)
                if flushed:
                    update_quote_record(record_id, {"debug_log": flushed})
        except Exception as e:
            logger.warning(f"⚠️ Failed to flush debug log after error: {e}")
            try:
                log_debug_event(None, "BACKEND", "Debug Log Flush Error", str(e))
            except:
                logger.error(f"❌ Could not log flush failure: {e}")

    except Exception as e:
        logger.error(f"💥 FATAL: send_gpt_error_email() failed to execute: {e}")

# === Append Message Log ===

def append_message_log(record_id: str, message: str, sender: str):
    """
    Appends a new message to the 'message_log' field in Airtable.
    Includes timestamp, sender label, and preserves ordering.
    Truncates if log exceeds MAX_LOG_LENGTH. Flushes debug_log after save.
    """
    if not record_id:
        logger.error("❌ Cannot append message_log — missing record ID")
        log_debug_event(None, "BACKEND", "Log Failed", "Missing record ID for message append")
        return

    message = str(message or "").strip()
    if not message:
        logger.info("⏩ Empty message — skipping append")
        log_debug_event(record_id, "BACKEND", "Message Skipped", "Empty message not logged")
        return

    # Normalize sender and set timestamp
    sender_clean = str(sender or "user").strip().upper()
    timestamp = datetime.utcnow().isoformat()

    # Format message line with timestamp and sender
    new_entry = f"[{timestamp}] {sender_clean}: {message}"

    # Fetch current message_log from Airtable
    try:
        url = f"https://api.airtable.com/v0/{settings.AIRTABLE_BASE_ID}/{TABLE_NAME}/{record_id}"
        headers = {"Authorization": f"Bearer {settings.AIRTABLE_API_KEY}"}
        res = requests.get(url, headers=headers)
        res.raise_for_status()
        airtable_data = res.json()
        old_log = str(airtable_data.get("fields", {}).get("message_log", "")).strip()
        log_debug_event(record_id, "BACKEND", "Loaded Old Log", f"Length: {len(old_log)}")
    except Exception as e:
        logger.warning(f"⚠️ Could not fetch current message_log: {e}")
        log_debug_event(record_id, "BACKEND", "Message Log Fetch Failed", str(e))
        return

    # Combine old log with new entry and check for truncation
    combined_log = f"{old_log}\n{new_entry}" if old_log else new_entry
    was_truncated = False
    if len(combined_log) > MAX_LOG_LENGTH:
        combined_log = combined_log[-MAX_LOG_LENGTH:]
        was_truncated = True
        log_debug_event(record_id, "BACKEND", "Log Truncated", f"Combined log exceeded {MAX_LOG_LENGTH} chars — truncated")

    # Save new message_log to Airtable
    try:
        update_quote_record(record_id, {"message_log": combined_log})
        logger.info(f"✅ message_log updated for {record_id} (len={len(combined_log)})")
        log_debug_event(record_id, "BACKEND", "Message Log Saved", f"New length: {len(combined_log)} | Truncated: {was_truncated}")
    except Exception as e:
        logger.error(f"❌ Failed to update message_log: {e}")
        log_debug_event(record_id, "BACKEND", "Message Log Update Failed", str(e))
        return

    # Metadata logging
    try:
        detail = f"{sender_clean} message logged ({len(message)} chars)"
        if was_truncated:
            detail += " | ⚠️ Log truncated"
        log_debug_event(record_id, "BACKEND", "Message Appended", detail)
    except Exception as e:
        logger.warning(f"⚠️ Debug log event failed: {e}")
        log_debug_event(record_id, "BACKEND", "Debug Log Failure", str(e))

    # Flush debug log after all saves
    try:
        flushed = flush_debug_log(record_id)
        if flushed:
            update_quote_record(record_id, {"debug_log": flushed})
            log_debug_event(record_id, "BACKEND", "Debug Log Flushed", f"{len(flushed)} chars flushed to Airtable")
        else:
            log_debug_event(record_id, "BACKEND", "Debug Log Flush Skipped", "No pending debug log to flush")
    except Exception as e:
        logger.warning(f"⚠️ Failed to flush debug log: {e}")
        log_debug_event(record_id, "BACKEND", "Debug Log Flush Error", str(e))


# === Handle Privacy Consent === 

async def handle_privacy_consent(message: str, message_lower: str, record_id: str, session_id: str):
    """
    Handles privacy consent step before collecting personal info.
    Confirms the customer is happy to provide contact details.
    """
    approved = {"yes", "yep", "sure", "go ahead", "ok", "okay", "alright", "please do", "y", "yup", "yeh"}

    if any(word in message_lower for word in approved):
        update_quote_record(record_id, {"privacy_acknowledged": True})
        append_message_log(record_id, "✅ Privacy consent acknowledged", "system")

        response = (
            "Thanks for confirming! Just pop in your full name, email, and best contact number, "
            "and I’ll send that quote straight through as a downloadable PDF."
        )
        log_debug_event(record_id, "BACKEND", "Privacy Acknowledged", "Customer approved data collection")
        return JSONResponse(content={
            "properties": [{"property": "privacy_acknowledged", "value": True}],
            "response": response,
            "next_actions": [],
            "session_id": session_id
        })

    # If they haven't confirmed yet — show privacy notice
    privacy_msg = (
        "Just so you know — we don’t ask for anything private like bank info. "
        "Only your name, email and phone so we can send the quote over.\n\n"
        "Your privacy is 100% respected.\n"
        "You can read our full Privacy Policy here: [https://orcacleaning.com.au/privacy-policy/](https://orcacleaning.com.au/privacy-policy/)\n\n"
        "**Would you like to continue and provide your details now?**"
    )
    log_debug_event(record_id, "BACKEND", "Privacy Prompt", "Awaiting consent before collecting contact details")

    return JSONResponse(content={
        "properties": [],
        "response": privacy_msg,
        "next_actions": [],
        "session_id": session_id
    })

# === Handle Chat Init === 

async def handle_chat_init(session_id: str):
    try:
        log_debug_event(None, "BACKEND", "Init Triggered", f"New chat started — Session ID: {session_id}")

        # === Check for existing quote ===
        log_debug_event(None, "BACKEND", "Session Lookup", f"Looking up session: {session_id}")
        existing = get_quote_by_session(session_id)

        quote_id, record_id, stage, fields = None, None, None, {}

        if isinstance(existing, dict):
            quote_id = existing.get("quote_id")
            record_id = existing.get("record_id")
            stage = existing.get("quote_stage", "Gathering Info")
            fields = existing.get("fields", {})
            timestamp = fields.get("timestamp")

            log_debug_event(record_id, "BACKEND", "Existing Quote Found", f"Quote ID: {quote_id}, Stage: {stage}, Timestamp: {timestamp}")

            if not timestamp or stage in ["Quote Calculated", "Personal Info Received", "Booking Confirmed"]:
                log_debug_event(record_id, "BACKEND", "Forcing New Quote", f"Stale or locked — Timestamp: {timestamp}, Stage: {stage}")
                existing = None  # Trigger new quote creation

        # === Create new quote if needed ===
        if not existing:
            log_debug_event(None, "BACKEND", "Creating Quote", f"No valid existing quote — creating new for session {session_id}")
            quote_id, record_id, stage, fields = create_new_quote(session_id, force_new=True)
            session_id = fields.get("session_id", session_id)
            log_debug_event(record_id, "BACKEND", "New Quote Created", f"Session ID: {session_id}, Quote ID: {quote_id}, Record ID: {record_id}")

        # === Check if customer_name exists before asking for it ===
        customer_name = fields.get("customer_name", "").strip()
        if customer_name:
            # If customer name is already filled, skip asking for it and proceed to the next step
            log_debug_event(record_id, "BACKEND", "Customer Name Found", f"Customer name already set: {customer_name}")
            reply = "Thanks for that! Let’s keep going with the next steps."
            append_message_log(record_id, reply, "brendan")
            log_debug_event(record_id, "BACKEND", "Reply Sent", f"Reply: {reply}")
        else:
            # Ask for customer name if not already filled
            reply = "What name should I put on the quote?"
            append_message_log(record_id, reply, "brendan")
            log_debug_event(record_id, "BACKEND", "Request Name", f"Requesting name from user.")

        # === SYSTEM log entry ===
        append_message_log(record_id, "SYSTEM_TRIGGER: Brendan started a new quote", "system")
        log_debug_event(record_id, "BACKEND", "System Message Logged", "Brendan start trigger recorded")

        # === Inject source field directly ===
        update_quote_record(record_id, {"source": "Brendan"})

        # === Flush initial debug log ===
        flushed = flush_debug_log(record_id)
        if flushed:
            log_debug_event(record_id, "BACKEND", "Flushing Initial Debug Log", f"{len(flushed)} chars")
            update_quote_record(record_id, {"debug_log": flushed})
            log_debug_event(record_id, "BACKEND", "Initial Debug Log Saved", "Flushed to Airtable")

        log_debug_event(record_id, "BACKEND", "Init Complete", f"Final response sent. Length: {len(reply)}")

        return JSONResponse(content={
            "properties": [{"property": "source", "value": "Brendan"}],
            "response": reply,
            "next_actions": [],
            "session_id": session_id
        })

    except Exception as e:
        log_debug_event(None, "BACKEND", "Fatal Init Error", str(e))
        raise HTTPException(status_code=500, detail="Failed to initialize Brendan.")


# === Brendan API Router ===

router = APIRouter()

@router.post("/filter-response")
async def filter_response_entry(request: Request):
    try:
        body = await request.json()
        message = str(body.get("message", "")).strip()
        session_id = str(body.get("session_id", "")).strip()

        if not session_id:
            log_debug_event(None, "BACKEND", "Session Error", "No session_id provided in request")
            raise HTTPException(status_code=400, detail="Session ID is required.")

        log_debug_event(None, "BACKEND", "Incoming Message", f"Session: {session_id}, Message: {message}")

        if message.lower() == "__init__":
            try:
                log_debug_event(None, "BACKEND", "Init Triggered", f"New chat started — Session ID: {session_id}")
                await handle_chat_init(session_id)

                quote_data = get_quote_by_session(session_id)
                record_id = quote_data["record_id"]
                fields = quote_data.get("fields", {})

                REQUIRED_ORDER = [
                    "customer_name", "suburb", "bedrooms_v2", "bathrooms_v2", "furnished_status"
                ]
                for field in REQUIRED_ORDER:
                    if not fields.get(field):
                        prompt = {
                            "customer_name": "What name should I put on the quote?",
                            "suburb": "What suburb is the property in?",
                            "bedrooms_v2": "How many bedrooms are there?",
                            "bathrooms_v2": "And how many bathrooms?",
                            "furnished_status": "Is the property furnished or unfurnished?"
                        }[field]

                        append_message_log(record_id, prompt, "brendan")
                        return JSONResponse(content={
                            "properties": [],
                            "response": prompt,
                            "next_actions": generate_next_actions("Gathering Info"),
                            "session_id": session_id
                        })

                return JSONResponse(content={
                    "properties": [],
                    "response": "Thanks! Let’s move ahead then.",
                    "next_actions": generate_next_actions("Gathering Info"),
                    "session_id": session_id
                })

            except Exception as e:
                log_debug_event(None, "BACKEND", "Init Error", traceback.format_exc())
                raise HTTPException(status_code=500, detail="Init failed.")

        quote_data = get_quote_by_session(session_id)
        if not isinstance(quote_data, dict) or "record_id" not in quote_data:
            log_debug_event(None, "BACKEND", "Session Lookup Failed", f"No valid quote found for session: {session_id}")
            raise HTTPException(status_code=404, detail="Quote not found.")

        quote_id = quote_data.get("quote_id", "N/A")
        record_id = quote_data.get("record_id", "")
        quote_stage = quote_data.get("quote_stage", "Gathering Info")
        fields = quote_data.get("fields", {})
        log_debug_event(record_id, "BACKEND", "Session Retrieved", f"Quote ID: {quote_id}, Stage: {quote_stage}, Fields: {list(fields.keys())}")

        if quote_stage == "Chat Banned":
            log_debug_event(record_id, "BACKEND", "Blocked Chat", "Chat is banned — denying interaction")
            return JSONResponse(content={
                "properties": [],
                "response": "This chat is closed. Call 1300 918 388 if you still need a quote.",
                "next_actions": [],
                "session_id": session_id
            })

        if quote_stage == "Gathering Personal Info" and not fields.get("privacy_acknowledged"):
            log_debug_event(record_id, "BACKEND", "Awaiting Privacy Consent", f"privacy_acknowledged: {fields.get('privacy_acknowledged')}")
            return await handle_privacy_consent(message, message.lower(), record_id, session_id)

        if quote_stage == "Gathering Personal Info" and fields.get("privacy_acknowledged"):
            name = fields.get("customer_name", "").strip()
            email = fields.get("customer_email", "").strip()
            phone = fields.get("customer_phone", "").strip()
            log_debug_event(record_id, "BACKEND", "PDF Flow Check", f"name={name}, email={email}, phone={phone}")

            if name and email and phone:
                try:
                    log_debug_event(record_id, "BACKEND", "Generating PDF", f"Preparing for: {name} ({email})")
                    pdf_path = generate_quote_pdf(fields)
                    send_quote_email(email, name, pdf_path, quote_id)
                    update_quote_record(record_id, {"quote_stage": "Personal Info Received"})
                    append_message_log(record_id, f"PDF quote sent to {email}", "brendan")
                    log_debug_event(record_id, "BACKEND", "PDF Sent", f"PDF sent to {email}, stage updated")

                    return JSONResponse(content={
                        "properties": [],
                        "response": f"Thanks {name}! I’ve just sent your quote to {email}. Let me know if you need help with anything else — or feel free to book directly anytime: https://orcacleaning.com.au/schedule?quote_id={quote_id}",
                        "next_actions": generate_next_actions("Personal Info Received"),
                        "session_id": session_id
                    })
                except Exception as e:
                    log_debug_event(record_id, "BACKEND", "PDF/Email Error", traceback.format_exc())
                    raise HTTPException(status_code=500, detail="Failed to send quote email.")

        if quote_stage in ["Quote Calculated", "Personal Info Received", "Booking Confirmed"]:
            append_message_log(record_id, message, "user")
            if any(k in message.lower() for k in PDF_KEYWORDS):
                reply = "Sure — I’ll just grab your name, email and phone so I can send your quote across now."
                update_quote_record(record_id, {"quote_stage": "Gathering Personal Info"})
                log_debug_event(record_id, "BACKEND", "PDF Keyword Triggered", "Switched to Gathering Personal Info")
            else:
                reply = "This quote is already prepared. Would you like me to email it, or are you ready to book?"
                log_debug_event(record_id, "BACKEND", "Locked Stage Reply", f"No action keywords found, reply: {reply}")

            append_message_log(record_id, reply, "brendan")
            return JSONResponse(content={
                "properties": [],
                "response": reply,
                "next_actions": generate_next_actions(quote_stage),
                "session_id": session_id
            })

        REQUIRED_ORDER = [
            "customer_name", "suburb", "bedrooms_v2", "bathrooms_v2", "furnished_status",
            "carpet_cleaning", "carpet_mainroom_count", "carpet_stairs_count", "carpet_other_count"
        ]
        skip_carpet_counts = fields.get("carpet_cleaning") == "No"
        for field in REQUIRED_ORDER:
            if field.startswith("carpet_") and skip_carpet_counts:
                continue
            if not fields.get(field):
                prompt = {
                    "customer_name": "What name should I put on the quote?",
                    "suburb": "What suburb is the property in?",
                    "bedrooms_v2": "How many bedrooms are there?",
                    "bathrooms_v2": "And how many bathrooms?",
                    "furnished_status": "Is the property furnished or unfurnished?",
                    "carpet_cleaning": "Would you like to include carpet steam cleaning in the vacate clean?",
                    "carpet_mainroom_count": "How many carpeted bedrooms or main rooms?",
                    "carpet_stairs_count": "How many sets of carpeted stairs?",
                    "carpet_other_count": "Any other carpeted rooms? (e.g. hallways, lounge)"
                }[field]

                append_message_log(record_id, message, "user")
                log_debug_event(record_id, "BACKEND", "Asking Missing Field", f"Missing: {field} → {prompt}")

                return JSONResponse(content={
                    "properties": [],
                    "response": prompt,
                    "next_actions": [],
                    "session_id": session_id
                })

        append_message_log(record_id, message, "user")
        message_log = fields.get("message_log", "")[-LOG_TRUNCATE_LENGTH:]
        log_debug_event(record_id, "BACKEND", "Calling GPT", f"Input: {message[:100]}")

        properties, reply = await extract_properties_from_gpt4(message, message_log, record_id, quote_id)

        if not reply:
            log_debug_event(record_id, "BACKEND", "GPT Returned Empty Reply", "GPT response missing")

        parsed = {p["property"]: p["value"] for p in properties if "property" in p and "value" in p}
        log_debug_event(record_id, "BACKEND", "Parsed Properties", str(parsed))

        for required in ["source", "bedrooms_v2", "bathrooms_v2"]:
            if required not in parsed and required in fields:
                parsed[required] = fields[required]
                log_debug_event(record_id, "BACKEND", "Preserved Field", f"{required} = {fields[required]}")

        updated_fields = fields.copy()
        updated_fields.update(parsed)

        if should_calculate_quote(updated_fields) and quote_stage != "Quote Calculated":
            try:
                log_debug_event(record_id, "BACKEND", "Triggering Quote Calculation", "All required fields present")
                result = calculate_quote(QuoteRequest(**updated_fields))
                quote_result = result.model_dump()
                parsed.update(quote_result)
                parsed["quote_stage"] = "Quote Calculated"
                reply = get_inline_quote_summary({**quote_result, "record_id": record_id})
                log_debug_event(record_id, "BACKEND", "Quote Generated", f"Total: ${parsed.get('total_price')} | Time: {parsed.get('estimated_time_mins')} mins")
            except Exception as e:
                log_debug_event(record_id, "BACKEND", "Quote Calc Error", traceback.format_exc())
                reply = "I ran into an issue calculating your quote — want me to try again?"

        log_debug_event(record_id, "BACKEND", "Saving Fields", f"{list(parsed.keys())}")
        update_quote_record(record_id, parsed)
        append_message_log(record_id, reply, "brendan")
        log_debug_event(record_id, "BACKEND", "Returning Final Response", reply[:120])

        return JSONResponse(content={
            "properties": properties,
            "response": reply,
            "next_actions": generate_next_actions(parsed.get("quote_stage", quote_stage)),
            "session_id": session_id
        })

    except Exception as e:
        log_debug_event(None, "BACKEND", "Fatal Error", traceback.format_exc())
        raise HTTPException(status_code=500, detail="Internal server error.")
