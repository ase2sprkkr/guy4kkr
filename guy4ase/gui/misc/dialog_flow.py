"""Compose independent dialogs using caller-supplied functions."""
from typing import Any, Callable, Dict


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
