"""Tests for the generic run monitor and persistent attach adapter."""
from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from guy4ase.gui.application.execution_cancellation import RunCancellation
from guy4ase.gui.application.persistent_jobs import PersistentJob
from guy4ase.gui.dialogs.attached_run import AttachedRunWorker
from guy4ase.gui.dialogs.run_monitor import RunMonitorWindow


class _Source:
    supports_attach = True

    def __init__(self, result):
        self.result = result
        self.attach_calls = []

    def attach(self, job_id, *, callback=None, output_listener=None):
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
        finished_at=None,
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
    worker = AttachedRunWorker(source, _job().id, RunCancellation())
    output = []
    finished = []
    worker.output.connect(lambda text, kind: output.append((text, kind)))
    worker.finished.connect(finished.append)

    worker.run()

    assert source.attach_calls == [_job().id]
    assert output == [("replayed\n", "out")]
    assert finished == [result]


def test_generic_monitor_has_cancellation_state_before_worker_start():
    app = QApplication.instance() or QApplication([])
    window = RunMonitorWindow(lambda cancellation: object(), autostart=False)

    window._on_stop()
    app.processEvents()

    assert window.runner is None
    assert not window._stop_btn.isEnabled()


def test_generic_monitor_close_hides_without_cancelling():
    app = QApplication.instance() or QApplication([])

    class RunningThread:
        @staticmethod
        def isRunning():
            return True

    window = RunMonitorWindow(lambda cancellation: object(), autostart=False)
    window._thread = RunningThread()
    window.show()
    app.processEvents()

    window.close()
    app.processEvents()

    assert window._close_requested
    assert not window.isVisible()
    assert not window._cancellation.requested
