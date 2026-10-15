from types import SimpleNamespace

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


def test_workspace_separates_calculation_state_from_launch_context():
    atoms = Atoms("Fe")
    calculation = CalculationState(atoms=atoms, input_parameters=object())
    context = WorkspaceContext(directory="run", active_project_id="project")

    workspace = WorkspaceState(calculation=calculation, context=context)

    assert workspace.calculation is calculation
    assert workspace.context is context
    assert workspace.atoms is atoms
    assert workspace.directory == "run"
    assert workspace.context.active_project_id == "project"


def test_structure_kind_is_derived_from_current_atoms():
    workspace = WorkspaceState()
    assert workspace.structure_kind() is None

    workspace.atoms = Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True)
    assert workspace.structure_kind() == "3d"

    workspace.atoms = semiinfinite_system(bulk("Fe", "bcc", a=2.8), (0, 0))
    assert workspace.structure_kind() == "2d"

    workspace.atoms = Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=(True, False, False))
    assert workspace.structure_kind() == "unknown"


def test_scf_status_and_convergence_are_derived_separately():
    workspace = WorkspaceState(atoms=_scf_atoms("ITR-L-BULK"))
    assert workspace.scf_status() == "ITR-L-BULK"
    assert not workspace.is_scf_converged()

    workspace.atoms = _scf_atoms(" START ", converged=True)
    assert workspace.scf_status() == "START"
    assert workspace.is_scf_converged()

    workspace.atoms = _scf_atoms(converged=True)
    assert workspace.scf_status() is None
    assert workspace.is_scf_converged()

    workspace.atoms = Atoms("Fe")
    assert workspace.scf_status() is None
    assert not workspace.is_scf_converged()


def test_pending_restart_reports_start_without_mutating_structure_potential():
    atoms = Atoms("Fe")
    workspace = WorkspaceState(atoms=atoms, restarted=True)

    assert workspace.scf_status() == "START"
    assert not workspace.is_scf_converged()
    assert workspace.atoms is atoms
