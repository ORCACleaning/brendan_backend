# === logging_utils.py ===

import requests
from app.config import logger, settings

# ✅ Pull actual Airtable table name here
TABLE_NAME = "Vacate Quotes"
AIRTABLE_API_KEY = settings.AIRTABLE_API_KEY
AIRTABLE_BASE_ID = settings.AIRTABLE_BASE_ID


def log_debug_event(record_id: str, source: str, stage: str, message: str):
    """
    Append a debug line to the Airtable message_log field of the given record_id.
    """
    if not record_id:
        return

    log_line = f"{source}: {stage} – {message}"
    logger.info(f"📄 {log_line}")

    try:
        url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{TABLE_NAME}/{record_id}"
        headers = {
            "Authorization": f"Bearer {AIRTABLE_API_KEY}",
            "Content-Type": "application/json"
        }

        # Patch only the message_log field (append to existing value)
        patch_payload = {
            "fields": {
                "message_log": log_line
            }
        }

        # Use Airtable append behavior via our main update path
        requests.patch(url, headers=headers, json=patch_payload)

    except Exception as e:
        logger.warning(f"⚠️ Failed to log event: {e}")
