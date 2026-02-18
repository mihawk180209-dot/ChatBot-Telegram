# src/handlers.py
import time
import asyncio
import logging
from datetime import datetime, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction, ParseMode
from telegram.ext import ContextTypes
from telegram.error import RetryAfter

from src.config import Config
from src.database import add_message, get_history, clear_history, get_global_stats, get_user_stats
from src.hf_client import generate_chat_stream, HuggingFaceAPIError
from src.middlewares import rate_limiter, validate_input
from src.prompts import SYSTEM_PROMPT

logger = logging.getLogger(__name__)

# ╔══════════════════════════════════════════════════════════╗
# ║                   HELPER UTILITIES                       ║
# ╚══════════════════════════════════════════════════════════╝

_boot_time = datetime.now(timezone.utc)

def _uptime() -> str:
    """Calculate bot uptime as human-readable string."""
    delta = datetime.now(timezone.utc) - _boot_time
    hours, remainder = divmod(int(delta.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)
    days, hours = divmod(hours, 24)
    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m {seconds}s")
    return " ".join(parts)


def _escape_md(text: str) -> str:
    """Escape special characters for MarkdownV2."""
    special = r'_*[]()~`>#+-=|{}.!'
    for char in special:
        text = text.replace(char, f'\\{char}')
    return text


def _format_number(n: int) -> str:
    """Format large numbers with comma separators."""
    return f"{n:,}"


# ╔══════════════════════════════════════════════════════════╗
# ║                  COMMAND HANDLERS                        ║
# ╚══════════════════════════════════════════════════════════╝

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start - Welcome new users with a styled intro."""
    user = update.effective_user
    await clear_history(user.id)

    welcome_text = (
        f"👋 **Yo, {user.first_name}!**\n\n"
        f"Gue **{Config.BOT_NAME}** — AI assistant yang siap bantuin lu.\n"
        f"Mau nanya apapun? Gas aja langsung.\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔹 `/reset` — Hapus ingatan, mulai fresh\n"
        f"🔹 `/help` — Lihat semua command\n"
        f"🔹 `/info` — Info tentang bot ini\n"
        f"🔹 `/mydata` — Statistik percakapan lu\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Langsung aja ketik pesan lu 👇"
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 Reset Chat", callback_data="reset_chat"),
            InlineKeyboardButton("ℹ️ Info Bot", callback_data="bot_info"),
        ]
    ])

    await update.message.reply_text(
        welcome_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard
    )
    logger.info(f"🆕 New user started: {user.first_name} (ID: {user.id})")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help - Show all available commands."""
    is_admin = update.effective_user.id in Config.ADMIN_IDS

    help_text = (
        "📖 **Daftar Command**\n\n"
        "🔹 `/start` — Mulai ulang & sambutan\n"
        "🔹 `/reset` — Hapus histori percakapan\n"
        "🔹 `/help` — Tampilkan bantuan ini\n"
        "🔹 `/info` — Informasi tentang bot\n"
        "🔹 `/mydata` — Statistik percakapan lu\n"
        "🔹 `/ping` — Cek apakah bot hidup\n"
    )

    if is_admin:
        help_text += (
            "\n🔐 **Admin Commands**\n"
            "🔸 `/stats` — Statistik global bot\n"
            "🔸 `/health` — Health check sistem\n"
        )

    help_text += (
        "\n━━━━━━━━━━━━━━━━━━━━━━\n"
        "💡 **Tips:** Langsung ketik pesan aja buat ngobrol!\n"
        f"⚡ Rate limit: {Config.RATE_LIMIT} pesan/menit\n"
        f"📝 Max input: {_format_number(Config.MAX_INPUT_CHARS)} karakter"
    )

    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)


async def info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /info - Show bot information and specs."""
    model_short = Config.HF_MODEL.split("/")[-1] if "/" in Config.HF_MODEL else Config.HF_MODEL

    info_text = (
        f"🤖 **{Config.BOT_NAME}**\n"
        f"_{Config.BOT_DESCRIPTION}_\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 **Version:** `{Config.BOT_VERSION}`\n"
        f"🧠 **Model:** `{model_short}`\n"
        f"🌡️ **Temperature:** `{Config.TEMPERATURE}`\n"
        f"🎯 **Top-P:** `{Config.TOP_P}`\n"
        f"📊 **Max Tokens:** `{_format_number(Config.MAX_NEW_TOKENS)}`\n"
        f"💬 **Context Window:** `{Config.MAX_HISTORY_MESSAGES} messages`\n"
        f"⏱️ **Uptime:** `{_uptime()}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━"
    )

    await update.message.reply_text(info_text, parse_mode=ParseMode.MARKDOWN)


async def ping_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /ping - Simple alive check with latency."""
    start = time.monotonic()
    msg = await update.message.reply_text("🏓 Pong!")
    latency_ms = (time.monotonic() - start) * 1000

    await msg.edit_text(
        f"🏓 **Pong!**\n"
        f"⚡ Latency: `{latency_ms:.0f}ms`\n"
        f"⏱️ Uptime: `{_uptime()}`",
        parse_mode=ParseMode.MARKDOWN
    )


async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /reset - Clear conversation history."""
    user_id = update.effective_user.id
    await clear_history(user_id)

    await update.message.reply_text(
        "🧹 **Chat direset!**\n\n"
        "Ingatan percakapan udah dihapus. Fresh start! 🔄\n"
        "Langsung gas aja ketik pesan baru.",
        parse_mode=ParseMode.MARKDOWN
    )
    logger.info(f"🔄 User {user_id} reset their chat history")


async def mydata_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /mydata - Show user's personal conversation stats."""
    user_id = update.effective_user.id
    user = update.effective_user

    user_stats = await get_user_stats(user_id)
    history = await get_history(user_id, limit=Config.MAX_HISTORY_MESSAGES)

    user_msgs = sum(1 for m in history if m.get("role") == "user")
    bot_msgs = sum(1 for m in history if m.get("role") == "assistant")

    stats_text = (
        f"📊 **Data Lu, {user.first_name}**\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💬 Total pesan lu     : `{_format_number(user_stats.get('total_messages', 0))}`\n"
        f"📨 Di sesi ini (user) : `{user_msgs}`\n"
        f"🤖 Di sesi ini (bot)  : `{bot_msgs}`\n"
        f"📅 Pertama chat       : `{user_stats.get('first_seen', 'N/A')}`\n"
        f"🕐 Terakhir aktif     : `{user_stats.get('last_active', 'N/A')}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🗂️ Context window     : `{len(history)}/{Config.MAX_HISTORY_MESSAGES}`"
    )

    await update.message.reply_text(stats_text, parse_mode=ParseMode.MARKDOWN)


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /stats - Admin-only global statistics."""
    user_id = update.effective_user.id
    if user_id not in Config.ADMIN_IDS:
        await update.message.reply_text("🚫 Lu ga punya akses ke command ini.")
        logger.warning(f"⚠️ Unauthorized /stats attempt by user {user_id}")
        return

    stats = await get_global_stats()
    uptime_str = _uptime()

    stats_text = (
        f"📊 **Global Bot Statistics**\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 Total Users    : `{_format_number(stats.get('total_users', 0))}`\n"
        f"💬 Total Messages : `{_format_number(stats.get('total_messages', 0))}`\n"
        f"📈 Active Today   : `{_format_number(stats.get('active_today', 0))}`\n"
        f"⏱️ Uptime         : `{uptime_str}`\n"
        f"🧠 Model          : `{Config.HF_MODEL.split('/')[-1]}`\n"
        f"🌡️ Temperature    : `{Config.TEMPERATURE}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━"
    )

    await update.message.reply_text(stats_text, parse_mode=ParseMode.MARKDOWN)


async def health_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /health - Admin-only system health check."""
    user_id = update.effective_user.id
    if user_id not in Config.ADMIN_IDS:
        await update.message.reply_text("🚫 Admin only.")
        return

    # Check HF API reachability
    import httpx
    hf_status = "❌ Unreachable"
    hf_latency = "N/A"
    try:
        start = time.monotonic()
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://huggingface.co/api/models/" + Config.HF_MODEL,
                headers={"Authorization": f"Bearer {Config.HF_TOKEN}"}
            )
            hf_latency = f"{(time.monotonic() - start) * 1000:.0f}ms"
            if resp.status_code == 200:
                hf_status = "✅ Online"
            else:
                hf_status = f"⚠️ Status {resp.status_code}"
    except Exception as e:
        hf_status = f"❌ Error: {str(e)[:50]}"

    health_text = (
        f"🏥 **System Health Check**\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🤖 Bot Status     : ✅ Running\n"
        f"⏱️ Uptime          : `{_uptime()}`\n"
        f"🧠 HF API Status  : {hf_status}\n"
        f"📡 HF Latency     : `{hf_latency}`\n"
        f"📦 Version        : `{Config.BOT_VERSION}`\n"
        f"🔧 Model          : `{Config.HF_MODEL.split('/')[-1]}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━"
    )

    await update.message.reply_text(health_text, parse_mode=ParseMode.MARKDOWN)


# ╔══════════════════════════════════════════════════════════╗
# ║                  CALLBACK HANDLER                        ║
# ╚══════════════════════════════════════════════════════════╝

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline keyboard button presses."""
    query = update.callback_query
    await query.answer()

    if query.data == "reset_chat":
        user_id = query.from_user.id
        await clear_history(user_id)
        await query.edit_message_text(
            "🧹 **Chat direset!** Fresh start! 🔄\n\nLangsung ketik pesan baru.",
            parse_mode=ParseMode.MARKDOWN
        )
        logger.info(f"🔄 User {user_id} reset via button")

    elif query.data == "bot_info":
        model_short = Config.HF_MODEL.split("/")[-1] if "/" in Config.HF_MODEL else Config.HF_MODEL
        info_text = (
            f"🤖 **{Config.BOT_NAME}** v{Config.BOT_VERSION}\n\n"
            f"🧠 Model: `{model_short}`\n"
            f"🌡️ Temp: `{Config.TEMPERATURE}` | Top-P: `{Config.TOP_P}`\n"
            f"⏱️ Uptime: `{_uptime()}`"
        )
        await query.edit_message_text(info_text, parse_mode=ParseMode.MARKDOWN)


# ╔══════════════════════════════════════════════════════════╗
# ║                  MESSAGE HANDLER                         ║
# ╚══════════════════════════════════════════════════════════╝

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming text messages - main AI conversation flow."""
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    user_text = update.message.text

    # ── Rate Limiting ────────────────────────────────────────
    if not rate_limiter.is_allowed(user_id):
        remaining = rate_limiter.get_cooldown(user_id) if hasattr(rate_limiter, 'get_cooldown') else "beberapa"
        await update.message.reply_text(
            f"⏳ Sabar bro, lu ngirim pesan kecepetan.\n"
            f"Tunggu `{remaining}` detik lagi ya.",
            parse_mode=ParseMode.MARKDOWN
        )
        logger.info(f"⏳ Rate limited: {user_name} (ID: {user_id})")
        return

    # ── Input Validation ─────────────────────────────────────
    is_valid, sanitized_text = validate_input(user_text)
    if not is_valid:
        await update.message.reply_text(f"⚠️ {sanitized_text}")
        return

    # ── Show Typing ──────────────────────────────────────────
    await update.message.chat.send_action(action=ChatAction.TYPING)

    # ── Build Context ────────────────────────────────────────
    await add_message(user_id, "user", sanitized_text)
    history = await get_history(user_id, limit=Config.MAX_HISTORY_MESSAGES)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history

    logger.info(f"💬 [{user_name}:{user_id}] {sanitized_text[:80]}{'...' if len(sanitized_text) > 80 else ''}")

    # ── Streaming Response ───────────────────────────────────
    placeholder_message = await update.message.reply_text("💭 _Mikir..._", parse_mode=ParseMode.MARKDOWN)
    full_response = ""
    last_edit_time = time.time()
    chunk_count = 0
    gen_start = time.monotonic()

    try:
        async for chunk in generate_chat_stream(messages):
            if not chunk.strip():
                continue
            full_response += chunk
            chunk_count += 1
            current_time = time.time()

            if current_time - last_edit_time > Config.STREAM_EDIT_INTERVAL:
                try:
                    display_text = full_response + f" {Config.TYPING_CURSOR}"
                    await placeholder_message.edit_text(display_text)
                    last_edit_time = current_time
                except RetryAfter as e:
                    await asyncio.sleep(e.retry_after)
                except Exception:
                    pass

        gen_duration = time.monotonic() - gen_start

        if full_response.strip():
            await placeholder_message.edit_text(full_response)
            await add_message(user_id, "assistant", full_response)
            logger.info(
                f"✅ [{user_name}:{user_id}] Response sent | "
                f"{len(full_response)} chars | {chunk_count} chunks | "
                f"{gen_duration:.1f}s"
            )
        else:
            raise HuggingFaceAPIError("Empty response from model.")

    except HuggingFaceAPIError as e:
        await placeholder_message.edit_text(
            "⚠️ **AI lagi gangguan nih.**\n"
            "Coba lagi ntar ya, biasanya bentar doang.",
            parse_mode=ParseMode.MARKDOWN
        )
        logger.error(f"❌ Generation error for {user_name} (ID: {user_id}): {e}")

    except Exception as e:
        await placeholder_message.edit_text(
            "💥 **Ada error aneh.**\n"
            "Gue lagi dibenerin, coba lagi ntar.",
            parse_mode=ParseMode.MARKDOWN
        )
        logger.exception(f"💥 Unexpected error for {user_name} (ID: {user_id}):")


# ╔══════════════════════════════════════════════════════════╗
# ║                  ERROR HANDLER                           ║
# ╚══════════════════════════════════════════════════════════╝

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Global error handler for unhandled exceptions."""
    logger.error(f"🔥 Unhandled exception: {context.error}", exc_info=context.error)

    if update and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "💥 Ada error yang ga ketangkep. Tim gue lagi cek.",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            pass