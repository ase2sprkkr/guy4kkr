"""Mutable workspace storage and its read-only application view."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ase2sprkkr.sprkkr.sprkkr_atoms import SPRKKRAtoms

from guy4ase.physics.lattice import StructureKind, detect_structure_kind


@dataclass
class WorkspaceState:
    """Mutable document storage owned by ``WorkspaceController``."""

    atoms: Any | None = None
    input_parameters: Any | None = None
    directory: str | None = None
    potential_path: str | None = None
    result: Any | None = None
    # Results available for browsing in the UI, newest first.
    result_history: tuple[Any, ...] = ()
    # None = not searched / provenance unknown; 0 = searched and none found;
    # positive = number of trailing empty-sphere sites added by Guy4ASE.
    empty_spheres_added: int | None = None
    restarted: bool = False

    def structure_kind(self) -> StructureKind | None:
        """Classify the current structure directly from ``atoms``."""
        return detect_structure_kind(self.atoms)

    def can_calculate(self) -> bool:
        """Return whether the workspace has all inputs required to run."""
        return (
            self.atoms is not None
            and self.input_parameters is not None
            and bool(self.directory)
        )

    def scf_status(self) -> str | None:
        """Return the normalized SCFSTATUS stored in the attached potential."""
        atoms = self.atoms
        if not isinstance(atoms, SPRKKRAtoms):
            return None
        if not atoms.has_potential():
            return None
        if self.restarted:
            return "START"
        status = atoms.potential.SCF_INFO.SCFSTATUS()
        if status is None:
            return None
        status = str(status).strip().upper()
        return status or None

    def is_scf_converged(self) -> bool:
        """Return effective SPR-KKR convergence derived from the current atoms."""
        if self.restarted:
            return False
        atoms = self.atoms
        if atoms is None:
            return False
        checker = getattr(atoms, "sprkkr_is_scf_converged", None)
        return bool(callable(checker) and checker())

    def has_vacuum_sites(self) -> bool:
        """Return whether the current structure contains pure vacuum sites."""
        atoms = self.atoms
        if atoms is None:
            return False
        if isinstance(atoms, SPRKKRAtoms):
            return any(site.is_vacuum() for site in atoms.sites)
        return any(int(number) == 0 for number in getattr(atoms, "numbers", ()))

    def empty_spheres_action(self) -> str | None:
        """Return ``add``/``recalculate`` for the explicit ES workflow.

        Imported or manually created vacuum sites are deliberately not treated
        as generated empty spheres. Recalculation is offered only while we
        still know exactly how many trailing sites Guy4ASE added.
        """
        if self.atoms is None:
            return None
        if self.empty_spheres_added is not None:
            return "recalculate" if self.empty_spheres_added > 0 else None
        if self.has_vacuum_sites():
            return None
        return "add"


class WorkspaceView:
    """Live read-only view of controller-owned workspace storage.

    Returned model objects such as ``atoms`` remain borrowed references and
    retain their own mutability contracts. The document slots themselves cannot
    be reassigned through this view; all publication goes through the controller.
    """

    __slots__ = ("__state",)

    def __init__(self, state: WorkspaceState) -> None:
        self.__state = state

    @property
    def atoms(self) -> Any | None:
        return self.__state.atoms

    @property
    def input_parameters(self) -> Any | None:
        return self.__state.input_parameters

    @property
    def directory(self) -> str | None:
        return self.__state.directory

    @property
    def potential_path(self) -> str | None:
        return self.__state.potential_path

    @property
    def result(self) -> Any | None:
        return self.__state.result

    @property
    def result_history(self) -> tuple[Any, ...]:
        return self.__state.result_history

    @property
    def empty_spheres_added(self) -> int | None:
        return self.__state.empty_spheres_added

    @property
    def restarted(self) -> bool:
        return self.__state.restarted

    def structure_kind(self) -> StructureKind | None:
        return self.__state.structure_kind()

    def can_calculate(self) -> bool:
        return self.__state.can_calculate()

    def scf_status(self) -> str | None:
        return self.__state.scf_status()

    def is_scf_converged(self) -> bool:
        return self.__state.is_scf_converged()

    def has_vacuum_sites(self) -> bool:
        return self.__state.has_vacuum_sites()

    def empty_spheres_action(self) -> str | None:
        return self.__state.empty_spheres_action()
