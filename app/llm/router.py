"""Model router: select LLM based on question."""
from app.core.config import get_settings

ESCALATION_TRIGGERS = ["compare", "architecture", "design", "analysis"]
ESCALATION_QUESTION_LENGTH = 400


def select_model(question: str) -> str:
    """
    Select model based on question.
    Escalation to ollama_escalation_model if:
    - question length > 400 chars, OR
    - contains compare, architecture, design, analysis
    """
    settings = get_settings()
    q_lower = question.lower().strip()

    if len(question) > ESCALATION_QUESTION_LENGTH:
        return settings.ollama_escalation_model

    for trigger in ESCALATION_TRIGGERS:
        if trigger in q_lower:
            return settings.ollama_escalation_model

    return settings.ollama_model
