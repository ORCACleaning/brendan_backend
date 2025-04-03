from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML
import uuid
import os
import base64

def generate_quote_pdf(data: dict) -> str:
    quote_id = data.get("quote_id") or f"VAC-{uuid.uuid4().hex[:8]}"
    filename = f"{quote_id}.pdf"
    output_path = f"app/static/quotes/{filename}"

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Load logo image as base64
    logo_path = "app/static/orca_logo.png"
    with open(logo_path, "rb") as logo_file:
        logo_base64 = base64.b64encode(logo_file.read()).decode("utf-8")

    # Load Jinja2 environment
    env = Environment(loader=FileSystemLoader("app/services/templates"))
    template = env.get_template("quote_template.html")

    # Inject logo
    data["logo_base64"] = logo_base64

    # --- Extra Services Section ---
    extra_services = []

    if data.get("window_cleaning"):
        wc = data.get("window_count")
        if wc:
            extra_services.append(f"Window Cleaning ({wc} windows)")
        else:
            extra_services.append("Window Cleaning")

    if data.get("carpet_cleaning"):
        extra_services.append("Carpet Steam Cleaning")

    if data.get("oven_cleaning"):
        extra_services.append("Oven Cleaning")

    if data.get("garage_cleaning"):
        extra_services.append("Garage/Shed Cleaning")

    if data.get("wall_cleaning"):
        extra_services.append("Wall Cleaning")

    if data.get("balcony_cleaning"):
        extra_services.append("Balcony Cleaning")

    if data.get("fridge_cleaning"):
        extra_services.append("Fridge Cleaning")

    if data.get("range_hood_cleaning"):
        extra_services.append("Range Hood Cleaning")

    if data.get("deep_cleaning"):
        extra_services.append("Deep/Detail Cleaning")

    # Add service summary to template data
    data["extra_services"] = ", ".join(extra_services) if extra_services else "None"

    # --- Property Manager Info ---
    if data.get("is_property_manager"):
        agency = data.get("real_estate_agency", "Your Real Estate Agency")
        data["property_manager_note"] = f"✅ Property Manager Discount Applied (5%) — {agency}"
    else:
        data["property_manager_note"] = "–"

    # --- After Hours Surcharge ---
    if data.get("after_hours_cleaning"):
        data["after_hours_note"] = "✅ After-Hours/Weekend Cleaning"
    else:
        data["after_hours_note"] = "–"

    # --- Final Render ---
    html_out = template.render(**data)
    HTML(string=html_out, base_url=".").write_pdf(output_path)

    return output_path
