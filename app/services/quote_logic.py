import uuid
from app.models.quote_models import QuoteRequest, QuoteResponse

def calculate_quote(data: QuoteRequest) -> QuoteResponse:
    # Constants
    BASE_HOURLY_RATE = 75
    SEASONAL_DISCOUNT_PERCENT = 10
    PROPERTY_MANAGER_DISCOUNT = 5
    GST_PERCENT = 10
    WEEKEND_SURCHARGE = 100
    AFTER_HOURS_SURCHARGE = 75
    MANDURAH_SURCHARGE = 50

    # Base time estimation
    base_minutes = (data.bedrooms * 40) + (data.bathrooms * 30)
    if data.oven_cleaning:
        base_minutes += 30
    if data.carpet_cleaning:
        base_minutes += 40
    if data.furnished.lower() == "yes":
        base_minutes += 60

    # Special requests
    is_range = data.special_request_minutes_min is not None and data.special_request_minutes_max is not None
    min_total_mins = base_minutes
    max_total_mins = base_minutes

    note = None
    if is_range:
        min_total_mins += data.special_request_minutes_min
        max_total_mins += data.special_request_minutes_max
        note = f"Includes {data.special_request_minutes_min}–{data.special_request_minutes_max} min for special request"
    else:
        max_total_mins = base_minutes

    # Calculate hours
    calculated_hours = round(max_total_mins / 60, 2)

    # Base session price
    base_price = calculated_hours * BASE_HOURLY_RATE

    # Surcharges
    weekend_fee = WEEKEND_SURCHARGE if data.weekend_cleaning else 0
    after_hours_fee = AFTER_HOURS_SURCHARGE if data.after_hours else 0
    mandurah_fee = MANDURAH_SURCHARGE if data.mandurah_property else 0

    total_before_discount = base_price + weekend_fee + after_hours_fee + mandurah_fee

    # Discounts: seasonal + property manager
    total_discount_percent = SEASONAL_DISCOUNT_PERCENT
    if data.is_property_manager:
        total_discount_percent += PROPERTY_MANAGER_DISCOUNT

    discount_amount = round(total_before_discount * (total_discount_percent / 100), 2)
    discounted_price = total_before_discount - discount_amount

    # GST
    gst_amount = round(discounted_price * (GST_PERCENT / 100), 2)
    total_with_gst = round(discounted_price + gst_amount, 2)

    # Quote ID
    quote_id = f"VAC-{str(uuid.uuid4())[:8]}"

    return QuoteResponse(
        quote_id=quote_id,
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
