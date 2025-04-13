import logging
from pydantic_settings import BaseSettings

# === Settings Class for ENV Vars ===
class Settings(BaseSettings):
    OPENAI_API_KEY: str
    AIRTABLE_API_KEY: str
    AIRTABLE_BASE_ID: str
    BOOKING_URL_BASE: str = "https://orcacleaning.com.au/schedule"
    SMTP_PASS: str

    class Config:
        env_file = ".env"

settings = Settings()

# === Setup Logging ===
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("brendan")

# === ENV Safety Check ===
if not settings.OPENAI_API_KEY or not settings.AIRTABLE_API_KEY or not settings.AIRTABLE_BASE_ID:
    logger.error("❌ Critical ENV variables missing.")
    raise RuntimeError("Missing critical ENV variables.")
