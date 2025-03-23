from fastapi import APIRouter
from app.models.quote_models import QuoteRequest, QuoteResponse
from app.services.quote_logic import calculate_quote

router = APIRouter()

@router.post("/calculate-quote", response_model=QuoteResponse)
def calculate_quote_endpoint(quote_request: QuoteRequest):
    return calculate_quote(quote_request)
