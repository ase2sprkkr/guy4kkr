"""Reusable editable tree renderer for expert ``InputParameters``."""
from __future__ import annotations

from collections.abc import Callable
from collections.abc import Sequence as AbcSequence
from typing import Any

import numpy as np
from ase2sprkkr.common.configuration_containers import Section
from ase2sprkkr.common.grammar_types import Array, SetOf, String, Table
from ase2sprkkr.common.grammar_types import Sequence as GrammarSequence
from PyQt6 import sip
from PyQt6.QtCore import QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStyle,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from guy4ase.gui.input_parameters.bindings import (
    InputParametersBinding,
    resolve_option,
)
from guy4ase.gui.input_parameters.expert_fields import (
    ExpertFieldSpec,
    applicable_expert_fields,
)
from guy4ase.gui.input_parameters.field_binding import DirectFieldBinding, FieldValue
from guy4ase.gui.input_parameters.specs.schema import FieldPlacement
from guy4ase.gui.widgets.input_parameters.modal_editor import (
    ExpertFieldEditorDialog,
)
from guy4ase.gui.widgets.input_parameters.registry import create_editor
from guy4ase.gui.widgets.input_parameters.value_editor import ParameterValueEditor


def _mutable_sequence(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, AbcSequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    return [value]


def _reverse_names_map(names: Any, size: int) -> list[str]:
    labels = [f"[{i}]" for i in range(size)]
    if isinstance(names, dict):
        for name, index in names.items():
            if isinstance(index, int) and 0 <= index < size:
                labels[index] = str(name)
    return labels


def _option_value(opt: Any) -> Any:
    try:
        return opt.get()
    except Exception:  # noqa: BLE001 - generated getters may fail while incomplete.
        return getattr(opt, "_value", None)


def _all_option_values(opt: Any) -> Any:
    """Return the outer repeated value instead of one effective occurrence."""
    try:
        return opt(all_values=True)
    except Exception:  # noqa: BLE001 - generated getters may fail while incomplete.
        return getattr(opt, "_value", None)


class ExpertInputTreeEditor(QWidget):
    """Render and edit one externally owned InputParameters document."""

    validationChanged = pyqtSignal(bool)
    _CHANGED_ROLE = Qt.ItemDataRole.UserRole
    _RELATED_PATHS_ROLE = Qt.ItemDataRole.UserRole + 1
    _VALUE_EDITOR_ROLE = Qt.ItemDataRole.UserRole + 2
    _ARRAY_ITEMS_ROLE = Qt.ItemDataRole.UserRole + 3

    def __init__(
        self,
        parameters_getter: Callable[[], Any],
        *,
        atoms: Any = None,
        show_changed_only: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._parameters_getter = parameters_getter
        self._atoms = atoms
        self._declared_editors = {}
        self._editor_errors = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        header = QHBoxLayout()
        header.addWidget(QLabel("Search:"))
        self.filter_edit = QLineEdit(self)
        self.filter_edit.setPlaceholderText("Filter by name…")
        header.addWidget(self.filter_edit, 1)
        clear_button = QPushButton("Clear", self)
        header.addWidget(clear_button)
        self.changed_only_checkbox = QCheckBox("Show changed only", self)
        header.addWidget(self.changed_only_checkbox)
        header.addStretch(1)
        expand_button = QPushButton("Expand all", self)
        collapse_button = QPushButton("Collapse all", self)
        header.addWidget(expand_button)
        header.addWidget(collapse_button)
        layout.addLayout(header)

        self.tree = QTreeWidget(self)
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels(["Name", "Type", "Value", "", "Comment"])
        self.tree.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.tree.setColumnWidth(0, 300)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(
            3,
            QHeaderView.ResizeMode.ResizeToContents,
        )
        self.tree.header().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.tree, 1)

        self.error_label = QLabel(self)
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        layout.addWidget(self.error_label)

        self.filter_edit.textChanged.connect(self.apply_filter)
        clear_button.clicked.connect(self.clear_filter)
        self.changed_only_checkbox.toggled.connect(
            lambda _checked: self.apply_filter(self.filter_edit.text())
        )
        expand_button.clicked.connect(self.tree.expandAll)
        collapse_button.clicked.connect(self.tree.collapseAll)
        self.changed_only_checkbox.setChecked(show_changed_only)
        self.rebuild()

    @property
    def parameters(self) -> Any:
        return self._parameters_getter()

    @property
    def has_errors(self) -> bool:
        return bool(self._editor_errors)

    @property
    def error_text(self) -> str:
        return self.error_label.text()

    def set_show_changed_only(self, enabled: bool) -> None:
        self.changed_only_checkbox.setChecked(enabled)

    def clear_filter(self) -> None:
        self.filter_edit.clear()
        self.filter_edit.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def apply_filter(self, text: str) -> None:
        self._apply_filter(text)

    def _add_child(
        self,
        parent: QTreeWidgetItem | None,
        child: QTreeWidgetItem,
    ) -> None:
        if parent is None:
            self.tree.addTopLevelItem(child)
        else:
            parent.addChild(child)

    def commit_pending(self) -> bool:
        """Commit every live value editor and reveal the first invalid draft."""
        focus = QApplication.focusWidget()
        if focus is not None:
            focus.clearFocus()
        for item, editor in self._editor_widgets():
            if editor is None or sip.isdeleted(editor) or sip.isdeleted(item):
                continue
            if not editor.commit():
                self.filter_edit.clear()
                self.changed_only_checkbox.setChecked(False)
                parent = item.parent()
                while parent is not None:
                    parent.setExpanded(True)
                    parent = parent.parent()
                self.tree.scrollToItem(item)
                editor.setFocus()
                return False
        return not self.has_errors

    def rebuild(self) -> None:
        self._declared_editors = {}
        self._field_specs = applicable_expert_fields(self.parameters)
        self._suppressed_paths = frozenset(
            related_path
            for spec in self._field_specs.values()
            for related_path in spec.related_paths
        )
        self._editor_errors = {}
        self.error_label.clear()
        self.error_label.hide()
        self.tree.clear()
        self._build_section(self.parameters)
        self.tree.expandAll()
        self._collapse_array_items()
        self._apply_filter(self.filter_edit.text())
        self.validationChanged.emit(self.has_errors)

    def _collapse_array_items(self) -> None:
        """Start component-level array rows collapsed without limiting Expand all."""
        def visit(item: QTreeWidgetItem) -> None:
            if item.data(0, self._ARRAY_ITEMS_ROLE):
                item.setExpanded(False)
            for index in range(item.childCount()):
                visit(item.child(index))

        visit(self.tree.invisibleRootItem())

    def _apply_filter(self, text: str) -> None:
        needle = (text or '').strip().lower()
        changed_only = self.changed_only_checkbox.isChecked()

        def visit(item: QTreeWidgetItem) -> bool:
            self_match = not needle or needle in (item.text(0) or '').lower()
            own_changed = bool(item.data(0, self._CHANGED_ROLE))
            child_visible = False
            for index in range(item.childCount()):
                child_visible = visit(item.child(index)) or child_visible

            has_children = item.childCount() > 0
            changed_match = not changed_only or own_changed or child_visible
            visible = (self_match and changed_match) or child_visible
            if has_children and changed_only and not own_changed and not child_visible:
                visible = False
            item.setHidden(not visible)
            return visible

        for index in range(self.tree.topLevelItemCount()):
            visit(self.tree.topLevelItem(index))

    def _build_section(
        self,
        parent: Any,
        treeitem: QTreeWidgetItem | None = None,
    ) -> None:
        expert_parent: QTreeWidgetItem | None = None

        def get_expert_parent() -> QTreeWidgetItem:
            nonlocal expert_parent
            if expert_parent is None:
                expert_parent = QTreeWidgetItem([
                    "expert", "", "", "", "Expert options",
                ])
                self._add_child(treeitem, expert_parent)
            return expert_parent

        for opt in parent:
            if isinstance(opt, Section):
                info = opt.info
                sec_item = QTreeWidgetItem([opt.name, "", "", "", info])
                sec_item.setToolTip(4, info)
                font = sec_item.font(0)
                font.setBold(True)
                sec_item.setFont(0, font)
                self._add_child(treeitem, sec_item)
                self._build_section(opt, sec_item)
                continue

            path = tuple(opt._get_path().split('.'))
            if path in self._suppressed_paths:
                continue

            parent_item = get_expert_parent() if bool(getattr(opt._definition, 'expert', False)) else treeitem
            self._build_option(opt, parent_item, path)

    def _build_option(
        self,
        opt: Any,
        parent_item: QTreeWidgetItem | None,
        path: tuple[str, ...],
    ) -> None:
        grammar_type = opt._definition.type
        info = opt.info
        type_text = str(grammar_type)
        item = QTreeWidgetItem([opt.name, type_text, '', '', info])
        item.setToolTip(1, type_text)
        item.setToolTip(4, info)
        self._add_child(parent_item, item)
        self._update_changed_style(opt, item, refresh_filter=False)

        spec = self._field_specs.get(path)
        if spec is not None and spec.small_editor is not None:
            self._build_compact_declared_option(opt, item, path, spec)
        elif spec is not None:
            self._build_declared_option(opt, item, path, spec)
        elif opt._definition.is_repeated:
            self._build_repeated_option(opt, item, grammar_type)
        elif isinstance(grammar_type, (Array, SetOf)):
            self._build_array_option(opt, item, grammar_type)
        elif isinstance(grammar_type, GrammarSequence):
            self._build_sequence_option(opt, item, grammar_type)
        elif isinstance(grammar_type, Table):
            self._build_table_option(opt, item, grammar_type)
        else:
            self._install_value_editor(
                opt,
                item,
                FieldPlacement(path, opt.name),
                error_label='.'.join(path),
            )

    def _direct_binding(
        self,
        opt,
        item,
        placement,
        *,
        read_value=None,
        apply_value=None,
        value_type=None,
        allows_unset=None,
        read_only=False,
        allow_empty=False,
        cache_applied=True,
    ):
        def changed(_path):
            self._update_changed_style(opt, item)
            self._refresh_declared_editors()

        model = InputParametersBinding(lambda: self.parameters, changed)
        return DirectFieldBinding(
            model,
            placement,
            read_value=read_value,
            apply_value=apply_value,
            value_type=value_type,
            allows_unset=allows_unset,
            read_only=read_only,
            allow_empty=allow_empty,
            cache_applied=cache_applied,
        )

    def _install_value_editor(
        self,
        opt,
        item,
        placement,
        *,
        read_value=None,
        apply_value=None,
        value_type=None,
        allows_unset=None,
        read_only=False,
        allow_empty=False,
        cache_applied=True,
        error_label=None,
    ):
        binding = self._direct_binding(
            opt,
            item,
            placement,
            read_value=read_value,
            apply_value=apply_value,
            value_type=value_type,
            allows_unset=allows_unset,
            read_only=read_only,
            allow_empty=allow_empty,
            cache_applied=cache_applied,
        )
        editor = create_editor(binding, placement, atoms=self._atoms, parent=self.tree)
        self._set_editor(item, editor, error_label)
        item.setSizeHint(2, editor.sizeHint())
        return editor

    def _build_declared_option(
        self,
        opt: Any,
        item: QTreeWidgetItem,
        path: tuple[str, ...],
        spec: ExpertFieldSpec,
    ) -> None:
        """Apply Qt-independent expert metadata to one registered editor."""
        placement = spec.placement(path, opt.name)
        item.setText(0, placement.label)
        item.setData(0, self._RELATED_PATHS_ROLE, placement.related_paths)
        if spec.type_label is not None:
            item.setText(1, spec.type_label)
        descriptions = [opt.info]
        descriptions.extend(
            resolve_option(self.parameters, related_path).info
            for related_path in placement.related_paths
        )
        item.setToolTip(4, '\n'.join(filter(None, descriptions)))
        editor = self._install_value_editor(
            opt,
            item,
            placement,
            error_label='.'.join(path),
        )
        self._declared_editors[placement.path] = (editor, item)
        if spec.minimum_width is not None:
            editor.setMinimumWidth(spec.minimum_width)
            self.tree.setColumnWidth(
                2,
                max(spec.minimum_width, self.tree.columnWidth(2)),
            )
        editor.refresh()
        self._update_changed_style(opt, item, refresh_filter=False)

    def _build_compact_declared_option(
        self,
        opt: Any,
        item: QTreeWidgetItem,
        path: tuple[str, ...],
        spec: ExpertFieldSpec,
    ) -> None:
        """Use a compact tree editor and expose the full editor modally."""
        placement = spec.placement(
            path,
            opt.name,
            editor=spec.small_editor,
        )
        item.setText(0, placement.label)
        if spec.type_label is not None:
            item.setText(1, spec.type_label)
        if opt._definition.is_repeated:
            self._build_repeated_option(
                opt,
                item,
                opt._definition.type,
                editor_name=spec.small_editor,
            )
        else:
            self._install_value_editor(
                opt,
                item,
                placement,
                error_label='.'.join(path),
            )

        self._install_full_editor_button(opt, item, path, spec)

    def _open_full_editor(
        self,
        opt: Any,
        item: QTreeWidgetItem,
        path: tuple[str, ...],
        spec: ExpertFieldSpec,
    ) -> None:
        dialog = ExpertFieldEditorDialog(
            self.parameters,
            path,
            spec,
            atoms=self._atoms,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        opt.set(dialog.value)
        self._update_changed_style(opt, item)
        inline_editor = self.tree.itemWidget(item, 2)
        if isinstance(inline_editor, ParameterValueEditor):
            inline_editor.refresh()
        self._rebuild_compound_option(opt, item)
        self._install_full_editor_button(opt, item, path, spec)

    def _install_full_editor_button(
        self,
        opt: Any,
        item: QTreeWidgetItem,
        path: tuple[str, ...],
        spec: ExpertFieldSpec,
    ) -> None:
        button = QToolButton(self.tree)
        button.setAutoRaise(True)
        button.setIcon(self.style().standardIcon(
            QStyle.StandardPixmap.SP_FileDialogDetailedView
        ))
        button.setToolTip(f"Open full editor for {'.'.join(path)}")
        button.setAccessibleName(f"Open full editor for {'.'.join(path)}")
        button.clicked.connect(
            lambda _checked=False, o=opt, tree_item=item, p=path, s=spec:
                self._open_full_editor(o, tree_item, p, s)
        )
        self.tree.setItemWidget(item, 3, button)

    def _refresh_declared_editors(self):
        for editor, _item in self._declared_editors.values():
            editor.refresh()

    def _update_changed_style(
        self,
        opt: Any,
        item: QTreeWidgetItem,
        *,
        refresh_filter: bool = True,
    ) -> None:
        try:
            changed = bool(opt.is_changed())
            related_paths = item.data(0, self._RELATED_PATHS_ROLE) or ()
            changed = changed or any(
                resolve_option(self.parameters, path).is_changed()
                for path in related_paths
            )
        except Exception:  # noqa: BLE001 - presentation must survive partial values.
            changed = False
        item.setData(0, self._CHANGED_ROLE, changed)
        font = item.font(0)
        font.setBold(changed)
        item.setFont(0, font)
        if refresh_filter:
            self._apply_filter(self.filter_edit.text())

    def _clear_children(self, item: QTreeWidgetItem) -> None:
        while item.childCount():
            item.removeChild(item.child(0))

    def _rebuild_compound_option(self, opt: Any, item: QTreeWidgetItem) -> None:
        self._clear_children(item)
        grammar_type = opt._definition.grammar_type
        if opt._definition.is_repeated:
            self._build_repeated_option(opt, item, grammar_type)
        elif isinstance(grammar_type, (Array, SetOf)):
            self._build_array_option(opt, item, grammar_type)
        elif isinstance(grammar_type, GrammarSequence):
            self._build_sequence_option(opt, item, grammar_type)
        elif isinstance(grammar_type, Table):
            self._build_table_option(opt, item, grammar_type)

    def _build_summary_editor(self, opt: Any, item: QTreeWidgetItem, grammar_type: Any, *, editable: bool) -> None:
        """Show a compound value's grammar text alongside its structured child editors."""
        def apply(value):
            opt.set(value)
            self._update_changed_style(opt, item)
            self._rebuild_compound_option(opt, item)
        placement = FieldPlacement(tuple(opt._get_path().split('.')), opt.name)
        editor = self._install_value_editor(
            opt,
            item,
            placement,
            apply_value=apply,
            value_type=grammar_type,
            read_only=not editable,
        )
        item.setToolTip(2, editor.text())

    def _set_editor(self, item, editor, error_label=None):
        """Install a control and surface value-editor validation uniformly."""
        if not isinstance(editor, ParameterValueEditor):
            raise TypeError("Expert value controls must implement ParameterValueEditor")
        item.setData(0, self._VALUE_EDITOR_ROLE, True)
        self.tree.setItemWidget(item, 2, editor)
        editor.validationChanged.connect(
            lambda message: self._display_editor_error(
                item, error_label or item.text(0), message))

    def _display_editor_error(self, item, label, message):
        key = id(item)
        if message:
            self._editor_errors[key] = (item, label, message)
        else:
            self._editor_errors.pop(key, None)
        self._refresh_editor_errors()

    def _refresh_editor_errors(self):
        self._editor_errors = {
            key: (item, label, error)
            for key, (item, label, error) in self._editor_errors.items()
            if not sip.isdeleted(item)
        }
        messages = [
            f"{label}: {error}"
            for _item, label, error in self._editor_errors.values()
        ]
        self.error_label.setText('\n'.join(messages))
        self.error_label.setVisible(bool(messages))
        self.validationChanged.emit(bool(messages))

    def _editor_widgets(self):
        """Snapshot registered value editors; a commit may rebuild child rows."""
        def walk(item):
            if item.data(0, self._VALUE_EDITOR_ROLE):
                yield item, self.tree.itemWidget(item, 2)
            for index in range(item.childCount()):
                yield from walk(item.child(index))
        return list(walk(self.tree.invisibleRootItem()))

    def _build_repeated_option(
        self,
        opt: Any,
        item: QTreeWidgetItem,
        grammar_type: Any,
        *,
        editor_name: str = "auto",
    ) -> None:
        """Render the repetition outside the grammar for one occurrence.

        DEFAULTDICT's unnumbered occurrence belongs on the option row.  Its
        explicitly numbered overrides are child rows.  Other repetition modes
        have no distinguished default occurrence, so every occurrence is a
        child row.
        """
        repetition = opt._definition.is_repeated
        path = tuple(opt._get_path().split('.'))
        all_values = _all_option_values(opt)

        if repetition.is_dict:
            values = all_values if isinstance(all_values, dict) else {}
            default_item_editors = []

            def read_default() -> FieldValue:
                stored = getattr(opt, "_value", None)
                default_is_explicit = (
                    isinstance(stored, dict) and "def" in stored
                )
                default_value = self._repeated_occurrence_value(
                    opt,
                    "def",
                    is_dict=True,
                )
                return FieldValue(
                    default_value,
                    opt.default_value,
                    implicit_default=(
                        not default_is_explicit and default_value is not None
                    ),
                    explicit=default_is_explicit,
                )

            def apply_default(value: Any) -> None:
                self._update_repeated_dict_value(opt, item, "def", value)
                for component_editor in default_item_editors:
                    component_editor.refresh()

            default_editor = self._install_value_editor(
                opt,
                item,
                FieldPlacement(path, opt.name, editor=editor_name),
                read_value=read_default,
                apply_value=apply_default,
                value_type=grammar_type,
                allows_unset=True,
                cache_applied=False,
                error_label='.'.join(path),
            )
            if isinstance(grammar_type, (Array, SetOf)):
                default_items = QTreeWidgetItem([
                    'Default items',
                    str(grammar_type.type),
                    '',
                    '',
                    'Items of the default value',
                ])
                default_items.setData(0, self._ARRAY_ITEMS_ROLE, True)
                self._add_child(item, default_items)
                default_item_editors.extend(self._add_repeated_array_items(
                    opt,
                    item,
                    default_items,
                    grammar_type,
                    "def",
                    is_dict=True,
                    occurrence_editor=default_editor,
                ))

            numbered_keys = sorted(key for key in values if key != "def")
            for key in numbered_keys:
                self._add_repeated_child(
                    opt,
                    item,
                    path,
                    grammar_type,
                    key,
                    values[key],
                    is_dict=True,
                    editor_name=editor_name,
                )

            numbered = [key for key in numbered_keys if isinstance(key, int)]
            next_key = max(numbered, default=0) + 1
            self._add_repeated_child(
                opt,
                item,
                path,
                grammar_type,
                next_key,
                None,
                is_dict=True,
                append=True,
                editor_name=editor_name,
            )
            return

        values = _mutable_sequence(all_values)
        summary = f"<{len(values)} value{'s' if len(values) != 1 else ''}>"
        item.setText(2, summary)
        item.setToolTip(2, summary)
        summary_label = QLabel(summary)
        summary_label.setToolTip(summary)
        self.tree.setItemWidget(item, 2, summary_label)
        for index, value in enumerate(values):
            self._add_repeated_child(
                opt,
                item,
                path,
                grammar_type,
                index,
                value,
                is_dict=False,
                editor_name=editor_name,
            )
        self._add_repeated_child(
            opt,
            item,
            path,
            grammar_type,
            len(values),
            None,
            is_dict=False,
            append=True,
            editor_name=editor_name,
        )

    def _add_repeated_child(
        self,
        opt: Any,
        item: QTreeWidgetItem,
        path: tuple[str, ...],
        grammar_type: Any,
        key: Any,
        value: Any,
        *,
        is_dict: bool,
        append: bool = False,
        editor_name: str = "auto",
    ) -> None:
        display_index = key if is_dict else key + 1
        child = QTreeWidgetItem([
            f'[{display_index}]',
            str(grammar_type),
            '',
            '',
            'Add numbered value' if append else '',
        ])
        self._add_child(item, child)
        placement = FieldPlacement(
            path,
            child.text(0),
            editor=editor_name,
            special_value_text="Add value…" if append else None,
        )
        update = (
            self._update_repeated_dict_value
            if is_dict
            else self._update_repeated_array_value
        )
        component_editors = []

        def apply_occurrence(new_value: Any) -> None:
            update(opt, item, key, new_value)
            for component_editor in component_editors:
                component_editor.refresh()

        editor = self._install_value_editor(
            opt,
            child,
            placement,
            read_value=lambda: FieldValue(
                self._repeated_occurrence_value(opt, key, is_dict=is_dict)
            ),
            apply_value=apply_occurrence,
            value_type=grammar_type,
            allows_unset=True,
            allow_empty=append,
            cache_applied=False,
            error_label=f"{'.'.join(path)}[{display_index}]",
        )
        if append:
            if isinstance(editor, QLineEdit):
                editor.setPlaceholderText("Add value…")
            elif hasattr(editor, "setSpecialValueText"):
                editor.setSpecialValueText("Add value…")
            return

        if isinstance(grammar_type, (Array, SetOf)):
            child.setData(0, self._ARRAY_ITEMS_ROLE, True)
            component_editors.extend(self._add_repeated_array_items(
                opt,
                item,
                child,
                grammar_type,
                key,
                is_dict=is_dict,
                occurrence_editor=editor,
            ))

        remove_button = QToolButton(self.tree)
        remove_button.setAutoRaise(True)
        remove_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogCloseButton)
        )
        remove_button.setToolTip(f"Remove repeated value {display_index}")
        remove_button.setAccessibleName(
            f"Remove {'.'.join(path)} repeated value {display_index}"
        )
        remove_button.clicked.connect(
            lambda _checked=False, o=opt, parent_item=item, k=key: update(
                o, parent_item, k, None
            )
        )
        self.tree.setItemWidget(child, 3, remove_button)

    def _repeated_occurrence_value(
        self,
        opt: Any,
        key: Any,
        *,
        is_dict: bool,
    ) -> Any:
        values = _all_option_values(opt)
        if is_dict:
            values = values if isinstance(values, dict) else {}
            if key == "def":
                return values.get("def", opt.default_value)
            return values.get(key)
        values = _mutable_sequence(values)
        return values[key] if key < len(values) else None

    def _add_repeated_array_items(
        self,
        opt: Any,
        repeated_item: QTreeWidgetItem,
        occurrence_item: QTreeWidgetItem,
        grammar_type: Any,
        key: Any,
        *,
        is_dict: bool,
        occurrence_editor: ParameterValueEditor,
    ) -> list[ParameterValueEditor]:
        """Add editors for the components of one array-valued occurrence."""
        values = _mutable_sequence(
            self._repeated_occurrence_value(opt, key, is_dict=is_dict)
        )
        minimum_length = getattr(grammar_type, 'min_length', None)
        maximum_length = getattr(grammar_type, 'max_length', None)
        fixed_length = minimum_length is not None and minimum_length == maximum_length
        staged_values = list(values)
        if fixed_length:
            staged_values.extend([None] * (minimum_length - len(staged_values)))

        editors = []

        def component_value(index: int) -> Any:
            current = _mutable_sequence(
                self._repeated_occurrence_value(opt, key, is_dict=is_dict)
            )
            return current[index] if index < len(current) else staged_values[index]

        def apply_component(index: int, new_value: Any) -> None:
            current = _mutable_sequence(
                self._repeated_occurrence_value(opt, key, is_dict=is_dict)
            )
            working = current or list(staged_values)
            while len(working) <= index:
                working.append(None)
            working[index] = new_value
            staged_values[:] = working
            if fixed_length and any(value is None for value in working):
                return
            update = (
                self._update_repeated_dict_value
                if is_dict
                else self._update_repeated_array_value
            )
            update(opt, repeated_item, key, working)
            occurrence_editor.refresh()

        for index, value in enumerate(staged_values):
            component = QTreeWidgetItem([
                f'[{index}]',
                str(grammar_type.type),
                '',
                '',
                '',
            ])
            self._add_child(occurrence_item, component)
            placement = FieldPlacement(
                tuple(opt._get_path().split('.')),
                component.text(0),
            )
            editors.append(self._install_value_editor(
                opt,
                component,
                placement,
                read_value=lambda idx=index: FieldValue(component_value(idx)),
                apply_value=lambda new_value, idx=index: apply_component(
                    idx, new_value
                ),
                value_type=grammar_type.type,
                allows_unset=fixed_length and value is None,
                cache_applied=False,
            ))
        return editors

    def _update_repeated_dict_value(
        self,
        opt: Any,
        item: QTreeWidgetItem,
        key: Any,
        value: Any,
    ) -> None:
        current = _all_option_values(opt)
        current = dict(current) if isinstance(current, dict) else {}
        had_key = key in current
        if value is None:
            current.pop(key, None)
        else:
            current[key] = value
        opt.set(current or None)
        self._update_changed_style(opt, item)
        structure_changed = key != "def" and had_key != (value is not None)
        if structure_changed:
            self._schedule_repeated_rebuild(opt, item)

    def _update_repeated_array_value(
        self,
        opt: Any,
        item: QTreeWidgetItem,
        index: int,
        value: Any,
    ) -> None:
        current = _mutable_sequence(_all_option_values(opt))
        structure_changed = value is None or index >= len(current)
        if value is None:
            if index < len(current):
                current.pop(index)
        elif index < len(current):
            current[index] = value
        else:
            current.append(value)
        opt.set(current or None)
        self._update_changed_style(opt, item)
        if structure_changed:
            self._schedule_repeated_rebuild(opt, item)

    def _schedule_repeated_rebuild(
        self,
        opt: Any,
        item: QTreeWidgetItem,
    ) -> None:
        """Rebuild after the active mouse/focus event without moving the view."""
        scrollbar = self.tree.verticalScrollBar()
        position = scrollbar.value()

        def rebuild() -> None:
            if sip.isdeleted(item):
                return
            self._rebuild_compound_option(opt, item)
            scrollbar.setValue(min(position, scrollbar.maximum()))

        QTimer.singleShot(0, rebuild)

    def _build_array_option(self, opt: Any, item: QTreeWidgetItem, grammar_type: Any) -> None:
        self._build_summary_editor(opt, item, grammar_type, editable=True)
        values = _mutable_sequence(_option_value(opt))
        minimum_length = getattr(grammar_type, 'min_length', None)
        maximum_length = getattr(grammar_type, 'max_length', None)
        fixed_length = minimum_length is not None and minimum_length == maximum_length
        staged_values = list(values)
        if fixed_length:
            staged_values.extend([None] * (minimum_length - len(staged_values)))

        def apply_fixed_value(index: int, value: Any) -> None:
            staged_values[index] = value
            if all(component is not None for component in staged_values):
                opt.set(staged_values)
                self._update_changed_style(opt, item)
                self._rebuild_compound_option(opt, item)

        for index, value in enumerate(staged_values):
            child = QTreeWidgetItem([
                f'[{index}]', str(grammar_type.type), '', '', '',
            ])
            self._add_child(item, child)
            placement = FieldPlacement(tuple(opt._get_path().split('.')), child.text(0))
            if fixed_length:
                apply_value = lambda new_value, idx=index: apply_fixed_value(idx, new_value)
            else:
                apply_value = lambda new_value, idx=index, o=opt, parent_item=item: self._update_array_value(
                    o, parent_item, idx, new_value
                )
            self._install_value_editor(
                opt,
                child,
                placement,
                read_value=lambda idx=index: FieldValue(staged_values[idx]),
                apply_value=apply_value,
                value_type=grammar_type.type,
                allows_unset=fixed_length and value is None,
            )

        max_length = maximum_length
        if not fixed_length and (max_length is None or len(values) < max_length):
            append_index = len(values)
            append_item = QTreeWidgetItem([
                f'[{append_index}]',
                str(grammar_type.type),
                '',
                '',
                'Append new item',
            ])
            self._add_child(item, append_item)
            placement = FieldPlacement(tuple(opt._get_path().split('.')), append_item.text(0))
            self._install_value_editor(
                opt,
                append_item,
                placement,
                read_value=lambda: FieldValue(None),
                apply_value=lambda new_value, idx=append_index, o=opt, parent_item=item: self._update_array_value(o, parent_item, idx, new_value),
                value_type=grammar_type.type,
                allows_unset=False,
                allow_empty=True,
            )

    def _update_array_value(self, opt: Any, item: QTreeWidgetItem, index: int, value: Any) -> None:
        values = _mutable_sequence(_option_value(opt))
        if index < len(values):
            values[index] = value
        else:
            values.append(value)
        opt.set(values)
        self._update_changed_style(opt, item)
        self._rebuild_compound_option(opt, item)
        self._refresh_declared_editors()

    def _build_sequence_option(self, opt: Any, item: QTreeWidgetItem, grammar_type: GrammarSequence) -> None:
        self._build_summary_editor(opt, item, grammar_type, editable=True)
        values = _mutable_sequence(_option_value(opt))
        labels = _reverse_names_map(getattr(grammar_type, 'names', None), len(grammar_type.types))
        for index, subtype in enumerate(grammar_type.types):
            value = values[index] if index < len(values) else None
            child = QTreeWidgetItem([labels[index], str(subtype), '', '', ''])
            self._add_child(item, child)
            placement = FieldPlacement(tuple(opt._get_path().split('.')), child.text(0))
            self._install_value_editor(
                opt,
                child,
                placement,
                read_value=lambda value=value: FieldValue(value),
                apply_value=lambda new_value, idx=index, o=opt, parent_item=item: self._update_sequence_value(o, parent_item, idx, new_value),
                value_type=subtype,
                allows_unset=False,
            )

    def _update_sequence_value(self, opt: Any, item: QTreeWidgetItem, index: int, value: Any) -> None:
        current = _mutable_sequence(_option_value(opt))
        grammar_type = opt._definition.grammar_type
        while len(current) < len(grammar_type.types):
            current.append(None)
        current[index] = value
        opt.set(current)
        self._update_changed_style(opt, item)
        self._rebuild_compound_option(opt, item)

    def _build_table_option(self, opt: Any, item: QTreeWidgetItem, grammar_type: Table) -> None:
        item.setText(2, '<Table>')
        item.setToolTip(2, '<Table>')
        table_label = QLabel('<Table>')
        table_label.setToolTip('<Table>')
        self.tree.setItemWidget(item, 2, table_label)

        value = _option_value(opt)
        if value is None:
            return
        if not isinstance(value, np.ndarray):
            try:
                value = grammar_type.convert(value)
            except Exception:  # noqa: BLE001 - grammar conversion errors vary by type.
                item.setText(2, '<Data>')
                return
        if not isinstance(value, np.ndarray):
            item.setText(2, '<Data>')
            return

        if value.dtype.names:
            column_names = list(value.dtype.names)
            for row_index in range(len(value)):
                row_item = QTreeWidgetItem([
                    f'[{row_index}]', 'row', '', '', '',
                ])
                self._add_child(item, row_item)
                for col_index, column_name in enumerate(column_names):
                    subtype = grammar_type.sequence.types[col_index] if col_index < len(grammar_type.sequence.types) else String()
                    cell_value = value[row_index][column_name]
                    if isinstance(cell_value, np.generic):
                        cell_value = cell_value.item()
                    cell_item = QTreeWidgetItem([
                        str(column_name), str(subtype), '', '', '',
                    ])
                    self._add_child(row_item, cell_item)
                    placement = FieldPlacement(tuple(opt._get_path().split('.')), cell_item.text(0))
                    self._install_value_editor(
                        opt,
                        cell_item,
                        placement,
                        read_value=lambda value=cell_value: FieldValue(value),
                        apply_value=lambda new_value, r=row_index, c=column_name, o=opt, parent_item=item: self._update_table_field(o, parent_item, r, c, new_value),
                        value_type=subtype,
                        allows_unset=False,
                    )
            return

        array = np.asarray(value)
        if array.ndim == 1:
            if len(grammar_type.sequence.types) == 1:
                array = array.reshape((-1, 1))
            else:
                item.setText(2, '<Data>')
                return
        if array.ndim != 2:
            item.setText(2, '<Data>')
            return

        column_names = list(getattr(grammar_type, 'names', []) or [f'[{i}]' for i in range(array.shape[1])])
        for row_index in range(array.shape[0]):
            row_item = QTreeWidgetItem([f'[{row_index}]', 'row', '', '', ''])
            self._add_child(item, row_item)
            for col_index in range(array.shape[1]):
                subtype = grammar_type.sequence.types[col_index] if col_index < len(grammar_type.sequence.types) else String()
                cell_value = array[row_index, col_index]
                if isinstance(cell_value, np.generic):
                    cell_value = cell_value.item()
                name = column_names[col_index] if col_index < len(column_names) else f'[{col_index}]'
                cell_item = QTreeWidgetItem([
                    str(name), str(subtype), '', '', '',
                ])
                self._add_child(row_item, cell_item)
                placement = FieldPlacement(tuple(opt._get_path().split('.')), cell_item.text(0))
                self._install_value_editor(
                    opt,
                    cell_item,
                    placement,
                    read_value=lambda value=cell_value: FieldValue(value),
                    apply_value=lambda new_value, r=row_index, c=col_index, o=opt, parent_item=item: self._update_table_cell(o, parent_item, r, c, new_value),
                    value_type=subtype,
                    allows_unset=False,
                )

    def _update_table_field(self, opt: Any, item: QTreeWidgetItem, row_index: int, column_name: str, value: Any) -> None:
        current = np.array(_option_value(opt), copy=True)
        current[row_index][column_name] = value
        opt.set(current)
        self._update_changed_style(opt, item)
        self._rebuild_compound_option(opt, item)

    def _update_table_cell(self, opt: Any, item: QTreeWidgetItem, row_index: int, column_index: int, value: Any) -> None:
        current = np.array(_option_value(opt), copy=True)
        current[row_index, column_index] = value
        opt.set(current)
        self._update_changed_style(opt, item)
        self._rebuild_compound_option(opt, item)
