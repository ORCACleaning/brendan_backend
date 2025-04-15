from pydantic import BaseModel
from typing import Optional


# === Input Model for Quote Request ===
class QuoteRequest(BaseModel):
    # === Property Details ===
    suburb: str
    bedrooms_v2: int
    bathrooms_v2: int
    furnished: str  # "Furnished" or "Unfurnished"

    # === Standard Cleaning Options ===
    oven_cleaning: bool
    window_cleaning: bool
    window_count: Optional[int] = 0
    blind_cleaning: bool

    # === Carpet Cleaning Breakdown ===
    carpet_bedroom_count: Optional[int] = 0
    carpet_mainroom_count: Optional[int] = 0
    carpet_study_count: Optional[int] = 0
    carpet_halway_count: Optional[int] = 0
    carpet_stairs_count: Optional[int] = 0
    carpet_other_count: Optional[int] = 0
    carpet_cleaning: Optional[bool] = False  # Auto-filled by backend logic

    # === Optional Extra Services ===
    wall_cleaning: bool
    balcony_cleaning: bool
    deep_cleaning: bool
    fridge_cleaning: bool
    range_hood_cleaning: bool
    garage_cleaning: bool
    upholstery_cleaning: bool

    # === Surcharges & Conditions ===
    after_hours_cleaning: bool
    weekend_cleaning: bool
    mandurah_property: bool
    after_hours_surcharge: Optional[float] = 0.0  # Final applied fee in $
    weekend_surcharge: Optional[float] = 0.0
    mandurah_surcharge: Optional[float] = 0.0

    # === Real Estate Details ===
    is_property_manager: bool
    real_estate_name: Optional[str] = None

    # === Special Requests Handling ===
    special_requests: Optional[str] = ""
    special_request_minutes_min: Optional[int] = 0
    special_request_minutes_max: Optional[int] = 0

    # === Customer Contact Details ===
    customer_name: Optional[str] = None
    customer_email: Optional[str] = None
    customer_phone: Optional[str] = None

    # === System & Logging Fields ===
    quote_notes: Optional[str] = None
    message_log: Optional[str] = None
    quote_stage: Optional[str] = "Gathering Info"
    quote_status: Optional[str] = "Pending"
    quote_id: Optional[str] = None
    quote_pdf_link: Optional[str] = None
    booking_url: Optional[str] = None
    privacy_acknowledged: Optional[bool] = False


# === Output Model for Quote Response ===
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
