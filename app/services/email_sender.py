def send_quote_email(to_email: str, customer_name: str, pdf_url: str, quote_id: str):
    """
    Sends a quote email with a public link to the Render-hosted PDF quote (not as an attachment).
    Validates inputs and logs all key steps.
    """

    # === Input validation ===
    if not to_email or "@" not in to_email:
        log_debug_event(quote_id, "BACKEND", "Email Send Skipped", f"Invalid or missing email: {to_email}")
        return

    if not pdf_url or not pdf_url.startswith("http"):
        log_debug_event(quote_id, "BACKEND", "Email Send Skipped", f"Invalid PDF URL: {pdf_url}")
        return

    if not quote_id:
        log_debug_event(None, "BACKEND", "Email Send Skipped", "Missing quote_id for email send")
        return

    customer_name = customer_name.strip() if customer_name else ""
    name_line = f"Hi {customer_name}," if customer_name else "Hi there,"

    subject = f"Your Orca Cleaning Vacate Quote ({quote_id})"
    booking_url = f"https://orcacleaning.com.au/schedule?quote_id={quote_id}"

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

    try:
        access_token = get_ms_access_token()
        url = f"https://graph.microsoft.com/v1.0/users/{SENDER_EMAIL}/sendMail"

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }

        log_debug_event(quote_id, "BACKEND", "Email Sending", f"Sending PDF link to {to_email}")
        res = requests.post(url, json=payload, headers=headers)

        if res.status_code == 202:
            log_debug_event(quote_id, "BACKEND", "Email Sent", f"Quote email sent to {to_email}")
            print(f"✅ Quote email sent to {to_email}")
        else:
            log_debug_event(quote_id, "BACKEND", "Email Send Failed", f"Status {res.status_code}: {res.text}")
            print(f"❌ Failed to send quote email ({res.status_code}): {res.text}")

    except Exception as e:
        log_debug_event(quote_id, "BACKEND", "Email Exception", str(e))
        print(f"❌ Exception while sending quote email: {e}")
