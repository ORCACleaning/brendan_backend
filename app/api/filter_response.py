from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import re

router = APIRouter()

# Define request schema
class UserMessage(BaseModel):
    message: str

# Define response schema
class FilteredResponse(BaseModel):
    property: str
    value: str

# ✅ Property Mapping (Define expected formats)
PROPERTY_MAP = {
    "suburb": r"suburb|area|location|place",
    "bedrooms": r"bedroom|bedrooms|room|rooms",
    "bathrooms": r"bathroom|bathrooms|toilet|washroom",
    "oven_cleaning": r"oven",
    "carpet_cleaning": r"carpet",
    "furnished": r"furnished|unfurnished",
    "special_requests": r"special|request|extra"
}

# ✅ Extract relevant data
@router.post("/filter-response", response_model=FilteredResponse)
async def filter_response(user_message: UserMessage):
    message = user_message.message.lower()

    for property_name, pattern in PROPERTY_MAP.items():
        if re.search(pattern, message):
            value = extract_value(message, property_name)
            if value:
                return {"property": property_name, "value": value}
    
    raise HTTPException(status_code=400, detail="No relevant data found")

# ✅ Extract specific values (Basic parsing logic)
def extract_value(message, property_name):
    if property_name in ["bedrooms", "bathrooms"]:
        match = re.search(r"\d+", message)
        return match.group() if match else None

    if property_name in ["oven_cleaning", "carpet_cleaning", "furnished"]:
        if "yes" in message or "checked" in message:
            return "Yes"
        elif "no" in message or "unchecked" in message:
            return "No"

    return message.strip()
