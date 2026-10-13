from __future__ import annotations

from threading import Event, get_ident
from types import SimpleNamespace

from guy4ase.gui.dialogs.run_calculation import _SprkkrRunWorker
from guy4ase.gui.dialogs.run_monitor import RunCancellation


def test_backend_cancel_runs_outside_requesting_thread():
    cancel_entered = Event()
    release_cancel = Event()
    cancelled = Event()
    caller_thread = get_ident()
    cancel_thread = None

    class Runner:
        def cancel(self):
            nonlocal cancel_thread
            cancel_thread = get_ident()
            cancel_entered.set()
            assert release_cancel.wait(5)
            cancelled.set()

    cancellation = RunCancellation()
    assert cancellation.register(Runner())

    cancellation.request()

    assert cancellation.requested
    assert cancel_entered.wait(5)
    assert cancel_thread != caller_thread
    assert not cancelled.is_set()

    release_cancel.set()
    assert cancelled.wait(5)


def test_launch_repeats_cancel_after_submit_if_stop_raced_with_submission():
    pre_submit_cancelled = Event()

    class Runner:
        def __init__(self):
            self.submitted = False
            self.cancel_calls = 0
            self.cancelled = False

        def submit(self):
            self.submitted = True

        def cancel(self):
            self.cancel_calls += 1
            if not self.submitted:
                pre_submit_cancelled.set()
                return
            self.cancelled = True

    class Cancellation(RunCancellation):
        def register(self, runner):
            assert super().register(runner)
            self.request()
            assert pre_submit_cancelled.wait(5)
            return True

    runner = Runner()
    cancellation = Cancellation()
    request = SimpleNamespace(
        atoms=object(),
        input_parameters=object(),
        directory=".",
        restart_scf=False,
    )
    worker = _SprkkrRunWorker(request, cancellation)
    worker._file_names = lambda: ("run.inp", "run.pot", "run.out")
    worker._create_runner = lambda _calculator, **_kwargs: runner

    assert worker._launch(object()) is runner
    assert runner.submitted
    assert runner.cancel_calls == 2
    assert runner.cancelled
