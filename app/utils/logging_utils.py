# === logging_utils.py ===

import requests
from app.config import logger

# Attempt to import update_airtable_record — fallback to dummy if unavailable
try:
    from app.services.airtable_handler import update_airtable_record
except Exception as e:
    logger.warning(f"⚠️ DEBUG LOGGER WARNING: Failed to import update_airtable_record: {e}")

    def update_airtable_record(record_id: str, fields: dict, append: bool = False):
        logger.warning(f"⚠️ Debug fallback: Skipping Airtable update for record {record_id}. Message: {fields.get('message_log')}")


def log_debug_event(record_id: str, source: str, stage: str, message: str):
    """
    Central logging handler that appends trace logs to the Airtable message_log field.
    """
    if not record_id:
        return

    try:
        log_line = f"{source}: {stage} – {message}"
        logger.info(f"📄 {log_line}")
        update_airtable_record(record_id, {"message_log": log_line}, append=True)

    except Exception as e:
        logger.warning(f"⚠️ Failed to log debug event: {e}")
