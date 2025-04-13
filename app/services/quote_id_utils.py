import uuid
from datetime import datetime
import pytz
import requests
from fastapi import HTTPException
from app.api.filter_response import logger, settings

AIRTABLE_API_KEY = settings.AIRTABLE_API_KEY
AIRTABLE_BASE_ID = settings.AIRTABLE_BASE_ID

def get_next_quote_id(prefix: str = "VC") -> str:
    """
    Generates a unique quote_id for Brendan using timestamp pattern.
    Format: VC-YYMMDD-HHMMSS-RANDOM
    """
    now = datetime.now(pytz.timezone("Australia/Perth"))
    timestamp = now.strftime("%y%m%d-%H%M%S")
    random_suffix = str(uuid.uuid4().int)[:3]

    next_quote_id = f"{prefix}-{timestamp}-{random_suffix}"
    logger.info(f"✅ Generated Brendan quote_id: {next_quote_id}")
    return next_quote_id


def get_next_manual_quote_id() -> str:
    """
    Generates the next sequential quote_id for manual quotes (admin use).
    """
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/Quote ID Counter"
    headers = {
        "Authorization": f"Bearer {AIRTABLE_API_KEY}",
        "Content-Type": "application/json"
    }

    res = requests.get(url, headers=headers)
    res.raise_for_status()

    records = res.json()["records"]
    if not records:
        raise Exception("No counter record found in Quote ID Counter table.")

    record_id = records[0]["id"]
    current_counter = records[0]["fields"].get("counter", 0)

    next_counter = current_counter + 1
    next_quote_id = f"VC-{str(next_counter).zfill(6)}"

    patch_res = requests.patch(
        f"{url}/{record_id}",
        headers=headers,
        json={"fields": {"counter": next_counter}}
    )

    if not patch_res.ok:
        raise Exception(f"Failed to update counter in Airtable: {patch_res.text}")

    logger.info(f"✅ Generated Manual quote_id: {next_quote_id}")
    return next_quote_id
