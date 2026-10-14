import pytest

from guy4ase.gui.application.materialized import (
    MaterializationCheckedOut,
    MaterializationNotCheckedOut,
    Materialized,
)


def test_drop_keeps_provenance_and_get_reloads():
    loaded = []
    reloaded = object()
    item = Materialized(
        "p1",
        materializer=lambda provenance: loaded.append(provenance) or reloaded,
        value=object(),
    )

    item.drop()

    assert item.provenance == "p1"
    assert not item.is_materialized
    assert item.get() is reloaded
    assert loaded == ["p1"]


def test_take_transfers_mutable_realization_but_keeps_logical_provenance():
    original = []
    item = Materialized("p1", materializer=lambda provenance: [provenance], value=original)

    taken = item.take_for_mutation()

    assert taken is original
    assert item.provenance == "p1"
    assert item.is_checked_out
    assert not item.is_materialized
    with pytest.raises(MaterializationCheckedOut):
        item.take_for_mutation()


def test_read_during_checkout_rematerializes_old_logical_state():
    original = ["old"]
    item = Materialized("p1", materializer=lambda provenance: [provenance], value=original)
    draft = item.take_for_mutation()
    draft[:] = ["changed"]

    current_read = item.get()

    assert current_read == ["p1"]
    assert current_read is not draft
    assert item.provenance == "p1"


def test_abandoned_mutation_keeps_rematerialized_old_state():
    item = Materialized("p1", materializer=lambda provenance: [provenance], value=["old"])
    draft = item.take_for_mutation()
    draft[:] = ["changed"]
    old_read = item.get()

    item.abandon_mutation()

    assert not item.is_checked_out
    assert item.provenance == "p1"
    assert item.get() is old_read
    assert item.get() == ["p1"]


def test_committed_mutation_installs_new_provenance_and_overwrites_old_read_cache():
    item = Materialized("p1", materializer=lambda provenance: [provenance], value=["old"])
    draft = item.take_for_mutation()
    old_read = item.get()
    draft[:] = ["new"]

    item.replace_after_mutation(draft, "p2")

    assert item.provenance == "p2"
    assert item.get() is draft
    assert item.get() is not old_read
    assert item.get() == ["new"]


def test_mutation_completion_requires_checkout():
    item = Materialized("p1", materializer=lambda provenance: [provenance], value=["old"])

    with pytest.raises(MaterializationNotCheckedOut):
        item.replace_after_mutation(["new"], "p2")
    with pytest.raises(MaterializationNotCheckedOut):
        item.abandon_mutation()
