import os
import requests
from dotenv import load_dotenv

load_dotenv()

MS_CLIENT_ID = os.getenv("MS_CLIENT_ID")
MS_TENANT_ID = os.getenv("MS_TENANT_ID")
MS_CLIENT_SECRET = os.getenv("MS_CLIENT_SECRET")

SENDER_EMAIL = "info@orcacleaning.com.au"

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


def send_email_outlook(to_email: str, subject: str, body_html: str):
    access_token = get_ms_access_token()
    url = "https://graph.microsoft.com/v1.0/users/{}/sendMail".format(SENDER_EMAIL)

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
