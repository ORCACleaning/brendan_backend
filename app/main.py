# === Built-in & External Imports ===
from fastapi import FastAPI
from fastapi.responses import JSONResponse

# === Internal Imports ===
from app.api import quote
from app import auto_fixer

# === FastAPI App Setup ===
app = FastAPI(
    title="Brendan API",
    description="Backend for Orca Cleaning's AI Quote Assistant - Brendan",
    version="1.0.0"
)

# === Routers ===
app.include_router(auto_fixer.router)              # AI GitHub Commit System
app.include_router(quote.router, prefix="/api")    # Main Quote & PDF Routes

# === Root Endpoint ===
@app.get("/")
def read_root():
    return JSONResponse(
        content={"message": "Welcome to Brendan Backend! 🎉"},
        media_type="application/json; charset=utf-8"
    )
