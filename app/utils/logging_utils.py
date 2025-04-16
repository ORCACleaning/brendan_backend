# === logging_utils.py ===

import os
import logging
import requests
from app.config import logger
from app.constants import TABLE_NAME
from app.settings import settings

AIRTABLE_URL = f"https://api.airtable.com/v0/{settings.AIRTABLE_BASE_ID}/{TABLE_NAME}"
HEADERS = {
    "Authorization": f"Bearer {settings.AIRTABLE_API_KEY}",
    "Content-Type": "application/json"
}


def log_debug_event(record_id: str, source: str, stage: str, message: str):
    """
    Central debug logging function.
    Writes trace logs into the message_log field in Airtable.
    Appends the log entry to existing log via PATCH.
    """
    if not record_id:
        return

    try:
        log_line = f"{source}: {stage} – {message}"
        logger.info(f"📄 {log_line}")

        # Retrieve existing log (GET)
        get_url = f"{AIRTABLE_URL}/{record_id}"
        res = requests.get(get_url, headers=HEADERS)
        res.raise_for_status()

        existing_log = res.json().get("fields", {}).get("message_log", "")
        updated_log = (existing_log + "\n" + log_line).strip()

        # Update with appended log
        update_url = f"{AIRTABLE_URL}/{record_id}"
        update_payload = {
            "fields": {
                "message_log": updated_log
            }
        }
        update_res = requests.patch(update_url, headers=HEADERS, json=update_payload)
        update_res.raise_for_status()

    except Exception as e:
        logger.warning(f"⚠️ Failed to log debug event: {e}")
