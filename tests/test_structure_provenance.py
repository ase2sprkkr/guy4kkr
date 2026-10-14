from ase import Atoms

from guy4ase.gui.application.result_history import ResultHistory
from guy4ase.gui.application.structure_provenance import StructureProvenance


def test_snapshot_provenance_reconstructs_after_materialization_is_dropped():
    atoms = Atoms("Fe", positions=[[1.0, 2.0, 3.0]])
    provenance = StructureProvenance.capture(atoms)
    materialized = provenance.materialized(atoms)

    materialized.drop()
    restored = materialized.get()

    assert restored is not atoms
    assert restored.get_chemical_symbols() == ["Fe"]
    assert restored.positions.tolist() == [[1.0, 2.0, 3.0]]
    assert materialized.provenance is provenance


def test_equal_physical_content_does_not_reuse_logical_state_identity():
    atoms = Atoms("Fe")

    first = StructureProvenance.capture(atoms)
    second = StructureProvenance.capture(atoms.copy())

    assert first.identity != second.identity
    assert first != second
    assert first.structure_snapshot == second.structure_snapshot


def test_mutation_keeps_old_provenance_reloadable_until_commit():
    atoms = Atoms("Fe")
    old = StructureProvenance.capture(atoms)
    materialized = old.materialized(atoms)
    editable = materialized.take_for_mutation()
    editable.set_chemical_symbols(["Co"])

    old_read = materialized.get()

    assert materialized.provenance is old
    assert old_read.get_chemical_symbols() == ["Fe"]
    assert editable.get_chemical_symbols() == ["Co"]


def test_successful_mutation_installs_new_structure_provenance():
    atoms = Atoms("Fe")
    old = StructureProvenance.capture(atoms)
    materialized = old.materialized(atoms)
    editable = materialized.take_for_mutation()
    editable.set_chemical_symbols(["Co"])
    new = StructureProvenance.capture(editable)

    materialized.replace_after_mutation(editable, new)

    assert materialized.provenance is new
    assert materialized.provenance != old
    assert materialized.get() is editable


def test_result_history_keeps_structure_provenance_as_one_identity():
    provenance = StructureProvenance.capture(Atoms("Fe"))
    history = ResultHistory()

    structure_id, state_id = history.add_structure_state(provenance)
    state = history.state(state_id)

    assert structure_id == state.structure_id
    assert state.structure_provenance is provenance
    assert state.potential_path is provenance.potential_path
    assert state.potential_version is provenance.potential_version
    assert state.structure_snapshot is provenance.structure_snapshot
