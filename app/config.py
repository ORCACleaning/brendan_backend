import logging
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    OPENAI_API_KEY: str
    AIRTABLE_API_KEY: str
    AIRTABLE_BASE_ID: str
    BOOKING_URL_BASE: str = "https://orcacleaning.com.au/schedule"
    SMTP_PASS: str

    class Config:
        env_file = ".env"

settings = Settings()

logger = logging.getLogger("brendan")
logger.setLevel(logging.DEBUG)
