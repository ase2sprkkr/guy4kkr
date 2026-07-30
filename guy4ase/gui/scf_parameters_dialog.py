"""Compact, guided editor for the most important SPR-KKR SCF parameters."""
from __future__ import annotations

from typing import Any, Optional
from pathlib import Path

import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ase2sprkkr.input_parameters.input_parameters import InputParameters

from .input_parameters_dialog import edit_input_parameters
from .parameter_tooltips import parameter_tooltip


class GuidedScfParametersDialog(QDialog):
    """Edit common SCF settings without exposing the complete input schema."""

    def __init__(
        self,
        params: InputParameters,
        atoms: Any,
        parent: Optional[QWidget] = None,
        *,
        directory: Optional[str] = None,
    ):
        super().__init__(parent)
        self._params = params
        self._atoms = atoms
        self._directory = directory or ''
        self._is_2d = self._detect_2d(atoms)
        self._rows: list[tuple[Any, QWidget]] = []

        self.setWindowTitle("SCF Calculation Setup")
        self.resize(860, 560)

        root = QVBoxLayout(self)
        intro = QLabel(
            "Configure the settings that most often affect the physical model, convergence, "
            "and numerical accuracy. Specialized parameters remain available in Expert settings."
        )
        if self._is_2d:
            intro.setText(
                intro.text() + " For a 2D system, one SCF run automatically converges the left bulk, "
                "the right bulk when distinct, and finally the interaction zone."
            )
        intro.setWordWrap(True)
        root.addWidget(intro)

        directory_row = QWidget(self)
        directory_layout = QHBoxLayout(directory_row)
        directory_layout.setContentsMargins(0, 0, 0, 0)
        directory_layout.addWidget(QLabel("Working directory:"))
        self._directory_edit = QLineEdit(self._directory, directory_row)
        self._directory_edit.setPlaceholderText("Select a calculation directory")
        directory_layout.addWidget(self._directory_edit, 1)
        choose_directory = QPushButton("Browse…", directory_row)
        choose_directory.clicked.connect(self._choose_directory)
        directory_layout.addWidget(choose_directory)
        root.addWidget(directory_row)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        content = QWidget(scroll)
        columns = QHBoxLayout(content)
        columns.setContentsMargins(4, 4, 4, 4)
        columns.setSpacing(12)
        left = QVBoxLayout()
        right = QVBoxLayout()
        columns.addLayout(left, 1)
        columns.addLayout(right, 1)

        left.addWidget(self._build_physical_model_group())
        left.addWidget(self._build_initial_potential_group())
        left.addStretch(1)
        right.addWidget(self._build_convergence_group())
        right.addWidget(self._build_accuracy_group())
        right.addStretch(1)

        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel, parent=self)
        calculate = QPushButton("Calculate", self)
        calculate.setIcon(QIcon(str(Path(__file__).resolve().parent.parent / "assets" / "icons" / "system-run.svg")))
        buttons.addButton(calculate, QDialogButtonBox.ButtonRole.AcceptRole)
        load = QPushButton("Load input…", self)
        buttons.addButton(load, QDialogButtonBox.ButtonRole.ActionRole)
        expert = QPushButton("Expert settings…", self)
        buttons.addButton(expert, QDialogButtonBox.ButtonRole.ActionRole)
        load.clicked.connect(self._load_input)
        expert.clicked.connect(self._open_expert_settings)
        calculate.clicked.connect(self._accept_values)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._load_values()

    @staticmethod
    def _detect_2d(atoms: Any) -> bool:
        try:
            return not all(bool(value) for value in atoms.get_pbc())
        except Exception:
            return False

    def _option(self, section: str, option: str) -> Any:
        return getattr(getattr(self._params, section), option)

    def _label(
        self,
        text: str,
        tooltip: str,
    ) -> QLabel:
        label = QLabel(text)
        label.setToolTip(tooltip)
        return label

    def _add_row(
        self,
        form: QFormLayout,
        text: str,
        section: str,
        option: str,
        editor: QWidget,
    ) -> QWidget:
        tooltip = parameter_tooltip(
            self._option(section, option),
            section,
            option,
            text,
        )
        editor.setToolTip(tooltip)
        form.addRow(self._label(text, tooltip), editor)
        self._rows.append(((section, option), editor))
        return editor

    def _keyword_combo(self, section: str, option: str, *, include_default: bool = False) -> QComboBox:
        combo = QComboBox(self)
        opt = self._option(section, option)
        if include_default:
            combo.addItem("Fully relativistic (default)", None)
        grammar = opt._definition.grammar_type
        for keyword, description in grammar.items():
            combo.addItem(str(keyword), keyword)
            index = combo.count() - 1
            if description:
                combo.setItemData(index, str(description), Qt.ItemDataRole.ToolTipRole)
        return combo

    @staticmethod
    def _integer_editor(minimum: int, maximum: int, step: int = 1) -> QSpinBox:
        editor = QSpinBox()
        editor.setRange(minimum, maximum)
        editor.setSingleStep(step)
        editor.setKeyboardTracking(False)
        return editor

    @staticmethod
    def _real_editor(minimum: float, maximum: float, step: float, decimals: int = 6) -> QDoubleSpinBox:
        editor = QDoubleSpinBox()
        editor.setDecimals(decimals)
        editor.setRange(minimum, maximum)
        editor.setSingleStep(step)
        editor.setKeyboardTracking(False)
        return editor

    def _build_physical_model_group(self) -> QGroupBox:
        group = QGroupBox("Physical model", self)
        form = QFormLayout(group)

        self._vxc = self._keyword_combo("SCF", "VXC")
        self._add_row(form, "Exchange-correlation:", "SCF", "VXC", self._vxc)

        self._mode = self._keyword_combo("MODE", "MODE", include_default=True)
        self._add_row(form, "Relativity and spin:", "MODE", "MODE", self._mode)

        self._nonmag = QCheckBox("Treat as known non-magnetic system", group)
        self._add_row(form, "Magnetism:", "CONTROL", "NONMAG", self._nonmag)

        self._fullpot = QCheckBox("Use full-potential calculation", group)
        self._add_row(form, "Potential shape:", "SCF", "FULLPOT", self._fullpot)

        self._krmt = self._integer_editor(0, 10)
        self._krmt.setSpecialValueText("Automatic")
        self._add_row(form, "Muffin-tin radius scheme:", "CONTROL", "KRMT", self._krmt)
        return group

    def _build_initial_potential_group(self) -> QGroupBox:
        group = QGroupBox("Initial potential", self)
        form = QFormLayout(group)
        self._initial = QComboBox(group)
        self._initial.addItem("Atomic charge density (recommended)", False)
        self._initial.addItem("Mattheiss potential", True)
        self._add_row(form, "Starting guess:", "SCF", "USEVMATT", self._initial)

        note = QLabel("Per-type ionic charge and spin-moment guesses are available in Expert settings.")
        note.setWordWrap(True)
        note.setStyleSheet("color: palette(mid);")
        form.addRow(note)
        return group

    def _build_convergence_group(self) -> QGroupBox:
        group = QGroupBox("SCF convergence and mixing", self)
        form = QFormLayout(group)

        self._niter = self._integer_editor(1, 2000, 10)
        self._add_row(form, "Maximum iterations:", "SCF", "NITER", self._niter)

        self._tol = self._real_editor(1e-10, 1.0, 1e-6, 10)
        self._add_row(form, "Convergence tolerance:", "SCF", "TOL", self._tol)

        self._alg = self._keyword_combo("SCF", "ALG")
        self._add_row(form, "Mixing algorithm:", "SCF", "ALG", self._alg)

        self._mix = self._real_editor(0.001, 1.0, 0.01, 4)
        self._add_row(form, "Mixing factor:", "SCF", "MIX", self._mix)

        self._istbry = self._integer_editor(1, 100)
        self._add_row(form, "Start Broyden after:", "SCF", "ISTBRY", self._istbry)

        self._itdept = self._integer_editor(1, 500)
        self._add_row(form, "Broyden history length:", "SCF", "ITDEPT", self._itdept)
        self._alg.currentIndexChanged.connect(self._update_algorithm_controls)
        return group

    def _build_accuracy_group(self) -> QGroupBox:
        title = "Numerical accuracy (2D)" if self._is_2d else "Numerical accuracy"
        group = QGroupBox(title, self)
        form = QFormLayout(group)

        self._bzint = self._keyword_combo("TAU", "BZINT")
        self._add_row(form, "BZ integration:", "TAU", "BZINT", self._bzint)

        self._kkrmode = self._keyword_combo("TAU", "KKRMODE", include_default=True)
        self._add_row(form, "KKR representation:", "TAU", "KKRMODE", self._kkrmode)

        self._kpoint_editors: list[tuple[str, QSpinBox]] = []
        if self._is_2d:
            for option, label in (("NKTAB2D", "2D-region k-points:"), ("NKTAB3D", "3D-region k-points:")):
                editor = self._integer_editor(1, 100000, 10)
                self._add_row(form, label, "TAU", option, editor)
                self._kpoint_editors.append((option, editor))
        else:
            editor = self._integer_editor(1, 100000, 10)
            self._add_row(form, "Special k-points:", "TAU", "NKTAB", editor)
            self._kpoint_editors.append(("NKTAB", editor))

        self._energy_points = self._integer_editor(4, 1000, 2)
        self._add_row(form, "Energy-mesh points:", "ENERGY", "NE", self._energy_points)

        self._energy_grid = self._integer_editor(1, 10)
        self._add_row(form, "Energy contour grid:", "ENERGY", "GRID", self._energy_grid)

        self._imaginary_energy = self._real_editor(0.0, 10.0, 0.001)
        self._add_row(form, "Imaginary energy (Ry):", "ENERGY", "ImE", self._imaginary_energy)

        self._cluster_radius = self._real_editor(0.0, 100.0, 0.1)
        self._cluster_radius.setSpecialValueText("Automatic")
        self._add_row(form, "Cluster radius:", "TAU", "CLURAD", self._cluster_radius)

        self._nl = self._integer_editor(1, 8)
        self._add_row(form, "Angular-momentum cutoff:", "SITES", "NL", self._nl)
        return group

    @staticmethod
    def _first_value(value: Any, fallback: Any) -> Any:
        if isinstance(value, np.ndarray):
            return value.flat[0] if value.size else fallback
        if isinstance(value, (list, tuple)):
            return value[0] if value else fallback
        return fallback if value is None else value

    @staticmethod
    def _set_combo(combo: QComboBox, value: Any) -> None:
        for index in range(combo.count()):
            if combo.itemData(index) == value:
                combo.setCurrentIndex(index)
                return

    def _load_values(self) -> None:
        self._set_combo(self._vxc, self._option("SCF", "VXC")())
        self._set_combo(self._mode, self._option("MODE", "MODE")())
        self._nonmag.setChecked(bool(self._option("CONTROL", "NONMAG")()))
        self._fullpot.setChecked(bool(self._option("SCF", "FULLPOT")()))
        self._krmt.setValue(int(self._option("CONTROL", "KRMT")() or 0))
        self._set_combo(self._initial, bool(self._option("SCF", "USEVMATT")()))

        self._niter.setValue(int(self._option("SCF", "NITER")()))
        self._tol.setValue(float(self._option("SCF", "TOL")()))
        self._set_combo(self._alg, self._option("SCF", "ALG")())
        self._mix.setValue(float(self._option("SCF", "MIX")()))
        self._istbry.setValue(int(self._option("SCF", "ISTBRY")()))
        self._itdept.setValue(int(self._option("SCF", "ITDEPT")()))

        self._set_combo(self._bzint, self._option("TAU", "BZINT")())
        self._set_combo(self._kkrmode, self._option("TAU", "KKRMODE")())
        for option, editor in self._kpoint_editors:
            editor.setValue(int(self._option("TAU", option)()))
        self._energy_points.setValue(int(self._first_value(self._option("ENERGY", "NE")(), 32)))
        self._energy_grid.setValue(int(self._first_value(self._option("ENERGY", "GRID")(), 5)))
        self._imaginary_energy.setValue(float(self._option("ENERGY", "ImE")()))
        self._cluster_radius.setValue(float(self._option("TAU", "CLURAD")() or 0.0))
        self._nl.setValue(int(self._first_value(self._option("SITES", "NL")(), 3)))
        self._update_algorithm_controls()

    def _update_algorithm_controls(self, *_args: Any) -> None:
        enabled = self._alg.currentData() == "BROYDEN2"
        self._istbry.setEnabled(enabled)
        self._itdept.setEnabled(enabled)

    def _apply_values(self) -> None:
        values = (
            ("SCF", "VXC", self._vxc.currentData()),
            ("MODE", "MODE", self._mode.currentData()),
            ("CONTROL", "NONMAG", self._nonmag.isChecked()),
            ("SCF", "FULLPOT", self._fullpot.isChecked()),
            ("CONTROL", "KRMT", self._krmt.value() or None),
            ("SCF", "USEVMATT", self._initial.currentData()),
            ("SCF", "NITER", self._niter.value()),
            ("SCF", "TOL", self._tol.value()),
            ("SCF", "ALG", self._alg.currentData()),
            ("SCF", "MIX", self._mix.value()),
            ("SCF", "ISTBRY", self._istbry.value()),
            ("SCF", "ITDEPT", self._itdept.value()),
            ("TAU", "BZINT", self._bzint.currentData()),
            ("TAU", "KKRMODE", self._kkrmode.currentData()),
            ("ENERGY", "NE", self._energy_points.value()),
            ("ENERGY", "GRID", self._energy_grid.value()),
            ("ENERGY", "ImE", self._imaginary_energy.value()),
            ("TAU", "CLURAD", self._cluster_radius.value() or None),
            ("SITES", "NL", self._nl.value()),
        )
        for section, option, value in values:
            self._option(section, option).set(value)
        for option, editor in self._kpoint_editors:
            self._option("TAU", option).set(editor.value())

    def _accept_values(self) -> None:
        try:
            self._apply_values()
        except Exception as exc:
            QMessageBox.critical(self, "Invalid SCF Settings", str(exc))
            return
        self._directory = self._directory_edit.text().strip()
        if not self._directory and not self._choose_directory():
            return
        self.accept()

    def _choose_directory(self) -> bool:
        selected = QFileDialog.getExistingDirectory(
            self,
            "Select Calculation Directory",
            self._directory_edit.text().strip(),
        )
        if not selected:
            return False
        self._directory = str(selected)
        self._directory_edit.setText(self._directory)
        return True

    def _open_expert_settings(self) -> None:
        try:
            self._apply_values()
            candidate = self._params.copy(copy_values=True)
            selection = edit_input_parameters(
                candidate,
                parent=self,
                calculate_mode=True,
                directory=self._directory_edit.text().strip(),
                return_directory=True,
            )
        except Exception as exc:
            QMessageBox.critical(self, "SCF Settings Error", str(exc))
            return
        if selection is not None:
            self._params, self._directory = selection
            self._directory_edit.setText(self._directory)
            self.accept()

    def _load_input(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Load SPRKKR Input File",
            "",
            "SPRKKR Input Files (*.inp *.in *.txt);;All Files (*)",
        )
        if not file_path:
            return
        try:
            loaded = InputParameters.from_file(file_path)
            selection = edit_input_parameters(
                loaded,
                parent=self,
                show_changed_only=True,
                calculate_mode=True,
                directory=self._directory_edit.text().strip(),
                return_directory=True,
            )
        except Exception as exc:
            QMessageBox.critical(self, "Load Error", f"Failed to load input parameters:\n{exc}")
            return
        if selection is not None:
            self._params, self._directory = selection
            self._directory_edit.setText(self._directory)
            self.accept()

    def result(self) -> tuple[InputParameters, str]:
        return self._params, self._directory


def select_guided_scf_parameters(
    atoms: Any,
    parent: Optional[QWidget] = None,
    *,
    directory: Optional[str] = None,
) -> Optional[tuple[InputParameters, str]]:
    from ase2sprkkr.input_parameters.definitions.scf import input_parameters

    params = input_parameters().create_object()
    dialog = GuidedScfParametersDialog(params, atoms, parent=parent, directory=directory)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return dialog.result()
