import logging
from fastapi import FastAPI
from app.services.pdf_generator import generate_quote_pdf
from app.store_customer import router as store_customer_router
from app.api.quote import router as quote_router
from app.brendan_chat import router as brendan_chat_router
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()


app = FastAPI()

# ✅ Default route to prevent 404
@app.get("/")
def read_root():
    return {"message": "Welcome to Brendan Backend! 🎉"}

# ✅ Health check route for testing
@app.get("/ping")
def ping():
    return {"ping": "pong"}

# ✅ Register the new endpoints
app.include_router(quote_router)
app.include_router(store_customer_router)
app.include_router(brendan_chat_router)

# ✅ Only run locally, not on the server
if __name__ == "__main__":
    import uvicorn

    # ✅ Set UTF-8 encoding to fix emoji display
    logging.basicConfig(encoding="utf-8")

    # ✅ Test data for PDF generation
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
        "carpet_cleaning": False,
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
        # Embedded logo (read from file)
        "logo_base64": open("app/static/orca_logo.b64.txt", "r").read(),
    }

    # ✅ Generate PDF for testing
    output_path = generate_quote_pdf(data)
    print(f"✅ PDF successfully generated at: {output_path}")

    # ✅ Start Uvicorn for local testing
    uvicorn.run("run:app", host="0.0.0.0", port=10000, reload=True, log_config=None, access_log=False)
