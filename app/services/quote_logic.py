# === quote_logic.py ===

from app.models.quote_models import QuoteRequest, QuoteResponse


def calculate_quote(data: QuoteRequest) -> QuoteResponse:
    BASE_HOURLY_RATE = 75
    SEASONAL_DISCOUNT_PERCENT = 10
    PROPERTY_MANAGER_DISCOUNT = 5
    GST_PERCENT = 10
    WEEKEND_SURCHARGE = 100
    MANDURAH_SURCHARGE = 50

    EXTRA_SERVICE_TIMES = {
        "wall_cleaning": 30,
        "balcony_cleaning": 20,
        "deep_cleaning": 60,
        "fridge_cleaning": 30,
        "range_hood_cleaning": 20,
        "garage_cleaning": 40,
    }

    # === Calculate Base Minutes ===
    base_minutes = (data.bedrooms_v2 * 40) + (data.bathrooms_v2 * 30)

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

    if str(data.furnished).lower() == "furnished":
        base_minutes += 60

    base_minutes += (data.carpet_bedroom_count or 0) * 30
    base_minutes += (data.carpet_mainroom_count or 0) * 45
    base_minutes += (data.carpet_study_count or 0) * 25
    base_minutes += (data.carpet_halway_count or 0) * 20
    base_minutes += (data.carpet_stairs_count or 0) * 35
    base_minutes += (data.carpet_other_count or 0) * 30

    # === Special Request Handling ===
    min_total_mins = base_minutes
    max_total_mins = base_minutes
    note = None
    is_range = False

    if data.special_request_minutes_min is not None and data.special_request_minutes_max is not None:
        min_total_mins += data.special_request_minutes_min
        max_total_mins += data.special_request_minutes_max
        note = f"Includes {data.special_request_minutes_min}–{data.special_request_minutes_max} min for special request"
        is_range = True

    # === Surcharge Calculation ===
    weekend_fee = WEEKEND_SURCHARGE if data.weekend_cleaning else 0
    after_hours_fee = data.after_hours_surcharge or 0
    mandurah_fee = MANDURAH_SURCHARGE if data.mandurah_property else 0

    # === Price Calculation ===
    calculated_hours = round(max_total_mins / 60, 2)
    base_price = calculated_hours * BASE_HOURLY_RATE

    total_before_discount = base_price + weekend_fee + after_hours_fee + mandurah_fee

    total_discount_percent = SEASONAL_DISCOUNT_PERCENT
    if str(data.is_property_manager).strip().lower() in {"true", "yes", "1"}:
        total_discount_percent += PROPERTY_MANAGER_DISCOUNT

    discount_amount = round(total_before_discount * (total_discount_percent / 100), 2)
    discounted_price = total_before_discount - discount_amount

    gst_amount = round(discounted_price * (GST_PERCENT / 100), 2)
    total_with_gst = round(discounted_price + gst_amount, 2)

    # === Final Response ===
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
