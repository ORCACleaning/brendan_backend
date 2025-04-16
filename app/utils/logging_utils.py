# === logging_utils.py ===

import requests
from app.config import logger, settings

TABLE_NAME = "Vacate Quotes"  # ✅ No external import
AIRTABLE_API_KEY = settings.AIRTABLE_API_KEY
AIRTABLE_BASE_ID = settings.AIRTABLE_BASE_ID


def log_debug_event(record_id: str, source: str, stage: str, message: str):
    """
    Central logging handler that appends trace logs to the Airtable message_log field.
    """
    if not record_id:
        return

    try:
        log_line = f"{source}: {stage} – {message}"
        logger.info(f"📄 {log_line}")

        url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{TABLE_NAME}/{record_id}"
        headers = {
            "Authorization": f"Bearer {AIRTABLE_API_KEY}",
            "Content-Type": "application/json"
        }

        # Fetch current message_log
        current_log = ""
        res = requests.get(url, headers=headers)
        if res.status_code == 200:
            fields = res.json().get("fields", {})
            current_log = fields.get("message_log", "")

        new_log = (current_log + "\n" + log_line).strip()

        payload = {
            "fields": {
                "message_log": new_log
            }
        }

        res = requests.patch(url, headers=headers, json=payload)
        res.raise_for_status()

    except Exception as e:
        logger.warning(f"⚠️ Failed to log event: {e}")
