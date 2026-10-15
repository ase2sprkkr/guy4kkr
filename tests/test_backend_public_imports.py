from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).parents[1] / "guy4ase"
_FORBIDDEN_MODULES = {
    "ase2sprkkr.input_parameters.input_parameters": {"InputParameters"},
    "ase2sprkkr.sprkkr.calculator": {"SPRKKR"},
    "ase2sprkkr.sprkkr.sprkkr_atoms": {"SPRKKRAtoms"},
    "ase2sprkkr.outputs.task_result": {"TaskResult"},
    "ase2sprkkr.potentials.potentials": {"Potential"},
}


def test_public_backend_core_types_are_not_imported_from_private_modules():
    violations = []
    for path in ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            forbidden = _FORBIDDEN_MODULES.get(node.module or "")
            if not forbidden:
                continue
            imported = forbidden.intersection(alias.name for alias in node.names)
            if imported:
                violations.append(
                    f"{path.relative_to(ROOT.parent)}:{node.lineno}: "
                    f"{', '.join(sorted(imported))}"
                )

    assert not violations, (
        "Import public ASE2SPRKKR core types from the package public API, not "
        "their implementation modules:\n" + "\n".join(violations)
    )
