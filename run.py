# === Imports ===
import logging
import os
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from openai import OpenAI
from app.utils.logging_utils import log_debug_event
from app.api.quote import router as quote_router
from app.api.filter_response import router as filter_response_router
from app.store_customer import router as store_customer_router
from app import auto_fixer  # ✅ AI Auto-Fix Commit System

# === Load environment variables ===
load_dotenv()

# === Load API Keys ===
api_key = os.getenv("OPENAI_API_KEY")
airtable_key = os.getenv("AIRTABLE_API_KEY")
airtable_base = os.getenv("AIRTABLE_BASE_ID")

# === Set logging config for full stdout/stderr capture ===
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler()
    ]
)

logger = logging.getLogger("BrendanStartup")

# === Key Load Debug Logging ===
try:
    if api_key:
        logger.info(f"✅ Loaded OpenAI Key: {api_key}")
        log_debug_event(None, "LOCAL", "OpenAI Key Loaded", f"Key = {api_key}")
    else:
        logger.error("❌ ERROR: OPENAI_API_KEY not loaded!")
        log_debug_event(None, "LOCAL", "OpenAI Key Error", "OPENAI_API_KEY not found in .env")
except Exception as e:
    logger.warning(f"⚠️ Error logging OpenAI key load: {e}")

try:
    if airtable_key and airtable_base:
        logger.info(f"✅ Airtable Key: {airtable_key}")
        logger.info(f"✅ Airtable Base ID: {airtable_base}")
        log_debug_event(None, "LOCAL", "Airtable Credentials Loaded", f"Key = {airtable_key}, Base = {airtable_base}")
    else:
        logger.error("❌ ERROR: Airtable credentials not loaded! Check .env.")
        log_debug_event(None, "LOCAL", "Airtable Credentials Error", "Missing airtable_key or base")
except Exception as e:
    logger.warning(f"⚠️ Error logging Airtable credential load: {e}")

# === OpenAI Client ===
client = OpenAI(api_key=api_key)

# === FastAPI App ===
app = FastAPI(
    title="Brendan API",
    description="Backend for Orca Cleaning's AI Quote Assistant - Brendan",
    version="1.0.0"
)

# === CORS ===
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# === Routers ===
app.include_router(filter_response_router)
app.include_router(quote_router)
app.include_router(store_customer_router)
app.include_router(auto_fixer.router)

# === Root Endpoint ===
@app.get("/")
def read_root():
    try:
        log_debug_event(None, "LOCAL", "Ping Root", "Root endpoint accessed")
    except Exception as e:
        logger.warning(f"⚠️ Error logging root ping: {e}")
    return JSONResponse(content={"message": "Welcome to Brendan Backend! 🎉"})

# === Health Check ===
@app.get("/ping")
def ping():
    try:
        log_debug_event(None, "LOCAL", "Ping /ping", "Health check requested")
    except Exception as e:
        logger.warning(f"⚠️ Error logging ping: {e}")
    return {"ping": "pong"}

# === Optional: Test PDF Gen ===
from app.services.pdf_generator import generate_quote_pdf
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

# === Run ===
if __name__ == "__main__":
    try:
        log_debug_event(None, "LOCAL", "Test Mode", "Attempting PDF generation...")
        data = get_test_pdf_data()
        path = generate_quote_pdf(data)
        print(f"✅ PDF generated at: {path}")
        log_debug_event(None, "LOCAL", "PDF Generation Successful", path)
    except Exception as e:
        print(f"❌ PDF generation failed: {e}")
        try:
            log_debug_event(None, "LOCAL", "PDF Generation Error", str(e))
        except Exception as fallback:
            print(f"⚠️ Fallback logging failed: {fallback}")

    import uvicorn
    uvicorn.run(
        "run:app",
        host="0.0.0.0",
        port=10000,
        reload=True,
        access_log=True,
        log_level="debug"
    )
