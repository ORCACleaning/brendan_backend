from fastapi import FastAPI
from app.api import quote

app = FastAPI(
    title="Brendan API",
    description="Backend for Orca Cleaning's AI Quote Assistant - Brendan",
    version="1.0.0"
)

# Include the /calculate-quote route
app.include_router(quote.router, prefix="/api")
