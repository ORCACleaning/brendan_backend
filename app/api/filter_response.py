from openai import OpenAI
import os
import json
import requests
import uuid
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

# ✅ Load .env variables
load_dotenv()

router = APIRouter()

# ✅ API Keys
api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=api_key)

AIRTABLE_API_KEY = os.getenv("AIRTABLE_API_KEY")
AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID")
TABLE_NAME = "Vacate Quotes"

# ✅ GPT Prompt
GPT_PROMPT = """
You are Brendan, an Aussie quote assistant working for Orca Cleaning — a top-rated professional cleaning company based in Western Australia.

We specialise in:
- Vacate / End-of-Lease Cleaning (this is your primary job)
- Office Cleaning
- Holiday Home Cleaning
- Gym, Retail & Education Facilities (info available on the website)

Customers contact you for **vacate cleaning quotes**, and you:
1. Ask questions in a casual Aussie tone (max 2–3 things per message).
2. Vary how you respond naturally, avoid sounding robotic.
3. NEVER repeat greetings like "G'day" — only introduce yourself ONCE.
4. Keep chat light, helpful, and professional.
5. Use customer’s previous messages to continue the convo smoothly.
6. If you're unsure, just ask politely instead of guessing.
7. If someone asks about services other than vacate cleaning, say:
   "I focus on vacate cleans, but you can grab a quote for other types at orcacleaning.com.au."
8. If it’s urgent or unusual, say:
   "Best to ring our team on 1300 918 838 or email info@orcacleaning.com.au."

Orca Cleaning is known for:
- 5-star vacate cleaning in Perth
- Affordable prices
- No hidden fees
- Cheeky discounts
- Fully insured and police-cleared staff

If it's the first message, say something friendly and detailed like:
"Hey there! I’m Brendan, Orca Cleaning’s vacate cleaning assistant 🎼🐳. I’ll sort your quote in under 2 minutes — no sign-up needed. We’ve even got a cheeky seasonal discount on right now 😉\n\nJust start by telling me your **suburb**, how many **bedrooms and bathrooms**, and whether it’s **furnished or empty** — then we’ll go from there!"

Otherwise, continue the convo naturally.

Always extract any of the following properties if mentioned:
- suburb (Text)
- bedrooms_v2 (Integer)
- bathrooms_v2 (Integer)
- furnished (Yes/No)
- oven_cleaning (Yes/No)
- carpet_cleaning (Yes/No)
- deep_cleaning (Yes/No)
- wall_cleaning (Yes/No)
- fridge_cleaning (Yes/No)
- garage_cleaning (Yes/No)
- window_tracks (Yes/No)
- windows_v2 (Integer)
- balcony_cleaning (Yes/No)
- range_hood_cleaning (Yes/No)
- special_requests (Text)
- user_message (Text)

Respond using this JSON format:
{
  "properties": [
    {"property": "suburb", "value": "Perth"},
    {"property": "bedrooms_v2", "value": "3"}
  ],
  "response": "Awesome, noted! Just need a few more details to finalise your quote."
}
"""

# ✅ Airtable utilities
def get_quote_by_session(session_id):
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{TABLE_NAME}"
    headers = {"Authorization": f"Bearer {AIRTABLE_API_KEY}"}
    params = {"filterByFormula": f"{{session_id}}='{session_id}'"}
    res = requests.get(url, headers=headers, params=params)
    data = res.json()
    if data.get("records"):
        record = data["records"][0]
        return {
            "record_id": record["id"],
            "fields": record["fields"],
            "stage": record["fields"].get("quote_stage", "Gathering Info"),
            "quote_id": record["fields"].get("quote_id")
        }
    return None

def get_quote_by_record_id(record_id):
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{TABLE_NAME}/{record_id}"
    headers = {"Authorization": f"Bearer {AIRTABLE_API_KEY}"}
    res = requests.get(url, headers=headers)
    return res.json()

def create_new_quote(session_id):
    quote_id = f"VAC-{uuid.uuid4().hex[:8]}"
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
    record = res.json().get("id")
    return quote_id, record

def update_quote_record(record_id, fields):
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{TABLE_NAME}/{record_id}"
    headers = {
        "Authorization": f"Bearer {AIRTABLE_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {"fields": fields}
    requests.patch(url, headers=headers, json=data)

def append_message_log(record_id, new_message, sender):
    current = get_quote_by_record_id(record_id)["fields"].get("message_log", "")
    updated = f"{current}\n{sender.upper()}: {new_message}".strip()[-5000:]
    update_quote_record(record_id, {"message_log": updated})

def extract_properties_from_gpt4(message: str, log: str):
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": GPT_PROMPT},
                {"role": "system", "content": f"Conversation so far:\n{log}"},
                {"role": "user", "content": message}
            ],
            max_tokens=400
        )
        content = response.choices[0].message.content.strip()
        content = content.replace("```json", "").replace("```", "").strip()
        result_json = json.loads(content)
        return result_json.get("properties", []), result_json.get("response", "")
    except Exception as e:
        print("❌ GPT parsing error:", e)
        return [], "Sorry, I couldn’t quite get that. Could you rephrase it?"

def generate_next_actions():
    return [
        {"action": "proceed_booking", "label": "Proceed to Booking"},
        {"action": "download_pdf", "label": "Download PDF Quote"},
        {"action": "email_pdf", "label": "Email PDF Quote"},
        {"action": "ask_questions", "label": "Ask Questions or Change Parameters"}
    ]

@router.post("/filter-response")
async def filter_response_entry(request: Request):
    try:
        body = await request.json()
        message = body.get("message", "").strip()
        session_id = body.get("session_id")

        if not session_id:
            raise HTTPException(status_code=400, detail="Session ID is required.")

        quote_data = get_quote_by_session(session_id)

        if not quote_data:
            quote_id, record_id = create_new_quote(session_id)
            fields = {}
            stage = "Gathering Info"
            log = ""
        else:
            quote_id = quote_data["quote_id"]
            record_id = quote_data["record_id"]
            fields = quote_data["fields"]
            stage = quote_data["stage"]
            log = fields.get("message_log", "")

        # Store user's message
        append_message_log(record_id, message, "user")

        if stage == "Gathering Info":
            props, reply = extract_properties_from_gpt4(message, log)

            updates = {p["property"]: p["value"] for p in props}
            updates["quote_stage"] = "Gathering Info"
            update_quote_record(record_id, updates)

            # Store Brendan's message
            append_message_log(record_id, reply, "brendan")

            required = ["suburb", "bedrooms_v2", "bathrooms_v2", "oven_cleaning", "carpet_cleaning", "furnished"]
            if all(field in {**fields, **updates} for field in required):
                update_quote_record(record_id, {"quote_stage": "Quote Calculated", "status": "Quote Calculated"})
                return JSONResponse(
                    content={
                        "properties": props,
                        "response": "Thanks mate! I’ve got everything I need to whip up your quote. Hang tight…",
                        "next_actions": []
                    }
                )

            return JSONResponse(
                content={
                    "properties": props,
                    "response": reply or "Got that! Anything else you'd like us to know?",
                    "next_actions": []
                }
            )

        elif stage == "Quote Calculated":
            pdf = fields.get("pdf_link", "#")
            booking = fields.get("booking_url", "#")
            return JSONResponse(
                content={
                    "properties": [],
                    "response": f"Your quote is ready! 👉 [View PDF]({pdf}) or [Schedule Now]({booking})",
                    "next_actions": generate_next_actions()
                }
            )

        elif stage == "Gathering Personal Info":
            return JSONResponse(
                content={
                    "properties": [],
                    "response": "Just need your name, email, and phone to send that through. 😊",
                    "next_actions": []
                }
            )

        else:
            return JSONResponse(
                content={
                    "properties": [],
                    "response": "All done and dusted! Let me know if you'd like to tweak anything.",
                    "next_actions": generate_next_actions()
                }
            )

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
