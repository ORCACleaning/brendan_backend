from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import re

router = APIRouter()

# ✅ Define request and response schemas
class UserMessage(BaseModel):
    message: str

class FilteredResponse(BaseModel):
    properties: list

# ✅ Property Mapping to Match Customer Input
PROPERTY_MAP = {
    "suburb": r"suburb|area|location|place",
    "bedrooms_v2": r"bedroom|bedrooms|room|rooms",
    "bathrooms_v2": r"bathroom|bathrooms|toilet|washroom",
    "oven_cleaning": r"oven",
    "carpet_cleaning": r"carpet",
    "furnished": r"furnished|unfurnished",
    "special_requests": r"special|request|extra",
    "wall_cleaning": r"wall|walls",
    "balcony_cleaning": r"balcony",
    "window_v2": r"(\d+)\s*window[s]*",  # ✅ Extract number of windows dynamically
    "deep_cleaning": r"deep clean|intense clean",
    "fridge_cleaning": r"fridge|refrigerator",
    "range_hood_cleaning": r"range hood|hood",
    "garage_cleaning": r"garage"
}

# ✅ Extract and clean relevant data from user message
@router.post("/filter-response", response_model=FilteredResponse)
async def filter_response(user_message: UserMessage):
    message = user_message.message.lower()
    matched_properties = []

    for property_name, pattern in PROPERTY_MAP.items():
        if re.search(pattern, message):
            value = extract_value(message, property_name)
            if value:
                matched_properties.append({"property": property_name, "value": value})

    if not matched_properties:
        raise HTTPException(status_code=400, detail="No relevant data found")

    return {"properties": matched_properties}

# ✅ Extract specific values for each property
def extract_value(message, property_name):
    if property_name == "window_v2":
        match = re.search(r"(\d+)\s*window[s]*", message)
        return match.group(1) if match else "0"

    if property_name in ["bedrooms_v2", "bathrooms_v2"]:
        match = re.search(r"\d+", message)
        return match.group() if match else None

    if property_name in ["oven_cleaning", "carpet_cleaning", "furnished", "wall_cleaning",
                         "balcony_cleaning", "window_cleaning", "deep_cleaning", "fridge_cleaning",
                         "range_hood_cleaning", "garage_cleaning"]:
        if "yes" in message or "checked" in message:
            return "Yes"
        elif "no" in message or "unchecked" in message:
            return "No"

    return message.strip()
