import os
import json
import requests
import inflect
import openai
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from app.services.email_sender import handle_pdf_and_email

load_dotenv()
router = APIRouter()

openai.api_key = os.getenv("OPENAI_API_KEY")
AIRTABLE_API_KEY = os.getenv("AIRTABLE_API_KEY")
AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID")
TABLE_NAME = "Vacate Quotes"

inflector = inflect.engine()
import logging
import os
import json
import requests
import inflect
import openai
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from app.services.email_sender import handle_pdf_and_email

# Setup logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

load_dotenv()
router = APIRouter()

openai.api_key = os.getenv("OPENAI_API_KEY")
AIRTABLE_API_KEY = os.getenv("AIRTABLE_API_KEY")
AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID")
TABLE_NAME = "Vacate Quotes"

inflector = inflect.engine()

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
- Orca cleaning specialises in office cleaning, vacate cleaning, holiday home cleaning (airbnb), educational facility cleaning, retail cleaning and gym cleaning. 
- Remember: You only specialise in vacate cleaning, if customer asks for other types of cleaning you will ask them to visit website at orcacleaning.com.au or contact office.
- Our contact number is 1300 818838 and email is info@orcacleaning.com.au
- Your boss is Behzad Bagheri, managing director of ORCA cleaning, his direct number is 0431002469.
- We do provide a cleaning certificate for tenants to show their property managers.
- When customer asks specific questions about Orca Cleaning feel free to browse the websie to find the answer.

Just rmemeber, until end of June 2025 we have special offers for vacate cleaning: 
- 10% off for everyone who is applying for online quote
- 5% off on top of that for property managers

- Your job as quote assistant is to try to be as polite, and kind as possible and convince customer to finish the quote and book the cleaning.
- You will be acting very professionally like the best salesperson in the world,,, your convincing language is super important, your aim is to sell.
- You don't tollerate abusive customers
- The front end has already greeted the customer, DO NOT say "Hello", "G'day", "Hi" etc.
- If customer has a long pause, try to bring them back to conversation, you are a salersperson, you won't miss a single customer or let them change their mind and wake up away!
- Your job is to guide customers through a fast, legally-compliant quote for **vacate cleaning**, using a warm and respectful Aussie tone — like a top salesperson who knows their stuff but doesn’t pressure anyone.

## 🔰 PRIVACY + LEGAL

Brendan must respect the customer’s privacy at all times. Do **not** ask for personal info (name, phone, email) during quoting.

If the user asks about privacy, respond with:
> "No worries — we don’t collect personal info at this stage. You can read our Privacy Policy here: https://orcacleaning.com.au/privacy-policy"

## 🟢 START OF CHAT (message = "__init__")

When the message is "__init__", the frontend will show the greeting. You must NOT send a greeting.

Instead, jump straight into collecting info by asking **2–4 missing fields** in a single question. Always start with:

- suburb
- bedrooms_v2
- bathrooms_v2
- furnished

Your tone should still be warm, confident, and helpful — but skip introductions.

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
- Say: `"Thank you! I’ve got what I need to whip up your quote. Hang tight…" or something simillar.
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


## 🧼 CARPET RULES

Never ask yes/no for carpet. Ask how many rooms have carpet:

> “Roughly how many bedrooms, living areas, studies or stairs have carpet?”

Always populate the `carpet_*` fields individually.

✅ If any `carpet_*` field has a value > 0, also set:
```json
{ "property": "carpet_cleaning", "value": true }

"""

# --- Brendan Utilities ---
import uuid
from fastapi import HTTPException
import os
import openai

# --- Config ---
AIRTABLE_API_KEY = os.getenv("AIRTABLE_API_KEY")
AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID")
TABLE_NAME = "Vacate Quotes"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

client = openai.OpenAI(api_key=OPENAI_API_KEY)

BOOKING_URL_BASE = os.getenv("BOOKING_URL_BASE", "https://orcacleaning.com.au/schedule")

# ✅ Master Airtable Field List (used for validation)
VALID_AIRTABLE_FIELDS = {
    "quote_id", "timestamp", "source", "suburb", "bedrooms_v2", "bathrooms_v2",
    "window_cleaning", "window_count", "blind_cleaning", "furnished",
    "carpet_steam_clean", "oven_cleaning", "garage_cleaning", "extra_hours_requested",
    "special_requests", "quote_total", "quote_time_estimate", "hourly_rate", "gst_amount",
    "discount_percent", "discount_reason", "final_price", "customer_name", "email", "phone",
    "business_name", "property_address", "pdf_link", "booking_url", "quote_stage", "quote_notes",
    "message_log", "session_id", "privacy_acknowledged", "carpet_bedroom_count", 
    "carpet_mainroom_count", "carpet_study_count", "carpet_halway_count",
    "carpet_stairs_count", "carpet_other_count", "balcony_cleaning", "after_hours_cleaning",
    "weekend_cleaning", "is_property_manager", "real_estate_name", "carpet_cleaning",
    "special_request_minutes_min", "special_request_minutes_max", "upholstery_cleaning", 
    "deep_cleaning", "fridge_cleaning", "range_hood_cleaning", "wall_cleaning", "mandurah_property",
}

# 🔁 Field Normalisation Map
FIELD_MAP = {k: k for k in VALID_AIRTABLE_FIELDS}

# 🎯 Integer Fields — Always force to int
INTEGER_FIELDS = {
    "bedrooms_v2", "bathrooms_v2", "window_count",
    "carpet_bedroom_count", "carpet_mainroom_count", "carpet_study_count",
    "carpet_halway_count", "carpet_stairs_count", "carpet_other_count",
    "special_request_minutes_min", "special_request_minutes_max"
}

# ✅ Boolean Fields — Always force to True/False
BOOLEAN_FIELDS = {
    "oven_cleaning", "window_cleaning", "blind_cleaning", "garage_cleaning",
    "deep_cleaning", "fridge_cleaning", "range_hood_cleaning",
    "wall_cleaning", "mandurah_property", "carpet_cleaning"
}

BOOKING_URL_BASE = os.getenv("BOOKING_URL_BASE", "https://orcacleaning.com.au/schedule")

# Functions remain unchanged except for the improvements above


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
        return existing  # Already correct tuple (quote_id, record_id, stage, fields)

    if force_new:
        print("🔁 Force creating new quote despite duplicate session ID.")
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

    return quote_id, record_id, "Gathering Info", {"quote_stage": "Gathering Info", "message_log": ""}


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

    # Handling multiple records for the same session_id
    if len(res.get("records", [])) > 1:
        print(f"🚨 MULTIPLE QUOTES found for session_id: {session_id}")
        for r in res["records"]:
            print(f"   → ID: {r['id']} | Quote ID: {r['fields'].get('quote_id')}")
    
    # Fetch the latest record and return it
    if res.get("records"):
        record = res["records"][0]  # This ensures only the most recent record is used
        quote_id = record["fields"].get("quote_id")
        record_id = record["id"]
        stage = record["fields"].get("quote_stage", "Gathering Info")
        fields = record["fields"]
        return quote_id, record_id, stage, fields

    return None

def update_quote_record(record_id: str, fields: dict):
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{TABLE_NAME}/{record_id}"
    headers = {
        "Authorization": f"Bearer {AIRTABLE_API_KEY}",
        "Content-Type": "application/json"
    }

    # Normalize dropdown: furnished
    if "furnished" in fields:
        val = str(fields["furnished"]).strip().lower()
        if "unfurnished" in val:
            fields["furnished"] = "Unfurnished"
        elif "furnished" in val:
            fields["furnished"] = "Furnished"

    normalized_fields = {}

    for key, value in fields.items():
        mapped_key = FIELD_MAP.get(key, key)

        if mapped_key not in VALID_AIRTABLE_FIELDS:
            print(f"🔕 Skipping unmapped field: {key} → {mapped_key}")
            continue

        if isinstance(value, str):
            value = value.strip()

        if mapped_key in BOOLEAN_FIELDS:
            if str(value).lower() in ["yes", "true", "1"]:
                value = True
            elif str(value).lower() in ["no", "false", "0"]:
                value = False

        if mapped_key in INTEGER_FIELDS:
            try:
                value = int(value)
            except:
                value = 0

        # Special Request Merging Logic
        if mapped_key == "special_requests":
            old = normalized_fields.get("special_requests", "")
            if old and value:
                value = f"{old}\n{value}".strip()

        if mapped_key == "special_request_minutes_min":
            old = normalized_fields.get("special_request_minutes_min", 0)
            try:
                value = int(value) + int(old)
            except:
                value = int(value) if value else 0

        if mapped_key == "special_request_minutes_max":
            old = normalized_fields.get("special_request_minutes_max", 0)
            try:
                value = int(value) + int(old)
            except:
                value = int(value) if value else 0

        normalized_fields[mapped_key] = value

    if not normalized_fields:
        print(f"⏩ No valid fields to update for record {record_id}. Skipping Airtable update.")
        return []

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

    message = str(message).strip()
    if not message:
        print("⏩ Empty message after stripping — skipping log update")
        return

    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{TABLE_NAME}/{record_id}"
    headers = {"Authorization": f"Bearer {AIRTABLE_API_KEY}"}

    res = requests.get(url, headers=headers)
    if not res.ok:
        print(f"❌ Failed to fetch existing log from Airtable: {res.status_code}")
        return

    current = res.json()
    old_log = current.get("fields", {}).get("message_log", "")

    # Ensure that the log does not exceed a reasonable size
    max_log_length = 10000  # Max characters for message log
    new_log = f"{old_log}\n{sender.upper()}: {message}".strip()

    # Truncate if the log exceeds the max size
    if len(new_log) > max_log_length:
        new_log = new_log[-max_log_length:]

    # Update the record with the new log
    update_quote_record(record_id, {"message_log": new_log})
    print(f"✅ Appended message to log for record {record_id}")

import smtplib
from email.mime.text import MIMEText
from time import sleep

def send_gpt_error_email(error_msg: str):
    try:
        msg = MIMEText(error_msg)
        msg["Subject"] = "🚨 Brendan GPT Extraction Error"
        msg["From"] = "info@orcacleaning.com.au"
        msg["To"] = "admin@orcacleaning.com.au"

        # Fetch SMTP password from environment variables
        smtp_pass = os.getenv("SMTP_PASS")

        if not smtp_pass:
            print("❌ SMTP password is missing in environment variables.")
            return

        # Use SMTP server to send the email
        with smtplib.SMTP("smtp.office365.com", 587) as server:
            server.starttls()
            server.login("info@orcacleaning.com.au", smtp_pass)
            server.sendmail(
                from_addr=msg["From"],
                to_addrs=[msg["To"]],
                msg=msg.as_string()
            )

        print("✅ GPT error email sent successfully.")

    except smtplib.SMTPException as e:
        print(f"⚠️ SMTP error occurred while sending the email: {e}")
        sleep(5)  # Simple retry mechanism
        send_gpt_error_email(error_msg)  # Retry email sending

    except Exception as e:
        print(f"⚠️ Could not send GPT error alert: {e}")

def extract_properties_from_gpt4(message: str, log: str, record_id: str = None, quote_id: str = None):
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

        # Check if 'choices' exists and is not empty
        if not response.choices or len(response.choices) == 0:
            raise ValueError("No choices returned from GPT-4 response.")

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

                if key == "quote_stage" and current_stage in [
                    "Quote Calculated", "Gathering Personal Info",
                    "Personal Info Received", "Booking Confirmed", "Referred to Office"
                ]:
                    continue

                if key in ["special_requests", "special_request_minutes_min", "special_request_minutes_max"]:
                    if current_stage not in ["Gathering Info"] and (value in ["", None, 0, False]):
                        continue

                if isinstance(value, str):
                    value = value.strip()

                # Special Request Merging Logic
                if key == "special_requests":
                    old = existing.get("special_requests", "")
                    if old and value:
                        value = f"{old}\n{value}".strip()

                if key == "special_request_minutes_min":
                    old = existing.get("special_request_minutes_min", 0)
                    try:
                        value = int(value) + int(old)
                    except:
                        value = int(value) if value else 0

                if key == "special_request_minutes_max":
                    old = existing.get("special_request_minutes_max", 0)
                    try:
                        value = int(value) + int(old)
                    except:
                        value = int(value) if value else 0

                field_updates[key] = value

        if current_stage == "Gathering Info" and "quote_stage" not in field_updates:
            field_updates["quote_stage"] = "Gathering Info"

        carpet_fields = [
            "carpet_bedroom_count", "carpet_mainroom_count",
            "carpet_study_count", "carpet_halway_count",
            "carpet_stairs_count", "carpet_other_count"
        ]
        if any(field_updates.get(f, existing.get(f, 0)) > 0 for f in carpet_fields):
            field_updates["carpet_cleaning"] = True

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

def handle_pdf_and_email(record_id: str, quote_id: str, fields: dict):
    from app.services.pdf_generator import generate_pdf
    from app.services.email_sender import send_quote_email

    # Generate PDF
    print(f"📄 Generating PDF for Quote ID: {quote_id}")
    pdf_url = generate_pdf(quote_id, fields)

    # Generate Booking URL
    booking_url = f"{BOOKING_URL_BASE}?quote_id={quote_id}"

    # Send Email
    print(f"📧 Sending Quote Email to: {fields.get('email')}")
    send_quote_email(
        to_email=fields.get("email"),
        customer_name=fields.get("customer_name", "Customer"),
        quote_id=quote_id,
        pdf_url=pdf_url,
        booking_url=booking_url
    )

    # Update Airtable
    print(f"📤 Updating Airtable Record with PDF + Booking URL")
    update_quote_record(record_id, {
        "pdf_link": pdf_url,
        "booking_url": booking_url
    })

    print(f"✅ PDF generated and email sent for {quote_id}")


import logging
import os
import json
import requests
import inflect
import openai
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from app.services.email_sender import handle_pdf_and_email

# Setup logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

load_dotenv()
router = APIRouter()

openai.api_key = os.getenv("OPENAI_API_KEY")
AIRTABLE_API_KEY = os.getenv("AIRTABLE_API_KEY")
AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID")
TABLE_NAME = "Vacate Quotes"

inflector = inflect.engine()

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

... [rest of the GPT_PROMPT] ...
"""

# --- Brendan Utilities ---
import uuid
from fastapi import HTTPException
import os
import openai

# --- Config ---
AIRTABLE_API_KEY = os.getenv("AIRTABLE_API_KEY")
AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID")
TABLE_NAME = "Vacate Quotes"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

client = openai.OpenAI(api_key=OPENAI_API_KEY)

BOOKING_URL_BASE = os.getenv("BOOKING_URL_BASE", "https://orcacleaning.com.au/schedule")

# ✅ Master Airtable Field List (used for validation)
VALID_AIRTABLE_FIELDS = { ... }

# --- Functions ---
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
    logger.info(f"🚨 Checking for existing session: {session_id}")

    existing = get_quote_by_session(session_id)
    if existing and not force_new:
        logger.warning("⚠️ Duplicate session detected. Returning existing quote.")
        return existing  # Already correct tuple (quote_id, record_id, stage, fields)

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
            "quote_stage": "Gathering Info"
        }
    }
    res = requests.post(url, headers=headers, json=data)
    if not res.ok:
        logger.error(f"❌ FAILED to create quote: {res.status_code} - {res.text}")
        raise HTTPException(status_code=500, detail="Failed to create Airtable record.")

    record_id = res.json().get("id")
    logger.info(f"✅ Created new quote record: {record_id} with ID {quote_id}")

    append_message_log(record_id, "SYSTEM_TRIGGER: Brendan started a new quote", "system")

    return quote_id, record_id, "Gathering Info", {"quote_stage": "Gathering Info", "message_log": ""}


def update_quote_record(record_id: str, fields: dict):
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{TABLE_NAME}/{record_id}"
    headers = {
        "Authorization": f"Bearer {AIRTABLE_API_KEY}",
        "Content-Type": "application/json"
    }

    logger.info(f"📤 Updating Airtable Record: {record_id}")
    res = requests.patch(url, headers=headers, json={"fields": fields})

    if res.ok:
        logger.info(f"✅ Airtable updated successfully for record {record_id}.")
    else:
        logger.error(f"❌ Airtable update failed: {res.status_code} - {res.text}")
        try:
            logger.error(f"🧾 Error message: {json.dumps(res.json(), indent=2)}")
        except Exception as e:
            logger.warning(f"⚠️ Could not decode Airtable error: {str(e)}")


def append_message_log(record_id: str, message: str, sender: str):
    if not record_id:
        logger.error("❌ Cannot append log — missing record ID")
        return

    message = str(message).strip()
    if not message:
        logger.warning("⏩ Empty message after stripping — skipping log update")
        return

    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{TABLE_NAME}/{record_id}"
    headers = {"Authorization": f"Bearer {AIRTABLE_API_KEY}"}

    res = requests.get(url, headers=headers)
    if not res.ok:
        logger.error(f"❌ Failed to fetch existing log from Airtable: {res.status_code}")
        return

    current = res.json()
    old_log = current.get("fields", {}).get("message_log", "")

    # Ensure that the log does not exceed a reasonable size
    max_log_length = 10000  # Max characters for message log
    new_log = f"{old_log}\n{sender.upper()}: {message}".strip()

    # Truncate if the log exceeds the max size
    if len(new_log) > max_log_length:
        new_log = new_log[-max_log_length:]

    # Update the record with the new log
    update_quote_record(record_id, {"message_log": new_log})
    logger.info(f"✅ Appended message to log for record {record_id}")


def send_gpt_error_email(error_msg: str):
    try:
        msg = MIMEText(error_msg)
        msg["Subject"] = "🚨 Brendan GPT Extraction Error"
        msg["From"] = "info@orcacleaning.com.au"
        msg["To"] = "admin@orcacleaning.com.au"

        # Fetch SMTP password from environment variables
        smtp_pass = os.getenv("SMTP_PASS")

        if not smtp_pass:
            logger.error("❌ SMTP password is missing in environment variables.")
            return

        # Use SMTP server to send the email
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
        sleep(5)  # Simple retry mechanism
        send_gpt_error_email(error_msg)  # Retry email sending

    except Exception as e:
        logger.error(f"⚠️ Could not send GPT error alert: {e}")


# --- Route ---
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from app.services.quote_logic import QuoteRequest, calculate_quote


router = APIRouter()

@router.post("/filter-response")
async def filter_response_entry(request: Request):
    try:
        body = await request.json()
        message = body.get("message", "").strip()
        session_id = body.get("session_id")

        if not session_id:
            raise HTTPException(status_code=400, detail="Session ID is required.")

        # --- __init__ : Start a New Quote ---
        if message.lower() == "__init__":
            existing = get_quote_by_session(session_id)
            if existing:
                quote_id, record_id, stage, fields = existing["quote_id"], existing["record_id"], existing["stage"], existing["fields"]
            else:
                quote_id, record_id, fields = create_new_quote(session_id, force_new=True)

            intro = "What needs cleaning today — bedrooms, bathrooms, oven, carpets, anything else?"
            append_message_log(record_id, message, "user")
            append_message_log(record_id, intro, "brendan")

            return JSONResponse(content={
                "properties": [],
                "response": intro,
                "next_actions": [],
                "session_id": session_id
            })

        # --- Retrieve Existing Quote ---
        quote_data = get_quote_by_session(session_id)
        if not quote_data:
            raise HTTPException(status_code=404, detail="Session expired or not initialized.")

        quote_id, record_id, stage, fields = quote_data["quote_id"], quote_data["record_id"], quote_data["stage"], quote_data["fields"]
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

        # --- Handle Abuse Escalation ---
        if props_dict.get("quote_stage") in ["Abuse Warning", "Chat Banned"]:
            logger.info(f"📤 Updating Airtable Record for Abuse Escalation: {json.dumps(props_dict, indent=2)}")
            update_quote_record(record_id, props_dict)
            append_message_log(record_id, message, "user")
            append_message_log(record_id, reply, "brendan")

            return JSONResponse(content={
                "properties": list(props_dict.keys()),
                "response": reply,
                "next_actions": [],
                "session_id": session_id
            })

        # --- Stage: Quote Calculated (Ask for Name, Email, Phone) ---
        if stage == "Quote Calculated":
            reply = "Awesome — to send your quote over, can I grab your name, email and best contact number?"
            logger.info(f"📤 Updating Airtable Record to Gathering Personal Info: {{'quote_stage': 'Gathering Personal Info'}}")
            update_quote_record(record_id, {"quote_stage": "Gathering Personal Info"})
            append_message_log(record_id, message, "user")
            append_message_log(record_id, reply, "brendan")

            return JSONResponse(content={
                "properties": [],
                "response": reply,
                "next_actions": [],
                "session_id": session_id
            })

        # --- Stage: Gathering Info ---
        if stage == "Gathering Info":
            if props_dict:
                reply = reply.replace("123456", quote_id).replace("{{quote_id}}", quote_id)

            merged = fields.copy()
            merged.update(props_dict)

            required_fields = [
                "suburb", "bedrooms_v2", "bathrooms_v2", "furnished",
                "oven_cleaning", "window_cleaning", "window_count", "blind_cleaning",
                "carpet_bedroom_count", "carpet_mainroom_count", "carpet_study_count", "carpet_halway_count",
                "carpet_stairs_count", "carpet_other_count", "deep_cleaning", "fridge_cleaning",
                "range_hood_cleaning", "wall_cleaning", "balcony_cleaning", "garage_cleaning",
                "upholstery_cleaning", "after_hours_cleaning", "weekend_cleaning", "mandurah_property",
                "is_property_manager", "special_requests", "special_request_minutes_min", "special_request_minutes_max"
            ]

            filled = [f for f in required_fields if merged.get(f) not in [None, "", False] or f == "special_requests"]

            # --- If All Required Fields Filled → Calculate Quote ---
            if len(filled) >= 28:
                logger.info(f"📤 Updating Airtable Record to Quote Calculated: {json.dumps({**props_dict, 'quote_stage': 'Quote Calculated'}, indent=2)}")
                update_quote_record(record_id, {**props_dict, "quote_stage": "Quote Calculated"})

                quote_request = QuoteRequest(**merged)
                quote_response = calculate_quote(quote_request)

                logger.info(f"📤 Updating Airtable Record with Quote Details: {json.dumps(quote_response.dict(), indent=2)}")
                update_quote_record(record_id, {
                    "quote_total": quote_response.total_price,
                    "quote_time_estimate": quote_response.estimated_time_mins,
                    "hourly_rate": quote_response.base_hourly_rate,
                    "discount_percent": quote_response.discount_applied,
                    "gst_amount": quote_response.gst_applied,
                    "final_price": quote_response.total_price
                })

                summary = get_inline_quote_summary(quote_response.dict())
                reply = f"Thank you! I’ve got what I need to whip up your quote. Hang tight…\n\n{summary}"

                append_message_log(record_id, message, "user")
                append_message_log(record_id, reply, "brendan")

                return JSONResponse(content={
                    "properties": list(props_dict.keys()),
                    "response": reply,
                    "next_actions": generate_next_actions(),
                    "session_id": session_id
                })

            logger.info(f"📤 Updating Airtable Record while Gathering Info: {json.dumps(props_dict, indent=2)}")
            update_quote_record(record_id, props_dict)

            return JSONResponse(content={
                "properties": list(props_dict.keys()),
                "response": reply,
                "next_actions": [],
                "session_id": session_id
            })

        logger.warning(f"🚫 Cannot update — quote_stage is '{stage}'")
        return JSONResponse(content={
            "properties": [],
            "response": "That quote's already been calculated. You’ll need to start a new one if anything’s changed.",
            "next_actions": [],
            "session_id": session_id
        })

    except Exception as e:
        logger.error(f"🔥 UNEXPECTED ERROR: {e}")
        return JSONResponse(status_code=500, content={"error": "Server issue. Try again in a moment."})
