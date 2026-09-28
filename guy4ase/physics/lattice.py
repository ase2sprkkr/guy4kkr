"""Pure lattice transformations."""
import numpy as np


def scale_lattice_to_lengths(lattice, lengths):
    lattice_array = np.asarray(lattice, dtype=float)
    if lattice_array.shape != (3, 3):
        raise ValueError("Lattice must be a 3x3 matrix of row vectors.")

    target_lengths = np.asarray(lengths, dtype=float)
    if target_lengths.shape != (3,):
        raise ValueError("Lengths must contain exactly three values: a, b, c.")
    if (target_lengths <= 0).any():
        raise ValueError("Lattice constants must be positive numbers.")

    original_lengths = np.linalg.norm(lattice_array, axis=1)
    if np.isclose(original_lengths, 0.0).any():
        raise ValueError("Cannot scale structure with zero lattice constant.")

    factors = target_lengths / original_lengths
    scaled_lattice = lattice_array.copy()
    for axis in range(3):
        scaled_lattice[axis] = lattice_array[axis] * factors[axis]
    return scaled_lattice
