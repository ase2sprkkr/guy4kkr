from __future__ import annotations

from threading import Event, get_ident

from guy4ase.gui.dialogs.run_calculation import _RunCancellation


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

    cancellation = _RunCancellation()
    assert cancellation.register(Runner())

    cancellation.request()

    assert cancellation.requested
    assert cancel_entered.wait(5)
    assert cancel_thread != caller_thread
    assert not cancelled.is_set()

    release_cancel.set()
    assert cancelled.wait(5)
