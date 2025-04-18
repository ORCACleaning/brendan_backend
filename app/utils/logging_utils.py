# === logging_utils.py ===

import requests
from app.config import logger, settings

# ✅ Define Airtable table and credentials
TABLE_NAME = "Vacate Quotes"
AIRTABLE_API_KEY = settings.AIRTABLE_API_KEY
AIRTABLE_BASE_ID = settings.AIRTABLE_BASE_ID

# ✅ In-memory cache for debug logs (to be flushed during updates)
DEBUG_CACHE = {}
MAX_DEBUG_LENGTH = 10000

def log_debug_event(record_id: str, source: str, event: str, message: str):
    """
    Caches debug messages by record_id.
    Messages will be flushed to Airtable when update_quote_record() is called.
    """
    if not record_id:
        logger.warning("⚠️ log_debug_event called with no record_id")
        return

    log_line = f"{source.upper()}: {event}: {message}"
    DEBUG_CACHE.setdefault(record_id, []).append(log_line)

    logger.debug(f"🧠 Cached debug event for {record_id}: {log_line}")


def flush_debug_log(record_id: str):
    """
    Combines and returns debug log for record_id from DEBUG_CACHE.
    Clears it after retrieval.
    """
    lines = DEBUG_CACHE.pop(record_id, [])
    if not lines:
        return ""

    combined = "\n".join(lines).strip()
    if len(combined) > MAX_DEBUG_LENGTH:
        combined = combined[-MAX_DEBUG_LENGTH:]
        logger.warning(f"⚠️ Truncated debug log for {record_id} to last {MAX_DEBUG_LENGTH} characters")

    return combined
