from app.models.quote_models import QuoteRequest, QuoteResponse
from app.config import logger

REQUIRED_FIELDS_FOR_QUOTE = [
    "suburb", "bedrooms_v2", "bathrooms_v2", "furnished_status",
    "oven_cleaning", "window_cleaning", "blind_cleaning",
    "carpet_cleaning", "deep_cleaning", "fridge_cleaning", "range_hood_cleaning",
    "wall_cleaning", "balcony_cleaning", "garage_cleaning", "upholstery_cleaning",
    "after_hours_cleaning", "weekend_cleaning", "mandurah_property",
    "is_property_manager", "special_requests",
    "special_request_minutes_min", "special_request_minutes_max",
    "window_count",
    "carpet_mainroom_count", "carpet_stairs_count", "carpet_other_count",
    "quote_id"
]

def should_calculate_quote(fields: dict) -> bool:
    missing = []
    for key in REQUIRED_FIELDS_FOR_QUOTE:
        if key not in fields or fields[key] in ["", None, False]:
            missing.append(key)

    # Carpet breakdown required if carpet_cleaning == "Yes"
    if fields.get("carpet_cleaning") == "Yes":
        for carpet_field in ["carpet_mainroom_count", "carpet_stairs_count", "carpet_other_count"]:
            if fields.get(carpet_field) in ["", None]:
                missing.append(carpet_field)

    if missing:
        logger.warning(f"🟡 Quote not ready — missing fields: {missing}")
        return False

    return True

def calculate_quote(data: QuoteRequest) -> QuoteResponse:
    from app.utils.logging_utils import log_debug_event

    BASE_HOURLY_RATE = 75.0
    SEASONAL_DISCOUNT_PERCENT = 10
    PROPERTY_MANAGER_DISCOUNT = 5
    GST_PERCENT = 10

    WEEKEND_SURCHARGE_PERCENT = 100
    AFTER_HOURS_SURCHARGE_PERCENT = 15
    MANDURAH_SURCHARGE_PERCENT = 30

    EXTRA_SERVICE_TIMES = {
        "wall_cleaning": 30,
        "balcony_cleaning": 20,
        "deep_cleaning": 60,
        "fridge_cleaning": 30,
        "range_hood_cleaning": 20,
        "garage_cleaning": 40,
    }

    record_id = getattr(data, "record_id", None)
    try:
        log_debug_event(record_id, "BACKEND", "Quote Calculation Started", f"quote_id: {data.quote_id}")
    except:
        pass

    base_minutes = 0
    try:
        base_minutes += (data.bedrooms_v2 or 0) * 40
        base_minutes += (data.bathrooms_v2 or 0) * 30
        log_debug_event(record_id, "BACKEND", "Base Room Time", f"Bedrooms: {data.bedrooms_v2}, Bathrooms: {data.bathrooms_v2}")

        for service, time in EXTRA_SERVICE_TIMES.items():
            if getattr(data, service, False):
                base_minutes += time
                log_debug_event(record_id, "BACKEND", "Extra Service Time", f"{service}: +{time} mins")

        if data.window_cleaning:
            wc = data.window_count or 0
            base_minutes += wc * 10
            log_debug_event(record_id, "BACKEND", "Window Cleaning Time", f"{wc} windows: +{wc * 10} mins")

            if data.blind_cleaning:
                base_minutes += wc * 10
                log_debug_event(record_id, "BACKEND", "Blind Cleaning Time", f"{wc} blinds: +{wc * 10} mins")

        if data.oven_cleaning:
            base_minutes += 30
            log_debug_event(record_id, "BACKEND", "Oven Cleaning Time", "+30 mins")

        if data.upholstery_cleaning:
            base_minutes += 45
            log_debug_event(record_id, "BACKEND", "Upholstery Cleaning Time", "+45 mins")

        if str(data.furnished_status).strip().lower() == "furnished":
            base_minutes += 60
            log_debug_event(record_id, "BACKEND", "Furnished Bonus Time", "+60 mins")

        if str(data.carpet_cleaning).strip() == "Yes":
            carpet_breakdown = {
                "mainroom": (data.carpet_mainroom_count or 0) * 45,
                "stairs": (data.carpet_stairs_count or 0) * 35,
                "other": (data.carpet_other_count or 0) * 30
            }

            for area, mins in carpet_breakdown.items():
                if mins > 0:
                    log_debug_event(record_id, "BACKEND", f"Carpet {area.title()} Time", f"+{mins} mins")
                base_minutes += mins

        log_debug_event(record_id, "BACKEND", "Base Time Calculated", f"{base_minutes} mins")

    except Exception as e:
        logger.warning(f"⚠️ Error in base time calculation: {e}")
        log_debug_event(record_id, "BACKEND", "Calculation Error", f"Base time error: {e}")
        base_minutes = 0

    min_total_mins = base_minutes
    max_total_mins = base_minutes
    is_range = False
    note = None

    if data.special_request_minutes_min is not None and data.special_request_minutes_max is not None:
        min_total_mins += data.special_request_minutes_min
        max_total_mins += data.special_request_minutes_max
        is_range = True
        note = f"Includes {data.special_request_minutes_min}–{data.special_request_minutes_max} min for special request"
        log_debug_event(record_id, "BACKEND", "Special Request Time Added", f"{data.special_request_minutes_min}–{data.special_request_minutes_max} mins")

    calculated_hours = round(max_total_mins / 60, 2)
    base_price = round(calculated_hours * BASE_HOURLY_RATE, 2)

    weekend_fee = round(base_price * WEEKEND_SURCHARGE_PERCENT / 100, 2) if data.weekend_cleaning else 0.0
    after_hours_fee = round(base_price * AFTER_HOURS_SURCHARGE_PERCENT / 100, 2) if data.after_hours_cleaning else 0.0
    mandurah_fee = round(base_price * MANDURAH_SURCHARGE_PERCENT / 100, 2) if data.mandurah_property else 0.0

    log_debug_event(record_id, "BACKEND", "Surcharges", f"Weekend: ${weekend_fee}, After-hours: ${after_hours_fee}, Mandurah: ${mandurah_fee}")

    total_before_discount = base_price + weekend_fee + after_hours_fee + mandurah_fee

    total_discount_percent = SEASONAL_DISCOUNT_PERCENT
    if str(data.is_property_manager).strip().lower() in {"true", "yes", "1"}:
        total_discount_percent += PROPERTY_MANAGER_DISCOUNT

    discount_amount = round(total_before_discount * total_discount_percent / 100, 2)
    discounted_price = round(total_before_discount - discount_amount, 2)

    log_debug_event(record_id, "BACKEND", "Discount Applied", f"{total_discount_percent}% = -${discount_amount:.2f}")

    gst_amount = round(discounted_price * GST_PERCENT / 100, 2)
    total_with_gst = round(discounted_price + gst_amount, 2)

    log_debug_event(record_id, "BACKEND", "Quote Total Calculated", f"${total_with_gst:.2f} incl GST")

    return QuoteResponse(
        quote_id=data.quote_id,
        estimated_time_mins=max_total_mins,
        minimum_time_mins=min_total_mins if is_range else None,
        calculated_hours=calculated_hours,
        base_hourly_rate=BASE_HOURLY_RATE,
        discount_applied=discount_amount,
        gst_applied=gst_amount,
        mandurah_surcharge=mandurah_fee,
        after_hours_surcharge=after_hours_fee,
        weekend_surcharge=weekend_fee,
        price_per_session=discounted_price,
        total_price=total_with_gst,
        is_range=is_range,
        note=note
    )
