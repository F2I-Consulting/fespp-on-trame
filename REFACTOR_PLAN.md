# Refactor plan — `core/`

État au commit `faa396c` (post-renames + flatten + cross-folder moves).

Le pass `ui/` + `io/` + `core/`-cosmétique est fait. Il restait **2 gros sujets** dans `core/` qui ont été identifiés et délibérément repoussés : l'éclatement du god-file `engine.py` et la normalisation du data-source layer. Tous les sujets (1 à 4) sont maintenant traités. Reste à exécuter un smoke-test bout-en-bout pour valider qu'aucune régression silencieuse n'a été introduite par la chaîne de refactors.

---

## Sujet 1 — Éclatement de `engine.py` (1885 LOC, prioritaire) — **DONE**

> Atterrissage : `engine.py` (1885 LOC) → `engine/boot.py` (~425 LOC) + 14 modules thématiques. Les closures ont été converties en fonctions libres prenant explicitement leurs dépendances (variante plus légère de l'option A — pas de `EngineContext` dataclass, juste des paramètres explicites). `boot.py` n'est plus qu'un orchestrateur de wiring : construction des objets (`Tree`, `Collector`, `SourceRegistry`, `Selector`, `Activator`), seeds via `init_state_defaults`, puis enregistrement des décorateurs `@state.change` / `@controller.set` qui forwardent vers les modules thématiques.
>
> Modules extraits : `vtk_log`, `state_defaults`, `source_resolver`, `threshold_dispatch`, `slicer_dispatch`, `time_realization`, `data_load`, `etp`, `panel_resolver`, `visibility`, `active_array`, `diff`, `hierarchy`, `selection_dispatch`, `view_ops`. Plus `upload_endpoint.resolve_upload_session_id` côté `io/`.

`fespp_on_trame/app/core/engine.py` est le god-file orchestrateur. Une seule fonction `initialize_fespp_engine(server, *, fespp_plugin_path)` contient ~1700 lignes de closures sur des variables locales (`_view`, `_collector`, `_ijkgrids`, `_rep_sources`, `_activator`, `_tree`, etc.). Cible : descendre à ~150 LOC dans `engine.py` (le shell d'init) et répartir le reste dans un package `engine/` thématique.

### Découpe proposée

| Fichier cible | Contenu actuel à extraire | LOC estimées |
|---|---|---|
| `engine/__init__.py` | re-export `initialize_fespp_engine` pour back-compat des imports | ~10 |
| `engine/boot.py` | `LoadPlugin`, `GetActiveViewOrCreate`, stderr tee, state setdefaults, registration des hooks `on_client_*`, route `/upload`, shell de `initialize_fespp_engine` | ~150 |
| `engine/vtk_log.py` | `_setup_stderr_tee`, `capture_vtk_messages`, `_VTK_LINE_RE`, `_ANSI_RE`, le queue + tee thread | ~80 |
| `engine/ijk_registry.py` | `_ijkgrids` dict + `_ensure_ijkgrid_for`, `_ijkgrid_by_rep_path`, `_active_ijkgrid`, `_push_active_ijk_state_to_ui` | ~80 |
| `engine/data_load.py` | `_on_change_fespp_data_selectors_impl` + helpers (sync ijkgrids, present_paths, color assignment, array tracking) | ~250 |
| `engine/source_resolver.py` | `_sources_for_rep_path`, `_color_sources_for_rep_path`, `_displays_for_rep_path`, `_resolve_array_for_path`, `_apply_color_array` | ~200 |
| `engine/visibility.py` | `toggle_rep_visibility`, `_refresh_collector_block_selectors`, `view_reset_camera` handler | ~100 |
| `engine/threshold_dispatch.py` | `threshold_add/delete/set_range/set_visible`, `_threshold_provider`, `_publish_threshold_chain`, `_hide_unused_scalar_bars`, `_refresh_threshold_ui_for_active_grid` | ~200 |
| `engine/slicer_dispatch.py` | `update_slice`, `update_range_slicer`, `update_mode_slicer`, `update_volume_visible`, `update_slices_visibility`, `ui_scale_z_update`, `_propagate_representation` | ~150 |
| `engine/time_realization.py` | `changeTimeLabel`, `update_realization_slider`, `update_real_lock` | ~80 |
| `engine/hierarchy.py` | `_push_tree_hierarchy_mode`, `_MODE_NAME_TO_INT`, `on_tree_hierarchy_mode_change` | ~70 |
| `engine/etp.py` | `connect_to_etp`, `select_etp_dataspace`, `force_etp_refresh`, `update_data_information` (côté ETP) | ~80 |

Total ≈ 1450 LOC réparties + ~150 LOC dans `boot.py` ≈ 1600. Le reste (290 LOC) c'est essentiellement les blank lines et docstrings du gros fichier actuel.

### Le **vrai** problème : les closures

Toutes ces fonctions sont aujourd'hui des fonctions internes à `initialize_fespp_engine`. Elles **capturent par closure** :

- `_view` (RenderView ParaView)
- `_collector` (Collector EPC)
- `_etp_connector`
- `_ijkgrids` (dict)
- `_rep_sources`
- `_activator`
- `_tree`
- `_selector`
- `server`, `state`, `controller`

Pour les extraire en modules séparés, deux options :

#### Option A — `EngineContext` dataclass (propre)

```python
@dataclass
class EngineContext:
    server: Server
    state: Any
    controller: Any
    view: Any
    collector: Collector
    etp_connector: ETPConnector
    tree: Tree
    rep_sources: RepSources
    ijkgrids: dict[int, IjkGrid] = field(default_factory=dict)
    selector: Selector | None = None
    activator: Activator | None = None
```

Chaque module reçoit `ctx: EngineContext` en argument. Avantages : explicite, testable, pas de globals. Inconvénients : signature de ~50 fonctions à changer, beaucoup de `ctx.collector` partout.

#### Option B — Variables module-level dans `engine/state.py` (moins propre, plus rapide)

```python
# engine/state.py
view = None
collector = None
ijkgrids: dict = {}
# ...

def init(server, fespp_plugin_path):
    global view, collector, ijkgrids
    view = pvsimple.GetActiveViewOrCreate(...)
    # ...
```

Les autres modules font `from engine import state` et lisent `state.collector`. Avantages : peu de changements de signature. Inconvénients : globals mutables, ordre d'init fragile.

**Recommandation** : Option A. C'est plus de travail (~30% de plus) mais ça aligne le data layer avec ce qu'on a fait dans `ui/` (passage explicite de `state`/`controller` aux constructeurs).

### Procédure d'exécution

1. Créer `engine/__init__.py` qui re-exporte `initialize_fespp_engine` depuis l'ancien `engine.py` renommé temporairement.
2. Créer la dataclass `EngineContext` dans `engine/context.py`.
3. **Un par un**, extraire chaque module (`vtk_log.py`, `ijk_registry.py`, …). Pour chaque module :
   - Déplacer les fonctions concernées.
   - Convertir les closures en fonctions prenant `ctx: EngineContext`.
   - Mettre à jour `initialize_fespp_engine` qui appelle les nouvelles fonctions extraites.
   - Compile-check + smoke test côté UI à chaque étape (charger un EPC, switcher de tab, toggler une propriété).
4. Quand `initialize_fespp_engine` est descendu à ~150 LOC, supprimer le shell et finaliser `boot.py`.
5. Commit par phase (un par module extrait) pour faciliter le revert ciblé si quelque chose casse.

### Risques

- **Smoke testing manuel obligatoire** — pas de tests end-to-end automatisés sur le pipeline (les 14 tests de `test_fespp_tree.py` sont déjà cassés indépendamment du refactor).
- **Ordre d'initialisation** : aujourd'hui le code de `initialize_fespp_engine` a un ordre implicite (créer Collector → IjkGrid → Selector → Activator → registrer hooks). Le respecter dans le nouveau `boot.py`.
- **`fespp_active.py` → `activator.py`** a aussi un constructeur d'~250 LOC dans son `__init__` (les `@state.change` handlers). À nettoyer dans le même pass ou séparément.

---

## Sujet 2 — Normalisation du data-source layer — **DONE**

> Atterrissage : `core/sources/` réorganisé avec `representation.py` (helpers communs `_sanitize`, `_find_registered_proxy`, `_apply_default_tint`), `ijkgrid.py` (enrichi avec les propriétés `source` / `rep_path` pour symétrie), `extract_block.py` (nouvelle `ExtractBlockRepresentation` + `ChainEntry`, multi-instance par rep), `source_registry.py` (point d'entrée unique qui wrappe IjkGrid + ExtractBlockRepresentation avec une API compatible — `get`, `sync`, `add_threshold`, `all_chain_proxies`, etc.). L'engine ne fait plus de special-casing : `source_registry.get(rep_path)` retourne uniformément la bonne représentation, et le seul résidu IjkGrid-specific est dans `threshold_dispatch.threshold_provider` (qui n'a pas pu être unifié à cause de la divergence d'API `add_threshold`).

### Section originale (référence) — Normalisation du data-source layer

Asymétrie actuelle :

- `IjkGrid` — **classe multi-instance**, une instance par grille IJK loadée. Gestion via dict externe `_ijkgrids[node_id]` dans engine.
- `RepSources` — **singleton** qui gère TOUS les non-IjkGrid reps (UnstructuredGrid, Wellbore, Trajectory, Grid2d, PointSet, Polyline, PolylineSet, TriangulatedSet) via un dict interne `_sources[rep_path]`.

Conséquence : le code engine doit faire du special-casing entre les deux (cf. `_sources_for_rep_path`, `_color_sources_for_rep_path`, `_threshold_provider` qui retourne soit `_ijkgrid` soit `_rep_sources`). Bouclé sur le découpage `engine.py`, c'est un irritant qui revient à plusieurs endroits.

### Refactor possible

```
core/sources/
├── representation.py     NEW — base class Representation + ChainEntry commun + helpers (_sanitize, _find_registered_proxy, _apply_default_tint)
├── ijk_grid.py          (renommé depuis ijkgrid.py, snake_case) — IjkGrid hérite de Representation, ajoute slicers + volume
├── extract_block.py     NEW — class ExtractBlockRepresentation, multi-instance, remplace l'actuel RepSources pour les non-IjkGrid
├── source_registry.py   NEW — dict {rep_node_id → Representation}, point d'entrée unique
├── collector.py         (inchangé) — Collector EPC
└── etp_connector.py     (inchangé) — ETPConnector OSDU/RDDMS
```

Effet attendu :

- `_threshold_provider()` devient `source_registry.get(grid_path)` qui retourne **toujours** une instance de `Representation`. Plus de branche IjkGrid vs UG.
- `_sources_for_rep_path()` itère sur les sources de la `Representation` correspondante.
- L'engine ne connaît plus l'asymétrie : il dispatche uniformément vers la registry.

### Quand l'attaquer

- **Pas avant le sujet 1** (sinon double surface mouvante).
- **Pas critique** non plus tant qu'on n'ajoute pas de comportement par-type qui pousse `RepSources` à devenir un god-class avec des `if rep_type == ...` partout.
- Estimé ~400-500 LOC à déplacer, ~1 jour de travail focus.

---

## Sujet 3 — Pass dead code audit — **DONE**

> Atterrissage : `vulture` run sur `fespp_on_trame/` à confidence 90 puis 60, en filtrant les faux positifs récurrents (`**kwargs` requis par Trame pour les `@state.change`, `frame` requis par `signal`, `state.foo = ...` lus par les templates Vue, propriétés ParaView). Trouvailles réelles supprimées : `tempfile` import dans `io/http_download.py`, `get_icon_for_type` import dans `core/tree.py`, paramètre `tree_data` dans `Selector.optimize_tree_selection` (la méthode est devenue identitaire depuis le passage à `ExplicitSelection=1`), paramètre `tab` dans `tree_views._expand_selection_with_deps`, attribut `Activator._realization_locked_range` (jamais lu), méthode `Activator._set_active_block_selector` (jamais appelée). Le reste des hits vulture sont des faux positifs framework-induced.

---

## Sujet 4 — `activator.py` — méthodes longues — **DONE**

> Atterrissage : `Activator.__init__` descend de ~250 LOC de handlers imbriqués à ~20 LOC de wiring `@state.change`. Le handler monstre `on_ui_active_node_reservoir_change` (~440 LOC) éclaté en :
> - `_handle_reservoir_change` — l'orchestrateur (~100 LOC)
> - `_activate_reservoir_rep` — résolution de la rep active + `SetActiveSource`
> - `_apply_multirealization_state` / `_reset_realization_state` — état du slider de réalisations
> - `_resolve_color_target_source` — sélection de la source visible (UG / IjkGrid avec priorité)
> - `_apply_color_for_active_property` — la machine ColorBy / LUT / scalar-bar avec les hacks de cache invalidation
> - `_debug_missing_array` — diagnostic "array not found"
>
> Les 3 handlers `surface` / `well` / `reservoir` sont maintenant des méthodes `_handle_*_change` appelées directement par `refresh_active()` (plus d'aliases `_*_active_handler`).

---

## Hors scope

- `engine/__init__.py` API : on garde `initialize_fespp_engine` comme entry point public. Pas besoin de l'aliaser en `initialize` (un peu trop générique).
- Test suite : 14 tests dans `tests/unit/test_fespp_tree.py` sont cassés indépendamment du refactor (bug `node_type=None` dans `get_icon_for_type`). À fixer dans un PR à part.

---

**Mise à jour de ce doc** : à chaque commit qui touche un de ces sujets, mettre à jour cette section (cocher, ajuster les LOC, ajouter des risques découverts).
