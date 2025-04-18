# === config.py ===

import os
import logging
from logging.handlers import RotatingFileHandler
from pydantic_settings import BaseSettings

# === Brendan System Constants ===
LOG_TRUNCATE_LENGTH = 10000
MAX_LOG_LENGTH = 10000
PDF_SYSTEM_MESSAGE = (
    "SYSTEM: The quote has already been calculated. Do not recalculate. "
    "Politely ask the customer for name, email, phone number, and optional address so you can send the PDF quote."
)
TABLE_NAME = "Vacate Quotes"

# === Settings Class for Environment Variables ===
class Settings(BaseSettings):
    OPENAI_API_KEY: str
    AIRTABLE_API_KEY: str
    AIRTABLE_BASE_ID: str
    BOOKING_URL_BASE: str = "https://orcacleaning.com.au/schedule"
    SMTP_PASS: str
    GITHUB_TOKEN: str

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()

# === Logging Setup ===

LOG_DIR = "logs"
LOG_FILE = os.path.join(LOG_DIR, "brendan.log")
os.makedirs(LOG_DIR, exist_ok=True)

logger = logging.getLogger("brendan")
logger.setLevel(logging.DEBUG)

formatter = logging.Formatter(
    "%(asctime)s - %(levelname)s - %(message)s"
)

file_handler = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=5)
file_handler.setFormatter(formatter)

stream_handler = logging.StreamHandler()
stream_handler.setFormatter(formatter)

logger.addHandler(file_handler)
logger.addHandler(stream_handler)

# === ENV Safety Check ===

missing_env = []

if not settings.OPENAI_API_KEY:
    missing_env.append("OPENAI_API_KEY")
if not settings.AIRTABLE_API_KEY:
    missing_env.append("AIRTABLE_API_KEY")
if not settings.AIRTABLE_BASE_ID:
    missing_env.append("AIRTABLE_BASE_ID")
if not settings.SMTP_PASS:
    missing_env.append("SMTP_PASS")

if missing_env:
    logger.error(f"❌ Missing critical ENV variables: {', '.join(missing_env)}")
    raise RuntimeError("Missing required environment variables.")

logger.info("✅ Brendan config loaded and validated.")
