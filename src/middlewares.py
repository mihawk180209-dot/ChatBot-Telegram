import time
from collections import defaultdict
from src.config import Config
import logging

logger = logging.getLogger(__name__)

class RateLimiter:
    def __init__(self, limit: int, window: int = 60):
        self.limit = limit
        self.window = window
        self.users = defaultdict(list)

    def is_allowed(self, user_id: int) -> bool:
        now = time.time()
        # Clean old records
        self.users[user_id] = [req for req in self.users[user_id] if req > now - self.window]
        
        if len(self.users[user_id]) >= self.limit:
            return False
            
        self.users[user_id].append(now)
        return True

rate_limiter = RateLimiter(Config.RATE_LIMIT)

def validate_input(text: str) -> tuple[bool, str]:
    """Sanitize and validate input length to prevent DoS."""
    if not text or not text.strip():
        return False, "Message is empty."
    if len(text) > Config.MAX_INPUT_CHARS:
        return False, f"Message too long. Please keep it under {Config.MAX_INPUT_CHARS} characters."
    return True, text.strip()