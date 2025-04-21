import os
from weasyprint import HTML
from jinja2 import Environment, FileSystemLoader, select_autoescape
from app.api.field_rules import FIELD_MAP

# === Paths for PDF Generation ===
STATIC_PDF_DIR = "/opt/render/project/public/quotes"
BASE_URL = "https://quote.orcacleaning.com.au/quotes"

# === Load Jinja Template ===
template_dir = os.path.join(os.path.dirname(__file__), "templates")
env = Environment(
    loader=FileSystemLoader(template_dir),
    autoescape=select_autoescape(['html', 'xml'])
)
template = env.get_template("quote_template.html")


def generate_quote_pdf(data: dict) -> str:
    """
    Generate a PDF quote using customer data and save it in the public folder.
    Returns the public Render URL of the generated PDF.
    """

    # === Validate Minimum Required Fields ===
    required = ["quote_id", "customer_name", "customer_email", "total_price", "estimated_time_mins", "quote_stage"]
    for field in required:
        if field not in data or data[field] in [None, "", False]:
            raise ValueError(f"Cannot generate PDF — missing required field: {field}")

    if data.get("quote_stage") not in ["Quote Calculated", "Personal Info Received"]:
        raise ValueError(f"PDF cannot be generated — invalid quote_stage: {data.get('quote_stage')}")

    os.makedirs(STATIC_PDF_DIR, exist_ok=True)

    # === Clean and normalize input data ===
    cleaned = {}
    for key, val in data.items():
        if val in [None, ""]:
            continue
        readable_key = FIELD_MAP.get(key, key)
        cleaned[readable_key] = val

    # === Required fallback values for template placeholders ===
    fallback_fields = {
        "quote_id": "N/A",
        "customer_name": "Valued Customer",
        "property_address": data.get("suburb", "Unknown Suburb"),
        "bedrooms_v2": "0",
        "bathrooms_v2": "0",
        "total_price": "TBC",
        "price_per_session": "TBC",
        "base_hourly_rate": "N/A",
        "estimated_time_mins": "N/A",
        "discount_applied": "None",
        "gst_applied": "N/A",
        "quote_summary": "No breakdown available.",
        "furnished": "Not specified",
        "quote_stage": data.get("quote_stage", ""),
        "carpet_cleaning": data.get("carpet_cleaning", ""),
        "garage_cleaning": data.get("garage_cleaning", False),
        "window_cleaning": data.get("window_cleaning", False),
        "oven_cleaning": data.get("oven_cleaning", False),
        "upholstery_cleaning": data.get("upholstery_cleaning", False),
        "after_hours_cleaning": data.get("after_hours_cleaning", False),
        "weekend_cleaning": data.get("weekend_cleaning", False),
        "special_requests": data.get("special_requests", "None")
    }

    for field, default in fallback_fields.items():
        if field not in cleaned:
            cleaned[field] = default

    # === Format estimated time nicely ===
    try:
        mins = int(cleaned.get("estimated_time_mins", 0))
        hrs = round(mins / 60, 2)
        cleaned["estimated_duration_hr"] = f"{hrs} hours"
    except:
        cleaned["estimated_duration_hr"] = "N/A"

    # === Format price ===
    try:
        price = float(cleaned.get("total_price", 0))
        cleaned["formatted_price"] = f"${price:,.2f} incl. GST"
    except:
        cleaned["formatted_price"] = "N/A"

    # === Format job breakdown ===
    job_items = []

    if cleaned.get("carpet_cleaning") == "Yes":
        for room_type in [
            "carpet_mainroom_count", "carpet_smallroom_count",
            "carpet_hallway_count", "carpet_stairs_count"
        ]:
            val = data.get(room_type)
            if isinstance(val, int) and val > 0:
                job_items.append(f"{val} × {FIELD_MAP.get(room_type, room_type).replace('_', ' ').capitalize()}")

    for addon in [
        "oven_cleaning", "garage_cleaning", "window_cleaning",
        "upholstery_cleaning", "after_hours_cleaning", "weekend_cleaning"
    ]:
        if data.get(addon):
            job_items.append(FIELD_MAP.get(addon, addon).replace('_', ' ').capitalize())

    if cleaned.get("special_requests") not in ["", "None", None, False]:
        job_items.append("Special Requests")

    cleaned["job_items"] = job_items if job_items else ["Standard Vacate Clean"]

    # === Generate HTML and PDF ===
    try:
        quote_id = data.get("quote_id", "missing-id")
        html_out = template.render(**cleaned)
        pdf_path = f"{STATIC_PDF_DIR}/{quote_id}.pdf"
        HTML(string=html_out).write_pdf(pdf_path)
        return f"{BASE_URL}/{quote_id}.pdf"
    except Exception as e:
        raise RuntimeError(f"PDF generation failed: {e}")
