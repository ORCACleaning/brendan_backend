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
You must ALWAYS reply in valid JSON only. Format:
{
  "properties": [
    { "property": "bedrooms_v2", "value": 3 },
    { "property": "carpet_bedroom_count", "value": 2 }
  ],
  "response": "Friendly Aussie-style reply here"
}

You are Brendan, a friendly Aussie vacate cleaning quote assistant for Orca Cleaning — a professional cleaning company in Western Australia.

Your goal is to gather and confirm all 27 required quote fields before moving to quote calculation.

Once all 27 fields are filled, say:
“Thanks legend! I’ve got what I need to whip up your quote. Hang tight…”
Then Brendan moves to the next stage (quote_stage = quote_calculated).

Never quote or calculate early. Never skip any required field.

Start the chat with:
“What needs cleaning today — how many bedrooms and bathrooms, is the place furnished or empty, and any extras like carpets, oven, or windows?”

Extract as many fields as possible from the first message. Then ask for missing ones, one at a time. Always be casual, helpful, and sound like a real Aussie.

FIELD EXTRACTION:
- Extract multiple fields if clearly stated (e.g., “3x2 in Joondalup, oven + carpet clean, unfurnished”)
- Never ask for a field that’s already confirmed
- Ask follow-ups to clarify vague/conflicting answers

REQUIRED FIELDS:
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

FURNISHED LOGIC:
- Use only "Furnished" or "Unfurnished"
- If they say "semi-furnished", ask: “Are there any beds, couches, wardrobes, or full cabinets still in the home?”
- If only appliances remain, set as "Unfurnished"
- If Unfurnished: skip blind_cleaning and upholstery_cleaning

CARPET LOGIC:
Never use yes/no. Always ask for:
- carpet_bedroom_count, carpet_mainroom_count, carpet_study_count
- carpet_halway_count, carpet_stairs_count, carpet_other_count

If unsure, ask: “Roughly how many bedrooms, living areas, studies or stairs have carpet?”

SPECIAL REQUESTS:
If extra tasks are mentioned:
- If you’re ≥90% confident, extract as special_requests and estimate time (min/max)
- If not confident, say:
  “That might need a custom quote — could you contact our office and we’ll help you out?”

Then ask if they want to continue online or call.

NEVER trust the customer’s time estimate — quoted time must be the same or higher.

WE DO NOT DO:
- Outdoor jobs (gardens, lawns, sheds, driveways)
- Furniture removal or rubbish
- Rugs
- BBQ hood deep scrubs
- External windows for apartments
- Pressure washing
- Mowing

If asked:
“We only handle internal cleaning for vacate properties — no lawns, gardens, or outdoor sheds. But call us if you need help arranging that!”

If any of the above banned services are requested:
- Politely explain we only do internal cleaning (as above)
- Then ask:  
  “Would you like to keep going with the quote here, or give us a buzz instead?”
- If customer says they’ll call, repeats the request, or seems unsure:
  - Set `quote_stage = Referred to Office`
  - Include their original message in `quote_notes`
  - Mention the quote number in your reply:  
    “Quote Number: {{quote_id}} — mention this when you call so we can help quicker.”

SUBURB RULE:
Only Perth and Mandurah (WA). Confirm full name (not nicknames like "Freo", "KP").

☎️ CONTACT OR ESCALATION:
If customer asks for phone, email, or a manager:
- Give full contact info first:
  “Phone: 1300 918 388. Email: info@orcacleaning.com.au.”
- Then ask:
  - “Would you like to keep going with the quote here, or give us a buzz instead?”
  - “Happy to keep going, or would you prefer to ring the office?”
  - “All good either way — want to finish the quote or call the team?”
  - “You’re welcome to call 1300 918 388 — or I can help you finish up the quote here.”

- If they say call: stop quoting
- If they say continue: resume quote

NEVER:
- Return non-JSON
- Quote early
- Repeat privacy policy more than once
- Use bullet points in JSON
- Answer unrelated questions — refer to the office


SPECIAL REQUESTS:
If extra tasks are mentioned:
- If you’re ≥90% confident, extract as `special_requests` and estimate time using `special_request_minutes_min` and `special_request_minutes_max`
- If not confident, say:
  “That might need a custom quote — could you contact our office and we’ll help you out?”
- Then ask if they want to continue online or call.

You must always extract all 3 fields if confident:
→ `special_requests` (long text)
→ `special_request_minutes_min` (number)
→ `special_request_minutes_max` (number)

Never trust the customer’s time estimate — quoted time must be the same or higher.

EXAMPLES OF COMMON SPECIAL REQUESTS:
(Use these for confident extraction)

1. Balcony door tracks – 20–40 min  
2. Deep spot-clean of a specific wall – 20–30 min  
3. Cleaning inside microwave – 10–15 min  
4. Pet hair removal from furniture – 30–60 min  
5. Light mould removal in bathroom corners – 30–45 min  
6. Window track detailing – 30–60 min  
7. Cobweb removal from high ceilings – 20–30 min  
8. Small amount of dishes left in sink – 10–20 min  
9. Wipe down of balcony railings – 20–30 min  
10. Mattress stain spot-clean – 30–45 min  
11. Wipe out bathroom drawers/cupboards – 15–25 min  
12. Removal of sticker residue – 10–30 min  
13. Rangehood filter soak – 20–40 min  
14. Small wall patch dust cleanup – 10–15 min  
15. Vacuuming inside wardrobe corners – 10–20 min

Other tasks not listed should be treated the same way:
- If you’re confident: estimate time + fill the 3 fields
- If not sure or sounds complex: refer to office and explain why

🚫 DO NOT ALLOW:
- Sauna cleaning
- Pool or spa cleaning
- High-risk jobs involving ladders or roof access
- Pressure washing or polishing floors
- Anything requiring hand tools, chemicals, or protective gear

If asked:
“We’re not set up for anything involving hand tools, ladders, saunas, pools, or polishing machines. Those need specialist help — best to call our office if you need that sort of work.”

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
    "weekend_cleaning", "is_property_manager", "real_estate_name",
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
        if val == "furnished":
            fields["furnished"] = "Furnished"
        elif val == "unfurnished":
            fields["furnished"] = "Unfurnished"

    # ✅ Boolean checkbox fields in Airtable
    BOOLEAN_FIELDS = {
        "oven_cleaning", "window_cleaning", "blind_cleaning", "garage_cleaning",
        "deep_cleaning", "fridge_cleaning", "range_hood_cleaning", 
        "wall_cleaning", "mandurah_property"
    }

    normalized_fields = {}
    for key, value in fields.items():
        mapped_key = FIELD_MAP.get(key, key)

        if mapped_key not in VALID_AIRTABLE_FIELDS:
            print(f"❌ Skipped field '{mapped_key}' — not in Airtable schema")
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
    new_log = f"{old_log}\n{sender.upper()}: {message}".strip()[-5000:]
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

        print("✅ Parsed props:", props)
        print("✅ Parsed reply:", reply)

        field_updates = {}

        # 🔄 Load existing values for merging
        existing = {}
        if record_id:
            url = f"https://api.airtable.com/v0/{airtable_base_id}/{table_name}/{record_id}"
            headers = {"Authorization": f"Bearer {airtable_api_key}"}
            res = requests.get(url, headers=headers)
            if res.ok:
                existing = res.json().get("fields", {})
            else:
                print("⚠️ Could not load existing fields for merge")

        for p in props:
            if isinstance(p, dict):
                if "property" in p and "value" in p:
                    key = p["property"]
                    value = p["value"]

                    if key == "special_requests":
                        prev = existing.get("special_requests", "").strip()
                        if value.strip() != prev:
                            combined = value.strip()
                            if prev and prev not in combined:
                                combined = f"{prev}\n+ {value.strip()}"
                            field_updates[key] = combined

                    elif key == "special_request_minutes_min":
                        prev = int(existing.get("special_request_minutes_min", 0))
                        if int(value) > prev:
                            field_updates[key] = prev + int(value)

                    elif key == "special_request_minutes_max":
                        prev = int(existing.get("special_request_minutes_max", 0))
                        if int(value) > prev:
                            field_updates[key] = prev + int(value)

                    else:
                        # Skip if same value already stored
                        if str(existing.get(key)).strip() != str(value).strip():
                            field_updates[key] = value

                elif len(p) == 1:
                    for k, v in p.items():
                        if str(existing.get(k)).strip() != str(v).strip():
                            field_updates[k] = v

        # 🧠 Handle escalation to office
        if any(x in reply.lower() for x in ["contact our office", "call the office", "ring the office"]):
            print("📞 Detected referral to office. Applying escalation flags.")
            field_updates["quote_stage"] = "Referred to Office"

            referral_note = (
                f"Brendan referred the customer to the office — unsure how to handle request.\n\n"
                f"📩 Customer said: “{message.strip()}”"
            )
            field_updates["quote_notes"] = referral_note[:10000]

            if quote_id:
                reply = reply.replace("VC-123456", quote_id)
                reply = reply.replace("{{quote_id}}", quote_id)

        return field_updates, reply

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

        # Handle __init__ → Always start a new quote
        if message.lower() == "__init__":
            print("🧪 DEBUG — FORCING NEW QUOTE")
            quote_id, record_id, session_id = create_new_quote(session_id, force_new=True)

            intro = "What needs cleaning today — bedrooms, bathrooms, oven, carpets, anything else?"
            append_message_log(record_id, message, "user")
            append_message_log(record_id, intro, "brendan")

            return JSONResponse(content={
                "properties": [],
                "response": intro,
                "next_actions": [],
                "session_id": session_id  # ✅ Already correct
            })

        # Otherwise, get existing quote
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

        # 🚧 Prevent updates once quote is finalized
        if stage != "Gathering Info":
            print(f"🚫 Cannot update — quote_stage is '{stage}'")
            return JSONResponse(content={
                "properties": [],
                "response": "That quote's already been calculated. You’ll need to start a new one if anything’s changed.",
                "next_actions": []
            })

        # --- Stage: Gathering Info ---
        updated_log = f"{log}\nUSER: {message}".strip()[-5000:]

        # Call GPT
        props_dict, reply = extract_properties_from_gpt4(message, updated_log, record_id, quote_id)

        print(f"\n🧠 Raw GPT Properties:\n{json.dumps(props_dict, indent=2)}")
        updates = props_dict

        print(f"\n🛠 Structured updates ready for Airtable:\n{json.dumps(updates, indent=2)}")

        if not updates:
            print("⚠️ WARNING: No valid fields parsed — double check GPT output or field map.")

        if updates:
            update_quote_record(record_id, updates)

        # Append convo log
        append_message_log(record_id, message, "user")
        append_message_log(record_id, reply, "brendan")

        return JSONResponse(content={
            "properties": list(updates.keys()),
            "response": reply or "Got that. Anything else I should know?",
            "next_actions": []
        })

    except Exception as e:
        print("🔥 UNEXPECTED ERROR:", e)
        return JSONResponse(status_code=500, content={"error": "Server issue. Try again in a moment."})
