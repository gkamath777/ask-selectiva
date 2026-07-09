"""Provider-aware LLM generation facade."""
import time
from dataclasses import dataclass

from app.core.config import get_settings
from app.core.logging import get_logger
from app.llm.ollama_client import generate as generate_ollama
from app.llm.openai_client import generate as generate_openai
from app.llm.router import select_model

logger = get_logger(__name__)

SUPPORTED_PROVIDERS = {"ollama", "openai"}


@dataclass(frozen=True)
class LLMGenerationResult:
    """Generated answer with the provider and model that produced it."""

    answer: str
    provider: str
    model: str
    duration_ms: float


def normalize_provider(llm_provider: str) -> str:
    """Return a supported provider name, falling back to Ollama."""
    provider = (llm_provider or "ollama").strip().lower()
    if provider not in SUPPORTED_PROVIDERS:
        logger.warning("unsupported_llm_provider", llm_provider=llm_provider)
        return "ollama"
    return provider


def select_provider_model(provider: str, question: str) -> str:
    """Select the model for the requested provider."""
    if provider == "openai":
        return get_settings().openai_model
    return select_model(question)


async def generate_answer(prompt: str, question: str, llm_provider: str) -> LLMGenerationResult:
    """Generate an answer using the selected provider."""
    provider = normalize_provider(llm_provider)
    model = select_provider_model(provider, question)
    started = time.perf_counter()

    if provider == "openai":
        answer = await generate_openai(prompt=prompt, model=model)
    else:
        answer = await generate_ollama(prompt=prompt, model=model)

    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    return LLMGenerationResult(
        answer=answer,
        provider=provider,
        model=model,
        duration_ms=duration_ms,
    )
