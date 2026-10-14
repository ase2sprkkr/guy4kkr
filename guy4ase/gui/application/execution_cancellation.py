"""Thread-safe cancellation state shared by calculation execution adapters."""
from __future__ import annotations

import logging
from threading import Lock, Thread
from typing import Any, Protocol


logger = logging.getLogger(__name__)


class Cancellation(Protocol):
    """Cancellation state required by backend execution services."""

    @property
    def requested(self) -> bool: ...

    def register(self, runner: Any) -> bool: ...


class RunCancellation:
    """Bridge a cancellation request to a runner that may not exist yet."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._requested = False
        self._runner: Any | None = None

    @property
    def requested(self) -> bool:
        with self._lock:
            return self._requested

    @property
    def runner(self) -> Any | None:
        with self._lock:
            return self._runner

    def register(self, runner: Any) -> bool:
        """Register the runner unless cancellation was already requested."""
        with self._lock:
            if self._requested:
                return False
            self._runner = runner
            return True

    @staticmethod
    def _cancel_runner(runner: Any) -> None:
        try:
            runner.cancel()
        except Exception:  # noqa: BLE001 - backend cancellation boundary
            logger.exception("Failed to cancel calculation")

    def request(self) -> None:
        """Latch cancellation and cancel an already-registered runner off-thread."""
        with self._lock:
            if self._requested:
                return
            self._requested = True
            runner = self._runner

        if runner is not None:
            Thread(
                target=self._cancel_runner,
                args=(runner,),
                name="run-cancel",
                daemon=True,
            ).start()
