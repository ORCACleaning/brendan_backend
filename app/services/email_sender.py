import os
import requests
import base64
from dotenv import load_dotenv

from app.services.pdf_generator import generate_quote_pdf
from app.api import filter_response  # Airtable update logic

load_dotenv()

MS_CLIENT_ID = os.getenv("MS_CLIENT_ID")
MS_TENANT_ID = os.getenv("MS_TENANT_ID")
MS_CLIENT_SECRET = os.getenv("MS_CLIENT_SECRET")

SENDER_EMAIL = "info@orcacleaning.com.au"


def get_ms_access_token() -> str:
    """
    Retrieve Microsoft Graph API access token using Client Credentials Flow.
    """
    url = f"https://login.microsoftonline.com/{MS_TENANT_ID}/oauth2/v2.0/token"
    data = {
        "client_id": MS_CLIENT_ID,
        "client_secret": MS_CLIENT_SECRET,
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials",
    }
    response = requests.post(url, data=data)
    response.raise_for_status()
    token = response.json().get("access_token")

    if not token:
        raise ValueError("❌ Failed to retrieve MS Graph API access token")

    return token


def send_email_outlook(to_email: str, subject: str, body_html: str):
    """
    Send a plain email (no attachment) via MS Graph API.
    """
    access_token = get_ms_access_token()
    url = f"https://graph.microsoft.com/v1.0/users/{SENDER_EMAIL}/sendMail"

    payload = {
        "message": {
            "subject": subject,
            "body": {"contentType": "HTML", "content": body_html},
            "toRecipients": [{"emailAddress": {"address": to_email}}],
        }
    }

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    res = requests.post(url, json=payload, headers=headers)
    if res.status_code == 202:
        print(f"✅ Email sent to {to_email}")
    else:
        print(f"❌ Failed to send email ({res.status_code}): {res.text}")


def send_quote_email(to_email: str, customer_name: str, pdf_path: str, quote_id: str):
    """
    Send the quote email with attached PDF.
    """
    access_token = get_ms_access_token()
    url = f"https://graph.microsoft.com/v1.0/users/{SENDER_EMAIL}/sendMail"

    subject = f"Your Vacate Cleaning Quote from Orca Cleaning ({quote_id})"
    booking_url = f"https://orcacleaning.com.au/schedule?quote_id={quote_id}"

    body_html = f"""
    <p>Hi {customer_name or 'there'},</p>

    <p>Thank you for requesting a quote with Orca Cleaning!</p>

    <p>I’ve attached your vacate cleaning quote as a PDF. If you’d like to proceed with booking, simply reply to this email or click below:</p>

    <p><a href="{booking_url}">Schedule My Cleaning</a></p>

    <p>Let me know if you have any questions.</p>

    <p>Cheers,<br>Brendan<br>Orca Cleaning</p>
    """

    with open(pdf_path, "rb") as f:
        pdf_data = base64.b64encode(f.read()).decode("utf-8")

    payload = {
        "message": {
            "subject": subject,
            "body": {"contentType": "HTML", "content": body_html},
            "toRecipients": [{"emailAddress": {"address": to_email}}],
            "attachments": [
                {
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "name": os.path.basename(pdf_path),
                    "contentBytes": pdf_data,
                }
            ],
        }
    }

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    res = requests.post(url, json=payload, headers=headers)
    if res.status_code == 202:
        print(f"✅ Quote email sent to {to_email}")
    else:
        print(f"❌ Failed to send quote email ({res.status_code}): {res.text}")


def handle_pdf_and_email(record_id: str, quote_id: str, fields: dict):
    """
    Generate quote PDF, send it via email, and update Airtable record with PDF link.
    """
    pdf_path = generate_quote_pdf(fields)
    to_email = fields.get("customer_email")

    if not to_email:
        print(f"❌ No customer email found for Quote ID: {quote_id} — skipping email.")
        return

    customer_name = fields.get("customer_name") or "there"

    print(f"📧 Generating PDF & Sending Email to {to_email} for Quote {quote_id}")
    send_quote_email(to_email, customer_name, pdf_path, quote_id)

    pdf_url = f"https://orcacleaning.com.au/static/quotes/{os.path.basename(pdf_path)}"
    filter_response.update_quote_record(record_id, {"pdf_link": pdf_url})
