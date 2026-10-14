from guy4ase.gui.application.recent_presentation import recent_launch


class RecentHistory:
    def __init__(self, *, structures=(), outputs=(), last_kind=None):
        self._paths = {
            "structure": tuple(structures),
            "output": tuple(outputs),
        }
        self.last_kind = last_kind

    def paths(self, kind):
        return self._paths[kind]


def test_recent_launch_is_none_without_launchable_files():
    assert recent_launch(RecentHistory()) is None


def test_recent_launch_uses_last_kind_when_available():
    launch = recent_launch(
        RecentHistory(
            structures=("structure.cif",),
            outputs=("calculation.out",),
            last_kind="structure",
        )
    )

    assert launch is not None
    assert launch.kind == "structure"
    assert launch.path == "structure.cif"
    assert launch.title == "Continue: structure.cif"


def test_recent_launch_falls_back_to_output():
    launch = recent_launch(
        RecentHistory(
            structures=("structure.cif",),
            outputs=("calculation.out",),
            last_kind=None,
        )
    )

    assert launch is not None
    assert launch.kind == "output"
    assert launch.path == "calculation.out"


def test_recent_launch_falls_back_when_last_kind_is_empty():
    launch = recent_launch(
        RecentHistory(
            structures=("structure.cif",),
            last_kind="output",
        )
    )

    assert launch is not None
    assert launch.kind == "structure"
    assert launch.path == "structure.cif"
