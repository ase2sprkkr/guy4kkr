"""Regression tests for explicit worker-to-GUI thread boundaries."""
from __future__ import annotations

from threading import get_ident
from time import monotonic

from ase import Atoms
from PyQt6.QtWidgets import QApplication, QWidget

from guy4ase.gui.application.workspace_controller import CalculationRequest
from guy4ase.gui.dialogs import run_calculation as run_dialog
from guy4ase.gui.misc import modal_task


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_modal_task_completion_updates_dialog_in_gui_thread(monkeypatch):
    _application()
    parent = QWidget()
    gui_thread = get_ident()
    operation_threads = []
    finish_threads = []

    original_finish = modal_task._ModalTaskDialog.finish_successfully

    def finish_successfully(dialog):
        finish_threads.append(get_ident())
        original_finish(dialog)

    monkeypatch.setattr(
        modal_task._ModalTaskDialog,
        "finish_successfully",
        finish_successfully,
    )

    def operation():
        operation_threads.append(get_ident())
        return 42

    try:
        assert modal_task.run_modal_task(parent, operation) == 42
        assert operation_threads and operation_threads[0] != gui_thread
        assert finish_threads == [gui_thread]
    finally:
        parent.close()


def test_run_activity_callback_is_forwarded_in_gui_thread(monkeypatch, tmp_path):
    app = _application()
    parent = QWidget()
    gui_thread = get_ident()
    callback_threads = []

    class Process:
        def run(self):
            return object()

    class Calculator:
        def calculate(self, **_kwargs):
            return Process()

    monkeypatch.setattr(run_dialog, "SPRKKR", Calculator)
    monkeypatch.setattr(run_dialog, "load_result", lambda *_args, **_kwargs: object())

    request = CalculationRequest(
        atoms=Atoms("Fe"),
        input_parameters=object(),
        directory=str(tmp_path),
        generation=0,
    )
    window = run_dialog.SprkkrRunWindow(
        request=request,
        parent=parent,
        on_activity_ended=lambda _run_id: callback_threads.append(get_ident()),
    )

    deadline = monotonic() + 5
    try:
        while not callback_threads and monotonic() < deadline:
            app.processEvents()
        assert callback_threads == [gui_thread]
    finally:
        if window._thread is not None:
            window._thread.quit()
            window._thread.wait(5000)
        window.close()
        parent.close()
