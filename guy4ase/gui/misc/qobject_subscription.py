"""Qt-safe adapters for subscriptions owned by non-Qt services."""
from __future__ import annotations

from collections.abc import Callable
from weakref import ref

from PyQt6.QtCore import QObject, pyqtSignal

StringSubscriber = Callable[[Callable[[str], None]], Callable[[], None]]


class _StringSignalRelay(QObject):
    changed = pyqtSignal(str)


def subscribe_qt_string(
    owner: QObject,
    subscribe: StringSubscriber,
    slot: Callable[[str], None],
) -> QObject:
    """Relay string events into Qt without a source -> QObject ownership cycle.

    External services commonly retain subscribers strongly.  Subscribing a
    bound Qt signal therefore keeps its QObject (and potentially its complete
    parent widget tree) alive.  The retained listener below owns only a weak
    reference to the relay, while the owner's destruction deterministically
    removes the listener from the external service.
    """
    relay = _StringSignalRelay(owner)
    relay.changed.connect(slot)
    relay_ref = ref(relay)

    def listener(value: str) -> None:
        current = relay_ref()
        if current is not None:
            current.changed.emit(value)

    unsubscribe = subscribe(listener)

    def cleanup(*_args: object) -> None:
        unsubscribe()

    owner.destroyed.connect(cleanup)
    return relay
