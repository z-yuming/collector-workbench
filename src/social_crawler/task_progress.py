"""Workers report real phases/pages; callers outside a managed task remain unchanged."""
from contextvars import ContextVar

callback = ContextVar("task_progress", default=None)


def report(stage: str, current: int | None = None, total: int | None = None, counts: dict | None = None):
    handler = callback.get()
    if handler:
        handler(stage, current, total, counts)
