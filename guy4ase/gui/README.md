# GUI organization

## Packages

- `dialogs`: finished application windows, including `MainWindow` and
  `WorkflowWindow`. `dialogs.structures` contains structure-specific dialogs.
  `guy4ase.main` remains the application entry point.
- `widgets`: reusable controls. `widgets.input_parameters` contains editors for
  ase2sprkkr `InputParameters`; these are shared by guided and expert editing.
  Structure-specific controls live in `widgets.structures`.
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
- `workspace.WorkspaceState`: the Qt-independent current document: structure,
  input parameters, working directory, potential and calculation result.
  `MainWindow` renders and mutates it through public operations; guided
  `WorkflowWindow` shares the same instance rather than accessing its internals.

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
Ordinary expert controls use `widgets.input_parameters.commit.EditorCommit` to
contain validation exceptions and avoid writing unchanged, rounded display
values back into the model. Both dialogs use `input_parameters.validation` for
completion checks, without requiring calculator-supplied files such as POTFIL.

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

The shared `EnergyEditor` receives read/apply callbacks. Backend-specific
absolute/relative option mapping lives in `input_parameters.energy`.
`RelativisticScalingEditor` edits global and per-atomic-type `MODE.C`/`MODE.SOC`;
its numeric delegate lives in `widgets.numeric_table`, independently of K-paths.

`dialogs.input_file.InputFileEditor` stays independent of both the guided session
and expert tree. Additional validation/application is passed through its
`apply_parameters` callback. A failed callback leaves the draft open.

## Dependency rules

- Dialogs compose widgets and parameter-editing services.
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
