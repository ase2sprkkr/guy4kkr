"""Policy for presenting calculations in the Guided workflow."""
from __future__ import annotations

from guy4ase.gui.input_parameters.tasks import GuidedTaskDefinition, WorkflowStage


def guided_task_is_recommended(
    definition: GuidedTaskDefinition,
    *,
    has_structure: bool,
    scf_converged: bool,
) -> bool:
    """Return whether a Guided task should be offered for the current state.

    This is presentation/workflow policy, not an execution validity check.
    Expert calculations remain launchable whenever the workspace contains the
    concrete calculation inputs required by the execution boundary.
    """
    if not has_structure:
        return False
    if definition.workflow.stage is WorkflowStage.POST_SCF:
        return scf_converged
    return True
