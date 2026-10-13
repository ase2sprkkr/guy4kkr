from __future__ import annotations

import os
import warnings
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from guy4ase.gui.application.workspace_controller import CalculationRequest
from guy4ase.gui.dialogs import profiles as profiles_module
from guy4ase.gui.dialogs import run_calculation as run_module
from guy4ase.gui.dialogs.run_monitor import RunCancellation


def _app():
    return QApplication.instance() or QApplication([])


def test_profile_description_explains_backend_and_mpi(monkeypatch):
    profile = SimpleNamespace(
        executor="ssh",
        host="cluster.example",
        psij_backend="slurm",
        psij_url=None,
        mpi=8,
        executable_dir="/opt/sprkkr",
        executable_suffix="_v8",
    )
    monkeypatch.setattr(profiles_module, "_runtime_profile", lambda name: profile)

    text = profiles_module.profile_description("cluster")

    assert "SSH to cluster.example + PSI/J (slurm)" in text
    assert "MPI: 8 processes" in text
    assert "/opt/sprkkr" in text
    assert "_v8" in text


def test_profile_form_changes_fields_with_execution_type():
    _application = _app()
    form = profiles_module._ProfileForm()

    form.kind.setCurrentIndex(form.kind.findData("local"))
    assert form.host.isHidden()
    assert form.psij_backend.isHidden()

    form.kind.setCurrentIndex(form.kind.findData("ssh"))
    assert not form.host.isHidden()
    assert form.psij_backend.isHidden()

    form.kind.setCurrentIndex(form.kind.findData("ssh-psij"))
    assert not form.host.isHidden()
    assert not form.psij_backend.isHidden()
    form.close()


def test_profile_form_parses_mpi_and_backend_specific_values():
    _application = _app()
    form = profiles_module._ProfileForm()
    form.kind.setCurrentIndex(form.kind.findData("ssh-psij"))
    form.mpi.set_value(8)
    form.host.setText("user@cluster")
    form.ssh_options.setText("-p 2222")
    form.psij_backend.setText("slurm")

    values = form.values()

    assert values["executor"] == "ssh"
    assert values["mpi"] == 8
    assert values["mpi_warning"] is True
    assert values["host"] == "user@cluster"
    assert values["ssh_options"] == ["-p", "2222"]
    assert values["psij_backend"] == "slurm"
    form.close()


class _Option:
    def __init__(self, value=None):
        self.value = value

    def __call__(self):
        return self.value

    def set(self, value):
        self.value = value


class _Profile:
    def __init__(self, values, *, read_only=False):
        self._values = dict(values)
        self.read_only = read_only

    def as_dict(self, *args, **kwargs):
        return dict(self._values)


class _Profiles:
    def __init__(self):
        self.values = {
            "ase": _Profile({"command": "/opt/sprkkr/kkrscf"}, read_only=True),
            "local": _Profile({"executor": "local", "mpi": 4}),
        }
        self.saved = None

    def items(self):
        return self.values.items()

    def set(self, values):
        self.saved = values


class _Config:
    def __init__(self, *, default_profile=None):
        self.profiles = _Profiles()
        self.default_profile = _Option(default_profile)
        self.saved = False

    def save_user_preferences(self):
        self.saved = True


def test_profile_editor_saves_only_mutable_profiles(monkeypatch):
    _application = _app()
    config = _Config()
    monkeypatch.setattr(profiles_module, "config", config)
    dialog = profiles_module.ProfilesDialog()

    for row in range(dialog.list.count()):
        item = dialog.list.item(row)
        if item.data(profiles_module.Qt.ItemDataRole.UserRole) == "local":
            dialog.list.setCurrentRow(row)
            break
    dialog.form.mpi.set_value(12)
    dialog.accept()

    assert config.profiles.saved == {
        "local": {"executor": "local", "mpi": 12, "mpi_warning": True},
    }
    assert config.default_profile() is None
    assert config.saved
    dialog.close()


def test_profile_editor_clears_default_when_that_profile_is_deleted(monkeypatch):
    _application = _app()
    config = _Config(default_profile="local")
    monkeypatch.setattr(profiles_module, "config", config)
    dialog = profiles_module.ProfilesDialog()

    del dialog._drafts["local"]
    dialog.accept()

    assert config.profiles.saved == {}
    assert config.default_profile() is None
    assert config.saved
    dialog.close()


def test_read_only_profile_cannot_be_deleted_or_edited(monkeypatch):
    _application = _app()
    config = _Config(default_profile="ase")
    monkeypatch.setattr(profiles_module, "config", config)
    dialog = profiles_module.ProfilesDialog()

    for row in range(dialog.list.count()):
        item = dialog.list.item(row)
        if item.data(profiles_module.Qt.ItemDataRole.UserRole) == "ase":
            dialog.list.setCurrentRow(row)
            break

    assert not dialog.delete_button.isEnabled()
    assert not dialog.form.form_widget.isEnabled()
    dialog.close()


def test_worker_constructs_sprkkr_with_selected_profile(monkeypatch, tmp_path):
    captured = {}
    backend_result = object()
    loaded_result = object()
    request = CalculationRequest(
        atoms=object(),
        input_parameters=object(),
        directory=str(tmp_path),
        generation=object(),
    )

    class Calculator:
        pass

    def make_calculator(*, profile):
        captured["profile"] = profile
        return Calculator()

    class Runner:
        reference = None

        def wait(self):
            return backend_result

    worker = run_module._SprkkrRunWorker(request, profile_name="cluster")
    monkeypatch.setattr(run_module, "SPRKKR", make_calculator)
    monkeypatch.setattr(worker, "_launch", lambda calculator: Runner())
    monkeypatch.setattr(
        run_module,
        "load_result",
        lambda result, *, fallback_directory: loaded_result,
    )
    finished = []
    worker.finished.connect(finished.append)

    worker.run()

    assert captured == {"profile": "cluster"}
    assert finished == [loaded_result]


def test_worker_launches_persistent_run(monkeypatch, tmp_path):
    request = CalculationRequest(
        atoms=object(),
        input_parameters=object(),
        directory=str(tmp_path),
        generation=object(),
    )
    worker = run_module._SprkkrRunWorker(request)
    captured = {}

    class Runner:
        reference = None

        def submit(self):
            return None

        def cancel(self):
            return None

    runner = Runner()

    def create_runner(_calculator, **kwargs):
        captured.update(kwargs)
        return runner

    monkeypatch.setattr(worker, "_create_runner", create_runner)

    assert worker._launch(object()) is runner
    assert captured["persistent"] is True


def test_worker_forwards_specific_mpi_warning():
    request = CalculationRequest(
        atoms=object(),
        input_parameters=object(),
        directory=".",
        generation=object(),
    )
    worker = run_module._SprkkrRunWorker(request)
    runner = object()

    class Calculator:
        def create_run(self, **_kwargs):
            warnings.warn("No MPI runner", run_module.MpiNotFoundWarning)
            return runner

    seen = []
    worker.warning.connect(seen.append)

    assert worker._create_runner(Calculator()) is runner
    assert seen == ["No MPI runner"]


def test_run_window_shows_mpi_warning_message_box(monkeypatch, tmp_path):
    _application = _app()
    request = CalculationRequest(
        atoms=object(),
        input_parameters=object(),
        directory=str(tmp_path),
        generation=object(),
    )
    monkeypatch.setattr(run_module.SprkkrRunWindow, "_start_worker", lambda self: None)
    shown = []
    monkeypatch.setattr(
        run_module.QMessageBox,
        "warning",
        lambda parent, title, message: shown.append((parent, title, message)),
    )

    window = run_module.SprkkrRunWindow(request)
    window._on_warning("MPI autodetection failed")

    assert shown == [(window, "MPI Not Detected", "MPI autodetection failed")]
    window.close()


def test_run_window_close_hides_without_cancelling_running_job(monkeypatch, tmp_path):
    app = _app()
    request = CalculationRequest(
        atoms=object(),
        input_parameters=object(),
        directory=str(tmp_path),
        generation=object(),
    )
    monkeypatch.setattr(run_module.SprkkrRunWindow, "_start_worker", lambda self: None)

    class RunningThread:
        @staticmethod
        def isRunning():
            return True

    window = run_module.SprkkrRunWindow(request)
    window._cancellation = RunCancellation()
    window._thread = RunningThread()
    window.show()
    app.processEvents()

    window.close()
    app.processEvents()

    assert window._close_requested
    assert not window.isVisible()
    assert not window._cancellation.requested

    window._thread = None
    window.close()


def test_run_window_refreshes_state_without_gui_thread_io(monkeypatch, tmp_path):
    _application = _app()
    request = CalculationRequest(
        atoms=object(),
        input_parameters=object(),
        directory=str(tmp_path),
        generation=object(),
    )
    monkeypatch.setattr(run_module.SprkkrRunWindow, "_start_worker", lambda self: None)

    window = run_module.SprkkrRunWindow(request)
    window._cancellation = RunCancellation()
    runner = SimpleNamespace(state=SimpleNamespace(value="queued"))
    assert window._cancellation.register(runner)

    class InlineThread:
        def __init__(self, *, target, **_kwargs):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(run_module, "Thread", InlineThread)
    window._on_refresh()

    assert window._status.text() == "Queued"
    window.close()
