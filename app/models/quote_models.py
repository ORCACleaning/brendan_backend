from pydantic import BaseModel
from typing import Optional

# ✅ Input Model for Quote Request
class QuoteRequest(BaseModel):
    # 🏠 Basic Property Info
    suburb: str
    bedrooms_v2: int
    bathrooms_v2: int
    furnished: str  # "Furnished" / "Unfurnished"

    # 🧼 Standard Cleaning Options (Airtable checkboxes as "true"/"false")
    oven_cleaning: str
    window_cleaning: str
    window_count: Optional[int] = 0

    # 🧹 Carpet Cleaning (detailed breakdown)
    carpet_bedroom_count: Optional[int] = 0
    carpet_mainroom_count: Optional[int] = 0
    carpet_study_count: Optional[int] = 0
    carpet_halway_count: Optional[int] = 0
    carpet_stairs_count: Optional[int] = 0
    carpet_other_count: Optional[int] = 0

    # ➕ Optional Extras
    wall_cleaning: Optional[str] = "false"
    balcony_cleaning: Optional[str] = "false"
    deep_cleaning: Optional[str] = "false"
    fridge_cleaning: Optional[str] = "false"
    range_hood_cleaning: Optional[str] = "false"
    garage_cleaning: Optional[str] = "false"
    blind_cleaning: Optional[str] = "false"
    upholstery_cleaning: Optional[str] = "false"

    # ⏰ Surcharges & Scheduling
    after_hours_cleaning: Optional[str] = "false"
    weekend_cleaning: Optional[str] = "false"
    after_hours_surcharge: Optional[float] = 0.0
    weekend_surcharge: Optional[float] = 0.0
    mandurah_property: Optional[str] = "false"
    mandurah_surcharge: Optional[float] = 0.0

    # 🏢 Real Estate / Agent
    is_property_manager: Optional[str] = "false"
    real_estate_name: Optional[str] = None

    # 🤖 Special Requests
    special_requests: Optional[str] = None
    special_request_minutes_min: Optional[int] = None
    special_request_minutes_max: Optional[int] = None

    # 👤 Personal Info
    customer_name: Optional[str] = None
    customer_email: Optional[str] = None
    customer_phone: Optional[str] = None

    # 📌 Additional Fields (Missing Previously)
    quote_notes: Optional[str] = None
    message_log: Optional[str] = None

    # 🧠 System Fields
    quote_stage: Optional[str] = "Gathering Info"
    quote_status: Optional[str] = "Pending"
    quote_id: Optional[str] = None
    quote_pdf_link: Optional[str] = None
    booking_url: Optional[str] = None
    privacy_acknowledged: Optional[str] = "false"


# ✅ Output Model for Quote Response
class QuoteResponse(BaseModel):
    quote_id: str
    calculated_hours: float
    base_hourly_rate: float
    discount_applied: float
    gst_applied: float
    mandurah_surcharge: float
    after_hours_surcharge: float
    weekend_surcharge: float
    price_per_session: float
    total_price: float
    is_range: bool
    estimated_time_mins: Optional[int] = None
    minimum_time_mins: Optional[int] = None
    note: Optional[str] = None
