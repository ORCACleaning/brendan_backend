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

1. Extract EVERY possible field mentioned by customer.
2. NEVER skip fields if customer has already provided that info.
3. NEVER assume or summarise — extract explicitly what was said.
4. Field extraction is your #1 priority. Your reply comes second.
5. Brendan must NEVER re-show quote summary once quote is calculated — unless customer changes details.

---

## CONTEXT AWARENESS RULES:

You will always be given the full conversation log so far.

- Look for lines like:  
> "BRENDAN: Looks like a big job! Here's your quote:"  
This means the quote has already been calculated.

- If customer asks for PDF or says things like "pdf please", "send quote", "email it to me":  
→ Do NOT regenerate the quote summary.  
→ Instead, say:  
> "Sure thing — I’ll just grab your name, email and phone number so I can send that through."

- Only ask for personal info after quote is calculated.

---

## YOUR JOB:

You are **Brendan**, the quoting officer at **Orca Cleaning**, based in **Western Australia**.

- We ONLY specialise in vacate cleaning for this chat.  
If customer asks for other services:  
> "We specialise in vacate cleaning here — but check out orcacleaning.com.au or call our office on 1300 918 388 for other services."

- We provide cleaning certificates for tenants.

- Glass roller doors count as 3 windows each — always let customer know.

---

## CURRENT DISCOUNTS (Valid Until May 31, 2025)

- 10% Off for all vacate cleans  
- Extra 5% Off if booked by a **property manager**

---

## PRIVACY RULES

Before asking for name/email/phone — always say:  
> "Just so you know — we don’t ask for anything private like bank info. Only your name, email and phone so we can send the quote over. Your privacy is 100% respected."

If customer asks about privacy:  
> "No worries — we don’t collect personal info at this stage. You can read our Privacy Policy here: https://orcacleaning.com.au/privacy-policy"

---

## START OF CHAT ("__init__")

- Skip greeting, front end has already said hello.
- Ask for suburb, bedrooms_v2, bathrooms_v2, furnished.
- Always ask 2–4 missing fields per message.
- Be warm, professional, straight to the point.

---

## REQUIRED FIELDS (Must Collect All 27)

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
24. is_property_manager → if true, ask for real_estate_name & number_of_sessions  
25. special_requests  
26. special_request_minutes_min  
27. special_request_minutes_max  

---

## RULES FOR FURNISHED VALUE

- Only accept "Furnished" or "Unfurnished".  
- If customer says "semi-furnished" — ask:  
> "Are there any beds, couches, wardrobes, or full cabinets still in the home?"  
- If only appliances are left → treat as "Unfurnished".

Do NOT skip blind cleaning — even if unfurnished.

---

## RULES FOR CARPET CLEANING

- Never ask yes/no for carpet.  
- Ask:  
> "Roughly how many bedrooms, living areas, studies or stairs have carpet?"  
- Always populate carpet_* fields individually.

If any carpet_* field > 0:  
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
    "customer_name", "customer_email", "customer_phone", "real_estate_name", "property_address", "number_of_sessions",

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
    "special_request_minutes_min", "special_request_minutes_max",
    "number_of_sessions"
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

    # === Normalize + Validate + Map Fields ===
    for raw_key, value in fields.items():
        key = FIELD_MAP.get(raw_key, raw_key)

        if key not in VALID_AIRTABLE_FIELDS:
            logger.warning(f"⚠️ Skipping unknown Airtable field: {key}")
            continue

        # === Boolean Fields ===
        if key in BOOLEAN_FIELDS:
            if isinstance(value, bool):
                pass
            elif value in [None, ""]:
                value = False
            else:
                value = str(value).strip().lower() in {"true", "1", "yes"}

        # === Integer Fields ===
        elif key in INTEGER_FIELDS:
            try:
                value = int(value)
                if value > MAX_REASONABLE_INT:
                    logger.warning(f"⚠️ Clamping large value for {key}: {value}")
                    value = MAX_REASONABLE_INT
            except Exception:
                logger.warning(f"⚠️ Failed to convert {key} to int — forcing 0")
                value = 0

        # === Float Fields ===
        elif key in {
            "gst_applied", "total_price", "base_hourly_rate",
            "price_per_session", "estimated_time_mins", "discount_applied",
            "mandurah_surcharge", "after_hours_surcharge", "weekend_surcharge"
        }:
            try:
                value = float(value)
            except Exception:
                value = 0.0

        # === Special Request Normalization ===
        elif key == "special_requests":
            if not value or str(value).strip().lower() in {
                "no", "none", "false", "no special requests", "n/a"
            }:
                value = ""

        # === Extra Hours Requested Normalization ===
        elif key == "extra_hours_requested":
            if value in [None, ""]:
                value = 0
            else:
                try:
                    value = float(value)
                except Exception:
                    value = 0

        # === String Fallback ===
        else:
            value = "" if value is None else str(value).strip()

        normalized_fields[key] = value

    # === Force Privacy Field as Boolean ===
    if "privacy_acknowledged" in fields:
        normalized_fields["privacy_acknowledged"] = bool(fields.get("privacy_acknowledged"))

    if not normalized_fields:
        logger.info(f"⏩ No valid fields to update for record {record_id}")
        return []

    logger.info(f"\n📤 Updating Airtable Record: {record_id}")
    logger.info(f"🛠 Payload: {json.dumps(normalized_fields, indent=2)}")

    # === Final Sanity Check ===
    for key in list(normalized_fields.keys()):
        if key not in VALID_AIRTABLE_FIELDS:
            logger.error(f"❌ INVALID FIELD DETECTED: {key} — Removing from payload.")
            normalized_fields.pop(key, None)

    # === Bulk Update First ===
    res = requests.patch(url, headers=headers, json={"fields": normalized_fields})
    if res.ok:
        logger.info("✅ Airtable bulk update success.")
        return list(normalized_fields.keys())

    logger.error(f"❌ Airtable bulk update failed: {res.status_code}")
    try:
        logger.error(f"🧾 Error response: {res.json()}")
    except Exception:
        logger.error("🧾 Error response: (Non-JSON)")

    # === Fallback to Single Field Updates ===
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
    is_property_manager = str(data.get("is_property_manager", "") or "").lower() in TRUE_VALUES

    # Calculate hours and cleaners (max 5 hours per cleaner)
    hours = time_est_mins / 60
    cleaners = max(1, (time_est_mins + 299) // 300)
    hours_per_cleaner = hours / cleaners
    hours_per_cleaner_rounded = int(hours_per_cleaner) if hours_per_cleaner.is_integer() else round(hours_per_cleaner + 0.49)

    # Opening based on price / time
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

    # Discount
    if discount > 0:
        if is_property_manager and discount >= price / 1.1 * 0.15:
            summary += f"🏷️ Discount Applied: ${discount:.2f} — 10% Vacate Clean Special (+5% Property Manager Bonus)\n"
        else:
            summary += f"🏷️ Discount Applied: ${discount:.2f} — 10% Vacate Clean Special\n"

    # Cleaning Options
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
        if str(data.get(field, "")).lower() in TRUE_VALUES:
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

    return summary.strip()

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
                "What would you like to do next?\n\n"
                "I can generate a formal PDF quote, send it straight to your email, "
                "or we can tweak the quote if you'd like to change anything.\n\n"
                "If you'd rather have a chat with our office, you can call us on "
                "**1300 918 388** — just mention your quote ID and they'll look after you."
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
                {"role": "user", "content": log[-LOG_TRUNCATE_LENGTH:]}
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

        # === Load Existing Airtable Fields ===
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

        # === GPT Reply Suppression for PDF Requests ===
        if current_stage == "Quote Calculated" and any(x in message.lower() for x in PDF_KEYWORDS):
            reply = "Sure thing — I’ll just grab your name, email and phone number so I can send that through."
            return field_updates, reply

        for p in props:
            if not isinstance(p, dict) or "property" not in p or "value" not in p:
                continue

            key, value = p["property"], p["value"]

            if key in BOOLEAN_FIELDS:
                value = str(value).strip().lower() in TRUE_VALUES

            elif key in INTEGER_FIELDS:
                try:
                    value = int(value)
                except:
                    value = 0

            elif key == "special_requests":
                if not value or str(value).strip().lower() in {"no", "none", "false", "n/a"}:
                    value = ""
                else:
                    new_value = str(value).strip()
                    old = existing.get("special_requests", "").strip()
                    if old and new_value.lower() not in old.lower():
                        value = f"{old}\n{new_value}".strip()
                    elif not old:
                        value = new_value
                    else:
                        value = old

            if key == "quote_stage" and current_stage in {
                "Gathering Personal Info", "Personal Info Received", "Booking Confirmed", "Referred to Office"
            }:
                continue

            field_updates[key] = value
            logger.warning(f"🚨 Updating Field: {key} = {value}")

        # Always set source
        field_updates["source"] = "Brendan"

        # Auto-property manager detection
        if "i am a property manager" in message.lower() or "i’m a property manager" in message.lower():
            field_updates["is_property_manager"] = True

        # Ask for session count if missing
        if (field_updates.get("is_property_manager") or existing.get("is_property_manager")) and not (
            field_updates.get("number_of_sessions") or existing.get("number_of_sessions")
        ):
            reply = (
                "No worries! How many sessions would you like to book for this property? "
                "Let me know if it's just 1 or more."
            )
            field_updates["number_of_sessions"] = 1
            return field_updates, reply

        # Fill missing fields with safe defaults
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

        # Auto-estimate for special requests
        if field_updates.get("special_requests") and not field_updates.get("special_request_minutes_min"):
            field_updates["special_request_minutes_min"] = 30
            field_updates["special_request_minutes_max"] = 60

        # Auto-check carpet_cleaning
        if any(int(field_updates.get(f, existing.get(f, 0) or 0)) > 0 for f in [
            "carpet_bedroom_count", "carpet_mainroom_count", "carpet_study_count",
            "carpet_halway_count", "carpet_stairs_count", "carpet_other_count"
        ]):
            field_updates["carpet_cleaning"] = True

        # Float normalization
        for f in ["after_hours_surcharge", "weekend_surcharge", "mandurah_surcharge"]:
            if f in field_updates:
                try:
                    field_updates[f] = float(field_updates[f])
                except:
                    field_updates[f] = 0.0

        # Required Fields Check
        required = [
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
        for f in required:
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

        # Abuse check
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
            "privacy_acknowledged": False  # Force privacy ack to False
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
        "session_id": session_id,
        "privacy_acknowledged": False  # Return in local cache too
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
    Appends a new message to the message_log field in Airtable.
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
            logger.warning(f"⚠️ Airtable fetch failed (attempt {attempt + 1}/3): {e}")
            if attempt == 2:
                logger.error(f"❌ Failed to fetch message log for record {record_id} after 3 attempts.")
                return
            sleep(1)

    old_log = str(current.get("fields", {}).get("message_log", "")).strip()
    combined_log = f"{old_log}\n{new_entry}".strip() if old_log else new_entry

    # === Truncate if Exceeds MAX_LOG_LENGTH ===
    if len(combined_log) > MAX_LOG_LENGTH:
        combined_log = combined_log[-MAX_LOG_LENGTH:]

    logger.info(f"📚 Appending to message log for record {record_id}")
    logger.debug(f"📝 New message_log length: {len(combined_log)} characters")

    update_quote_record(record_id, {"message_log": combined_log})


# === Brendan Filter Response Route ===

@router.post("/filter-response")
async def filter_response_entry(request: Request):
    try:
        body = await request.json()
        message = str(body.get("message", "")).strip()
        session_id = str(body.get("session_id", "")).strip()

        if not session_id:
            raise HTTPException(status_code=400, detail="Session ID is required.")

        # === Initialisation Handling ===
        if message.lower() == "__init__":
            existing = get_quote_by_session(session_id)
            if existing:
                quote_id, record_id, stage, fields = existing
            else:
                quote_id, record_id, stage, fields = create_new_quote(session_id, force_new=True)
                session_id = fields.get("session_id", session_id)

            reply = "What needs cleaning today — bedrooms, bathrooms, oven, carpets, anything else?"
            append_message_log(record_id, message, "user")
            append_message_log(record_id, reply, "brendan")

            return JSONResponse(content={
                "properties": [],
                "response": reply,
                "next_actions": [],
                "session_id": session_id
            })

        # === Load Quote Record ===
        quote_id, record_id, stage, fields = get_quote_by_session(session_id)
        if not record_id:
            raise HTTPException(status_code=404, detail="Quote not found.")

        message_lower = message.lower()
        pdf_keywords = ["pdf please", "send pdf", "get pdf", "send quote", "email it to me", "email quote", "pdf quote"]

        # === Stage: Chat Banned ===
        if stage == "Chat Banned":
            reply = "This chat is closed due to prior messages. Please call 1300 918 388 if you still need a quote."
            return JSONResponse(content={
                "properties": [],
                "response": reply,
                "next_actions": [],
                "session_id": session_id
            })

        # === Stage: Gathering Personal Info | Privacy Check ===
        if stage == "Gathering Personal Info" and not fields.get("privacy_acknowledged", False):
            if message_lower in ["yes", "yep", "sure", "ok", "okay", "yes please", "go ahead"]:
                update_quote_record(record_id, {"privacy_acknowledged": True})
                fields = get_quote_by_session(session_id)[3]
                reply = "Great! Could you please provide your name, email, and phone number so I can send the PDF quote?"
            else:
                reply = (
                    "No problem — we only need your name, email, and phone number to send the quote. "
                    "Let me know if you'd like to continue or if you have any questions about our privacy policy."
                )

            append_message_log(record_id, message, "user")
            append_message_log(record_id, reply, "brendan")
            return JSONResponse(content={
                "properties": [],
                "response": reply,
                "next_actions": [],
                "session_id": session_id
            })

        # === Stage: Gathering Personal Info | Final Step — PDF and Email ===
        if stage == "Gathering Personal Info" and fields.get("privacy_acknowledged", False):
            if all([fields.get("customer_name"), fields.get("customer_email"), fields.get("customer_phone")]):
                import re
                customer_email = str(fields.get("customer_email", "")).strip()
                if not re.match(r"[^@]+@[^@]+\.[^@]+", customer_email):
                    reply = "That email doesn’t look right — could you double check and send it again?"
                    append_message_log(record_id, message, "user")
                    append_message_log(record_id, reply, "brendan")
                    return JSONResponse(content={
                        "properties": [],
                        "response": reply,
                        "next_actions": [],
                        "session_id": session_id
                    })

                update_quote_record(record_id, {"quote_stage": "Personal Info Received"})
                fields = get_quote_by_session(session_id)[3]

                try:
                    pdf_path = generate_quote_pdf(fields)
                    if not pdf_path:
                        raise Exception("PDF generation failed")

                    send_quote_email(
                        to_email=customer_email,
                        customer_name=fields.get("customer_name"),
                        pdf_path=pdf_path,
                        quote_id=quote_id
                    )

                    update_quote_record(record_id, {"pdf_link": pdf_path})
                    reply = "Thanks so much — I’ve sent your quote through to your email! Let me know if there’s anything else I can help with."

                except Exception as e:
                    logger.exception(f"❌ PDF Generation/Email Sending Failed: {e}")
                    reply = "Sorry — I ran into an issue while generating your PDF quote. Please call our office on 1300 918 388 and we’ll sort it out for you."

                append_message_log(record_id, message, "user")
                append_message_log(record_id, reply, "brendan")
                return JSONResponse(content={
                    "properties": [],
                    "response": reply,
                    "next_actions": [],
                    "session_id": session_id
                })

        # === Prepare Log for GPT ===
        log = fields.get("message_log", "")
        if stage == "Quote Calculated" and any(k in message_lower for k in pdf_keywords):
            log = PDF_SYSTEM_MESSAGE + "\n\n" + log[-LOG_TRUNCATE_LENGTH:]
        else:
            log = log[-LOG_TRUNCATE_LENGTH:]

        # === Default GPT Extraction & Quote Recalc ===
        append_message_log(record_id, message, "user")
        field_updates, reply = extract_properties_from_gpt4(message, log, record_id, quote_id)

        merged_fields = fields.copy()
        merged_fields.update(field_updates)

        if field_updates.get("quote_stage") == "Quote Calculated" and message_lower not in pdf_keywords:
            try:
                quote_obj = calculate_quote(QuoteRequest(**merged_fields))
                field_updates.update(quote_obj.model_dump())
                summary = get_inline_quote_summary(quote_obj.model_dump())
                reply = summary + "\n\nWould you like me to send this quote to your email as a PDF?"
            except Exception as e:
                logger.warning(f"⚠️ Quote calculation failed: {e}")

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
        raise HTTPException(status_code=500, detail="Internal server error.")

