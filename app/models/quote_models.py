from pydantic import BaseModel
from typing import Optional

# ✅ Input Model for Quote Request
class QuoteRequest(BaseModel):
    suburb: str
    bedrooms_v2: int
    bathrooms_v2: int
    oven_cleaning_v2: bool
    carpet_cleaning_v2: bool
    furnished_v2: str
    special_requests_v2: Optional[str] = None
    special_request_minutes_min_v2: Optional[int] = None
    special_request_minutes_max_v2: Optional[int] = None
    after_hours_v2: bool
    weekend_cleaning_v2: bool
    mandurah_property_v2: bool
    is_property_manager_v2: Optional[bool] = False  # Updated ✅

    # ✅ Updated Fields with _v2 Suffix for Additional Services
    wall_cleaning_v2: Optional[bool] = False
    balcony_cleaning_v2: Optional[bool] = False
    window_cleaning_v2: Optional[bool] = False
    window_count_v2: Optional[int] = 0  # Number of windows for window cleaning
    deep_cleaning_v2: Optional[bool] = False
    fridge_cleaning_v2: Optional[bool] = False
    range_hood_cleaning_v2: Optional[bool] = False
    garage_cleaning_v2: Optional[bool] = False


# ✅ Output Model for Quote Response
class QuoteResponse(BaseModel):
    quote_id: str
    estimated_time_mins: Optional[int] = None
    minimum_time_mins: Optional[int] = None
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
    note: Optional[str] = None
