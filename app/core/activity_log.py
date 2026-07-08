"""In-memory activity log for recent app events."""
from __future__ import annotations

import datetime as dt
import itertools
from collections import deque
from typing import Any

MAX_ACTIVITY_EVENTS = 500

_events: deque[dict[str, Any]] = deque(maxlen=MAX_ACTIVITY_EVENTS)
_sequence = itertools.count(1)


def _safe_value(value: Any) -> Any:
    """Convert log values into JSON-friendly primitives."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_safe_value(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _safe_value(v) for k, v in value.items()}
    return str(value)


def record_activity(event: dict[str, Any]) -> None:
    """Store a recent structured logging event for the UI/activity endpoint."""
    item = {str(k): _safe_value(v) for k, v in event.items()}
    item["sequence"] = next(_sequence)
    item.setdefault("timestamp", dt.datetime.now(dt.UTC).isoformat())
    _events.append(item)


def list_activity(*, since: int = 0, limit: int = 100) -> list[dict[str, Any]]:
    """Return recent events newer than ``since`` sequence."""
    bounded_limit = max(1, min(limit, MAX_ACTIVITY_EVENTS))
    matching = [event for event in _events if int(event.get("sequence", 0)) > since]
    return matching[-bounded_limit:]
