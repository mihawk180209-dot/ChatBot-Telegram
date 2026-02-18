import os
import sys
import signal
import asyncio
import uvicorn
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)
from src.config import Config
from src.database import init_db, get_db_info
from src.handlers import (
    start_command,
    reset_command,
    stats_command,
    handle_message,
    help_command,
    info_command,
    ping_command,
    mydata_command,
    health_command,
    button_callback,
    error_handler,
)
from src.server import app

import logging

logger = logging.getLogger(__name__)

# ╔══════════════════════════════════════════════════════════╗
# ║                 🌐 FASTAPI WEB SERVER                    ║
# ╚══════════════════════════════════════════════════════════╝

async def start_fastapi():
    """Run lightweight FastAPI server for health checks (Railway/Render requires a web port)."""
    port = int(os.getenv("PORT", "8000"))
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    logger.info(f"🌐 FastAPI health server starting on port {port}")
    await server.serve()


# ╔══════════════════════════════════════════════════════════╗
# ║                 🤖 TELEGRAM BOT CORE                     ║
# ╚══════════════════════════════════════════════════════════╝

async def post_init(application: Application):
    """Hook that runs after bot is fully initialized — sets commands & logs info."""
    bot = application.bot
    bot_info = await bot.get_me()

    # ── Set visible command menu in Telegram ─────────────────
    from telegram import BotCommand

    commands = [
        BotCommand("start", "🚀 Mulai & sambutan"),
        BotCommand("reset", "🧹 Hapus histori chat"),
        BotCommand("help", "📖 Daftar semua command"),
        BotCommand("info", "ℹ️ Info tentang bot"),
        BotCommand("mydata", "📊 Statistik percakapan lu"),
        BotCommand("ping", "🏓 Cek bot hidup"),
    ]
    await bot.set_my_commands(commands)

    # ── Startup banner ───────────────────────────────────────
    db_info = await get_db_info()
    logger.info(
        f"\n"
        f"╔══════════════════════════════════════════════╗\n"
        f"║            🤖 BOT ONLINE & READY             ║\n"
        f"╠══════════════════════════════════════════════╣\n"
        f"║ Username : @{bot_info.username:<31}║\n"
        f"║ Name     : {bot_info.first_name:<32}║\n"
        f"║ Bot ID   : {bot_info.id:<32}║\n"
        f"║ Model    : {Config.HF_MODEL.split('/')[-1]:<32}║\n"
        f"║ DB Users : {db_info['total_users']:<32}║\n"
        f"║ DB Msgs  : {db_info['total_messages']:<32}║\n"
        f"║ DB Size  : {db_info['db_size']:<32}║\n"
        f"║ Admins   : {len(Config.ADMIN_IDS):<32}║\n"
        f"║ Commands : {len(commands)} registered{' ' * 21}║\n"
        f"╚══════════════════════════════════════════════╝"
    )


async def start_bot():
    """Initialize and run Telegram Bot with all handlers."""
    # ── Database init ────────────────────────────────────────
    await init_db()

    # ── Validate config before starting ──────────────────────
    config_errors = Config.validate()
    critical = [e for e in config_errors if "❌" in e]
    if critical:
        for err in critical:
            logger.critical(err)
        logger.critical("🛑 Cannot start bot — fix critical config errors above!")
        sys.exit(1)

    for warning in [e for e in config_errors if "⚠️" in e]:
        logger.warning(warning)

    # ── Build application ────────────────────────────────────
    application = (
        Application.builder()
        .token(Config.BOT_TOKEN)
        .post_init(post_init)
        .job_queue(None)
        .build()
    )

    # ── Register command handlers ────────────────────────────
    command_handlers = [
        ("start", start_command),
        ("reset", reset_command),
        ("help", help_command),
        ("info", info_command),
        ("ping", ping_command),
        ("mydata", mydata_command),
        ("stats", stats_command),       # admin only
        ("health", health_command),     # admin only
    ]

    for cmd_name, cmd_func in command_handlers:
        application.add_handler(CommandHandler(cmd_name, cmd_func))
        logger.debug(f"📌 Registered command: /{cmd_name}")

    # ── Register message & callback handlers ─────────────────
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )
    application.add_handler(CallbackQueryHandler(button_callback))

    # ── Register global error handler ────────────────────────
    application.add_error_handler(error_handler)

    logger.info(
        f"📌 Registered {len(command_handlers)} commands, "
        f"1 message handler, 1 callback handler, 1 error handler"
    )

    # ── Start polling ────────────────────────────────────────
    logger.info("🚀 Bot polling is starting...")

    await application.initialize()
    await application.start()
    await application.updater.start_polling(
        drop_pending_updates=True,
        allowed_updates=["message", "callback_query"],
    )

    # ── Keep alive until shutdown signal ─────────────────────
    stop_event = asyncio.Event()

    # Handle graceful shutdown signals
    def _signal_handler():
        logger.info("🛑 Shutdown signal received...")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass

    await stop_event.wait()

    # ── Graceful shutdown ────────────────────────────────────
    logger.info("🔄 Shutting down bot gracefully...")
    await application.updater.stop()
    await application.stop()
    await application.shutdown()
    logger.info("✅ Bot shutdown complete.")


# ╔══════════════════════════════════════════════════════════╗
# ║                    🏁 MAIN ENTRY                         ║
# ╚══════════════════════════════════════════════════════════╝

async def main():
    """Run both Bot and Web Server concurrently."""
    logger.info(
        f"\n"
        f"🏁 ═══════════════════════════════════════════\n"
        f"   {Config.BOT_NAME} v{Config.BOT_VERSION} — Starting up...\n"
        f"   Python {sys.version.split()[0]} | PID {os.getpid()}\n"
        f"🏁 ═══════════════════════════════════════════"
    )

    await asyncio.gather(
        start_bot(),
        start_fastapi(),
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Graceful shutdown via KeyboardInterrupt. Bye!")
    except SystemExit as e:
        logger.info(f"🛑 System exit with code {e.code}")
    except Exception as e:
        logger.critical(f"💥 Fatal error: {e}", exc_info=True)
        sys.exit(1)