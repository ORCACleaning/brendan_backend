# === quote_id_utils.py ===

import uuid
from datetime import datetime
import pytz
import requests

from fastapi import HTTPException
from app.config import logger, settings  # Load from config.py
from app.routes.filter_response import log_debug_event  # Debug log support

# Airtable Settings
AIRTABLE_API_KEY = settings.AIRTABLE_API_KEY
AIRTABLE_BASE_ID = settings.AIRTABLE_BASE_ID
QUOTE_ID_COUNTER_TABLE = "Quote ID Counter"


# === Brendan Auto Quote ID (Chatbot Generated) ===
def get_next_quote_id(prefix: str = "VC") -> str:
    """
    Generates a timestamp-based quote_id for Brendan (AI-generated quotes).
    Format: VC-YYMMDD-HHMMSS-RND
    Example: VC-250413-224512-491
    """
    now = datetime.now(pytz.timezone("Australia/Perth"))
    timestamp = now.strftime("%y%m%d-%H%M%S")
    random_suffix = str(uuid.uuid4().int)[-3:]  # Use last 3 digits for randomness

    quote_id = f"{prefix}-{timestamp}-{random_suffix}"
    logger.info(f"✅ Generated Brendan quote_id: {quote_id}")

    # Optional debug log if passed into create flow
    try:
        log_debug_event(None, "BACKEND", "Quote ID Generated", f"Auto quote_id: {quote_id}")
    except:
        pass

    return quote_id


# === Admin Manual Quote ID (Sequential) ===
def get_next_manual_quote_id() -> str:
    """
    Generates a sequential quote_id for admin-created quotes.
    Pulls & increments counter in Airtable.
    Format: VC-000123
    """
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{QUOTE_ID_COUNTER_TABLE}"
    headers = {
        "Authorization": f"Bearer {AIRTABLE_API_KEY}",
        "Content-Type": "application/json"
    }

    try:
        res = requests.get(url, headers=headers)
        res.raise_for_status()
    except Exception as e:
        logger.error(f"❌ Failed to fetch Quote ID Counter: {e}")
        try:
            log_debug_event(None, "BACKEND", "Quote ID Counter Fetch Failed", str(e))
        except:
            pass
        raise HTTPException(status_code=500, detail="Failed to fetch Quote ID Counter.")

    records = res.json().get("records", [])
    if not records:
        logger.error("❌ No Quote ID Counter record found in Airtable.")
        try:
            log_debug_event(None, "BACKEND", "Quote ID Counter Missing", "No records found")
        except:
            pass
        raise HTTPException(status_code=500, detail="No Quote ID Counter record found.")

    record_id = records[0]["id"]
    current_counter = records[0]["fields"].get("counter", 0)

    next_counter = current_counter + 1
    next_quote_id = f"VC-{str(next_counter).zfill(6)}"  # Format: VC-000123

    patch_res = requests.patch(
        f"{url}/{record_id}",
        headers=headers,
        json={"fields": {"counter": next_counter}}
    )

    if not patch_res.ok:
        logger.error(f"❌ Failed to update Quote ID Counter: {patch_res.text}")
        try:
            log_debug_event(record_id, "BACKEND", "Quote ID Counter Update Failed", patch_res.text)
        except:
            pass
        raise HTTPException(status_code=500, detail="Failed to update Quote ID Counter.")

    logger.info(f"✅ Generated Manual quote_id: {next_quote_id}")
    try:
        log_debug_event(record_id, "BACKEND", "Manual Quote ID Generated", f"Manual quote_id: {next_quote_id}")
    except:
        pass

    return next_quote_id
