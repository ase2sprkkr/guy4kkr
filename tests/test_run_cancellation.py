import asyncio
import logging

import pytest

from guy4ase.gui.dialogs import run_calculation
from guy4ase.gui.dialogs.run_calculation import (
    _RunCancellation,
    _SprkkrRunWorker,
)


class _Process:
    def __init__(self, run_action=None) -> None:
        self.stop_calls = 0
        self.run_calls = 0
        self._run_action = run_action

    def stop_the_process(self) -> None:
        self.stop_calls += 1

    def run(self):
        self.run_calls += 1
        if self._run_action is not None:
            return self._run_action()
        return object()


class _Calculator:
    def __init__(self, process) -> None:
        self._process = process

    def calculate(self, **_kwargs):
        return self._process


def _make_worker(monkeypatch, process, cancellation=None):
    monkeypatch.setattr(
        run_calculation, "SPRKKR", lambda: _Calculator(process)
    )
    request = run_calculation.CalculationRequest(
        atoms=object(),
        input_parameters=object(),
        directory=".",
        generation=0,
    )
    return _SprkkrRunWorker(request, cancellation)


def test_stop_before_process_prevents_start():
    cancellation = _RunCancellation()

    cancellation.request()

    assert cancellation.requested
    assert not cancellation.register(_Process())


def test_stop_after_process_stops_it_once():
    cancellation = _RunCancellation()
    process = _Process()
    assert cancellation.register(process)

    cancellation.request()
    cancellation.request()

    assert cancellation.requested
    assert process.stop_calls == 1


def test_stop_before_process_is_cancelled_outcome(monkeypatch):
    cancellation = _RunCancellation()
    cancellation.request()
    process = _Process()
    worker = _make_worker(monkeypatch, process, cancellation)

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
    assert process.run_calls == 0


@pytest.mark.parametrize(
    "exception",
    [RuntimeError("terminated"), asyncio.CancelledError()],
)
def test_stop_during_run_is_cancelled_outcome(
    monkeypatch, exception
):
    cancellation = _RunCancellation()

    def stop_and_fail():
        cancellation.request()
        raise exception

    process = _Process(stop_and_fail)
    worker = _make_worker(monkeypatch, process, cancellation)

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
    assert process.stop_calls == 1


def test_unexpected_worker_error_is_logged_with_traceback(
    monkeypatch, caplog
):
    def fail():
        raise RuntimeError("worker invariant")

    process = _Process(fail)
    worker = _make_worker(monkeypatch, process)

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
        if record.getMessage() == "SPR-KKR calculation failed"
    )
    assert record.exc_info is not None
    assert record.exc_info[0] is RuntimeError
