# === logging_utils.py ===

import requests
from app.config import logger, settings

# ✅ Define Airtable table and credentials
TABLE_NAME = "Vacate Quotes"
AIRTABLE_API_KEY = settings.AIRTABLE_API_KEY
AIRTABLE_BASE_ID = settings.AIRTABLE_BASE_ID


def log_debug_event(record_id: str, source: str, stage: str, message: str):
    """
    Appends a debug log entry to the message_log field in Airtable.
    """
    if not record_id:
        return

    log_line = f"{source}: {stage} – {message}"
    logger.info(f"📄 {log_line}")

    try:
        # Fetch current message_log
        url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{TABLE_NAME}/{record_id}"
        headers = {
            "Authorization": f"Bearer {AIRTABLE_API_KEY}",
            "Content-Type": "application/json"
        }

        # Get existing log (only message_log field to keep light)
        res = requests.get(url, headers=headers, params={"fields[]": ["message_log"]})
        res.raise_for_status()
        existing_log = res.json().get("fields", {}).get("message_log", "")
        new_log = f"{existing_log}\n{log_line}".strip()

        # Update with appended log
        patch_payload = {
            "fields": {
                "message_log": new_log
            }
        }
        patch_url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{TABLE_NAME}/{record_id}"
        patch_res = requests.patch(patch_url, headers=headers, json=patch_payload)
        patch_res.raise_for_status()

    except Exception as e:
        logger.warning(f"⚠️ Failed to log event: {e}")
