from __future__ import annotations

from typing import Optional, Any
import numpy as np

from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QFileDialog,
    QFormLayout,
    QDoubleSpinBox,
    QComboBox,
    QDialogButtonBox,
    QStackedWidget,
    QWidget,
    QGridLayout,
)
from PyQt6.QtCore import Qt
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from ase.io import read as ase_read

from ase2sprkkr.sprkkr.build import semiinfinite_system

from .lattice import plot_atoms_preview
from .common import chain_dialogs
from .spacegroup_selector import select_spacegroup
from .element_assignment import select_site_elements
from .structure_transform_dialogs import scale_atoms, rotate_atoms


class Build2DStructureDialog(QDialog):
    def __init__(self, atoms: Any, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Build 2D Structure")
        self.resize(1200, 760)

        self._left_atoms = atoms.copy()
        self._right_atoms: Optional[Any] = None
        self._semiinfinite_atoms: Optional[Any] = None

        root = QVBoxLayout(self)

        top = QHBoxLayout()
        root.addLayout(top, 1)

        left_group = QGroupBox("Main System")
        left_layout = QVBoxLayout(left_group)
        left_preview_row = QHBoxLayout()
        self._left_fig = Figure(figsize=(4.0, 3.2), tight_layout=True)
        self._left_canvas = FigureCanvas(self._left_fig)
        self._left_ax = self._left_fig.add_subplot(111, projection='3d')
        left_preview_row.addWidget(self._left_canvas, 1)

        left_controls = QVBoxLayout()
        self._left_scale_btn = QPushButton("Scale...")
        self._left_scale_btn.clicked.connect(self._on_scale_left)
        left_controls.addWidget(self._left_scale_btn)
        self._left_rotate_btn = QPushButton("Rotate...")
        self._left_rotate_btn.clicked.connect(self._on_rotate_left)
        left_controls.addWidget(self._left_rotate_btn)
        self._left_match_axis_btn = QPushButton("Match Other Axis")
        self._left_match_axis_btn.clicked.connect(self._on_match_left_axis)
        self._left_match_axis_btn.setEnabled(False)
        left_controls.addWidget(self._left_match_axis_btn)
        left_controls.addStretch(1)
        left_preview_row.addLayout(left_controls)

        left_layout.addLayout(left_preview_row, 1)
        left_lattice_box = QGroupBox("Lattice vectors")
        left_lattice_layout = QGridLayout(left_lattice_box)
        self._left_lattice_labels: list[list[QLabel]] = []
        for i in range(3):
            row: list[QLabel] = []
            left_lattice_layout.addWidget(QLabel(f"{chr(ord('a') + i)}:"), i, 0)
            for j in range(3):
                lbl = QLabel("–")
                lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                left_lattice_layout.addWidget(lbl, i, j + 1)
                row.append(lbl)
            self._left_lattice_labels.append(row)
        left_layout.addWidget(left_lattice_box)
        self._formula_label = QLabel("")
        left_layout.addWidget(self._formula_label)
        top.addWidget(left_group, 1)

        right_col = QVBoxLayout()
        top.addLayout(right_col, 1)

        right_group = QGroupBox("Replacement System")
        right_layout = QVBoxLayout(right_group)

        right_buttons = QHBoxLayout()
        self._load_right_btn = QPushButton("Load Structure...")
        self._load_right_btn.clicked.connect(self._on_load_right)
        right_buttons.addWidget(self._load_right_btn)

        self._create_right_btn = QPushButton("Create Structure...")
        self._create_right_btn.clicked.connect(self._on_create_right)
        right_buttons.addWidget(self._create_right_btn)

        right_layout.addLayout(right_buttons)

        self._right_stack = QStackedWidget(right_group)
        self._vacuum_label = QLabel("Vacuum")
        self._vacuum_label.setStyleSheet("font-size: 14pt; color: #666;")
        self._vacuum_label.setMinimumHeight(220)
        self._vacuum_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._right_stack.addWidget(self._vacuum_label)

        self._right_fig = Figure(figsize=(3.8, 2.8), tight_layout=True)
        self._right_canvas = FigureCanvas(self._right_fig)
        self._right_ax = self._right_fig.add_subplot(111, projection='3d')
        self._right_stack.addWidget(self._right_canvas)

        right_preview_row = QHBoxLayout()
        right_preview_row.addWidget(self._right_stack, 1)

        right_controls = QVBoxLayout()
        self._right_scale_btn = QPushButton("Scale...")
        self._right_scale_btn.clicked.connect(self._on_scale_right)
        self._right_scale_btn.setEnabled(False)
        right_controls.addWidget(self._right_scale_btn)
        self._right_rotate_btn = QPushButton("Rotate...")
        self._right_rotate_btn.clicked.connect(self._on_rotate_right)
        self._right_rotate_btn.setEnabled(False)
        right_controls.addWidget(self._right_rotate_btn)
        self._right_match_axis_btn = QPushButton("Match Other Axis")
        self._right_match_axis_btn.clicked.connect(self._on_match_right_axis)
        self._right_match_axis_btn.setEnabled(False)
        right_controls.addWidget(self._right_match_axis_btn)
        right_controls.addStretch(1)
        right_preview_row.addLayout(right_controls)

        right_layout.addLayout(right_preview_row, 1)
        right_lattice_box = QGroupBox("Lattice vectors")
        right_lattice_layout = QGridLayout(right_lattice_box)
        self._right_lattice_labels: list[list[QLabel]] = []
        for i in range(3):
            row: list[QLabel] = []
            right_lattice_layout.addWidget(QLabel(f"{chr(ord('a') + i)}:"), i, 0)
            for j in range(3):
                lbl = QLabel("–")
                lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                right_lattice_layout.addWidget(lbl, i, j + 1)
                row.append(lbl)
            self._right_lattice_labels.append(row)
        right_layout.addWidget(right_lattice_box)
        right_col.addWidget(right_group, 1)

        params_group = QGroupBox("2D Build Parameters")
        params_layout = QFormLayout(params_group)

        self._repeat_left = QDoubleSpinBox(params_group)
        self._repeat_left.setDecimals(6)
        self._repeat_left.setRange(1.0, 1e6)
        self._repeat_left.setValue(1.0)
        self._repeat_left.valueChanged.connect(self._update_result_preview)
        params_layout.addRow("Repeat left:", self._repeat_left)

        self._repeat_right = QDoubleSpinBox(params_group)
        self._repeat_right.setDecimals(6)
        self._repeat_right.setRange(1.0, 1e6)
        self._repeat_right.setValue(1.0)
        self._repeat_right.valueChanged.connect(self._update_result_preview)
        params_layout.addRow("Repeat right:", self._repeat_right)

        self._axis = QComboBox(params_group)
        self._axis.addItem("x", 0)
        self._axis.addItem("y", 1)
        self._axis.addItem("z", 2)
        self._axis.setCurrentIndex(2)
        self._axis.currentIndexChanged.connect(self._update_result_preview)
        params_layout.addRow("Axis:", self._axis)

        right_col.addWidget(params_group, 0)

        result_group = QGroupBox("Semiinfinite System")
        result_layout = QVBoxLayout(result_group)
        self._result_fig = Figure(figsize=(4.0, 3.2), tight_layout=True)
        self._result_canvas = FigureCanvas(self._result_fig)
        self._result_ax = self._result_fig.add_subplot(111, projection='3d')
        result_layout.addWidget(self._result_canvas, 1)
        root.addWidget(result_group, 1)

        self._status_label = QLabel("")
        root.addWidget(self._status_label)

        self._buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self._buttons.accepted.connect(self._on_ok)
        self._buttons.rejected.connect(self.reject)
        root.addWidget(self._buttons)

        self._ok_button = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        if self._ok_button is not None:
            self._ok_button.setEnabled(False)

        self._formula_label.setText(f"Formula: {self._left_atoms.get_chemical_formula()}")
        self._plot_structure(self._left_ax, self._left_canvas, self._left_atoms)
        self._right_stack.setCurrentIndex(0)
        self._update_lattice_panels()
        self._update_result_preview()

    def _set_status(self, message: str, *, error: bool = False) -> None:
        self._status_label.setText(message)
        if error:
            self._status_label.setStyleSheet("color: #b00020;")
        else:
            self._status_label.setStyleSheet("color: #2f6f2f;")

    def _plot_structure(self, ax, canvas, atoms: Any, *, view_axis: Optional[int] = None) -> None:
        if view_axis is None:
            plot_atoms_preview(ax, atoms, canvas=canvas, fit_to_atoms=True)
            return

        def _extra_draw(axis_obj, atoms_obj, lattice) -> None:
            if lattice is None:
                return

            axis_idx = int(view_axis)
            e1 = np.asarray(lattice[axis_idx], dtype=float)
            e1_norm = float(np.linalg.norm(e1))
            if e1_norm <= 1e-12:
                return
            e1 = e1 / e1_norm

            candidates = []
            for idx in range(3):
                if idx == axis_idx:
                    continue
                vec = np.asarray(lattice[idx], dtype=float)
                orth = vec - np.dot(vec, e1) * e1
                orth_norm = float(np.linalg.norm(orth))
                if orth_norm > 1e-12:
                    candidates.append((orth_norm, orth / orth_norm))

            if candidates:
                e2 = max(candidates, key=lambda item: item[0])[1]
            elif atoms_obj is not None:
                positions = np.asarray(atoms_obj.get_positions(), dtype=float)
                centered = positions - positions.mean(axis=0, keepdims=True)
                _, _, vh = np.linalg.svd(centered, full_matrices=False)
                candidate = np.asarray(vh[0], dtype=float)
                candidate = candidate - np.dot(candidate, e1) * e1
                cand_norm = float(np.linalg.norm(candidate))
                if cand_norm <= 1e-12:
                    return
                e2 = candidate / cand_norm
            else:
                return

            e3 = np.cross(e1, e2)
            e3_norm = float(np.linalg.norm(e3))
            if e3_norm <= 1e-12:
                return
            e3 = e3 / e3_norm

            azim = float(np.degrees(np.arctan2(e3[1], e3[0])))
            elev = float(np.degrees(np.arctan2(e3[2], np.linalg.norm(e3[:2]))))

            forward = -e3
            right = np.cross(e2, forward)
            right_norm = float(np.linalg.norm(right))
            if right_norm <= 1e-12:
                roll = 0.0
            else:
                right = right / right_norm
                up_screen = np.cross(forward, right)
                h_comp = float(np.dot(e1, right))
                v_comp = float(np.dot(e1, up_screen))
                roll = -float(np.degrees(np.arctan2(v_comp, h_comp)))

            try:
                axis_obj.view_init(elev=elev, azim=azim, roll=roll)
            except TypeError:
                axis_obj.view_init(elev=elev, azim=azim)

            try:
                axis_obj.set_proj_type('ortho')
            except Exception:
                pass

        plot_atoms_preview(
            ax,
            atoms,
            canvas=canvas,
            extra_draw=_extra_draw,
            fit_to_cell=True,
        )

    def _set_lattice_labels(self, labels: list[list[QLabel]], atoms: Optional[Any]) -> None:
        if atoms is None:
            for row in labels:
                for lbl in row:
                    lbl.setText("–")
                    lbl.setStyleSheet("")
            return

        cell = np.array(atoms.get_cell(), dtype=float)
        for i in range(3):
            for j in range(3):
                labels[i][j].setText(f"{cell[i, j]:.6f}")
                labels[i][j].setStyleSheet("")

    def _update_lattice_panels(self) -> None:
        self._set_lattice_labels(self._left_lattice_labels, self._left_atoms)
        self._set_lattice_labels(self._right_lattice_labels, self._right_atoms)

        for row in self._left_lattice_labels:
            for lbl in row:
                lbl.setStyleSheet("")
        for row in self._right_lattice_labels:
            for lbl in row:
                lbl.setStyleSheet("")

        if self._right_atoms is None:
            return

        axis = int(self._axis.currentData())
        left_vec = np.array(self._left_atoms.get_cell()[axis], dtype=float)
        right_vec = np.array(self._right_atoms.get_cell()[axis], dtype=float)

        left_norm = np.linalg.norm(left_vec)
        right_norm = np.linalg.norm(right_vec)

        matches = False
        if left_norm > 1e-12 and right_norm > 1e-12:
            left_unit = left_vec / left_norm
            right_unit = right_vec / right_norm
            same_direction = np.allclose(left_unit, right_unit, atol=1e-3)
            same_length = np.isclose(left_norm, right_norm, rtol=1e-3, atol=1e-3)
            matches = bool(same_direction and same_length)

        if not matches:
            for lbl in self._left_lattice_labels[axis]:
                lbl.setStyleSheet("color: #b00020;")
            for lbl in self._right_lattice_labels[axis]:
                lbl.setStyleSheet("color: #b00020;")

    def _on_load_right(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Load Right Structure",
            "",
            "Structure Files (*);;All Files (*)",
        )
        if not file_path:
            return
        try:
            self._right_atoms = ase_read(file_path)
            self._right_stack.setCurrentIndex(1)
            self._plot_structure(self._right_ax, self._right_canvas, self._right_atoms)
            self._right_scale_btn.setEnabled(True)
            self._right_rotate_btn.setEnabled(True)
            self._left_match_axis_btn.setEnabled(True)
            self._right_match_axis_btn.setEnabled(True)
            self._update_lattice_panels()
            self._update_result_preview()
        except Exception as e:
            self._set_status(f"Failed to load right structure: {str(e)}", error=True)

    def _on_create_right(self) -> None:
        result = chain_dialogs(
            select_spacegroup,
            select_site_elements,
            back=True,
            kwargs={'parent': self},
        )
        if result is None:
            return
        self._right_atoms = result
        self._right_stack.setCurrentIndex(1)
        self._plot_structure(self._right_ax, self._right_canvas, self._right_atoms)
        self._right_scale_btn.setEnabled(True)
        self._right_rotate_btn.setEnabled(True)
        self._left_match_axis_btn.setEnabled(True)
        self._right_match_axis_btn.setEnabled(True)
        self._update_lattice_panels()
        self._update_result_preview()

    def _on_scale_left(self) -> None:
        try:
            updated = scale_atoms(self._left_atoms, parent=self)
            if updated is None:
                return
            self._left_atoms = updated
            self._formula_label.setText(f"Formula: {self._left_atoms.get_chemical_formula()}")
            self._plot_structure(self._left_ax, self._left_canvas, self._left_atoms)
            self._update_lattice_panels()
            self._update_result_preview()
        except Exception as e:
            self._set_status(f"Scale (left) failed: {str(e)}", error=True)

    def _on_scale_right(self) -> None:
        if self._right_atoms is None:
            self._set_status("No replacement structure to scale.", error=True)
            return
        try:
            updated = scale_atoms(self._right_atoms, parent=self)
            if updated is None:
                return
            self._right_atoms = updated
            self._plot_structure(self._right_ax, self._right_canvas, self._right_atoms)
            self._update_lattice_panels()
            self._update_result_preview()
        except Exception as e:
            self._set_status(f"Scale (right) failed: {str(e)}", error=True)

    def _on_rotate_left(self) -> None:
        try:
            updated = rotate_atoms(self._left_atoms, parent=self)
            if updated is None:
                return
            self._left_atoms = updated
            self._plot_structure(self._left_ax, self._left_canvas, self._left_atoms)
            self._update_lattice_panels()
            self._update_result_preview()
        except Exception as e:
            self._set_status(f"Rotate (left) failed: {str(e)}", error=True)

    def _on_rotate_right(self) -> None:
        if self._right_atoms is None:
            self._set_status("No replacement structure to rotate.", error=True)
            return
        try:
            updated = rotate_atoms(self._right_atoms, parent=self)
            if updated is None:
                return
            self._right_atoms = updated
            self._plot_structure(self._right_ax, self._right_canvas, self._right_atoms)
            self._update_lattice_panels()
            self._update_result_preview()
        except Exception as e:
            self._set_status(f"Rotate (right) failed: {str(e)}", error=True)

    def _stretch_axis_to_other(self, source: Any, target: Any) -> Any:
        axis = int(self._axis.currentData())
        source_cell = np.array(source.get_cell(), dtype=float)
        target_cell = np.array(target.get_cell(), dtype=float)

        source_vec = source_cell[axis]
        target_vec = target_cell[axis]
        source_len = float(np.linalg.norm(source_vec))
        target_len = float(np.linalg.norm(target_vec))
        if source_len <= 1e-12 or target_len <= 1e-12:
            raise ValueError("Selected axis has near-zero length and cannot be stretched.")

        source_unit = source_vec / source_len
        source_cell[axis] = source_unit * target_len

        result = source.copy()
        result.set_cell(source_cell, scale_atoms=True)
        return result

    def _on_match_left_axis(self) -> None:
        if self._right_atoms is None:
            self._set_status("No replacement structure to match against.", error=True)
            return
        try:
            self._left_atoms = self._stretch_axis_to_other(self._left_atoms, self._right_atoms)
            self._plot_structure(self._left_ax, self._left_canvas, self._left_atoms)
            self._update_lattice_panels()
            self._update_result_preview()
        except Exception as e:
            self._set_status(f"Match axis (left) failed: {str(e)}", error=True)

    def _on_match_right_axis(self) -> None:
        if self._right_atoms is None:
            self._set_status("No replacement structure to match against.", error=True)
            return
        try:
            self._right_atoms = self._stretch_axis_to_other(self._right_atoms, self._left_atoms)
            self._plot_structure(self._right_ax, self._right_canvas, self._right_atoms)
            self._update_lattice_panels()
            self._update_result_preview()
        except Exception as e:
            self._set_status(f"Match axis (right) failed: {str(e)}", error=True)

    def _update_result_preview(self) -> None:
        self._result_ax.clear()
        self._semiinfinite_atoms = None
        self._update_lattice_panels()
        if self._ok_button is not None:
            self._ok_button.setEnabled(False)

        try:
            left_repeat = float(self._repeat_left.value())
            right_repeat = float(self._repeat_right.value())
            repeat = (left_repeat, right_repeat)
            axis = int(self._axis.currentData())
            atoms2 = self._right_atoms.copy() if self._right_atoms is not None else None
            semi = semiinfinite_system(self._left_atoms.copy(), repeat=repeat, atoms2=atoms2, axis=axis)
            self._semiinfinite_atoms = semi
            self._plot_structure(self._result_ax, self._result_canvas, semi, view_axis=axis)
            self._set_status("Preview ready.")
            if self._ok_button is not None:
                self._ok_button.setEnabled(True)
        except Exception as e:
            self._result_ax.clear()
            self._result_ax.set_axis_off()
            message = str(e) if str(e) else type(e).__name__
            self._result_ax.text(
                0.5,
                0.5,
                f"Preview error:\n{message}",
                ha='center',
                va='center',
                wrap=True,
                transform=self._result_ax.transAxes,
            )
            self._result_canvas.draw_idle()
            self._set_status(f"Preview error: {str(e)}", error=True)

    def _on_ok(self) -> None:
        if self._semiinfinite_atoms is None:
            self._set_status("Cannot accept: no valid semiinfinite system.", error=True)
            return
        self.accept()

    def result_atoms(self) -> Optional[Any]:
        if self._semiinfinite_atoms is None:
            return None
        return self._semiinfinite_atoms.copy()

def select_build_2d_structure(atoms: Any, parent: Optional[QWidget] = None) -> Optional[Any]:
    dialog = Build2DStructureDialog(atoms, parent=parent)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return dialog.result_atoms()
