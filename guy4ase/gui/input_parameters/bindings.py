"""Paths and direct access to an existing InputParameters object (no value copy)."""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, TypeAlias

import numpy as np
from ase2sprkkr.input_parameters.input_parameters import InputParameters

InputParameterPath: TypeAlias = tuple[str, ...]


def resolve_option(parameters: InputParameters, path: InputParameterPath) -> Any:
    """Resolve an option without relying on ase2sprkkr's ambiguous name search."""
    value: Any = parameters
    for name in path:
        # Conditional BSF members still need editors while inactive. Attribute
        # access rejects them; explicit item access intentionally permits it.
        value = value[name]
    return value


def values_equal(left: Any, right: Any) -> bool:
    """Compare nested values without NumPy's ambiguous array truth conversion."""
    if isinstance(left, np.ndarray) or isinstance(right, np.ndarray):
        try:
            return bool(np.array_equal(np.asarray(left), np.asarray(right), equal_nan=True))
        except TypeError:
            return bool(np.array_equal(np.asarray(left), np.asarray(right)))
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        return left.keys() == right.keys() and all(
            values_equal(left[key], right[key]) for key in left
        )
    if (
        isinstance(left, Sequence)
        and isinstance(right, Sequence)
        and not isinstance(left, (str, bytes))
        and not isinstance(right, (str, bytes))
    ):
        return len(left) == len(right) and all(
            values_equal(a, b) for a, b in zip(left, right)
        )
    try:
        result = left == right
        if isinstance(result, np.ndarray):
            return bool(np.all(result))
        return bool(result)
    except Exception:
        return False


class InputParametersBinding:
    """Read/write adapter; the caller owns parameters and reacts to commits.

    A getter follows replaced parameter objects without retaining stale values.
    Guided editors can use InputParametersSession's matching methods directly.
    """

    def __init__(self, get_parameters: Callable[[], InputParameters],
                 on_changed: Callable[[InputParameterPath], None]):
        self._get_parameters = get_parameters
        self._on_changed = on_changed

    def option(self, path: InputParameterPath):
        return resolve_option(self._get_parameters(), path)

    def value(self, path: InputParameterPath):
        return self.option(path)(all_values=True)

    def set_value(self, path: InputParameterPath, value, **_kwargs):
        """Write directly and notify after success; this adapter supplies no undo.

        Extra session-style arguments (such as source_page) are ignored so
        shared widgets can use either this adapter or InputParametersSession.
        """
        option = self.option(path)
        if values_equal(option(all_values=True), value):
            return False
        option.set(value)
        self._on_changed(path)
        return True
