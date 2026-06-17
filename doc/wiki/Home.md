# fespp-on-trame — Developer Wiki

A [Trame](https://kitware.github.io/trame/) (Vue 3 + websocket) web UI that drives an in-process **ParaView Server**. ParaView loads the **FESPP** C++ plugin (F2I-Consulting), which reads **RESQML/EPC** geoscience data through **FESAPI** and emits VTK multiblock datasets plus a `vtkDataAssembly` describing the object tree.

> **This wiki is the handoff reference for forking the project.** It documents *what every Python file does*, the cross-cutting architecture, and the non-obvious traps — so you can work without asking the original author. It is generated from a deep read of the codebase; pair it with the in-repo guides under `doc/EN/` and `doc/FR/` (user-guide, dev-guide, SOURCES_ARCHITECTURE, TYPES_PARTICULARITES).

## Start here

1. **[[Architecture]]** — the big picture, the per-view scene model, end-to-end data flows (selection → render, coloring, z-scale, threshold/slice/clip, view split), and the `state.*` catalog. Read this first.
2. **[[Build and Run|Build-and-Run]]** — how to build the two Docker images, run the container, the dev rebuild loop, and where the runtime logs actually go.
3. **[[Glossary]]** — RESQML/EPC/FESAPI + ParaView + Trame vocabulary used everywhere.

## Per-subsystem file reference

Each page documents every file in that subsystem: responsibility, key classes/functions (with signatures), the `state.*` it touches, collaborators, and gotchas.

| Page | What's inside |
|---|---|
| **[[Core — Sources|Core-Sources]]** | The ParaView pipeline heart: `Collector`, `ViewScene`, `RepInScene`, `ElementType` delegation, `ExtractBlock` (legacy), `IjkGrid`, slice/clip/threshold, ETP. |
| **[[Core — Element Types|Core-Element-Types]]** | The strategy hierarchy (general → family → unit) encoding per-RESQML-kind behaviour. |
| **[[Engine — Lifecycle & State|Engine-Lifecycle-and-State]]** | `boot.py` wiring hub, state defaults, data load, selection, visibility, active-array (coloring), resolvers. |
| **[[Engine — Dispatchers|Engine-Dispatchers]]** | One module per feature: slicer/slice/clip/threshold/marker/realization/distribution/stats/diff/etp + z-scale. |
| **[[Core (root), IO & Utils|Core-IO-and-Utils]]** | `Tree`, `Selector`, `Activator`, `Wellhead`, `TimeSeries`; upload/download/temp-dir; naming/colour/search helpers; `__main__`. |
| **[[UI — Content area|UI-Content]]** | Layout, the dockview `FesppMultiView` (render/diff/stats/distribution panels), dialogs, widgets, stats panels. |
| **[[UI — Drawer, Toolbar & Shared|UI-Drawer-Toolbar-Shared]]** | The left drawer (tree tabs + Attributes panels), tree views with tri-state checkboxes + per-view eyes, toolbar, shared helpers/CSS/JS. |

## Refactoring

**[[Refactoring Notes|Refactoring-Notes]]** — concrete opportunities and code smells found while documenting (god objects, triple-duplicated algorithms, cross-module private reaches, and **two likely real bugs**: remote-file download signature mismatch, and the import dialog's multi-URL separator). Suggestions for the fork, not blockers.

## The 60-second mental model

```
Browser (Vue)  ──state.* / controller.* / server.trigger──▶  Engine handlers (boot.py wires them)
                                                                     │ delegate to
                                                                     ▼
                                                       Source/Scene layer  ──pvsimple proxies──▶  ParaView + FESPP plugin
                                                       (two models, see below)                        │
                                                                                                       ▼
                                                                                          FESAPI → RESQML/EPC/H5 on disk
```

- A **representation** ("rep") is a renderable RESQML object, identified everywhere by its **`rep_path`** (its `vtkDataAssembly` node path).
- Two pipeline generations coexist: a **legacy** per-rep registry (`SourceRegistry` → `ExtractBlock`/`IjkGrid`, view-agnostic) and the **live per-view** model (`SceneRegistry` → `ViewScene` → `RepInScene`), so each render panel can colour/slice/clip/threshold the same rep independently. The legacy path is a **Phase-2 fallback** that fires only when the `vtkEPCCollectorClone` plugin proxy is unavailable.
- Per-kind *behaviour* lives in stateless **`ElementType`** singletons; per-(rep, view) *state* lives in **`RepInScene`** (which delegates to the ElementType, passing itself as `ris`).

See **[[Architecture]]** for the full story.
