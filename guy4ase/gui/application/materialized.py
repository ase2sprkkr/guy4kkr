"""Runtime ownership of mutable values backed by immutable provenance."""
from __future__ import annotations

from collections.abc import Callable
from typing import Generic, TypeVar


T = TypeVar("T")
P = TypeVar("P")


class MaterializationCheckedOut(RuntimeError):
    """The owned runtime value is currently checked out for mutation."""


class MaterializationNotCheckedOut(RuntimeError):
    """A mutation completion was attempted without an active checkout."""


class Materialized(Generic[T, P]):
    """Own a logical value and an optional mutable runtime realization.

    ``provenance`` is always the authoritative description of the logical value.
    The runtime value is merely a realization of that provenance and may be
    discarded and reconstructed. Mutation transfers ownership of the realization
    out of this object; while checked out, the old provenance remains available
    for reload/cancel semantics and reads may rematerialize that old logical state.
    """

    def __init__(
        self,
        provenance: P,
        *,
        materializer: Callable[[P], T],
        value: T | None = None,
    ) -> None:
        self._provenance = provenance
        self._materializer = materializer
        self._value = value
        self._checked_out = False

    @property
    def provenance(self) -> P:
        return self._provenance

    @property
    def is_materialized(self) -> bool:
        return self._value is not None

    @property
    def is_checked_out(self) -> bool:
        return self._checked_out

    def get(self) -> T:
        """Return the current logical value, materializing it when necessary.

        While a mutator owns a checked-out realization, reads still represent the
        unchanged logical state and may therefore rematerialize it from provenance.
        The checked-out object is a private draft until it is committed.
        """
        if self._value is None:
            self._value = self._materializer(self._provenance)
        return self._value

    def drop(self) -> None:
        """Discard only the owned read realization, preserving provenance."""
        self._value = None

    def take_for_mutation(self) -> T:
        """Transfer exclusive ownership of the current realization to a mutator."""
        if self._checked_out:
            raise MaterializationCheckedOut(
                "The materialization is already checked out for mutation."
            )
        value = self.get()
        self._value = None
        self._checked_out = True
        return value

    def replace_after_mutation(self, value: T, provenance: P) -> None:
        """Install the mutated value together with provenance for its new state."""
        if not self._checked_out:
            raise MaterializationNotCheckedOut(
                "No materialization is checked out for mutation."
            )
        self._provenance = provenance
        self._value = value
        self._checked_out = False

    def abandon_mutation(self) -> None:
        """Abandon a checked-out value and keep the previous logical state."""
        if not self._checked_out:
            raise MaterializationNotCheckedOut(
                "No materialization is checked out for mutation."
            )
        self._checked_out = False
        # _value deliberately remains None if nobody rematerialized the logical
        # state while the draft was checked out. A later get() reconstructs it.

    def replace(self, value: T, provenance: P) -> None:
        """Replace the logical state when no mutator owns the current realization."""
        if self._checked_out:
            raise MaterializationCheckedOut(
                "Cannot replace a materialization while it is checked out."
            )
        self._provenance = provenance
        self._value = value
