# V2 — Single-composite re-architecture (drop the per-rep extraction)

> Status: **proposal, validated by pvpython probes (PV6.0.1 / VTK9.5.2), 2026-07-01.**
> Not implemented. This is the plan for a future implementation day.

## 1. Why

Today FESPP emits **one `vtkPartitionedDataSetCollection` (PDC)** and the app
extracts **each RESQML rep into its own ParaView source** (`EnergisticsExtractor`
per rep, then its own representation). That deliberate *N-source* design is the
root cause of several problems:

- **Mass-load `std::bad_alloc`** — every ParaView representation eagerly builds a
  `vtkSelectionRepresentation → vtkDataLabelRepresentation → 100 vtkTextMapper`;
  at ~100-150 reps the heap arena fragments and a small `new` throws. *Mitigated*
  by the leaf-rep fix (branch `fix/mass-load-crash-leaf-rep`, ~18x less/rep) but
  the N reps still exist.
- **Marker load/unload O(N²)** (one proxy per marker).
- **High memory** — N representations, N sources.

The leaf-rep fix *mitigates*. This proposal *eliminates the root cause*: **1 PDC
source + 1 composite representation**, everything driven per-block.

## 2. The proposal

Keep the PDC as a single source + single composite representation. Drive per-rep
behaviour through the composite's **per-block** machinery instead of N sources:

| Concern | Per-block mechanism (on the ONE composite rep) |
|---|---|
| Visibility | `BlockSelectors` (assembly paths) |
| Colour / LUT / opacity **per block** | `BlockColorArrayNames`, `BlockLookupTables`, `BlockMapScalars`, `BlockOpacities`, `BlockUseSeparateColorMaps` |
| Picking | composite selection returns the block index / assembly path |
| Global filters | composite-aware filters auto-loop over leaves |
| Per-grid filters | **on-demand** extraction to a concrete dataset (see §4) |

## 3. Verified facts (pvpython probes, container `fespp_leaftest`)

Composite built from a mixed `vtkExplicitStructuredGrid` (ESG) + `vtkPolyData`:

- **Type-specific filters AUTO-LOOP over composite leaves.** `Slice` and
  `Threshold` applied to the *whole* PDC ran per-leaf, each leaf presented as its
  concrete type (`Slice` → both leaves sliced; `Threshold` → both → ugrid). So
  for the common filters you apply directly to the PDC — no extraction needed.
- **Per-block colour with separate LUTs is native.** The composite rep exposes
  `BlockColorArrayNames`, `BlockLookupTables`, `BlockMapScalars`, `BlockOpacities`,
  `BlockUseSeparateColorMaps`, `BlockSelectors`, `SelectedBlockSelectors`. → each
  leaf can be coloured by a different array with a different LUT on **one** rep.
- **`ProgrammableFilter` can isolate a poly/ugrid leaf** as a concrete dataset
  (`OutputDataSetType` + `vtkDataObjectTreeIterator` → `ShallowCopy` the leaf).
- **`SurfaceRepresentation` (leaf) HAS `Assembly` + `BlockSelectors`** and
  `BlockSelectors` really filters a multiblock on render (so even the leaf-rep
  fix's rep supports per-block visibility).

## 4. The ESG caveat — per-grid IJK filtering still needs a concrete extract

The RESQML grids are `vtkExplicitStructuredGrid`. The IJK slice/crop proper to
them is `ExplicitStructuredGridCrop`. Probes showed:

- ✅ `ExplicitStructuredGridCrop` on a **concrete ESG** works (IJK crop, 8000→N cells).
- ❌ `ExplicitStructuredGridCrop` on a **composite** containing an ESG **CRASHES
  the process** (it is not composite-safe; it chokes on the non-ESG leaf). So you
  cannot IJK-crop "inside" the PDC.
- ❌ `ProgrammableFilter` **cannot output an ESG** — its `OutputDataSetType` enum
  is `{Same as Input, vtkPolyData, vtkStructuredGrid, vtkRectilinearGrid,
  vtkUnstructuredGrid, vtkImageData, vtkUniformGrid, vtkMultiblockDataSet,
  vtkHierarchicalBoxDataSet, vtkHyperTreeGrid, vtkTable, vtkMolecule,
  vtkPartitionedDataSet, vtkPartitionedDataSetCollection}` — **no
  `vtkExplicitStructuredGrid`**.

**Conclusion:** to run an ESG-specific filter (IJK slice/crop) you must first
isolate that grid to a **concrete `vtkExplicitStructuredGrid`**. FESPP's existing
`EnergisticsExtractor` already does exactly this (it returns the concrete type).
So the pattern is **hybrid**:

- **Display / colour / visibility of the many** → the single composite rep.
- **Per-grid filtering of the few** → `EnergisticsExtractor` *on demand*, only for
  the grid(s) actually being sliced/clipped — not for every rep.

This still removes the N-source explosion (extraction becomes rare, not per-rep).

## 5. Answers to the three design questions

1. **ESG IJK slice possible?** Yes, but only on a **concrete ESG** — isolate the
   grid with `EnergisticsExtractor` first (not `ProgrammableFilter`, which can't
   output ESG; not on the composite, which crashes). Only for grids being sliced.
2. **`ProgrammableFilter` to crop/slice a single block?** Yes for **poly/ugrid**
   leaves (verified). For **ESG** use `EnergisticsExtractor` instead (type limit).
3. **Isolated picking on one block?** Yes — ParaView's composite selection returns
   the block index / assembly path with the picked cell/point, so you know which
   block was clicked. (Native multiblock-selection behaviour; wire it in the Trame
   selection handler. Verify the exact block-id field during implementation.)

## 6. Migration impact — simpler steady-state, non-trivial migration

- **Simpler at rest:** 1 source + 1 rep instead of N; far fewer VTK/SM objects;
  the mass-load crash and marker O(N²) disappear structurally.
- **The work is the data model:** today a "rep" == a source proxy. Here a "rep" ==
  a **block / assembly path** on the shared composite. That touches: the source
  registry, visibility (`BlockSelectors` instead of per-source Show/Hide), colour
  (`BlockLookupTables` instead of per-rep display), selection/picking, the stats /
  diff / slicer dispatchers, and the tree→rep wiring. Per-grid filters need an
  on-demand extract-and-reinsert path.
- Net: **conceptually simpler, but a broad refactor of the per-rep plumbing** —
  best done as the V2 backbone rather than bolted on.

## 6b. PER-VIEW × single-composite — VALIDATED (2026-07-02)

The natural synthesis with the V2 per-view architecture: **ONE shared PDC source
(no per-view `vtkEPCCollectorClone`, no per-(rep,view) extractor)**, and let the
per-view divergence live in the **representations** — which ParaView already
scopes per (source, view):

- `Show(pdc, viewN)` → each view gets its OWN composite rep of the SAME source.
- **Pixel-proven in pvpython** (one GroupDatasets source: ESG + sphere, 2 views):
  view1 `BlockSelectors=[<esg path>]` + red tint → renders ONLY the red ESG;
  view2 `BlockSelectors=[<sphere path>]` + blue tint + `Scale=[1,1,3]` → renders
  ONLY the blue sphere z-scaled ×3. Selector paths introspected from
  `GetDataInformation().GetHierarchy()` (`/Root/<node name>` — with FESPP these
  are the assembly rep paths).
- Mapping: tree **eye** = add/remove one selector on THAT view's rep (O(1), no
  Show/Hide of N sources); per-view **colour/LUT** = `BlockColorArrayNames` /
  `BlockLookupTables` (+ the existing view-scoped LUT machinery); per-view
  **z-scale** = `rep.Scale`; per-view **time** = native `ViewTime`; per-view
  **realization** = per-view choice of the suffixed array (`<title>_real_<idx>`).
- Per-(grid,view) **filters** (IJK crop…) = on-demand concrete extraction, only
  for the grid(s) actively filtered in that view (§4 ESG caveat applies).
- Memory: today's V2 costs O(R×V) proxies (clone + extractor + slice + clip +
  chain per rep per view); this costs 1 source + V composite reps + O(filtered)
  extracts.

## 7. Open questions / TODO for the implementation day

- [ ] Confirm the composite-selection block-id field in the Trame view selection
      handler (which key: `COMPOSITE_INDEX`, assembly node id, or selector path).
- [ ] Wire per-block LUTs (`BlockLookupTables` / `BlockColorArrayNames`) to the
      existing colour-editor / scene-LUT machinery (per-view scoped LUTs).
- [ ] On-demand `EnergisticsExtractor` lifecycle for filtered grids: create when a
      grid gets a slice/clip, drop when the filter is removed.
- [ ] Decide how thresholds map (composite auto-loop vs per-block threshold).
- [ ] Keep the leaf-rep fix meanwhile — the composite rep is ONE rep, so the
      leaf-rep patch is harmless/irrelevant there, but it still protects any
      residual per-source Show paths during migration.

## 8. Separate issue — the surface load crash is upstream (FESPP C++)

Independent of all the above: loading "all surfaces" still crashes in **FESPP's
`vtkEPCCollector`** (`std::bad_alloc` allocating a ~61 MB `vtkFloatArray` +
`vtkDataAssembly` XML) — i.e. **data loading / assembly building**, not the
representation side. The leaf-rep fix and this composite proposal do NOT address
it (they're downstream of the collector). This is a FESPP-side memory issue to
investigate separately (same arena-fragmentation class, but in the collector).
