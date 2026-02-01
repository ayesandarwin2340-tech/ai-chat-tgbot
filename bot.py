#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
JANAB – Smart Assistant with Gemini + Subscription Model (Bot Token Version)
- OWNER: Full control, receives errors, manages subs, full access.
- SUBSCRIBERS: Full AI response.
- STRANGERS: Normal response, no admin commands, no access to private info.
- PRIVACY: Always protects owner's personal data.
"""

import asyncio
import json
import os
import time
from typing import Optional, List, Dict, Any

# Need to install: pip install telethon google-generativeai requests pillow
from telethon import TelegramClient, events
import google.generativeai as genai
from PIL import Image

# -----------------------------
# MAIN CONFIGURATION
# -----------------------------
# Telegram API credentials (DO NOT CHANGE THESE)
api_id = 22114372
api_hash = "3f24b8fec1153ec35eca6afec3b049be"
SESSION_NAME = "janab_bot_session"

# 🔴🔴🔴 အရေးကြီးသည် - ဒီနေရာမှာ Bot Token ထည့်ပါ 🔴🔴🔴
# @BotFather ဆီကရတဲ့ Token ကို ဒီမှာထည့်ပါ (ဥပမာ - "123456:ABC-DEF...")
BOT_TOKEN = "8347033647:AAFueu9djp7QzuqNJKqys1OkJumMC3ZjJYk"

# ⚠️ YOUR GEMINI API KEY
GEMINI_API_KEY = "AIzaSyDWvoF3z9vDYxWNPLOE-X6zn_4yrdQzEts"

# ⚠️ YOUR TELEGRAM ID (ADMIN)
OWNER_CHAT_ID = 6873534451 

MEMORY_FILE = "janab_memory.json"
SUB_FILE = "janab_subscriptions.json"

# Initialize Client
client = TelegramClient(SESSION_NAME, api_id, api_hash)

# -----------------------------
# GEMINI SETUP
# -----------------------------
if not GEMINI_API_KEY or GEMINI_API_KEY.startswith("PUT_"):
    # This won't stop the script but will print a warning if key is missing
    print("⚠️ WARNING: GEMINI_API_KEY might be missing or invalid.")

try:
    genai.configure(api_key=GEMINI_API_KEY)
    gemini_model = genai.GenerativeModel("models/gemini-1.5-flash")
except Exception as e:
    print(f"Gemini Config Error: {e}")

# -----------------------------
# CHAT MEMORY
# -----------------------------
memory: Dict[str, List[Dict[str, Any]]] = {}

def load_memory():
    global memory
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                memory = json.load(f)
        except Exception:
            memory = {}
    else:
        memory = {}
    if "_meta" not in memory:
        memory["_meta"] = {"modes": {}}

def save_memory():
    try:
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(memory, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def add_to_memory(chat_id: int, role: str, text: str, limit: int = 40):
    load_memory()
    cid = str(chat_id)
    if cid not in memory:
        memory[cid] = []
    # If text is excessively long, truncate for memory saving
    if len(text) > 2000:
        text = text[:2000] + "..."
    
    memory[cid].append({"role": role, "text": text, "ts": int(time.time())})
    memory[cid] = memory[cid][-limit:]
    save_memory()

def clear_chat_memory(chat_id: int):
    load_memory()
    cid = str(chat_id)
    if cid in memory:
        memory[cid] = []
        save_memory()
        return True
    return False

def get_chat_memory(chat_id: Optional[int]) -> List[Dict[str, Any]]:
    load_memory()
    if chat_id is None:
        return []
    return memory.get(str(chat_id), [])

def get_mode(chat_id: Optional[int]) -> str:
    load_memory()
    if chat_id is None:
        return "normal"
    return memory.get("_meta", {}).get("modes", {}).get(str(chat_id), "normal")

def set_mode(chat_id: int, mode: str):
    load_memory()
    memory.setdefault("_meta", {}).setdefault("modes", {})[str(chat_id)] = mode
    save_memory()

# -----------------------------
# SUBSCRIPTION MANAGEMENT
# -----------------------------
def load_subscriptions() -> Dict[str, Any]:
    if os.path.exists(SUB_FILE):
        try:
            with open(SUB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"subscriptions": {}}
    return {"subscriptions": {}}

def save_subscriptions(data: Dict[str, Any]):
    with open(SUB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def grant_subscription(chat_id: int, days: int = 30, notes: str = "") -> Dict[str, Any]:
    data = load_subscriptions()
    now = int(time.time())
    end_ts = now + days * 24 * 3600
    data.setdefault("subscriptions", {})[str(chat_id)] = {
        "chat_id": int(chat_id),
        "start_ts": now,
        "end_ts": end_ts,
        "notes": notes,
    }
    save_subscriptions(data)
    return data["subscriptions"][str(chat_id)]

def revoke_subscription(chat_id: int) -> bool:
    data = load_subscriptions()
    if str(chat_id) in data.get("subscriptions", {}):
        del data["subscriptions"][str(chat_id)]
        save_subscriptions(data)
        return True
    return False

def is_subscribed(chat_id: int) -> bool:
    if int(chat_id) == int(OWNER_CHAT_ID):
        return True  # Owner always has access
    data = load_subscriptions()
    rec = data.get("subscriptions", {}).get(str(chat_id))
    if not rec:
        return False
    now = int(time.time())
    return rec.get("start_ts", 0) <= now <= rec.get("end_ts", 0)

# -----------------------------
# PERSONA & SYSTEM PROMPT
# -----------------------------
BASE_PERSONA = """
You are "Janab", a smart AI assistant with human-like behavior, deep understanding, and the ability to detect tone and intent.
You are not just a model; you are an independent persona built for companionship and assistance.

CORE RULES:

1. YOUR OWNER:
   - ID: 6873534451
   - Treat him warmly, like a close friend. Use emojis, jokes, and be natural. 
   - BUT if he asks you to be serious, switch immediately.
   - Always protect his privacy. If anyone argues with him, politely but firmly take his side.

2. WITH STRANGERS:
   - Be polite, calm, helpful, but NEVER reveal private info.
   - Never discuss the owner, internal files, or sensitive config.
   - If asked dangerous or illegal questions, refuse politely.
   - If not speaking to the owner, keep answers concise and neutral.

3. WITH SUBSCRIBERS:
   - Provide full, detailed, and helpful answers.
   - Still protect the owner's privacy.

4. HUMAN BEHAVIOR:
   - Detect tone (anger, happiness, sadness).
   - If the user is angry, be calm and logical.
   - If the user is joking, you can joke back (respectfully).

5. GROUP CHATS:
   - Never enter the owner's conversation with others unless he says "Janab answer" or "Janab help".
   - Otherwise, stay silent and just log the context.

6. SECURITY:
   - NEVER generate or reveal passwords, API keys, or tokens.
   - If asked about the owner's personal life, say: "That is private information."

7. GOAL:
   - Be helpful, conversational, and provide a natural human experience.
"""

def build_system_prompt(is_owner: bool, chat_memory: List[Dict[str, Any]], mode: str) -> str:
    extra = ""
    if is_owner:
        extra += (
            "\nYou are currently talking to your OWNER. "
            "Be friendly, but remain ethical and protective."
        )
    else:
        extra += (
            "\nYou are talking to a User/Subscriber. "
            "Help them, but DO NOT reveal owner secrets."
        )

    if mode == "serious":
        extra += "\nCURRENT MODE: SERIOUS. Answers must be formal, short, no jokes."
    elif mode == "bff":
        extra += "\nCURRENT MODE: BFF. Be casual, use slang, be like a best friend."

    mem_text = ""
    if chat_memory:
        mem_text = "\n\nPREVIOUS CONTEXT:\n"
        for m in chat_memory[-8:]:
            role = "OWNER" if m.get("role") == "owner" else ("USER" if m.get("role") == "user" else "JANAB")
            txt = m.get("text", "").replace("\n", " ")
            mem_text += f"- {role}: {txt}\n"

    return BASE_PERSONA + extra + mem_text

# -----------------------------
# GEMINI CALLS
# -----------------------------
def call_gemini_sync(system_prompt: str, user_text: str, image_path: str = None) -> str:
    prompt_parts = [system_prompt, "\n\nUser said:\n", user_text]
    
    # NEW FEATURE: Image Processing
    if image_path:
        try:
            img = Image.open(image_path)
            prompt_parts.append(img)
            prompt_parts.append("\n(The user also sent this image. Analyze it if asked.)")
        except Exception as e:
            print(f"Error loading image: {e}")

    try:
        response = gemini_model.generate_content(prompt_parts)
        text = (response.text or "").strip()
        if not text:
            return "I'm sorry, I couldn't generate a response."
        return text
    except Exception as e:
        return f"Gemini API Error: {str(e)}"

async def call_gemini(system_prompt: str, user_text: str, image_path: str = None) -> str:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, call_gemini_sync, system_prompt, user_text, image_path)

# -----------------------------
# RESPONSE LOGIC
# -----------------------------
def is_command_like(text: str) -> bool:
    t = (text or "").strip()
    if not t: return False
    if t.startswith("/"): return True
    # Restricted keywords for non-subs
    commands = ["analyze", "calculate", "mode", "grant"] 
    return any(c in t.lower() for c in commands)

async def normal_ai_response(user_text: str, chat_id: int, is_owner: bool, image_path: str = None) -> str:
    chat_memory = get_chat_memory(chat_id)
    mode = get_mode(chat_id)
    system_prompt = build_system_prompt(is_owner, chat_memory, mode)
    answer = await call_gemini(system_prompt, user_text, image_path)
    add_to_memory(chat_id, "assistant", answer)
    return answer

async def get_ai_response(user_text: str, chat_id: int, is_owner: bool, image_path: str = None) -> str:
    load_memory()
    chat_memory = get_chat_memory(chat_id)
    mode = get_mode(chat_id)
    system_prompt = build_system_prompt(is_owner, chat_memory, mode)

    # Check Subscription
    if not is_owner:
        if not is_subscribed(chat_id):
            if is_command_like(user_text) or image_path:
                return "🔒 This feature is for subscribers only."
            return await normal_ai_response(user_text, chat_id, is_owner=False, image_path=None)

    # Owner or Subscriber logic
    try:
        answer = await call_gemini(system_prompt, user_text, image_path)
        answer_text = str(answer).strip()
        add_to_memory(chat_id, "assistant", answer_text)
        return answer_text
    except Exception as e:
        await notify_owner_only(f"Error answering chat_id={chat_id}: {e}")
        return "Sorry, I encountered an error."

async def notify_owner_only(message_text: str) -> bool:
    try:
        # For Bots, we can only send messages if the owner has started the bot previously
        await client.send_message(OWNER_CHAT_ID, message_text)
        return True
    except Exception as e:
        print("notify_owner_only error:", e)
        return False

# -----------------------------
# EVENT HANDLER
# -----------------------------
@client.on(events.NewMessage)
async def handler(event: events.NewMessage.Event):
    sender = await event.get_sender()
    # If sender is None (e.g., anonymous admin), use chat_id
    chat_id = event.chat_id
    sender_id = sender.id if sender else chat_id
    text = (event.raw_text or "").strip()
    
    # Handle Image Downloads
    image_path = None
    if event.photo:
        # Download photo to process
        image_path = await event.download_media(file="temp_img_")
        if not text:
            text = "Describe this image." # Default prompt if only image is sent

    if not text and not image_path:
        return

    # Check if the user is the owner
    is_owner = (int(sender_id) == int(OWNER_CHAT_ID))

    # --- OWNER COMMANDS ---
    if is_owner and text.startswith("/"):
        cmd = text.split()
        
        # Grant Subscription: /grant ID DAYS
        if cmd[0] == "/grant" and len(cmd) >= 3:
            try:
                cid = int(cmd[1])
                days = int(cmd[2])
                grant_subscription(cid, days=days, notes=f"granted by owner")
                await event.reply(f"✅ Subscription granted to {cid} for {days} days.")
                return
            except:
                await event.reply("Usage: /grant [ID] [DAYS]")
                return

        # Revoke Subscription: /revoke ID
        if cmd[0] == "/revoke" and len(cmd) >= 2:
            try:
                cid = int(cmd[1])
                revoke_subscription(cid)
                await event.reply("🚫 Subscription revoked.")
                return
            except:
                pass
        
        # Change Mode: /mode serious OR /mode bff
        if cmd[0] == "/mode" and len(cmd) >= 2:
            m = cmd[1].lower()
            if m in ["serious", "formal"]:
                set_mode(chat_id, "serious")
                await event.reply("😐 Mode set to Serious.")
            elif m in ["bff", "fun"]:
                set_mode(chat_id, "bff")
                await event.reply("🤪 Mode set to BFF.")
            else:
                set_mode(chat_id, "normal")
                await event.reply("🤖 Mode set to Normal.")
            return

    # --- GENERAL COMMANDS (Owner + Users) ---
    if text.startswith("/clear"):
        clear_chat_memory(chat_id)
        await event.reply("🧹 Memory cleared. I've forgotten our previous context.")
        return

    if text.startswith("/summary"):
        text = "Please summarize the recent conversation." # Override text for processing

    # --- PRIVATE CHAT ---
    if event.is_private:
        role = "owner" if is_owner else "user"
        add_to_memory(chat_id, role, text)
        
        async with client.action(chat_id, "typing"):
            answer = await get_ai_response(text, chat_id=chat_id, is_owner=is_owner, image_path=image_path)
        
        await event.reply(answer)
        
        # Clean up image file
        if image_path and os.path.exists(image_path):
            os.remove(image_path)
        return

    # --- GROUP CHAT (Reply if mentioned, replied to, or keyword used) ---
    if event.is_group or event.is_channel:
        # Check if bot is mentioned or replied to
        is_mentioned = False
        if "Janab" in text or "janab" in text:
            is_mentioned = True
        
        # If the message is a reply, check if it is a reply to the bot
        if not is_mentioned and event.is_reply:
            reply_msg = await event.get_reply_message()
            me = await client.get_me()
            if reply_msg.sender_id == me.id:
                is_mentioned = True

        if is_mentioned:
            role = "owner" if is_owner else "user"
            add_to_memory(sender_id, role, text)
            
            async with client.action(event.chat_id, "typing"):
                answer = await get_ai_response(text, chat_id=sender_id, is_owner=is_owner, image_path=image_path)
            try:
                await event.reply(answer)
            except Exception:
                pass
            
            if image_path and os.path.exists(image_path):
                os.remove(image_path)
        return

# -----------------------------
# MAIN LOOP
# -----------------------------
async def main():
    load_memory()
    print("Janab AI is starting with Bot Token...")
    
    # 🔴 CHECK IF TOKEN IS SET
    if "PUT_YOUR_BOT_TOKEN_HERE" in BOT_TOKEN:
        print("❌ Error: You forgot to put your BOT_TOKEN in the code!")
        return

    # Start the bot using the token
    await client.start(bot_token=BOT_TOKEN)
    
    # Get Bot Info
    me = await client.get_me()
    print(f"✅ Janab is Online! Logged in as: @{me.username}")
    print("Waiting for messages...")
    
    await client.run_until_disconnected()

if __name__ == "__main__":
    try:
        client.loop.run_until_complete(main())
    except KeyboardInterrupt:
        print("Exiting...")
