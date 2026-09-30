# GUI organization

## Packages

- `dialogs`: finished application windows, including `MainWindow` and
  `WorkflowWindow`. `dialogs.structures` contains structure-specific dialogs.
  `guy4ase.main` remains the application entry point.
- `widgets`: reusable controls. `widgets.input_parameters` contains editors for
  ase2sprkkr `InputParameters`; these are shared by guided and expert editing.
  Task-only composite controls live in modules such as
  `widgets.input_parameters.bsf`; structure-specific controls live in
  `widgets.structures`.
- `input_parameters`: editing state, backend bindings, energy/BSF operations,
  keyword choices and help text. It contains no finished dialogs or widgets.
- `input_parameters.specs`: Qt-independent declarations of the guided layouts.
  `schema` defines fields/groups/pages, `shared` contains common definitions,
  individual task modules expose `build_spec`, and `registry.task_dialog_spec`
  selects and validates a layout.
- `plots`: Matplotlib rendering. Pure lattice transformations belong in
  `guy4ase.physics.lattice`, not in the GUI.
- `misc`: small, specifically named Qt/layout/resource helpers. It must not
  become a home for application state or task-specific rules.
- `style`: the small palette-aware visual vocabulary shared by dialogs and
  renderers: spacing, relative heading fonts, tinting, rounded panels and
  primary/secondary action states. Semantic colors and layout remain with the
  window or task that owns their meaning; this is intentionally not a theme
  manager.
- `application`: shared application state and document services, kept separate from
  Qt windows and reusable widgets. `application.workspace.WorkspaceState` is
  the Qt-independent current document. `application.workspace_controller`
  provides its single mutation/signalling boundary, and
  `application.recent_files` owns Qt-independent history persistence. Menus
  and other presentation state remain owned by the windows.
- `flows`: shared Qt orchestration such as structure selection, file loading,
  guided task setup, calculation windows and result actions. A flow may compose
  leaf dialogs and update `application`, but it does not depend on
  `MainWindow` or `WorkflowWindow`. Both window shells use the same
  `GuiOperations` instance; Expert Mode is created lazily as another view.

Package `__init__.py` files intentionally do not eagerly import dialogs or
re-export their internals. Import concrete modules directly. The former flat
module paths and `calculation_setup` package have no compatibility wrappers.

## Parameter editing

`input_parameters.session.InputParametersSession` owns the working parameters,
initial snapshot, Undo/Redo and remembered single-site settings. Widgets must not
keep a second authoritative parameter model. Invalid or incomplete input may
remain in a widget's draft until committed or discarded.

`input_parameters.bindings.InputParameterPath` is a tuple such as
`("ENERGY", "EMIN")`. It is an option address, not a file-system path.

`InputParametersBinding` is a direct read/write adapter, not another session. It
accepts a parameter getter and a change callback. The expert dialog supplies its
isolated parameter copy and updates its tree presentation after a commit.
The guided dialog uses the session's corresponding access methods, preserving
Undo/Redo. The getter follows replacement of the object after loading text input.

The expert dialog also edits a copy: Cancel never modifies its caller's input.
`dialogs.expert_input.InputParametersDialog` owns that draft, input-file and
working-directory workflow, overall validation, and modal acceptance. The
reusable `widgets.input_parameters.expert_tree.ExpertInputTreeEditor` owns the
searchable tree, changed-only presentation, value editors, compound-value rows,
and editor-error aggregation. It receives a getter for the dialog-owned draft,
so replacing a parsed input does not create a second authoritative model.
Ordinary scalar controls use `widgets.input_parameters.commit.EditorCommit`
internally to contain validation exceptions and avoid writing unchanged,
rounded display values back into the model. It is an implementation helper,
not a protocol inspected by either dialog. Both dialogs use
`input_parameters.validation` for completion checks, without requiring
calculator-supplied files such as POTFIL.

Implicit backend defaults appear as placeholders (`Default: …`) in text and
numeric inputs. They are not presets and are not stored by focusing a control.
Spin controls retain the effective default for stepping; clearing an explicit
value restores the backend default where one exists. The layout schema does
not duplicate defaults. Energy widgets convert placeholder values with display
units and use the shared ase2sprkkr absolute/relative default rules.

`InputParametersSession.editApplied` distinguishes changed option paths from
full replacement/history restoration. Unrelated commits preserve local drafts;
undo/redo and explicit replacement discard them. A change to a draft's own
option or a mode on which it depends refreshes it from the model.

Task preparation and atomic BSF mode changes live in `input_parameters.tasks`
and `input_parameters.bsf`. A widget requests modal K-path editing via a signal;
the guided dialog owns the modal operation and its parent window. Shared group
selection uses stable IDs, never translated/user-facing titles.

### Conditional guided fields

Presentation rules live beside a task's field declarations and receive a
Qt-independent `PresentationContext`. Keep them as named functions when they
express domain meaning:

```python
def broyden_enabled(context: PresentationContext) -> bool:
    return context.value("SCF", "ALG") == "BROYDEN2"

GroupSpec("Potential mixing", (
    ALG,
    field("SCF", "ISTBRY", "Start Broyden after:", "integer",
          enabled_when=broyden_enabled),
))
```

Fields support `visible_when`, `enabled_when`, `label_when`, `tooltip_when`,
`disabled_reason_when` and `required_when`. Groups support visibility, dynamic
titles and notes. Use `layout="paired"` for a two-column group and `GroupSpec.id`
for stable programmatic identity; displayed titles are not identifiers. Rules
must only inspect the context. They must not mutate `InputParameters` or invoke
Qt code—the renderer reapplies them after every session replacement, including
Undo/Redo, loaded input and accepted expert edits.

Task-specific controls are selected by `FieldPlacement.editor`, never
by a page or group ID:

```python
field("TASK", "KA", "Path segments:", editor="bsf_vectors",
      related_paths=(("TASK", "KE"),))
```

All implementations are collected in the single `EDITORS` mapping in
`widgets.input_parameters.registry`. Scalar, energy, vector and task-specific
controls all implement the single
`ParameterValueEditor` lifecycle. `ParameterValueEditorWidget` is only a
convenient QWidget base for controls composed from child widgets; it is not a
separate editor category. The contract supplies defaults for optional
capabilities. Task-specific
implementations such as BSF mode, path selection and path vectors live in
`widgets.input_parameters.bsf`; shared binding adapters for energy bounds and
relativistic scaling live in `widgets.input_parameters.common`. Such a control
implements `refresh()`, `commit()` and `focus_for_history(path, index)`, emits
`validationChanged(str)`, and may declare `dependencies` and `full_width`.
Task-specific modal controls, such as the BSF custom K-path editor, handle
their action in the registered widget and mutate the session for Undo/Redo.
`input_parameters.field_binding.SessionFieldBinding` maps a scalar or whole
option to its value, default and atomic session write. An explicitly indexed
placement uses `IndexedFieldBinding`; the option's array type alone does not
imply indexing because fields such as `MSPIN` edit the whole array. Energy-unit
conversion belongs to the energy value editor rather than the storage binding.
The field declaration selects a presentation explicitly with, for example,
`editor="energy"`. Only `editor="auto"` invokes the deterministic grammar-MRO
mapping in `editor_for_type()`.
Dormant single-site mesh values remain owned by the session.
`ParameterEditor` remains the
session/tooltip/presentation shell and delegates `refresh()`, `commit()` and
history focus without knowing any concrete Qt value-editor type.

`widgets.input_parameters.form.GuidedFormRenderer` owns the rendered anatomy of
the guided form. Its `PageView`, `GroupView` and `FieldView` objects keep an
editor together with its label, mirror link, auxiliary widgets, collapsed-group
toggle and validation state. `GuidedInputParametersDialog` owns workflow and
navigation only. Its `NavigationView` keeps each list item, label and tint
together; these shell widgets are not stored in renderer-owned `PageView`s.
Adding field decorations or another group layout belongs in the renderer rather
than in the dialog.

The smallest new editor therefore only needs the lifecycle methods:

```python
class MyEditor(ParameterValueEditorWidget):
    def __init__(self, binding, placement, atoms=None, parent=None): ...
    def refresh(self): ...
    def commit(self) -> bool: ...
```

`create_editor(binding, placement, ...)` is the only construction path. It
resolves `placement.editor`, looks up `EDITORS`, and calls the common
`from_binding()` constructor. The factory contains no widget-specific setup.

Override `focus_for_history()`, `set_editor_tooltip()`, `dependencies`,
`full_width` or `help_text` only when their defaults are insufficient.

The shared `EnergyEditor` receives read/apply callbacks. Backend-specific
absolute/relative option mapping lives in `input_parameters.energy`.
`RelativisticScalingEditor` edits global and per-atomic-type `MODE.C`/`MODE.SOC`;
its numeric delegate lives in `widgets.numeric_table`, independently of K-paths.

`dialogs.input_file.InputFileEditor` stays independent of both the guided session
and expert tree. Additional validation/application is passed through its
`apply_parameters` callback. A failed callback leaves the draft open.

## Dependency rules

- Dialogs compose widgets and parameter-editing services.
- Windows render `WorkspaceController` changes; they do not assign document
  fields directly. Calculation completion is delivered through an explicit
  callback rather than by inspecting a parent window for a named method.
- Widgets may use parameter services and small helpers, but never import
  concrete application dialogs. Use signals or callbacks to request actions.
- `input_parameters` must not import `dialogs` or `widgets`.
- Task specifications must not import the Qt session or GUI controls.
- `misc` and `plots` must not depend on dialogs or parameter editors.

The dependency checks in `tests/test_gui_architecture.py` protect these rules,
including the absence of circular GUI imports and import-time window loading.

## Common imports

```python
from guy4ase.gui.dialogs.guided_input import GuidedInputParametersDialog
from guy4ase.gui.dialogs.expert_input import InputParametersDialog
from guy4ase.gui.dialogs.object_view import ReadOnlyObjectDialog
from guy4ase.gui.input_parameters.session import InputParametersSession
from guy4ase.gui.input_parameters.bindings import InputParameterPath
from guy4ase.gui.input_parameters.specs.registry import task_dialog_spec
from guy4ase.gui.widgets.input_parameters.energy import EnergyEditor
from guy4ase.gui.widgets.input_parameters.relativistic_scaling import RelativisticScalingEditor
```
