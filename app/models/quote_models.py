from pydantic import BaseModel
from typing import Optional

# ✅ Input Model for Quote Request
class QuoteRequest(BaseModel):
    # 🏠 Basic Property Info
    suburb: str
    bedrooms_v2: int
    bathrooms_v2: int
    furnished: str  # "Yes" / "No"

    # 🧼 Standard Cleaning Options
    oven_cleaning: bool
    window_cleaning: bool
    windows_v2: Optional[int] = 0
    window_count: Optional[int] = 0  # Alias for consistency

    # 🧹 Carpet Cleaning (per-room breakdown)
    carpet_cleaning: bool
    carpet_bedroom_count: Optional[int] = 0
    carpet_main_count: Optional[int] = 0
    carpet_study_count: Optional[int] = 0
    carpet_hallway_count: Optional[int] = 0
    carpet_stairs_count: Optional[int] = 0
    carpet_other_count: Optional[int] = 0

    # ➕ Optional Extras
    wall_cleaning: Optional[bool] = False
    balcony_cleaning: Optional[bool] = False
    deep_cleaning: Optional[bool] = False
    fridge_cleaning: Optional[bool] = False
    range_hood_cleaning: Optional[bool] = False
    garage_cleaning: Optional[bool] = False
    blind_cleaning: Optional[bool] = False
    upholstery_cleaning: Optional[bool] = False

    # ⏰ Conditions & Scheduling
    after_hours: Optional[bool] = False
    weekend_cleaning: Optional[bool] = False
    mandurah_property: Optional[bool] = False
    is_property_manager: Optional[bool] = False
    real_estate_name: Optional[str] = None

    # 🤖 Special Requests (AI-handled)
    special_requests: Optional[str] = None
    special_request_minutes_min: Optional[int] = None
    special_request_minutes_max: Optional[int] = None

    # 👤 Personal Info (later stage)
    customer_name: Optional[str] = None
    customer_email: Optional[str] = None
    customer_phone: Optional[str] = None

    # 🧠 System Fields
    quote_stage: Optional[str] = "Gathering Info"
    quote_status: Optional[str] = "Pending"
    quote_id: Optional[str] = None
    quote_pdf_link: Optional[str] = None
    booking_url: Optional[str] = None
    privacy_acknowledged: Optional[str] = None


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
