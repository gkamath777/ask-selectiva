"""OpenAI Responses API client."""
import time
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def _parse_response_text(data: dict[str, Any]) -> str:
    """Extract text from Responses API JSON."""
    if data.get("output_text") is not None:
        return str(data["output_text"]).strip()

    parts = []
    for item in data.get("output", []) or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []) or []:
            if not isinstance(content, dict):
                continue
            if content.get("text") is not None:
                parts.append(str(content["text"]))
    return "\n".join(parts).strip()


async def generate(
    prompt: str,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> str:
    """Generate text with OpenAI's Responses API."""
    settings = get_settings()
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is required when llm_provider=openai")

    base_url = settings.openai_base_url.rstrip("/")
    model_name = model or settings.openai_model
    temp = temperature if temperature is not None else settings.openai_temperature
    max_output_tokens = max_tokens if max_tokens is not None else settings.openai_max_output_tokens
    timeout_s = float(settings.openai_request_timeout_seconds)
    url = f"{base_url}/responses"
    payload = {
        "model": model_name,
        "input": prompt,
        "temperature": temp,
        "max_output_tokens": max_output_tokens,
    }
    headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }

    started = time.perf_counter()
    logger.info(
        "openai_generate_started",
        model=model_name,
        prompt_chars=len(prompt),
        temperature=temp,
        max_output_tokens=max_output_tokens,
        timeout_seconds=timeout_s,
    )

    timeout = httpx.Timeout(connect=30.0, read=timeout_s, write=60.0, pool=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
        except httpx.TimeoutException as e:
            logger.warning(
                "openai_generate_timeout",
                model=model_name,
                error=str(e),
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
            raise
        except httpx.HTTPStatusError as e:
            logger.warning(
                "openai_generate_bad_status",
                model=model_name,
                status_code=e.response.status_code,
                response_chars=len(e.response.text or ""),
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
            raise
        except httpx.HTTPError as e:
            logger.warning(
                "openai_generate_http_error",
                model=model_name,
                error=str(e),
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
            raise

    data = response.json()
    text = _parse_response_text(data)
    if not text:
        logger.warning("openai_empty_reply", model=model_name, keys=list(data.keys())[:10])
    logger.info(
        "openai_generate_complete",
        model=model_name,
        status_code=response.status_code,
        response_chars=len(text),
        duration_ms=round((time.perf_counter() - started) * 1000, 2),
    )
    return text
