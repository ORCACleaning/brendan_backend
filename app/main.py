from fastapi import FastAPI
from app.api import quote
from fastapi.responses import JSONResponse
import json

app = FastAPI(
    title="Brendan API",
    description="Backend for Orca Cleaning's AI Quote Assistant - Brendan",
    version="1.0.0"
)

# Include the /calculate-quote and /generate-pdf routes
app.include_router(quote.router, prefix="/api")

# Welcome endpoint with corrected emoji encoding
@app.get("/")
def read_root():
    return JSONResponse(
        content={"message": "Welcome to Brendan Backend! 🎉"},
        media_type="application/json; charset=utf-8"
    )
