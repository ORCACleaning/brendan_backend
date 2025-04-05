from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import requests
import os
import smtplib
from io import BytesIO
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication

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
    quote_id: str
    customer_name: str
    customer_email: str
    customer_phone: str

    after_hours: bool = False
    weekend_cleaning: bool = False
    is_property_manager: bool = False
    real_estate_company_name: str = ""
    special_requests: str = ""
    special_request_minutes_min: int = 0
    special_request_minutes_max: int = 0
    mandurah_property: bool = False

    wall_cleaning: bool = False
    balcony_cleaning: bool = False
    window_cleaning: bool = False
    window_count: int = 0
    deep_cleaning: bool = False
    fridge_cleaning: bool = False
    range_hood_cleaning: bool = False
    garage_cleaning: bool = False

    # ✅ New fields for carpeted areas
    carpet_bedroom_count: int = 0
    carpet_mainroom_count: int = 0

# --- Helper Functions ---
def find_airtable_record(quote_id):
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}"
    headers = {"Authorization": f"Bearer {AIRTABLE_API_KEY}"}
    params = {"filterByFormula": f"{{quote_id}} = '{quote_id}'"}

    response = requests.get(url, headers=headers, params=params)
    print("🔍 Airtable raw response:", response.json())
    records = response.json().get("records", [])
    return records[0] if records else None

def send_email(to_email: str, customer_name: str, quote_id: str, pdf_link: str, booking_url: str):
    subject = f"Your Orca Cleaning Quote – Ref #{quote_id}"
    body = f"""
    G'day {customer_name},

    Thanks for reaching out to Orca Cleaning! Here's your personalized quote for the cleaning job.

    Quote ID: {quote_id}
    Please find your quote PDF attached.

    You can also **Schedule Now** using the link below:
    {booking_url}

    If you're a property manager, we’ve already applied your discount — just confirm your real estate company in the form!

    Need help? Just reply to this email or text us on WhatsApp. Cheers!

    The Orca Cleaning Team
    """

    # Create email
    msg = MIMEMultipart()
    msg['From'] = SENDER_EMAIL
    msg['To'] = to_email
    msg['Subject'] = subject
    msg.attach(MIMEApplication(body, 'plain'))

    try:
        response = requests.get(pdf_link)
        if response.status_code != 200:
            print(f"🔴 Error downloading PDF: {response.status_code}")
            raise HTTPException(status_code=500, detail="Error downloading PDF")

        pdf_data = BytesIO(response.content)
        msg.attach(MIMEApplication(pdf_data.read(), Name=f"Quote_{quote_id}.pdf", _subtype="pdf"))
        print("✅ PDF attached successfully.")
    except Exception as e:
        print(f"🔴 Error attaching PDF: {e}")
        raise HTTPException(status_code=500, detail="Error attaching PDF")

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SENDER_EMAIL, to_email, msg.as_string())
            print(f"✅ Email sent successfully to {to_email}")
    except Exception as e:
        print(f"🔴 Error sending email: {e}")
        raise HTTPException(status_code=500, detail="Error sending email")

# --- Endpoint ---
@router.post("/store-customer")
def store_customer(data: CustomerData):
    record = find_airtable_record(data.quote_id)
    if not record:
        print(f"🔴 Quote ID {data.quote_id} not found in Airtable.")
        raise HTTPException(status_code=404, detail="Quote ID not found in Airtable")

    pdf_link = f"https://orcacleaning.com.au/quotes/{data.quote_id}.pdf"
    booking_url = f"https://orcacleaning.com.au/schedule?quote_id={data.quote_id}"

    # ✅ Update Airtable
    airtable_data = {
        "fields": {
            "quote_id": data.quote_id,
            "customer_name": data.customer_name,
            "customer_email": data.customer_email,
            "customer_phone": data.customer_phone,
            "after_hours": "Yes" if data.after_hours else "No",
            "weekend_cleaning": "Yes" if data.weekend_cleaning else "No",
            "is_property_manager": "Yes" if data.is_property_manager else "No",
            "real_estate_company_name": data.real_estate_company_name.strip() or "N/A",
            "special_requests": data.special_requests or "None",
            "special_request_minutes_min": data.special_request_minutes_min,
            "special_request_minutes_max": data.special_request_minutes_max,
            "mandurah_property": "Yes" if data.mandurah_property else "No",
            "wall_cleaning": "Yes" if data.wall_cleaning else "No",
            "balcony_cleaning": "Yes" if data.balcony_cleaning else "No",
            "window_cleaning": "Yes" if data.window_cleaning else "No",
            "window_count": data.window_count,
            "deep_cleaning": "Yes" if data.deep_cleaning else "No",
            "fridge_cleaning": "Yes" if data.fridge_cleaning else "No",
            "range_hood_cleaning": "Yes" if data.range_hood_cleaning else "No",
            "garage_cleaning": "Yes" if data.garage_cleaning else "No",

            # ✅ New carpet fields
            "carpet_bedroom_count": data.carpet_bedroom_count,
            "carpet_mainroom_count": data.carpet_mainroom_count,

            "status": "Quote Only",
            "pdf_link": pdf_link,
            "booking_url": booking_url,
        }
    }

    airtable_url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}/{record['id']}"
    headers = {
        "Authorization": f"Bearer {AIRTABLE_API_KEY}",
        "Content-Type": "application/json"
    }

    print(f"🔄 Sending update to Airtable: {airtable_url}")
    response = requests.patch(airtable_url, json=airtable_data, headers=headers)
    if response.status_code != 200:
        print(f"🔴 Error updating Airtable: {response.text}")
        raise HTTPException(status_code=500, detail="Error updating Airtable")
    else:
        print(f"✅ Airtable update successful: {response.json()}")

    send_email(data.customer_email, data.customer_name, data.quote_id, pdf_link, booking_url)

    return {
        "status": "success",
        "message": f"Quote email sent to {data.customer_email}.",
        "booking_url": booking_url,
        "quote_id": data.quote_id
    }
