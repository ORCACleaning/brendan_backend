# === logging_utils.py ===

import requests
from app.config import logger


def log_debug_event(record_id: str, source: str, stage: str, message: str):
    """
    Central logging handler that appends trace logs to the Airtable message_log field.
    """
    if not record_id:
        return

    try:
        from app.services.airtable_handler import update_airtable_record  # Lazy import to avoid circular refs

        log_line = f"{source}: {stage} – {message}"
        logger.info(f"📄 {log_line}")

        update_airtable_record(record_id, {"message_log": log_line}, append=True)

    except Exception as e:
        logger.warning(f"⚠️ Failed to log event: {e}")
