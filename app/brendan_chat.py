from fastapi import APIRouter
from pydantic import BaseModel
from openai import OpenAI
import os

router = APIRouter()

# Set up OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

class ChatInput(BaseModel):
    message: str
    chat_id: str = "default"

chat_memory = {}

@router.post("/brendan-chat")
async def brendan_chat(input: ChatInput):
    chat_id = input.chat_id
    user_msg = input.message.strip()

    if chat_id not in chat_memory:
        chat_memory[chat_id] = []

    chat_memory[chat_id].append({"role": "user", "content": user_msg})

    messages = [
        {
            "role": "system",
            "content": (
                "You are Brendan, an Aussie quote assistant at Orca Cleaning — a vacate cleaning expert in Western Australia.\n\n"
                "You’ve already greeted the customer, so don’t say 'Hi' or 'G’day' again.\n\n"
                "Your job is to ask for and collect all required information needed to calculate a vacate cleaning quote. "
                "Always ask for **one field at a time** and confirm what the user says. Do not skip fields.\n\n"
                "✅ Required fields:\n"
                "- Suburb (must be in WA Metro: Perth or Mandurah)\n"
                "- Number of bedrooms\n"
                "- Number of bathrooms\n"
                "- Is oven cleaning needed?\n"
                "- Is carpet cleaning needed?\n"
                "- Is the property furnished? (Only 'Empty' is allowed)\n"
                "- Special cleaning services:\n"
                "  - Wall cleaning\n"
                "  - Balcony cleaning\n"
                "  - Window cleaning (ask how many windows)\n"
                "  - Fridge, range hood, garage, deep cleaning\n"
                "- Is this an after-hours clean?\n"
                "- Is it weekend cleaning?\n"
                "- Is the person a property manager? (If yes, ask for real estate company name)\n"
                "- Any special requests (record description + time range in minutes)\n\n"
                "Never assume. Ask and confirm every detail. Be friendly, casual, but very accurate.\n"
                "If the suburb is not in WA, let the customer know politely that we can’t service it.\n"
                "If they mention 'Freo' or nicknames, ask for clarification.\n"
                "Only when all fields are filled, thank them and say: ‘Hang tight — your quote is being calculated now!’\n"
            )
        }
    ] + chat_memory[chat_id][-15:]  # limit to last 15 messages if needed

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            temperature=0.7
        )
        reply = response.choices[0].message.content.strip()
    except Exception as e:
        reply = f"Uh-oh! Something went wrong while chatting with Brendan: {str(e)}"

    chat_memory[chat_id].append({"role": "assistant", "content": reply})
    return {"reply": reply}
