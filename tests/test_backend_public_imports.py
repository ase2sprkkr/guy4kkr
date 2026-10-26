"""Keep ASE2SPRKKR imports compatible with its explicitly exposed APIs."""

from __future__ import annotations

import ast
from pathlib import Path

import ase2sprkkr


ROOT = Path(__file__).parents[1] / "guy4ase"
# Older backend releases have root shortcuts but no __all__ declaration.
# Inspect their actual attributes rather than rejecting every root import.
_ROOT_EXPORTS = frozenset(
    getattr(ase2sprkkr, "__all__", None)
    or (name for name in vars(ase2sprkkr) if not name.startswith("_"))
)

# These contracts have a stable owning module, even in backend versions that
# do not re-export them from ase2sprkkr. Use those module imports consistently.
_MODULE_OWNED = {
    "FileState": "ase2sprkkr.execution",
    "FileVersion": "ase2sprkkr.execution",
    "FileVersionCaptureError": "ase2sprkkr.execution",
    "PotentialFileChanged": "ase2sprkkr.potentials.potentials",
}
_ROOT_SHORTCUTS = _ROOT_EXPORTS.difference(_MODULE_OWNED)


def test_backend_imports_follow_public_contracts():
    violations = []
    for path in ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            module = node.module or ""
            if module != "ase2sprkkr" and not module.startswith("ase2sprkkr."):
                continue

            names = {alias.name for alias in node.names}
            if module == "ase2sprkkr":
                # Importing an undeclared name from the root may work in a
                # development checkout but fail with another backend version.
                unsupported = names - _ROOT_EXPORTS
                misplaced = names.intersection(_MODULE_OWNED)
                issues = unsupported | misplaced
            else:
                # Root shortcuts are preferred for the common public classes.
                # Specialized contracts stay with their documented owner.
                issues = names.intersection(_ROOT_SHORTCUTS)
                issues.update(
                    name for name in names.intersection(_MODULE_OWNED)
                    if module != _MODULE_OWNED[name]
                )

            if issues:
                violations.append(
                    f"{path.relative_to(ROOT.parent)}:{node.lineno}: "
                    f"{', '.join(sorted(issues))} imported from {module}"
                )

    assert not violations, (
        "Use root imports only for the standard ASE2SPRKKR shortcuts; "
        "specialized symbols belong to their public defining modules:\n"
        + "\n".join(violations)
    )
