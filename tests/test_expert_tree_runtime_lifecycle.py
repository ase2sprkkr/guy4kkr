"""Qt ownership regressions for Expert-tree subtree teardown."""
from __future__ import annotations

from PyQt6 import sip
from PyQt6.QtCore import QCoreApplication, QEvent
from PyQt6.QtWidgets import QApplication, QToolButton, QTreeWidget, QTreeWidgetItem, QWidget

from guy4ase.gui.widgets.input_parameters.expert_tree_runtime import ExpertTreeRuntime


def test_unregister_subtree_removes_cell_widgets_before_items_are_detached() -> None:
    application = QApplication.instance()
    assert application is not None

    tree = QTreeWidget()
    tree.setColumnCount(5)
    root = QTreeWidgetItem(["root"])
    child = QTreeWidgetItem(["child"])
    grandchild = QTreeWidgetItem(["grandchild"])
    tree.addTopLevelItem(root)
    root.addChild(child)
    child.addChild(grandchild)

    editor = QWidget(tree)
    action = QToolButton(tree)
    nested_editor = QWidget(tree)
    tree.setItemWidget(child, 2, editor)
    tree.setItemWidget(child, 3, action)
    tree.setItemWidget(grandchild, 2, nested_editor)

    runtime = ExpertTreeRuntime(tree)
    runtime.register_option(("CHILD",), child)
    runtime.register_option(("GRANDCHILD",), grandchild)

    runtime.unregister_subtree(root, include_root=False)

    assert runtime.option_item(("CHILD",)) is None
    assert runtime.option_item(("GRANDCHILD",)) is None
    assert tree.itemWidget(child, 2) is None
    assert tree.itemWidget(child, 3) is None
    assert tree.itemWidget(grandchild, 2) is None

    # Mirror the renderer's next step.  The detached item can still be held by
    # Python, but widgets that belonged to its former model indexes must already
    # be scheduled for destruction by the view.
    root.removeChild(child)
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    application.processEvents()

    assert sip.isdeleted(editor)
    assert sip.isdeleted(action)
    assert sip.isdeleted(nested_editor)
