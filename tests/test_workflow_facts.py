import pytest

from guy4ase.gui.application.workflow_facts import (
    ScfProgress,
    classify_scf_progress,
)


@pytest.mark.parametrize(
    ("status", "expected"),
    (
        (None, ScfProgress.NOT_STARTED),
        ("", ScfProgress.NOT_STARTED),
        ("START", ScfProgress.NOT_STARTED),
        ("itr", ScfProgress.ITERATING),
        ("ITR-BULK", ScfProgress.BULK),
        ("ITR-L-BULK", ScfProgress.LEFT_BULK),
        ("ITR-R-BULK", ScfProgress.RIGHT_BULK),
        ("ITR-I-ZONE", ScfProgress.INTERACTION_ZONE),
        ("SOMETHING-NEW", ScfProgress.UNKNOWN),
    ),
)
def test_classify_scf_progress_normalizes_backend_status(status, expected):
    assert classify_scf_progress(status, converged=False) is expected


def test_converged_fact_takes_precedence_over_raw_status():
    assert (
        classify_scf_progress("ITR-BULK", converged=True)
        is ScfProgress.CONVERGED
    )


@pytest.mark.parametrize(
    "progress",
    (
        ScfProgress.ITERATING,
        ScfProgress.BULK,
        ScfProgress.LEFT_BULK,
        ScfProgress.RIGHT_BULK,
        ScfProgress.INTERACTION_ZONE,
    ),
)
def test_interrupted_scf_progress_can_continue(progress):
    assert progress.can_continue


@pytest.mark.parametrize(
    "progress",
    (
        ScfProgress.NOT_STARTED,
        ScfProgress.CONVERGED,
        ScfProgress.UNKNOWN,
    ),
)
def test_non_iterating_scf_progress_cannot_continue(progress):
    assert not progress.can_continue
