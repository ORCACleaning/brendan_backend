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
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

# === Brendan Config and Constants ===
from app.config import logger, settings
from app.config import LOG_TRUNCATE_LENGTH, MAX_LOG_LENGTH, PDF_SYSTEM_MESSAGE, TABLE_NAME

# === Models ===
from app.models.quote_models import QuoteRequest

# === Services ===
from app.services.email_sender import send_quote_email
from app.services.pdf_generator import generate_quote_pdf
from app.services.quote_logic import calculate_quote
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

1. Your #1 priority is to extract ALL fields from the customer's message — NEVER skip a field if the customer has already provided info.
2. DO NOT summarise, guess, or assume — extract exactly what the customer says.
3. Field extraction is always more important than your reply.
4. NEVER re-show the quote summary after calculation unless the customer changes details.
5. ALWAYS return valid JSON — no exceptions.

---

## CONTEXT AWARENESS:

You will always receive the full conversation log.

If you see this in the log:
> "BRENDAN: Looks like a big job! Here's your quote:"

That means the quote is already calculated — DO NOT recalculate unless customer changes details.

If the customer says anything like:
- "pdf please"
- "send quote"
- "email it to me"
- "get pdf"
- "email quote"

DO NOT regenerate the quote summary.

Instead reply:
> "Sure thing — I’ll just grab your name, email and phone number so I can send that through."

---

## YOUR ROLE:

You are Brendan — the quoting officer for Orca Cleaning, based in Western Australia.

You ONLY do vacate cleaning here.

If the customer asks for any other service (like office cleaning, carpet-only, pressure washing etc), reply:
> "We specialise in vacate cleaning here — but check out orcacleaning.com.au or call our office on 1300 918 388 for other services."

You provide cleaning certificates for tenants.

Glass roller doors = 3 windows each — mention this if relevant.

---

## DISCOUNTS (Valid Until May 31, 2025):

- 10% Off all vacate cleans.
- Extra 5% Off if booked by a Property Manager.

---

## PRIVACY RULE (Before Asking for Contact Details):

Always say:
> "Just so you know — we don’t ask for anything private like bank info. Only your name, email and phone so we can send the quote over. Your privacy is 100% respected."

If customer asks about privacy:
> "No worries — we don’t collect personal info at this stage. You can read our Privacy Policy here: https://orcacleaning.com.au/privacy-policy"

---

## CHAT START RULE ("__init__" Trigger):

Skip greetings (the website frontend already said hello).

Start by asking for suburb, bedrooms_v2, bathrooms_v2, furnished.

Always ask 2–4 missing fields per message — friendly but straight to the point.

---

## REQUIRED FIELDS — Must Collect These 27:

1. suburb  
2. bedrooms_v2  
3. bathrooms_v2  
4. furnished — Must be "Furnished" or "Unfurnished"  
5. oven_cleaning  
6. window_cleaning — If true, ask for window_count  
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
24. is_property_manager — If true, ask for real_estate_name and number_of_sessions  
25. special_requests  
26. special_request_minutes_min  
27. special_request_minutes_max  

---

## RULES FOR FURNISHED:

Accept ONLY "Furnished" or "Unfurnished".

If the customer says "semi-furnished", ask:
> "Are there any beds, couches, wardrobes, or full cabinets still in the home?"

If only appliances (like fridge/oven) are left, treat as "Unfurnished".

NEVER skip blind cleaning — even if unfurnished.

---

## RULES FOR CARPET CLEANING:

NEVER ask yes/no for carpet cleaning.

Instead ask:
> "Roughly how many bedrooms, living areas, studies or stairs have carpet?"

Extract carpet_* fields individually.

If any carpet_* field is greater than 0, also extract:
```json
{ "property": "carpet_cleaning", "value": true }

RULES FOR SPECIAL REQUESTS:

Ask:

"Do you have any special requests like inside microwave, extra windows, balcony door tracks, or anything else?"
If the customer provides any special request:

Always extract special_requests
Also extract:
{ "property": "special_request_minutes_min", "value": 30 }
{ "property": "special_request_minutes_max", "value": 60 }
Unless the customer gives their own time estimate.

REMINDER:

Be friendly, casual, and Aussie-style.

Prioritise field extraction always.

Reply in a professional, customer-friendly tone.

ALWAYS return valid JSON exactly like this: { "properties": [ { "property": "field_name", "value": "field_value" } ], "response": "Aussie-style reply here" } """

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
    Returns: (quote_id, record_id, quote_stage, fields) or None.
    """
    safe_table_name = quote(TABLE_NAME)
    url = f"https://api.airtable.com/v0/{settings.AIRTABLE_BASE_ID}/{safe_table_name}"
    headers = {
        "Authorization": f"Bearer {settings.AIRTABLE_API_KEY}"
    }
    params = {
        "filterByFormula": f"{{session_id}}='{session_id}'",
        "sort[0][field]": "timestamp",
        "sort[0][direction]": "desc",
        "pageSize": 1
    }

    logger.info(f"🔍 Searching for quote by session_id: {session_id}")
    log_debug_event(None, "BACKEND", "Session Lookup Attempt", f"Initiating lookup for session_id: {session_id}")

    for attempt in range(3):
        try:
            log_debug_event(None, "BACKEND", "Airtable Request Sent", f"Attempt {attempt + 1}: Sending GET to Airtable with session_id filter")
            res = requests.get(url, headers=headers, params=params)
            res.raise_for_status()
            data = res.json()
            log_debug_event(None, "BACKEND", "Airtable Response Received", f"Attempt {attempt + 1}: Successfully received response from Airtable")
            break
        except Exception as e:
            logger.warning(f"⚠️ Airtable fetch failed (attempt {attempt + 1}/3): {e}")
            log_debug_event(None, "BACKEND", "Session Lookup Failed", f"Airtable attempt {attempt + 1} failed: {str(e)}")
            if attempt == 2:
                logger.error(f"❌ Final failure fetching quote for session_id {session_id} after 3 attempts.")
                log_debug_event(None, "BACKEND", "Session Lookup Final Failure", f"Failed after 3 attempts: {str(e)}")
                return None
            sleep(1)

    records = data.get("records", [])
    if not records:
        logger.info(f"⏳ No existing quote found for session_id: {session_id}")
        log_debug_event(None, "BACKEND", "No Quote Found", f"No record found in Airtable for session_id: {session_id}")
        return None

    record = records[0]
    fields = record.get("fields", {})
    quote_id = fields.get("quote_id", "N/A")
    record_id = record.get("id", "")
    quote_stage = fields.get("quote_stage", "Gathering Info")
    session_id_return = fields.get("session_id", session_id)

    logger.info(f"✅ Found quote | session_id: {session_id_return} | quote_id: {quote_id} | stage: {quote_stage}")
    log_debug_event(record_id, "BACKEND", "Session Lookup Success", f"Retrieved quote_id: {quote_id}, stage: {quote_stage}, session_id: {session_id_return}")

    return quote_id, record_id, quote_stage, fields


# === Update Quote Record ===

def update_quote_record(record_id: str, fields: dict):
    """
    Updates a record in Airtable with normalized fields.
    Always includes message_log and debug_log even if unchanged.
    Handles type conversion, validation, and fallback logic.
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

    MAX_REASONABLE_INT = 100
    normalized_fields = {}

    # === Normalize 'furnished' ===
    if "furnished" in fields:
        val = str(fields["furnished"]).strip().lower()
        if "unfurnished" in val:
            fields["furnished"] = "Unfurnished"
        elif "furnished" in val:
            fields["furnished"] = "Furnished"
        else:
            logger.warning(f"⚠️ Invalid furnished value: {fields['furnished']}")
            fields["furnished"] = ""

    # === Normalize all fields ===
    for raw_key, value in fields.items():
        key = FIELD_MAP.get(raw_key, raw_key)
        if key not in VALID_AIRTABLE_FIELDS:
            logger.warning(f"⚠️ Skipping unknown Airtable field: {key}")
            continue

        if key in BOOLEAN_FIELDS:
            value = (
                value if isinstance(value, bool)
                else str(value).strip().lower() in TRUE_VALUES
            )

        elif key in INTEGER_FIELDS:
            try:
                value = int(float(value))
                if value > MAX_REASONABLE_INT:
                    logger.warning(f"⚠️ Clamping large int value for {key}: {value}")
                    value = MAX_REASONABLE_INT
            except:
                logger.warning(f"⚠️ Failed to convert {key} to int — defaulting to 0")
                value = 0

        elif key in {
            "gst_applied", "total_price", "base_hourly_rate", "price_per_session",
            "estimated_time_mins", "discount_applied", "mandurah_surcharge",
            "after_hours_surcharge", "weekend_surcharge", "calculated_hours"
        }:
            try:
                value = float(value)
            except:
                logger.warning(f"⚠️ Failed to convert {key} to float — defaulting to 0.0")
                value = 0.0

        elif key == "special_requests":
            if not value or str(value).strip().lower() in {"no", "none", "false", "no special requests", "n/a"}:
                value = ""

        elif key == "extra_hours_requested":
            try:
                value = float(value) if value not in [None, ""] else 0.0
            except:
                value = 0.0

        else:
            value = "" if value is None else str(value).strip()

        normalized_fields[key] = value

    # === Force critical defaults ===
    normalized_fields["privacy_acknowledged"] = bool(fields.get("privacy_acknowledged", False))
    normalized_fields["carpet_cleaning"] = bool(fields.get("carpet_cleaning", False))
    normalized_fields["upholstery_cleaning"] = bool(fields.get("upholstery_cleaning", False))

    # === Always include logs ===
    for log_field in ["message_log", "debug_log"]:
        if log_field in fields:
            normalized_fields[log_field] = str(fields[log_field]) if fields[log_field] is not None else ""

    # === Flush debug log to payload ===
    debug_log = flush_debug_log(record_id)
    if debug_log:
        normalized_fields["debug_log"] = debug_log

    if not normalized_fields:
        logger.info(f"⏩ No valid fields to update for record {record_id}")
        log_debug_event(record_id, "BACKEND", "No Valid Fields", "Nothing passed validation for update.")
        return []

    # === Final validation check ===
    for key in list(normalized_fields.keys()):
        if key not in VALID_AIRTABLE_FIELDS:
            logger.error(f"❌ INVALID FIELD: {key} — Removing before update.")
            normalized_fields.pop(key, None)

    logger.info(f"\n📤 Updating Airtable Record: {record_id}")
    logger.info(f"🛠 Payload: {json.dumps(normalized_fields, indent=2)}")

    # === Try bulk update ===
    try:
        res = requests.patch(url, headers=headers, json={"fields": normalized_fields})
        if res.ok:
            logger.info("✅ Airtable bulk update successful.")
            log_debug_event(record_id, "BACKEND", "Record Updated (Bulk)", f"Fields updated: {list(normalized_fields.keys())}")
            return list(normalized_fields.keys())
        logger.error(f"❌ Airtable bulk update failed with status {res.status_code}")
        try:
            logger.error(f"🧾 Airtable error response: {res.json()}")
        except:
            logger.error("🧾 Airtable error response: (not JSON)")
    except Exception as e:
        logger.error(f"❌ Airtable bulk update exception: {e}")
        log_debug_event(record_id, "BACKEND", "Airtable Bulk Error", str(e))

    # === Fallback to one-by-one update ===
    successful = []
    for key, value in normalized_fields.items():
        try:
            res = requests.patch(url, headers=headers, json={"fields": {key: value}})
            if res.ok:
                logger.info(f"✅ Field '{key}' updated successfully.")
                successful.append(key)
            else:
                logger.error(f"❌ Field '{key}' failed to update.")
        except Exception as e:
            logger.error(f"❌ Exception on field '{key}': {e}")
            log_debug_event(record_id, "BACKEND", "Single Field Update Failed", f"{key}: {e}")

    if successful:
        log_debug_event(record_id, "BACKEND", "Record Updated (Fallback)", f"Fields updated: {successful}")
    else:
        log_debug_event(record_id, "BACKEND", "Update Failed", "No fields updated in fallback.")

    return successful


# === Inline Quote Summary Helper ===

def get_inline_quote_summary(data: dict) -> str:
    """
    Generates a natural, friendly quote summary for Brendan to show in chat.
    Includes price, estimated time, cleaner count, discount details, and selected options.
    """

    price = float(data.get("total_price", 0) or 0)
    time_est_mins = int(data.get("estimated_time_mins", 0) or 0)
    discount = float(data.get("discount_applied", 0) or 0)
    note = str(data.get("note", "") or "").strip()
    special_requests = str(data.get("special_requests", "") or "").strip()
    is_property_manager = str(data.get("is_property_manager", "") or "").lower() in TRUE_VALUES

    # === Time & Cleaners Calculation ===
    hours = time_est_mins / 60
    cleaners = max(1, (time_est_mins + 299) // 300)  # Max 5 hours per cleaner
    hours_per_cleaner = hours / cleaners
    hours_display = int(hours_per_cleaner) if hours_per_cleaner.is_integer() else round(hours_per_cleaner + 0.49)

    # === Dynamic Opening Line ===
    if price >= 800:
        opening = "Here’s what we’re looking at for this job:\n\n"
    elif price <= 300:
        opening = "Nice and easy — here’s your quote:\n\n"
    elif time_est_mins >= 360:
        opening = "This one will take a little longer — here’s your quote:\n\n"
    else:
        opening = "All sorted — here’s your quote:\n\n"

    summary = f"{opening}"
    summary += f"💰 Total Price (incl. GST): ${price:.2f}\n"
    summary += f"⏰ Estimated Time: ~{hours_display} hour(s) per cleaner with {cleaners} cleaner(s)\n"

    # === Discount Line Logic ===
    if discount > 0:
        if is_property_manager and discount >= (price / 1.1) * 0.15:
            summary += f"🏷️ Discount Applied: ${discount:.2f} — 10% Vacate Clean Special + 5% Property Manager Bonus\n"
        else:
            summary += f"🏷️ Discount Applied: ${discount:.2f} — 10% Vacate Clean Special\n"

    # === Selected Cleaning Options ===
    selected_services = []

    CLEANING_OPTIONS = {
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
    }

    for field, label in CLEANING_OPTIONS.items():
        if str(data.get(field, "")).lower() in TRUE_VALUES:
            selected_services.append(f"- {label}")

    if special_requests:
        selected_services.append(f"- Special Request: {special_requests}")

    if selected_services:
        summary += "\n🧹 Cleaning Included:\n" + "\n".join(selected_services)

    # === Notes (Optional) ===
    if note:
        summary += f"\n\n📜 Note: {note}"

    # === Closing Line ===
    summary += (
        "\n\nThis quote is valid for 7 days.\n"
        "Would you like me to send this to your email as a PDF, or would you like to make any changes?"
    )

    return summary.strip()


# === Generate Next Actions After Quote ===

def generate_next_actions():
    """
    Generates the next action options after quote is calculated.
    Brendan will:
    - Offer to send a PDF quote
    - Offer to email it
    - Offer to edit the quote
    - Offer to call the office
    """
    return [
        {
            "action": "offer_next_step",
            "response": (
                "What would you like to do next?\n\n"
                "I can send you a formal PDF quote, shoot it over to your email, "
                "or we can adjust the quote if you'd like to make any changes.\n\n"
                "Otherwise, you're always welcome to call our office on **1300 918 388** — "
                "just mention your quote number and they'll sort you out."
            ),
            "options": [
                {"label": "📄 Send PDF Quote", "value": "pdf_quote"},
                {"label": "📧 Email Me the Quote", "value": "email_quote"},
                {"label": "✏️ Edit the Quote", "value": "edit_quote"},
                {"label": "📞 Call the Office", "value": "call_office"}
            ]
        }
    ]

# === GPT Extraction (Production-Grade) ===

async def extract_properties_from_gpt4(message: str, log: str, record_id: str = None, quote_id: str = None):
   
    logger.info("🧑‍🔬 Calling GPT-4 Turbo to extract properties...")
    if record_id:
        log_debug_event(record_id, "BACKEND", "Calling GPT-4", "Sending message log for extraction.")

    # === Skip weak small talk ===
    weak_inputs = {"hi", "hello", "hey", "you there?", "you hear me?", "what’s up", "oi"}
    if message.lower().strip() in weak_inputs:
        reply = (
            "Hey there! I’m here to help — just let me know which suburb you're in, how many bedrooms and "
            "bathrooms you’ve got, and whether the place is furnished or unfurnished."
        )
        if record_id:
            log_debug_event(record_id, "GPT", "Weak Message Skipped", f"Message: {message}")
        return [], reply

    # === Retrieve current Airtable state (needed for quote_stage awareness and abuse escalation) ===
    existing = {}
    current_stage = ""
    if record_id:
        try:
            url = f"https://api.airtable.com/v0/{settings.AIRTABLE_BASE_ID}/{TABLE_NAME}/{record_id}"
            headers = {"Authorization": f"Bearer {settings.AIRTABLE_API_KEY}"}
            res = requests.get(url, headers=headers)
            res.raise_for_status()
            existing = res.json().get("fields", {})
            current_stage = existing.get("quote_stage", "")
        except Exception as e:
            logger.error(f"❌ Airtable fetch failed: {e}")
            log_debug_event(record_id, "BACKEND", "Airtable Fetch Failed", str(e))

    # === Format log and inject SYSTEM guard for calculated quotes ===
    prepared_log = re.sub(r'[^ -~\n]', '', log[-LOG_TRUNCATE_LENGTH:])
    messages = [{"role": "system", "content": GPT_PROMPT}]
    for line in prepared_log.split("\n"):
        if line.startswith("USER:"):
            messages.append({"role": "user", "content": line[5:].strip()})
        elif line.startswith("BRENDAN:"):
            messages.append({"role": "assistant", "content": line[8:].strip()})
        elif line.startswith("SYSTEM:"):
            messages.append({"role": "system", "content": line[7:].strip()})

    # Inject quote-stage message to stop premature confirmation
    if current_stage == "Quote Calculated":
        messages.append({
            "role": "system",
            "content": "REMINDER: The quote has already been calculated. Do NOT confirm or imply quote readiness again unless user requests changes."
        })

    messages.append({"role": "user", "content": message.strip()})

    # === GPT Call Helper ===
    def call_gpt(msgs):
        try:
            res = client.chat.completions.create(
                model="gpt-4-turbo",
                messages=msgs,
                max_tokens=3000,
                temperature=0.4
            )
            if not res.choices:
                raise ValueError("No choices returned.")
            return res.choices[0].message.content.strip().replace("```json", "").replace("```", "").strip()
        except Exception as e:
            logger.error(f"❌ GPT-4 request failed: {e}")
            if record_id:
                log_debug_event(record_id, "GPT", "Request Failed", str(e))
            raise

    # === Call GPT and parse JSON ===
    parsed = {}
    for attempt in range(2):
        try:
            raw = call_gpt(messages)
            logger.debug(f"🔍 RAW GPT OUTPUT (attempt {attempt + 1}):\n{raw}")
            if record_id:
                log_debug_event(record_id, "GPT", f"Raw Response Attempt {attempt + 1}", raw)

            start, end = raw.find("{"), raw.rfind("}")
            if start == -1 or end == -1:
                raise ValueError("JSON block not found.")
            parsed = json.loads(raw[start:end + 1])
            break
        except Exception as e:
            logger.warning(f"⚠️ GPT parsing failed (attempt {attempt + 1}): {e}")
            if record_id:
                log_debug_event(record_id, "GPT", f"Parse Error Attempt {attempt + 1}", str(e))
            if attempt == 1:
                return [], raw.strip()
            sleep(1)

    props = parsed.get("properties", [])
    reply = parsed.get("response", "").strip()
    existing_keys = {p["property"] for p in props if "property" in p}

    def ensure_field(name: str, default):
        if name not in existing_keys:
            props.append({"property": name, "value": default})

    # === Carpet logic ===
    carpet_fields = [
        "carpet_bedroom_count", "carpet_mainroom_count", "carpet_study_count",
        "carpet_halway_count", "carpet_stairs_count", "carpet_other_count"
    ]
    ensure_field("carpet_study_count", 0)
    ensure_field("upholstery_cleaning", False)
    ensure_field("carpet_cleaning", False)

    carpet_count = sum(
        int(p.get("value", 0)) for p in props
        if p["property"] in carpet_fields and isinstance(p.get("value"), (int, float))
    )
    if carpet_count > 0:
        for p in props:
            if p["property"] == "carpet_cleaning":
                p["value"] = True
                break
        else:
            props.append({"property": "carpet_cleaning", "value": True})

    # === Ask for missing carpet counts if any are missing ===
    missing_carpet = [f for f in carpet_fields if f not in existing_keys]
    if missing_carpet:
        msg = (
            "Thanks! Just to finish off the carpet section — could you tell me roughly how many of these have carpet?\n\n"
            "- Bedrooms\n- Living areas\n- Studies\n- Hallways\n- Stairs\n- Other areas"
        )
        if record_id:
            log_debug_event(record_id, "GPT", "Missing Carpet Fields", f"Missing: {missing_carpet}")
        return props, msg

    # === Abuse detection ===
    abuse_detected = any(word in message.lower() for word in ABUSE_WORDS)
    if abuse_detected:
        if not quote_id and existing:
            quote_id = existing.get("quote_id", "N/A")
        if current_stage == "Abuse Warning":
            reply = random.choice([
                f"We’ve ended the quote due to repeated language. Call us on 1300 918 388 with your quote number: {quote_id}. This chat is now closed.",
                f"Unfortunately we have to end the quote due to language. You're welcome to call our office if you'd like to continue. Quote Number: {quote_id}.",
                f"Let’s keep things respectful — I’ve had to stop the quote here. Feel free to call the office. Quote ID: {quote_id}. This chat is now closed."
            ])
            log_debug_event(record_id, "BACKEND", "Chat Banned", f"Repeated abuse. Quote ID: {quote_id}")
            return [{"property": "quote_stage", "value": "Chat Banned"}], reply
        else:
            reply = "Just a quick heads-up — we can’t continue the quote if abusive language is used. Let’s keep it respectful!\n\n" + reply
            log_debug_event(record_id, "BACKEND", "Abuse Warning", "First abuse detected.")
            return [{"property": "quote_stage", "value": "Abuse Warning"}], reply.strip()

    # === Fallback if nothing useful returned ===
    if not props:
        return [], "Hmm, I couldn’t quite catch the details. Mind telling me suburb, bedrooms, bathrooms and if it’s furnished?"

    log_debug_event(record_id, "GPT", "Properties Parsed", f"Props: {len(props)} | Reply: {reply[:100]}...")
    return props, reply

# === GPT Error Email Alert ===

def send_gpt_error_email(error_msg: str):
    """
    Sends an email to admin if GPT extraction fails and logs the error event.
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
            return  # Exit after success
        except smtplib.SMTPException as e:
            logger.warning(f"⚠️ SMTP error (attempt {attempt + 1}/2): {e}")
            if attempt == 1:
                logger.error("❌ Failed to send GPT error email after 2 attempts.")
                try:
                    log_debug_event(None, "BACKEND", "GPT Error Email Failed", f"SMTP error: {str(e)}")
                except Exception as log_e:
                    logger.error(f"❌ Error logging email send failure: {log_e}")
            else:
                sleep(5)  # Wait before retrying
        except Exception as e:
            logger.error(f"❌ Unexpected error sending GPT error email: {e}")
            try:
                log_debug_event(None, "BACKEND", "Unexpected Email Error", str(e))
            except Exception as log_e:
                logger.error(f"❌ Error logging unexpected email failure: {log_e}")
            return


# === Append Message Log ===

def append_message_log(record_id: str, message: str, sender: str):
    """
    Appends a new message to the 'message_log' field in Airtable.
    Truncates from the start if the log exceeds MAX_LOG_LENGTH.
    Logs all actions and failures for traceability.
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
    new_entry = (
        "SYSTEM_TRIGGER: Brendan started a new quote"
        if sender_clean == "USER" and message.lower() == "__init__"
        else f"{sender_clean}: {message}"
    )

    url = f"https://api.airtable.com/v0/{settings.AIRTABLE_BASE_ID}/{TABLE_NAME}/{record_id}"
    headers = {"Authorization": f"Bearer {settings.AIRTABLE_API_KEY}"}

    # === Fetch existing message_log with up to 3 retries ===
    old_log = ""
    for attempt in range(3):
        try:
            res = requests.get(url, headers=headers)
            res.raise_for_status()
            old_log = str(res.json().get("fields", {}).get("message_log", "")).strip()
            break
        except Exception as e:
            logger.warning(f"⚠️ Attempt {attempt + 1}/3 — Failed to fetch message_log: {e}")
            if attempt == 2:
                logger.error(f"❌ Failed to fetch message_log after 3 attempts for {record_id}")
                log_debug_event(record_id, "BACKEND", "Log Fetch Failed", str(e))
                return
            sleep(1)

    combined_log = f"{old_log}\n{new_entry}" if old_log else new_entry
    was_truncated = False
    if len(combined_log) > MAX_LOG_LENGTH:
        combined_log = combined_log[-MAX_LOG_LENGTH:]
        was_truncated = True

    logger.info(f"📚 Updating message_log for {record_id} (len={len(combined_log)})")

    try:
        update_quote_record(record_id, {"message_log": combined_log})
    except Exception as e:
        logger.error(f"❌ Failed to update message_log in Airtable: {e}")
        log_debug_event(record_id, "BACKEND", "Message Log Update Failed", str(e))
        return

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
        logger.warning(f"⚠️ Failed to log debug message: {e}")
        log_debug_event(record_id, "BACKEND", "Debug Log Event Failed", str(e))

# === Brendan Filter Response Route ===

# === Brendan API Router ===
router = APIRouter()

# === /log-debug Route ===
@router.post("/log-debug")
async def log_debug(request: Request):
    try:
        body = await request.json()
        session_id = str(body.get("session_id", "")).strip()
        message = str(body.get("message", "")).strip()
        source = str(body.get("source", "frontend")).strip()

        if session_id and message:
            formatted = f"(Session ID: {session_id}) {message}"
            log_debug_event(None, source.upper(), "Frontend Log", formatted)

        return JSONResponse(content={"status": "success"})
    except Exception as e:
        log_debug_event(None, "BACKEND", "Log Debug Error", str(e))
        return JSONResponse(content={"status": "error"}, status_code=500)


# === /filter-response Route ===
@router.post("/filter-response")
async def filter_response_entry(request: Request):
    try:
        body = await request.json()
        message = str(body.get("message", "")).strip()
        session_id = str(body.get("session_id", "")).strip()

        log_debug_event(None, "BACKEND", "Incoming Message", f"Session: {session_id}, Message: {message}")

        if not session_id:
            raise HTTPException(status_code=400, detail="Session ID is required.")

        if message.lower() == "__init__":
            log_debug_event(None, "BACKEND", "Init Triggered", "User opened chat and triggered __init__.")
            existing = get_quote_by_session(session_id)

            if existing:
                try:
                    quote_id, record_id, stage, fields = existing
                    timestamp = fields.get("timestamp")
                    if stage in ["Quote Calculated", "Personal Info Received", "Booking Confirmed"] or not timestamp:
                        raise ValueError("Stale or complete quote")
                except Exception:
                    existing = None

            if not existing:
                quote_id, record_id, stage, fields = create_new_quote(session_id, force_new=True)
                session_id = fields.get("session_id", session_id)
                log_debug_event(record_id, "BACKEND", "New Quote Created", f"Session: {session_id}")

            append_message_log(record_id, message, "user")
            flush = flush_debug_log(record_id)
            if flush:
                update_quote_record(record_id, {"debug_log": flush})

            log_debug_event(record_id, "BACKEND", "Init Complete", "Chat flow started with new session.")

            return JSONResponse(content={
                "properties": [],
                "response": "",
                "next_actions": [],
                "session_id": session_id
            })

        quote_data = get_quote_by_session(session_id)
        if not quote_data:
            raise HTTPException(status_code=404, detail="Quote not found.")

        quote_id, record_id, stage, fields = quote_data
        message_lower = message.lower()
        pdf_keywords = ["pdf please", "send pdf", "get pdf", "send quote", "email quote", "pdf quote"]

        if stage == "Chat Banned":
            reply = "This chat is closed. Call 1300 918 388 if you still need a quote."
            log_debug_event(record_id, "BACKEND", "Blocked", "User is banned.")
            return JSONResponse(content={"properties": [], "response": reply, "next_actions": [], "session_id": session_id})

        if stage == "Gathering Personal Info" and not fields.get("privacy_acknowledged", False):
            if message_lower in ["yes", "yep", "ok", "sure", "go ahead"]:
                update_quote_record(record_id, {"privacy_acknowledged": True})
                fields = get_quote_by_session(session_id)[3]
                reply = "Thanks! What’s your name, email, phone number, and (optional) property address?"
                log_debug_event(record_id, "BACKEND", "Privacy Acknowledged", "User accepted.")
            else:
                reply = "No worries — we just need your name, email and phone to send the quote. Let me know when you're ready."
                log_debug_event(record_id, "BACKEND", "Privacy Awaiting", "Still waiting on consent.")

            append_message_log(record_id, message, "user")
            append_message_log(record_id, reply, "brendan")
            return JSONResponse(content={"properties": [], "response": reply, "next_actions": [], "session_id": session_id})

        if stage == "Gathering Personal Info" and fields.get("privacy_acknowledged", False):
            if all([fields.get("customer_name"), fields.get("customer_email"), fields.get("customer_phone")]):
                email = fields.get("customer_email", "")
                if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
                    reply = "Hmm, that email looks off — could you double check it?"
                    append_message_log(record_id, message, "user")
                    append_message_log(record_id, reply, "brendan")
                    return JSONResponse(content={"properties": [], "response": reply, "next_actions": [], "session_id": session_id})

                update_quote_record(record_id, {"quote_stage": "Personal Info Received"})
                fields = get_quote_by_session(session_id)[3]

                try:
                    pdf_path = generate_quote_pdf(fields)
                    send_quote_email(
                        to_email=email,
                        customer_name=fields.get("customer_name"),
                        pdf_path=pdf_path,
                        quote_id=quote_id
                    )
                    update_quote_record(record_id, {"pdf_link": pdf_path})
                    reply = "All done! I’ve just emailed your quote. Let me know if you need anything else."
                    log_debug_event(record_id, "BACKEND", "PDF Sent", f"To: {email}")
                except Exception as e:
                    reply = "Something went wrong while sending your quote. Please call 1300 918 388 and we’ll help out."
                    log_debug_event(record_id, "BACKEND", "PDF Error", str(e))

                append_message_log(record_id, message, "user")
                append_message_log(record_id, reply, "brendan")
                return JSONResponse(content={"properties": [], "response": reply, "next_actions": [], "session_id": session_id})

        log = fields.get("message_log", "")[-LOG_TRUNCATE_LENGTH:]
        if stage == "Quote Calculated" and any(k in message_lower for k in pdf_keywords):
            log = PDF_SYSTEM_MESSAGE + "\n\n" + log

        append_message_log(record_id, message, "user")
        log_debug_event(record_id, "BACKEND", "Calling GPT", "Sending log to GPT for field extraction.")

        properties, reply = await extract_properties_from_gpt4(message, log, record_id, quote_id)
        parsed = {p["property"]: p["value"] for p in properties if "property" in p and "value" in p}

        merged = fields.copy()
        merged.update(parsed)

        if parsed.get("quote_stage") == "Quote Calculated" and message_lower not in pdf_keywords:
            try:
                result = calculate_quote(QuoteRequest(**merged))
                parsed.update(result.model_dump())
                summary = get_inline_quote_summary(result.model_dump())
                reply = summary + "\n\nWould you like me to email you this quote as a PDF?"
                log_debug_event(record_id, "BACKEND", "Quote Ready", f"${parsed.get('total_price')} for {parsed.get('estimated_time_mins')} mins")
            except Exception as e:
                log_debug_event(record_id, "BACKEND", "Quote Calc Fail", str(e))

        update_quote_record(record_id, parsed)
        append_message_log(record_id, reply, "brendan")
        next_actions = generate_next_actions() if parsed.get("quote_stage") == "Quote Calculated" else []

        return JSONResponse(content={
            "properties": properties,
            "response": reply,
            "next_actions": next_actions,
            "session_id": session_id
        })

    except Exception as e:
        log_debug_event(None, "BACKEND", "Fatal Error", str(e))
        raise HTTPException(status_code=500, detail="Internal server error.")
