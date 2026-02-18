# src/hf_client.py
import httpx
import json
import time
import logging
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
    after_log,
)
from src.config import Config

logger = logging.getLogger(__name__)


class HuggingFaceAPIError(Exception):
    """Custom exception for HF API failures with status code tracking."""
    def __init__(self, message: str, status_code: int = None):
        self.status_code = status_code
        super().__init__(message)

    def __str__(self):
        base = super().__str__()
        if self.status_code:
            return f"[HTTP {self.status_code}] {base}"
        return base


# ╔══════════════════════════════════════════════════════════╗
# ║              🧠 HF API CLIENT (Streaming)               ║
# ╚══════════════════════════════════════════════════════════╝

# Simple request stats tracker
class _APIStats:
    """Track API call statistics for monitoring."""
    def __init__(self):
        self.total_requests = 0
        self.successful = 0
        self.failed = 0
        self.total_tokens_generated = 0
        self.total_latency = 0.0

    def record_success(self, chars: int, latency: float):
        self.total_requests += 1
        self.successful += 1
        self.total_tokens_generated += chars
        self.total_latency += latency

    def record_failure(self):
        self.total_requests += 1
        self.failed += 1

    @property
    def avg_latency(self) -> float:
        return self.total_latency / self.successful if self.successful > 0 else 0.0

    @property
    def success_rate(self) -> float:
        return (self.successful / self.total_requests * 100) if self.total_requests > 0 else 0.0

    def summary(self) -> str:
        return (
            f"📡 API Stats: {self.total_requests} calls | "
            f"✅ {self.successful} ok | ❌ {self.failed} fail | "
            f"📊 {self.success_rate:.1f}% success | "
            f"⏱️ {self.avg_latency:.1f}s avg"
        )


api_stats = _APIStats()


def _get_error_message(status_code: int) -> str:
    """Return user-friendly error message based on HTTP status."""
    error_map = {
        400: "Bad request — pesan mungkin terlalu panjang atau format salah.",
        401: "Authentication failed — token HF ga valid.",
        403: "Access denied — model ga bisa diakses.",
        404: "Model not found — cek nama model di config.",
        422: "Input ga valid — coba pake pesan yang lebih pendek.",
        429: "Rate limit HF — terlalu banyak request, tunggu bentar.",
        500: "Server HF lagi error.",
        502: "Bad gateway — HF infrastructure issue.",
        503: "Model lagi loading atau overloaded.",
    }
    return error_map.get(status_code, f"Unknown error (HTTP {status_code})")


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((httpx.RequestError, httpx.TimeoutException)),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
async def generate_chat_stream(messages: list):
    """
    Communicates with Hugging Face via OpenAI-compatible endpoint.
    Yields chunks of response text for streaming display.

    Features:
    - SSE streaming support
    - Fallback to JSON response
    - Retry with exponential backoff
    - Performance tracking
    """

    headers = {
        "Authorization": f"Bearer {Config.HF_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }

    payload = {
        "model": Config.HF_MODEL,
        "messages": messages,
        "temperature": Config.TEMPERATURE,
        "top_p": Config.TOP_P,
        "max_tokens": Config.MAX_NEW_TOKENS,
        "stream": True,
    }

    start_time = time.monotonic()
    total_chars = 0
    model_short = Config.HF_MODEL.split("/")[-1] if "/" in Config.HF_MODEL else Config.HF_MODEL

    logger.debug(
        f"🚀 Sending request to HF | Model: {model_short} | "
        f"Messages: {len(messages)} | Temp: {Config.TEMPERATURE}"
    )

    async with httpx.AsyncClient(timeout=90.0) as client:
        try:
            async with client.stream(
                "POST",
                Config.HF_API_URL,
                json=payload,
                headers=headers,
            ) as response:

                # ── Error Handling ───────────────────────────
                if response.status_code != 200:
                    err_body = await response.aread()
                    err_decoded = err_body.decode(errors="replace")
                    friendly_msg = _get_error_message(response.status_code)

                    logger.error(
                        f"❌ HF API Error [{response.status_code}]: {err_decoded[:300]}"
                    )
                    api_stats.record_failure()

                    # Don't retry on client errors (4xx) except 429
                    if 400 <= response.status_code < 500 and response.status_code != 429:
                        raise HuggingFaceAPIError(friendly_msg, response.status_code)

                    raise HuggingFaceAPIError(friendly_msg, response.status_code)

                content_type = response.headers.get("content-type", "")

                # ── CASE 1: SSE Streaming ────────────────────
                if "text/event-stream" in content_type:
                    logger.debug("📡 Receiving SSE stream...")
                    chunk_count = 0

                    async for line in response.aiter_lines():
                        if not line.startswith("data: "):
                            continue

                        data_str = line[6:].strip()
                        if data_str == "[DONE]":
                            logger.debug(f"✅ SSE stream completed | {chunk_count} chunks")
                            break

                        try:
                            data_json = json.loads(data_str)
                            choices = data_json.get("choices")
                            if not choices or len(choices) == 0:
                                continue

                            delta = choices[0].get("delta", {})
                            finish_reason = choices[0].get("finish_reason")

                            chunk = delta.get("content", "")
                            if chunk:
                                total_chars += len(chunk)
                                chunk_count += 1
                                yield chunk

                            if finish_reason == "stop":
                                logger.debug("✅ Stream finished (stop reason)")
                                break

                        except json.JSONDecodeError:
                            logger.warning(f"⚠️ Malformed JSON chunk: {data_str[:100]}")
                            continue
                        except Exception as e:
                            logger.warning(f"⚠️ SSE parse error: {e}")
                            continue

                # ── CASE 2: Fallback JSON ────────────────────
                else:
                    logger.debug("📦 Receiving JSON fallback response...")
                    raw_data = await response.aread()

                    try:
                        data = json.loads(raw_data)
                    except json.JSONDecodeError:
                        logger.error(f"❌ Failed to parse JSON response: {raw_data[:200]}")
                        api_stats.record_failure()
                        raise HuggingFaceAPIError("Invalid JSON response from model.")

                    choices = data.get("choices", [])
                    if not choices:
                        logger.error(f"❌ Empty choices in response: {data}")
                        api_stats.record_failure()
                        raise HuggingFaceAPIError("Model returned empty response.")

                    message_obj = choices[0].get("message", {})
                    content = message_obj.get("content", "")

                    if not content:
                        logger.error(f"❌ Empty content in response: {data}")
                        api_stats.record_failure()
                        raise HuggingFaceAPIError("Model returned empty content.")

                    # Check for usage info
                    usage = data.get("usage", {})
                    if usage:
                        logger.info(
                            f"📊 Usage: prompt={usage.get('prompt_tokens', '?')} | "
                            f"completion={usage.get('completion_tokens', '?')} | "
                            f"total={usage.get('total_tokens', '?')}"
                        )

                    total_chars = len(content)
                    yield content

            # ── Record Success ───────────────────────────────
            latency = time.monotonic() - start_time
            api_stats.record_success(total_chars, latency)
            logger.info(
                f"✅ HF Response | {total_chars} chars | {latency:.1f}s | "
                f"{api_stats.summary()}"
            )

        except httpx.TimeoutException:
            api_stats.record_failure()
            logger.error(f"⏰ HF API Timeout after {time.monotonic() - start_time:.1f}s")
            raise HuggingFaceAPIError("Model terlalu lama merespon. Coba lagi.")

        except httpx.RequestError as e:
            api_stats.record_failure()
            logger.error(f"🌐 Network error: {e}")
            raise HuggingFaceAPIError(f"Koneksi ke AI gagal: {str(e)[:100]}")


def get_api_stats() -> dict:
    """Return current API stats as a dictionary."""
    return {
        "total_requests": api_stats.total_requests,
        "successful": api_stats.successful,
        "failed": api_stats.failed,
        "success_rate": f"{api_stats.success_rate:.1f}%",
        "avg_latency": f"{api_stats.avg_latency:.1f}s",
        "total_chars_generated": api_stats.total_tokens_generated,
    }