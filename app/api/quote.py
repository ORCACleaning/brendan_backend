from fastapi import APIRouter, Response
from app.models.quote_models import QuoteRequest, QuoteResponse
from app.services.quote_logic import calculate_quote
from app.services.pdf_generator import generate_quote_pdf

router = APIRouter()

# ✅ Endpoint to calculate the quote
@router.post("/calculate-quote", response_model=QuoteResponse)
def calculate_quote_endpoint(quote_request: QuoteRequest):
    # ✅ Calculate the quote with all the new properties
    return calculate_quote(quote_request)

# ✅ Endpoint to generate the PDF
@router.post("/generate-pdf")
def generate_pdf(quote: QuoteResponse):
    # ✅ Generate PDF with updated fields
    filepath = generate_quote_pdf(quote.dict())
    with open(filepath, "rb") as file:
        return Response(
            content=file.read(),
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={quote.quote_id}.pdf"}
        )
