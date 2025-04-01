from openai import OpenAI
import os
import json
import requests
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
You are Brendan, an Aussie vacate cleaning assistant for Orca Cleaning. Your job is to:
1. Extract useful cleaning-related properties from the customer's message.
2. If the customer mentions a range (e.g., "3–4 bedrooms"), use the higher value.
3. If they say something vague (like "a few windows"), default to the closest reasonable number.
4. If they mention any special requests (e.g. "clean behind fridge", "extra deep shower scrub"), include it as special_requests.
5. Reply in a casual, friendly Aussie tone if there's anything unusual or unclear.

Extract the following properties **only if they are mentioned**:
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
    {"property": "bedrooms_v2", "value": "3"},
    {"property": "oven_cleaning", "value": "Yes"}
  ],
  "response": "Got it mate, sounds like a standard 3x1 — I’ll pop that in!"
}
"""

# ✅ Airtable utilities
def get_quote_record(quote_id):
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{TABLE_NAME}"
    headers = {"Authorization": f"Bearer {AIRTABLE_API_KEY}"}
    params = {"filterByFormula": f"{{quote_id}}='{quote_id}'"}

    res = requests.get(url, headers=headers, params=params)
    data = res.json()

    if data.get("records"):
        record = data["records"][0]
        return {
            "record_id": record["id"],
            "fields": record["fields"],
            "stage": record["fields"].get("quote_stage", "Gathering Info")
        }
    return None

def update_quote_record(record_id, fields):
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{TABLE_NAME}/{record_id}"
    headers = {
        "Authorization": f"Bearer {AIRTABLE_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {"fields": fields}
    requests.patch(url, headers=headers, json=data)

# ✅ GPT-4 Extraction
def extract_properties_from_gpt4(message: str):
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": GPT_PROMPT},
            {"role": "user", "content": message}
        ],
        max_tokens=300
    )
    content = response.choices[0].message.content.strip()
    content = content.replace("```json", "").replace("```", "").strip()
    result_json = json.loads(content)
    return result_json.get("properties", []), result_json.get("response", "")

# ✅ PDF + Quote trigger
def generate_quote_and_pdf(fields: dict, quote_id: str, record_id: str):
    try:
        payload = {
            "suburb": fields.get("suburb", ""),
            "bedrooms_v2": int(fields.get("bedrooms_v2", 0)),
            "bathrooms_v2": int(fields.get("bathrooms_v2", 0)),
            "oven_cleaning": fields.get("oven_cleaning") == "Yes",
            "carpet_cleaning": fields.get("carpet_cleaning") == "Yes",
            "furnished": fields.get("furnished", ""),
            "special_requests": fields.get("special_requests", ""),
            "special_request_minutes_min": None,
            "special_request_minutes_max": None,
            "after_hours": False,
            "weekend_cleaning": False,
            "mandurah_property": False,
            "is_property_manager": False,
            "wall_cleaning": fields.get("wall_cleaning") == "Yes",
            "balcony_cleaning": fields.get("balcony_cleaning") == "Yes",
            "window_cleaning": False,
            "windows_v2": int(fields.get("windows_v2", 0)),
            "deep_cleaning": fields.get("deep_cleaning") == "Yes",
            "fridge_cleaning": fields.get("fridge_cleaning") == "Yes",
            "range_hood_cleaning": fields.get("range_hood_cleaning") == "Yes",
            "garage_cleaning": fields.get("garage_cleaning") == "Yes"
        }

        quote_response = requests.post("http://localhost:10000/calculate-quote", json=payload)
        quote_data = quote_response.json()
        quote_data["quote_id"] = quote_id

        requests.post("http://localhost:10000/generate-pdf", json=quote_data)

        pdf_path = f"/static/quotes/{quote_id}.pdf"
        booking_url = f"https://orcacleaning.com.au/schedule?quote_id={quote_id}"

        update_quote_record(record_id, {
            "pdf_link": pdf_path,
            "booking_url": booking_url,
            "quote_stage": "Quote Calculated",
            "status": "quote_ready"
        })

        return pdf_path, booking_url

    except Exception as e:
        print("❌ [ERROR] Quote/PDF Generation Failed:", str(e))
        return None, None

# ✅ Dynamic Tidio buttons
def generate_next_actions():
    return [
        {"action": "proceed_booking", "label": "Proceed to Booking"},
        {"action": "download_pdf", "label": "Download PDF Quote"},
        {"action": "email_pdf", "label": "Email PDF Quote"},
        {"action": "ask_questions", "label": "Ask Questions or Change Parameters"}
    ]

# ✅ MAIN CHAT ENDPOINT (now accepts plain text only)
@router.post("/filter-response")
async def filter_response_raw_text(request: Request):
    try:
        message = await request.body()
        message = message.decode("utf-8")
        print(f"📩 Incoming raw message: {message}")

        # You can optionally handle quote_id via query param or skip for now
        # For now we fake a test quote_id to prevent crash
        quote_id = "TEST-QUOTE-ID"

        quote_data = get_quote_record(quote_id)
        if not quote_data:
            raise HTTPException(status_code=404, detail="Quote ID not found.")

        record_id = quote_data["record_id"]
        fields = quote_data["fields"]
        stage = quote_data["stage"]

        if stage == "Gathering Info":
            props, reply = extract_properties_from_gpt4(message)
            updates = {p["property"]: p["value"] for p in props}
            updates["quote_stage"] = "Gathering Info"
            update_quote_record(record_id, updates)

            required = ["suburb", "bedrooms_v2", "bathrooms_v2", "oven_cleaning", "carpet_cleaning", "furnished"]
            if all(field in {**fields, **updates} for field in required):
                update_quote_record(record_id, {"quote_stage": "Quote Calculated", "status": "quote_ready"})
                pdf_link, booking_url = generate_quote_and_pdf({**fields, **updates}, quote_id, record_id)
                return JSONResponse(
                    content={
                        "properties": props,
                        "response": f"All set! Your quote’s ready 👉 [View PDF]({pdf_link}) or [Book Now]({booking_url})",
                        "next_actions": generate_next_actions()
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
