from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import requests
import os
import smtplib
from io import BytesIO
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
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
        # Airtable payload with exact field names
        airtable_data = {
            "Quote ID": data.quote_id,
            "Customer Name": data.name,
            "Customer Email": data.email,
            "Customer Phone": data.phone,
            "Suburb": data.suburb,
            "Bedrooms": data.bedrooms_v2,
            "Bathrooms": data.bathrooms_v2,
            "Furnished Status": data.furnished,
            "Property Address": data.property_address,
            "Business Name": data.business_name,

            "Oven Cleaning": bool_to_checkbox(data.oven_cleaning),
            "Window Cleaning": bool_to_checkbox(data.window_cleaning),
            "Window Count": data.window_count,
            "Wall Cleaning": bool_to_checkbox(data.wall_cleaning),
            "Balcony Cleaning": bool_to_checkbox(data.balcony_cleaning),
            "Deep Cleaning": bool_to_checkbox(data.deep_cleaning),
            "Fridge Cleaning": bool_to_checkbox(data.fridge_cleaning),
            "Rangehood Cleaning": bool_to_checkbox(data.range_hood_cleaning),

            "After Hours": bool_to_checkbox(data.after_hours),
            "Weekend Cleaning": bool_to_checkbox(data.weekend_cleaning),
            "After Hours Surcharge": data.after_hours_surcharge,
            "Weekend Surcharge": data.weekend_surcharge,

            "PDF Quote Link": data.pdf_link,
            "Booking URL": data.booking_url,
            "Quote Stage": data.quote_stage,
            "Quote Notes": data.quote_notes,
            "Message Log": data.message_log,
            "Mandurah Property": bool_to_checkbox(data.mandurah_property),
            "Special Requests": data.special_requests,
            "Special Request Min Minutes": data.special_request_minutes_min,
            "Special Request Max Minutes": data.special_request_minutes_max,
            "Session ID": data.session_id,
        }

        headers = {
            "Authorization": f"Bearer {AIRTABLE_API_KEY}",
            "Content-Type": "application/json"
        }

        response = requests.post(
            f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}",
            headers=headers,
            json={"fields": airtable_data}
        )

        if response.status_code >= 300:
            raise Exception(f"Airtable error: {response.text}")

        # Generate PDF
        pdf_path = generate_quote_pdf(data.dict())

        # Send Email
        msg = MIMEMultipart()
        msg["From"] = SENDER_EMAIL
        msg["To"] = data.email
        msg["Subject"] = f"Your Orca Vacate Cleaning Quote ({data.quote_id})"

        body = f"""Hi {data.name},

Thanks for chatting with Brendan! Attached is your PDF quote.

You can book your clean here: {data.booking_url}

Cheers,  
Orca Cleaning
"""
        msg.attach(MIMEText(body, "plain"))

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
