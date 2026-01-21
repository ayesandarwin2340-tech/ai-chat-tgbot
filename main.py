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
    ContextTypes,
    MessageHandler,
    filters
)

from openai import OpenAI

# =============================
# CONFIG
# =============================
TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = 6873534451
MAX_SIZE = 2048
DB_PATH = "ai_bot.db"

if not TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# =============================
# LOGGING
# =============================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# -----------------------------
# DATABASE SETUP
# -----------------------------
def init_db():
    """Initialize the database with required tables"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Allowed groups table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS allowed_groups (
            group_id INTEGER PRIMARY KEY,
            added_by INTEGER,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # User stats table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_stats (
            user_id INTEGER,
            username TEXT,
            first_name TEXT,
            group_id INTEGER,
            command TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Group stats table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS group_stats (
            group_id INTEGER,
            group_name TEXT,
            total_commands INTEGER DEFAULT 0,
            last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()
    logger.info("Database initialized successfully")

def get_allowed_groups():
    """Get all allowed groups from database"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT group_id FROM allowed_groups")
    groups = {row[0] for row in cursor.fetchall()}
    conn.close()
    return groups

def add_allowed_group(group_id, added_by):
    """Add a group to allowed list"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT OR REPLACE INTO allowed_groups (group_id, added_by) VALUES (?, ?)",
            (group_id, added_by)
        )
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error adding group: {e}")
        return False
    finally:
        conn.close()

def remove_allowed_group(group_id):
    """Remove a group from allowed list"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM allowed_groups WHERE group_id = ?", (group_id,))
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Error removing group: {e}")
        return False
    finally:
        conn.close()

def log_user_action(user_id, username, first_name, group_id, command):
    """Log user actions for statistics"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO user_stats (user_id, username, first_name, group_id, command)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, username, first_name, group_id, command))
        
        # Update group stats
        cursor.execute('''
            INSERT OR REPLACE INTO group_stats (group_id, total_commands, last_active)
            VALUES (?, COALESCE((SELECT total_commands FROM group_stats WHERE group_id = ?), 0) + 1, CURRENT_TIMESTAMP)
        ''', (group_id, group_id))
        
        conn.commit()
    except Exception as e:
        logger.error(f"Error logging user action: {e}")
    finally:
        conn.close()

# -----------------------------
# UTILS
# -----------------------------
def check_group_permission(update: Update):
    """Check if group is allowed"""
    if update.effective_chat.type == "private":
        return False
    allowed_groups = get_allowed_groups()
    return update.effective_chat.id in allowed_groups

def is_owner(user_id: int):
    return user_id == OWNER_ID

# -----------------------------
# START COMMAND - FIXED
# -----------------------------
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        chat_type = update.effective_chat.type
        
        # Log the action
        log_user_action(
            user_id=user_id,
            username=update.effective_user.username,
            first_name=update.effective_user.first_name,
            group_id=update.effective_chat.id if chat_type != "private" else None,
            command="start"
        )
        
        if is_owner(user_id) and chat_type == "private":
            welcome_text = """🤖 *AI Bot Owner Panel* 🚀

*Owner Commands:*
/allow <group_id> - Allow group
/remove <group_id> - Remove group  
/list - Show allowed groups

✨ *Available AI Features for Groups:*

🎨 *Image Generation:*
• /img <prompt> - Realistic Photos
• /anime <prompt> - Anime Art
• /art <prompt> - Digital Paintings  
• /hd <prompt> - High Quality
• /cyber <prompt> - Cyberpunk Style
• /portrait <prompt> - Portraits
• /landscape <prompt> - Landscapes
• /fantasy <prompt> - Fantasy Worlds

💬 *AI Features:*
• /ai <question> - AI Chat
• /resize HxW - Resize Images (max 2048x2048)"""
        else:
            welcome_text = """🤖 *AI Bot* 🚀

✨ *Available AI Features:*

🎨 *Image Generation:*
• /img <prompt> - Realistic Photos
• /anime <prompt> - Anime Art
• /art <prompt> - Digital Paintings  
• /hd <prompt> - High Quality
• /cyber <prompt> - Cyberpunk Style
• /portrait <prompt> - Portraits
• /landscape <prompt> - Landscapes
• /fantasy <prompt> - Fantasy Worlds

💬 *AI Features:*
• /ai <question> - AI Chat
• /resize HxW - Resize Images (max 2048x2048)"""
        
        await update.message.reply_text(welcome_text, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Error in start command: {e}")
        # Fallback response if main one fails
        try:
            await update.message.reply_text(
                "🤖 AI Bot Started!\n\n"
                "Use /ai for chat, /img for images\n"
                "Contact @Zinko158 for group access"
            )
        except:
            pass

# -----------------------------
# OWNER COMMANDS (PRIVATE ONLY)
# -----------------------------
async def allow_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.effective_chat.type != "private" or not is_owner(update.effective_user.id):
            await update.message.reply_text("❌ Owner command only available in private chat.")
            return
        
        if not context.args:
            await update.message.reply_text("📝 Usage: /allow <group_id>")
            return
            
        gc = int(context.args[0])
        if add_allowed_group(gc, update.effective_user.id):
            await update.message.reply_text(f"✅ Group {gc} has been authorized!", parse_mode='Markdown')
        else:
            await update.message.reply_text("❌ Failed to add group to database.")
            
    except ValueError:
        await update.message.reply_text("❌ Invalid group ID. Please provide a numeric ID.")
    except Exception as e:
        logger.error(f"Allow command error: {e}")
        await update.message.reply_text("❌ Error: Use /allow <group_id>")

async def remove_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.effective_chat.type != "private" or not is_owner(update.effective_user.id):
            await update.message.reply_text("❌ Owner command only available in private chat.")
            return
            
        if not context.args:
            await update.message.reply_text("📝 Usage: /remove <group_id>")
            return
            
        gc = int(context.args[0])
        if remove_allowed_group(gc):
            await update.message.reply_text(f"❌ Group {gc} has been removed!", parse_mode='Markdown')
        else:
            await update.message.reply_text("❌ Group not found in database.")
            
    except ValueError:
        await update.message.reply_text("❌ Invalid group ID. Please provide a numeric ID.")
    except Exception as e:
        logger.error(f"Remove command error: {e}")
        await update.message.reply_text("❌ Error: Use /remove <group_id>")

async def list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.effective_chat.type != "private" or not is_owner(update.effective_user.id):
            await update.message.reply_text("❌ Owner command only available in private chat.")
            return
            
        allowed_groups = get_allowed_groups()
        if not allowed_groups:
            await update.message.reply_text("📝 No groups are currently authorized.")
        else:
            groups_list = "\n".join([f"• {group_id}" for group_id in allowed_groups])
            await update.message.reply_text(
                f"✅ *Authorized Groups:*\n{groups_list}\n\nTotal: {len(allowed_groups)} groups",
                parse_mode='Markdown'
            )
    except Exception as e:
        logger.error(f"List command error: {e}")
        await update.message.reply_text("❌ Error retrieving group list.")

# -----------------------------
# AI TEXT COMMAND (GROUP ONLY)
# -----------------------------
async def ai_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not check_group_permission(update):
            await update.message.reply_text(
                "❌ This bot only works in authorized groups.\n"
                "📧 Contact @Zinko158 for group access."
            )
            return
            
        if not context.args:
            await update.message.reply_text("🤖 Usage: /ai <your question>")
            return
            
        query = " ".join(context.args)
        if len(query) < 2:
            await update.message.reply_text("❌ Please provide a longer question.")
            return
        
        # Log the action
        log_user_action(
            user_id=update.effective_user.id,
            username=update.effective_user.username,
            first_name=update.effective_user.first_name,
            group_id=update.effective_chat.id,
            command="ai"
        )
            
        await update.message.reply_chat_action("typing")
        url = f"https://text.pollinations.ai/{query}"
        response = requests.get(url, timeout=20)
        
        if response.status_code == 200:
            await update.message.reply_text(f"🤖 {response.text}")
        else:
            await update.message.reply_text("❌ Sorry, I'm having trouble responding right now.")
            
    except requests.exceptions.Timeout:
        await update.message.reply_text("⏰ Request timeout. Please try again.")
    except Exception as e:
        logger.error(f"AI command error: {e}")
        await update.message.reply_text("❌ Error processing your request.")

# -----------------------------
# IMAGE GENERATOR (GROUP ONLY)
# -----------------------------
async def gen_image(update: Update, context: ContextTypes.DEFAULT_TYPE, style, style_name):
    try:
        if not check_group_permission(update):
            await update.message.reply_text(
                "❌ This bot only works in authorized groups.\n"
                "📧 Contact @Zinko158 for group access."
            )
            return
            
        if not context.args:
            command = update.message.text.split()[0][1:]
            await update.message.reply_text(f"🎨 Usage: /{command} <image description>")
            return
            
        prompt = " ".join(context.args)
        if len(prompt) < 3:
            await update.message.reply_text("❌ Please provide a longer description.")
            return
        
        # Log the action
        log_user_action(
            user_id=update.effective_user.id,
            username=update.effective_user.username,
            first_name=update.effective_user.first_name,
            group_id=update.effective_chat.id,
            command=style_name.lower()
        )
            
        await update.message.reply_chat_action("upload_photo")
        final_prompt = f"{style}, {prompt}, high quality, always no watermark"
        url = f"https://image.pollinations.ai/prompt/{final_prompt}"
        
        response = requests.get(url, timeout=45)
        if response.status_code == 200:
            await update.message.reply_photo(
                response.content, 
                caption=f"🎨 {style_name}: {prompt}\n🌝 @Zinko158"
            )
        else:
            await update.message.reply_text("❌ Failed to generate image. Please try again.")
            
    except requests.exceptions.Timeout:
        await update.message.reply_text("⏰ Image generation timeout. Please try again.")
    except Exception as e:
        logger.error(f"Image generation error: {e}")
        await update.message.reply_text("❌ Error generating image. Please try a different prompt.")

# Image command wrappers
async def img_cmd(update, context): 
    await gen_image(update, context, "realistic photo high detail", "Realistic Image")
async def anime_cmd(update, context): 
    await gen_image(update, context, "anime style art", "Anime Art")
async def art_cmd(update, context): 
    await gen_image(update, context, "digital art painting", "Digital Art")
async def hd_cmd(update, context): 
    await gen_image(update, context, "high quality ultra detailed", "HD Image")
async def cyber_cmd(update, context): 
    await gen_image(update, context, "cyberpunk futuristic neon", "Cyberpunk")
async def portrait_cmd(update, context): 
    await gen_image(update, context, "portrait detailed face", "Portrait")
async def landscape_cmd(update, context): 
    await gen_image(update, context, "landscape scenery environment", "Landscape")
async def fantasy_cmd(update, context): 
    await gen_image(update, context, "fantasy magic epic", "Fantasy")

# -----------------------------
# RESIZE COMMAND (GROUP ONLY)
# -----------------------------
async def resize_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not check_group_permission(update):
            await update.message.reply_text(
                "❌ This bot only works in authorized groups.\n"
                "📧 Contact @Zinko158 for group access."
            )
            return
            
        if not update.message.reply_to_message:
            await update.message.reply_text("❌ Please reply to an image message with /resize HEIGHTxWIDTH")
            return
            
        if not update.message.reply_to_message.photo:
            await update.message.reply_text("❌ The replied message doesn't contain an image.")
            return
            
        if not context.args or len(context.args) != 1:
            await update.message.reply_text("📐 Usage: /resize HEIGHTxWIDTH (e.g., /resize 800x600)")
            return
            
        size_arg = context.args[0].lower()
        if "x" not in size_arg:
            await update.message.reply_text("❌ Format: HEIGHTxWIDTH (e.g., 800x600)")
            return
            
        try:
            h, w = map(int, size_arg.split("x"))
        except ValueError:
            await update.message.reply_text("❌ Invalid dimensions. Use numbers like 800x600")
            return
            
        if h > MAX_SIZE or w > MAX_SIZE or h <= 0 or w <= 0:
            await update.message.reply_text(f"❌ Size must be between 1x1 and {MAX_SIZE}x{MAX_SIZE}")
            return
        
        # Log the action
        log_user_action(
            user_id=update.effective_user.id,
            username=update.effective_user.username,
            first_name=update.effective_user.first_name,
            group_id=update.effective_chat.id,
            command="resize"
        )
            
        await update.message.reply_chat_action("upload_photo")
        photo_file = await update.message.reply_to_message.photo[-1].get_file()
        
        img_bytes = BytesIO()
        await photo_file.download_to_memory(img_bytes)
        img_bytes.seek(0)
        
        with Image.open(img_bytes) as img:
            if img.mode in ('RGBA', 'LA', 'P'):
                img = img.convert('RGB')
            
            img_resized = img.resize((w, h), Image.Resampling.LANCZOS)
            
            output = BytesIO()
            output.name = "resized.jpg"
            img_resized.save(output, "JPEG", quality=90)
            output.seek(0)
            
            await update.message.reply_photo(
                photo=output,
                caption=f"🔄 Resized to: {h}x{w}\n🥱 @Zinko158"
            )
            
    except Exception as e:
        logger.error(f"Resize error: {e}")
        await update.message.reply_text("❌ Failed to resize image. Please make sure you're replying to a valid image.")

# -----------------------------
# AUTO ROAST (GROUP ONLY) - IMPROVED
# -----------------------------
async def roast_auto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.effective_chat.type == "private":
            return
            
        if not check_group_permission(update):
            return
            
        msg = update.message.text.strip()
        if len(msg) < 5 or msg.startswith('/'):
            return
            
        # Don't roast if message contains bot mention
        if '@ITS_UNKNOWN_AI_BOT' in msg or 'bot' in msg.lower():
            return
        
        # Log the action
        log_user_action(
            user_id=update.effective_user.id,
            username=update.effective_user.username,
            first_name=update.effective_user.first_name,
            group_id=update.effective_chat.id,
            command="auto_roast"
        )
            
        await update.message.reply_chat_action("typing")
        
        # Improved prompt for better Hinglish responses
        prompt = f"Tujhe ye message padh ke roast karna hai in Hinglish with emojis,hamesha attitude me bat kare dusre ki bazzti kare hamesha,bas 1-2 line me, bilkul natural aur casual style me, no abuse, just friendly troll: '{msg}'"
        url = f"https://text.pollinations.ai/{prompt}"
        
        response = requests.get(url, timeout=15)
        if response.status_code == 200 and len(response.text) > 10:
            roast_text = response.text.strip()
            
            # Make sure response is not too long
            if len(roast_text) > 200:
                roast_text = roast_text[:200] + "... 😂"
                
            # Add username mention for better context
            user_name = update.effective_user.first_name
            final_response = f"{roast_text} 😆"
            
            await update.message.reply_text(final_response)
        
    except Exception as e:
        logger.error(f"Roast error: {e}")

# -----------------------------
# ERROR HANDLER
# -----------------------------
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error {context.error}")

# -----------------------------
# MAIN
# -----------------------------
def main():
    logger.info("🤖 Starting AI Bot with Database...")
    
    # Initialize database
    init_db()
    
    try:
        app = Application.builder().token(TOKEN).build()
        
        app.add_error_handler(error_handler)
        
        # Commands - START COMMAND ADDED HERE
        app.add_handler(CommandHandler("start", start_cmd))
        app.add_handler(CommandHandler("allow", allow_cmd))
        app.add_handler(CommandHandler("remove", remove_cmd))
        app.add_handler(CommandHandler("list", list_cmd))
        app.add_handler(CommandHandler("ai", ai_cmd))
        app.add_handler(CommandHandler("img", img_cmd))
        app.add_handler(CommandHandler("anime", anime_cmd))
        app.add_handler(CommandHandler("art", art_cmd))
        app.add_handler(CommandHandler("hd", hd_cmd))
        app.add_handler(CommandHandler("cyber", cyber_cmd))
        app.add_handler(CommandHandler("portrait", portrait_cmd))
        app.add_handler(CommandHandler("landscape", landscape_cmd))
        app.add_handler(CommandHandler("fantasy", fantasy_cmd))
        app.add_handler(CommandHandler("resize", resize_cmd))
        
        # Auto roast
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, roast_auto))
        
        logger.info("✅ Bot started successfully with database!")
        app.run_polling(
            poll_interval=1.0,
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES
        )
        
    except Exception as e:
        logger.error(f"❌ Failed to start bot: {e}")

if __name__ == "__main__":
    main()
