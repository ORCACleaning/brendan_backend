import os
import requests
import base64
from dotenv import load_dotenv
from app.services.pdf_generator import generate_quote_pdf
from app.filter_response import update_quote_record

load_dotenv()

MS_CLIENT_ID = os.getenv("MS_CLIENT_ID")
MS_TENANT_ID = os.getenv("MS_TENANT_ID")
MS_CLIENT_SECRET = os.getenv("MS_CLIENT_SECRET")

SENDER_EMAIL = "info@orcacleaning.com.au"

# --- Microsoft Auth ---
def get_ms_access_token():
    url = f"https://login.microsoftonline.com/{MS_TENANT_ID}/oauth2/v2.0/token"
    data = {
        "client_id": MS_CLIENT_ID,
        "client_secret": MS_CLIENT_SECRET,
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials"
    }
    res = requests.post(url, data=data)
    res.raise_for_status()
    return res.json()["access_token"]

# --- Basic Email Sending ---
def send_email_outlook(to_email: str, subject: str, body_html: str):
    access_token = get_ms_access_token()
    url = f"https://graph.microsoft.com/v1.0/users/{SENDER_EMAIL}/sendMail"

    payload = {
        "message": {
            "subject": subject,
            "body": {
                "contentType": "HTML",
                "content": body_html
            },
            "toRecipients": [
                {"emailAddress": {"address": to_email}}
            ]
        }
    }

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    res = requests.post(url, json=payload, headers=headers)
    if res.status_code == 202:
        print(f"✅ Email sent to {to_email}")
    else:
        print("❌ Failed to send email:", res.status_code, res.text)

# --- Quote Email with PDF ---
def send_quote_email(to_email: str, customer_name: str, pdf_path: str, quote_id: str):
    access_token = get_ms_access_token()
    url = f"https://graph.microsoft.com/v1.0/users/{SENDER_EMAIL}/sendMail"

    subject = f"Your Vacate Cleaning Quote from Orca Cleaning ({quote_id})"

    body_html = f"""
    <p>Hi {customer_name or 'there'},</p>

    <p>Thank you for requesting a quote with Orca Cleaning!</p>

    <p>I've attached your vacate cleaning quote as a PDF. If you’d like to proceed with booking, simply reply to this email or click the link below:</p>

    <p><a href="https://orcacleaning.com.au/schedule?quote_id={quote_id}">Schedule My Cleaning</a></p>

    <p>Let me know if you have any questions.</p>

    <p>Cheers,<br>
    Brendan<br>
    Orca Cleaning</p>
    """

    with open(pdf_path, "rb") as f:
        pdf_data = base64.b64encode(f.read()).decode("utf-8")

    payload = {
        "message": {
            "subject": subject,
            "body": {
                "contentType": "HTML",
                "content": body_html
            },
            "toRecipients": [
                {"emailAddress": {"address": to_email}}
            ],
            "attachments": [
                {
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "name": os.path.basename(pdf_path),
                    "contentBytes": pdf_data
                }
            ]
        }
    }

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    res = requests.post(url, json=payload, headers=headers)
    if res.status_code == 202:
        print(f"✅ Quote email sent to {to_email}")
    else:
        print("❌ Failed to send quote email:", res.status_code, res.text)

# --- PDF Generation + Email Sending Handler ---
def handle_pdf_and_email(record_id: str, quote_id: str, fields: dict):
    pdf_path = generate_quote_pdf(fields)
    customer_name = fields.get("customer_name", "there")
    to_email = fields.get("email")

    if not to_email:
        print("❌ No customer email found — skipping PDF + Email sending.")
        return

    print(f"📧 Generating PDF & Sending Email to {to_email} for Quote {quote_id}")
    send_quote_email(to_email, customer_name, pdf_path, quote_id)

    pdf_url = f"https://orcacleaning.com.au/static/quotes/{os.path.basename(pdf_path)}"
    update_quote_record(record_id, {"pdf_link": pdf_url})
