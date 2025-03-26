from fastapi import APIRouter
from pydantic import BaseModel
from openai import OpenAI
import os

router = APIRouter()

# Set up OpenAI client with your API key
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

class ChatInput(BaseModel):
    message: str
    chat_id: str = "default"

# In-memory storage of chat history (you can upgrade later)
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
                "You are Brendan, an Aussie vacate cleaning quoting assistant at Orca Cleaning. "
                "Use casual, friendly language. Extract suburb, bedrooms, bathrooms, and any extras or special requests. "
                "Ask smart follow-up questions. Once ready, confirm details before submitting the quote. "
                "Mention seasonal deals if relevant."
            )
        }
    ] + chat_memory[chat_id]

    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=messages,
            temperature=0.7
        )
        reply = response.choices[0].message.content.strip()

    except Exception as e:
        reply = f"Uh-oh! Something went wrong while chatting with Brendan: {str(e)}"

    chat_memory[chat_id].append({"role": "assistant", "content": reply})
    return {"reply": reply}
