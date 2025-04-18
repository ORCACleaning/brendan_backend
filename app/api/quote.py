from fastapi import APIRouter, Response, HTTPException
from app.models.quote_models import QuoteRequest, QuoteResponse
from app.services.quote_logic import calculate_quote
from app.services.pdf_generator import generate_quote_pdf
import os

router = APIRouter()

# === Endpoint: Calculate Quote ===
@router.post("/calculate-quote", response_model=QuoteResponse)
def calculate_quote_endpoint(quote_request: QuoteRequest):
    try:
        return calculate_quote(quote_request)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Quote calculation failed: {str(e)}")

# === Endpoint: Generate PDF ===
@router.post("/generate-pdf")
def generate_pdf(quote: QuoteResponse):
    try:
        filepath, _ = generate_quote_pdf(quote.dict())
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"PDF not found at: {filepath}")

        with open(filepath, "rb") as file:
            return Response(
                content=file.read(),
                media_type="application/pdf",
                headers={"Content-Disposition": f"attachment; filename={quote.quote_id}.pdf"}
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {str(e)}")
