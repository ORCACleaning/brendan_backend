import os
import requests
from dotenv import load_dotenv
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

# === Send Email with Public Link to PDF ===
def send_quote_email(to_email: str, customer_name: str, pdf_url: str, quote_id: str):
    """
    Sends a quote email with a public link to the Render-hosted PDF quote (not as an attachment).
    """
    access_token = get_ms_access_token()
    url = f"https://graph.microsoft.com/v1.0/users/{SENDER_EMAIL}/sendMail"

    subject = f"Your Orca Cleaning Vacate Quote ({quote_id})"
    booking_url = f"https://orcacleaning.com.au/schedule?quote_id={quote_id}"
    name_line = f"Hi {customer_name}," if customer_name else "Hi there,"

    body_html = f"""\
<p>{name_line}</p>

<p>Thanks for requesting a quote with Orca Cleaning!</p>
<p>Your vacate clean quote is ready. You can view or download it here:</p>

<p><a href="{pdf_url}" style="font-weight: bold; color: #007BFF;">View Your PDF Quote</a></p>

<p>When you're ready to book, just use this link:</p>
<p><a href="{booking_url}" style="font-weight: bold; color: #28a745;">Book Your Clean</a></p>

<p>If you need to make changes or have any questions, just reply to this email — we’re always happy to help.</p>

<p>Cheers,<br>Brendan<br>Orca Cleaning Team</p>
"""

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

    try:
        log_debug_event(quote_id, "BACKEND", "Email Sending", f"Sending public PDF link to {to_email}")
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
