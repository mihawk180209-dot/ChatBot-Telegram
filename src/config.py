import os
import sys
import logging
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv

load_dotenv()

# ╔══════════════════════════════════════════════════════════╗
# ║               🤖 BOT CONFIGURATION CENTER               ║
# ╚══════════════════════════════════════════════════════════╝

class Config:
    # ── Core Tokens ──────────────────────────────────────────
    BOT_TOKEN = os.getenv("BOT_TOKEN", "")
    HF_TOKEN = os.getenv("HF_TOKEN", "")
    HF_MODEL = os.getenv("HF_MODEL", "meta-llama/Meta-Llama-3-8B-Instruct")

    # ── Security & Admin ─────────────────────────────────────
    try:
        ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
    except ValueError:
        ADMIN_IDS = []

    MAX_INPUT_CHARS = int(os.getenv("MAX_USER_TOKENS", "2000"))
    RATE_LIMIT = int(os.getenv("RATE_LIMIT_PER_MINUTE", "5"))

    # ── Model Parameters ────────────────────────────────────
    TEMPERATURE = float(os.getenv("TEMPERATURE", "0.7"))
    TOP_P = float(os.getenv("TOP_P", "0.9"))
    MAX_NEW_TOKENS = int(os.getenv("MAX_NEW_TOKENS", "1024"))

    # ── API Endpoint ─────────────────────────────────────────
    HF_API_URL = "https://router.huggingface.co/v1/chat/completions"

    # ── Bot Identity ─────────────────────────────────────────
    BOT_VERSION = "2.1.0"
    BOT_NAME = os.getenv("BOT_NAME", "AI Assistant")
    BOT_DESCRIPTION = "Street-smart AI yang siap bantuin lu kapan aja 🤓"

    # ── History & Context ────────────────────────────────────
    MAX_HISTORY_MESSAGES = int(os.getenv("MAX_HISTORY_MESSAGES", "10"))
    HISTORY_TTL_HOURS = int(os.getenv("HISTORY_TTL_HOURS", "24"))

    # ── Streaming Display ────────────────────────────────────
    STREAM_EDIT_INTERVAL = float(os.getenv("STREAM_EDIT_INTERVAL", "0.8"))
    TYPING_CURSOR = "▌"

    @classmethod
    def validate(cls) -> list[str]:
        """Validate critical config values. Returns list of error messages."""
        errors = []
        if not cls.BOT_TOKEN:
            errors.append("❌ BOT_TOKEN is not set!")
        if not cls.HF_TOKEN:
            errors.append("❌ HF_TOKEN is not set!")
        if cls.TEMPERATURE < 0.0 or cls.TEMPERATURE > 2.0:
            errors.append(f"⚠️ TEMPERATURE={cls.TEMPERATURE} is out of recommended range (0.0-2.0)")
        if cls.TOP_P < 0.0 or cls.TOP_P > 1.0:
            errors.append(f"⚠️ TOP_P={cls.TOP_P} is out of range (0.0-1.0)")
        if cls.MAX_NEW_TOKENS < 1:
            errors.append(f"⚠️ MAX_NEW_TOKENS={cls.MAX_NEW_TOKENS} must be >= 1")
        if cls.RATE_LIMIT < 1:
            errors.append(f"⚠️ RATE_LIMIT={cls.RATE_LIMIT} must be >= 1")
        return errors

    @classmethod
    def summary(cls) -> str:
        """Return a human-readable config summary for boot logs."""
        admin_count = len(cls.ADMIN_IDS)
        model_short = cls.HF_MODEL.split("/")[-1] if "/" in cls.HF_MODEL else cls.HF_MODEL
        return (
            f"\n"
            f"╔══════════════════════════════════════════════╗\n"
            f"║        🤖 {cls.BOT_NAME} v{cls.BOT_VERSION}            ║\n"
            f"╠══════════════════════════════════════════════╣\n"
            f"║ Model      : {model_short:<30} ║\n"
            f"║ Temp       : {cls.TEMPERATURE:<30} ║\n"
            f"║ Top-P      : {cls.TOP_P:<30} ║\n"
            f"║ Max Tokens : {cls.MAX_NEW_TOKENS:<30} ║\n"
            f"║ Rate Limit : {cls.RATE_LIMIT}/min{' ' * 24}║\n"
            f"║ Max Input  : {cls.MAX_INPUT_CHARS} chars{' ' * 20}║\n"
            f"║ History    : {cls.MAX_HISTORY_MESSAGES} msgs / {cls.HISTORY_TTL_HOURS}h TTL{' ' * 14}║\n"
            f"║ Admins     : {admin_count} registered{' ' * 18}║\n"
            f"╚══════════════════════════════════════════════╝"
        )


# ╔══════════════════════════════════════════════════════════╗
# ║              📋 LOGGING SYSTEM SETUP                     ║
# ╚══════════════════════════════════════════════════════════╝

class TokenFilter(logging.Filter):
    """Mask sensitive tokens in log output."""
    SENSITIVE_KEYS = []

    def __init__(self):
        super().__init__()
        if Config.BOT_TOKEN:
            self.SENSITIVE_KEYS.append((Config.BOT_TOKEN, "***BOT_TOKEN***"))
        if Config.HF_TOKEN:
            self.SENSITIVE_KEYS.append((Config.HF_TOKEN, "***HF_TOKEN***"))

    def filter(self, record):
        message = record.getMessage()
        for token, mask in self.SENSITIVE_KEYS:
            if token in message:
                record.msg = message.replace(token, mask)
                record.args = None  # Prevent re-formatting with args
        return True


class ColorFormatter(logging.Formatter):
    """Colored console output for better readability."""
    COLORS = {
        logging.DEBUG:    "\033[36m",   # Cyan
        logging.INFO:     "\033[32m",   # Green
        logging.WARNING:  "\033[33m",   # Yellow
        logging.ERROR:    "\033[31m",   # Red
        logging.CRITICAL: "\033[1;31m", # Bold Red
    }
    RESET = "\033[0m"

    def format(self, record):
        color = self.COLORS.get(record.levelno, self.RESET)
        record.levelname = f"{color}{record.levelname}{self.RESET}"
        return super().format(record)


def setup_logging():
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # Avoid duplicate handlers on reload
    if logger.handlers:
        logger.handlers.clear()

    token_filter = TokenFilter()

    # ── Console Handler (with color) ─────────────────────────
    console_fmt = ColorFormatter(
        '%(asctime)s │ %(name)-20s │ %(levelname)-8s │ %(message)s',
        datefmt='%H:%M:%S'
    )
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(console_fmt)
    ch.addFilter(token_filter)

    # ── File Handler (structured) ────────────────────────────
    if not os.path.exists("logs"):
        os.makedirs("logs")

    file_fmt = logging.Formatter(
        '%(asctime)s | %(name)s | %(levelname)s | %(funcName)s:%(lineno)d | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    fh = RotatingFileHandler(
        "logs/bot.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding='utf-8'
    )
    fh.setFormatter(file_fmt)
    fh.addFilter(token_filter)

    logger.addHandler(ch)
    logger.addHandler(fh)

    # ── Silence noisy third-party loggers ────────────────────
    for noisy in ("httpx", "httpcore", "hpack", "h2", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.INFO)


# ── Initialize on import ────────────────────────────────────
setup_logging()
logger = logging.getLogger(__name__)

# Validate config on startup
_config_errors = Config.validate()
if _config_errors:
    for err in _config_errors:
        logger.error(err)
    if any("❌" in e for e in _config_errors):
        logger.critical("Critical configuration missing. Bot may not function properly!")

logger.info(Config.summary())