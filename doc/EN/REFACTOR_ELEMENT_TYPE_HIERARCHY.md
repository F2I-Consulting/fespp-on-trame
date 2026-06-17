# Refactor — Element type hierarchy (ElementType)

> Status: **in progress** — **Steps 0, 1, 2, 3, 5 done** (the hierarchy +
> resolver in the [element_type/](../../fespp_on_trame/app/core/element_type/) package,
> and the tracking / eye / visibility-predicate / channel-detection layers
> now DELEGATE to it; see §5). **Step 4 (moving BEHAVIOUR into the classes —
> child management, visibility, source construction) is largely done (4.1–4.3)**
> via the strategy pattern (Option A: `RepInScene` keeps the per-view state
> and passes itself as `ris`); the IJK pipeline builder + threshold/resolver
> delegation are follow-ups. Each landed step is a behaviour-preserving pure
> refactor.
> Goal: replace the scattered `if kind == ...` with a hierarchy of
> classes by inheritance, so that a change to one type no longer breaks
> the others.

---

## 1. Why this refactor

### The symptom
Behavior genuinely diverges per RESQML element type (IjkGrid,
surface, trajectory, log frame, marker frame, …), but today
this divergence is expressed by `if kind == "..."` branches **scattered
across ~7 independent files**:

| Layer | File | Branches per type |
|---|---|---|
| Tree (model) | [tree.py](../../fespp_on_trame/app/core/tree.py) | `_representation_type_in`, `is_grouping`, reservoir/surface/well routing |
| Tracking | [data_load.py](../../fespp_on_trame/app/core/engine/data_load.py) | `_DATA_ARRAY_KINDS`, `_update_data_array_tracking`, `_update_marker_tracking` |
| Tree (view) | [tree_views.py](../../fespp_on_trame/app/ui/drawer/tree_views.py) | `_eye_slot` (rep / array / marker eye) |
| Coloring | [active_array.py](../../fespp_on_trame/app/core/engine/active_array.py) | `is_channel` |
| Visibility | [visibility.py](../../fespp_on_trame/app/core/engine/visibility.py) | `toggle_rep_visibility` (Frame case), `toggle_marker_visibility` |
| Per-view source | [rep_in_scene.py](../../fespp_on_trame/app/core/sources/rep_in_scene.py) | `_is_ijk_grid`, `_is_wellbore_frame`, `_is_marker_frame`, `_channelless_frame` |
| Legacy source | [ijkgrid.py](../../fespp_on_trame/app/core/sources/ijkgrid.py), [extract_block.py](../../fespp_on_trame/app/core/sources/extract_block.py) | classes per type (already) |

### The triggering incident
While adding the "logs displayable one at a time" feature (originally a
shared-extractor ExtractPath retarget; since reworked into one extractor
per channel — see [TYPES_PARTICULARITES.md](TYPES_PARTICULARITES.md)),
we **broke the display of reservoirs and surfaces**: the per-view
visibility logic (`_ensure_extractor`, `_refresh_parent_rep_visibility`)
is shared by ALL types, and a change designed for log frames
drifted the behavior of grids/surfaces. This is exactly the
kind of regression that inheritance eliminates: shared code lives in the
base class, specifics in the subclasses — modifying an
override does not touch siblings.

### The key observation
The **source** layer already has classes per type (`IjkGrid`,
`ExtractBlockRepresentation`). The problem is that:
1. `RepInScene` **branches on the kind** instead of delegating;
2. the tree / tracking / visibility / color layers each branch **on
   their own side** on the kind strings, with no common point of truth.

So we do **not** want "a class from scratch" (which would duplicate
all the per-view plumbing, orthogonal to the type), but **a hierarchy of
element types to which the layers delegate**.

---

## 2. Principle: 3-level inheritance (general → group → unit)

```
ElementType                         (général — comportement par défaut)
├── Grouping                        (dossier : pas de source, sélection tri-state)
│     • Collection, Wellbore, Feature, Interpretation, Partial
│
├── Representation                  (a une géométrie, un œil, une source par-vue)
│   ├── GridRep                     (grille réservoir : slicers/volume/threshold)
│   │     • IjkGrid, UnstructuredGrid, SubRep
│   ├── SurfaceRep                  (géométrie simple : 1 extracteur, show/hide + couleur)
│   │     • Grid2d, PointSet, Polyline, PolylineSet, TriangulatedSet
│   ├── WellboreGeometryRep         (tube simple : 1 extracteur)
│   │     • Trajectory, Completion, Perfo
│   └── FrameRep                    (conteneur de sous-partitions commutables)
│       ├── ChannelFrameRep         (WellboreFrame : 1 log à la fois — 1 extracteur par channel, show exclusif)
│       └── MarkerFrameRep          (WellboreMarkerFrame : N markers — 1 extracteur par marker)
│
└── Leaf                            (sous-élément d'une rep, pas une rep)
    ├── PropertyLeaf                (colore la rep parente ; un channel EST ça sous un Frame)
    └── MarkerLeaf                  (toggle la visibilité d'UN marker)
```

- **General level (`ElementType`)**: the default behavior + the contract
  (methods that any subclass can override).
- **Group level** (`GridRep`, `SurfaceRep`, `FrameRep`, …): what is common
  to a family (e.g. all grids share the slicers pipeline).
- **Unit level** (`IjkGrid`, `MarkerFrameRep`, …): the specificity of a single
  type.

### The golden rule (what you were looking for)
> Before writing a change, ask yourself: **at what level is this behavior
> true?**
> - True for everything → `ElementType` (base).
> - True for a family → the group class (`GridRep`, `FrameRep`, …).
> - True for a single type → the unit class.
>
> Write the change **at the highest level where it is correct**, and **never
> higher**. Result: zero duplication, and an override cannot break
> a sibling.

---

## 3. The contract (what each class owns)

Each `ElementType` exposes a single contract that the 7 layers consume instead
of branching on the kind:

```python
class ElementType:
    # --- Identité -------------------------------------------------
    KINDS: tuple[str, ...]        # kinds runtime que cette classe matche
    @classmethod
    def matches(cls, kind) -> bool

    # --- Rôle dans l'arbre (couches tree.py / tree_views.py) -------
    def tree_role(self) -> "TreeRole"      # FOLDER | REPRESENTATION | LEAF
    def is_grouping(self) -> bool
    def eye_descriptor(self) -> "EyeDescriptor | None"
        # type d'œil (rep / array / marker), couleur, multi-select ?,
        # controller à câbler (toggle_rep_visibility / _color / _marker)

    # --- Tracking (couche data_load.py) ---------------------------
    def tracking_bucket(self) -> str | None
        # "rep" | "array" | "marker" | None

    # --- Source / pipeline par-vue (rep_in_scene.py) --------------
    def make_source(self, scene) -> "SourceHandle"
    def visibility_policy(self) -> "VisibilityPolicy"
        # STANDARD | IJK_MODAL | ONE_AT_A_TIME | MULTI | NONE
    def color_policy(self) -> "ColorPolicy"
        # COLORABLE | VISIBILITY_ONLY | NONE
```

Example of specialization (what would have prevented the logs→surface incident):

| Behavior | Level where it lives | Classes concerned |
|---|---|---|
| "hide when non-active at load" | `Representation` (base of reps) | all reps, **only once** |
| "1 log at a time" | `ChannelFrameRep` | only log frames |
| "N markers, one eye per marker" | `MarkerFrameRep` | only marker frames |
| "I/J/K slicers + volume" | `GridRep` | IjkGrid + UnstructuredGrid + Sub |
| "no color, visibility only" | `color_policy()` overridden | `MarkerLeaf` |

---

## 4. Integration with the existing per-view architecture

The per-view architecture (`ViewScene` / `RepInScene`) **does not change role**: it
remains the (rep, view) multiplexing. We just add an `element_type` member
and replace its `if self._is_*()` with calls to the contract:

```python
class RepInScene:
    def __init__(self, scene, rep_path):
        self.element_type = ElementType.for_path(scene.tree, rep_path)  # ← 1 résolution
    def source(self):
        return self.element_type.make_source(self.scene)               # ← délégation
    def _refresh_parent_rep_visibility(self):
        self.element_type.visibility_policy().refresh(self, self.scene) # ← délégation
```

Two options for "where the per-view state lives":
- **(A) Stateless strategy**: `ElementType` is a stateless singleton;
  `RepInScene` keeps the state (extractors, selected channel, visible markers)
  and passes it as an argument. *Recommended* — minimizes coupling, reuses
  `RepInScene` as is.
- **(B) Subclasses of `RepInScene`**: `IjkRepInScene`, `MarkerFrameRepInScene`,
  … More "pure object" but duplicates the per-view plumbing and complicates the view
  split. *To avoid on the first pass.*

→ We go with **(A)**: `RepInScene` delegates the *semantics* to `element_type`,
and keeps the *per-view mechanics*.

---

## 5. Incremental migration plan (low risk)

We do **not** rewrite all at once. Proposed order, each step testable on its own:

1. **Step 0 — `element_type.py` + `ElementType.for_path()`** ✅ **done**
   Class hierarchy + a `kind → class` resolver (`for_kind` / `for_path`),
   stateless singletons, the declarative contract (`tree_role`,
   `is_grouping`, `eye_descriptor`, `tracking_bucket`, `visibility_policy`,
   `color_policy`, `primary_hidden`); `make_source` is a Step-4 placeholder.
   No caller yet → *zero behaviour change*. Guarded by `test_element_type.py`
   (incl. a sync check that `PropertyLeaf.KINDS == data_load._DATA_ARRAY_KINDS`).

2. **Step 1 — Consolidate the tracking decisions** (data_load) ✅ **done**
   `_DATA_ARRAY_KINDS` removed; `_update_data_array_tracking` /
   `_update_marker_tracking` now test
   `element_type.for_kind(kind).tracking_bucket()`. One place for "this
   kind feeds which bucket".

3. **Step 2 — Consolidate the eye** (tree_views + tree) ✅ **done**
   `tree.py` emits a per-node `eye` token via `element_type.eye_descriptor()`
   (and `is_grouping` via `element_type.is_grouping()`); the three tree-view
   JS gates read `item.eye === 'rep'/'array'/'marker'` instead of the
   `item.type !== 'Frame'` kind checks.

4. **Step 3 — Consolidate visibility** (rep_in_scene) ✅ **done**
   `RepInScene` resolves `self.element_type` (lazy); `_is_ijk_grid` /
   `_is_wellbore_frame` / `_is_marker_frame` / `_channelless_frame` now
   delegate (`isinstance(…)` / `primary_hidden()`). Callers unchanged.

5. **Step 4 — Move BEHAVIOUR into the classes** (the strategy pattern,
   Option A) — **largely done** (the classes were "too thin" with only
   declarative tags; now they carry the per-type logic, `RepInScene` keeps
   the state and passes itself as `ris`):
   - **4.1 ✅ child management** — `ChannelFrameRep` / `MarkerFrameRep` own
     `set_child_visible` (the EXCLUSIVE-vs-MULTI override boundary),
     `child_source`, `visible_child_*`, `set_child_color`; the shared
     `_create_child_extractor` is on `FrameRep`.
   - **4.2 ✅ visibility** — `refresh_primary_visibility(ris)` /
     `hide_in_view(ris)` per type (Representation standard / IjkGridRep IJK /
     FrameRep force-hide); `RepInScene` keeps only the shared guards.
   - **4.3 ✅ source** — `Representation.ensure_extractor(ris)` builds the
     per-view extractor; `ensure_source(ris)` routes (IjkGridRep → the IJK
     pipeline). `source()` no longer branches on `_is_ijk_grid`.
   - **IJK pipeline ✅** — `_ensure_per_view_ijk` moved into
     `IjkGridRep.ensure_per_view_ijk(ris)`; `RepInScene` keeps only the
     `_hide_legacy_ijk` / `refresh_per_view_ijk_property` plumbing.
   - **4b ✅ source_resolver** — `sources_for_rep_path` /
     `color_sources_for_rep_path` / `resolve_array_for_path` delegate to
     `rendered_sources(ris)` / `color_sources(ris)` /
     `array_candidate_source(ris, path)` (0 predicate uses left in
     source_resolver); the legacy registry fallbacks stay there.
   - **4.4 threshold ⏭ skipped (low value)** — the threshold cluster already
     dispatches via `_is_ijk_grid` (which delegates to
     `isinstance(IjkGridRep)`); moving it to a `threshold_provider` wouldn't
     make a class substantive (the local chain stays in `RepInScene`) and
     would need recursion-avoiding renames. Left as-is.

   Net: the type-string branching is eliminated except the predicate
   *definitions* (the delegators) and the threshold cluster. All
   behaviour-preserving.

6. **Step 5 — Coloring** (active_array) ✅ **done**
   `is_channel` now = `element_type.for_kind(rep_kind).visibility_policy()
   == ONE_AT_A_TIME and r_id != node_id`; `_show_channel_active_view`
   delegates the same way.

After each step: the app must behave **exactly** as before
(pure refactor). We keep the `_is_*` as deprecated aliases as long as a caller
uses them, then we remove them.

---

## 6. What it concretely changes (replaying the incident)

**Before** (today): "1 log at a time" touched `_ensure_extractor`
(shared) → broke grids + surfaces. Fix = add `_channelless_frame` guards
everywhere, which re-branch on the kind.

**After** (target): "1 log at a time" = override `visibility_policy()` in
`ChannelFrameRep` only. `GridRep` and `SurfaceRep` inherit the
standard behavior, **unchanged**, **impossible to break** from the
frames code.

---

## 7. Risks & safeguards

- **Large scope, hot paths.** → incremental migration (§5), each
  step = pure refactor tested.
- **The runtime kind ≠ C++ enum name.** `SimplifyXmlTag` produces `'Frame'`,
  `'MarkerFrame'`, `'Marker'` (not `'WellboreFrame'` / `'WellboreMarker'`). The
  `KINDS` table must use the **runtime** strings. Cf. the trap already present
  in `_representation_type_in` (`'WellboreMarker'` is dead there).
- **The per-view axis stays orthogonal.** Do not merge `ElementType` and
  `RepInScene` (option A, not B).
- **Partial.** `Partial` remains a non-selectable `Grouping`-like —
  keep `find_all_selectable_descendant_ids` which excludes it.

---

## 8. Migration inventory (correspondence table)

| Today (`if kind`) | Tomorrow (class / method) |
|---|---|
| `tree._representation_type_in` | `ElementType.tree_role() == REPRESENTATION` |
| `tree.is_grouping` | `ElementType.is_grouping()` |
| `data_load._DATA_ARRAY_KINDS` | `PropertyLeaf.tracking_bucket() == "array"` |
| `data_load._update_marker_tracking` | `MarkerLeaf.tracking_bucket() == "marker"` |
| `tree_views` is_loaded_rep/array/marker | `ElementType.eye_descriptor()` |
| `active_array.is_channel` | `ChannelFrameRep` + `visibility_policy() == ONE_AT_A_TIME` |
| `rep_in_scene._is_ijk_grid` | `isinstance(element_type, IjkGridRep)` |
| `rep_in_scene._is_wellbore_frame` | `isinstance(element_type, ChannelFrameRep)` |
| `rep_in_scene._is_marker_frame` | `isinstance(element_type, MarkerFrameRep)` |
| `rep_in_scene._channelless_frame` | `FrameRep.visibility_policy().primary_hidden()` |
| `visibility.toggle_marker_visibility` | `MarkerLeaf` / `MarkerFrameRep.set_visible()` |

---

## 8 bis. Important clarification: FOLDER (tree) ≠ Grouping (family)

An investigation into the Frame/MarkerFrame subsystem surfaced a
distinction that the hierarchy must explicitly enact:

> **The "FOLDER" role in the tree is orthogonal to owning a
> source.** A `FrameRep` (WellboreFrame / WellboreMarkerFrame) is a
> **FOLDER in the tree** (no eye, checking = selecting all children,
> tri-state checkbox) **but a Representation in the source layer** (it
> owns the clone + the per-view `EnergisticsExtractor`; it is the render anchor
> of the channels/markers). On the C++ side it is a `MapperType::MapperSet` — a
> container that owns the geometry of its children — not an `isGroupingType`.

Consequences for the contract:
- `tree_role()` must be able to return `FOLDER` **without** implying
  `is_grouping()=="no source"`. `FrameRep`: `tree_role()==FOLDER`,
  `eye_descriptor()==None`, `propagates_selection()==True`, **but remains a
  subclass of `Representation`** (it has `make_source()`).
- `ChannelFrameRep`: `visibility_policy()==ONE_AT_A_TIME`; children =
  `PropertyLeaf` (`tracking_bucket=='array'`, `COLORABLE`).
- `MarkerFrameRep`: `visibility_policy()==MULTI`; children = `MarkerLeaf`
  (`tracking_bucket=='marker'`, `VISIBILITY_ONLY`).

**Step 2/3 partially started** (outside the hierarchy, as a fix): Frame /
MarkerFrame have already become folders-for-the-tree via `is_grouping`
(selection propagation + eye removal), while remaining in
`_representation_type_in` (render anchor). The refactor will consolidate this
dual role into `FrameRep` instead of expressing it through two separate mechanisms
(`is_grouping` vs `_representation_type_in`).

## 9. Expected decision

Before launching the implementation:
- **Option A** (delegated strategy, `RepInScene` keeps the state) — recommended.
- Start with **Step 0 + 1** (hierarchy creation + tracking) which are the
  least risky and already provide "a single place per type".

> Once this doc is validated, we tackle Step 0 in a dedicated branch, separate
> from the bug-fixes in progress.
