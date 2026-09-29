"""Pure lattice-transformation regressions."""
import numpy as np
import pytest
from ase import Atoms

from guy4ase.physics.lattice import match_structure_axis_length


def test_match_structure_axis_length_preserves_direction_and_inputs():
    source = Atoms(
        "H",
        scaled_positions=[[0.5, 0.5, 0.5]],
        cell=[[2.0, 0.0, 0.0], [0.0, 3.0, 0.0], [0.0, 0.0, 4.0]],
    )
    target = Atoms("He", cell=[1.0, 6.0, 1.0])
    source_cell = source.cell.array.copy()
    source_position = source.positions.copy()

    result = match_structure_axis_length(source, target, 1)

    assert result is not source
    assert np.allclose(result.cell[1], [0.0, 6.0, 0.0])
    assert np.allclose(result.get_scaled_positions(), [[0.5, 0.5, 0.5]])
    assert np.allclose(source.cell.array, source_cell)
    assert np.allclose(source.positions, source_position)


@pytest.mark.parametrize("axis", [-1, 3, 1.5])
def test_match_structure_axis_length_rejects_invalid_axis(axis):
    atoms = Atoms("H", cell=[1.0, 1.0, 1.0])

    with pytest.raises(ValueError, match="Axis must"):
        match_structure_axis_length(atoms, atoms, axis)


def test_match_structure_axis_length_rejects_zero_length_vector():
    source = Atoms("H", cell=[[1, 0, 0], [0, 0, 0], [0, 0, 1]])
    target = Atoms("He", cell=[1.0, 2.0, 1.0])

    with pytest.raises(ValueError, match="near-zero length"):
        match_structure_axis_length(source, target, 1)
