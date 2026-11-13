"""Stable architectural and component-contract checks for the GUI."""
import ast
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/guy4ase-test-matplotlib")

import numpy as np
import pytest
from ase import Atoms
from ase2sprkkr.common.grammar_types import Energy, Real
from ase2sprkkr.input_parameters.input_parameters import InputParameters
from PyQt6.QtWidgets import QApplication

from guy4ase.ase.element_assignment import ElementAssignmentDraft
from guy4ase.gui.input_parameters.field_binding import (
    IndexedFieldBinding,
    SessionFieldBinding,
)
from guy4ase.gui.input_parameters.session import InputParametersSession
from guy4ase.gui.input_parameters.specs.schema import field
from guy4ase.gui.misc.resources import icon_path
from guy4ase.gui.widgets.input_parameters.energy import EnergyEditor
from guy4ase.gui.widgets.input_parameters.kpath import VectorEditor
from guy4ase.gui.widgets.input_parameters.registry import EDITORS, editor_for_type
from guy4ase.gui.widgets.input_parameters.scalar import (
    BooleanEditor,
    ChoiceEditor,
    IntegerEditor,
    RealEditor,
    TextEditor,
)
from guy4ase.gui.widgets.input_parameters.value_editor import ParameterValueEditor
from guy4ase.gui.widgets.structures.element_assignment import QLetterRow

ROOT = Path(__file__).resolve().parents[1]
GUI = ROOT / "guy4ase" / "gui"


def _gui_graph():
    """Return the static import graph between modules inside ``guy4ase.gui``."""
    modules = {}
    for path in GUI.rglob("*.py"):
        module = ".".join(path.relative_to(ROOT).with_suffix("").parts)
        package = path.name == "__init__.py"
        if package:
            module = module.removesuffix(".__init__")
        modules[module] = (path, package)

    graph = {module: set() for module in modules}
    for module, (path, package) in modules.items():
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                targets = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    base = importlib.util.resolve_name(
                        "." * node.level + base,
                        module if package else module.rpartition(".")[0],
                    )
                targets = [base] + [
                    base + "." + alias.name for alias in node.names
                ]
            else:
                continue
            graph[module].update(target for target in targets if target in modules)
    return graph


def test_gui_dependencies_are_acyclic_and_follow_layers():
    """Keep broad layer boundaries without pinning individual implementations."""
    graph = _gui_graph()
    for module, targets in graph.items():
        if module.startswith("guy4ase.gui.widgets"):
            assert not any(
                target.startswith(("guy4ase.gui.dialogs", "guy4ase.gui.flows"))
                for target in targets
            ), module
        if module.startswith("guy4ase.gui.flows"):
            assert not any(
                target in {
                    "guy4ase.gui.dialogs.main_window",
                    "guy4ase.gui.dialogs.workflow_window",
                }
                for target in targets
            ), module
        if module.startswith("guy4ase.gui.input_parameters"):
            assert not any(
                target.startswith(("guy4ase.gui.dialogs", "guy4ase.gui.widgets"))
                for target in targets
            ), module
        if module.startswith("guy4ase.gui.application"):
            assert not any(
                target.startswith(
                    (
                        "guy4ase.gui.dialogs",
                        "guy4ase.gui.widgets",
                        "guy4ase.gui.flows",
                    )
                )
                for target in targets
            ), module

    visited = set()

    def visit(module, trail):
        assert module not in trail, " -> ".join((*trail, module))
        if module in visited:
            return
        for target in graph[module]:
            visit(target, (*trail, module))
        visited.add(module)

    for module in graph:
        visit(module, ())


def test_all_parameter_value_editors_share_one_explicit_contract():
    assert EDITORS
    assert all(issubclass(editor, ParameterValueEditor) for editor in EDITORS.values())
    assert all(
        issubclass(editor, ParameterValueEditor)
        for editor in (
            IntegerEditor,
            RealEditor,
            BooleanEditor,
            ChoiceEditor,
            TextEditor,
            EnergyEditor,
            VectorEditor,
        )
    )


def test_indexed_binding_is_the_only_binding_with_index_capability():
    assert "index" not in SessionFieldBinding.__dict__
    assert "index" in IndexedFieldBinding.__dict__


def test_editor_registry_dispatches_known_grammar_types():
    assert editor_for_type(Energy()) == "energy"
    assert editor_for_type(Real()) == "real"


def test_lightweight_input_parameter_modules_import_without_qt_or_dialogs():
    subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
from guy4ase.gui.input_parameters.expert_fields import EXPERT_FIELDS
from guy4ase.gui.input_parameters.specs.registry import task_dialog_spec
assert EXPERT_FIELDS
assert task_dialog_spec('scf').task == 'scf'
assert not any(name.startswith('PyQt6') for name in sys.modules)
assert not any(name.startswith('guy4ase.gui.dialogs.') for name in sys.modules)
""",
        ],
        cwd=ROOT,
        check=True,
        timeout=30,
    )


def test_domain_element_assignment_import_does_not_pull_in_gui():
    subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
import guy4ase.ase.element_assignment
assert not any(name.startswith('PyQt6') for name in sys.modules)
assert not any(name.startswith('guy4ase.gui') for name in sys.modules)
""",
        ],
        cwd=ROOT,
        check=True,
        timeout=30,
    )


def test_all_gui_modules_import_in_a_fresh_process():
    subprocess.run(
        [
            sys.executable,
            "-c",
            """
import importlib
import pkgutil
import guy4ase.gui
for module in pkgutil.walk_packages(guy4ase.gui.__path__, 'guy4ase.gui.'):
    importlib.import_module(module.name)
""",
        ],
        cwd=ROOT,
        check=True,
        timeout=30,
    )


def test_session_binding_parameters_follows_the_working_snapshot():
    session = InputParametersSession(InputParameters.create("scf"))
    binding = SessionFieldBinding(
        session,
        field("SCF", "NITER", "Iterations"),
        "expert",
    )

    binding.set_value(42)
    first_snapshot = binding.parameters
    binding.set_value(17)

    assert first_snapshot.SCF.NITER() == 42
    assert binding.parameters is session.working_parameters
    assert binding.parameters.SCF.NITER() == 17


@pytest.mark.parametrize(
    "name",
    ["system-run.svg", "run-build-clean.svg", "labplot-xy-interpolation-curve.svg"],
)
def test_icons_are_found_after_relocation(name):
    assert icon_path(name).is_file()


def test_element_rows_use_callbacks_without_a_parent_dialog():
    app = QApplication.instance() or QApplication([])
    parents, messages = [], []

    def pick_element(parent):
        parents.append(parent)
        return "Co"

    atoms = Atoms("Fe", cell=np.eye(3), pbc=True)
    atoms.set_array("labels", np.asarray(["a"], dtype=object))
    draft = ElementAssignmentDraft(atoms)
    row = QLetterRow(
        draft,
        draft.sites[0],
        select_element=pick_element,
        on_validation=lambda label, message: messages.append((label, message)),
    )
    row.rows[0]["pick"].click()
    app.processEvents()
    assert parents == [row]
    assert row.rows[0]["elem"].text() == "Co"
    row.add_row()
    row.rows[1]["elem"].setText("Fe")
    assert messages[-1] == ("a", "Occupation too large for site a")
    row.close()
