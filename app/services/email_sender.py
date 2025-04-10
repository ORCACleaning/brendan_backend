import os
import base64
import requests

from dotenv import load_dotenv

load_dotenv()

# Microsoft Graph API Config
TENANT_ID = os.getenv("AZURE_TENANT_ID")
CLIENT_ID = os.getenv("AZURE_CLIENT_ID")
CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET")
FROM_EMAIL = "info@orcacleaning.com.au"

def get_graph_access_token():
    url = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
    data = {
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "scope": "https://graph.microsoft.com/.default"
    }
    response = requests.post(url, data=data)
    response.raise_for_status()
    return response.json()["access_token"]

def send_quote_email(to_email: str, pdf_path: str, data: dict):
    access_token = get_graph_access_token()
    
    with open(pdf_path, "rb") as pdf_file:
        pdf_base64 = base64.b64encode(pdf_file.read()).decode("utf-8")

    subject = f"Your Orca Cleaning Quote — {data.get('quote_id', 'Vacate Cleaning')}"
    
    body_html = f"""
    <p>Hi there,</p>

    <p>Thanks for requesting a vacate cleaning quote with Orca Cleaning!</p>

    <p>Attached is your personalised quote based on the details you provided. Let me know if you have any questions or if you'd like to lock in a booking.</p>

    <p>Kind regards,</p>

    <p><strong>Brendan</strong><br>
    Quoting Officer<br>
    Orca Cleaning<br>
    <a href="https://orcacleaning.com.au">orcacleaning.com.au</a><br>
    1300 918 388</p>
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
            ],
            "attachments": [
                {
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "name": os.path.basename(pdf_path),
                    "contentBytes": pdf_base64
                }
            ]
        },
        "saveToSentItems": "true"
    }

    send_url = "https://graph.microsoft.com/v1.0/users/{}/sendMail".format(FROM_EMAIL)
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    response = requests.post(send_url, headers=headers, json=payload)

    if response.status_code == 202:
        print(f"✅ Email sent successfully to {to_email}")
    else:
        print(f"❌ Failed to send email: {response.status_code} - {response.text}")

