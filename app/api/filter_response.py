from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import re

router = APIRouter()

# ✅ Define request and response schemas
class UserMessage(BaseModel):
    message: str

class FilteredResponse(BaseModel):
    properties: list[dict]


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
    "window_cleaning": r"window|windows",
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
    extracted_properties = []

    # ✅ Check all property patterns
    for property_name, pattern in PROPERTY_MAP.items():
        if re.search(pattern, message):
            value = extract_value(message, property_name)
            if value is not None:
                extracted_properties.append({"property": property_name, "value": value})

    if not extracted_properties:
        raise HTTPException(status_code=400, detail="No relevant data found")

    return {"properties": extracted_properties}


# ✅ Extract specific values for each property
def extract_value(message, property_name):
    # ✅ Extract number of windows for `window_v2`
    if property_name == "window_v2":
        match = re.search(r"(\d+)\s*window[s]*", message)
        return match.group(1) if match else "0"

    # ✅ Extract number of bedrooms and bathrooms dynamically
    if property_name in ["bedrooms_v2", "bathrooms_v2"]:
        match = re.search(r"(\d+)\s*" + property_name.replace("_v2", ""), message)
        return match.group(1) if match else None

    # ✅ Handle boolean properties with yes/no or checked/unchecked
    if property_name in ["oven_cleaning", "carpet_cleaning", "furnished", "wall_cleaning",
                         "balcony_cleaning", "window_cleaning", "deep_cleaning", "fridge_cleaning",
                         "range_hood_cleaning", "garage_cleaning"]:
        if "yes" in message or "checked" in message or "can you" in message:
            return "Yes"
        elif "no" in message or "unchecked" in message:
            return "No"

    # ✅ Return the raw message as a fallback for string-based properties
    return message.strip()
