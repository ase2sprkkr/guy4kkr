from guy4ase.gui.dialogs.run_calculation import _RunCancellation


class _Process:
    def __init__(self) -> None:
        self.stop_calls = 0

    def stop_the_process(self) -> None:
        self.stop_calls += 1


def test_stop_before_process_prevents_start():
    cancellation = _RunCancellation()

    cancellation.request()

    assert not cancellation.register(_Process())


def test_stop_after_process_stops_it_once():
    cancellation = _RunCancellation()
    process = _Process()
    assert cancellation.register(process)

    cancellation.request()
    cancellation.request()

    assert process.stop_calls == 1
