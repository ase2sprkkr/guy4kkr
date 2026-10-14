from guy4ase.gui.application.workflow_actions import (
    WorkflowAction,
    WorkflowActions,
    WorkflowState,
)


def test_no_structure_offers_only_initial_workflow_actions():
    actions = WorkflowActions.for_state(WorkflowState(has_structure=False))

    assert actions == (
        WorkflowAction.CREATE_3D,
        WorkflowAction.CREATE_FROM_DATABASE,
        WorkflowAction.DOWNLOAD_STRUCTURE,
        WorkflowAction.CREATE_2D_SURFACE,
        WorkflowAction.CREATE_2D_STRUCTURE,
        WorkflowAction.LOAD_STRUCTURE,
        WorkflowAction.LOAD_OUTPUT,
    )


def test_fresh_structure_offers_empty_spheres_scf_and_start_over():
    actions = WorkflowActions.for_state(
        WorkflowState(
            has_structure=True,
            can_run_scf=True,
            empty_spheres_action="add",
        )
    )

    assert actions == (
        WorkflowAction.VISUALIZE_STRUCTURE,
        WorkflowAction.ADD_EMPTY_SPHERES,
        WorkflowAction.RUN_SCF,
        WorkflowAction.START_OVER,
    )


def test_iterating_scf_offers_continue_and_new_calculation():
    actions = WorkflowActions.for_state(
        WorkflowState(
            has_structure=True,
            scf_status="ITR-BULK",
            can_run_scf=True,
            empty_spheres_action="recalculate",
        )
    )

    assert actions == (
        WorkflowAction.VISUALIZE_STRUCTURE,
        WorkflowAction.RECALCULATE_EMPTY_SPHERES,
        WorkflowAction.CONTINUE_SCF,
        WorkflowAction.USE_FOR_NEW_CALCULATION,
        WorkflowAction.START_OVER,
    )


def test_pending_structure_restart_suppresses_empty_spheres_action():
    actions = WorkflowActions.for_state(
        WorkflowState(
            has_structure=True,
            scf_status="ITR",
            can_run_scf=True,
            empty_spheres_action="recalculate",
            structure_change_requires_scf_restart=True,
        )
    )

    assert WorkflowAction.RECALCULATE_EMPTY_SPHERES not in actions
    assert WorkflowAction.CONTINUE_SCF in actions


def test_converged_3d_structure_offers_new_calculation_and_2d_derivations():
    actions = WorkflowActions.for_state(
        WorkflowState(
            has_structure=True,
            scf_status="CONVERGED",
            scf_converged=True,
            can_build_2d=True,
        )
    )

    assert actions == (
        WorkflowAction.VISUALIZE_STRUCTURE,
        WorkflowAction.USE_FOR_NEW_CALCULATION,
        WorkflowAction.BUILD_2D_SURFACE,
        WorkflowAction.BUILD_2D_STRUCTURE,
        WorkflowAction.START_OVER,
    )


def test_restart_stage_does_not_offer_new_calculation_again():
    actions = WorkflowActions.for_state(
        WorkflowState(
            has_structure=True,
            scf_status="START",
            can_run_scf=True,
        )
    )

    assert WorkflowAction.RUN_SCF in actions
    assert WorkflowAction.USE_FOR_NEW_CALCULATION not in actions
