from __future__ import annotations

import json

from PyQt6.QtCore import QRect

from guy4ase.gui.application.window_geometry import (
    WindowGeometryStore,
    adjust_window_geometry,
)


def test_adjust_window_geometry_clamps_size_and_position() -> None:
    available = QRect(0, 0, 1280, 720)
    assert adjust_window_geometry(QRect(1100, 650, 600, 500), available) == QRect(
        680, 220, 600, 500
    )
    assert adjust_window_geometry(QRect(-100, -50, 1800, 900), available) == QRect(
        0, 0, 1280, 720
    )


def test_adjust_window_geometry_centers_disconnected_window() -> None:
    available = QRect(0, 0, 1920, 1040)
    restored = adjust_window_geometry(
        QRect(3000, 100, 1000, 700),
        available,
        center_if_outside=True,
    )
    assert restored == QRect(460, 170, 1000, 700)


def test_window_geometry_store_ignores_corrupt_entries(tmp_path) -> None:
    path = tmp_path / "window_geometry.json"
    path.write_text(
        json.dumps(
            {
                "windows": {
                    "good": {
                        "x": 10,
                        "y": 20,
                        "width": 800,
                        "height": 600,
                        "maximized": True,
                        "screen": "screen-1",
                    },
                    "bad": {"x": 0, "y": 0, "width": -1, "height": 20},
                }
            }
        ),
        encoding="utf-8",
    )
    store = WindowGeometryStore(path)
    assert set(store._states) == {"good"}
    assert store._states["good"].maximized is True
    assert store._states["good"].screen == "screen-1"
