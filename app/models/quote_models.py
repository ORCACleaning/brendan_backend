from pydantic import BaseModel
from typing import Optional

class QuoteRequest(BaseModel):
    suburb: str
    bedrooms: int
    bathrooms: int
    oven_cleaning: bool
    carpet_cleaning: bool
    furnished: str
    special_requests: Optional[str] = None
    special_request_minutes_min: Optional[int] = None
    special_request_minutes_max: Optional[int] = None
    after_hours: bool
    weekend_cleaning: bool
    mandurah_property: bool
    is_property_manager: Optional[bool] = False  # New field ✅

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
