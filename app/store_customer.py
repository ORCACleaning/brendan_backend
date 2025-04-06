from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import requests
import os
import smtplib
from io import BytesIO
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from app.services.pdf_generator import generate_quote_pdf

router = APIRouter()

# --- Config ---
AIRTABLE_API_KEY = os.getenv("AIRTABLE_API_KEY")
AIRTABLE_BASE_ID = "appXZ4gOnbdu2Tpme"
AIRTABLE_TABLE_NAME = "Vacate Quotes"
SMTP_SERVER = "smtp.office365.com"
SMTP_PORT = 587
SMTP_USER = "info@orcacleaning.com.au"
SMTP_PASS = os.getenv("SMTP_PASS")
SENDER_EMAIL = SMTP_USER

# --- Data Model ---
class CustomerData(BaseModel):
    mandurah_property: bool = False
    special_requests: str = ""
    special_request_minutes_min: int = 0
    special_request_minutes_max: int = 0

    quote_id: str
    name: str
    email: str
    phone: str

    suburb: str
    bedrooms_v2: int
    bathrooms_v2: int
    furnished: str
    property_address: str
    business_name: str

    oven_cleaning: bool = False
    window_cleaning: bool = False
    window_count: int = 0
    wall_cleaning: bool = False
    balcony_cleaning: bool = False
    deep_cleaning: bool = False
    fridge_cleaning: bool = False
    range_hood_cleaning: bool = False

    after_hours: bool = False
    weekend_cleaning: bool = False
    after_hours_surcharge: float = 0.0
    weekend_surcharge: float = 0.0

    pdf_link: str = ""
    booking_url: str = ""
    quote_stage: str = "Personal Info Received"
    quote_notes: str = ""
    message_log: str = ""
    session_id: str = ""

def bool_to_checkbox(value: bool) -> str:
    return "true" if value else "false"

@router.post("/store-customer")
async def store_customer(data: CustomerData):
    try:
        # Convert booleans to Airtable-compatible "true"/"false" strings
        airtable_data = {
            "quote_id": data.quote_id,
            "name": data.name,
            "email": data.email,
            "phone": data.phone,
            "suburb": data.suburb,
            "bedrooms_v2": data.bedrooms_v2,
            "bathrooms_v2": data.bathrooms_v2,
            "furnished": data.furnished,
            "property_address": data.property_address,
            "business_name": data.business_name,

            "oven_cleaning": bool_to_checkbox(data.oven_cleaning),
            "window_cleaning": bool_to_checkbox(data.window_cleaning),
            "window_count": data.window_count,
            "wall_cleaning": bool_to_checkbox(data.wall_cleaning),
            "balcony_cleaning": bool_to_checkbox(data.balcony_cleaning),
            "deep_cleaning": bool_to_checkbox(data.deep_cleaning),
            "fridge_cleaning": bool_to_checkbox(data.fridge_cleaning),
            "range_hood_cleaning": bool_to_checkbox(data.range_hood_cleaning),

            "after_hours": bool_to_checkbox(data.after_hours),
            "weekend_cleaning": bool_to_checkbox(data.weekend_cleaning),
            "after_hours_surcharge": data.after_hours_surcharge,
            "weekend_surcharge": data.weekend_surcharge,

            "pdf_link": data.pdf_link,
            "booking_url": data.booking_url,
            "quote_stage": data.quote_stage,
            "quote_notes": data.quote_notes,
            "message_log": data.message_log,
            
        "mandurah_property": bool_to_checkbox(data.mandurah_property),
        "special_requests": data.special_requests,
        "special_request_minutes_min": data.special_request_minutes_min,
        "special_request_minutes_max": data.special_request_minutes_max,
        "session_id": data.session_id,
        }

        headers = {
            "Authorization": f"Bearer {AIRTABLE_API_KEY}",
            "Content-Type": "application/json"
        }

        # --- Airtable Update ---
        response = requests.post(
            f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}",
            headers=headers,
            json={"fields": airtable_data}
        )

        if response.status_code >= 300:
            raise Exception(f"Airtable error: {response.text}")

        # --- Generate PDF ---
        pdf_path = generate_quote_pdf(data.dict())

        # --- Send Email with PDF ---
        msg = MIMEMultipart()
        msg["From"] = SENDER_EMAIL
        msg["To"] = data.email
        msg["Subject"] = f"Your Orca Vacate Cleaning Quote ({data.quote_id})"

        body = f"Hi {data.name},

Thanks for chatting with Brendan! Attached is your PDF quote.

"                f"You can book your clean here: {data.booking_url}

Cheers,
Orca Cleaning"
        msg.attach(MIMEApplication(body.encode("utf-8"), Name="body.txt"))

        with open(pdf_path, "rb") as f:
            part = MIMEApplication(f.read(), Name=os.path.basename(pdf_path))
            part["Content-Disposition"] = f'attachment; filename="{os.path.basename(pdf_path)}"'
            msg.attach(part)

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SENDER_EMAIL, data.email, msg.as_string())

        return {"status": "success", "quote_id": data.quote_id}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

