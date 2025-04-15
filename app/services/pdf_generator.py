import os
import uuid
import base64
from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML
from app.config import logger


def generate_quote_pdf(data: dict) -> (str, str):
    """
    Generate a PDF quote using WeasyPrint & Jinja2.
    Returns: (Absolute PDF Path, Public PDF URL)
    """

    # === Generate Safe Quote ID ===
    quote_id = data.get("quote_id") or f"VAC-{uuid.uuid4().hex[:8]}"
    filename = f"{quote_id}.pdf"
    output_path = f"app/static/quotes/{filename}"
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    pdf_url = f"https://orcacleaning.com.au/static/quotes/{filename}"

    logger.info(f"📄 Generating PDF Quote: {output_path}")

    # === Load Logo Base64 ===
    logo_path = "app/static/orca_logo.png"
    try:
        with open(logo_path, "rb") as f:
            logo_base64 = base64.b64encode(f.read()).decode("utf-8")
    except Exception as e:
        logger.error(f"❌ Failed to load logo: {e}")
        logo_base64 = ""

    data["logo_base64"] = logo_base64

    # === Load Template ===
    env = Environment(loader=FileSystemLoader("app/services/templates"))
    template = env.get_template("quote_template.html")

    # === Extra Services List ===
    extra_services = []

    if data.get("window_cleaning"):
        wc = int(data.get("window_count") or 0)
        extra_services.append(f"Window Cleaning ({wc} windows)" if wc else "Window Cleaning")

    carpet_map = [
        ("carpet_bedroom_count", "bedroom"),
        ("carpet_mainroom_count", "main room"),
        ("carpet_study_count", "study"),
        ("carpet_halway_count", "hallway"),
        ("carpet_stairs_count", "stairs"),
        ("carpet_other_count", "other area"),
    ]

    for field, label in carpet_map:
        count = int(data.get(field) or 0)
        if count > 0:
            extra_services.append(f"Carpet Steam Cleaning – {count} {label}(s)")

    extras_map = {
        "oven_cleaning": "Oven Cleaning",
        "garage_cleaning": "Garage/Shed Cleaning",
        "wall_cleaning": "Wall Cleaning",
        "balcony_cleaning": "Balcony Cleaning",
        "fridge_cleaning": "Fridge Cleaning",
        "range_hood_cleaning": "Range Hood Cleaning",
        "deep_cleaning": "Deep/Detail Cleaning",
        "blind_cleaning": "Blind/Curtain Cleaning",
        "upholstery_cleaning": "Upholstery Cleaning",
    }

    for field, label in extras_map.items():
        if data.get(field):
            extra_services.append(label)

    data["extra_services"] = ", ".join(extra_services) if extra_services else "None"

    # === Property Manager Note ===
    if data.get("is_property_manager"):
        agency = data.get("real_estate_name", "Your Real Estate Agency")
        data["property_manager_note"] = f"✅ Property Manager Discount Applied (5%) — {agency}"
    else:
        data["property_manager_note"] = "–"

    # === After-Hours Surcharge Note ===
    after_hours = float(data.get("after_hours_surcharge") or 0)
    data["after_hours_note"] = (
        f"✅ After-Hours Cleaning Surcharge (${after_hours:.2f})" if after_hours > 0 else "–"
    )

    # === Weekend Surcharge Note ===
    weekend_surcharge = float(data.get("weekend_surcharge") or 0)
    data["weekend_note"] = (
        f"✅ Weekend Cleaning Surcharge (${weekend_surcharge:.2f})" if weekend_surcharge > 0 else "–"
    )

    # === Ensure Surcharge Exists in Data for Template ===
    data["weekend_surcharge"] = weekend_surcharge

    # === Render & Export PDF ===
    html_out = template.render(**data)
    HTML(string=html_out, base_url=".").write_pdf(output_path)

    logger.info(f"✅ PDF Generated: {output_path}")

    return output_path, pdf_url
