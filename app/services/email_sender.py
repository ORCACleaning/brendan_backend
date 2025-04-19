import os
import uuid
import base64
import requests
from dotenv import load_dotenv

from app.services.pdf_generator import generate_quote_pdf
from app.utils.logging_utils import log_debug_event

# === Load Environment Variables ===
load_dotenv()

# === Microsoft Graph API Credentials ===
MS_CLIENT_ID = os.getenv("MS_CLIENT_ID")
MS_TENANT_ID = os.getenv("MS_TENANT_ID")
MS_CLIENT_SECRET = os.getenv("MS_CLIENT_SECRET")
SENDER_EMAIL = "info@orcacleaning.com.au"

# === Get Microsoft Graph Token ===
def get_ms_access_token() -> str:
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
        raise ValueError("❌ MS Graph token retrieval failed.")
    return token

# === Send Email Without Attachment ===
def send_email_outlook(to_email: str, subject: str, body_html: str):
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

# === Send PDF Quote Email ===
def send_quote_email(to_email: str, customer_name: str, pdf_path: str, quote_id: str):
    """
    Send the quote email with attached PDF via Microsoft Graph API.
    """
    access_token = get_ms_access_token()
    url = f"https://graph.microsoft.com/v1.0/users/{SENDER_EMAIL}/sendMail"

    subject = f"Your Vacate Cleaning Quote from Orca Cleaning ({quote_id})"
    booking_url = f"https://orcacleaning.com.au/schedule?quote_id={quote_id}"

    body_html = f"""\
<p>Hi {customer_name or 'there'},</p>

<p>Thanks for requesting a quote with Orca Cleaning!</p>
<p>We’ve attached your vacate cleaning quote as a PDF for your records.</p>

<p>You can book your clean directly using the link below:</p>
<p><a href="{booking_url}" style="font-weight: bold; color: #007BFF;">Click here to book online</a></p>

<p>If you have any questions or need to make changes, just reply to this email — we’re here to help.</p>

<p>Cheers,<br>Brendan<br>Orca Cleaning Team</p>
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
                    "contentBytes": pdf_data,
                }
            ]
        }
    }

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    try:
        log_debug_event(quote_id, "BACKEND", "Email Sending", f"Sending quote email to {to_email}")
        res = requests.post(url, json=payload, headers=headers)

        if res.status_code == 202:
            log_debug_event(quote_id, "BACKEND", "Email Sent", f"Quote email successfully sent to {to_email}")
            print(f"✅ Quote email sent to {to_email}")
        else:
            log_debug_event(quote_id, "BACKEND", "Email Send Failed", f"{res.status_code}: {res.text}")
            print(f"❌ Failed to send quote email ({res.status_code}): {res.text}")

    except Exception as e:
        log_debug_event(quote_id, "BACKEND", "Email Exception", str(e))
        print(f"❌ Exception while sending quote email: {e}")
