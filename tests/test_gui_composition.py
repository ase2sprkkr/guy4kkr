"""Composition-root and shared GUI-session regressions."""
import json
import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('MPLCONFIGDIR', '/tmp/guy4ase-test-matplotlib')

from PyQt6.QtWidgets import QApplication

from guy4ase.main import GuiApplication


def test_composition_root_owns_state_objects_and_loads_history(tmp_path):
    _application = QApplication.instance() or QApplication([])
    history = tmp_path / 'recent.json'
    history.write_text(json.dumps({
        'recent_files': {
            'structure': ['/tmp/Fe.cif'],
            'input': [],
            'output': [],
        },
        'last_recent_kind': 'structure',
    }))

    gui = GuiApplication(recent_files_path=history)

    assert gui.controller.parent() is gui
    assert gui.recent_files.parent() is gui
    assert gui.recent_files.paths('structure') == ('/tmp/Fe.cif',)


def test_composition_root_lazily_owns_and_reuses_both_windows(tmp_path):
    application = QApplication.instance() or QApplication([])
    gui = GuiApplication(recent_files_path=tmp_path / 'recent.json')
    workflow = gui.create_workflow_window()

    assert gui._main_window is None
    workflow._open_expert_mode()
    application.processEvents()
    expert = gui.create_main_window()

    assert gui.create_workflow_window() is workflow
    assert gui.create_main_window() is expert
    assert workflow.controller is expert.controller is gui.controller
    assert workflow.recent_history is expert.recent_history is gui.recent_files
    assert not hasattr(gui, "operations")
    assert not hasattr(workflow, "operations")
    assert not hasattr(expert, "operations")

    workflow.close()
    application.processEvents()
    assert expert.isVisible()
    expert.close()
    gui.show_main_window()
    application.processEvents()
    assert expert.isVisible()
    expert.close()
