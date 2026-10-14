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


def test_result_capture_depends_on_history_data_contracts_not_the_reverse():
    capture_tree = ast.parse(
        (APPLICATION / "result_capture.py").read_text(encoding="utf-8")
    )
    imported_names = {
        alias.name
        for node in ast.walk(capture_tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "guy4ase.gui.application.result_history"
        for alias in node.names
    }
    class_names = {
        node.name for node in capture_tree.body if isinstance(node, ast.ClassDef)
    }

    assert {"CapturedResult", "CapturedStructure"} <= imported_names
    assert "CapturedResult" not in class_names
    assert "CapturedStructure" not in class_names


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
