"""Wyckoff-position selection and free-coordinate controls."""
from itertools import chain, zip_longest
from typing import List

from PyQt6.QtCore import QEvent, QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QCheckBox, QDoubleSpinBox, QGridLayout, QLabel, QWidget


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
