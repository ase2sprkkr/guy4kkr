"""Numeric BSF geometry editor; committed values live in the shared session."""


from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from guy4ase.gui.input_parameters.bsf import EK, bsf_mode
from guy4ase.gui.misc.tables import fit_table_height
from guy4ase.gui.widgets.numeric_table import (
    CoordinateDelegate,
    CoordinateTable,
    coordinate_value,
)


class KPathTable(QWidget):
    """One row per KA/KE segment, or one three-component origin in k–k mode.

    The table is an editing buffer, refreshed from the session on undo/redo.
    Display rounding never touches EditRole values or the input parameters.
    Incomplete/invalid edits remain local until corrected or a session refresh
    replaces the draft (including undo/redo and edits to other parameters).
    """
    validationChanged = pyqtSignal(str)

    def __init__(self, session, page_id, parent=None):
        super().__init__(parent)
        self.session, self.page_id = session, page_id
        self._refreshing = False
        self._ek = True
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.table = CoordinateTable(self)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.delegate = CoordinateDelegate(self.table)
        self.delegate.invalid.connect(self.validationChanged)
        self.table.setItemDelegate(self.delegate)
        self.table.itemChanged.connect(self._cell_changed)
        self.table.copyRequested.connect(self.copy)
        self.table.pasteRequested.connect(self.paste)
        layout.addWidget(self.table)
        row = QHBoxLayout()
        self.add_button = self._button(row, "Add segment", self.add_segment)
        self.remove_button = self._button(row, "Remove", self.remove_segments)
        self.up_button = self._button(row, "↑", lambda: self.move_segment(-1))
        self.up_button.setToolTip("Move selected segment up")
        self.down_button = self._button(row, "↓", lambda: self.move_segment(1))
        self.down_button.setToolTip("Move selected segment down")
        self.clear_button = self._button(row, "Default origin", self.clear_origin)
        row.addStretch(1)
        self._button(row, "Copy", self.copy)
        self._button(row, "Paste", self.paste)
        layout.addLayout(row)
        hint = QLabel("Cartesian coordinates in 2π/a. Fractions (1/2) and spreadsheet paste are supported. "
                      "Display is shortened; edit or hover for full precision.", self)
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.setFocusProxy(self.table)

    def _button(self, layout, text, callback):
        button = QPushButton(text, self)
        button.setAutoDefault(False)
        button.clicked.connect(callback)
        layout.addWidget(button)
        return button

    def refresh(self):
        self._ek = bsf_mode(self.session.working_parameters) == EK
        starts = self.session.value(("TASK", "KA"))
        ends = self.session.value(("TASK", "KE")) if self._ek else None
        count = max(len(starts) if starts is not None else 0,
                    len(ends) if ends is not None else 0) if self._ek else 1
        rows = []
        for i in range(count):
            start = list(starts[i]) if starts is not None and i < len(starts) else [None] * 3
            end = list(ends[i]) if ends is not None and i < len(ends) else [None] * 3
            rows.append(start + end if self._ek else start)
        self._show_rows(rows)
        for button in (self.add_button, self.remove_button, self.up_button, self.down_button):
            button.setVisible(self._ek)
        self.clear_button.setVisible(not self._ek)

    def _show_rows(self, rows):
        """Replace the table's draft without committing it or emitting cell edits."""
        self._refreshing = True
        try:
            self.table.setColumnCount(6 if self._ek else 3)
            headers = ([f"Start {axis}" for axis in ("kx", "ky", "kz")]
                       + [f"End {axis}" for axis in ("kx", "ky", "kz")]) if self._ek else ["kx", "ky", "kz"]
            self.table.setHorizontalHeaderLabels(headers)
            self.table.setRowCount(len(rows))
            for r, row in enumerate(rows):
                for c, value in enumerate(row):
                    item = QTableWidgetItem()
                    if value is not None:
                        item.setData(Qt.ItemDataRole.EditRole, value)
                        item.setToolTip(str(value))
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    self.table.setItem(r, c, item)
            self.add_button.setEnabled(len(rows) < 9)
            fit_table_height(self.table)
        finally:
            self._refreshing = False

    def _rows(self):
        return [[self.table.item(r, c).data(Qt.ItemDataRole.EditRole)
                 for c in range(self.table.columnCount())] for r in range(self.table.rowCount())]

    def _apply(self, text, row=0, column=0):
        """Parse all cells and commit KA/KE together, retaining the draft on failure.

        Row/column identify the changed value for history navigation; no partial
        segment is installed in the session if any coordinate is invalid.
        """
        try:
            rows = [[coordinate_value(v) for v in values] for values in self._rows()]
            updates = {"KA": [values[:3] for values in rows] or None}
            if self._ek:
                updates["KE"] = [values[3:] for values in rows] or None
            path = ("TASK", "KE" if column >= 3 else "KA")
            self.session.mutate(lambda p: p.TASK.set(updates), text=text,
                                source_page=self.page_id, path=path, field_index=row)
            self.validationChanged.emit("")
            if self.table.rowCount():
                self.table.setCurrentCell(min(row, self.table.rowCount() - 1), column)
            return True
        except (ValueError, TypeError, ZeroDivisionError, OverflowError) as exc:
            self.validationChanged.emit(str(exc))
            return False

    def _cell_changed(self, item):
        if not self._refreshing:
            self._apply("Edit K-path coordinate" if self._ek else "Edit plane origin", item.row(), item.column())

    def add_segment(self):
        rows = self._rows()
        if len(rows) >= 9:
            self.validationChanged.emit("A path can contain at most 9 segments.")
            return
        index = self.table.currentRow() + 1 if self.table.currentRow() >= 0 else len(rows)
        start = rows[index - 1][3:].copy() if index else [0., 0., 0.]
        try:
            end = [coordinate_value(v) for v in start]
            end[0] += 1.
        except (ValueError, ZeroDivisionError, OverflowError) as exc:
            self.validationChanged.emit(str(exc))
            return
        rows.insert(index, start + end)
        self._show_rows(rows)
        self._apply("Add K-path segment", index)

    def remove_segments(self):
        selected = {index.row() for index in self.table.selectedIndexes()}
        if not selected:
            return
        rows = [row for i, row in enumerate(self._rows()) if i not in selected]
        self._show_rows(rows)
        self._apply("Remove K-path segments", min(selected))

    def move_segment(self, offset):
        row = self.table.currentRow()
        target = row + offset
        rows = self._rows()
        if row < 0 or not 0 <= target < len(rows):
            return
        rows[row], rows[target] = rows[target], rows[row]
        self._show_rows(rows)
        self._apply("Move K-path segment", target)

    def clear_origin(self):
        self.session.set_value(("TASK", "KA"), None, source_page=self.page_id, text="Use default plane origin")
        self.validationChanged.emit("")

    def copy(self):
        """Copy the selection's bounding rectangle as full-precision tab-separated data."""
        selected = self.table.selectedIndexes()
        if not selected:
            return
        rows = self._rows()
        r0, r1 = min(i.row() for i in selected), max(i.row() for i in selected)
        c0, c1 = min(i.column() for i in selected), max(i.column() for i in selected)
        text = "\n".join("\t".join("" if v is None else str(v) for v in row[c0:c1 + 1])
                         for row in rows[r0:r1 + 1])
        QApplication.clipboard().setText(text)

    def paste(self):
        """Insert a rectangular numeric block at the active cell as one session edit."""
        try:
            lines = QApplication.clipboard().text().strip().splitlines()
            if not lines:
                return
            values = [[coordinate_value(v) for v in (line.split("\t") if "\t" in line else line.split())]
                      for line in lines]
            if not values[0] or any(len(row) != len(values[0]) for row in values):
                raise ValueError("Paste a rectangular block of coordinates.")
            row, column = max(0, self.table.currentRow()), max(0, self.table.currentColumn())
            if column + len(values[0]) > self.table.columnCount() or row + len(values) > (9 if self._ek else 1):
                raise ValueError("Pasted coordinates exceed the table size (at most 9 segments).")
            rows = self._rows()
            while len(rows) < row + len(values):
                rows.append([None] * self.table.columnCount())
            for i, data in enumerate(values):
                rows[row + i][column:column + len(data)] = data
            self._show_rows(rows)
            self._apply("Paste K-path coordinates", row, column)
        except (ValueError, ZeroDivisionError, OverflowError) as exc:
            self.validationChanged.emit(str(exc))

    def focus_value(self, path, row):
        """Reveal the start/end coordinate row identified by an undo/redo command."""
        if self.table.rowCount():
            column = 3 if path[-1] == "KE" and self._ek else 0
            self.table.setCurrentCell(min(row or 0, self.table.rowCount() - 1), column)
        self.table.setFocus(Qt.FocusReason.OtherFocusReason)


class VectorEditor(QWidget):
    """A three-component vector with full-precision editing and optional unset state."""
    validationChanged = pyqtSignal(str)

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
