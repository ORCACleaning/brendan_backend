import json
import requests
import logging
from datetime import datetime

from app.api.field_rules import (
    FIELD_MAP,
    VALID_AIRTABLE_FIELDS,
    BOOLEAN_FIELDS,
    INTEGER_FIELDS,
    TRUE_VALUES
)
from app.config import settings

logger = logging.getLogger(__name__)

TABLE_NAME = "Vacate Quotes"
_log_cache = {}  # Global in-memory debug cache


# === Debug Logger ===
def log_debug_event(record_id: str = None, source: str = "BACKEND", label: str = "", message: str = ""):
    timestamp = datetime.utcnow().isoformat()
    entry = f"[{timestamp}] [{source}] {label}: {message}"

    if not record_id:
        print(f"📄 Debug (no record_id): {entry}")
        return

    if record_id not in _log_cache:
        _log_cache[record_id] = []

    _log_cache[record_id].append(entry)
    if len(_log_cache[record_id]) > 50:
        _log_cache[record_id] = _log_cache[record_id][-50:]


# === Flush Debug Log ===
def flush_debug_log(record_id: str):
    logs = _log_cache.get(record_id, [])
    if not logs:
        return ""
    combined = "\n".join(logs).strip()
    _log_cache[record_id] = []  # Clear after flush
    return combined


# === Update Airtable Record ===
def update_quote_record(record_id: str, fields: dict):
    url = f"https://api.airtable.com/v0/{settings.AIRTABLE_BASE_ID}/{TABLE_NAME}/{record_id}"
    headers = {
        "Authorization": f"Bearer {settings.AIRTABLE_API_KEY}",
        "Content-Type": "application/json"
    }

    MAX_REASONABLE_INT = 100
    normalized_fields = {}

    # === Furnished Field Special Handling ===
    if "furnished" in fields:
        val = str(fields["furnished"]).strip().lower()
        if "unfurnished" in val:
            fields["furnished"] = "Unfurnished"
        elif "furnished" in val:
            fields["furnished"] = "Furnished"
        else:
            logger.warning(f"⚠️ Invalid furnished value: {fields['furnished']}")
            fields["furnished"] = ""

    # === Normalize Fields ===
    for raw_key, value in fields.items():
        key = FIELD_MAP.get(raw_key, raw_key)

        if key not in VALID_AIRTABLE_FIELDS:
            logger.warning(f"⚠️ Skipping unknown Airtable field: {key}")
            continue

        # Boolean Handling
        if key in BOOLEAN_FIELDS:
            if isinstance(value, bool):
                pass
            elif value in [None, ""]:
                value = False
            else:
                value = str(value).strip().lower() in TRUE_VALUES

        # Integer Handling
        elif key in INTEGER_FIELDS:
            try:
                value = int(value)
                if value > MAX_REASONABLE_INT:
                    logger.warning(f"⚠️ Clamping large value for {key}: {value}")
                    value = MAX_REASONABLE_INT
            except Exception:
                logger.warning(f"⚠️ Failed to convert {key} to int — forcing 0")
                value = 0

        # Float Handling
        elif key in {
            "gst_applied", "total_price", "base_hourly_rate", "price_per_session",
            "estimated_time_mins", "discount_applied", "mandurah_surcharge",
            "after_hours_surcharge", "weekend_surcharge", "calculated_hours"
        }:
            try:
                value = float(value)
            except Exception:
                logger.warning(f"⚠️ Failed to convert {key} to float — forcing 0.0")
                value = 0.0

        # Special Requests Normalization
        elif key == "special_requests":
            if not value or str(value).strip().lower() in {"no", "none", "false", "no special requests", "n/a"}:
                value = ""

        # Extra Hours Requested
        elif key == "extra_hours_requested":
            try:
                value = float(value) if value not in [None, ""] else 0
            except Exception:
                value = 0

        # Everything else as string
        else:
            value = "" if value is None else str(value).strip()

        normalized_fields[key] = value

    # Final Privacy Boolean Force
    if "privacy_acknowledged" in fields:
        normalized_fields["privacy_acknowledged"] = bool(fields.get("privacy_acknowledged"))

    # Inject debug log
    debug_log = flush_debug_log(record_id)
    if debug_log:
        normalized_fields["debug_log"] = debug_log

    # No valid fields to update
    if not normalized_fields:
        logger.info(f"⏩ No valid fields to update for record {record_id}")
        return []

    logger.info(f"\n📤 Updating Airtable Record: {record_id}")
    logger.info(f"🛠 Payload: {json.dumps(normalized_fields, indent=2)}")

    # Final validation before sending
    for key in list(normalized_fields.keys()):
        if key not in VALID_AIRTABLE_FIELDS:
            logger.error(f"❌ INVALID FIELD DETECTED: {key} — Removing from payload.")
            normalized_fields.pop(key, None)

    # === Bulk Update Attempt ===
    try:
        res = requests.patch(url, headers=headers, json={"fields": normalized_fields})
        if res.ok:
            logger.info("✅ Airtable bulk update success.")
            log_debug_event(record_id, "BACKEND", "Record Updated (Bulk)", f"Fields updated: {list(normalized_fields.keys())}")
            return list(normalized_fields.keys())
        logger.error(f"❌ Airtable bulk update failed: {res.status_code}")
        try:
            logger.error(f"🧾 Error response: {res.json()}")
        except Exception:
            logger.error("🧾 Error response: (Non-JSON)")
    except Exception as e:
        logger.error(f"❌ Exception during Airtable bulk update: {e}")

    # === Fallback: Update Fields Individually ===
    successful = []
    for key, value in normalized_fields.items():
        try:
            single_res = requests.patch(url, headers=headers, json={"fields": {key: value}})
            if single_res.ok:
                logger.info(f"✅ Field '{key}' updated successfully.")
                successful.append(key)
            else:
                logger.error(f"❌ Field '{key}' failed to update.")
        except Exception as e:
            logger.error(f"❌ Exception updating field '{key}': {e}")

    if successful:
        log_debug_event(record_id, "BACKEND", "Record Updated (Fallback)", f"Fields updated one-by-one: {successful}")
    else:
        log_debug_event(record_id, "BACKEND", "Update Failed", "No fields could be updated (bulk and fallback both failed).")

    return successful
