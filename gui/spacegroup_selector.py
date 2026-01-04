from __future__ import annotations

from typing import Optional, Dict, Any, List

from PyQt6.QtCore import Qt, QTimer, QSignalBlocker, QObject, QEvent, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QLineEdit,
    QTableWidget, QTableWidgetItem, QPushButton, QWidget,
    QSplitter, QGroupBox, QScrollArea, QCheckBox, QGridLayout, QSizePolicy,
    QHeaderView, QDoubleSpinBox
)
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from contextlib import contextmanager
from pyxtal.symmetry import Group
from weakref import WeakKeyDictionary
from itertools import zip_longest, chain
from ase.cell import Cell

from .lattice import plot_lattice, plot_sites_in_lattice
from ..physics.pyxtal_utils import complete_lattice_params, lattice_from_params,\
                                   lattice_default_params, lattice_fixed_params,\
                                   WyckoffPosition
from .common import create_units_combo, QDoubleEdit

_DIALOGS = WeakKeyDictionary()

class _GlobalSentinel:
    pass

_DEFAULT_KEY = _GlobalSentinel()


class SpaceGroupSelectorDialog(QDialog):
    def __init__(self, parent: Optional[QWidget] = None, back: bool = False):
        """Initialize dialog state, caches, and build the UI layout.

        Parameters
        ----------
        parent
            Optional parent widget hosting the dialog.
        back
            Enables the Back button when True so the dialog can return a sentinel value.

        Attributes
        ----------
        _allow_back
            Whether the Back button is shown and active.
        selected_group
            Currently loaded ``pyxtal`` group or ``None`` when no selection exists.
        lattice_params
            User-entered lattice parameter values gathered from the input widgets.
        units
            Conversion factor applied to the lattice when rendering.
        wyckoff_positions
            Sorted cache of Wyckoff position objects for the active group.
        _draw_counter
            Monotonically increasing token used to drop stale draw requests.
        _focused_letter
            Wyckoff label under mouse/keyboard focus, used for hover highlighting.
        _mouse_over_letter
            Wyckoff label currently being mouseovered, used for hover highlighting.
        _sg_cache
            Lazy cache of table rows containing space-group metadata for filtering.
        _filter_timer
            Debounce timer that postpones table filtering while the user types.
        _selected_sites
            Persistent Wyckoff DOF values remembered across dialog openings.
        """
        super().__init__(parent)
        self.setWindowTitle("Select Space Group")
        self.resize(1100, 700)
        self._allow_back = bool(back)
        self.selected_group: Optional[Group] = None
        self.wyckoff_positions: dict[str, WyckoffPosition] = {}
        self.lattice_params: Dict[str, float] = {}
        self.units: float = 1.0
        self._draw_counter = 0
        self._mouse_over_letter: Optional[str] = None
        self._focused_letter: Optional[str] = None
        # Cached space-group rows for fast filtering: (id, symbol, lattice, hay)
        self._sg_cache: Optional[List[tuple]] = None
        # Debounce for search typing
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.timeout.connect(self._populate_table)
        self._selected_sites: Dict[str, list[list[float]]] = {}
        # Durable user-entered lattice memory (not cleared when params become fixed)
        self._wyckoff_widgets = {}
        self._build_ui()
        self._populate_table()

    def _safe_signal_block(self, widget):
        """Context manager to safely block signals with fallback."""
        @contextmanager
        def blocker():
            b = QSignalBlocker(widget)
            yield b

        return blocker()

    def _build_ui(self) -> None:
        """Build the three-pane layout and connect top-level signals."""
        root = QVBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter, 1)

        # Left pane
        left = QWidget()
        left.setMinimumWidth(325)
        left_v = QVBoxLayout(left)
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("System:"))
        self.system_combo = QComboBox()
        self.system_combo.addItems(["All", "triclinic", "monoclinic", "orthorhombic", "tetragonal", "trigonal", "hexagonal", "cubic"])
        self.system_combo.currentIndexChanged.connect(self._populate_table)
        filter_row.addWidget(self.system_combo)
        filter_row.addSpacing(12)
        filter_row.addWidget(QLabel("Search:"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("ID / symbol / lattice…")
        self.search_edit.textChanged.connect(self._debounce_table_filter)
        filter_row.addWidget(self.search_edit, 1)
        left_v.addLayout(filter_row)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["ID", "Symbol", "Lattice"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 60)

        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

        left_v.addWidget(self.table, 1)
        splitter.addWidget(left)
        # Make ID column narrower


        # Middle pane
        middle = QWidget()
        middle_v = QVBoxLayout(middle)
        wy_group = QGroupBox("Wyckoff sites positions (multiplicity)")
        middle_v.addWidget(wy_group, 1)
        wy_v = QVBoxLayout(wy_group)
        self.wy_scroll = QScrollArea()
        wy_v.addWidget(self.wy_scroll)

        self.wy_scroll.setWidgetResizable(True)
        self.wy_container = QWidget()
        self.wy_scroll.setWidget(self.wy_container)
        self.wy_container.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

        self.wy_layout = QVBoxLayout(self.wy_container)
        self.wy_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.wy_scroll.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.wy_layout.setSpacing(2)

        # Ensure middle column is wide enough to show up to three DOF inputs by default
        splitter.addWidget(middle)
        middle.setMinimumWidth(500)

        # Right pane
        right = QWidget()
        right_v = QVBoxLayout(right)
        lat_group = QGroupBox("Lattice parameters")
        lat_grid = QGridLayout(lat_group)
        lat_grid.setColumnStretch(0, 0)
        lat_grid.setColumnStretch(1, 0)  # keep inputs left; no stretch to center
        lat_grid.setColumnStretch(2, 0)
        lat_grid.setColumnStretch(3, 0)
        lat_grid.setColumnStretch(4, 0)
        lat_grid.setColumnStretch(5, 0)
        lat_grid.setHorizontalSpacing(12)
        self._lat_vars: Dict[str, Any] = {}

        # Ensure all lattice edit boxes have identical width
        _lat_edit_w = 110

        def add_lat_line(key: str, row: int, col: int, min_val: float, max_val: float, decimals: int = 6):
            lab = QLabel(f"{key}:")
            lat_grid.addWidget(lab, row, col)

            le = QDoubleEdit(min_val, max_val, decimals)
            le.setFixedWidth(_lat_edit_w)
            le.textChanged.connect(lambda str, k=key, le=le: self._on_lattice_value(k, le.value()))
            lat_grid.addWidget(le, row, col + 1)
            self._lat_vars[key] = le

        add_lat_line("a", 0, 0, 0.0, 1e9, 6)
        add_lat_line("b", 0, 2, 0.0, 1e9, 6)
        add_lat_line("c", 0, 4, 0.0, 1e9, 6)
        add_lat_line("α", 1, 0, 0.0, 180.0, 3)
        add_lat_line("β", 1, 2, 0.0, 180.0, 3)
        add_lat_line("γ", 1, 4, 0.0, 180.0, 3)
        lat_grid.addWidget(QLabel("Units:"), 2, 0)
        units_combo = create_units_combo(lat_group, self._on_units_changed)
        lat_grid.addWidget(units_combo, 2, 1, 1, 2)
        right_v.addWidget(lat_group, 0)

        self.fig = Figure(figsize=(5, 5))
        self.ax = self.fig.add_subplot(111, projection='3d')
        self.canvas = FigureCanvas(self.fig)
        right_v.addWidget(self.canvas, 1)

        mat_group = QGroupBox("Lattice vectors (Å)")
        mat_grid = QGridLayout(mat_group)
        self.lattice_labels: List[List[QLabel]] = []
        for i in range(3):
            row_labels: List[QLabel] = []
            for j in range(3):
                lbl = QLabel("–")
                lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                mat_grid.addWidget(lbl, i, j)
                row_labels.append(lbl)
            self.lattice_labels.append(row_labels)
        right_v.addWidget(mat_group, 0)
        splitter.addWidget(right)
        # Initial splitter sizes: left table, middle wyckoff, right preview
        try:
            splitter.setStretchFactor(0, 0)
            splitter.setStretchFactor(1, 1)
            splitter.setStretchFactor(2, 2)
            splitter.setSizes([300, 520, 560])
        except Exception:
            pass

        # Error/status label (like Tk version): shows what is missing to continue
        self.error_label = QLabel("")
        # Larger, prominent error message spanning the whole right column
        self.error_label.setStyleSheet("color: #ff4d4d; font-size: 13pt; font-weight: 600;")
        # Do not wrap; let it span full width and grow vertically only if necessary
        self.error_label.setWordWrap(False)
        self.error_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        # Bottom area: align error label above buttons in the right (third) column
        bottom_h = QHBoxLayout()
        bottom_h.addStretch(1)  # consume left & middle space
        right_bottom_v = QVBoxLayout()
        right_bottom_v.addWidget(self.error_label)
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        if self._allow_back:
            self.back_btn = QPushButton("Back")
            self.back_btn.clicked.connect(self._on_back)
            btn_row.addWidget(self.back_btn)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self.cancel_btn)
        self.ok_btn = QPushButton("OK")
        self.ok_btn.setEnabled(False)
        self.ok_btn.clicked.connect(self._on_ok)
        btn_row.addWidget(self.ok_btn)
        right_bottom_v.addLayout(btn_row)
        bottom_h.addLayout(right_bottom_v)
        root.addLayout(bottom_h)

        self.table.itemSelectionChanged.connect(self._on_selection_changed)

    def _on_selection_changed(self) -> None:
        """Load the currently selected space group and rebuild dependent UI."""
        row = self.table.currentRow()
        if row < 0:
            self.selected_group = None
            self.ok_btn.setEnabled(False)
            return
        sg_no = int(self.table.item(row, 0).text())
        # Record previously fixed params before switching

        self.selected_group = Group(sg_no)
        wps = sorted(self.selected_group.Wyckoff_positions, key=lambda wp: wp.letter)
        self.wyckoff_positions = { wp.letter: WyckoffPosition(wp) for wp in wps}

        self._rebuild_wyckoff_panel()
        self._update_lattice_constraints()
        # If some params were fixed previously but are now free, restore user value if remembered, else clear
        self._on_lattice_changed()
        self._update_ok_state()

    def _on_ok(self) -> None:
        """Accept the dialog when the current selection passes validation."""
        if not self._is_valid():
            return
        self.accept()

    def _on_back(self) -> None:
        """Return a sentinel value indicating the Back action."""
        self.selected_group = -1
        self.done(42)

    def _populate_table(self) -> None:
        """Populate the table widget with cached space-group metadata."""
        # Build cache on first use
        if self._sg_cache is None:
            cache: List[tuple] = []
            for i in range(1, 231):
                g = Group(i)
                sym = g.symbol
                lat = g.lattice_type
                hay = f"{i} {sym} {lat}".lower()
                cache.append((i, sym, lat, hay))
            self._sg_cache = cache

        system = self.system_combo.currentText()
        search = self.search_edit.text().strip().lower()
        rows: List[tuple] = []
        for i, sym, lat, hay in self._sg_cache:
            if system != "All" and system != lat:
                continue
            if search and search not in hay:
                continue
            rows.append((i, sym, lat))
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for r, (i, sym, lat) in enumerate(rows):
            # First column: use numeric DisplayRole for proper numeric sorting
            id_item = QTableWidgetItem()
            id_item.setData(Qt.ItemDataRole.DisplayRole, int(i))
            self.table.setItem(r, 0, id_item)
            # Other columns remain textual
            self.table.setItem(r, 1, QTableWidgetItem(sym))
            self.table.setItem(r, 2, QTableWidgetItem(str(lat)))
        self.table.setSortingEnabled(True)
        # Default sort by the first column (space group number), ascending
        try:
            self.table.sortItems(0, Qt.SortOrder.AscendingOrder)
        except Exception:
            pass
        if rows:
            self.table.selectRow(0)
        else:
            self.ok_btn.setEnabled(False)

    def _debounce_table_filter(self) -> None:
        """Debounce search input before refreshing the table view."""

        try:
            self._filter_timer.start(150)
        except Exception:
            self._populate_table()

    def _on_lattice_value(self, key: str, val: float) -> None:
        """Persist lattice text edits and trigger downstream updates."""
        self.lattice_params[key] = val
        self._on_lattice_changed()

    def _on_units_changed(self, factor: float) -> None:
        """Apply a new unit conversion factor and update the preview."""
        self.units = float(factor)
        self._on_lattice_changed()

    def _update_lattice_constraints(self) -> None:
        """Lock or unlock lattice inputs based on system-specific rules."""
        if not self.selected_group:
            return
        system = self.selected_group.lattice_type
        fixed = lattice_fixed_params.get(system, {})

        for key, w in self._lat_vars.items():
            with self._safe_signal_block(w):
                if key in fixed:
                    w.setEnabled(False)
                    w.setText(str(fixed[key]))
                else:
                    w.setEnabled(True)
                    w.setText(str(self.lattice_params.get(key, "")))

    def _is_lattice_defined(self) -> bool:
        """Return True when all required lattice inputs contain valid numbers."""
        if not self.selected_group:
            return False
        system = self.selected_group.lattice_type
        fixed = lattice_fixed_params.get(system, {})
        for key in lattice_default_params:
            if key in fixed:
                continue
            val = self._lat_vars[key].value()
            if not val:
                return False
        return True

    def _on_lattice_changed(self) -> None:
        """Recompute the lattice matrix and refresh previews after edits."""
        if not self.selected_group:
            return
        params = complete_lattice_params(self.selected_group, self.lattice_params)
        try:
            self.lattice = lattice_from_params(params) * self.units
        except Exception:
            self.lattice = False
        self._update_lattice_matrix()
        self._schedule_draw()
        self._update_ok_state()

    def _update_lattice_matrix(self) -> None:
        """Update the lattice vector labels with the latest matrix values."""
        lat = getattr(self, 'lattice', False)
        if lat is False or not self._is_lattice_defined():
            for i in range(3):
                for j in range(3):
                    self.lattice_labels[i][j].setText("–")
            return
        for i in range(3):
            for j in range(3):
                self.lattice_labels[i][j].setText(f"{lat[i, j]:8.3f}")

    def _update_degeneracy_warnings(self, q) -> None:
        vals = q.value
        wp = self.wyckoff_positions[q.letter]
        p = wp.position_for_free_dofs(vals)
        dofs = wp.n_dofs
        degen = []
        for other in self.wyckoff_positions.values():
            if other.n_dofs < dofs and other.is_the_same_position(p):
                degen.append(other.letter)
        if degen:
            message = "⚠️ Degenerate with: " + ", ".join(sorted(degen))
            q.set_warning(message)
        else:
            q.clear_warning()

    def _rebuild_wyckoff_panel(self, focus=(None, None)) -> None:
        """Rebuild Wyckoff sites UI.
        For letters with degrees of freedom (free axes), show duplicates a1,a2,... (checked) plus one
        trailing placeholder (unchecked) to allow adding a new variant with different coordinates.
        Single fixed letters remain one row.
        """
        for i in range(self.wy_layout.count()-1, -1, -1):
            item = self.wy_layout.itemAt(i)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

        self._mouse_over_letter = None, None
        self._focused_letter = None, None
        self._wyckoff_widgets = {}

        for wp in self.wyckoff_positions.values():
            values = self._selected_sites.get(wp.letter, [])
            if wp.n_dofs == 0:
                values = bool(values)
                self._add_wyckoff_checkbox(wp, 0, values)
            else:
                for i, v in enumerate(values):
                    self._add_wyckoff_checkbox(wp, i, v)
                self._add_wyckoff_checkbox(wp, len(values), False)

    def _add_wyckoff_checkbox(self, wp, index, value):
        q = WyckoffPositionWidget(wp, index, value, self.wy_container)
        self._wyckoff_widgets[(wp.letter, index)] = q
        self.wy_layout.addWidget(q)

        def toggled(checked, letter, index, Q=q):
            vals = self._selected_sites.setdefault(letter, [])
            if checked:
                if index >= len(vals):
                    vals.append([0.0] * wp.n_dofs)
                else:
                    vals[index] = Q.value
            else:
                vals.pop(index)
            if q.type != 'SINGLE':
                self._rebuild_wyckoff_panel()
                n = self._wyckoff_widgets.get((letter, index))
                if n:
                    n.setFocus()

            self._schedule_draw()
            self._update_ok_state()

        def spin(letter: str, index: int, values: list) -> None:
            """Persist a DOF duplicate coordinate change and refresh highlights."""
            self._selected_sites[letter][index] = values
            self._active_letter = f"{letter}.{index+1}"
            self._update_degeneracy_warnings(q)
            self._schedule_draw()

        def focus(letter: Optional[str], index: Optional[int], active: bool) -> None:
            """Update the hovered/focused letter and refresh the preview."""
            if ((letter, index) == self._focused_letter) == active:
                return
            self._focused_letter = (letter, index) if active else (None, None)
            self._schedule_draw()

        def mouse_over(letter: Optional[str], index: Optional[int]) -> None:
            """Update the hovered/focused letter and refresh the preview."""
            if (letter, index) == self._mouse_over_letter:
                return
            self._mouse_over_letter = (letter, index) if letter else (None, None)
            self._schedule_draw()

        q.mouse_over.connect(mouse_over)
        q.focus_changed.connect(focus)
        q.checkbox_toggled.connect(toggled)
        q.spin_value_changed.connect(spin)
        if q.type != 'PLACEHOLDER':
            self._update_degeneracy_warnings(q)

    def _next_draw_token(self) -> int:
        """Return a new draw token used to discard stale plot requests."""
        self._draw_counter += 1
        return self._draw_counter

    def _capture_draw_state(self, token: int) -> Optional[Dict[str, Any]]:
        """Capture lattice and Wyckoff state for downstream plotting."""
        if not self.selected_group:
            return None
        # Determine lattice for drawing: prefer user-defined, else default preview lattice
        lat = getattr(self, 'lattice', False)
        if lat is False:
            try:
                # Build preview params from defaults + user partial + fixed constraints
                params = dict(lattice_default_params)
                params.update(self.lattice_params)
                system = self.selected_group.lattice_type
                fixed = lattice_fixed_params.get(system, {})
                params.update(fixed)
                lat = lattice_from_params(params) * self.units
            except Exception:
                return None

        return {
            'token': token,
            'lattice': lat,
            'sites': self._selected_sites.copy(),
            'wp': self.wyckoff_positions,
            'mouse_over_letter': self._mouse_over_letter,
            'focused_letter': self._focused_letter,
        }

    def _schedule_draw(self) -> None:
        """Queue a redraw of the 3D lattice preview using the latest state."""
        token = self._next_draw_token()
        snap = self._capture_draw_state(token)
        if snap is None:
            def clear_latest(tok=token):
                if tok != self._draw_counter:
                    return
                self.ax.clear()
                self.canvas.draw()
            QTimer.singleShot(0, clear_latest)
            return

        def compute_and_apply(req=snap):
            tok = req['token']
            if tok != self._draw_counter:
                return

            lattice = req['lattice']
            sites = req['sites']
            wps = req['wp']
            highligh = req['mouse_over_letter'] if req['mouse_over_letter'][0] else req['focused_letter']

            inactive_positions = []
            focused_positions = []
            active_positions = []

            focused = None
            for wp in wps.values():
                vals = sites.get(wp.letter, [])
                if highligh[0] == wp.letter and (highligh[1] >= len(vals)):
                    focused_positions.append(wp.all_positions_for_free_dofs([]))
                for i, value in enumerate(vals):
                    if highligh[0] == wp.letter and (highligh[1] == i):
                        to = active_positions
                    else:
                        to = inactive_positions
                    to.append(wp.all_positions_for_free_dofs(value))

            self.ax.clear()
            plot_lattice(self.ax, lattice)
            for arr in inactive_positions:
                plot_sites_in_lattice(self.ax, lattice, arr, role='inactive')
            for arr in focused_positions:
                plot_sites_in_lattice(self.ax, lattice, arr, role='focused')
            for arr in active_positions:
                plot_sites_in_lattice(self.ax, lattice, arr, role='active')
            self.canvas.draw()

        QTimer.singleShot(0, compute_and_apply)

    def _is_any_position_selected(self) -> bool:
        """Return True if any Wyckoff checkbox (duplicate or single) is checked."""
        # Any checked checkbox (duplicate or single) counts as selection
        for k in self.wyckoff_positions:
            if self._selected_sites.get(k):
                return True
        return False

    def _is_valid(self) -> bool:
        """Validate that lattice values exist and at least one site is chosen."""
        return bool(self.selected_group) and getattr(self, 'lattice', False) is not False and self._is_lattice_defined() and self._is_any_position_selected()

    def _update_ok_state(self) -> None:
        """Enable the OK button when selection state is complete."""
        valid = self._is_valid()
        self.ok_btn.setEnabled(valid)
        self._update_error_label()

    # Error/status messaging to guide user to completion
    def _update_error_label(self) -> None:
        """Refresh the inline helper message with the latest validation text."""
        self.error_label.setText(self._validation_message())

    def _validation_message(self) -> str:
        """Describe the next required user action, or return an empty string."""
        if not self.selected_group:
            return "Select a space group."
        if not self._is_lattice_defined():
            # Determine which length parameters are still missing
            fixed = lattice_fixed_params.get(self.selected_group.lattice_type, {})
            missing = []
            for key in lattice_default_params:
                if key in fixed:
                    continue
                txt = self._lat_vars[key].text().strip()
                if not txt:
                    missing.append(key)
            if missing:
                items = ", ".join(missing)
                return f"Specify lattice parameters: {items}."
            return "Specify valid (positive) lattice parameters."
        if not self._is_any_position_selected():
            return "Select at least one Wyckoff site."
        return ""


def select_spacegroup(parent: Optional[QWidget] = None, back: bool = False,
                      **kwargs: Any) -> Optional[Dict[str, Any]] | str:
    """
    PyQt6 version of the spacegroup selector. Returns:
      - {'spacegroup': int, 'cell': ase.Cell, 'wyckoff_positions': dict} on OK
      - 'back' if Back is enabled and pressed
      - None on cancel
    """
    key = parent if parent is not None else _DEFAULT_KEY
    try:
        dlg = _DIALOGS.get(key)
    except Exception:
        dlg = None
    if dlg is None or not isinstance(dlg, SpaceGroupSelectorDialog):
        dlg = SpaceGroupSelectorDialog(parent, back=back)
        _DIALOGS[key] = dlg
    else:
        dlg._allow_back = bool(back)

    result = dlg.exec()
    if result == 42:
        return 'back'
    if result == QDialog.DialogCode.Accepted:
        sg = dlg.selected_group
        lat = getattr(dlg, 'lattice', None)
        positions = {}
        if sg is not None:
            for letter, wp in dlg.wyckoff_positions.items():
                vals = dlg._selected_sites.get(letter, [])
                for i, val in enumerate(vals):
                    label = letter
                    if len(vals) > 1:
                        label = f"{letter}.{i + 1}"
                    positions[label] = wp.all_positions_for_free_dofs(val)
        cell_obj = Cell(lat) if lat is not None and lat is not False else None
        return {'spacegroup': int(sg.number) if sg else None, 'cell': cell_obj, 'wyckoff_positions': positions}
    return None


class WyckoffPositionWidget(QWidget):
    # Custom signals
    checkbox_toggled = pyqtSignal(bool, str, int)
    spin_value_changed = pyqtSignal(str, int, list)  # spin_index, new_value
    mouse_over = pyqtSignal(str, int)
    focus_changed = pyqtSignal(str, int, bool)

    def __init__(self, wp, index=0, value=[], parent=None):
        super().__init__(parent)
        self.letter = wp.letter
        self.index = index
        label = self.letter
        dof = wp.n_dofs

        if dof:
            if value is False:
                self.type = 'PLACEHOLDER'
                self.__dict__['value'] = [0.0] * dof
            else:
                self.type = 'MULTIPLE'
                label += f".{index + 1}"
        else:
            self.type = 'SINGLE'

        label = f"{label} ({wp.multiplicity}): {wp.dof_description}"

        # Layout
        layout = QGridLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setHorizontalSpacing(4)
        layout.setVerticalSpacing(0)
        layout.setRowMinimumHeight(1, 0)

        # Column 0: checkbox
        self.checkbox = QCheckBox(label)
        self.checkbox.setChecked(bool(value))
        layout.addWidget(self.checkbox, 0, 0)
        self.checkbox.toggled.connect(self.on_checkbox_toggled)

        # Columns 1–6: spinboxes with labels
        self.spinboxes = []
        self.spin_labels_widgets = []

        class _FocusFilter(QObject):

            def __init__(self, widget):
                super().__init__(widget)
                self.widget = widget
                self.focused = 0

            def eventFilter(self, obj, event):
                et = event.type()

                if et == QEvent.Type.FocusIn:
                    self.focused += 1
                    self.widget.focus_changed.emit(self.widget.letter, index, True)
                elif et == QEvent.Type.FocusOut:
                    self.focused -= 1

                    def really_leave(focus_count=self.focused):
                        if self.focused > 0:
                            return
                        self.widget.focus_changed.emit(self.widget.letter, index, False)
                    QTimer.singleShot(0, really_leave)

                return False

        ff = _FocusFilter(self)
        self.checkbox.installEventFilter(ff)

        if self.type == 'MULTIPLE':
            col = 1
            for letter, val in zip_longest(wp.dof_labels, value, fillvalue=0.0):
                if letter == 0.0:
                    break
                lbl = QLabel(f"{letter} =")
                lbl.setFixedWidth(18)  # <-- fixed width for any single-letter label
                layout.addWidget(lbl, 0, col)
                self.spin_labels_widgets.append(lbl)
                col += 1

                spin = QDoubleSpinBox()
                spin.setFixedWidth(60)
                spin.setRange(0.0, 1.0)
                spin.setSingleStep(0.05)
                spin.setDecimals(4)   # IMPORTANT: must allow 2 decimals
                spin.setValue(val)
                spin.installEventFilter(ff)
                spin.valueChanged.connect(self.on_spin_changed)
                layout.addWidget(spin, 0, col)
                self.spinboxes.append(spin)
                col += 1

        # Enable mouse tracking for enter/leave events
        if self.type != 'PLACEHOLDER':
            lbl = QLabel("", self)
            self.warn_label = lbl
            lbl.setStyleSheet("color: #d18900; font-size: 11px; margin-left: 26px;")
            lbl.setWordWrap(True)
            lbl.setVisible(False)
            layout.addWidget(lbl, 1, 0, 1, 10)

        self.setMouseTracking(True)

    @property
    def value(self) -> List[float]:
        return [sp.value() for sp in self.spinboxes]

    def set_warning(self, message):
        self.warn_label.setText(message)
        self.warn_label.setVisible(True)

    def clear_warning(self):
        self.warn_label.setVisible(False)

    def on_checkbox_toggled(self, checked: bool):
        for i in chain(
            self.spin_labels_widgets,
            self.spinboxes
            ):
            i.setEnabled(checked)
        self.checkbox_toggled.emit(checked, self.letter, self.index)

    def on_spin_changed(self, value: int):
        self.spin_value_changed.emit(self.letter, self.index, self.value)

    def focus_first_spinbox(self) -> None:
        """Focus the first DOF spinbox """
        self.spinboxes[0].setFocus(Qt.FocusReason.OtherFocusReason)

    def enterEvent(self, event):
        self.mouse_over.emit(self.letter, self.index)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.mouse_over.emit("", -1)
        super().leaveEvent(event)