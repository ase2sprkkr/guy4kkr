"""Shared pytest fixtures for GUI tests."""
from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="session", autouse=True)
def _qt_application() -> QApplication:
    """Keep the process-wide Qt application alive for the whole test session."""
    application = QApplication.instance() or QApplication([])
    return application
