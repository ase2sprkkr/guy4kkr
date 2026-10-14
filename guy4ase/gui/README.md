# GUI organization

This document describes the **canonical GUI architecture**. It is an
architectural contract for new code and refactors. Internal migration shims are
not part of that contract and should be removed rather than preserved as
alternate APIs.

## Packages

- `dialogs`: finished application windows and modal workflows, including
  `MainWindow`, `WorkflowWindow`, and structure-specific dialogs under
  `dialogs.structures`.
- `widgets`: reusable Qt controls. `widgets.input_parameters` contains the
  concrete value editors shared by guided and expert parameter editing;
  structure-specific controls live in `widgets.structures`.
- `input_parameters`: parameter-editing state and Qt-independent model helpers.
  It contains the editing session, field bindings, validation, DATASET naming,
  tooltips, task-specific editing semantics, and Guided-task declarations. It
  does not own finished application windows.
- `input_parameters.tasks`: the single Guy4ASE registry of tasks for which a
  Guided experience exists. A `GuidedTaskDefinition` maps the Guided task to
  its ASE2SPRKKR backend task and owns its workflow presentation metadata and
  declarative layout builder. It is not the registry of all SPR-KKR tasks;
  backend task existence and execution semantics are owned by ASE2SPRKKR.
- `input_parameters.specs`: presentation-only declarative Guided layouts.
  `schema` defines fields/groups/pages and individual task modules build their
  layouts. `TaskDialogSpec` does not own task identity or backend-task mapping;
  `registry.task_dialog_spec` is only a compatibility-free lookup facade over
  `input_parameters.tasks`.
- `application`: application/document state, calculation execution, provenance,
  and policy over application state. `WorkspaceState` represents the mutable
  draft prepared for the next calculation; `ResultStore` owns calculation
  history independently of that draft; `WorkspaceController` is the
  mutation/signalling boundary between them and the GUI. `calculation_policy`
  interprets Guided workflow stages as recommendations; those recommendations
  are deliberately not Expert/backend launch restrictions. `SprkkrExecution`
  owns the non-Qt execution contract for one immutable calculation request.
  Persistent application state such as recent files and settings also lives
  here.
- `flows`: stateless shared Qt workflows composed from application state and
  leaf dialogs. They may show modal UI and call public controller transitions,
  but they do not own application state or top-level windows.
- `plots`: GUI plotting/rendering. Pure physical/lattice queries and
  transformations belong in `guy4ase.physics`, not in the GUI layer.
- `misc`: small, specifically named Qt/layout/resource helpers. It must not
  become a home for application state or task-specific rules.
- `style`: the small palette-aware visual vocabulary shared by dialogs and
  renderers. Semantic state and task-specific presentation stay with the
  component that owns their meaning.

`guy4ase.main.GuiApplication` is the composition root. It owns one
`WorkspaceController`, one `RecentFiles`, and one `ApplicationSettings`, and
injects the same shared objects into the workflow and expert top-level windows.
The windows do not construct another application state or another top-level
window. Result selection is presentation state; the composition root wires
explicit result-selection intent separately from result history updates.

Calculation execution is deliberately not owned by a GUI run registry. A
`CalculationRequest` captures exact launch provenance, `SprkkrExecution` owns
runner creation/submission/cancellation/result loading, and `RunMonitorWindow`
is only the generic Qt monitor. Persistent execution identity and collision
policy belong to ASE2SPRKKR's runner/persistence layer.

SPR-KKR task identity and backend execution semantics likewise belong to
ASE2SPRKKR's `InputParametersDefinition` registry. Guy4ASE may provide a
smaller Guided registry, but Expert execution must not reject a valid backend
task merely because Guy4ASE has no Guided dialog for it. Backend facts such as
whether a task produces a new potential are read from ASE2SPRKKR task-definition
metadata rather than inferred from task-name strings in the GUI.

Package `__init__.py` files should stay lightweight and should not become
alternate import APIs for dialog/widget internals. Canonical imports use the
concrete modules documented by the current package layout. Internal
compatibility wrappers are not architectural extension points and should not be
added to accommodate tests or obsolete call shapes.

## Workspace, results, and provenance

`WorkspaceState` is the draft for the **next** calculation. Results deliberately
do not live in it. Its `structure_id` identifies the user-visible structure and
`state_id` identifies the exact calculation state from which the next task will
start.

`WorkspaceState.atoms` is the sole physical authority for the active structure,
including an attached SPR-KKR potential when one exists. `potential_path` is
artifact/provenance metadata only; calculation launch must not silently use it
as a second physical source of truth.

`ResultStore` owns result history and calculation-state provenance independently
of the mutable workspace. A result may refer to an input state and, for a
backend-declared potential-producing task, to an output state. Historical states
retain enough provenance to reconstruct a reusable calculation input from the
recorded POTFIL version or a structure snapshot when necessary. Activating
historical state is always an explicit transition.

Windows and flows mutate the draft through named `WorkspaceController`
operations rather than assigning workspace facets independently. The important
result-adoption semantics are:

- `adopt_external_result()` **records** an output imported by the user or another
  external source. It does not implicitly replace the current workspace draft.
  The imported result's atoms, potential, and input parameters belong to that
  result's provenance, not to the active draft. `select_result=True` expresses
  only explicit presentation intent to select that result in the UI.
- `adopt_calculation_result()` records a result produced from its mandatory
  captured `CalculationRequest`. It never reconstructs launch provenance from
  whatever happens to be active when the result finishes. Only a
  backend-declared potential-producing result finishing from the exact currently
  active input state may fast-forward the workspace to its produced state. A
  result from an older branch is recorded in that branch and cannot silently
  overwrite a newer user choice.
- `use_result_state()` is the explicit operation for activating a reusable
  historical state (or an explicitly approved current version of its POTFIL).
- `use_for_new_calculation()` creates a new calculation branch from the active
  state instead of rewriting historical provenance.

The distinction between **recording a result**, **selecting a result for
presentation**, and **activating a result state for a future calculation** is
intentional. Do not collapse these operations into one implicit transition.
Presentation code reads history through `result_store`; controllers do not
expose duplicate compatibility views of the same history.

## Parameter editing

`input_parameters.session.InputParametersSession` owns an isolated working copy
of `InputParameters`, Undo/Redo history, and non-serialized editing state.
Edits go through session transactions; callers may inspect
`working_parameters` but must not mutate it directly. `result()` returns an
independently mutable copy. Transaction plugins may adjust a candidate and its
dormant state atomically before one history command is installed.

`input_parameters.bindings.InputParameterPath` is a tuple such as
`("ENERGY", "EMIN")`; it is an option address, not a filesystem path. Shared
option resolution/value comparison also lives in `input_parameters.bindings`.

Guided fields are connected to the session by
`input_parameters.field_binding`:

- `SessionFieldBinding` binds an ordinary option to its authoritative session
  value.
- `ProjectedFieldBinding` exposes a composable view into part of a structured
  parent value while reconstruction still happens through the parent binding.
- specialized draft/index helpers are presentation adapters; they must not
  become a second parameter model.

`widgets.input_parameters.parameter.ParameterEditor` is the presentation shell
for one declarative field. It owns tooltip/validation presentation and delegates
value editing to a registered `ParameterValueEditor` control. It does not
implement type-specific editing semantics itself.

All guided value editors implement the explicit
`widgets.input_parameters.value_editor.ParameterValueEditor` lifecycle:
`refresh()`, `commit()`, and `focus_for_history()`. Optional capabilities such as
`dependencies`, `full_width`, `help_text`, and tooltip application have formal
defaults; surrounding code must not discover editor contracts by probing
arbitrary attributes with `getattr`.

`widgets.input_parameters.registry.EDITORS` is the single name-to-editor
registry. `create_editor()` is the construction path. A field declaration
normally chooses its editor explicitly; `editor="auto"` alone invokes the
registered grammar-type MRO fallback in `editor_for_type()`.

Task-specific parameter semantics belong outside generic widgets. For example,
atomic BSF mode/path changes live in `input_parameters.bsf`, and the
single-site-contour transaction behavior lives in its dedicated plugin.
Generic renderers and scalar controls must not duplicate those rules.

### Guided tasks, specifications, and presentation rules

A `GuidedTaskDefinition` owns Guy4ASE's Guided identity, the backend-task mapping,
workflow label/description/stage, and the builder for its dialog layout. The
workflow stage is interpreted by `application.calculation_policy`; neither the
registry nor `WorkflowWindow` turns it into a backend-validity rule.

Guided layouts themselves are declarative and presentation-only. A
`FieldPlacement` identifies the parameter path, editor, related paths, and
presentation metadata. Conditional behavior is expressed by named rules in the
task specification and receives a Qt-independent presentation context. Rules
may inspect parameter state but must not mutate `InputParameters` or invoke Qt
actions.

Fields may define dynamic visibility/enabling/labels/help and required state;
groups may define dynamic visibility, titles, notes, and layout. Programmatic
identity uses stable IDs, never translated/user-visible titles.

The renderer reapplies presentation rules after session changes, including
Undo/Redo and parameter replacement. Unrelated edits preserve a control's local
draft; replacement/history restoration or changes to that control's own
parameter/dependencies refresh it from the model.

### Expert editing

`dialogs.expert_input.InputParametersDialog` edits an isolated
`InputParametersSession` fork. Cancel therefore cannot mutate the caller's
session. The accepted result is returned as the fork/current parameter copy.

`widgets.input_parameters.expert_tree.ExpertInputTreeEditor` owns expert-tree
presentation and pending editor commits, while the dialog owns modal workflow,
validation, loading/editing input files, and acceptance. The expert tree and
guided form share the same session model; neither owns a second authoritative
parameter object. Tests and neighboring components use its narrow query API
such as `option_item(path)` rather than depending on internal row registries or
Qt role aliases.

Implicit backend defaults are presentation placeholders, not GUI-created
presets. Focusing or refreshing a control must not turn an implicit default into
an explicit stored value.

## Dependency rules

- `guy4ase.main.GuiApplication` is the composition root for shared application
  state and top-level windows.
- `application` does not import dialogs, widgets, or flows.
- Windows render controller state and invoke flows/controller transitions; they
  do not assign workspace fields directly.
- `flows` may compose application state and leaf dialogs, but must not import
  `MainWindow` or `WorkflowWindow`.
- Widgets may use parameter services and small helpers, but must not import
  concrete application dialogs. Use signals/callbacks for actions owned by a
  higher layer.
- `input_parameters` must not depend on concrete dialogs or widgets.
- `input_parameters.tasks` owns Guided registration only; it must not become a
  second ASE2SPRKKR backend-task registry.
- `input_parameters.specs` must remain independent of task identity, Qt
  session/widget implementations, and workflow policy.
- `misc` and `plots` must not become dependencies on top-level dialogs or
  parameter editors.
- Domain logic that can be expressed without Qt belongs outside the GUI package
  where practical.

The checks in `tests/test_gui_architecture.py` protect the broad layer
directions, acyclic GUI imports, and lightweight import boundaries. Tests should
protect invariants and public contracts, not freeze incidental implementation
layout. Backend execution behavior is tested through `SprkkrExecution`; only Qt
signal/thread adaptation belongs in worker-level tests.

## Common canonical imports

```python
from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.application.workspace_controller import WorkspaceController
from guy4ase.gui.application.result_store import ResultStore
from guy4ase.gui.application.sprkkr_execution import SprkkrExecution
from guy4ase.gui.dialogs.guided_input import GuidedInputParametersDialog
from guy4ase.gui.dialogs.expert_input import InputParametersDialog
from guy4ase.gui.input_parameters.session import InputParametersSession
from guy4ase.gui.input_parameters.bindings import InputParameterPath
from guy4ase.gui.input_parameters.dataset import filename_component
from guy4ase.gui.input_parameters.field_binding import SessionFieldBinding
from guy4ase.gui.input_parameters.tasks import guided_task_definition
from guy4ase.gui.input_parameters.specs.registry import task_dialog_spec
from guy4ase.gui.widgets.input_parameters.value_editor import ParameterValueEditor
```
