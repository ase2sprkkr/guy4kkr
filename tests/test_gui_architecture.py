"""Protect the refactored package boundaries and independent controls."""
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
from guy4ase.gui.input_parameters.bindings import InputParametersBinding
from guy4ase.gui.input_parameters.field_binding import (
    IndexedFieldBinding,
    SessionFieldBinding,
)
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
from guy4ase.gui.widgets.input_parameters.value_editor import (
    ParameterValueEditor,
)
from guy4ase.gui.widgets.structures.element_assignment import QLetterRow

ROOT = Path(__file__).resolve().parents[1]
GUI = ROOT / "guy4ase" / "gui"


def _gui_graph():
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
            targets = []
            if isinstance(node, ast.Import):
                targets = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    base = importlib.util.resolve_name(
                        "." * node.level + base,
                        module if package else module.rpartition(".")[0],
                    )
                targets = [base] + [base + "." + alias.name for alias in node.names]
            graph[module].update(target for target in targets if target in modules)
    return graph


def test_gui_dependencies_are_acyclic_and_follow_layers():
    graph = _gui_graph()
    for module, targets in graph.items():
        if module.startswith("guy4ase.gui.widgets"):
            assert not any(
                t.startswith(("guy4ase.gui.dialogs", "guy4ase.gui.flows"))
                for t in targets
            ), module
        if module.startswith("guy4ase.gui.flows"):
            assert not any(
                t in {
                    "guy4ase.gui.dialogs.main_window",
                    "guy4ase.gui.dialogs.workflow_window",
                }
                for t in targets
            ), module
        if module.startswith("guy4ase.gui.input_parameters"):
            assert not any(t.startswith(("guy4ase.gui.dialogs", "guy4ase.gui.widgets")) for t in targets), module
        if module.startswith("guy4ase.gui.input_parameters.specs"):
            assert "guy4ase.gui.input_parameters.session" not in targets, module
        if module.startswith("guy4ase.gui.application"):
            assert not any(
                t.startswith(
                    (
                        "guy4ase.gui.dialogs",
                        "guy4ase.gui.widgets",
                        "guy4ase.gui.flows",
                    )
                )
                for t in targets
            ), module
        if module == "guy4ase.gui.style" or module.startswith(
            (
                "guy4ase.gui.misc",
                "guy4ase.gui.plots",
            )
        ):
            assert not any(t.startswith(("guy4ase.gui.dialogs", "guy4ase.gui.widgets", "guy4ase.gui.input_parameters")) for t in targets), module

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


def test_composition_root_owns_services_and_top_level_windows():
    """The two sibling views receive one session assembled in main.py."""
    workflow_source = (GUI / "dialogs" / "workflow_window.py").read_text()
    main_window_source = (GUI / "dialogs" / "main_window.py").read_text()
    composition_source = (ROOT / "guy4ase" / "main.py").read_text()

    for source in (workflow_source, main_window_source):
        tree = ast.parse(source)
        constructed = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
        }
        assert not constructed & {
            "WorkspaceController",
            "RecentFiles",
            "MainWindow",
            "WorkflowWindow",
        }
    assert "main_window" not in workflow_source
    assert "expert_window" not in workflow_source
    for dependency in (
        "WorkspaceController(",
        "RecentFiles(",
        "WorkflowWindow(",
        "MainWindow(",
    ):
        assert composition_source.count(dependency) == 1

    assert "GuiOperations" not in composition_source
    assert not (GUI / "flows" / "operations.py").exists()
    assert "self.operations" not in workflow_source
    assert "self.operations" not in main_window_source
    assert "def prepare_guided_task" not in main_window_source


def test_workspace_mutation_and_history_persistence_are_outside_main_window():
    for name in ("main_window.py", "workflow_window.py"):
        source = (GUI / "dialogs" / name).read_text()
        for assignment in (
            "workspace.atoms =",
            "workspace.input_parameters =",
            "workspace.directory =",
            "workspace.potential_path =",
            "workspace.result =",
        ):
            assert assignment not in source
    main_source = (GUI / "dialogs" / "main_window.py").read_text()
    assert "def _remember_recent" not in main_source
    assert "def _load_recent_files" not in main_source
    assert "def _save_recent_files" not in main_source


def test_workspace_low_level_mutation_is_confined_to_controller():
    controller_path = GUI / "application" / "workspace_controller.py"
    workspace_path = GUI / "application" / "workspace.py"
    forbidden_assignments = (
        "workspace.atoms =",
        "workspace.input_parameters =",
        "workspace.directory =",
        "workspace.potential_path =",
        "workspace.result =",
    )
    private_operations = (
        "._set_structure(",
        "._set_input_parameters(",
        "._set_directory(",
        "._set_result(",
    )
    retired_public_setters = (
        ".set_structure(",
        ".set_input_parameters(",
        ".set_directory(",
        ".adopt_result(",
    )

    for path in GUI.rglob("*.py"):
        if path in {controller_path, workspace_path}:
            continue
        source = path.read_text()
        assert not any(value in source for value in forbidden_assignments), path
        assert not any(value in source for value in private_operations), path
        assert not any(value in source for value in retired_public_setters), path

    workspace_source = workspace_path.read_text()
    assert "def reset(" not in workspace_source


def test_result_actions_have_one_dialog_owned_execution_implementation():
    object_view = (GUI / "dialogs" / "object_view.py").read_text()
    main_window = (GUI / "dialogs" / "main_window.py").read_text()
    workflow = (GUI / "dialogs" / "workflow_window.py").read_text()
    widget = (GUI / "widgets" / "result_actions.py").read_text()

    assert object_view.count("def execute_value_action(") == 1
    assert "execute_value_action(value, action, self)" in main_window
    assert "execute_value_action(value, action, self)" in workflow
    assert "object_view" not in widget
    assert "_result_dialogs" not in object_view + main_window + workflow


def test_transient_dialog_lifetime_uses_qt_ownership():
    calculation = (GUI / "flows" / "calculation.py").read_text()
    run_dialog = (GUI / "dialogs" / "run_calculation.py").read_text()
    object_view = (GUI / "dialogs" / "object_view.py").read_text()

    assert "_run_windows" not in calculation
    assert "_result_dialogs" not in object_view
    assert "_child_dialogs" not in object_view
    assert "WA_DeleteOnClose" in run_dialog
    assert "WA_DeleteOnClose" in object_view


def test_workflow_does_not_cache_derived_structure_kind():
    workflow = (GUI / "dialogs" / "workflow_window.py").read_text()
    lattice = (ROOT / "guy4ase" / "physics" / "lattice.py").read_text()

    assert "self._structure_kind" not in workflow
    assert "_detect_structure_kind" not in workflow
    assert "detect_structure_kind(atoms)" in workflow
    assert "def detect_structure_kind" in lattice
    assert "PyQt" not in lattice


def test_run_dialog_reports_completion_through_an_explicit_callback():
    source = (GUI / "dialogs" / "run_calculation.py").read_text()
    assert "handle_sprkkr_finished_result" not in source
    assert "on_finished" in source


def test_guided_renderer_has_no_task_specific_presentation_branches():
    source = (GUI / "dialogs" / "guided_input.py").read_text()
    renderer = (GUI / "widgets" / "input_parameters" / "form.py").read_text()
    assert "_update_bsf_state" not in source
    assert "_update_dynamic_state" not in source
    assert "bsf_mode" not in source
    assert "SPLIT_SWITCHES" not in source
    assert "bsf_mode" not in renderer
    assert "SPLIT_SWITCHES" not in renderer


def test_session_has_no_single_site_contour_semantics():
    source = (GUI / "input_parameters" / "session.py").read_text()
    for identifier in ("SPLITSS", "FSOHFF", "GRID", "NE", "single_site"):
        assert identifier not in source


def test_single_site_contour_policy_imports_without_qt():
    source = (GUI / "input_parameters" / "single_site_contour.py").read_text()
    assert "PyQt" not in source
    assert "InputParametersSession" not in source


def test_guided_dialog_delegates_field_anatomy_to_form_views():
    source = (GUI / "dialogs" / "guided_input.py").read_text()
    renderer = (GUI / "widgets" / "input_parameters" / "form.py").read_text()
    for old_parallel_structure in (
        "_editors_by_path",
        "_labels_by_path",
        "_field_widgets",
        "_group_views",
        "_detail_toggles",
        "_editor_errors",
        "_rule_errors",
        "_navigation_items",
        "_navigation_labels",
        "_navigation_tints",
    ):
        assert old_parallel_structure not in source
    assert "editor._error" not in renderer
    assert "QListWidgetItem" not in renderer
    assert "navigation_item" not in renderer
    assert "navigation_label" not in renderer
    assert "navigation_tint" not in renderer


def test_expert_dialog_delegates_parameter_tree_rendering():
    dialog = (GUI / "dialogs" / "expert_input.py").read_text()
    renderer = (
        GUI / "widgets" / "input_parameters" / "expert_tree.py"
    ).read_text()
    field_specs = (
        GUI / "input_parameters" / "expert_fields.py"
    ).read_text()

    assert "ExpertInputTreeEditor(" in dialog
    for tree_detail in (
        "QTreeWidgetItem",
        "GrammarSequence",
        "_build_section",
        "_build_option",
        "_rebuild_compound_option",
        "_update_table_cell",
    ):
        assert tree_detail not in dialog

    # The modal shell owns the one isolated draft. The reusable tree only
    # accesses the current externally owned document through its getter.
    assert "copy(copy_values=True)" in dialog
    assert "copy(copy_values=True)" not in renderer
    assert "self._params" not in renderer
    assert "create_editor(" in renderer
    assert "ParameterValueEditor" in renderer
    for option_semantic in (
        "('ENERGY', 'EMIN')",
        "('ENERGY', 'EMAX')",
        "('MODE', 'C')",
        "('MODE', 'SOC')",
        "energy_bound",
        "scaling",
    ):
        assert option_semantic not in renderer
        assert option_semantic in field_specs
    assert "PyQt6" not in field_specs


def test_workflow_and_guided_renderer_use_shared_visual_primitives():
    """Shared styling belongs below dialogs; semantic colors remain local."""
    workflow = (GUI / "dialogs" / "workflow_window.py").read_text()
    guided = (GUI / "dialogs" / "guided_input.py").read_text()
    renderer = (GUI / "widgets" / "input_parameters" / "form.py").read_text()
    assert "def _blend_color" not in workflow
    assert "guy4ase.gui.style" in workflow
    assert "guy4ase.gui.style" in guided
    assert "guy4ase.gui.style" in renderer


def test_generic_parameter_adapter_has_no_registered_editor_implementations():
    source = (GUI / "widgets" / "input_parameters" / "parameter.py").read_text()
    for implementation in (
        "bsf_mesh",
        "bsf_kpath",
        "bsf_vectors",
        "set_energy_points",
        "select_path",
        "set_bound_energy",
        "bound_energy_state",
        "RelativisticScalingEditor",
    ):
        assert implementation not in source

    vector_source = (GUI / "widgets" / "input_parameters" / "kpath.py").read_text()
    assert "input_parameters.bsf" not in vector_source
    assert "BsfVectorsEditor" not in vector_source

    common_source = (GUI / "widgets" / "input_parameters" / "common.py").read_text()
    assert "input_parameters.bsf" not in common_source


def test_all_parameter_value_editors_share_one_explicit_contract():
    assert EDITORS
    assert all(
        issubclass(editor, ParameterValueEditor)
        for editor in EDITORS.values()
    )
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
    source = (GUI / "widgets" / "input_parameters" / "parameter.py").read_text()
    for capability in (
        "dependencies",
        "full_width",
        "help_text",
        "set_editor_tooltip",
        "focus_for_history",
    ):
        assert f'getattr(self.control, "{capability}"' not in source
        assert f'hasattr(self.control, "{capability}"' not in source


def test_parameter_editor_does_not_reconstruct_value_editor_dispatch():
    source = (GUI / "widgets" / "input_parameters" / "parameter.py").read_text()
    for implementation in (
        "QSpinBox",
        "QDoubleSpinBox",
        "QCheckBox",
        "QComboBox",
        "QLineEdit",
        "EnergyEditor",
        "VectorEditor",
        "input_commit",
        '("ENERGY", "GRID")',
        '("ENERGY", "NE")',
    ):
        assert implementation not in source
    for operation in (
        "self.control.refresh()",
        "self.control.commit()",
        "self.control.focus_for_history(path, index)",
    ):
        assert operation in source


def test_indexing_is_the_only_specialized_field_binding_capability():
    assert "index" not in SessionFieldBinding.__dict__
    assert "index" in IndexedFieldBinding.__dict__
    source = (GUI / "input_parameters" / "field_binding.py").read_text()
    assert "EnergyFieldBinding" not in source
    assert 'placement.kind == "energy"' not in source


def test_field_placement_has_one_editor_selector_and_one_registry():
    schema = (GUI / "input_parameters" / "specs" / "schema.py").read_text()
    assert "kind: str" not in schema
    assert 'editor: str = "auto"' in schema
    parameter = (GUI / "widgets" / "input_parameters" / "parameter.py").read_text()
    assert "create_editor(" in parameter
    assert "create_registered_editor" not in parameter
    assert "create_option_editor" not in parameter
    assert editor_for_type(Energy()) == "energy"
    assert editor_for_type(Real()) == "real"

    registry = (GUI / "widgets" / "input_parameters" / "registry.py").read_text()
    assert "def editor_for_type" in registry
    assert "def create_editor" in registry
    assert "EnergyState" not in registry
    assert "convert_energy" not in registry
    assert "create_option_editor" not in registry
    assert "EDITORS" not in (GUI / "widgets" / "input_parameters" / "bsf.py").read_text()
    assert "EDITORS" not in (GUI / "widgets" / "input_parameters" / "common.py").read_text()

    expert_tree = (
        GUI / "widgets" / "input_parameters" / "expert_tree.py"
    ).read_text()
    assert "create_editor(" in expert_tree
    assert "EnergyEditor" not in expert_tree
    assert "RelativisticScalingEditor" not in expert_tree


def test_expert_dialog_commits_only_explicitly_registered_value_editors():
    source = (
        GUI / "widgets" / "input_parameters" / "expert_tree.py"
    ).read_text()
    assert "item.setData(0, self._VALUE_EDITOR_ROLE, True)" in source
    assert "if not editor.commit():" in source
    assert "isinstance(editor, ParameterValueEditor) and not editor.commit()" not in source


def test_packages_and_specs_do_not_load_dialogs_or_qt():
    subprocess.run([sys.executable, "-c", """
import sys
import guy4ase.gui.dialogs
import guy4ase.gui.widgets.input_parameters
from guy4ase.gui.input_parameters.expert_fields import EXPERT_FIELDS
from guy4ase.gui.input_parameters.specs.registry import task_dialog_spec
assert EXPERT_FIELDS
assert task_dialog_spec('scf').task == 'scf'
assert not any(name.startswith('PyQt6') for name in sys.modules)
assert not any(name.startswith('guy4ase.gui.dialogs.') for name in sys.modules)
"""], cwd=ROOT, check=True, timeout=30)


def test_all_gui_modules_import_in_a_fresh_process():
    subprocess.run([sys.executable, "-c", """
import importlib
import pkgutil
import guy4ase.gui
for module in pkgutil.walk_packages(guy4ase.gui.__path__, 'guy4ase.gui.'):
    importlib.import_module(module.name)
"""], cwd=ROOT, check=True, timeout=30)


def test_binding_follows_replacement_without_owning_values():
    current = [InputParameters.create("scf")]
    changes = []
    binding = InputParametersBinding(lambda: current[0], changes.append)
    path = ("SCF", "NITER")
    assert binding.set_value(path, 42)
    assert current[0].SCF.NITER() == 42
    assert changes == [path]
    assert not binding.set_value(path, 42)
    old = current[0]
    current[0] = InputParameters.create("scf")
    assert binding.option(path) is current[0].SCF.NITER
    binding.set_value(path, 17)
    assert old.SCF.NITER() == 42
    assert current[0].SCF.NITER() == 17


@pytest.mark.parametrize("name", ["system-run.svg", "run-build-clean.svg", "labplot-xy-interpolation-curve.svg"])
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
        draft, draft.sites[0], select_element=pick_element,
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


def test_element_assignment_domain_model_has_no_qt_dependency():
    source = (ROOT / "guy4ase" / "ase" / "element_assignment.py").read_text()
    assert "PyQt" not in source
    assert "guy4ase.gui" not in source
