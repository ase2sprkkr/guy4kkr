from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APPLICATION = ROOT / "guy4ase" / "gui" / "application"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add(node.module or "")
    return imports


def test_result_history_is_the_inner_provenance_dependency():
    imports = _imports(APPLICATION / "result_history.py")

    assert "guy4ase.gui.application.result_capture" not in imports
    assert "guy4ase.gui.application.result_artifacts" not in imports
    assert "guy4ase.gui.application.result_loading" not in imports
    assert "guy4ase.gui.application.result_presentation" not in imports
    assert not any(name.startswith("PyQt6") for name in imports)


def test_structure_provenance_is_not_defined_by_result_history():
    history_tree = ast.parse(
        (APPLICATION / "result_history.py").read_text(encoding="utf-8")
    )
    class_names = {
        node.name for node in history_tree.body if isinstance(node, ast.ClassDef)
    }
    imports = _imports(APPLICATION / "result_history.py")

    assert "StructureProvenance" not in class_names
    assert "CapturedStructure" not in class_names
    assert "guy4ase.gui.application.structure_provenance" in imports


def test_result_capture_uses_structure_provenance_contract():
    capture_tree = ast.parse(
        (APPLICATION / "result_capture.py").read_text(encoding="utf-8")
    )
    imported_history_names = {
        alias.name
        for node in ast.walk(capture_tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "guy4ase.gui.application.result_history"
        for alias in node.names
    }
    imported_structure_names = {
        alias.name
        for node in ast.walk(capture_tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "guy4ase.gui.application.structure_provenance"
        for alias in node.names
    }

    assert "CapturedResult" in imported_history_names
    assert "StructureProvenance" in imported_structure_names
    assert "CapturedStructure" not in imported_history_names


def test_workspace_stores_no_independent_potential_path():
    workspace_tree = ast.parse(
        (APPLICATION / "workspace.py").read_text(encoding="utf-8")
    )
    assignments = {
        target.attr
        for node in ast.walk(workspace_tree)
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Attribute)
        and isinstance(target.value, ast.Name)
        and target.value.id == "self"
    }

    assert "potential_path" not in assignments


def test_result_action_policy_does_not_observe_file_versions_directly():
    path = APPLICATION / "result_action_policy.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = _imports(path)

    assert "guy4ase.gui.application.result_artifacts" in imports
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "current"
        for node in ast.walk(tree)
    )
