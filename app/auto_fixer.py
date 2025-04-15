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

# === auto_fixer.py (Part 2 of 3) ===

ALLOWED_FILES = [
    "app/brendan_chat.py",
    "app/services/quote_logic.py",
]

class FixRequest(BaseModel):
    file_path: str
    new_code: str
    commit_message: str

def commit_to_github(file_path: str, new_code: str, commit_message: str):
    if file_path not in ALLOWED_FILES:
        raise HTTPException(status_code=400, detail="File not allowed for auto-commit.")

    url = f"https://api.github.com/repos/{GITHUB_USERNAME}/{GITHUB_REPO}/contents/{file_path}"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json"
    }

    # === Get current file SHA ===
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        raise HTTPException(status_code=500, detail=f"Failed to fetch file: {response.text}")
    file_data = response.json()
    sha = file_data["sha"]

    # === Prepare commit payload ===
    encoded_content = base64.b64encode(new_code.encode()).decode()
    commit_payload = {
        "message": commit_message,
        "content": encoded_content,
        "branch": DEFAULT_BRANCH,
        "sha": sha
    }

    # === Commit to GitHub ===
    commit_response = requests.put(url, headers=headers, json=commit_payload)
    if commit_response.status_code not in [200, 201]:
        raise HTTPException(status_code=500, detail=f"Commit failed: {commit_response.text}")

    return commit_response.json()

# === auto_fixer.py (Part 3 of 3) ===

@router.post("/auto-fix-code")
async def auto_fix_code(request: Request, payload: FixRequest):
    logger.info(f"Auto-fix requested for: {payload.file_path}")

    try:
        result = commit_to_github(
            file_path=payload.file_path,
            new_code=payload.new_code,
            commit_message=payload.commit_message,
        )
        return JSONResponse(content={"detail": "Commit successful", "result": result})

    except HTTPException as http_exc:
        logger.error(f"HTTP Error: {http_exc.detail}")
        raise http_exc

    except Exception as exc:
        logger.exception("Unexpected error during auto-fix")
        raise HTTPException(status_code=500, detail=str(exc))
