import asyncio
import logging

import pytest

from guy4ase.gui.application.workspace_controller import Generation
from guy4ase.gui.dialogs import run_calculation
from guy4ase.gui.dialogs.run_calculation import (
    _RunCancellation,
    _SprkkrRunWorker,
)


class _Runner:
    def __init__(self, wait_action=None) -> None:
        self.cancel_calls = 0
        self.wait_calls = 0
        self._wait_action = wait_action

    def cancel(self) -> None:
        self.cancel_calls += 1

    def wait(self):
        self.wait_calls += 1
        if self._wait_action is not None:
            return self._wait_action()
        return object()


def _make_worker(monkeypatch, runner, cancellation=None):
    request = run_calculation.CalculationRequest(
        atoms=object(),
        input_parameters=object(),
        directory=".",
        generation=Generation(),
    )
    worker = _SprkkrRunWorker(request, cancellation)
    monkeypatch.setattr(worker, "_launch", lambda _calculator: runner)
    return worker


def test_stop_before_runner_prevents_registration():
    cancellation = _RunCancellation()

    cancellation.request()

    assert cancellation.requested
    assert not cancellation.register(_Runner())


def test_stop_after_runner_cancels_it_once():
    cancellation = _RunCancellation()
    runner = _Runner()
    assert cancellation.register(runner)

    cancellation.request()
    cancellation.request()

    assert cancellation.requested
    assert runner.cancel_calls == 1


def test_stop_before_launch_is_cancelled_outcome(monkeypatch):
    cancellation = _RunCancellation()
    cancellation.request()
    runner = _Runner()
    worker = _make_worker(monkeypatch, runner, cancellation)
    monkeypatch.setattr(worker, "_launch", lambda _calculator: None)

    cancelled = []
    errors = []
    finished = []
    statuses = []
    worker.cancelled.connect(lambda: cancelled.append(True))
    worker.error.connect(errors.append)
    worker.finished.connect(finished.append)
    worker.status.connect(statuses.append)

    worker.run()

    assert cancelled == [True]
    assert errors == []
    assert finished == []
    assert statuses[-1] == "Cancelled"
    assert runner.wait_calls == 0


@pytest.mark.parametrize(
    "exception",
    [RuntimeError("terminated"), asyncio.CancelledError()],
)
def test_stop_during_wait_is_cancelled_outcome(monkeypatch, exception):
    cancellation = _RunCancellation()

    def stop_and_fail():
        cancellation.request()
        raise exception

    runner = _Runner(stop_and_fail)
    worker = _make_worker(monkeypatch, runner, cancellation)
    cancellation.register(runner)

    cancelled = []
    errors = []
    finished = []
    worker.cancelled.connect(lambda: cancelled.append(True))
    worker.error.connect(errors.append)
    worker.finished.connect(finished.append)

    worker.run()

    assert cancelled == [True]
    assert errors == []
    assert finished == []
    assert runner.cancel_calls == 1


def test_unexpected_worker_error_is_logged_with_traceback(monkeypatch, caplog):
    def fail():
        raise RuntimeError("worker invariant")

    runner = _Runner(fail)
    worker = _make_worker(monkeypatch, runner)

    cancelled = []
    errors = []
    worker.cancelled.connect(lambda: cancelled.append(True))
    worker.error.connect(errors.append)

    with caplog.at_level(logging.ERROR, logger=run_calculation.__name__):
        worker.run()

    assert cancelled == []
    assert errors == ["worker invariant"]
    record = next(
        record
        for record in caplog.records
        if record.getMessage() == "SPR-KKR calculation or result loading failed"
    )
    assert record.exc_info is not None
    assert record.exc_info[0] is RuntimeError
