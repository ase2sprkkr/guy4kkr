"""Tests for reconnecting the GUI to an already submitted persistent job."""
from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from guy4ase.gui.application.persistent_jobs import PersistentJob
from guy4ase.gui.dialogs.persistent_run_monitor import (
    PersistentRunMonitorWindow,
    _PersistentRunWorker,
)


class _Source:
    supports_attach = True

    def __init__(self, result):
        self.result = result
        self.attach_calls = []

    def attach(self, job_id, *, output_listener=None):
        self.attach_calls.append(job_id)
        output_listener("replayed\n", "out")
        result = self.result

        class Runner:
            state = SimpleNamespace(value="running")

            @staticmethod
            def wait():
                return result

            @staticmethod
            def cancel():
                return None

        return Runner()


def _job():
    return PersistentJob(
        id="0123456789abcdef0123456789abcdef",
        state="running",
        created_at="2026-10-13T08:00:00+00:00",
        updated_at="2026-10-13T08:00:00+00:00",
        task="SCF",
        directory="/tmp/calc",
        dataset="Fe-SCF",
        target="Local",
        return_code=None,
        message=None,
        result_files_state=None,
        attachable=True,
    )


def test_attached_worker_receives_replayed_output_before_wait():
    result = object()
    source = _Source(result)
    worker = _PersistentRunWorker(source, _job().id)
    output = []
    finished = []
    worker.output.connect(lambda text, kind: output.append((text, kind)))
    worker.finished.connect(finished.append)

    worker.run()

    assert source.attach_calls == [_job().id]
    assert output == [("replayed\n", "out")]
    assert finished == [result]


def test_monitor_close_detaches_without_cancelling(monkeypatch):
    app = QApplication.instance() or QApplication([])
    job = _job()
    source = _Source(object())
    monkeypatch.setattr(PersistentRunMonitorWindow, "_start", lambda self: None)

    class RunningThread:
        @staticmethod
        def isRunning():
            return True

    window = PersistentRunMonitorWindow(job, source)
    from guy4ase.gui.dialogs.run_calculation import _RunCancellation

    window._cancellation = _RunCancellation()
    window._thread = RunningThread()
    window.show()
    app.processEvents()

    window.close()
    app.processEvents()

    assert window._close_requested
    assert not window.isVisible()
    assert not window._cancellation.requested
