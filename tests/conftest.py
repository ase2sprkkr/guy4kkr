"""Shared pytest fixtures for GUI tests."""
from __future__ import annotations

import pytest
from PyQt6.QtCore import QCoreApplication, QEvent
from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="session", autouse=True)
def _qt_application() -> QApplication:
    """Keep the process-wide Qt application alive for the whole test session."""
    application = QApplication.instance() or QApplication([])
    return application


@pytest.fixture(autouse=True)
def _cleanup_qt_widgets(_qt_application: QApplication):
    """Destroy top-level widgets deterministically between GUI tests.

    PyQt wrappers can participate in Python reference cycles even though Qt owns
    their underlying QObject tree.  Leaving top-level widgets for cyclic GC can
    therefore run Qt destruction at an arbitrary point in a later test.  Queue
    deletion while the session QApplication is certainly alive and flush the
    deferred deletes before the next test starts.
    """
    yield

    for widget in QApplication.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _qt_application.processEvents()
