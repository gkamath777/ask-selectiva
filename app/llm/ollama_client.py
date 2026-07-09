"""Ollama REST client for local LLM."""
import json
import time
from typing import Any, AsyncGenerator

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def _parse_ollama_response_body(data: dict[str, Any]) -> str:
    """Parse native /api/chat, /api/generate, or OpenAI-compat /v1/chat/completions JSON."""
    msg = data.get("message")
    if isinstance(msg, dict) and msg.get("content") is not None:
        return str(msg["content"]).strip()
    if data.get("response") is not None:
        return str(data["response"]).strip()
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        m = choices[0].get("message") if isinstance(choices[0], dict) else None
        if isinstance(m, dict) and m.get("content") is not None:
            return str(m["content"]).strip()
    return ""


async def generate(
    prompt: str,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    stream: bool = False,
) -> str | AsyncGenerator[str, None]:
    """
    Call Ollama: tries /api/chat, then /api/generate, then OpenAI-compatible /v1/chat/completions.
    """
    settings = get_settings()
    base_url = settings.ollama_base_url.rstrip("/")
    model_name = model or settings.ollama_model
    temp = temperature if temperature is not None else settings.ollama_temperature
    n_predict = max_tokens if max_tokens is not None else settings.ollama_max_tokens
    options = {
        "temperature": temp,
        "num_predict": n_predict,
    }

    chat_url = f"{base_url}/api/chat"
    chat_payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": prompt}],
        "stream": stream,
        "options": options,
    }
    generate_url = f"{base_url}/api/generate"
    generate_payload = {
        "model": model_name,
        "prompt": prompt,
        "stream": stream,
        "options": options,
    }
    openai_url = f"{base_url}/v1/chat/completions"
    openai_payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temp,
        "max_tokens": n_predict,
        "stream": stream,
    }

    read_s = float(settings.ollama_request_timeout_seconds)
    timeout = httpx.Timeout(connect=30.0, read=read_s, write=60.0, pool=10.0)

    async with httpx.AsyncClient(timeout=timeout) as client:
        if stream:
            return _stream_chat(
                client,
                chat_url,
                chat_payload,
                generate_url,
                generate_payload,
            )

        started = time.perf_counter()
        logger.info(
            "ollama_generate_started",
            model=model_name,
            prompt_chars=len(prompt),
            temperature=temp,
            max_tokens=n_predict,
            timeout_seconds=read_s,
        )
        endpoint = "/api/chat"
        try:
            response = await client.post(chat_url, json=chat_payload)
        except httpx.TimeoutException as e:
            logger.warning(
                "ollama_generate_timeout",
                model=model_name,
                endpoint=endpoint,
                error=str(e),
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
            raise
        except httpx.HTTPError as e:
            logger.warning(
                "ollama_generate_http_error",
                model=model_name,
                endpoint=endpoint,
                error=str(e),
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
            raise
        if response.status_code == 404:
            logger.info("ollama_trying_generate", model=model_name)
            endpoint = "/api/generate"
            try:
                response = await client.post(generate_url, json=generate_payload)
            except httpx.TimeoutException as e:
                logger.warning(
                    "ollama_generate_timeout",
                    model=model_name,
                    endpoint=endpoint,
                    error=str(e),
                    duration_ms=round((time.perf_counter() - started) * 1000, 2),
                )
                raise
            except httpx.HTTPError as e:
                logger.warning(
                    "ollama_generate_http_error",
                    model=model_name,
                    endpoint=endpoint,
                    error=str(e),
                    duration_ms=round((time.perf_counter() - started) * 1000, 2),
                )
                raise
        if response.status_code == 404:
            logger.info("ollama_trying_openai_compat", model=model_name, url=openai_url)
            endpoint = "/v1/chat/completions"
            try:
                response = await client.post(openai_url, json=openai_payload)
            except httpx.TimeoutException as e:
                logger.warning(
                    "ollama_generate_timeout",
                    model=model_name,
                    endpoint=endpoint,
                    error=str(e),
                    duration_ms=round((time.perf_counter() - started) * 1000, 2),
                )
                raise
            except httpx.HTTPError as e:
                logger.warning(
                    "ollama_generate_http_error",
                    model=model_name,
                    endpoint=endpoint,
                    error=str(e),
                    duration_ms=round((time.perf_counter() - started) * 1000, 2),
                )
                raise

        if response.status_code == 404:
            raise RuntimeError(
                f"No LLM API at {base_url}: /api/chat, /api/generate, and /v1/chat/completions "
                f"all returned 404. That usually means Ollama is not listening here (wrong port, "
                f"or another app is using 11434). Run `ollama serve` on the host, then from your machine: "
                f"`curl {base_url}/api/tags`. If that fails, fix OLLAMA_BASE_URL."
            )

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.warning(
                "ollama_generate_bad_status",
                model=model_name,
                endpoint=endpoint,
                status_code=response.status_code,
                response_chars=len(response.text or ""),
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
            raise
        data = response.json()
        text = _parse_ollama_response_body(data)
        if not text:
            logger.warning("ollama_empty_reply", model=model_name, keys=list(data.keys())[:10])
        logger.info(
            "ollama_generate_complete",
            model=model_name,
            endpoint=endpoint,
            status_code=response.status_code,
            response_chars=len(text),
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        return text


async def _stream_chat(
    client: httpx.AsyncClient,
    chat_url: str,
    chat_payload: dict,
    generate_url: str,
    generate_payload: dict,
) -> AsyncGenerator[str, None]:
    """Stream response; fall back from /api/chat to /api/generate on 404."""
    chat_payload = {**chat_payload, "stream": True}
    generate_payload = {**generate_payload, "stream": True}

    async with client.stream("POST", chat_url, json=chat_payload) as resp:
        if resp.status_code == 404:
            await resp.aclose()
        else:
            resp.raise_for_status()
            async for chunk in _iter_stream_lines(resp, use_message_key=True):
                yield chunk
            return

    async with client.stream("POST", generate_url, json=generate_payload) as resp:
        resp.raise_for_status()
        async for chunk in _iter_stream_lines(resp, use_message_key=False):
            yield chunk


async def _iter_stream_lines(
    resp: httpx.Response,
    *,
    use_message_key: bool,
) -> AsyncGenerator[str, None]:
    async for line in resp.aiter_lines():
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if use_message_key:
            msg = data.get("message", {})
            if isinstance(msg, dict) and "content" in msg:
                yield msg["content"]
        else:
            if data.get("response"):
                yield data["response"]
        if data.get("done"):
            break
