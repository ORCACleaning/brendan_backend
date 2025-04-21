# === Airtable Field Rules ===

# Master List of Valid Airtable Fields (Allowed for Read/Write)
VALID_AIRTABLE_FIELDS = {
    # Core Quote Identifiers
    "quote_id", "timestamp", "source", "session_id", "quote_stage", "quote_notes", "privacy_acknowledged",

    # Property Details
    "suburb", "bedrooms_v2", "bathrooms_v2", "furnished_status",

    # Cleaning Options - Checkboxes / Extras
    "oven_cleaning", "window_cleaning", "window_count", "blind_cleaning",
    "garage_cleaning", "balcony_cleaning", "upholstery_cleaning",
    "deep_cleaning", "fridge_cleaning", "range_hood_cleaning", "wall_cleaning",
    "after_hours_cleaning", "weekend_cleaning", "mandurah_property", "is_property_manager",

    # Carpet Cleaning Breakdown
    "carpet_cleaning",  # ✅ Now a Single Select: "Yes", "No", or empty
    "carpet_bedroom_count", "carpet_mainroom_count", "carpet_study_count",
    "carpet_halway_count", "carpet_stairs_count", "carpet_other_count",

    # Special Requests Handling
    "special_requests", "special_request_minutes_min", "special_request_minutes_max", "extra_hours_requested",

    # Quote Result Fields
    "total_price", "estimated_time_mins", "base_hourly_rate", "gst_applied",
    "discount_applied", "discount_reason", "price_per_session",
    "mandurah_surcharge", "after_hours_surcharge", "weekend_surcharge",

    # Customer Details (After Quote)
    "customer_name", "customer_email", "customer_phone", "real_estate_name", "property_address", "number_of_sessions",

    # Outputs
    "pdf_link", "booking_url",

    # Traceability
    "message_log", "gpt_error_log"
}

# === Field Mapping ===
FIELD_MAP = {k: k for k in VALID_AIRTABLE_FIELDS}

# === Integer-only Fields ===
INTEGER_FIELDS = {
    "bedrooms_v2", "bathrooms_v2", "window_count",
    "carpet_bedroom_count", "carpet_mainroom_count", "carpet_study_count",
    "carpet_halway_count", "carpet_stairs_count", "carpet_other_count",
    "special_request_minutes_min", "special_request_minutes_max",
    "number_of_sessions"
}

# === Boolean-only Fields (must normalize to True/False) ===
BOOLEAN_FIELDS = {
    "oven_cleaning",
    "window_cleaning",
    "blind_cleaning",
    "garage_cleaning",
    "balcony_cleaning",
    "upholstery_cleaning",
    "deep_cleaning",
    "fridge_cleaning",
    "range_hood_cleaning",
    "wall_cleaning",
    "after_hours_cleaning",
    "weekend_cleaning",
    "mandurah_property",
    "is_property_manager",
    "privacy_acknowledged"
}

# === Single Select Fields (expected exact string values) ===
SINGLE_SELECT_FIELDS = {
    "carpet_cleaning"  # Allowed: "Yes", "No", or ""
}
