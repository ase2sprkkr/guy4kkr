"""Workflow recommendations for guided SPR-KKR tasks.

This module deliberately does not decide whether ASE2SPRKKR may execute a task.
Backend validity belongs to ASE2SPRKKR; these rules only decide which guided
calculation cards are useful to offer for the current workspace state.
"""
from __future__ import annotations

from guy4ase.gui.input_parameters.specs.registry import (
    GuidedTaskDefinition,
    WorkflowStage,
)


def is_guided_task_recommended(
    definition: GuidedTaskDefinition,
    *,
    has_structure: bool,
    scf_converged: bool,
) -> bool:
    """Return whether a guided task should be offered in the workflow view."""
    if not has_structure:
        return False
    if definition.workflow_stage is WorkflowStage.POST_SCF:
        return scf_converged
    return True
