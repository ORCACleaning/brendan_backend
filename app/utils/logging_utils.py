# === logging_utils.py ===

import requests
from app.config import logger, settings

# ✅ Define Airtable table and credentials
TABLE_NAME = "Vacate Quotes"
AIRTABLE_API_KEY = settings.AIRTABLE_API_KEY
AIRTABLE_BASE_ID = settings.AIRTABLE_BASE_ID


def log_debug_event(record_id: str, source: str, event: str, message: str):
    """
    Logs a debug message to Airtable for the given record_id.
    Truncates message if too long for Airtable field.
    """
    if not record_id:
        return

    try:
        url = f"https://api.airtable.com/v0/{settings.AIRTABLE_BASE_ID}/{TABLE_NAME}/{record_id}"
        headers = {
            "Authorization": f"Bearer {settings.AIRTABLE_API_KEY}",
            "Content-Type": "application/json"
        }

        max_length = 10000  # Airtable field size safety
        if message and len(message) > max_length:
            logger.warning(f"⚠️ Message too long for Airtable logging — truncating from {len(message)} to {max_length} characters.")
            message = message[:max_length]

        payload = {
            "fields": {
                "message_log": f"{source.upper()}: {event}: {message}"
            }
        }

        res = requests.patch(url, headers=headers, json=payload)
        res.raise_for_status()
        logger.info(f"📄 BACKEND: Logged debug event – {event}")

    except Exception as e:
        logger.warning(f"⚠️ Failed to log event: {e}")
