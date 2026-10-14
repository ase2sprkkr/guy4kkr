"""Architectural and presentation checks for expert-window decomposition."""

import ast
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/guy4ase-test-matplotlib")

from ase import Atoms
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QApplication

from guy4ase.gui.widgets.calculation_setup import CalculationSetupPanel
from guy4ase.gui.widgets.structure_overview import StructureOverviewWidget

ROOT = Path(__file__).resolve().parents[1]
GUI = ROOT / "guy4ase" / "gui"


def _tree(relative_path: str) -> ast.Module:
    return ast.parse((GUI / relative_path).read_text())


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_main_window_composes_specialized_expert_widgets():
    tree = _tree("dialogs/main_window.py")
    imports = {
        alias.name
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert "StructureOverviewWidget" in imports
    assert "CalculationSetupPanel" in imports


def test_main_window_does_not_own_structure_rendering_widgets():
    tree = _tree("dialogs/main_window.py")
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    assert names.isdisjoint(
        {
            "Figure",
            "FigureCanvas",
            "QTableWidget",
            "QTableWidgetItem",
            "QPlainTextEdit",
        }
    )


def test_extracted_widgets_do_not_depend_on_dialogs_or_flows():
    for relative_path in (
        "widgets/structure_overview.py",
        "widgets/calculation_setup.py",
    ):
        tree = _tree(relative_path)
        imported_modules = {
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        assert not any(
            module.startswith(("guy4ase.gui.dialogs", "guy4ase.gui.flows"))
            for module in imported_modules
        ), relative_path


def test_structure_overview_renders_structure_snapshot():
    app = _app()
    save_action = QAction("Save")
    edit_action = QAction("Edit")
    noop = lambda: None
    widget = StructureOverviewWidget(
        save_action=save_action,
        edit_action=edit_action,
        create_structure=noop,
        create_from_database=noop,
        download_structure=noop,
        load_structure=noop,
        load_output=noop,
    )

    widget.set_structure(
        Atoms("Fe", cell=[2.0, 3.0, 4.0], pbc=True),
        scf_status="ITERATING",
    )
    app.processEvents()

    assert widget.lattice_labels["a"].text() == "2.0000 Å"
    assert widget.positions_table.rowCount() == 1
    assert "Formula: Fe" in widget.info_label.text()
    assert widget.converged_label.text() == "SCF Status: ITERATING"

    widget.clear_structure()
    assert widget.positions_table.rowCount() == 0
    widget.close()


def test_calculation_setup_panel_renders_supplied_state():
    _app()
    run_action = QAction("Run")
    noop = lambda: None
    panel = CalculationSetupPanel(
        edit_input=noop,
        load_input=noop,
        save_input=noop,
        choose_directory=noop,
        run_calculation_action=run_action,
        load_output=noop,
        value_action=lambda _value, _action: None,
    )

    class Parameters:
        def to_string(self, *, validate: bool) -> str:
            assert validate is False
            return "TASK SCF"

    panel.set_input_parameters(Parameters())
    panel.set_save_input_enabled(True)
    panel.set_directory("/tmp/run")
    panel.set_potential_path("/tmp/run/Fe.pot")

    assert panel.create_input_btn.text() == "Edit SPRKKR Input File..."
    assert panel.input_params_preview.toPlainText() == "TASK SCF"
    assert panel.save_input_btn.isEnabled()
    assert panel.directory_label.text() == "/tmp/run"
    assert panel.potential_path_label.text() == "/tmp/run/Fe.pot"
    panel.close()
