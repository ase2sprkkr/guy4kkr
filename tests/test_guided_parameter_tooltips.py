import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/guy4ase-test-matplotlib")

from ase import Atoms
from PyQt6.QtWidgets import QApplication

from ase2sprkkr.input_parameters.input_parameters import InputParameters

from guy4ase.gui.dialogs.guided_input import GuidedInputParametersDialog
from guy4ase.gui.input_parameters.tooltips import parameter_tooltip


def _dialog(task):
    parameter_task = task
    atoms = Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True)
    return GuidedInputParametersDialog(
        task,
        InputParameters.create(parameter_task),
        atoms=atoms,
    )


def test_scf_fields_show_real_name_and_ase2sprkkr_help():
    application = QApplication.instance() or QApplication([])
    dialog = _dialog("scf")

    for editor in dialog._editors:
        parameter_name = ".".join(editor.path)
        assert parameter_name in editor.toolTip()
        assert parameter_name in dialog._labels_by_path[editor.path][0].toolTip()

    niter = dialog.editors_for(("SCF", "NITER"))[0]
    assert "SPR-KKR parameter: SCF.NITER" in niter.toolTip()
    assert "Maximal number of iterations of the SCF cycle" in niter.toolTip()

    dialog.close()
    application.processEvents()


def test_all_task_fields_show_real_parameter_name_on_editor_and_label():
    application = QApplication.instance() or QApplication([])

    for task in ("dos", "xas", "arpes", "bsf", "jxc"):
        dialog = _dialog(task)
        for editor in dialog._editors:
            parameter_name = ".".join(editor.path)
            assert parameter_name in editor.toolTip()
            assert any(
                parameter_name in label.toolTip()
                for label in dialog._labels_by_path[editor.path]
            )
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
    dialog = _dialog("bsf")

    for editor in dialog.editors_for(("TASK", "KPATH")):
        assert "TASK.KPATH" in editor.path_combo.toolTip()
        assert "Predefined path in k-space" in editor.path_combo.toolTip()
        assert "TASK.KPATH" in editor.path_summary.toolTip()

    dialog.close()
    application.processEvents()
