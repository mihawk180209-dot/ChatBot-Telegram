import os
import logging
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv

load_dotenv()

class Config:
    BOT_TOKEN = os.getenv("BOT_TOKEN", "")
    HF_TOKEN = os.getenv("HF_TOKEN", "")
    HF_MODEL = os.getenv("HF_MODEL", "meta-llama/Meta-Llama-3-8B-Instruct")
    
    # Security & Admin
    try:
        ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
    except ValueError:
        ADMIN_IDS = []
        
    MAX_INPUT_CHARS = int(os.getenv("MAX_USER_TOKENS", "2000"))
    RATE_LIMIT = int(os.getenv("RATE_LIMIT_PER_MINUTE", "5"))
    
    # Model Params
    TEMPERATURE = float(os.getenv("TEMPERATURE", "0.7"))
    TOP_P = float(os.getenv("TOP_P", "0.9"))
    MAX_NEW_TOKENS = int(os.getenv("MAX_NEW_TOKENS", "1024"))
    
    # HF Base URL (using OpenAI compatible endpoint for ease of chat formatting)
    # Using the newer endpoint format with model in the path
    HF_API_URL = "https://router.huggingface.co/v1/chat/completions"


# Structured & Masked Logging
class TokenFilter(logging.Filter):
    def filter(self, record):
        message = record.getMessage()
        if Config.BOT_TOKEN in message:
            record.msg = message.replace(Config.BOT_TOKEN, "***BOT_TOKEN***")
        if Config.HF_TOKEN in message:
            record.msg = message.replace(Config.HF_TOKEN, "***HF_TOKEN***")
        return True

def setup_logging():
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # Console Handler
    ch = logging.StreamHandler()
    ch.setFormatter(formatter)
    ch.addFilter(TokenFilter())
    
    # File Handler
    if not os.path.exists("logs"):
        os.makedirs("logs")
    fh = RotatingFileHandler("logs/bot.log", maxBytes=5*1024*1024, backupCount=3)
    fh.setFormatter(formatter)
    fh.addFilter(TokenFilter())
    
    logger.addHandler(ch)
    logger.addHandler(fh)
    
    # Silence third party logs
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.INFO)

setup_logging()
logger = logging.getLogger(__name__)