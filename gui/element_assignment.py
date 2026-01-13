from __future__ import annotations

from typing import Dict, Any, Optional

from PyQt6.QtCore import Qt, QEvent
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton, QLineEdit,
    QScrollArea, QDoubleSpinBox,
    QSizePolicy, QSplitter, QStyle, QTableWidget, QHeaderView, QGroupBox, QFrame
)
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from ase import Atoms
import re
import numpy as np
from weakref import WeakKeyDictionary
from ase.data import chemical_symbols
from ase2sprkkr.sprkkr.atomic_types import AtomicType
from ase2sprkkr import SPRKKRAtoms
from ase import Atoms
from .lattice import plot_lattice, plot_sites_in_lattice
from ..ase.utils import partition_by_kinds, labels_for_partitions


class _GlobalSentinel:
    pass

_DEFAULT_KEY = _GlobalSentinel()
_DIALOGS = WeakKeyDictionary()
_VALID_SYMBOLS = set(s for s in chemical_symbols if isinstance(s, str))
_VALID_SYMBOLS.add("Vc")

class QLetterRow(QWidget):
    """Container for one Wyckoff letter's element rows."""
    glyph_font = QFont()
    glyph_font.setBold(True)
    glyph_font.setPointSize(12)

    def __init__(self, payload: Dict[str, Any],
                 cell: np.ndarray,
                 parent: Optional[QWidget] = None,
                 on_activity: Optional[callable] = None,
                 on_break: Optional[callable] = None):
        super().__init__(parent)
        self.cell = cell
        self._on_activity = on_activity
        self._on_break = on_break
        self.rows: list[Dict[str, Any]] = []

        # Two-column layout: left = element assignment, right = positions table
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(0)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 0)

        # Site header (separate line, spans both columns)
        header_w = QWidget(self)
        header_v = QVBoxLayout(header_w)
        header_v.setContentsMargins(0, 0, 0, 0)
        header_v.setSpacing(2)
        line = QFrame(header_w)
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        header_v.addWidget(line)
        self.site_label = QLabel()
        f = self.site_label.font()
        f.setBold(True)
        self.site_label.setFont(f)
        header_v.addWidget(self.site_label)
        grid.addWidget(header_w, 0, 0, 1, 2)

        left = QWidget(self)
        left.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.vbox = QVBoxLayout(left)
        self.vbox.setContentsMargins(0, 0, 0, 0)

        # Controls row
        controls = QHBoxLayout()
        controls.addStretch(1)
        self.normalize_btn = QPushButton("Normalize")
        self.normalize_btn.clicked.connect(self._normalize)
        controls.addWidget(self.normalize_btn)
        # Break symmetry button (visible only when multiplicity > 1)
        self.break_btn = QPushButton("Break symmetry")
        can_break = len(payload['positions']) > 1
        self.break_btn.setVisible(bool(can_break))
        if can_break and callable(self._on_break):
            self.break_btn.clicked.connect(lambda: self._on_break(self.payload))
        controls.addWidget(self.break_btn)
        self.vbox.addLayout(controls)

        # Rows area
        self.rows_box = QVBoxLayout()
        self.vbox.addLayout(self.rows_box)

        # Add-row button
        add_row = QHBoxLayout()
        self.add_btn = QPushButton("＋ Add element")
        self.add_btn.clicked.connect(self.add_row)
        add_row.addWidget(self.add_btn)
        self.vbox.addLayout(add_row)

        # Positions table (fractional X/Y/Z per equivalent site)
        # Positions on the right; title omitted (there is a global header above all sites)
        self.positions_group = QGroupBox(self)
        self.positions_group.setTitle("")
        self.positions_group.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        pos_v = QVBoxLayout(self.positions_group)
        pos_v.setContentsMargins(6, 6, 6, 6)
        self.positions_table = QTableWidget(0, 3, self.positions_group)
        self.positions_table.setHorizontalHeaderLabels(["X", "Y", "Z"])
        self.positions_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.positions_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.positions_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.positions_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.positions_table.horizontalHeader().setStretchLastSection(False)
        self.positions_table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        for j in range(3):
            self.positions_table.setColumnWidth(j, 90)
        pos_v.addWidget(self.positions_table)

        pos_btns = QHBoxLayout()
        pos_btns.addStretch(1)
        self.add_pos_btn = QPushButton("＋")
        self.add_pos_btn.setToolTip("Add position")
        self.add_pos_btn.setFixedWidth(34)
        self.add_pos_btn.clicked.connect(self._add_position)
        pos_btns.addWidget(self.add_pos_btn)

        self.del_pos_btn = QPushButton()
        self.del_pos_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon))
        self.del_pos_btn.setToolTip("Delete selected position")
        self.del_pos_btn.setFixedWidth(34)
        self.del_pos_btn.clicked.connect(self._delete_position)
        pos_btns.addWidget(self.del_pos_btn)

        pos_v.addLayout(pos_btns)

        # Fixed width: just enough to fit the table
        vh_w = self.positions_table.verticalHeader().sizeHint().width()
        fw = self.positions_table.frameWidth()
        table_w = sum(self.positions_table.columnWidth(j) for j in range(3)) + vh_w + fw * 2 + 2
        m = pos_v.contentsMargins()
        self.positions_table.setFixedWidth(table_w)
        self.positions_group.setFixedWidth(table_w + m.left() + m.right())

        grid.addWidget(left, 1, 0, alignment=Qt.AlignmentFlag.AlignTop)
        grid.addWidget(self.positions_group, 1, 1, alignment=Qt.AlignmentFlag.AlignTop)

        self._pos_spins: list[list[QDoubleSpinBox]] = []

        self.load_payload(payload)

    @property
    def label(self):
        return self.payload.get('label', '')

    def load_payload(self, payload: Dict[str, Any]) -> None:
        self.payload = payload
        self.site_label.setText(f"Site kind {payload.get('label', '')}")

        self._refresh_break_button()

        self._rebuild_positions_table()
        self.load_occupancy(payload.get('occupancy', {}))
        self._validate_controls_state()
        self._validate_totals()

    def _refresh_break_button(self) -> None:
        try:
            can_break = len(self.payload.get('positions', [])) > 1
        except Exception:
            can_break = False
        self.break_btn.setVisible(bool(can_break))

    def _rebuild_positions_table(self) -> None:
        positions = self.payload.get('positions', [])
        n_rows = len(positions)
        old_rows = self.positions_table.rowCount()
        self.positions_table.setRowCount(n_rows)
        self._pos_spins = []

        def setup(i, j, spin):
            spin.setProperty("pos_row", i)
            spin.setProperty("pos_col", j)
            spin.valueChanged.connect(lambda v, r=i, c=j: self._on_position_changed(r, c, v))
            spin.installEventFilter(self)
            try:
                spin.blockSignals(True)
                spin.setValue(float(positions[i][j]))
            except Exception:
                spin.setValue(0.0)
            finally:
                spin.blockSignals(False)

        for i in range(min(old_rows, n_rows)):
            for j in range(3):
                spin = self.positions_table.cellWidget(i, j)
                if isinstance(spin, QDoubleSpinBox):
                    try:
                        spin.valueChanged.disconnect()
                    except TypeError:
                        pass
                    setup(i, j, spin)

        for i in range(old_rows, n_rows):
            spin_row: list[QDoubleSpinBox] = []
            for j in range(3):
                spin = QDoubleSpinBox(self.positions_table)
                spin.setRange(0.0, 1.0)
                spin.setDecimals(4)
                spin.setSingleStep(0.05)
                spin.setAlignment(Qt.AlignmentFlag.AlignRight)
                self.positions_table.setCellWidget(i, j, spin)
                spin_row.append(spin)
                setup(i, j, spin)
            self._pos_spins.append(spin_row)

        header_h = self.positions_table.horizontalHeader().height()
        row_h = self.positions_table.verticalHeader().defaultSectionSize()
        self.positions_table.setMinimumHeight(header_h + n_rows * row_h + 2)
        self.positions_table.setMaximumHeight(header_h + n_rows * row_h + 2)

        # Enable delete only when there is more than one row
        try:
            self.del_pos_btn.setEnabled(n_rows > 1)
        except Exception:
            pass

    def _current_position_row(self) -> int:
        r = self.positions_table.currentRow()
        return int(r) if r is not None and r >= 0 else 0

    def _add_position(self) -> None:
        pos = np.asarray(self.payload.get('positions', []), dtype=float)
        if pos.ndim != 2 or pos.shape[1] != 3:
            pos = np.zeros((0, 3), dtype=float)

        if pos.shape[0] == 0:
            new_row = np.zeros((1, 3), dtype=float)
            pos = new_row
            new_index = 0
        else:
            pos = np.vstack([pos, pos[-1].copy()])
            new_index = pos.shape[0] - 1

        self.payload['positions'] = pos
        self._refresh_break_button()
        self._rebuild_positions_table()
        try:
            self.positions_table.setCurrentCell(new_index, 0)
        except Exception:
            pass
        try:
            if callable(self._on_activity):
                self._on_activity(self.label, new_index, True)
        except Exception:
            pass

    def _delete_position(self) -> None:
        pos = np.asarray(self.payload.get('positions', []), dtype=float)
        if pos.ndim != 2 or pos.shape[1] != 3 or pos.shape[0] <= 1:
            return

        row = self._current_position_row()
        row = max(0, min(row, pos.shape[0] - 1))
        pos = np.delete(pos, row, axis=0)
        self.payload['positions'] = pos
        self._refresh_break_button()
        self._rebuild_positions_table()

        new_row = min(row, pos.shape[0] - 1)
        try:
            self.positions_table.setCurrentCell(new_row, 0)
        except Exception:
            pass
        try:
            if callable(self._on_activity):
                self._on_activity(self.label, new_row, True)
        except Exception:
            pass

    def _on_position_changed(self, row: int, col: int, value: float) -> None:
        self.payload['positions'][row][col] = value
        # Ensure preview updates immediately when positions change
        try:
            if callable(self._on_activity):
                self._on_activity(self.label, row, True)
        except Exception:
            pass

    def load_occupancy(self, occupancy: Dict[Any, float]) -> None:
        """Replace current element rows with provided payload [{'element':sym,'occupancy':val},...]."""
        # remove existing row widgets
        for r in list(self.rows):
            r['w'].setParent(None)
        self.rows.clear()

        # add rows from payload
        if not occupancy:
            self._add_row()
        else:
            for symbol, occ in occupancy.items():
                symbol = symbol.sub(r'_\d+$', '', s)
                self._add_row(element=getattr(symbol, "symbol", str(symbol)), occ=occ)

    def add_row(self) -> None:
        """Add a blank element row."""
        self._add_row()
        self._validate_controls_state()
        self._validate_totals()

    def _add_row(self, element: Optional[str] = "", occ: float = 1.0) -> None:
        from .element_selector import select_element  # local import to avoid cyclic import

        row_w = QWidget(self)
        row_w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        h = QHBoxLayout(row_w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)

        elem_edit = QLineEdit()
        elem_edit.setPlaceholderText("Element")
        if not isinstance(element, str):
            element = ""
        elem_edit.setText(element)
        elem_edit.setMaxLength(3)
        elem_edit.setFixedWidth(55)
        label_elem = QLabel("Element")
        label_elem.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        h.addWidget(label_elem)
        h.addWidget(elem_edit)

        pick_btn = QPushButton("⚛️")
        pick_btn.setFont(self.glyph_font)
        pick_btn.setToolTip("Pick element")
        pick_btn.setFixedWidth(34)
        h.addWidget(pick_btn)

        occ_spin = QDoubleSpinBox()
        occ_spin.setRange(0.0, 1.0)
        occ_spin.setDecimals(3)
        occ_spin.setSingleStep(0.05)
        occ_spin.setValue(occ)
        label_occ = QLabel("occupation")
        label_occ.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        occ_spin.setFixedWidth(70)
        h.addWidget(occ_spin)

        # Keep controls left; push only the trash button to the far right.
        h.addStretch(1)

        del_btn = QPushButton()
        del_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon))
        del_btn.setToolTip("Remove this element row")
        del_btn.setFixedWidth(34)
        h.addWidget(del_btn)

        row = {
            'w': row_w,
            'elem': elem_edit,
            'occ': occ_spin,
            'del': del_btn,
            'pick': pick_btn,
        }
        self.rows.append(row)
        self.rows_box.addWidget(row_w)

        def do_pick():
            sym = select_element(self)
            if sym:
                elem_edit.setText(sym)
        pick_btn.clicked.connect(do_pick)
        del_btn.clicked.connect(lambda: self._remove_row(row))
        # Validation only; no redraw on value changes
        elem_edit.textChanged.connect(lambda _t: self._validate_row(row))
        occ_spin.valueChanged.connect(lambda _v: self._validate_totals())

        # Focus-driven highlighting
        for w in (elem_edit, occ_spin, pick_btn, del_btn):
            w.installEventFilter(self)

        self._validate_row(row)

    def _remove_row(self, row: Dict[str, Any]) -> None:
        if len(self.rows) <= 1:
            return
        row['w'].setParent(None)
        try:
            self.rows.remove(row)
        except ValueError:
            pass
        self._validate_controls_state()
        self._validate_totals()

    def _validate_controls_state(self) -> None:
        # disable delete when only one row
        for r in self.rows:
            r['del'].setEnabled(len(self.rows) > 1)

    def _validate_row(self, row: Dict[str, Any]) -> None:
        elem = row['elem'].text().strip()
        ok = elem in _VALID_SYMBOLS
        # Styling: red border when invalid. Keep readable background.
        if ok or elem == "":
            row['elem'].setStyleSheet("")
        else:
            # Use a darker background only if palette seems light; simple heuristic
            row['elem'].setStyleSheet("QLineEdit { border: 1px solid #cc3333; background-color: #330000; color: #ffecec; }")
        self._validate_totals()

    def _normalize(self) -> None:
        total = sum(r['occ'].value() for r in self.rows) or 1.0
        for r in self.rows:
            r['occ'].setValue(r['occ'].value() / total)
        self._validate_totals()

    def _validate_totals(self) -> None:
        total = sum(r['occ'].value() for r in self.rows)
        over = total > 1.0000001
        # red border on all occupancy widgets when overfull
        style_bad = "QDoubleSpinBox { border: 1px solid #cc3333; }"
        for r in self.rows:
            r['occ'].setStyleSheet(style_bad if over else "")
        # bubble up to parent dialog for OK state and error text
        dlg = self.window()
        dlg._update_ok_state()
        msg = f"Occupation too large for site {self.label}" if over else None
        dlg._set_site_error(self.label, msg)

    # Focus event filter to trigger highlighting only when user focuses a widget.
    def eventFilter(self, obj, event):  # type: ignore[override]
        try:
            if event.type() == QEvent.Type.FocusIn:
                if isinstance(obj, QDoubleSpinBox):
                    r = obj.property("pos_row")
                    c = obj.property("pos_col")
                    if r is not None and c is not None:
                        try:
                            self.positions_table.setCurrentCell(int(r), int(c))
                        except Exception:
                            pass
                if callable(self._on_activity):
                    if isinstance(obj, QDoubleSpinBox) and obj.property("pos_row") is not None:
                        self._on_activity(self.label, int(obj.property("pos_row")), False)
                    else:
                        self._on_activity(self.label)
        except Exception:
            pass
        return super().eventFilter(obj, event)

    def is_valid(self) -> bool:
        # Require at least one valid element symbol and total between 0 and 1.0
        has_valid_element = False
        for r in self.rows:
            elem = r['elem'].text().strip()
            if elem:
                if elem not in _VALID_SYMBOLS:
                    return False
                has_valid_element = True

        if not has_valid_element:
            return False

        total = sum(r['occ'].value() for r in self.rows)
        # Allow partial occupation: total must be > 0 and <= 1.0
        return 0.0 < total <= 1.0 + 1e-6

    def resulting_payload(self) -> list[Dict[str, Any]]:
        payload = self.payload
        occs = {}
        for r in self.rows:
            elem = r['elem'].text().strip()
            occ = float(r['occ'].value())
            if not elem:
                continue
            if elem in occs:
                elem = AtomicType.from_symbol(elem)
            occs[elem] = occ
        payload['occupancy'] = occs
        return payload

    @classmethod
    def payload_from_atoms(cls, atoms: Atoms) -> list[Dict[str, Any]]:
        """Extract payload from atoms."""
        payloads: list[Dict[str, Any]] = []
        parts = partition_by_kinds(atoms)
        kinds = atoms.get_array('spacegroup_kinds') if 'spacegroup_kinds' in atoms.arrays else None
        occs = atoms.info.get('occupancy', {})
        labels = labels_for_partitions(atoms, partitions=parts)
        positions = atoms.get_scaled_positions()

        occ_map: Dict[str, float] = {}
        for i, part in enumerate(parts):
            first = part[0]
            label = labels[i]
            sym = atoms[first].symbol
            if occs and kinds is not None:
                kind = kinds[first]
                occ = occs.get(str(kind), None)
            else:
                occ = None
            if occ is None:
                if sym == 'X':
                    occ = {}
                else:
                    occ = { sym: 1.0 }
            payloads.append({
                'label': label,
                'occupancy': occ,
                'positions': positions[part],
                'index': part,
            })
        return payloads

class ElementAssignmentDialog(QDialog):
    def __init__(self, parent: Optional[QWidget] = None, back: bool = False):
        super().__init__(parent)
        self.setWindowTitle("Assign Elements to Wyckoff Sites")
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowType.WindowMaximizeButtonHint
            | Qt.WindowType.WindowMinimizeButtonHint
        )
        # Wider default window to accommodate expanded left panel
        self.resize(1400, 650)
        self._allow_back = bool(back)
        self._letter_widgets: list[QLetterRow] = []
        self._cell: Optional[np.ndarray] = None
        self._active_letter: tuple(Optional[str],Optional[int]) = (None, None)
        self._site_errors: Dict[str, Optional[str]] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        root.addWidget(splitter, 1)

        # Left: Scroll area for letters
        left = QWidget()
        left_v = QVBoxLayout(left)
        self.scroll = QScrollArea(left)
        self.scroll.setWidgetResizable(True)
        self.container = QWidget()
        self.scroll.setWidget(self.container)
        self.container_layout = QVBoxLayout(self.container)
        self.container_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        left_v.addWidget(self.scroll, 1)
        # Keep left column wide enough and stable so headers and inputs fit
        # Widen left panel for better readability of element rows
        left.setMinimumWidth(750)
        # Initial splitter sizing (favor left)
        splitter.setSizes([850, 550])
        splitter.addWidget(left)

        # Right: 3D preview
        right = QWidget()
        right_v = QVBoxLayout(right)

        # Lattice vectors table (editable)
        lattice_vectors_group = QGroupBox("Lattice Vectors (Å)")
        lattice_vectors_layout = QVBoxLayout(lattice_vectors_group)
        self.lattice_vectors_table = QTableWidget(3, 3)
        self.lattice_vectors_table.setHorizontalHeaderLabels(["x", "y", "z"])
        self.lattice_vectors_table.setVerticalHeaderLabels(["a", "b", "c"])
        self.lattice_vectors_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.lattice_vectors_table.verticalHeader().setMinimumWidth(40)
        self.lattice_vectors_table.setMaximumHeight(120)

        # Initialize with spinboxes
        self.lattice_spinboxes = []
        for i in range(3):
            row_spinboxes = []
            for j in range(3):
                spinbox = QDoubleSpinBox()
                spinbox.setRange(-1000.0, 1000.0)
                spinbox.setDecimals(4)
                spinbox.setSingleStep(0.1)
                spinbox.setValue(0.0)
                spinbox.setAlignment(Qt.AlignmentFlag.AlignRight)
                spinbox.valueChanged.connect(self._on_lattice_vector_changed)
                self.lattice_vectors_table.setCellWidget(i, j, spinbox)
                row_spinboxes.append(spinbox)
            self.lattice_spinboxes.append(row_spinboxes)

        lattice_vectors_layout.addWidget(self.lattice_vectors_table)
        right_v.addWidget(lattice_vectors_group, 0)

        self.fig = Figure(figsize=(4, 4))
        self.ax = self.fig.add_subplot(111, projection='3d')
        self.canvas = FigureCanvas(self.fig)
        right_v.addWidget(self.canvas, 1)
        # Error label at the bottom of right panel (larger, centered)
        self.error_label = QLabel("")
        self.error_label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.error_label.setStyleSheet(
            "QLabel { color: #cc3333; font-size: 14px; font-weight: 600; padding: 4px 0; }"
        )
        right_v.addWidget(self.error_label)
        splitter.addWidget(right)

        # Buttons
        btns = QHBoxLayout()
        btns.addStretch(1)
        if self._allow_back:
            self.back_btn = QPushButton("Back")
            self.back_btn.clicked.connect(self._on_back)
            btns.addWidget(self.back_btn)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        btns.addWidget(self.cancel_btn)
        self.ok_btn = QPushButton("OK")
        self.ok_btn.clicked.connect(self._on_ok)
        self.ok_btn.setEnabled(False)
        btns.addWidget(self.ok_btn)
        root.addLayout(btns)



    def setup(self, atoms: Atoms, back: bool = False) -> None:
        # reset state
        self._allow_back = bool(back)
        for child in list(self._letter_widgets):
            child.setParent(None)
        self._atoms = atoms
        self._cell = atoms.cell.copy()

        # Update lattice vector spinboxes
        for i in range(3):
            for j in range(3):
                self.lattice_spinboxes[i][j].blockSignals(True)
                self.lattice_spinboxes[i][j].setValue(self._cell[i, j])
                self.lattice_spinboxes[i][j].blockSignals(False)

        payload = QLetterRow.payload_from_atoms(atoms)
        self._build_site_rows(payload)

        self._update_ok_state()
        self._draw_preview()

    def _build_site_rows(self, payloads) -> None:
        # Clear entire container layout (prevents duplicated spacers/headers across setups)
        while self.container_layout.count():
            item = self.container_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._letter_widgets.clear()

        # Build site rows
        for payload in payloads:
            row = QLetterRow(payload, self._atoms.cell, self.container, on_activity=self._mark_active, on_break=self._break_site)
            self.container_layout.addWidget(row)
            self._letter_widgets.append(row)

        # Global headers above all sites: left = Occupation, right = Positions
        if self._letter_widgets:
            first = self._letter_widgets[0]
            header = QWidget(self.container)
            header_grid = QGridLayout(header)
            header_grid.setContentsMargins(0, 0, 0, 6)
            header_grid.setHorizontalSpacing(10)
            header_grid.setColumnStretch(0, 1)
            header_grid.setColumnStretch(1, 0)

            occ_lbl = QLabel("Occupation")
            f = occ_lbl.font()
            f.setBold(True)
            occ_lbl.setFont(f)

            pos_lbl = QLabel("Positions")
            pos_lbl.setFont(f)
            pos_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            try:
                pm = first.positions_group.layout().contentsMargins()
                pos_lbl.setContentsMargins(pm.left(), 0, 0, 0)
            except Exception:
                pass
            pos_lbl.setFixedWidth(first.positions_group.sizeHint().width())

            header_grid.addWidget(occ_lbl, 0, 0, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            header_grid.addWidget(pos_lbl, 0, 1, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

            self.container_layout.insertWidget(0, header)

        # Spacer to consume remaining space
        spacer = QWidget(self.container)
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.container_layout.addWidget(spacer)

    def _capture_payloads(self) -> Dict[str, list[Dict[str, Any]]]:
        return [ w.resulting_payload() for w in self._letter_widgets ]

    def _break_site(self, payload) -> None:
        # Split a multi-position letter into independent subsites letter.1, letter.2, ...

        payloads = self._capture_payloads()
        labels = {p['label'] for p in payloads}
        out = []

        for idx, p in enumerate(payloads):
            if p is payload:
                out = payloads[:idx]

            for i,pos in enumerate(payload['positions']):
                index = payload.pop('index', None)
                add = payload.copy()
                template = f"{payload['label']}.{i+1}"
                label = template
                j=1
                while label in labels:
                    label = f"{template}.{j}"
                    j+=1
                add['label'] = label
                add['positions'] = pos
                if index is not None:
                    add['origin'] = [ index[i] ]
                out.append( add )
            out.extend( payloads[idx+1:] )
        else:
            raise ValueError("Payload to break not found in current payloads.")

        self._build_site_rows(out)
        self._update_ok_state()
        self._draw_preview()

    def _update_ok_state(self) -> None:
        ok = bool(self._letter_widgets) and all(w.is_valid() for w in self._letter_widgets)
        self.ok_btn.setEnabled(ok)

    def _on_ok(self) -> None:
        # Validate rows first
        if not all(w.is_valid() for w in self._letter_widgets):
            return

        pos_blocks: list[np.ndarray] = []
        kinds: list[int] = []
        symbols = []
        labels = []
        occupancy: Dict[int, Dict[Any, float]] = {}
        payloads = self._capture_payloads()
        start = 0

        changed = False

        atoms = self._atoms
        sprkkr = isinstance(atoms,SPRKKRAtoms)

        regions = []
        if sprkkr:
            for r in atoms.regions:
                regions.append((r, set(r.ids()), []))

        for kind, payload in enumerate(payloads):
            cart = np.dot(payload['positions'], self._cell)
            ln = len(cart)
            pos_blocks.append(cart)
            kinds.extend([kind] * ln)
            occs = payload['occupancy']
            occupancy[str(kind)] = occs
            symbol = next(iter(occs.keys()), 'X')

            o = payload.get('index')
            if not changed:
                if o is not None and np.all( np.arange(start, start+ln) == o ):
                    changed = True

            if regions is not None:
                origins = o if o is not None else payload.get('origin')
                if origins is None:
                    regions = None
                else:
                    for i,origin in enumerate(origins):
                        for r, ids, new in regions:
                            if origin in ids:
                                new.append(start+i)
            start += ln
            occs = payload['occupancy']
            symbols.extend( [symbol] * ln )
            labels.extend( f"{payload['label']}.{i}" for i in range(1,ln+1) )

        if changed:
            piter = iter(payloads)
            p = next(piter)
            if p['index'] is not None:
                new = atoms[p['index']]
            else:
                new = atoms(positions=payloads[0], cell=self._cell, pbc=True)
            for p in piter:
                if p['index'] is not None:
                    new += atoms[p['index']]
                else:
                    new += atoms(positions=p['positions'],)

        if sprkkr:
            if atoms.are_sites_inited():
                del atoms.sites
            if regions:
                for r, ids, new in regions:
                    r.copy_for_atoms(atoms, new)

        atoms.cell = self._cell
        atoms.symbols = symbols
        atoms.set_array('spacegroup_kinds', np.asarray(kinds, dtype=int))
        atoms.set_array('labels', np.asarray(labels, dtype=object))
        atoms.positions = np.vstack(pos_blocks)
        atoms.info['occupancy'] = occupancy
        self._result = atoms
        self.accept()

    def _on_back(self) -> None:
        self._result = 'back'
        self.done(42)

    def _mark_active(self, label: str, index:int=None, force=False) -> None:
        # Avoid redraw if the letter stays the same
        if not force and (label, index) == self._active_letter:
            return
        self._active_letter = (label, index)
        self._draw_preview()

    def _on_lattice_vector_changed(self, value: float) -> None:
        """Handle changes to lattice vector spinboxes."""
        # Build new cell from spinbox values
        for i in range(3):
            for j in range(3):
                self._cell[i, j] = self.lattice_spinboxes[i][j].value()

        # Redraw visualization
        self._draw_preview()

    def _draw_preview(self) -> None:
        self.ax.clear()
        lattice = self._cell
        plot_lattice(self.ax, lattice)

        # collect other vs active positions
        others = []
        active = []
        label, index = self._active_letter

        for w in self._letter_widgets:
            if label == w.label:
                if index is not None:
                    active.append( w.payload['positions'][index:index+1] )
                    others.append( w.payload['positions'][:index] )
                    others.append( w.payload['positions'][index+1:] )
                    continue
                to = active
            else:
                to = others
            to.append(w.payload['positions'])
        if others:
            plot_sites_in_lattice(self.ax, lattice, np.vstack(others), role='inactive')
        if active:
            plot_sites_in_lattice(self.ax, lattice, np.vstack(active), role='active')
        self.canvas.draw()

    # ---- error aggregation helpers ----
    def _set_site_error(self, letter: str, message: Optional[str]) -> None:
        if message:
            self._site_errors[letter] = message
        else:
            self._site_errors.pop(letter, None)
        self._update_error_label()

    def _update_error_label(self) -> None:
        self.error_label.setText("\n".join(self._site_errors.values()))


def select_site_elements(atoms:Atoms, parent: Optional[QWidget] = None,
                         back: bool = False) -> Optional[Atoms] | str:
    """
    PyQt6 element assignment dialog.

        Returns an ase.Atoms instance with:
            - positions in Cartesian coordinates
            - symbols
            - array 'spacegroup_kinds' (int per atom; a->0, b->1, ...)
            - array 'occupancy' (object array per atom: dict[AtomicType, float])
            - array 'labels' (str per atom: site labels like 'a', 'b.1', ...)
        Or 'back' or None.
    """
    key = parent if parent is not None else _DEFAULT_KEY
    dlg = _DIALOGS.get(key)
    if dlg is None:
        dlg = ElementAssignmentDialog(parent, back=back)
        _DIALOGS[key] = dlg
    else:
        dlg._allow_back = bool(back)

    dlg.setup(atoms)
    code = dlg.exec()
    if code == 42:
        return 'back'
    if code == QDialog.DialogCode.Accepted:
        return dlg._result
    return None