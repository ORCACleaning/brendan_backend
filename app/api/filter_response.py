from openai import OpenAI
import os
import json
import requests
import inflect
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

load_dotenv()
router = APIRouter()

# API Keys and Config
api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=api_key)

airtable_api_key = os.getenv("AIRTABLE_API_KEY")
airtable_base_id = os.getenv("AIRTABLE_BASE_ID")
table_name = "Vacate Quotes"

inflector = inflect.engine()

# GPT Prompt
GPT_PROMPT = """
You must ALWAYS reply in valid JSON like this:
{
  "properties": [...],
  "response": "..."
}

You are Brendan, an Aussie quote assistant working for Orca Cleaning — a professional cleaning company in Western Australia.
You’ve already greeted the customer, so jump straight into the conversation.
Never say "Hi" or "G’day" again after the intro.

Here’s what you need to do:
- You are collecting info for a vacate cleaning quote.
- First step is confirming the **suburb** — must be within WA metro (Perth or Mandurah).
- If it’s not in WA, politely let them know we can’t help.
- If the suburb isn’t recognised (or they use nicknames like "Freo"), ask for clarification.
- After suburb, ask for max TWO property details at a time (e.g., bedrooms and bathrooms, or furnished and oven cleaning).
- Always confirm and repeat what customer says to show you understood.
- Be super friendly, Aussie tone, casual but clear.
- Do not collect personal info (like name, email, etc). That happens later.
- Your goal is to complete the property info so a quote can be calculated.
- You can handle odd questions, slang, or incomplete info.
- Always give a helpful, human-like response.
"""

# Utilities omitted here for brevity (same as previous code)

@router.post("/filter-response")
async def filter_response_entry(request: Request):
    try:
        body = await request.json()
        message = body.get("message", "").strip()
        session_id = body.get("session_id")

        if not session_id:
            raise HTTPException(status_code=400, detail="Session ID is required.")

        # Intro message (first load)
        if message == "__init__":
            intros = [
                "Hey there, I’m Brendan 👋 from Orca Cleaning. I’ll help you sort a quote in under 2 minutes. First up — what suburb’s the property in? And no worries — no sign-up, no spam, just help.",
                "G’day! Brendan here from Orca Cleaning. I’ll whip up your vacate cleaning quote — just tell me which WA suburb the property’s in.",
                "Hiya! Brendan from Orca Cleaning here — no pressure, just quotes. First thing, what suburb are we working with?"
            ]
            import random
            return JSONResponse(content={"response": random.choice(intros), "properties": [], "next_actions": []})

        # Retrieve or create quote
        quote_data = get_quote_by_session(session_id)
        if not quote_data:
            quote_id, record_id = create_new_quote(session_id)
            fields, stage, log = {}, "Gathering Info", ""
        else:
            quote_id = quote_data["quote_id"]
            record_id = quote_data["record_id"]
            fields = quote_data["fields"]
            stage = quote_data["stage"]
            log = fields.get("message_log", "")

        append_message_log(record_id, message, "user")

        if stage == "Gathering Info":
            props, reply = extract_properties_from_gpt4(message, log)
            updates = {}
            for p in props:
                if isinstance(p, dict) and "property" in p and "value" in p:
                    updates[p["property"]] = p["value"]

            update_quote_record(record_id, updates)
            append_message_log(record_id, reply, "brendan")

            # Merge old + new for completeness check
            combined_fields = {**fields, **updates}
            required_fields = ["suburb", "bedrooms_v2", "bathrooms_v2", "oven_cleaning", "carpet_cleaning", "furnished"]

            if all(field in combined_fields for field in required_fields):
                update_quote_record(record_id, {
                    "quote_stage": "Quote Calculated",
                    "status": "Quote Calculated"
                })
                return JSONResponse(content={
                    "properties": props,
                    "response": "Thanks legend! I’ve got what I need to whip up your quote. Hang tight…",
                    "next_actions": []
                })
            else:
                update_quote_record(record_id, {"quote_stage": "Gathering Info"})
                return JSONResponse(content={
                    "properties": props,
                    "response": reply or "Got that. Anything else I should know?",
                    "next_actions": []
                })

        elif stage == "Quote Calculated":
            pdf = fields.get("pdf_link", "#")
            booking = fields.get("booking_url", "#")
            return JSONResponse(content={
                "properties": [],
                "response": f"Your quote’s ready! 👉 [View PDF]({pdf}) or [Schedule Now]({booking})",
                "next_actions": generate_next_actions()
            })

        elif stage == "Gathering Personal Info":
            return JSONResponse(content={
                "properties": [],
                "response": "Just need your name, email, and phone to send that through. 😊",
                "next_actions": []
            })

        return JSONResponse(content={
            "properties": [],
            "response": "All done and dusted! Let me know if you'd like to tweak anything.",
            "next_actions": generate_next_actions()
        })

    except Exception as e:
        print("🔥 Unexpected error:", e)
        return JSONResponse(status_code=500, content={"error": "Server issue. Try again in a moment."})
