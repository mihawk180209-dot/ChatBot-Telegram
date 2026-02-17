import asyncio
import uvicorn
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from src.config import Config
from src.database import init_db
from src.handlers import start_command, reset_command, stats_command, handle_message
from src.server import app

import logging
logger = logging.getLogger(__name__)

async def start_fastapi():
    """Run lightweight FastAPI server for health checks (Railway/Render requires a web port)"""
    config = uvicorn.Config(app, host="0.0.0.0", port=8000, log_level="warning")
    server = uvicorn.Server(config)
    await server.serve()

async def start_bot():
    """Initialize and run Telegram Bot"""
    await init_db()
    
   # Tambahkan .job_queue(None) untuk mem-bypass error weakref di Python 3.14
    application = Application.builder().token(Config.BOT_TOKEN).job_queue(None).build()
    
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("reset", reset_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("Bot is starting up...")
    
    # Run polling loop
    await application.initialize()
    await application.start()
    await application.updater.start_polling(drop_pending_updates=True)
    
    # Keep running
    stop_event = asyncio.Event()
    await stop_event.wait()

async def main():
    # Run both Bot and Web Server concurrently
    await asyncio.gather(
        start_bot(),
        start_fastapi()
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Graceful shutdown initiated.")