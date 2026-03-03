"""
PyQt6 equivalents of gui.common helpers.

- length_units: Same unit mapping as Tk version.
- create_units_combo(parent, callback): Returns a QComboBox configured with units and
  calls `callback(factor: float)` whenever the selection changes.
- chain_dialogs(*funcs, initial=None, all=False, back=False): Generic dialog chaining helper.
  Each func is called with keyword args from the previous result and may return:
    - None -> abort the chain and return None
    - 'back' -> step back to previous dialog (if possible) else return None
    - dict -> merged into next call's kwargs
  If `back` is truthy, we pass a back flag to each dialog after the first. If `back` is a string,
  it's used as the keyword name; if True, the keyword 'back' is used.

This file avoids importing any Tkinter symbols and only uses PyQt6.
"""
from __future__ import annotations

from typing import Callable, Dict, Any, Iterable, Optional

from PyQt6.QtWidgets import QComboBox, QWidget, QLineEdit
from PyQt6.QtGui import QDoubleValidator
from ase import units as ase_units

# Keep units consistent with the Tk version
length_units: Dict[str, float] = {
    "Angstrom (Å)": 1.0,
    "Nanometer (nm)": 10.0,
    "Picometer (pm)": 0.01,
    # Match the Tk version semantics: factor is relative to Angstrom
    "Rydberg (Ry)": ase_units.Rydberg / ase_units.Angstrom,
    "Bohr (a0)": ase_units.Bohr / ase_units.Angstrom,
}


def create_units_combo(parent: QWidget | None, callback: Callable[[float], None]) -> QComboBox:
    """Create a QComboBox with length units and invoke callback with the numeric factor on change.

    Args:
        parent: Parent QWidget (or None)
        callback: Function receiving the selected factor (float)
    Returns:
        The configured QComboBox instance.
    """
    combo = QComboBox(parent)
    items: Iterable[str] = list(length_units.keys())
    combo.addItems(items)
    # Default selection
    default_label = "Angstrom (Å)"
    idx = combo.findText(default_label)
    if idx >= 0:
        combo.setCurrentIndex(idx)

    def on_changed(_index: int) -> None:
        label = combo.currentText()
        factor = length_units.get(label, 1.0)
        try:
            callback(factor)
        except Exception:
            # Swallow callback errors to avoid crashing the UI; developers can connect their own safe slots
            pass

    combo.currentIndexChanged.connect(on_changed)
    return combo

class QDoubleEdit(QLineEdit):

      def __init__(self, min_val: float, max_val: float, decimals: int, parent: Optional[QWidget] = None):
           super().__init__(parent)
           validator = QDoubleValidator(min_val, max_val, decimals, self)
           validator.setNotation(QDoubleValidator.Notation.StandardNotation)

      def value(self)->Optional[float]:
           try:
               return float(self.text())
           except ValueError:
               return None

def chain_dialogs(*funcs: Callable[..., Any],
                  initial: list[Any] = [],
                  kwargs:   Dict[str, Any] = {},
                  all: bool = False, back: bool | str = False):
    """Run a sequence of dialog-like callables that accept kwargs and return a dict/'back'/None.

    This is framework-agnostic and can be used for PyQt6 dialogs that expose a functional API
    like: def run_dialog(...kwargs) -> dict | 'back' | None

    Args:
        *funcs: Callables to invoke in order.
        initial: Initial kwargs for the first callable.
        all: If True, return list of all intermediate results; else return the last one.
        back: If truthy, pass a back flag to callables after the first. If True, use key 'back'.
              If a string, use that as the key name.
    Returns:
        None on abort, or the last callable's return value (dict, Atoms, or other).
    """
    if initial is None:
        initial = {}

    results: list = []
    i = 0

    while i < len(funcs):
        func = funcs[i]
        # Determine args for current callable
        if i == 0:
            args = initial
        else:
            # For subsequent dialogs, pass the previous result as args
            args = results[i - 1]
            if not isinstance(args, tuple):
                args = (args,)

        kw = kwargs.copy()
        if back and i > 0:
            key = 'back' if back is True else (back if isinstance(back, str) else 'back')
            kw[key] = True

        result = func(*args, **kw)

        if result is None:
            return None
        if isinstance(result, str) and result == 'back':
            if i == 0:
                return None
            i -= 1
            continue

        if len(results) <= i:
            results.append(result)
        else:
            results[i] = result

        i += 1

    if all:
        return results
    # Return the last result directly (could be dict, Atoms, or anything)
    return results[-1] if results else None
