import httpx
import json
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from src.config import Config
import logging

logger = logging.getLogger(__name__)

class HuggingFaceAPIError(Exception):
    """Custom exception for HF API failures."""
    pass

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((httpx.RequestError, httpx.TimeoutException, HuggingFaceAPIError)),
    reraise=True
)
async def generate_chat_stream(messages: list):
    """
    Communicates with Hugging Face via OpenAI-compatible endpoint.
    Yields chunks of response for simulated streaming.
    """

    headers = {
        "Authorization": f"Bearer {Config.HF_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream"
    }

    payload = {
        "model": Config.HF_MODEL,
        "messages": messages,
        "temperature": Config.TEMPERATURE,
        "top_p": Config.TOP_P,
        "max_tokens": Config.MAX_NEW_TOKENS,
        "stream": True
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            async with client.stream(
                "POST",
                Config.HF_API_URL,
                json=payload,
                headers=headers
            ) as response:

                if response.status_code != 200:
                    err_msg = await response.aread()
                    logger.error(f"HF API Error: {response.status_code} - {err_msg.decode()}")
                    raise HuggingFaceAPIError("Failed to fetch response from AI model.")

                content_type = response.headers.get("content-type", "")

                # CASE 1: SSE streaming
                if "text/event-stream" in content_type:
                    async for line in response.aiter_lines():
                        if not line.startswith("data: "):
                            continue

                        data_str = line[6:].strip()
                        if data_str == "[DONE]":
                            break

                        try:
                            data_json = json.loads(data_str)
                            # ✅ Validasi choices sebelum akses
                            choices = data_json.get("choices")
                            if not choices or len(choices) == 0:
                                continue

                            delta = choices[0].get("delta", {})
                            chunk = delta.get("content", "")
                            if chunk:
                                yield chunk

                        except json.JSONDecodeError:
                            logger.warning(f"Failed to parse JSON chunk: {data_str}")
                            continue
                        except Exception as e:
                            logger.warning(f"Unexpected SSE chunk structure: {data_json} | Error: {e}")
                            continue

                # CASE 2: Fallback JSON
                else:
                    data = await response.json()
                    choices = data.get("choices", [])
                    if not choices:
                        logger.error(f"HF API returned empty choices: {data}")
                        raise HuggingFaceAPIError("Model returned empty response.")

                    message_obj = choices[0].get("message", {})
                    content = message_obj.get("content", "")
                    if not content:
                        logger.error(f"HF API returned empty content: {data}")
                        raise HuggingFaceAPIError("Model returned empty content.")

                    logger.info(f"HF Response content (first 100 chars): {content[:100]}...")
                    yield content

        except httpx.TimeoutException:
            logger.error("Timeout connecting to HF API")
            raise HuggingFaceAPIError("Model is taking too long to respond.")
