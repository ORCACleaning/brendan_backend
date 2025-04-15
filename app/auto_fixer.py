# === auto_fixer.py (Part 1 of 3) ===

import base64
import datetime
import logging
import os
import requests

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv

# === Load environment variables ===
load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_USERNAME = "ORCACleaning"
GITHUB_REPO = "brendan_backend"
DEFAULT_BRANCH = "main"

if not GITHUB_TOKEN:
    raise RuntimeError("❌ GITHUB_TOKEN not found in environment variables.")

logger = logging.getLogger("auto_fixer")
logger.setLevel(logging.INFO)

router = APIRouter()
