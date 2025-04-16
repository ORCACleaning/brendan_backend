# === Calculate Quote Function ===
from app.models.quote_models import QuoteRequest, QuoteResponse
from app.config import logger
from app.api.filter_response import log_debug_event  # ✅ Logging import

def calculate_quote(data: QuoteRequest) -> QuoteResponse:
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

    # === Base Time Calculation ===
    base_minutes = 0
    try:
        base_minutes += (data.bedrooms_v2 or 0) * 40
        base_minutes += (data.bathrooms_v2 or 0) * 30

        for service, time in EXTRA_SERVICE_TIMES.items():
            if getattr(data, service, False):
                base_minutes += time

        if data.window_cleaning:
            base_minutes += (data.window_count or 0) * 10
            if data.blind_cleaning:
                base_minutes += (data.window_count or 0) * 10

        if data.oven_cleaning:
            base_minutes += 30

        if data.upholstery_cleaning:
            base_minutes += 45

        if str(data.furnished).strip().lower() == "furnished":
            base_minutes += 60

        base_minutes += (data.carpet_bedroom_count or 0) * 30
        base_minutes += (data.carpet_mainroom_count or 0) * 45
        base_minutes += (data.carpet_study_count or 0) * 25
        base_minutes += (data.carpet_halway_count or 0) * 20
        base_minutes += (data.carpet_stairs_count or 0) * 35
        base_minutes += (data.carpet_other_count or 0) * 30

        log_debug_event(record_id, "BACKEND", "Base Time Calculated", f"{base_minutes} mins")

    except Exception as e:
        logger.warning(f"⚠️ Error in base time calculation: {e}")
        base_minutes = 0
        log_debug_event(record_id, "BACKEND", "Calculation Error", f"Base time error: {e}")

    # === Special Request Handling ===
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

    # === Price Calculation ===
    calculated_hours = round(max_total_mins / 60, 2)
    base_price = round(calculated_hours * BASE_HOURLY_RATE, 2)

    # === Surcharge Handling ===
    weekend_fee = round(base_price * WEEKEND_SURCHARGE_PERCENT / 100, 2) if data.weekend_cleaning else 0.0
    after_hours_fee = round(base_price * AFTER_HOURS_SURCHARGE_PERCENT / 100, 2) if data.after_hours_cleaning else 0.0
    mandurah_fee = round(base_price * MANDURAH_SURCHARGE_PERCENT / 100, 2) if data.mandurah_property else 0.0

    total_before_discount = base_price + weekend_fee + after_hours_fee + mandurah_fee

    # === Discount Handling ===
    total_discount_percent = SEASONAL_DISCOUNT_PERCENT
    if str(data.is_property_manager).strip().lower() in {"true", "yes", "1"}:
        total_discount_percent += PROPERTY_MANAGER_DISCOUNT

    discount_amount = round(total_before_discount * total_discount_percent / 100, 2)
    discounted_price = round(total_before_discount - discount_amount, 2)

    log_debug_event(record_id, "BACKEND", "Discount Applied", f"{total_discount_percent}% = -${discount_amount:.2f}")

    # === GST Calculation ===
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
