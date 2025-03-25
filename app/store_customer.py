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
        # Download the PDF from the URL
        response = requests.get(pdf_link)
        if response.status_code != 200:
            print(f"🔴 Error downloading PDF: {response.status_code}")
            raise HTTPException(status_code=500, detail="Error downloading PDF")

        # Attach the PDF
        pdf_data = BytesIO(response.content)
        msg.attach(MIMEApplication(pdf_data.read(), Name=f"Quote_{quote_id}.pdf", _subtype="pdf"))
        print("✅ PDF attached successfully.")
    except Exception as e:
        print(f"🔴 Error attaching PDF: {e}")
        raise HTTPException(status_code=500, detail="Error attaching PDF")

    try:
        # Send the email
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
    # Step 1: Find the record in Airtable
    record = find_airtable_record(data.quote_id)
    if not record:
        print(f"🔴 Quote ID {data.quote_id} not found in Airtable.")
        raise HTTPException(status_code=404, detail="Quote ID not found in Airtable")

    # Step 2: Build PDF link and booking URL
    pdf_link = f"https://your-pdf-storage-link/{data.quote_id}.pdf"
    booking_url = f"https://orcacleaning.com.au/schedule?quote_id={data.quote_id}"

    # Step 3: Update Airtable
    airtable_data = {
        "fields": {
            "quote_id": data.quote_id,
            "customer_name": data.customer_name,
            "customer_email": data.customer_email,
            "customer_phone": data.customer_phone,
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

    # Step 4: Send email
    send_email(data.customer_email, data.customer_name, data.quote_id, pdf_link, booking_url)

    # Step 5: Return success
    return {
    "status": "success",
    "message": f"Quote email sent to {data.customer_email}.",
    "booking_url": f"https://orcacleaning.com.au/schedule?quote_id={data.quote_id}",
    "quote_id": data.quote_id
}

