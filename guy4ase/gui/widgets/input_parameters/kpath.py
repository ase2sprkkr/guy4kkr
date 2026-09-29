"""Reusable numeric vector editor backed by the shared session."""


from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHeaderView, QTableWidget, QTableWidgetItem, QVBoxLayout

from guy4ase.gui.misc.tables import fit_table_height
from guy4ase.gui.widgets.numeric_table import CoordinateDelegate, coordinate_value
from guy4ase.gui.widgets.input_parameters.value_editor import (
    ParameterValueEditorWidget,
)


class VectorEditor(ParameterValueEditorWidget):
    """A three-component vector with full-precision editing and optional unset state."""
    def __init__(self, session, path, page_id, parent=None):
        super().__init__(parent)
        self.session, self.path, self.page_id = session, path, page_id
        self._refreshing = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget(1, 3, self)
        self.table.setHorizontalHeaderLabels(["kx", "ky", "kz"])
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        fit_table_height(self.table)
        self.delegate = CoordinateDelegate(self.table)
        self.table.setItemDelegate(self.delegate)
        self.table.itemChanged.connect(self.commit)
        layout.addWidget(self.table)
        self.setFocusProxy(self.table)

    def refresh(self):
        self._refreshing = True
        try:
            value = self.session.value(self.path)
            for column in range(3):
                item = QTableWidgetItem()
                if value is not None:
                    item.setData(Qt.ItemDataRole.EditRole, float(value[column]))
                    item.setToolTip(repr(float(value[column])))
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(0, column, item)
        finally:
            self._refreshing = False

    def commit(self, *_args):
        """Commit three coordinates, or None if all are blank; reject partial vectors."""
        if self._refreshing:
            return True
        try:
            cells = [self.table.item(0, c).data(Qt.ItemDataRole.EditRole) for c in range(3)]
            value = None if all(v is None or str(v).strip() == "" for v in cells) else [coordinate_value(v) for v in cells]
            self.session.set_value(self.path, value, source_page=self.page_id,
                                   text=f"Edit {self.path[-1]} vector")
            self.validationChanged.emit("")
            return True
        except (ValueError, TypeError, ZeroDivisionError, OverflowError) as exc:
            self.validationChanged.emit(str(exc))
            return False
