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
from app.services.quote_logic import calculate_quote
from app.models.quote_models import QuoteRequest
from app.config import logger, settings  # Logger and Settings loaded from config.py

# === Field Rules / Validations ===
from app.api.field_rules import FIELD_MAP, VALID_AIRTABLE_FIELDS, INTEGER_FIELDS, BOOLEAN_FIELDS

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

# === FastAPI Router ===
router = APIRouter()

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

# === Get Quote by Session ID ===

def get_quote_by_session(session_id: str):
    """
    Retrieves the latest quote record from Airtable using session_id.
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

    logger.info(f"🔍 Searching for quote by session_id: {session_id}")

    # Log the session lookup attempt
    log_debug_event(None, "BACKEND", "Session Lookup Attempt", f"Attempting to fetch quote for session_id: {session_id}")

    for attempt in range(3):
        try:
            res = requests.get(url, headers=headers, params=params)
            res.raise_for_status()
            data = res.json()
            break
        except Exception as e:
            logger.warning(f"⚠️ Airtable fetch failed (attempt {attempt + 1}/3): {e}")
            log_debug_event(None, "BACKEND", "Session Lookup Failed", f"Attempt {attempt + 1} failed with error: {e}")
            if attempt == 2:
                logger.error(f"❌ Failed to fetch quote for session_id {session_id} after 3 attempts.")
                log_debug_event(None, "BACKEND", "Session Lookup Final Failure", f"Failed to fetch quote after 3 attempts: {e}")
                return None
            sleep(1)

    records = data.get("records", [])
    if not records:
        logger.info(f"⏳ No existing quote found for session_id: {session_id}")
        log_debug_event(None, "BACKEND", "No Quote Found", f"No quote found for session_id: {session_id}")
        return None

    record = records[0]
    fields = record.get("fields", {})

    quote_id = fields.get("quote_id", "N/A")
    record_id = record.get("id", "")
    quote_stage = fields.get("quote_stage", "Gathering Info")
    session_id_return = fields.get("session_id", session_id)

    logger.info(
        f"✅ Found quote | session_id: {session_id_return} | quote_id: {quote_id} | stage: {quote_stage}"
    )

    # ✅ Log the found session and quote details
    try:
        log_debug_event(record_id, "BACKEND", "Session Lookup Success", f"Quote found for session_id: {session_id_return}, quote_id: {quote_id}, stage: {quote_stage}")
    except Exception as e:
        logger.warning(f"⚠️ Failed to log debug event for session lookup: {e}")

    return quote_id, record_id, quote_stage, fields

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

    # === Furnished Field Special Handling ===
    if "furnished" in fields:
        val = str(fields["furnished"]).strip().lower()
        if "unfurnished" in val:
            fields["furnished"] = "Unfurnished"
        elif "furnished" in val:
            fields["furnished"] = "Furnished"
        else:
            logger.warning(f"⚠️ Invalid furnished value: {fields['furnished']}")
            fields["furnished"] = ""

    # === Normalize Fields ===
    for raw_key, value in fields.items():
        key = FIELD_MAP.get(raw_key, raw_key)

        if key not in VALID_AIRTABLE_FIELDS:
            logger.warning(f"⚠️ Skipping unknown Airtable field: {key}")
            continue

        # Boolean Handling
        if key in BOOLEAN_FIELDS:
            if isinstance(value, bool):
                pass
            elif value in [None, ""]:
                value = False
            else:
                value = str(value).strip().lower() in TRUE_VALUES

        # Integer Handling
        elif key in INTEGER_FIELDS:
            try:
                value = int(value)
                if value > MAX_REASONABLE_INT:
                    logger.warning(f"⚠️ Clamping large value for {key}: {value}")
                    value = MAX_REASONABLE_INT
            except Exception:
                logger.warning(f"⚠️ Failed to convert {key} to int — forcing 0")
                value = 0

        # Float Handling
        elif key in {
            "gst_applied", "total_price", "base_hourly_rate", "price_per_session",
            "estimated_time_mins", "discount_applied", "mandurah_surcharge",
            "after_hours_surcharge", "weekend_surcharge", "calculated_hours"
        }:
            try:
                value = float(value)
            except Exception:
                logger.warning(f"⚠️ Failed to convert {key} to float — forcing 0.0")
                value = 0.0

        # Special Requests Normalization
        elif key == "special_requests":
            if not value or str(value).strip().lower() in {"no", "none", "false", "no special requests", "n/a"}:
                value = ""

        # Extra Hours Requested Normalization
        elif key == "extra_hours_requested":
            try:
                value = float(value) if value not in [None, ""] else 0
            except Exception:
                value = 0

        # Everything Else = Str
        else:
            value = "" if value is None else str(value).strip()

        normalized_fields[key] = value

    # === Final Force Privacy Handling ===
    if "privacy_acknowledged" in fields:
        normalized_fields["privacy_acknowledged"] = bool(fields.get("privacy_acknowledged"))

    # === Exit Early if No Valid Fields ===
    if not normalized_fields:
        logger.info(f"⏩ No valid fields to update for record {record_id}")
        log_debug_event(record_id, "BACKEND", "No Valid Fields", "No valid fields to update in this request.")
        return []

    # === Final Sanity Check ===
    logger.info(f"\n📤 Updating Airtable Record: {record_id}")
    logger.info(f"🛠 Payload: {json.dumps(normalized_fields, indent=2)}")

    for key in list(normalized_fields.keys()):
        if key not in VALID_AIRTABLE_FIELDS:
            logger.error(f"❌ INVALID FIELD DETECTED: {key} — Removing from payload.")
            normalized_fields.pop(key, None)

    # === Attempt Bulk Update ===
    try:
        res = requests.patch(url, headers=headers, json={"fields": normalized_fields})
        if res.ok:
            logger.info("✅ Airtable bulk update success.")
            log_debug_event(record_id, "BACKEND", "Record Updated (Bulk)", f"Fields updated: {list(normalized_fields.keys())}")
            return list(normalized_fields.keys())

        logger.error(f"❌ Airtable bulk update failed: {res.status_code}")
        try:
            logger.error(f"🧾 Error response: {res.json()}")
        except Exception:
            logger.error("🧾 Error response: (Non-JSON)")

    except Exception as e:
        logger.error(f"❌ Exception during Airtable bulk update: {e}")
        log_debug_event(record_id, "BACKEND", "Airtable Update Error", str(e))

    # === Fallback to Single Field Update ===
    successful = []
    for key, value in normalized_fields.items():
        try:
            single_res = requests.patch(url, headers=headers, json={"fields": {key: value}})
            if single_res.ok:
                logger.info(f"✅ Field '{key}' updated successfully.")
                successful.append(key)
            else:
                logger.error(f"❌ Field '{key}' failed to update.")
        except Exception as e:
            logger.error(f"❌ Exception updating field '{key}': {e}")
            log_debug_event(record_id, "BACKEND", "Single Field Update Failed", f"Field: {key}, Error: {e}")

    if successful:
        log_debug_event(record_id, "BACKEND", "Record Updated (Fallback)", f"Fields updated one-by-one: {successful}")
    else:
        log_debug_event(record_id, "BACKEND", "Update Failed", "No fields could be updated (bulk and fallback both failed).")

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
    hours_per_cleaner_rounded = int(hours_per_cleaner) if hours_per_cleaner.is_integer() else round(hours_per_cleaner + 0.49)

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
    summary += f"⏰ Estimated Time: ~{hours_per_cleaner_rounded} hour(s) per cleaner with {cleaners} cleaner(s)\n"

    # === Discount Line Logic ===
    if discount > 0:
        if is_property_manager and discount >= price / 1.1 * 0.15:
            summary += f"🏷️ Discount Applied: ${discount:.2f} — 10% Vacate Clean Special (+5% Property Manager Bonus)\n"
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
        summary += "\n🧹 Cleaning Included:\n" + "\n".join(selected_services) + "\n"

    # === Notes (Optional) ===
    if note:
        summary += f"\n📜 Note: {note}\n"

    # === Closing Line ===
    summary += (
        "\nThis quote is valid for 7 days.\n"
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

def extract_properties_from_gpt4(message: str, log: str, record_id: str = None, quote_id: str = None):
    import json
    import random
    import traceback
    import re
    from time import sleep

    # Log the incoming GPT-4 request
    logger.info("🧑‍🔬 Calling GPT-4 Turbo to extract properties...")
    if record_id:
        log_debug_event(record_id, "BACKEND", "Calling GPT-4", "Sending message log for extraction.")

    def call_gpt(prepared_log: str):
        """
        Send a request to GPT-4 Turbo to get the extracted properties.
        """
        try:
            response = client.chat.completions.create(
                model="gpt-4-turbo",
                messages=[
                    {"role": "system", "content": GPT_PROMPT},
                    {"role": "user", "content": prepared_log}
                ],
                max_tokens=3000,
                temperature=0.4
            )
            if not response.choices:
                raise ValueError("No choices returned from GPT-4.")
            raw = response.choices[0].message.content.strip()
            raw = raw.replace("```json", "").replace("```", "").strip()
            return raw
        except Exception as e:
            logger.error(f"❌ GPT-4 request failed: {e}")
            if record_id:
                log_debug_event(record_id, "GPT", "Request Failed", str(e))
            raise

    # Preprocess the log, cleaning non-printable characters
    prepared_log = log[-LOG_TRUNCATE_LENGTH:]
    prepared_log = re.sub(r'[^ -~\n]', '', prepared_log)

    # Call GPT-4 with retry logic
    raw = None
    for attempt in range(2):
        try:
            raw = call_gpt(prepared_log)
            logger.debug(f"🔍 RAW GPT OUTPUT (attempt {attempt + 1}):\n{raw}")

            if record_id:
                log_debug_event(record_id, "GPT", f"Raw Response Attempt {attempt + 1}", raw)

            # Extract JSON block from GPT output
            start, end = raw.find("{"), raw.rfind("}")
            if start == -1 or end == -1:
                raise ValueError("JSON block not found.")
            parsed = json.loads(raw[start:end + 1])
            break
        except Exception as e:
            logger.warning(f"⚠️ GPT extraction failed (attempt {attempt + 1}): {e}")
            if record_id:
                log_debug_event(record_id, "GPT", f"Parsing Failed Attempt {attempt + 1}", str(e))
            if attempt == 1:
                raise e
            sleep(1)

    # Parse the properties and response
    props = parsed.get("properties", [])
    reply = parsed.get("response", "")

    # Log the parsed properties
    if record_id:
        log_debug_event(record_id, "GPT", "Properties Parsed", f"Props found: {len(props)} | Reply: {reply[:100]}")

    logger.debug(f"✅ Parsed props: {props}")
    logger.debug(f"✅ Parsed reply: {reply}")

    # Fetch existing quote data from Airtable if record_id is present
    existing = {}
    if record_id:
        url = f"https://api.airtable.com/v0/{settings.AIRTABLE_BASE_ID}/{TABLE_NAME}/{record_id}"
        headers = {"Authorization": f"Bearer {settings.AIRTABLE_API_KEY}"}
        try:
            res = requests.get(url, headers=headers)
            res.raise_for_status()
            existing = res.json().get("fields", {})
        except Exception as e:
            logger.error(f"❌ Failed to fetch existing record from Airtable: {e}")
            if record_id:
                log_debug_event(record_id, "BACKEND", "Airtable Fetch Failed", str(e))

    logger.warning(f"🔍 Existing Airtable Fields: {existing}")
    current_stage = existing.get("quote_stage", "")
    field_updates = {}

    # Handle special request handling and early exit if special request times are specified
    min_total_mins = base_minutes = 0
    max_total_mins = base_minutes
    is_range = False
    note = None

    if data.special_request_minutes_min is not None and data.special_request_minutes_max is not None:
        min_total_mins += data.special_request_minutes_min
        max_total_mins += data.special_request_minutes_max
        is_range = True
        note = f"Includes {data.special_request_minutes_min}–{data.special_request_minutes_max} min for special request"
        log_debug_event(record_id, "BACKEND", "Special Request Time Added", f"{data.special_request_minutes_min}–{data.special_request_minutes_max} mins")

    # Return early if special requests need further input
    if "special_requests" in missing:
        reply = ("Awesome — before I whip up your quote, do you have any special requests "
                 "(like inside microwave, extra windows, balcony door tracks etc)?")
        return field_updates, reply

    if not missing:
        field_updates["quote_stage"] = "Quote Calculated"
    elif current_stage == "Gathering Info" and "quote_stage" not in field_updates:
        field_updates["quote_stage"] = "Gathering Info"
    elif current_stage == "Abuse Warning" and "quote_stage" not in field_updates:
        field_updates["quote_stage"] = "Chat Banned"

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
            if record_id:
                log_debug_event(record_id, "BACKEND", "Chat Banned", f"User repeated abusive language. Quote ID: {quote_id}")
            return field_updates, reply
        else:
            field_updates["quote_stage"] = "Abuse Warning"
            reply = ("Just a heads-up — we can’t continue the quote if abusive language is used. "
                     "Let’s keep things respectful 👍\n\n" + reply)
            if record_id:
                log_debug_event(record_id, "BACKEND", "Abuse Warning", "First offensive message detected.")

    return field_updates, reply.strip()

# === Create New Quote ===

def create_new_quote(session_id: str, force_new: bool = False):
    """
    Creates a new quote record in Airtable.
    Returns: (quote_id, record_id, quote_stage, fields)
    """

    logger.info(f"🚨 Checking for existing session: {session_id}")

    # Log the initiation of the quote creation
    log_debug_event(None, "BACKEND", "Quote Creation Initiated", f"Checking for existing quote with session_id: {session_id}")

    # Check for existing quote unless forced new
    if not force_new:
        existing = get_quote_by_session(session_id)
        if existing:
            logger.warning("⚠️ Duplicate session detected. Returning existing quote.")
            log_debug_event(None, "BACKEND", "Duplicate Session", f"Returning existing quote for session_id: {session_id}")
            return existing

    # Force new session_id if requested
    if force_new:
        logger.info("🔁 Force creating new quote despite duplicate session ID.")
        session_id = f"{session_id}-new-{str(uuid.uuid4())[:6]}"
        log_debug_event(None, "BACKEND", "Force New Quote", f"Session ID forced to be unique: {session_id}")

    # Generate new quote_id
    quote_id = get_next_quote_id()
    logger.info(f"🔑 Generated new quote_id: {quote_id}")
    log_debug_event(None, "BACKEND", "New Quote ID", f"New quote ID generated: {quote_id}")

    url = f"https://api.airtable.com/v0/{settings.AIRTABLE_BASE_ID}/{TABLE_NAME}"
    headers = {
        "Authorization": f"Bearer {settings.AIRTABLE_API_KEY}",
        "Content-Type": "application/json"
    }

    # Fields to create new record
    data = {
        "fields": {
            "session_id": session_id,
            "quote_id": quote_id,
            "quote_stage": "Gathering Info",
            "message_log": "",
            "privacy_acknowledged": False,  # Force privacy ack False on creation
            "source": "Brendan"  # Always tag source as Brendan
        }
    }

    # Attempt to create record
    try:
        res = requests.post(url, headers=headers, json=data)
        res.raise_for_status()

        record_id = res.json().get("id")
        logger.info(f"✅ Created new quote record: {record_id} with ID {quote_id}")
        log_debug_event(record_id, "BACKEND", "Quote Created", f"New quote record created with session_id: {session_id}, quote_id: {quote_id}")

        # Append system log entry
        append_message_log(record_id, "SYSTEM_TRIGGER: Brendan started a new quote", "system")

        # Return standard tuple for caching
        return quote_id, record_id, "Gathering Info", {
            "quote_stage": "Gathering Info",
            "message_log": "",
            "session_id": session_id,
            "privacy_acknowledged": False,  # Explicit for cache
            "source": "Brendan"
        }

    except requests.RequestException as e:
        logger.error(f"❌ FAILED to create quote: {e}")
        log_debug_event(None, "BACKEND", "Quote Creation Failed", f"Error creating quote: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to create Airtable record.")


# === GPT Error Email Alert ===

import smtplib
from email.mime.text import MIMEText
from time import sleep


def send_gpt_error_email(error_msg: str):
    """
    Sends an email to admin if GPT extraction fails and logs the error event.
    """

    import smtplib
    from email.mime.text import MIMEText
    from time import sleep
    from app.routes.filter_response import log_debug_event  # ✅ Import for logging

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
    """

    from time import sleep

    if not record_id:
        logger.error("❌ Cannot append message log — missing record ID")
        try:
            log_debug_event(record_id, "BACKEND", "Log Failed", "Missing record ID for appending message log")
        except Exception as e:
            logger.error(f"❌ Error logging message append failure due to missing record ID: {e}")
        return

    message = str(message or "").strip()
    if not message:
        logger.info("⏩ Empty message after stripping — skipping log update")
        return

    sender_clean = str(sender or "user").strip().upper()
    new_entry = f"{sender_clean}: {message}"

    url = f"https://api.airtable.com/v0/{settings.AIRTABLE_BASE_ID}/{TABLE_NAME}/{record_id}"
    headers = {
        "Authorization": f"Bearer {settings.AIRTABLE_API_KEY}"
    }

    # === Fetch Existing Log ===
    for attempt in range(3):
        try:
            res = requests.get(url, headers=headers)
            res.raise_for_status()
            current = res.json()
            break
        except Exception as e:
            logger.warning(f"⚠️ Airtable log fetch failed (attempt {attempt + 1}/3): {e}")
            if attempt == 2:
                logger.error(f"❌ Failed to fetch message_log for record {record_id} after 3 attempts.")
                try:
                    log_debug_event(record_id, "BACKEND", "Log Fetch Failed", f"Failed after 3 attempts to fetch message_log. Error: {str(e)}")
                except Exception as log_e:
                    logger.error(f"❌ Error logging failed log fetch: {log_e}")
                return
            sleep(1)

    old_log = str(current.get("fields", {}).get("message_log", "")).strip()
    combined_log = f"{old_log}\n{new_entry}" if old_log else new_entry

    # === Enforce Length Limit ===
    was_truncated = False
    if len(combined_log) > MAX_LOG_LENGTH:
        combined_log = combined_log[-MAX_LOG_LENGTH:]
        was_truncated = True

    logger.info(f"📚 Appending to message log for record {record_id}")
    logger.debug(f"📝 New message_log length: {len(combined_log)} characters")

    try:
        update_quote_record(record_id, {"message_log": combined_log})
    except Exception as e:
        logger.error(f"❌ Error updating message log in Airtable for record {record_id}: {e}")
        try:
            log_debug_event(record_id, "BACKEND", "Log Update Failed", f"Error updating message_log in Airtable: {e}")
        except Exception as log_e:
            logger.error(f"❌ Error logging log update failure: {log_e}")
        return

    # === Debug Log Event ===
    try:
        detail_msg = f"{sender_clean} message logged ({len(message)} chars)"
        if was_truncated:
            detail_msg += " | ⚠️ Truncated message_log due to size"
        log_debug_event(record_id, "BACKEND", "Message Appended", detail_msg)
    except Exception as e:
        logger.warning(f"⚠️ Failed to log debug event from append_message_log: {e}")
        try:
            log_debug_event(record_id, "BACKEND", "Debug Log Event Failed", f"Error logging debug event: {e}")
        except Exception as log_e:
            logger.error(f"❌ Error logging debug event failure: {log_e}")

# === Log Debugs At Airtable ===

import requests
import json
from app.config import settings, logger

# Airtable Settings
AIRTABLE_API_KEY = settings.AIRTABLE_API_KEY
AIRTABLE_BASE_ID = settings.AIRTABLE_BASE_ID
QUOTE_TABLE_NAME = "Vacate Quotes"  # The name of your existing table

def log_debug_event(record_id: str, source: str, message: str, raw_data: str = ""):
    """
    Logs a debug event to the existing Vacate Quotes table in Airtable under the `debug_log` field.
    """

    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{QUOTE_TABLE_NAME}/{record_id}"
    headers = {
        "Authorization": f"Bearer {AIRTABLE_API_KEY}",
        "Content-Type": "application/json"
    }

    # Prepare the log data to be sent to Airtable
    log_entry = f"[{source}] {message}\nRaw Data: {raw_data}\n"

    # Fetch the current debug log for this record
    try:
        res = requests.get(url, headers=headers)
        res.raise_for_status()
        record = res.json()
        existing_log = record.get("fields", {}).get("debug_log", "")
        combined_log = f"{existing_log}\n{log_entry}" if existing_log else log_entry
    except Exception as e:
        logger.error(f"❌ Failed to fetch existing debug log for record {record_id}: {e}")
        combined_log = log_entry

    # Update the `debug_log` field with the new log entry
    update_data = {
        "fields": {
            "debug_log": combined_log
        }
    }

    try:
        res = requests.patch(url, headers=headers, json=update_data)
        if res.ok:
            logger.info(f"✅ Log sent to Airtable for record {record_id}: {message}")
        else:
            logger.error(f"❌ Failed to send log to Airtable for record {record_id}: {res.text}")
            try:
                log_debug_event(record_id, "BACKEND", "Failed to send log", f"Airtable response: {res.text}")
            except Exception as inner_e:
                logger.error(f"❌ Failed to log error after failed log send: {inner_e}")
    except Exception as e:
        logger.error(f"❌ Error sending log to Airtable: {e}")
        try:
            log_debug_event(record_id, "BACKEND", "Error sending log", str(e))
        except Exception as inner_e:
            logger.error(f"❌ Failed to log error during log send failure: {inner_e}")


# === Brendan Filter Response Route ===

router = APIRouter()

# === log-debug Route ===
@router.post("/log-debug")
async def log_debug(request: Request):
    """
    Accepts logs from the frontend and logs them into Airtable or other logging systems.
    """
    try:
        body = await request.json()
        session_id = body.get("session_id", "")
        message = body.get("message", "")
        source = body.get("source", "frontend")

        # If session_id and message are available, log the event
        if session_id and message:
            log_debug_event(session_id, source, "Frontend Log", message)

        return JSONResponse(content={"status": "success"})  # Return success response
    except Exception as e:
        logger.error(f"❌ Error logging frontend debug message: {e}")
        return JSONResponse(content={"status": "error"}, status_code=500)


@router.post("/filter-response")
async def filter_response_entry(request: Request):
    try:
        body = await request.json()
        message = str(body.get("message", "")).strip()
        session_id = str(body.get("session_id", "")).strip()

        if not session_id:
            log_debug_event(None, "BACKEND", "Missing Session ID", "Session ID is required but not provided.")
            raise HTTPException(status_code=400, detail="Session ID is required.")

        # Log the start of the session initiation
        if message.lower() == "__init__":
            log_debug_event(None, "BACKEND", "Init Triggered", "User opened chat and triggered __init__.")

            existing = get_quote_by_session(session_id)
            if existing:
                quote_id, record_id, stage, fields = existing
                log_debug_event(record_id, "BACKEND", "Existing Quote Found", f"Session: {session_id}")
            else:
                quote_id, record_id, stage, fields = create_new_quote(session_id, force_new=True)
                session_id = fields.get("session_id", session_id)
                log_debug_event(record_id, "BACKEND", "Quote Created", f"New quote created with session_id: {session_id}")

            reply = "What needs cleaning today — bedrooms, bathrooms, oven, carpets, anything else?"
            append_message_log(record_id, message, "user")
            append_message_log(record_id, reply, "brendan")

            log_debug_event(record_id, "BACKEND", "Greeting Sent", reply)
            return JSONResponse(content={"properties": [], "response": reply, "next_actions": [], "session_id": session_id})

        # Fetch existing quote data
        quote_id, record_id, stage, fields = get_quote_by_session(session_id)
        if not record_id:
            log_debug_event(None, "BACKEND", "Quote Not Found", f"No quote found for session: {session_id}")
            raise HTTPException(status_code=404, detail="Quote not found.")

        message_lower = message.lower()
        pdf_keywords = ["pdf please", "send pdf", "get pdf", "send quote", "email it to me", "email quote", "pdf quote"]

        # Blocked Chat Handling
        if stage == "Chat Banned":
            reply = "This chat is closed due to prior messages. Please call 1300 918 388 if you still need a quote."
            log_debug_event(record_id, "BACKEND", "Blocked Message", "User is banned.")
            return JSONResponse(content={"properties": [], "response": reply, "next_actions": [], "session_id": session_id})

        # Privacy Acknowledgement Flow
        if stage == "Gathering Personal Info" and not fields.get("privacy_acknowledged", False):
            if message_lower in ["yes", "yep", "sure", "ok", "okay", "yes please", "go ahead"]:
                update_quote_record(record_id, {"privacy_acknowledged": True})
                fields = get_quote_by_session(session_id)[3]
                reply = "Great! Could you please provide your name, email, phone number, and (optional) property address so I can send the PDF quote?"
                log_debug_event(record_id, "BACKEND", "Privacy Acknowledged", "User accepted privacy policy.")
            else:
                reply = "No problem — we only need your name, email, phone number (and optional property address) to send the quote. Let me know if you'd like to continue or if you have any questions about our privacy policy."
                log_debug_event(record_id, "BACKEND", "Privacy Denied", "User has not yet accepted privacy policy.")

            append_message_log(record_id, message, "user")
            append_message_log(record_id, reply, "brendan")

            return JSONResponse(content={"properties": [], "response": reply, "next_actions": [], "session_id": session_id})

        # Handle Personal Info Received Stage
        if stage == "Gathering Personal Info" and fields.get("privacy_acknowledged", False):
            if all([fields.get("customer_name"), fields.get("customer_email"), fields.get("customer_phone")]):
                customer_email = str(fields.get("customer_email", "")).strip()
                if not re.match(r"[^@]+@[^@]+\.[^@]+", customer_email):
                    reply = "That email doesn’t look right — could you double check and send it again?"
                    append_message_log(record_id, message, "user")
                    append_message_log(record_id, reply, "brendan")
                    log_debug_event(record_id, "BACKEND", "Email Validation Failed", f"Input: {customer_email}")
                    return JSONResponse(content={"properties": [], "response": reply, "next_actions": [], "session_id": session_id})

                update_quote_record(record_id, {"quote_stage": "Personal Info Received"})
                fields = get_quote_by_session(session_id)[3]

                try:
                    pdf_path = generate_quote_pdf(fields)
                    send_quote_email(to_email=customer_email, customer_name=fields.get("customer_name"), pdf_path=pdf_path, quote_id=quote_id)
                    update_quote_record(record_id, {"pdf_link": pdf_path})
                    reply = "Thanks so much — I’ve sent your quote through to your email! Let me know if there’s anything else I can help with."
                    log_debug_event(record_id, "BACKEND", "PDF Sent", f"Quote emailed to {customer_email}")
                except Exception as e:
                    logger.exception(f"❌ PDF Generation/Email Sending Failed: {e}")
                    reply = "Sorry — I ran into an issue while generating your PDF quote. Please call our office on 1300 918 388 and we’ll sort it out for you."
                    log_debug_event(record_id, "BACKEND", "PDF Error", str(e))

                append_message_log(record_id, message, "user")
                append_message_log(record_id, reply, "brendan")
                return JSONResponse(content={"properties": [], "response": reply, "next_actions": [], "session_id": session_id})

        # Handle Quote Calculated Stage
        log = fields.get("message_log", "")
        if stage == "Quote Calculated" and any(k in message_lower for k in pdf_keywords):
            log = PDF_SYSTEM_MESSAGE + "\n\n" + log[-LOG_TRUNCATE_LENGTH:]
        else:
            log = log[-LOG_TRUNCATE_LENGTH:]

        append_message_log(record_id, message, "user")
        log_debug_event(record_id, "BACKEND", "Calling GPT-4", "Sending message log to extract properties.")

        field_updates, reply = extract_properties_from_gpt4(message, log, record_id, quote_id)

        merged_fields = fields.copy()
        merged_fields.update(field_updates)

        if field_updates.get("quote_stage") == "Quote Calculated" and message_lower not in pdf_keywords:
            try:
                quote_obj = calculate_quote(QuoteRequest(**merged_fields))
                field_updates.update(quote_obj.model_dump())
                summary = get_inline_quote_summary(quote_obj.model_dump())
                reply = summary + "\n\nWould you like me to send this quote to your email as a PDF?"
                log_debug_event(record_id, "BACKEND", "Quote Calculated", f"Total: ${field_updates.get('total_price')}, Time: {field_updates.get('estimated_time_mins')} mins")
            except Exception as e:
                logger.warning(f"⚠️ Quote calculation failed: {e}")
                log_debug_event(record_id, "BACKEND", "Quote Calculation Failed", str(e))

        update_quote_record(record_id, field_updates)
        append_message_log(record_id, reply, "brendan")

        next_actions = generate_next_actions() if field_updates.get("quote_stage") == "Quote Calculated" else []

        return JSONResponse(content={
            "properties": [{"property": k, "value": v} for k, v in field_updates.items()],
            "response": reply,
            "next_actions": next_actions,
            "session_id": session_id
        })

    except Exception as e:
        logger.exception("❌ Error in /filter-response route")
        log_debug_event(None, "BACKEND", "Route Error", str(e))
        raise HTTPException(status_code=500, detail="Internal server error.")
