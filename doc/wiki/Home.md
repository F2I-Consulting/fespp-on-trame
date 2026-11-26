# fespp-on-trame — Developer Wiki

A [Trame](https://kitware.github.io/trame/) (Vue 3 + websocket) web UI that drives an in-process **ParaView Server**. ParaView loads the **FESPP** C++ plugin (F2I-Consulting), which reads **RESQML/EPC** geoscience data through **FESAPI** and emits VTK multiblock datasets plus a `vtkDataAssembly` describing the object tree.

> **This wiki is the handoff reference for forking the project.** It documents *what every Python file does*, the cross-cutting architecture, and the non-obvious traps — so you can work without asking the original author. Pair it with the in-repo guides under `doc/EN/` and `doc/FR/` (user-guide, dev-guide, SOURCES_ARCHITECTURE, TYPES_PARTICULARITES). The Architecture and the two UI pages were rewritten on 2026-09-16 for the BlockScope scene model and the widget-per-panel UI; the Core pages describe the legacy per-rep model, which runs only with `FESPP_BLOCKSCOPE` unset.

## Start here

1. **[[Architecture]]** — the big picture: the shell, the boot, the BlockScope scene model (one collector, one composite representation per view, the isolates), the end-to-end flows (tick → load, eye, colour, Z, slicers, a second view, panels) and the state conventions. Read this first.
2. **[[Build and Run|Build-and-Run]]** — how to build the two Docker images, run the container, the dev rebuild loop, and where the runtime logs actually go.
3. **[[Glossary]]** — RESQML/EPC/FESAPI + ParaView + Trame vocabulary used everywhere.

## Per-subsystem file reference

Each page documents every file in that subsystem: responsibility, key classes/functions (with signatures), the `state.*` it touches, collaborators, and gotchas.

| Page | What's inside |
|---|---|
| **[[Core — Sources|Core-Sources]]** | The ParaView pipeline sources: `Collector`, the ETP connector, `IjkGrid` (the isolates), the threshold chain — and the legacy per-rep model (`ViewScene`, `RepInScene`, `ExtractBlock`), live only with `FESPP_BLOCKSCOPE` unset. |
| **[[Core — Element Types|Core-Element-Types]]** | The strategy hierarchy (general → family → unit) encoding per-RESQML-kind behaviour. |
| **[[Engine — Lifecycle & State|Engine-Lifecycle-and-State]]** | State defaults, data load, selection and its invariant, visibility, active-array (coloring), resolvers. |
| **[[Engine — Dispatchers|Engine-Dispatchers]]** | One module per feature: statistics, distributions, cross-plots, the well log, reconcile, health, volumetrics, the calculator, the categorical palette, time and realizations, ETP. |
| **[[Core (root), IO & Utils|Core-IO-and-Utils]]** | `Tree`, `Selector`, `Activator`, `Wellhead`, `TimeSeries`; upload/download/temp-dir; naming/colour/search helpers; `__main__`. |
| **[[UI — Content area|UI-Content]]** | The dockview `MultiView`, the view kinds, a 3D view and its tool cards, the trees and the right-click menus, the session panels one by one, how to add one. |
| **[[UI — Shell, Widgets & Charter|UI-Drawer-Toolbar-Shared]]** | The top bar and the import door, how a widget is packaged and wired, the charter R1–R18 and its shared components, the three gates (eslint, the browser sweep, strict mode). |

## Refactoring

**[[Refactoring Notes|Refactoring-Notes]]** — concrete opportunities and code smells found while documenting (god objects, triple-duplicated algorithms, cross-module private reaches, and **two likely real bugs**: remote-file download signature mismatch, and the import dialog's multi-URL separator). Suggestions for the fork, not blockers.

## The 60-second mental model

```
Browser (Vue)  ──state.* / controller.* / server.trigger──▶  Engine handlers (boot.py wires them)
                                                                     │ delegate to
                                                                     ▼
                                                       Source/Scene layer  ──pvsimple proxies──▶  ParaView + FESPP plugin
                                                       (BlockScope, see below)                        │
                                                                                                       ▼
                                                                                          FESAPI → RESQML/EPC/H5 on disk
```

- A **representation** ("rep") is a renderable RESQML object, identified everywhere by its **`rep_path`** (its `vtkDataAssembly` node path).
- In production (`FESPP_BLOCKSCOPE=1`) the scene is **BlockScope**: ONE FESPP collector for the session, ONE composite representation per 3D view (`engine/blockscope/pdc_scene.py`) driven by a desired-state table and `reconcile()`; a rep is a selector string, not a proxy. A grid being cut in a view gets a per-(view, grid) **isolate** (`IjkGrid`) meanwhile.
- With the flag unset the older per-rep model runs (`SourceRegistry`, `SceneRegistry` → `ViewScene` → `RepInScene`, the `ElementType` strategies) — documented on the Core pages.
- The UI is a set of **widgets** (`widgets/`, one Vue component per panel or card, written in the shared components of `widgets/_shared`) mounted by a few lines of Python in `app/views`; `app/boot.py` holds the session handlers.

See **[[Architecture]]** for the full story.
