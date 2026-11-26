# Widget: Toolbar (global)

The top app bar — app-level actions, view-independent.

## Scope
Global.

## Input
- User clicks.

## Behaviour
- Open the [import-dialog](import-dialog.md).
- Drive the [layout-view-manager](layout-view-manager.md): add / split / remove
  views.
- Collapse/expand the toolbar (the up/down corner toggle).
- Global settings / display options.

## Reads
- `dialog_visible`, layout state, global toggles.

## Writes (back-end / global)
- **[session]** `dialog_visible`; view-manager actions (create / destroy a
  `view_id`); toolbar collapse flag; global display options.

## Notes / open
- Holds **no** per-view state. View-specific affordances (tree/attributes/legend
  open-close) live on each [view-panel](view-panel.md), not here.
