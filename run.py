import logging
import os
from fastapi import FastAPI
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware

# ✅ Load environment variables FIRST
load_dotenv()

from app.services.pdf_generator import generate_quote_pdf
from app.store_customer import router as store_customer_router
from app.api.quote import router as quote_router
from app.brendan_chat import router as brendan_chat_router
from app.api.filter_response import router as filter_response_router
from openai import OpenAI

# ✅ Load API Keys
api_key = os.getenv("OPENAI_API_KEY")
airtable_key = os.getenv("AIRTABLE_API_KEY")
airtable_base = os.getenv("AIRTABLE_BASE_ID")

# ✅ Debug loaded keys (partial masking)
if api_key:
    print(f"✅ Loaded OpenAI Key: {api_key[:10]}...{api_key[-5:]}")
else:
    print("❌ ERROR: OPENAI_API_KEY not loaded!")

if airtable_key and airtable_base:
    print(f"✅ Airtable Key and Base ID loaded successfully.")
else:
    print("❌ ERROR: Airtable credentials not loaded! Check .env.")

# ✅ Initialize OpenAI client
client = OpenAI(api_key=api_key)

# ✅ FastAPI app init
app = FastAPI()

# ✅ CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ✅ Register endpoints
app.include_router(filter_response_router)
app.include_router(quote_router)
app.include_router(store_customer_router)
app.include_router(brendan_chat_router)

# ✅ Root
@app.get("/")
def read_root():
    return {"message": "Welcome to Brendan Backend! 🎉"}

# ✅ Health check
@app.get("/ping")
def ping():
    return {"ping": "pong"}

# ✅ Local only
def get_test_pdf_data():
    return {
        "quote_id": "VAC-LOGOTEST01",
        "suburb": "Subiaco",
        "customer_name": "John Smith",
        "phone": "0412 345 678",
        "property_address": "12 Example Street, Subiaco WA 6008",
        "business_name": "Smith Realty",
        "bedrooms_v2": 3,
        "bathrooms_v2": 2,
        "furnished": "Yes",
        "oven_cleaning": True,
        "carpet_bedroom_count": 2,
        "carpet_mainroom_count": 1,
        "carpet_study_count": 0,
        "carpet_halway_count": 1,
        "carpet_stairs_count": 0,
        "carpet_other_count": 0,
        "window_cleaning": True,
        "window_count": 6,
        "deep_cleaning": True,
        "fridge_cleaning": False,
        "range_hood_cleaning": True,
        "wall_cleaning": True,
        "garage_cleaning": False,
        "balcony_cleaning": False,
        "upholstery_cleaning": False,
        "after_hours_cleaning": False,
        "weekend_cleaning": True,
        "is_property_manager": True,
        "real_estate_name": "Smith Realty",
        "special_requests": "Please clean behind fridge",
        "special_request_minutes_min": 30,
        "special_request_minutes_max": 60,
        "hourly_rate": 75.00,
        "quote_time_estimate": 310,
        "discount_percent": 10.0,
        "gst_amount": 41.46,
        "final_price": 456.05,
        "quote_notes": "Includes 30–60 min for special request",
        "logo_base64": open("app/static/orca_logo.b64.txt", "r").read(),
    }

if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(encoding="utf-8")

    try:
        data = get_test_pdf_data()
        output_path = generate_quote_pdf(data)
        print(f"✅ PDF generated at: {output_path}")
    except Exception as e:
        print(f"❌ Failed to generate PDF: {e}")

    uvicorn.run("run:app", host="0.0.0.0", port=10000, reload=True, log_config=None, access_log=False)
