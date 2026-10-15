from types import SimpleNamespace

import pytest
from ase import Atoms
from ase.build import bulk
from ase2sprkkr import SPRKKRAtoms
from ase2sprkkr.sprkkr.build import semiinfinite_system

from guy4ase.gui.application.workspace import (
    CalculationState,
    WorkspaceContext,
    WorkspaceState,
)


def _scf_atoms(status=None, *, converged=False):
    atoms = SPRKKRAtoms.promote_ase_atoms(
        Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True),
        symmetry=False,
    )
    atoms.sprkkr_is_scf_converged = lambda: converged
    if status is not None:
        atoms._potential = SimpleNamespace(
            SCF_INFO=SimpleNamespace(SCFSTATUS=lambda: status)
        )
    return atoms


def test_workspace_state_has_explicit_calculation_and_context_parts():
    calculation = CalculationState(atoms=Atoms("Fe"))
    context = WorkspaceContext(directory="work", active_project_id="project")
    workspace = WorkspaceState(calculation=calculation, context=context)

    assert workspace.calculation is calculation
    assert workspace.context is context
    with pytest.raises(AttributeError):
        _ = workspace.atoms
    with pytest.raises(AttributeError):
        _ = workspace.directory


def test_structure_kind_is_derived_from_current_atoms():
    calculation = CalculationState()
    assert calculation.structure_kind() is None

    calculation.atoms = Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True)
    assert calculation.structure_kind() == "3d"

    calculation.atoms = semiinfinite_system(bulk("Fe", "bcc", a=2.8), (0, 0))
    assert calculation.structure_kind() == "2d"

    calculation.atoms = Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=(True, False, False))
    assert calculation.structure_kind() == "unknown"


def test_scf_status_and_convergence_are_derived_separately():
    calculation = CalculationState(atoms=_scf_atoms("ITR-L-BULK"))
    assert calculation.scf_status() == "ITR-L-BULK"
    assert not calculation.is_scf_converged()

    calculation.atoms = _scf_atoms(" START ", converged=True)
    assert calculation.scf_status() == "START"
    assert calculation.is_scf_converged()

    calculation.atoms = _scf_atoms(converged=True)
    assert calculation.scf_status() is None
    assert calculation.is_scf_converged()

    calculation.atoms = Atoms("Fe")
    assert calculation.scf_status() is None
    assert not calculation.is_scf_converged()


def test_pending_restart_reports_start_without_mutating_structure_potential():
    atoms = Atoms("Fe")
    calculation = CalculationState(atoms=atoms, restarted=True)

    assert calculation.scf_status() == "START"
    assert not calculation.is_scf_converged()
    assert calculation.atoms is atoms
