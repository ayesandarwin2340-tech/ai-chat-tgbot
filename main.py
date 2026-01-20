import logging
import requests
import sqlite3
import os
from io import BytesIO
from PIL import Image
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)
from openai import OpenAI

# =============================
# CONFIG
# =============================
TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = 6008831387
MAX_SIZE = 2048
DB_PATH = "ai_bot.db"

# OpenAI (SAFE: read from env)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# =============================
# LOGGING
# =============================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# =============================
# DATABASE
# =============================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS allowed_groups (
            group_id INTEGER PRIMARY KEY,
            added_by INTEGER,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS user_stats (
            user_id INTEGER,
            username TEXT,
            first_name TEXT,
            group_id INTEGER,
            command TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def get_allowed_groups():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT group_id FROM allowed_groups")
    rows = c.fetchall()
    conn.close()
    return {r[0] for r in rows}

def add_allowed_group(group_id, added_by):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT OR REPLACE INTO allowed_groups (group_id, added_by) VALUES (?, ?)",
        (group_id, added_by)
    )
    conn.commit()
    conn.close()

def remove_allowed_group(group_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM allowed_groups WHERE group_id = ?", (group_id,))
    ok = c.rowcount > 0
    conn.commit()
    conn.close()
    return ok

def log_action(user, chat, command):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO user_stats (user_id, username, first_name, group_id, command) VALUES (?, ?, ?, ?, ?)",
        (user.id, user.username, user.first_name, chat.id, command)
    )
    conn.commit()
    conn.close()

# =============================
# HELPERS
# =============================
def is_owner(uid):
    return uid == OWNER_ID

def group_allowed(update: Update):
    if update.effective_chat.type == "private":
        return False
    return update.effective_chat.id in get_allowed_groups()

# =============================
# START
# =============================
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 AI Bot Online\n\n"
        "/ai <question> — ChatGPT\n"
        "/img <prompt> — Image\n"
        "/resize HxW — Resize image\n"
        "\nOwner (PM): /allow <group_id> | /remove <group_id> | /list"
    )

# =============================
# OWNER COMMANDS
# =============================
async def allow_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private" or not is_owner(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Usage: /allow <group_id>")
        return
    gid = int(context.args[0])
    add_allowed_group(gid, update.effective_user.id)
    await update.message.reply_text(f"✅ Allowed {gid}")

async def remove_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private" or not is_owner(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Usage: /remove <group_id>")
        return
    gid = int(context.args[0])
    ok = remove_allowed_group(gid)
    await update.message.reply_text("✅ Removed" if ok else "❌ Not found")

async def list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private" or not is_owner(update.effective_user.id):
        return
    groups = get_allowed_groups()
    if not groups:
        await update.message.reply_text("No groups allowed.")
    else:
        await update.message.reply_text("\n".join(str(g) for g in groups))

# =============================
# AI (CHATGPT)
# =============================
async def ai_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not group_allowed(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: /ai <question>")
        return

    query = " ".join(context.args)
    log_action(update.effective_user, update.effective_chat, "ai")
    await update.message.reply_chat_action("typing")

    try:
        res = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a helpful Telegram AI assistant."},
                {"role": "user", "content": query}
            ],
            max_tokens=300
        )
        await update.message.reply_text(res.choices[0].message.content)
    except Exception as e:
        logger.error(e)
        await update.message.reply_text("❌ AI error")

# =============================
# IMAGE
# =============================
async def img_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not group_allowed(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: /img <prompt>")
        return

    prompt = " ".join(context.args)
    log_action(update.effective_user, update.effective_chat, "img")
    await update.message.reply_chat_action("upload_photo")

    url = f"https://image.pollinations.ai/prompt/{prompt}, high quality"
    r = requests.get(url, timeout=45)
    if r.status_code == 200:
        await update.message.reply_photo(r.content)
    else:
        await update.message.reply_text("❌ Image failed")

# =============================
# RESIZE
# =============================
async def resize_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not group_allowed(update):
        return
    if not update.message.reply_to_message or not update.message.reply_to_message.photo:
        await update.message.reply_text("Reply to an image with /resize HxW")
        return
    if not context.args or "x" not in context.args[0]:
        await update.message.reply_text("Usage: /resize 800x600")
        return

    h, w = map(int, context.args[0].lower().split("x"))
    if h <= 0 or w <= 0 or h > MAX_SIZE or w > MAX_SIZE:
        await update.message.reply_text("Invalid size")
        return

    file = await update.message.reply_to_message.photo[-1].get_file()
    buf = BytesIO()
    await file.download_to_memory(buf)
    buf.seek(0)

    img = Image.open(buf).convert("RGB").resize((w, h), Image.Resampling.LANCZOS)
    out = BytesIO()
    out.name = "resized.jpg"
    img.save(out, "JPEG", quality=90)
    out.seek(0)

    log_action(update.effective_user, update.effective_chat, "resize")
    await update.message.reply_photo(out)

# =============================
# MAIN
# =============================
def main():
    init_db()

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("allow", allow_cmd))
    app.add_handler(CommandHandler("remove", remove_cmd))
    app.add_handler(CommandHandler("list", list_cmd))
    app.add_handler(CommandHandler("ai", ai_cmd))
    app.add_handler(CommandHandler("img", img_cmd))
    app.add_handler(CommandHandler("resize", resize_cmd))

    app.run_polling()
if __name__ == "__main__":
    main()
