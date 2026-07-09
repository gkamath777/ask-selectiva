"""Structured logging configuration."""
import logging

import structlog

from app.core.activity_log import record_activity


def _record_activity(_: object, __: str, event_dict: dict) -> dict:
    """Mirror structured events into the in-memory activity feed."""
    record_activity(event_dict)
    return event_dict


def configure_logging(log_level: str = "INFO", log_format: str = "console") -> None:
    """Configure structlog with console output."""
    level = getattr(logging, log_level.upper(), logging.INFO)
    renderer = (
        structlog.processors.JSONRenderer()
        if log_format.lower() == "json"
        else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            _record_activity,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Get a bound logger for the given module name."""
    return structlog.get_logger(name)
