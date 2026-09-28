from __future__ import annotations

import sys
from PyQt6.QtWidgets import QApplication

from guy4ase.gui.dialogs.workflow_window import WorkflowWindow


def main() -> int:
    app = QApplication(sys.argv)

    window = WorkflowWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
