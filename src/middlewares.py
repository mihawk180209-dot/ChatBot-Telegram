# src/middlewares.py
import re
import time
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from src.config import Config

logger = logging.getLogger(__name__)

# ╔══════════════════════════════════════════════════════════╗
# ║              ⏱️ RATE LIMITER (Enhanced)                  ║
# ╚══════════════════════════════════════════════════════════╝

@dataclass
class _UserRateData:
    """Track per-user rate limiting data."""
    requests: list = field(default_factory=list)
    total_blocked: int = 0
    total_allowed: int = 0
    last_blocked_at: float = 0.0


class RateLimiter:
    """
    Sliding window rate limiter with cooldown tracking and analytics.
    
    Features:
    - Sliding window algorithm (not fixed window)
    - Per-user cooldown info
    - Block/allow statistics
    - Auto-cleanup of stale user data
    - Admin bypass support
    """

    def __init__(self, limit: int, window: int = 60):
        self.limit = limit
        self.window = window
        self._users: dict[int, _UserRateData] = defaultdict(_UserRateData)
        self._global_blocked = 0
        self._global_allowed = 0
        logger.info(
            f"⏱️ RateLimiter initialized | "
            f"Limit: {self.limit} req/{self.window}s"
        )

    def is_allowed(self, user_id: int) -> bool:
        """
        Check if user is within rate limit.
        Admins always pass.
        """
        # ── Admin bypass ─────────────────────────────────────
        if user_id in Config.ADMIN_IDS:
            self._global_allowed += 1
            return True

        now = time.time()
        data = self._users[user_id]

        # ── Clean expired requests ───────────────────────────
        data.requests = [t for t in data.requests if t > now - self.window]

        # ── Check limit ──────────────────────────────────────
        if len(data.requests) >= self.limit:
            data.total_blocked += 1
            data.last_blocked_at = now
            self._global_blocked += 1
            logger.debug(
                f"⏳ Rate limited user {user_id} | "
                f"{len(data.requests)}/{self.limit} in window | "
                f"Total blocks: {data.total_blocked}"
            )
            return False

        # ── Allow and record ─────────────────────────────────
        data.requests.append(now)
        data.total_allowed += 1
        self._global_allowed += 1
        return True

    def get_cooldown(self, user_id: int) -> int:
        """
        Get remaining cooldown seconds for a rate-limited user.
        Returns 0 if not currently limited.
        """
        if user_id in Config.ADMIN_IDS:
            return 0

        now = time.time()
        data = self._users[user_id]
        data.requests = [t for t in data.requests if t > now - self.window]

        if len(data.requests) < self.limit:
            return 0

        # Oldest request in window determines when slot opens
        oldest = min(data.requests)
        cooldown = int((oldest + self.window) - now) + 1
        return max(cooldown, 1)

    def get_remaining(self, user_id: int) -> int:
        """Get remaining allowed requests in current window."""
        if user_id in Config.ADMIN_IDS:
            return self.limit  # Admins always have full quota display

        now = time.time()
        data = self._users[user_id]
        data.requests = [t for t in data.requests if t > now - self.window]
        return max(0, self.limit - len(data.requests))

    def get_user_stats(self, user_id: int) -> dict:
        """Get rate limiting stats for a specific user."""
        data = self._users.get(user_id)
        if not data:
            return {
                "total_allowed": 0,
                "total_blocked": 0,
                "current_window": 0,
                "remaining": self.limit,
                "cooldown": 0,
            }

        now = time.time()
        active = [t for t in data.requests if t > now - self.window]
        return {
            "total_allowed": data.total_allowed,
            "total_blocked": data.total_blocked,
            "current_window": len(active),
            "remaining": self.get_remaining(user_id),
            "cooldown": self.get_cooldown(user_id),
        }

    def get_global_stats(self) -> dict:
        """Get global rate limiter statistics."""
        now = time.time()
        active_users = sum(
            1
            for data in self._users.values()
            if any(t > now - self.window for t in data.requests)
        )
        return {
            "total_tracked_users": len(self._users),
            "active_in_window": active_users,
            "global_allowed": self._global_allowed,
            "global_blocked": self._global_blocked,
            "block_rate": (
                f"{(self._global_blocked / (self._global_allowed + self._global_blocked) * 100):.1f}%"
                if (self._global_allowed + self._global_blocked) > 0
                else "0.0%"
            ),
            "limit": self.limit,
            "window": self.window,
        }

    def cleanup_stale(self, max_age: int = 3600):
        """Remove users who haven't made requests in max_age seconds."""
        now = time.time()
        stale_users = [
            uid
            for uid, data in self._users.items()
            if not data.requests or max(data.requests) < now - max_age
        ]
        for uid in stale_users:
            del self._users[uid]

        if stale_users:
            logger.debug(f"🧹 RateLimiter cleanup: removed {len(stale_users)} stale users")

        return len(stale_users)

    def reset_user(self, user_id: int):
        """Reset rate limit data for a specific user."""
        if user_id in self._users:
            del self._users[user_id]
            logger.debug(f"🔄 Rate limit reset for user {user_id}")


# ── Initialize global rate limiter ───────────────────────────
rate_limiter = RateLimiter(Config.RATE_LIMIT)


# ╔══════════════════════════════════════════════════════════╗
# ║              🛡️ INPUT VALIDATION (Enhanced)              ║
# ╚══════════════════════════════════════════════════════════╝

# Patterns that might indicate prompt injection or abuse
_SUSPICIOUS_PATTERNS = [
    r"ignore\s+(all\s+)?previous\s+instructions",
    r"ignore\s+(all\s+)?above",
    r"disregard\s+(all\s+)?previous",
    r"you\s+are\s+now\s+DAN",
    r"act\s+as\s+if\s+you\s+have\s+no\s+restrictions",
    r"pretend\s+you\s+(are|have)\s+no\s+(rules|restrictions|limits)",
    r"jailbreak",
    r"override\s+system\s+prompt",
    r"reveal\s+(your|the)\s+system\s+prompt",
    r"show\s+(me\s+)?(your|the)\s+(system\s+)?prompt",
    r"what\s+(is|are)\s+your\s+(system\s+)?(instructions|prompt|rules)",
]

_compiled_patterns = [
    re.compile(pattern, re.IGNORECASE) for pattern in _SUSPICIOUS_PATTERNS
]

# Characters/sequences that serve no conversational purpose
_SPAM_INDICATORS = {
    "max_repeating_chars": 20,     # e.g., "aaaaaaaaaaaaaaaaaaaaaa"
    "max_repeating_lines": 5,      # Same line repeated
    "min_meaningful_chars": 1,     # Must have at least 1 non-whitespace char
}


def validate_input(text: str) -> tuple[bool, str]:
    """
    Sanitize and validate user input.
    
    Checks:
    1. Empty/whitespace-only messages
    2. Character length limit
    3. Spam detection (repeating chars/lines)
    4. Prompt injection patterns (warning only, not blocked)
    
    Returns:
        (is_valid, sanitized_text_or_error_message)
    """

    # ── Check empty ──────────────────────────────────────────
    if not text or not text.strip():
        return False, "Pesan kosong. Ketik sesuatu dong 😅"

    cleaned = text.strip()

    # ── Check length ─────────────────────────────────────────
    if len(cleaned) > Config.MAX_INPUT_CHARS:
        return False, (
            f"Pesan lu kepanjangan! Max {Config.MAX_INPUT_CHARS:,} karakter, "
            f"lu ngirim {len(cleaned):,}. Potong dikit ya ✂️"
        )

    # ── Check minimum meaningful content ─────────────────────
    meaningful = re.sub(r'\s+', '', cleaned)
    if len(meaningful) < _SPAM_INDICATORS["min_meaningful_chars"]:
        return False, "Pesan lu cuma spasi doang. Serius dikit 😑"

    # ── Check repeating characters (spam) ────────────────────
    repeat_match = re.search(r'(.)\1{' + str(_SPAM_INDICATORS["max_repeating_chars"]) + r',}', cleaned)
    if repeat_match:
        return False, "Spam detected 🚫 Jangan kirim karakter berulang terus dong."

    # ── Check repeating lines (spam) ─────────────────────────
    lines = [line.strip() for line in cleaned.split('\n') if line.strip()]
    if len(lines) > 1:
        from collections import Counter
        line_counts = Counter(lines)
        most_common_count = line_counts.most_common(1)[0][1] if line_counts else 0
        if most_common_count > _SPAM_INDICATORS["max_repeating_lines"]:
            return False, "Spam detected 🚫 Jangan copas baris yang sama berulang kali."

    # ── Check prompt injection (log warning, don't block) ────
    for pattern in _compiled_patterns:
        if pattern.search(cleaned):
            logger.warning(
                f"🚨 Potential prompt injection detected: "
                f"'{cleaned[:100]}...'"
            )
            # We log but don't block — the system prompt should handle it
            break

    return True, cleaned


def validate_input_detailed(text: str) -> dict:
    """
    Extended validation that returns detailed analysis.
    Useful for admin/debug purposes.
    
    Returns dict with:
    - is_valid: bool
    - sanitized: str (cleaned text or error)
    - char_count: int
    - word_count: int
    - line_count: int
    - has_suspicious: bool
    - suspicious_matches: list[str]
    """
    is_valid, result = validate_input(text)

    if not text:
        return {
            "is_valid": False,
            "sanitized": result,
            "char_count": 0,
            "word_count": 0,
            "line_count": 0,
            "has_suspicious": False,
            "suspicious_matches": [],
        }

    cleaned = text.strip()

    # Find suspicious patterns
    suspicious = []
    for pattern in _compiled_patterns:
        match = pattern.search(cleaned)
        if match:
            suspicious.append(match.group())

    return {
        "is_valid": is_valid,
        "sanitized": result,
        "char_count": len(cleaned),
        "word_count": len(cleaned.split()),
        "line_count": len(cleaned.split('\n')),
        "has_suspicious": len(suspicious) > 0,
        "suspicious_matches": suspicious,
    }


# ╔══════════════════════════════════════════════════════════╗
# ║              📊 MIDDLEWARE STATS EXPORT                  ║
# ╚══════════════════════════════════════════════════════════╝

def get_middleware_stats() -> dict:
    """Get combined middleware statistics for admin dashboards."""
    return {
        "rate_limiter": rate_limiter.get_global_stats(),
        "config": {
            "max_input_chars": Config.MAX_INPUT_CHARS,
            "rate_limit": Config.RATE_LIMIT,
            "suspicious_patterns_loaded": len(_compiled_patterns),
            "admin_ids_count": len(Config.ADMIN_IDS),
        },
    }