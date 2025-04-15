from fastapi import FastAPI
from app.api import quote
from fastapi.responses import JSONResponse
import json

from app import auto_fixer  # Import after built-ins for clarity

app = FastAPI(
    title="Brendan API",
    description="Backend for Orca Cleaning's AI Quote Assistant - Brendan",
    version="1.0.0"
)

# Include Auto Fixer Route (AI GitHub Commit System)
app.include_router(auto_fixer.router)

# Include Quote Calculation and PDF Generation Routes
app.include_router(quote.router, prefix="/api")

# Root Welcome Endpoint
@app.get("/")
def read_root():
    return JSONResponse(
        content={"message": "Welcome to Brendan Backend! 🎉"},
        media_type="application/json; charset=utf-8"
    )
