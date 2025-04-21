import json
import logging
import requests
from datetime import datetime
from app.config import settings

# === Constants ===
TABLE_NAME = "Vacate Quotes"
MAX_LOG_LENGTH = 10000  # Adjust as per your requirement
_log_cache = {}

logger = logging.getLogger(__name__)

# === Debug Logging ===
def log_debug_event(record_id: str = None, source: str = "BACKEND", label: str = "", message: str = ""):
    timestamp = datetime.utcnow().isoformat()
    entry = f"[{timestamp}] [{source}] {label}: {message}"

    if not record_id:
        print(f"📄 Debug (no record_id): {entry}")
        return

    if record_id not in _log_cache:
        _log_cache[record_id] = []

    _log_cache[record_id].append(entry)

def flush_debug_log(record_id: str):
    if not record_id:
        return ""

    logs = _log_cache.get(record_id, [])
    if not logs:
        return ""

    combined = "\n".join(logs).strip()
    _log_cache[record_id] = []

    line_count = len(combined.splitlines())
    log_debug_event(record_id, "BACKEND", "Debug Log Flushed", f"{len(combined)} chars flushed to Airtable ({line_count} lines)")
    
    # Now try to update the debug log to Airtable
    try:
        url = f"https://api.airtable.com/v0/{settings.AIRTABLE_BASE_ID}/{TABLE_NAME}/{record_id}"
        headers = {
            "Authorization": f"Bearer {settings.AIRTABLE_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {"fields": {"debug_log": combined}}

        # Make the request to update Airtable
        res = requests.patch(url, headers=headers, json=payload)
        res.raise_for_status()  # Raise an error for bad responses

        logger.info(f"✅ Debug log successfully flushed for record {record_id}")
        return combined
    except Exception as e:
        logger.error(f"❌ Error flushing debug log to Airtable for record {record_id}: {e}")
        log_debug_event(record_id, "BACKEND", "Debug Log Flush Error", str(e))
        return combined  # Return the logs even if the API call failed


def update_quote_record(record_id: str, fields: dict):
    log_debug_event(record_id, "BACKEND", "Function Start", f"update_quote_record(record_id={record_id}, fields={list(fields.keys())})")

    if not record_id:
        logger.warning("⚠️ update_quote_record called with no record_id")
        return []

    url = f"https://api.airtable.com/v0/{settings.AIRTABLE_BASE_ID}/{TABLE_NAME}/{record_id}"
    headers = {
        "Authorization": f"Bearer {settings.AIRTABLE_API_KEY}",
        "Content-Type": "application/json"
    }

    normalized_fields = {}

    for raw_key, value in fields.items():
        key = FIELD_MAP.get(raw_key, raw_key)
        log_debug_event(record_id, "BACKEND", "Raw Field Input", f"{raw_key} → {key} = {value}")

        if key not in VALID_AIRTABLE_FIELDS:
            logger.warning(f"⚠️ Skipping unknown Airtable field: {key}")
            log_debug_event(record_id, "BACKEND", "Field Skipped", f"{key} not in VALID_AIRTABLE_FIELDS")
            continue

        try:
            if key == "customer_name":
                # Ensure customer_name is only updated if it's not already present
                if value and not fields.get("customer_name", "").strip():
                    value = str(value).strip()
                    log_debug_event(record_id, "BACKEND", "Customer Name Captured", f"Stored customer name: {value}")
                else:
                    value = fields.get("customer_name", "").strip()  # Don't overwrite if already filled

            if key in BOOLEAN_FIELDS:
                if isinstance(value, bool):
                    pass
                elif value in [None, ""]:
                    value = False
                else:
                    original = value
                    value = str(value).strip().lower() in TRUE_VALUES
                    log_debug_event(record_id, "BACKEND", "Bool Normalized", f"{key}: {original} → {value}")

            elif key in INTEGER_FIELDS:
                original = value
                value = int(float(value))
                if value > MAX_REASONABLE_INT:
                    logger.warning(f"⚠️ Clamping large value for {key}: {value}")
                    log_debug_event(record_id, "BACKEND", "Int Clamped", f"{key}: {original} → {MAX_REASONABLE_INT}")
                    value = MAX_REASONABLE_INT

            elif key in {
                "gst_applied", "total_price", "base_hourly_rate", "price_per_session",
                "estimated_time_mins", "discount_applied", "mandurah_surcharge",
                "after_hours_surcharge", "weekend_surcharge", "calculated_hours"
            }:
                value = float(value)

            elif key == "special_requests":
                if not value or str(value).strip().lower() in {"no", "none", "false", "no special requests", "n/a"}:
                    value = ""
                else:
                    value = str(value).strip()

            elif key == "extra_hours_requested":
                value = float(value) if value not in [None, ""] else 0.0

            elif key == "furnished":
                val = str(value).strip().lower()
                if "unfurnished" in val:
                    value = "Unfurnished"
                elif "furnished" in val:
                    value = "Furnished"
                else:
                    value = ""

            elif key == "carpet_cleaning":
                val = str(value).strip().capitalize()
                value = val if val in {"Yes", "No"} else ""

            else:
                value = "" if value is None else str(value).strip()

        except Exception as e:
            logger.warning(f"⚠️ Failed to normalize {key}: {e}")
            log_debug_event(record_id, "BACKEND", "Normalization Error", f"{key}: {e}")
            continue

        normalized_fields[key] = value

    debug_log = flush_debug_log(record_id)
    if debug_log:
        normalized_fields["debug_log"] = debug_log
        log_debug_event(record_id, "BACKEND", "Debug Log Flushed", f"{len(debug_log)} chars flushed to Airtable")

    if not normalized_fields:
        logger.info(f"⏩ No valid fields to update for record {record_id}")
        log_debug_event(record_id, "BACKEND", "Update Skipped", "No valid fields to apply.")
        return []

    logger.info(f"\n📤 Updating Airtable Record: {record_id}")
    logger.info(f"🛠 Payload: {json.dumps(normalized_fields, indent=2)}")

    for key in list(normalized_fields.keys()):
        if key not in VALID_AIRTABLE_FIELDS:
            logger.error(f"❌ INVALID FIELD DETECTED: {key} — Removing from payload.")
            normalized_fields.pop(key, None)

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
        log_debug_event(record_id, "BACKEND", "Bulk Update Exception", str(e))

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
            log_debug_event(record_id, "BACKEND", "Fallback Field Update Error", f"{key}: {e}")

    if successful:
        log_debug_event(record_id, "BACKEND", "Record Updated (Fallback)", f"Fields updated one-by-one: {successful}")
    else:
        log_debug_event(record_id, "BACKEND", "Update Failed", "No fields could be updated (bulk and fallback both failed).")

    return successful
