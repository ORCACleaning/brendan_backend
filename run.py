import logging
import os
from fastapi import FastAPI
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware  # Import CORSMiddleware

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
    allow_origins=["*"],  # Allow all origins or specify your website URL for security
    allow_credentials=True,
    allow_methods=["*"],  # Allow all methods (GET, POST, etc.)
    allow_headers=["*"],  # Allow all headers
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
if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(encoding="utf-8")

    # ✅ Test PDF data
    data = {
        "quote_id": "VAC-LOGOTEST01",
        "suburb": "Subiaco",
        "customer_name": "John Smith",
        "customer_phone": "0412 345 678",
        "customer_address": "12 Example Street, Subiaco WA 6008",
        "business_name": "Smith Realty",
        "bedrooms": 3,
        "bathrooms": 2,
        "furnished": "Yes",
        "oven_cleaning": True,
        "carpet_bedroom_count": 2,  # ✅ Updated
        "carpet_mainroom_count": 1,  # ✅ Updated
        "wall_cleaning": True,
        "balcony_cleaning": False,
        "window_cleaning": True,
        "deep_cleaning": True,
        "fridge_cleaning": False,
        "range_hood_cleaning": True,
        "garage_cleaning": False,
        "after_hours": False,
        "weekend_cleaning": True,
        "mandurah_property": False,
        "is_property_manager": True,
        "base_hourly_rate": 75.00,
        "minimum_time_mins": 280,
        "estimated_time_mins": 310,
        "is_range": True,
        "weekend_surcharge": 100.00,
        "after_hours_surcharge": 0.00,
        "mandurah_surcharge": 0.00,
        "discount_applied": 73.16,
        "gst_applied": 41.46,
        "total_price": 456.05,
        "note": "Includes 30–60 min for special request",
        "logo_base64": open("app/static/orca_logo.b64.txt", "r").read(),
    }


    output_path = generate_quote_pdf(data)
    print(f"✅ PDF generated at: {output_path}")

    uvicorn.run("run:app", host="0.0.0.0", port=10000, reload=True, log_config=None, access_log=False)
