from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from guy4ase.gui.application.workspace_controller import CalculationRequest
from guy4ase.gui.dialogs import profiles as profiles_module
from guy4ase.gui.dialogs import run_calculation as run_module


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
    form.mpi.setText("8")
    form.host.setText("user@cluster")
    form.ssh_options.setText("-p 2222")
    form.psij_backend.setText("slurm")

    values = form.values()

    assert values["executor"] == "ssh"
    assert values["mpi"] == 8
    assert values["host"] == "user@cluster"
    assert values["ssh_options"] == ["-p", "2222"]
    assert values["psij_backend"] == "slurm"
    form.close()


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
    def __init__(self):
        self.profiles = _Profiles()
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
    dialog.form.mpi.setText("12")
    dialog.accept()

    assert config.profiles.saved == {
        "local": {"executor": "local", "mpi": 12},
    }
    assert config.saved
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
