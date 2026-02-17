# src/handlers.py
import time
import asyncio
import logging
from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import ContextTypes
from telegram.error import RetryAfter

from src.config import Config
from src.database import add_message, get_history, clear_history, get_global_stats
from src.hf_client import generate_chat_stream, HuggingFaceAPIError
from src.middlewares import rate_limiter, validate_input
from src.prompts import SYSTEM_PROMPT

logger = logging.getLogger(__name__)

# --------------------------
# COMMAND HANDLERS
# --------------------------

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await clear_history(user.id)
    await update.message.reply_text(
        f"Halo {user.first_name}! Saya adalah AI Assistant siap membantu Anda. Silakan mulai mengobrol!\n\n"
        "Gunakan /reset jika ingin memulai topik baru."
    )

async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await clear_history(user_id)
    await update.message.reply_text("Ingatan tentang percakapan kita telah dihapus. Mari mulai dari awal!")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in Config.ADMIN_IDS:
        return await update.message.reply_text("You are not authorized to use this command.")
    
    stats = await get_global_stats()
    await update.message.reply_text(
        f"📊 **Global Stats**\n\nTotal Users: {stats['total_users']}\nTotal Messages: {stats['total_messages']}",
        parse_mode=ParseMode.MARKDOWN
    )

# --------------------------
# MESSAGE HANDLER
# --------------------------

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_text = update.message.text

    if not rate_limiter.is_allowed(user_id):
        return await update.message.reply_text("⏳ Anda mengirim pesan terlalu cepat. Mohon tunggu beberapa saat.")

    is_valid, sanitized_text = validate_input(user_text)
    if not is_valid:
        return await update.message.reply_text(f"⚠️ {sanitized_text}")

    await update.message.chat.send_action(action=ChatAction.TYPING)

    await add_message(user_id, "user", sanitized_text)
    history = await get_history(user_id, limit=10)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history

    placeholder_message = await update.message.reply_text("...")
    full_response = ""
    last_edit_time = time.time()
    edit_buffer_time = 0.8

    try:
        async for chunk in generate_chat_stream(messages):
            if not chunk.strip():
                continue  # skip empty chunk
            full_response += chunk
            current_time = time.time()

            if current_time - last_edit_time > edit_buffer_time:
                try:
                    await placeholder_message.edit_text(full_response + " ▌")
                    last_edit_time = current_time
                except RetryAfter as e:
                    await asyncio.sleep(e.retry_after)
                except Exception:
                    pass

        if full_response.strip():
            await placeholder_message.edit_text(full_response)
            await add_message(user_id, "assistant", full_response)
        else:
            raise HuggingFaceAPIError("Empty response from model.")

    except HuggingFaceAPIError as e:
        await placeholder_message.edit_text("⚠️ Maaf, layanan AI sedang mengalami gangguan. Silakan coba beberapa saat lagi.")
        logger.error(f"Generation error for user {user_id}: {e}")
    except Exception as e:
        await placeholder_message.edit_text("⚠️ Terjadi kesalahan sistem yang tidak terduga.")
        logger.exception("Unexpected error during generation:")
