"""Regression tests for explicit worker-to-GUI thread boundaries."""
from __future__ import annotations

from threading import get_ident
from time import monotonic
from types import SimpleNamespace

from ase import Atoms
from ase2sprkkr.execution import RunConflictError, RunTarget
from PyQt6.QtWidgets import QApplication, QWidget

from guy4ase.gui.application.workspace_controller import CalculationRequest, Generation
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


def test_run_conflict_prompt_is_forwarded_in_gui_thread(monkeypatch, tmp_path):
    app = _application()
    parent = QWidget()
    gui_thread = get_ident()
    prompt_threads = []
    target = RunTarget("local", (str(tmp_path / "Fe_SCF.out"),))
    conflict = RunConflictError(
        target,
        (SimpleNamespace(target=target),),
    )

    def launch(worker, _calculator):
        decision = run_dialog._ConflictDecision()
        worker.conflict.emit(conflict, decision)
        assert not decision.wait(worker._cancellation)
        return None

    monkeypatch.setattr(run_dialog._SprkkrRunWorker, "_launch", launch)

    def confirm(_parent, error):
        assert error is conflict
        prompt_threads.append(get_ident())
        return False

    monkeypatch.setattr(run_dialog, "_confirm_run_conflict", confirm)

    request = CalculationRequest(
        atoms=Atoms("Fe"),
        input_parameters=object(),
        directory=str(tmp_path),
        generation=Generation(),
    )
    window = run_dialog.SprkkrRunWindow(
        request=request,
        parent=parent,
    )

    deadline = monotonic() + 5
    try:
        while (
            window._thread is not None
            and window._thread.isRunning()
            and monotonic() < deadline
        ):
            app.processEvents()
        app.processEvents()
        assert prompt_threads == [gui_thread]
    finally:
        if window._thread is not None:
            window._thread.quit()
            window._thread.wait(5000)
        window.close()
        parent.close()
