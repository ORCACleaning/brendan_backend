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

    # Add logo_base64 into the template data
    data["logo_base64"] = logo_base64

    # ✅ Handle additional services and format them nicely
    extra_services = []
    if data.get("wall_cleaning"):
        extra_services.append("Wall Cleaning")
    if data.get("balcony_cleaning"):
        extra_services.append("Balcony Cleaning")
    if data.get("window_cleaning"):
        # ✅ Show number of windows dynamically
        window_count = data.get("window_count", 0)
        if window_count > 0:
            extra_services.append(f"Window Cleaning ({window_count} windows)")
        else:
            extra_services.append("Window Cleaning")

    if data.get("deep_cleaning"):
        extra_services.append("Deep Cleaning")
    if data.get("fridge_cleaning"):
        extra_services.append("Fridge Cleaning")
    if data.get("range_hood_cleaning"):
        extra_services.append("Range Hood Cleaning")
    if data.get("garage_cleaning"):
        extra_services.append("Garage Cleaning")

    # ✅ Add extra services to the data
    data["extra_services"] = ", ".join(extra_services) if extra_services else "None"

    # ✅ Render and export the PDF
    html_out = template.render(**data)
    HTML(string=html_out, base_url=".").write_pdf(output_path)

    return output_path
