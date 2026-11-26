# V2 widget specs

Each widget is a self-contained Trame component with an explicit contract. Every
spec below follows the same shape:

- **Scope** — global (one instance) or per-view (one per dockview panel,
  scoped to a `view_id`).
- **Input** — what the host passes in (props / the `view_id` / user gestures).
- **Behaviour** — what it renders and does.
- **Reads** — state it reads.
- **Writes (session / view)** — the state-changes it triggers; flagged
  **[session]** (trame session-scoped — drives the shared data layer) or
  **[per-view]** (local to its view). This is the contract that matters for the
  `@state.change` handlers.
- **Notes / open** — decisions and simplifications vs the drawer application.

| Widget | Scope |
|---|---|
| [import-dialog](import-dialog.md) | global |
| [toolbar](toolbar.md) | global |
| [layout-view-manager](layout-view-manager.md) | global |
| [view-panel](view-panel.md) | per-view |
| [data-explorer-tree](data-explorer-tree.md) | per-view |
| [attributes-panel](attributes-panel.md) | per-view |
| [color-legend](color-legend.md) | per-view |
| [time-control](time-control.md) | per-view |
| [analysis-panels](analysis-panels.md) | per-property |
| [navigation-panel](navigation-panel.md) | per-view |
| [stratigraphic-column](stratigraphic-column.md) | session data, per-view card |
| [calculator-panel](calculator-panel.md) | singleton |
| [crossplot-controls](../../../widgets/crossplot/README.md) | per-panel |

See [../ARCHITECTURE.md](../ARCHITECTURE.md) for the two-layer model and the
**checkbox (load, shared) vs eye (show, per-view)** semantic that underpins all
of these.
