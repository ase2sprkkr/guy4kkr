import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/guy4ase-test-matplotlib")

from ase import Atoms
from PyQt6.QtWidgets import QApplication, QLabel

from ase2sprkkr.input_parameters.input_parameters import InputParameters

from guy4ase.gui.parameter_tooltips import parameter_tooltip
from guy4ase.gui.scf_parameters_dialog import GuidedScfParametersDialog
from guy4ase.gui.task_parameters_dialog import GuidedTaskParametersDialog


def _label_with_tooltip(dialog, parameter_name):
    return next(
        label
        for label in dialog.findChildren(QLabel)
        if parameter_name in label.toolTip()
    )


def test_scf_fields_show_real_name_and_ase2sprkkr_help():
    application = QApplication.instance() or QApplication([])
    params = InputParameters.create("scf")
    atoms = Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True)
    dialog = GuidedScfParametersDialog(params, atoms)

    for (section, option), editor in dialog._rows:
        parameter_name = f"{section}.{option}"
        assert parameter_name in editor.toolTip()
        assert parameter_name in _label_with_tooltip(
            dialog,
            parameter_name,
        ).toolTip()
    assert "SPR-KKR parameter: SCF.NITER" in dialog._niter.toolTip()
    assert "Maximal number of iterations of the SCF cycle" in dialog._niter.toolTip()

    dialog.close()
    application.processEvents()


def test_all_task_fields_show_real_parameter_name_on_editor_and_label():
    application = QApplication.instance() or QApplication([])

    for task in ("dos", "xas", "arpes", "bsf", "jxc"):
        parameter_task = "bsfek" if task == "bsf" else task
        dialog = GuidedTaskParametersDialog(
            task,
            InputParameters.create(parameter_task),
        )
        for section, option, editor in dialog._editors:
            parameter_name = f"{section}.{option}"
            assert parameter_name in editor.toolTip()
            assert parameter_name in _label_with_tooltip(
                dialog,
                parameter_name,
            ).toolTip()
        dialog.close()

    application.processEvents()


def test_generic_help_is_not_mistaken_for_parameter_documentation():
    params = InputParameters.create("dos")

    tooltip = parameter_tooltip(
        params.ENERGY.ImE,
        "ENERGY",
        "ImE",
        "Imaginary broadening (Ry):",
    )

    assert tooltip == "SPR-KKR parameter: ENERGY.ImE"


def test_bsf_path_controls_share_kpath_tooltip():
    application = QApplication.instance() or QApplication([])
    dialog = GuidedTaskParametersDialog(
        "bsf",
        InputParameters.create("bsfek"),
    )

    assert "TASK.KPATH" in dialog._predefined_path.toolTip()
    assert "Predefined path in k-space" in dialog._predefined_path.toolTip()
    assert "TASK.KPATH" in dialog._path_label.toolTip()

    dialog.close()
    application.processEvents()
