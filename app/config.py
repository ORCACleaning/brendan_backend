# === config.py ===

import os
import logging
from logging.handlers import RotatingFileHandler
from pydantic_settings import BaseSettings


# === Settings Class for Environment Variables ===
class Settings(BaseSettings):
    OPENAI_API_KEY: str
    AIRTABLE_API_KEY: str
    AIRTABLE_BASE_ID: str
    BOOKING_URL_BASE: str = "https://orcacleaning.com.au/schedule"
    SMTP_PASS: str

    class Config:
        env_file = ".env"


settings = Settings()

# === Setup Logging Directory ===
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

# === Setup Logging ===
LOG_FILE = os.path.join(LOG_DIR, "brendan.log")

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=5),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger("brendan")

# === ENV Safety Check ===
required_env_vars = [
    settings.OPENAI_API_KEY,
    settings.AIRTABLE_API_KEY,
    settings.AIRTABLE_BASE_ID,
    settings.SMTP_PASS
]

if not all(required_env_vars):
    logger.error("❌ Critical ENV variables missing.")
    raise RuntimeError("Missing critical ENV variables.")

logger.info("✅ Config loaded successfully. Brendan is ready.")
