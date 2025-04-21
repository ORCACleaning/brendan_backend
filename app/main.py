# === Built-in & External Imports ===
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware  # Import CORSMiddleware

# === Internal Imports ===
from app.api import quote, filter_response  # Add filter_response import
from app import auto_fixer

# === FastAPI App Setup ===
app = FastAPI(
    title="Brendan API",
    description="Backend for Orca Cleaning's AI Quote Assistant - Brendan",
    version="1.0.0"
)

# === CORS Configuration ===
origins = [
    "https://yourfrontenddomain.com",  # Allow frontend domain (replace with actual domain)
    "http://localhost",  # Allow local development if needed
    "http://localhost:3000"  # If you're using a React frontend with localhost:3000
]

# Add CORS middleware to allow requests from specified origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,  # Allows requests from these origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all HTTP methods (GET, POST, etc.)
    allow_headers=["*"],  # Allows all headers
)

# === Routers ===
app.include_router(auto_fixer.router)              # AI GitHub Commit System
app.include_router(quote.router, prefix="/api")    # Main Quote & PDF Routes
app.include_router(filter_response.router, prefix="/api")  # Include filter_response router

# === Root Endpoint ===
@app.get("/")
def read_root():
    return JSONResponse(
        content={"message": "Welcome to Brendan Backend! 🎉"},
        media_type="application/json; charset=utf-8"
    )
