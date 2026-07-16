from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any


class TaskRegistry:
    """Own background tasks so duplicates, failures, and shutdown are controlled."""

    def __init__(self, *, logger: logging.Logger) -> None:
        self._logger = logger
        self._tasks: dict[str, asyncio.Task[Any]] = {}

    def start(self, key: str, coroutine: Coroutine[Any, Any, Any]) -> bool:
        existing = self._tasks.get(key)
        if existing is not None and not existing.done():
            coroutine.close()
            return False

        task = asyncio.create_task(coroutine, name=key)
        self._tasks[key] = task
        task.add_done_callback(lambda completed: self._on_done(key, completed))
        return True

    async def shutdown(self) -> None:
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()

    def _on_done(self, key: str, task: asyncio.Task[Any]) -> None:
        if self._tasks.get(key) is task:
            self._tasks.pop(key, None)
        if task.cancelled():
            return
        try:
            exception = task.exception()
        except asyncio.CancelledError:
            return
        if exception is not None:
            self._logger.error(
                "Background task %s failed",
                key,
                exc_info=(type(exception), exception, exception.__traceback__),
            )
