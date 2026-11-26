# V2 target architecture — **BlockScope-Native**

> **Status: DECIDED (2026-07-02).** Output of a 5-candidate design panel (incremental
> hardening / shared-PDC per-view / PV-native maximalist / C++-assisted / client-forward)
> scored by 3 judges (PV core engineer, solo maintainer, perf engineer) on robustness,
> PV-idiomacy, performance, memory, maintainability, migration realism — **BlockScope won
> unanimously**, executed with the best ideas grafted from every other candidate.
> All load-bearing mechanisms are **live-validated** on the exact target build
> (PV 6.0.1 / VTK 9.5.2, probes in PARAVIEW.md). Complements
> [COMPOSITE_REARCHITECTURE.md](COMPOSITE_REARCHITECTURE.md) (the seed idea) and
> supersedes the incremental-only reading of [ENGINE_MAP.md](ENGINE_MAP.md).

## 0. One-paragraph summary

ParaView already solved multi-object multi-view rendering: a representation is natively
scoped per **(source, view)**, and a composite representation natively drives per-block
visibility/colour/LUT. FESPP already emits the perfect input — **ONE
`vtkPartitionedDataSetCollection` + `vtkDataAssembly`** whose node paths ARE our rep
paths. So: the session owns **exactly one data source**; each view owns **exactly one
composite representation** of it; an app "rep" stops being a proxy and becomes an
**assembly-path string**. Proxies are created **only** where ParaView genuinely cannot
express something per-block — the validated ESG constraint — and then on-demand,
refcounted, released. Load = a `Selectors` edit. Eye = a `BlockSelectors` edit.
Colour = a `BlockLookupTables` entry. The crash class (13.5 MB × R composite reps) and
the O(N²) marker churn become **structurally unreachable**, not mitigated.

## 1. The three layers

### Layer S — SESSION (one per trame session)
| Component | Role |
|---|---|
| **Collector** (kept) | The single FESPP EPCCollector, `ExplicitSelection=true`; its `Selectors` property IS the loaded set. The ONLY steady-state data proxy. `vtkEPCCollectorClone` is **deleted**. |
| **AssemblyIndex** (new, ~150 lines) | Wraps `GetDataInformation().GetHierarchy()`. Bidirectional maps rep_path ↔ assembly selector (`/Root/...`) ↔ flat composite index (picking). Rebuilt once per Selectors commit. Replaces source_registry tree-walks. |
| **LutManager** (new) | Wraps `vtkSMTransferFunctionManager` under the existing `"array__viewId"` keys; refcounted per (view, array); view_scene.py seeding logic ported verbatim. Exports RGBPoints/annotations as JSON for the DOM legend. |
| **ExtractPool** (new) | Refcounted + LRU-capped (default 4) shared per-grid `EnergisticsExtractor`s — created only when a grid needs a concrete ESG (IJK crop) or numpy access; controller-registered. |
| **PV plugin** `pv_plugins/fespp_trame_filters.py` | `@smproxy` **MarkerCategorizer** (marker names → categorical int array + Annotations). Superseded by the C++ `MarkerNameId` array when that ticket lands. |
| **RenderScheduler + StateBatcher** (`app/wire/`) | Dirty-view set drained once per trame transaction — exactly ONE `Render(view)`+`html_view.update()` per dirty view; hold-commit/debounce for continuous controls; `load_generation` counter stamps deferred callbacks/caches. |

### Layer V — VIEW (one **PdcScene** per dockview render panel; scene_registry facade kept)
- **main_rep** = `controller.Show(collector, pv_view)` → ONE composite rep per view.
  Carries: `BlockSelectors` (eye) · `BlockColorArrayNames`/`BlockLookupTables`/
  `BlockMapScalars`/`BlockOpacities`/`BlockUseSeparateColorMaps` (colour) ·
  `SelectedBlockSelectors` (highlight) · `Scale=[1,1,z]` (z-scale) · `view.ViewTime` (time).
- **block_state** — THE robustness backbone: pure-Python desired-state table
  `{selector → {visible, color_array, assoc, lut_key, opacity, solid_rgb}}` +
  `reconcile()` which regenerates ALL Block* lists from the table. Every mutation is
  desired-state-first; the rep is a **projection of the dict** — idempotent repair after
  any structure change, view split, reconnect, or dropped render. Empty-visible-set =
  never-matching sentinel selector (one constant, one module).
- **DOM SVG legend** per panel from LutManager's RGBPoints JSON — **zero PV scalar-bar
  proxies** (block-LUT bars are unmanaged by UpdateScalarBars anyway; DOM is crisper and
  intrinsically per-panel).
- **Wellheads**: kept — Text source per well (session) + `TextSourceRepresentation` per
  (well, view) shown (light, no label subrep; leaf lacks TextPropMode).

### Layer O — ON-DEMAND (per actively-filtered (rep,view), refcounted, controller-registered)
- **GridIsolate** (ESG path): `ExtractPool.acquire(grid)` → shared concrete
  `vtkExplicitStructuredGrid` (type-asserted — the composite can NEVER reach
  `ExplicitStructuredGridCrop`) → per-(grid,view) crop + ijkgrid.py slicer math → **leaf
  SurfaceRepresentation** (0.75 MB; colour via direct
  `ColorArrayName+LookupTable+MapScalars`, never `ColorBy`) shown only in that view.
  While active, the grid's selector is swapped OUT of that view's BlockSelectors; release
  restores it, controller cascade deletes crop→(extractor at refcount 0).
- **BlockIsolate** (generic path): `ExtractBlock(Input=PDC, Selectors=[rep_path])`
  (composite-safe PDC→PDC) → slice/clip/threshold chains (auto-loop at concrete types)
  → leaf rep in that view. Same swap-out/refcount/release. Also serves a rep needing a
  divergent Representation type (composite rep = one type per view).
- **Diff**: PythonCalculator on a BlockIsolate (same-rep A−B) or two isolates +
  AppendAttributes; released on panel close.
- **endpoint_resolver(rep_path, view_id)** — THE single data seam for stats/distribution/
  compare/diff: isolate chain tail if the view filters that rep, else the PDC block
  (builtin-mode zero-copy `GetClientSideObject()` + `vtkDataAssembly.SelectNodes`).

**Canonical data flow:** checkbox → `Selectors` write → one C++ pipeline pass →
AssemblyIndex refresh → every `PdcScene.reconcile()` → RenderScheduler flush (one render
per dirty view). Eye/colour/z/time/realization = single property writes on ONE view's rep
+ one deferred render; they never touch the data layer.

## 2. Proxy inventory & numbers

Per (rep, view): **ZERO proxies** — a rep is a string in property lists + a dict entry.

| Scope | Proxies |
|---|---|
| Session | 1 collector · K≤4 shared extractors (LRU) · M MarkerCategorizer (→0 with C++ MarkerNameId) · 0-1 diff calc · W Text sources |
| Per view | 1 RenderView + **1 composite rep (~13.5 MB — the only place that cost exists, CONSTANT in R)** · A LUT/PWF (tiny) · 0 scalar bars · W_v text reps |
| Per filtered (rep,view) | 1 chain root + 1-3 filters + 1 leaf rep (0.75 MB) — on demand only |

- R=150, V=3: **~170 proxies** total (vs ~450+ per-view stacks today; vs ~2 GB rep memory pre-fix).
- R=200, V=4: rep memory = 4×13.5 ≈ **54 MB, constant in R**; ~200-260 proxies (vs ~1700 incremental).
- Per-interaction: eye O(1)+1 render · mass load O(R) strings + ONE pipeline pass, zero
  proxy churn · colour/time/realization/z O(1) per view · marker bulk O(M) LUT edits
  (was O(N²)) · unload O(V+F) list edits, no Delete storms · view close = controller cascade.

## 3. The 14 concerns (mechanism per concern)

1. **Mass load 150+** — one Selectors write + one UpdatePipeline; rep-side bad_alloc structurally impossible; upstream collector bad_alloc = the C++ ticket; interim = chunked commits + busy overlay; leaf-rep monkeypatch protects residuals until Phase 1 retires it.
2. **Eye per view** — `block_state[selector].visible` → reconcile → BlockSelectors (the MultiBlock-Inspector mechanism). Folder eye = one subtree selector.
3. **Colour+LUT+legend per view** — BlockColorArrayNames/BlockLookupTables → `"array__viewId"` TF-manager LUTs; `BlockUseSeparateColorMaps=1`; DOM SVG legend; solid colour = BlockColors if Probe Day confirms, else 1-point-LUT fallback; **never `pvsimple.ColorBy`** (one audited facade).
4. **Z-scale per view** — built on 2026-11-04 (`ui_scale_z__<vid>`, `state_defaults.z_scale_of`). The mechanism as planned: `ui_scale_z_by_view` → `main_rep.Scale` + isolate/text reps loop; hold-commit throttled.
5. **Time per view** — native `view.ViewTime` (zero duplication).
6. **Realization per view** — suffixed arrays `<title>_real_<idx>` as the view's Block* colour entry.
7. **IJK / ESG per (grid,view)** — GridIsolate (shared extractor + per-view crop + leaf rep + selector swap-out); "copy from view" replays snapshot/apply onto the isolate.
8. **Thresholds** — whole-scene: one Threshold on the PDC (auto-loop); per-rep chain: BlockIsolate + threshold_chain.py unchanged.
9. **Markers** — blocks of the PDC; bulk = Selectors edits; per-marker eye via per-marker assembly nodes (Probe Day) else categorical LUT (`IndexedOpacities` 0/1 per name) — fulfills the Well-Marker-LUT plan with O(1) proxies.
10. **Picking per view** — highlight = `SelectedBlockSelectors`; click-pick = `SelectSurfaceCells` → composite selection → AssemblyIndex → tree node.
11. **Diff** — calculator on isolate(s), diverging `"__diffView"` LUT, full release on close.
12. **Wellheads** — kept verbatim (TextSourceRepresentation flagpole/billboard).
13. **Lifecycle** — ALL proxies controller-registered (cascading unregister); unload = Selectors removal + block_state drop + isolate release + LUT decref + reconcile; UUID-stable assembly paths (C++ contract); view close purges every `*_by_view` bucket; `load_generation` rejects stale callbacks; dev-mode proxy-census leak audit; teardown exceptions logged with (view_id, rep_path, role) — never swallowed.
14. **Stats/distribution/compare** — all through `endpoint_resolver`; cheap ranges from per-block `vtkPVDataInformation` (`GetComponentRange(-1)`=magnitude); full stats via zero-copy block access + numpy; results cross the wire as bins/quantiles JSON (<10 KB); stats_dispatch splits stats_core/bindings, signatures preserved.

## 4. Deleted vs kept

**DELETED** (by phase): vtkEPCCollectorClone + `_create_clone` (P1) · eager
`_eager_setup_rep_in_scene` / RepInScene per-(rep,view) extraction (P1→P5; snapshot/apply
primitives survive on isolates) · representation.py N-source creation + extract_block.py
per-rep path (P3/P5) · source_registry per-rep instances (→ AssemblyIndex +
endpoint_resolver) · leaf_rep.py's **global monkeypatch** (retired end P1; the technique
survives as the isolates' display facade) · per-marker extractors (P4) · PV scalar-bar
plumbing + swap_to_scene_tfs juggling (P2) · ALL `pvsimple.ColorBy` sites ·
mirror_legacy_ijk_state (P3a) · the 806-line `boot_v2_engine` + 1640-line engine boot +
1274-line stats_dispatch god-functions (decomposed incrementally) · ViewScene._luts/_pwfs
hand bookkeeping (→ LutManager).

**KEPT**: collector.py, tree.py, selector.py, the data_load selection→Selectors flow (the
session contract) · scene_registry facade (owns PdcScene) · the `"array__viewId"` LUT
convention + seeding logic · ijkgrid slicer math, threshold_chain, slice/clip planes
(re-rooted on isolates) · wellhead.py · diff.py flow (re-rooted) · **all `*_by_view`
buckets, drawer/tree_views wiring, and every dispatcher public signature** (bodies
retarget; call sites never move — the session-vs-view blueprint stays valid) ·
statistics/distribution panel UIs · the hold-commit stepper pattern · vtk_log ·
the headless pvpython harness · **fix/mass-load-crash-leaf-rep** (merged first).

## 5. Migration roadmap (each phase shippable, old path behind a flag until its gate)

| Phase | Content | Durée | Gate |
|---|---|---|---|
| **0 — freebies + filet** (jours) | Merge `fix/mass-load-crash-leaf-rep` · RenderScheduler/StateBatcher · `interactive_ratio=0.5` (1 ligne, ~4× interactive) · debounce z/opacity/slicers · `load_generation` · narrow les ~40 `except: pass` · **harnais headless leak-audit** (load 150 → unload → assert proxy census) | days | harnais vert |
| **PROBE DAY** (gate dur avant P1) | 7 probes pvpython scriptées (`tools/probes/` + résultats dans PARAVIEW.md): BlockColors solid · BlockOpacities×SeparateColorMaps corners · persistance Block* après changement d'assembly · sémantique BlockSelectors vide (sentinel) · clé block-id de la sélection composite · granularité assembly markers (per-marker vs per-frame) · **coût AddSelector incrémental** (re-lit l'EPC ?) | 0.5-1 j | tout probé, fallbacks documentés |
| **C++ TRACK** (parallèle, 1 ticket, 1 SuperBuild; Python ne bloque jamais dessus) | vtkEPCCollector: pre-size le vtkFloatArray ~61 MB (`SetNumberOfTuples` once) + vtkDataAssembly incrémental (fix du crash "all surfaces") · noms d'assembly UUID-stables (contrat reload) · `RemoveExtract(repPath)` · MarkerNameId + annotations. Différé: vtkEnergisticsBlockCrop (endgame). Jamais: custom vtkPVDataRepresentation. | 1 ticket | build + all-surfaces passe |
| **1 — backbone composite** (1-2 sem) | PdcScene (main_rep + block_state + reconcile) sous flag · AssemblyIndex · load = Selectors-only · eye → BlockSelectors · delete clone · désactive l'extraction eager | 1-2 sem | 150 reps + 2 vues, eyes per-view, no crash, parité screenshots → **retire le monkeypatch** |
| **2 — couleur per-block + knobs per-view** (1-2 sem, après Probe Day) | LutManager · `apply_color_array` → Block* (signature inchangée) · légende DOM SVG · z-scale/ViewTime/realization per-view · fix camera card (classes=""/style="") | 1-2 sem | 2 vues divergentes couleur/z/time/real, COE sans bleed |
| **3 — isolates à la demande** (3-4 sem, sous-gates) | **3a IJK**: ExtractPool + GridIsolate, slicer_dispatch retarget, delete mirror_legacy_ijk_state · **3b slice/clip/threshold**: BlockIsolate + re-root threshold_chain · **3c stats/diff/compare**: endpoint_resolver, split stats_core/bindings, bins-over-wire | 3-4 sem | IJK divergent par vue; release restaure le bloc; parité stats |
| **4 — markers + picking** (1-2 sem) | Markers = blocks + LUT catégorielle (ou MarkerNameId C++) · retire les extracteurs per-marker · SelectedBlockSelectors + click-pick → AssemblyIndex | 1-2 sem | bulk markers fluide; pick → nœud d'arbre |
| **5 — deletion + docs** (1 sem) | Delete N-source/extract_block/shims/RepInScene residue · fin des décompositions boot · réécrit ENGINE_MAP · sync doc/wiki (+EN/FR disque) | 1 sem | grep-clean |

**Mapping de l'audit incrémental** (17 items, workflow séparé): ranks 1-2 = Phase 0
(leaf-rep merge, double stats recompute + debounce — à faire tout de suite) · ranks 3-9
(skip eager hidden builds, reverse index O(1), lifecycle per_view_state.py, CSV teardown,
view_routing, vtk_compute, hygiène shell) = valables en intérim, la plupart absorbées par
P1/P2 · ranks 10-15 (analysis_wiring, consolidation post-load, diff-scope active_array,
view_update_for, décomposition boot, threading du registry) = à faire pendant P1-P3 (elles
préparent les mêmes fichiers) · ranks 16-17 = **supersédées** par P1/P3 (le skip legacy-IjkGrid
et l'intent-visibility unique deviennent respectivement l'isolate et BlockSelectors).

## 6. Risk register (top 5 + de-risk)

| # | Risque | Mitigation | De-risk TÔT |
|---|---|---|---|
| R1 | Coins de l'API Block* sur PV 6.0.1 (BlockColors, opacité×SeparateColorMaps, persistance des listes) | reconcile() ré-affirme TOUT après chaque changement de structure; fallback 1-point-LUT; une seule facade couleur | Probe Day 1-3 |
| R2 | Coût FESPP d'un Selectors incrémental (re-lecture EPC ?) | write Selectors batché/transaction + overlay; commits chunkés; fix allocateur C++ | Probe Day 7 (timing 1/+10/+100 reps) |
| R3 | Régression du recâblage dispatchers (P3, ~4k lignes chaudes) | split 3a/3b/3c avec gates; signatures préservées; flag + harnais census/pixels; **pausable 1 mois après chaque sous-phase** | le harnais Phase 0 EST le harnais de régression |
| R4 | Pics mémoire/latence des isolates (grosses ESG) | refcount + LRU cap (4, configurable); extracteur partagé par grille; spinner; octets mesurés par type | harnais P0 mesure 1 extraction/type de rep |
| R5 | Clé block-id de la sélection composite incertaine | AssemblyIndex maintient selector↔flat-index (rebuild par commit); highlight (SelectedBlockSelectors) marche quoi qu'il arrive et ship d'abord | Probe Day 5 |

## 7. PV-native scorecard ("ParaView-parlant")

**Natif** (16 mécanismes): PDC+vtkDataAssembly comme modèle de données · ExplicitSelection/Selectors
comme contrat de load · reps per-(source,view) · l'API Block* (celle du MultiBlock
Inspector Qt — on hérite de la surface de test Kitware) · vtkSMParaViewPipelineControllerWithRendering
pour TOUT le lifecycle · vtkSMTransferFunctionManager · view.ViewTime · ExtractBlock
PDC→PDC + auto-loop composite · EnergisticsExtractor strictement pour l'ESG (type-fence) ·
arrays suffixés (réalisations) · LUT catégorielle (markers) · SelectSurfaceCells +
SelectedBlockSelectors (aucun sub-rep sélection/label instancié) · plugin
@smproxy VTKPythonAlgorithmBase (jamais de monkeypatch) · vtkPVDataInformation per-block
(stats zéro-fetch) · TextSourceRepresentation (wellheads) · leaf SurfaceRepresentation
pour les isolates (idiome ColorBy-free validé).

**Îlots non-natifs assumés** (chacun justifié, contenu, 1 module): block_state+reconcile
(le réconciliateur déclaratif que PV n'a pas — c'est LA robustesse) · légende DOM SVG ·
selector sentinelle · RenderScheduler/StateBatcher (transactions trame) · LRU ExtractPool.

**Banni**: monkeypatch global pvsimple (retiré fin P1) · pvsimple.ColorBy · crop ESG sur
composite · proxies-par-rep comme modèle d'identité · custom vtkPVDataRepresentation ·
parier le planning sur la sérialisation composite vtk.js (VtkLocalView = probe futur,
markers/wellheads seulement — et l'éventuel fix du known-limit #15).
