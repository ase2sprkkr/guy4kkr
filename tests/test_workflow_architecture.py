"""Architecture checks for Qt-independent Guided workflow planning."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_workflow_planning_imports_without_qt_or_dialogs():
    subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
from guy4ase.gui.application.recent_presentation import RecentLaunch
from guy4ase.gui.application.workflow_model import RunTask
from guy4ase.gui.application.workflow_planner import WorkflowPlanner
from guy4ase.gui.application.workspace_actions import EmptySpheresAction
assert RecentLaunch and RunTask and WorkflowPlanner and EmptySpheresAction
assert not any(name.startswith('PyQt6') for name in sys.modules)
assert not any(name.startswith('guy4ase.gui.dialogs.') for name in sys.modules)
""",
        ],
        cwd=ROOT,
        check=True,
        timeout=30,
    )
