# === quote_id_utils.py ===

import uuid
from datetime import datetime
import pytz
import requests

from fastapi import HTTPException
from app.config import logger, settings  # Load from config.py

# Airtable Settings
AIRTABLE_API_KEY = settings.AIRTABLE_API_KEY
AIRTABLE_BASE_ID = settings.AIRTABLE_BASE_ID
QUOTE_ID_COUNTER_TABLE = "Quote ID Counter"


# === Brendan Auto Quote ID ===
def get_next_quote_id(prefix: str = "VC") -> str:
    """
    Generates a timestamp-based quote_id for Brendan.
    Format: VC-YYMMDD-HHMMSS-RND
    Example: VC-250413-224512-491
    """
    now = datetime.now(pytz.timezone("Australia/Perth"))
    timestamp = now.strftime("%y%m%d-%H%M%S")
    random_suffix = str(uuid.uuid4().int)[:3]  # Last 3 digits from UUID for randomness

    quote_id = f"{prefix}-{timestamp}-{random_suffix}"
    logger.info(f"✅ Generated Brendan quote_id: {quote_id}")
    return quote_id


# === Manual Admin Quote ID ===
def get_next_manual_quote_id() -> str:
    """
    Generates a sequential quote_id for admin-created quotes.
    Pulls & increments counter in Airtable.
    Example: VC-000123
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
        raise HTTPException(status_code=500, detail="Failed to fetch Quote ID Counter.")

    records = res.json().get("records", [])
    if not records:
        logger.error("❌ No counter record found in Airtable.")
        raise HTTPException(status_code=500, detail="No Quote ID Counter record found.")

    record_id = records[0]["id"]
    current_counter = records[0]["fields"].get("counter", 0)

    next_counter = current_counter + 1
    next_quote_id = f"VC-{str(next_counter).zfill(6)}"  # Pad to VC-000123

    patch_res = requests.patch(
        f"{url}/{record_id}",
        headers=headers,
        json={"fields": {"counter": next_counter}}
    )

    if not patch_res.ok:
        logger.error(f"❌ Failed to update Airtable Counter: {patch_res.text}")
        raise HTTPException(status_code=500, detail="Failed to update Quote ID Counter.")

    logger.info(f"✅ Generated Manual quote_id: {next_quote_id}")
    return next_quote_id
