import os
import requests
from app.models.quote_models import QuoteRequest, QuoteResponse
from dotenv import load_dotenv

load_dotenv()

# ✅ Airtable Secure Config
airtable_base_id = os.getenv("AIRTABLE_BASE_ID")
airtable_api_key = os.getenv("AIRTABLE_API_KEY")
airtable_table = "Vacate Quotes"

def get_next_quote_id(prefix="VC"):
    url = f"https://api.airtable.com/v0/{airtable_base_id}/{airtable_table}"
    headers = {"Authorization": f"Bearer {airtable_api_key}"}
    params = {
        "filterByFormula": f'STARTS_WITH(quote_id, "{prefix}-")',
        "fields[]": "quote_id",
        "sort[0][field]": "quote_id",
        "sort[0][direction]": "desc",
        "pageSize": 1
    }
    response = requests.get(url, headers=headers, params=params)
    records = response.json().get("records", [])
    if records:
        last_id = records[0]["fields"]["quote_id"].split("-")[1]
        next_id = int(last_id) + 1
    else:
        next_id = 1
    return f"{prefix}-{str(next_id).zfill(6)}"

# ✅ Optional: Service-level calculator
def get_individual_service_cost(service_name: str, quantity: int = 1) -> float:
    BASE_HOURLY_RATE = 75
    SERVICE_MINUTES = {
        "oven_cleaning": 30,
        "carpet_cleaning": 40,
        "furnished": 60,
        "window_cleaning": 10,           # per window
        "wall_cleaning": 30,
        "balcony_cleaning": 20,
        "deep_cleaning": 60,
        "fridge_cleaning": 30,           # ✅ Updated
        "range_hood_cleaning": 20,       # ✅ Updated
        "garage_cleaning": 40,
        "blind_cleaning": 10,            # ✅ Added: per blind
        "upholstery_cleaning": 45        # estimate
    }
    minutes = SERVICE_MINUTES.get(service_name, 0) * quantity
    return round((minutes / 60) * BASE_HOURLY_RATE, 2)

def calculate_quote(data: QuoteRequest) -> QuoteResponse:
    BASE_HOURLY_RATE = 75
    SEASONAL_DISCOUNT_PERCENT = 10
    PROPERTY_MANAGER_DISCOUNT = 5
    GST_PERCENT = 10
    WEEKEND_SURCHARGE = 100
    AFTER_HOURS_SURCHARGE = 75
    MANDURAH_SURCHARGE = 50

    EXTRA_SERVICE_TIMES = {
        "wall_cleaning": 30,
        "balcony_cleaning": 20,
        "deep_cleaning": 60,
        "fridge_cleaning": 30,            # ✅ Updated
        "range_hood_cleaning": 20,        # ✅ Updated
        "garage_cleaning": 40
    }

    base_minutes = (data.bedrooms_v2 * 40) + (data.bathrooms_v2 * 30)

    for service, time in EXTRA_SERVICE_TIMES.items():
        if getattr(data, service, False):
            base_minutes += time

    # ✅ Window cleaning
    window_minutes = 0
    if data.window_cleaning:
        count = data.windows_v2 if data.windows_v2 else 0
        window_minutes = count * 10
        base_minutes += window_minutes

        # ✅ Blind cleaning (assume 1 blind per window)
        if data.blind_cleaning:
            blind_minutes = count * 10
            base_minutes += blind_minutes

    if data.oven_cleaning:
        base_minutes += 30
    if data.carpet_cleaning:
        base_minutes += 40
    if data.furnished.lower() == "yes":
        base_minutes += 60

    # ✅ Special Request
    is_range = data.special_request_minutes_min is not None and data.special_request_minutes_max is not None
    min_total_mins = base_minutes
    max_total_mins = base_minutes
    note = None

    if is_range:
        min_total_mins += data.special_request_minutes_min
        max_total_mins += data.special_request_minutes_max
        note = f"Includes {data.special_request_minutes_min}–{data.special_request_minutes_max} min for special request"

    calculated_hours = round(max_total_mins / 60, 2)
    base_price = calculated_hours * BASE_HOURLY_RATE

    # ✅ Weekend and after-hours logic
    weekend_fee = WEEKEND_SURCHARGE if data.weekend_cleaning else 0
    after_hours_fee = 0
    if data.after_hours and not data.weekend_cleaning:
        after_hours_fee = AFTER_HOURS_SURCHARGE

    mandurah_fee = MANDURAH_SURCHARGE if data.mandurah_property else 0

    total_before_discount = base_price + weekend_fee + after_hours_fee + mandurah_fee

    total_discount_percent = SEASONAL_DISCOUNT_PERCENT
    if data.is_property_manager:
        total_discount_percent += PROPERTY_MANAGER_DISCOUNT

    discount_amount = round(total_before_discount * (total_discount_percent / 100), 2)
    discounted_price = total_before_discount - discount_amount

    gst_amount = round(discounted_price * (GST_PERCENT / 100), 2)
    total_with_gst = round(discounted_price + gst_amount, 2)

    quote_id = get_next_quote_id("VC")

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
