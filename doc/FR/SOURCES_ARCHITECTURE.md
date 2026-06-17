# `fespp_on_trame/app/core/sources/` — architecture des sources ParaView

Ce document décrit l'architecture du paquet Python `sources/` — la
couche qui encapsule les proxys de pipeline ParaView (Collector,
IjkGrid, ExtractBlock, slice, clip, …) dans des objets par
représentation pilotés par le moteur trame.

C'est la **couche d'encapsulation entre l'état trame et le
ServerManager de ParaView**. Au-dessus se trouve le moteur
(`app/core/engine/`) qui orchestre les actions de l'utilisateur ;
en dessous résident `paraview.simple` et le graphe de proxys SM.

Pour une vue d'ensemble complète de l'application, voir
[`dev-guide.md`](dev-guide.md). Pour le contexte général ParaView /
RESQML, voir les notes locales
[`../PARAVIEW.md`](../../PARAVIEW.md) et [`../RESQML.md`](../../RESQML.md)
(ignorées par git).

---

## Table des matières

- [Position de la couche](#layer-position)
- [Carte des modules](#module-map)
- [Les deux sources d'entrée : `Collector` et `ETPConnector`](#the-two-entry-sources-collector-and-etpconnector)
- [Wrappers par représentation](#per-representation-wrappers)
  - [`IjkGrid` — grille structurée découpable](#ijkgrid--sliceable-structured-grid)
  - [`ExtractBlockRepresentation` — tout le reste](#extractblockrepresentation--everything-else)
- [Wrappers de filtres : `SlicePlane`, `ClipPlane`, `PlaneWidget`](#filter-wrappers-sliceplane-clipplane-planewidget)
- [`SourceRegistry` — point d'entrée unique pour le moteur](#sourceregistry--single-entry-point-for-the-engine)
- [Cycle de vie : un parcours chargement + activation + découpe](#lifecycle-a-load--activate--cut-walkthrough)
- [Conventions de nommage](#naming-conventions)
- [Helpers partagés (`representation.py`)](#shared-helpers-representationpy)
- [État transversal](#cross-cutting-state)

---

## Position de la couche

```
+-----------------------------------------------+
|  UI layer (trame.widgets)                     |
|  panels, tree, render views                   |
+-----------------------------------------------+
|  Engine layer (app/core/engine/)              |
|  dispatch handlers, state.change reactions    |
|  active_array, data_load, slicer_dispatch,    |
|  slice_dispatch, clip_dispatch, threshold,    |
|  realization_dispatch, source_resolver…       |
+-----------------------------------------------+
|  ★ Sources layer (app/core/sources/) ★        |  <— this doc
|  per-rep PV pipeline wrappers                 |
+-----------------------------------------------+
|  paraview.simple + ServerManager              |
|  vtkSMProxy graph (sources, filters, views)   |
+-----------------------------------------------+
|  VTK pipeline (vtkAlgorithm, vtkDataObject)   |
+-----------------------------------------------+
```

La couche sources maintient le moteur ignorant des idiomes PV/SM :
création de filtres, gestion des proxys d'affichage, conventions de
noms d'enregistrement, chaînage multi-amont, plomberie des widgets.
Le code du moteur n'appelle jamais `pvsimple.*` directement pour les
modifications de pipeline — il passe par ces wrappers via le registre.

---

## Carte des modules

| Fichier               | Ce qu'il possède                                                                                      |
|-----------------------|-------------------------------------------------------------------------------------------------------|
| `collector.py`        | L'unique source PV `EPCCollector` (une par application).                                              |
| `etp_connector.py`    | L'unique source PV `ETP12Store` pour les connexions OSDU RDDMS.                                       |
| `ijkgrid.py`          | `IjkGrid` — wrapper par grille IJK : slicers multi-axes + découpe volumique + chaîne de seuils.       |
| `extract_block.py`    | `ExtractBlockRepresentation` — wrapper par rep pour tout type non-IJK (UnstructuredGrid, Wellbore, …).|
| `slice_plane.py`      | `SlicePlane` — filtre de coupe par plan pour toute rep (utilisé par ExtractBlock aujourd'hui).        |
| `clip_plane.py`       | `ClipPlane` — filtre de clip par plan, reflète le modèle de données de `SlicePlane`.                  |
| `plane_widget.py`     | `PlaneWidget` — wrapper `ImplicitPlaneWidgetRepresentation` partagé par `SlicePlane` et `ClipPlane`.  |
| `representation.py`   | Helpers partagés (`_sanitize`, `_find_registered_proxy`, `_apply_default_tint`).                      |
| `source_registry.py`  | `SourceRegistry` — dictionnaire d'instances point d'entrée unique exposé au moteur.                   |

---

## Les deux sources d'entrée : `Collector` et `ETPConnector`

Deux wrappers minces qui possèdent la source PV singleton produisant
l'assemblage de données RESQML :

  - **`Collector`** encapsule `pvsimple.EPCCollector()` (enregistré
    sous `EPCCollector` dans le groupe `sources`). Charge les fichiers
    `.epc/.h5` via `add_file(...)` qui pousse le chemin dans la
    propriété SM multi-éléments `Files`, puis rafraîchit les
    informations afin que l'assemblage soit reconstruit.

  - **`ETPConnector`** encapsule `pvsimple.ETP12Store()` (enregistré
    sous `ETP12Store`). Même rôle pour les connexions ETP1.2 / OSDU
    RDDMS — gère l'authentification, le proxy optionnel, la sélection
    de l'espace de données, puis expose le proxy source de la même
    façon.

Les deux classes sont minces (~50 lignes) : elles conservent la
source, exposent un porteur representationType / scale_z pour l'UI, et
un `show()` qui affiche le proxy par défaut. Elles ne suivent PAS les
représentations — chaque rep rendue vit dans des instances `IjkGrid`
ou `ExtractBlockRepresentation` en aval.

---

## Wrappers par représentation

Une *représentation* en RESQML est un objet géométrique (une grille,
une trajectoire, …) qui peut avoir plusieurs propriétés /
sous-représentations. Lorsque l'utilisateur coche la case d'une rep
dans l'arbre, le moteur crée l'un des deux types de wrapper :

### `IjkGrid` — grille structurée découpable

Pour le type de rep `IjkGrid`. Possède le **pipeline multi-slicer** :

```
EnergisticsExtractor (rep_data)
        |
        +--> ExtractCellsAlongLine I_0
        +--> ExtractCellsAlongLine I_1
        |    …
        +--> ExtractCellsAlongLine J_…
        +--> ExtractCellsAlongLine K_…
        +--> ExtractSubset (volume crop, range mode)
```

Chaque *amont actif* (rep_data + slicers en mode slice ; rep_data +
découpe volumique en mode range) peut être l'entrée d'une *chaîne de
seuils*. La chaîne est modélisée par `_IjkChainEntry` : chaque entrée
détient un dictionnaire `pv_proxies` indexé par `id(upstream_source)`
afin que plusieurs proxys Threshold (un par amont) puissent être
chaînés depuis la même entrée logique — la nature multi-source de
l'IjkGrid impose ce fan-out.

Règles de visibilité :
  - `_deepest_visible_leaf()` choisit l'extrémité de chaîne à rendre
    par amont — les autres restent masquées.
  - `_show_source_or_chain(src, view, visible, leaf)` bascule entre
    la sortie du slicer et la feuille de chaîne dans une vue unique.

Le pipeline est reconstruit lors de :
  - changements d'axe / de position des slicers (range ou slicers
    par position)
  - ajout / suppression / set_range / set_visible d'un seuil
  - changement de type de représentation ou d'échelle Z

### `ExtractBlockRepresentation` — tout le reste

Pour chaque type de rep non-IJK (UnstructuredGrid, Wellbore,
Trajectory, Grid2d, PointSet, Polyline*, TriangulatedSet, …). Possède
un unique filtre **`ExtractBlock`** chaîné sur le collector :

```
EPCCollector  --> ExtractBlock (rep_<sanitized>)
                       |
                       +--> Threshold (chain entry 1)
                              |
                              +--> Threshold (chain entry 2)
                                     |
                                     …
                       +--> Slice (optional, plane)
                       +--> Clip  (optional, plane)
```

Le filtre `EnergisticsExtractor` par rep (sémantique ShallowCopy,
aucune duplication réelle de données) est créé côté Python via
`_create_plugin_filter_proxy("EnergisticsExtractor", …)` chaîné sur
la source collector, puis enregistré sous le nom déterministe
`rep_<rep_path-with-_>`. (La commande de propriété C++
`SetExtractRepPath` du collector produit un extracteur équivalent
mais son étape `controller->RegisterPipelineProxy` échoue
silencieusement lors d'un cycle de désélection/resélection sur la
même rep — voir PARAVIEW.md
"`controller->RegisterPipelineProxy` silently fails the second time
under the same name" pour la cause racine. Le chemin Python-direct
contourne entièrement le contrôleur.)

Les entrées de chaîne utilisent un `ChainEntry` plus simple (un proxy
par entrée, pas un dictionnaire) : l'entrée est une source unique
donc aucun fan-out multi-amont n'est nécessaire.

`IjkGrid` et `ExtractBlockRepresentation` exposent tous deux la même
API de seuils : `add_threshold`, `delete_threshold`, `set_range`,
`set_visible`, `get_chain`, `available_arrays`, `array_data_range`.

---

## Wrappers de filtres : `SlicePlane`, `ClipPlane`, `PlaneWidget`

**Note :** l'UI de slice/clip côté utilisateur est actuellement mise
en commentaire (voir le commit
`c791598 ui: hide slice/clip from the SlicersPanel`) ; les wrappers
backend ci-dessous restent actifs et réactivés en décommentant le
panneau.

### `SlicePlane`

Coupe par plan (découpe la rep avec un plan infini, la sortie est la
coupe transversale 2D). État canonique :

  - `_origin: [3]` — un point sur le plan
  - `_normal: [3]` — normale au plan (non nulle quand activé)
  - `_axis: 'X'|'Y'|'Z'` — affordance UI (l'axe cardinal le plus
    proche de la normale courante ; aligné à 5° près via
    `_AXIS_SNAP_COS`).

Pipeline : `pvsimple.Slice(SliceType='Plane')`, Input = la source
canonique de la rep. Quand activé, la source de la rep est masquée
afin que seule la coupe transversale s'affiche.

### `ClipPlane`

Clip par plan (coupe le volume en deux le long d'un plan, garde un
côté — inversé par `InsideOut` / `Invert` dans PV6). Même modèle de
données + alignement d'axe que `SlicePlane`, plus un drapeau
`_inside_out`. La sortie est volumique, donc la coloration de la rep
(ColorBy, LUT, opacité) suit le clip naturellement.

Pipeline : `pvsimple.Clip(ClipType='Plane', Crinkleclip=0)`.

### `PlaneWidget`

Wrapper `ImplicitPlaneWidgetRepresentation` partagé utilisé à la fois
par `SlicePlane` et `ClipPlane`. Créé via le ProxyManager SM
(`pxm.NewProxy('representations', 'ImplicitPlaneWidgetRepresentation')`),
enregistré dans la liste `HiddenRepresentations` de la vue, placé sur
les bornes courantes, puis activé. Pilote les gestes à l'écran
sphère/flèche.

Un seul widget est affiché à la fois : le mode d'édition est contrôlé
par `state.ui_plane_edit_mode` (`'slice'`, `'clip'`, ou `None`). Le
filtre dont le nom correspond à `ui_plane_edit_mode` appelle
`PlaneWidget.ensure(view)` ; l'autre appelle `destroy()`.

La fin du glisser-déposer rend les nouveaux (origin, normal) au
filtre via un observateur, qui s'aligne sur un axe cardinal s'il est
proche et réécrit dans l'état du panneau.

---

## `SourceRegistry` — point d'entrée unique pour le moteur

Tout ce qui précède est caché derrière une seule façade. Le moteur
parle au registre à travers une surface de compatibilité uniforme :

```python
registry.get(rep_path)                # → source proxy (IjkGrid or ExtractBlock)
registry.get_ijk_grid(rep_path)       # → IjkGrid | None
registry.get_extract_block(rep_path)  # → ExtractBlockRepresentation | None

registry.add_threshold(rep_path, parent, array)
registry.delete_threshold(rep_path, name)
registry.set_range(rep_path, name, low, high)
registry.set_visible(rep_path, name, visible)
registry.get_chain(rep_path)
registry.available_arrays(rep_path)
registry.array_data_range(rep_path, array_name)
registry.all_visible_thresholds(rep_path)
registry.all_chain_proxies(rep_path)
registry.get_threshold(rep_path)      # deepest visible

registry.apply_z_scale(zscale)
registry.apply_representation(rep_type)
registry.sync(selectors, reservoir_select_node_ids)
registry.release(rep_path)
registry.release_all()
```

En interne, le registre conserve **deux dictionnaires** (un par type
concret) car le cycle de vie d'IjkGrid est indexé sur un *id de nœud
de propriété* (passé via `set_node_id`) tandis que le cycle de vie
d'ExtractBlock est indexé sur le *chemin de rep*. Les deux finissent
par correspondre à un unique rep_path que le moteur connaît, donc
l'asymétrie reste cachée aux appelants.

`sync(selectors, …)` est le réconciliateur central — étant donné
l'ensemble courant de sélecteurs de l'arbre, il crée des instances
pour les reps nouvellement sélectionnées et libère les instances des
reps désélectionnées.

---

## Cycle de vie : un parcours chargement + activation + découpe

Un parcours qui touche chaque wrapper dans l'ordre :

1. **L'application démarre.** `Collector()` crée l'unique source PV
   `EPCCollector`. `SourceRegistry()` est vide.

2. **L'utilisateur téléverse `model.epc`.** `collector.add_file(path)`
   pousse le chemin dans la propriété `Files` de la source. Le plugin
   C++ analyse l'EPC et construit un `vtkDataAssembly` — exposé à
   Python via `collector.get_source().Assembly`. Le `tree.py` du
   moteur le ré-analyse en listes d'état trame `ui_subtree_*`.

3. **L'utilisateur coche une grille IJK dans l'arbre.** Le
   `data_load.run(...)` du moteur est invoqué via le gestionnaire
   `state.change("fespp_data_selectors")`. Il appelle
   `registry.sync(selectors, ...)` qui crée une instance `IjkGrid`
   pour le rep_path.

4. **L'utilisateur choisit une propriété (clic sur l'œil).**
   `active_array.toggle_dataarray_color(panel_id, array_path)` écrit
   dans `state.ui_active_array_by_rep_by_view[panel_id][rep_path] =
   array_path`, puis demande au registre les affichages via
   `displays_for_rep_path(...)`. Pour un IjkGrid il s'agit des
   affichages des slicers + découpe volumique + seuils.

5. **L'utilisateur ouvre le panneau Slicers et bascule un slicer J.**
   Le panneau écrit `ui_slices_j_list` ; le `slicer_dispatch` du
   moteur transmet à `IjkGrid._sync_slice_sources('j', n)` qui crée /
   réutilise des proxys Slice via pvsimple.

6. **L'utilisateur ajoute un seuil.**
   `threshold_dispatch.threshold_add(...)` appelle
   `registry.add_threshold(rep_path, parent, array)` →
   `IjkGrid.add_threshold(...)` qui crée un proxy `Threshold` par
   amont actif (slicer + découpe volumique).

7. **(Flux Slice/Clip — UI actuellement masquée) :** si réactivé, le
   panneau écrit axis/offset/enabled dans `state.ui_slice_*` ; le
   dispatch appelle `IjkGrid.slice_set(...)` (ou l'équivalent EB) qui
   construit paresseusement le pipeline `Slice` ;
   `PlaneWidget.ensure(...)` est appelé quand
   `ui_plane_edit_mode == 'slice'`. L'observateur de fin de
   glisser-déposer du widget repousse les nouveaux (origin, normal).

8. **L'utilisateur décoche la rep.** `registry.sync(...)` remarque
   que le rep_path n'est plus sélectionné, appelle `IjkGrid.delete()`
   qui démantèle chaque proxy Slice/Threshold/Clip + l'extracteur
   rep_data.

---

## Conventions de nommage

Chaque proxy créé par ces wrappers porte un nom d'enregistrement
déterministe afin que les recherches ultérieures puissent reconstruire
les références après un rechargement d'état :

| Proxy                              | Motif du nom d'enregistrement         |
|-----------------------------------|----------------------------------------|
| EPC collector                     | `EPCCollector`                         |
| ETP store                         | `ETP12Store`                           |
| Per-rep extractor (C++ side)      | `rep_<sanitized(rep_path)>`            |
| IjkGrid rep_data                  | `rep_data_<sanitized(rep_path)>`       |
| IjkGrid slicer (one per position) | `slice_<axis>_<idx>_<sanitized(rep)>`  |
| IjkGrid volume crop               | `volume_<sanitized(rep_path)>`         |
| Threshold (any chain)             | `th_<chain-entry-uuid>_<upstream-id>`  |
| SlicePlane                        | `slice_plane_<sanitized(rep_path)>`    |
| ClipPlane                         | `clip_plane_<sanitized(rep_path)>`     |
| PlaneWidget                       | `plane_widget_<sanitized(rep_path)>`   |

`_sanitize(name)` (dans `representation.py`) remplace chaque caractère
hors de `[-.0-9A-Z_a-z]` par `_` afin que les chemins RESQML se
traduisent en noms d'enregistrement PV valides.

`_find_registered_proxy(reg_name)` élargit la recherche du
`ProxyManager` SM aux deux groupes `filters` et `sources`. Aujourd'hui
la construction d'extracteur Python-direct s'enregistre sous
`sources` ; le helper conserve le repli `filters` comme couverture
défensive pour les chemins de code ou les sessions sauvegardées
héritées qui auraient pu y atterrir, et parce que
`pvsimple.FindSource` ne scanne que `sources` et manquerait tout le
reste par lui-même.

---

## Helpers partagés (`representation.py`)

Minimal aujourd'hui, héberge :

  - `_sanitize(name)` — voir le tableau ci-dessus.
  - `_find_registered_proxy(reg_name)` — voir ci-dessus.
  - `_apply_default_tint(display)` — applique une couleur
    `DiffuseColor` par défaut déterministe mais agréable à un affichage
    fraîchement créé, afin que les reps ne démarrent pas toutes en
    blanc pur.

Le plan dans `REFACTOR_PLAN.md` (TODO) est de faire évoluer ceci en
une classe de base `Representation` partagée par `IjkGrid` et
`ExtractBlockRepresentation`, et une dataclass de base `ChainEntry`.

---

## État transversal

Variables d'état trame que la couche sources lit / écrit (les
gestionnaires du moteur médiatisent généralement celles-ci — les
sources elles-mêmes ne manipulent que leur propre état interne) :

| Variable                                  | Propriétaire / écrivain   | Lu ici                             |
|-------------------------------------------|---------------------------|------------------------------------|
| `ui_loaded_rep_paths`                     | engine.data_load          | (aucun — le registre est la vérité) |
| `ui_hidden_rep_paths_by_view`             | engine.visibility / UI    | `IjkGrid.show()`, `EB.show()`       |
| `ui_active_array_by_rep_by_view`          | engine.active_array       | résolveur `apply_color_array`       |
| `ui_active_realization_by_array_by_view`  | engine.realization_dispatch| idem                               |
| `ui_slices_range_mode`                    | UI (onglet Slicers IJK)   | `IjkGrid` (pipeline range vs slice) |
| `ui_slices_range_{i,j,k}`                 | UI                        | `IjkGrid._sync_slice_sources`       |
| `ui_slices_{i,j,k}_list/_visible_list`    | UI                        | idem                                |
| `ui_slice_*` / `ui_clip_*`                | UI (panneaux — actuellement masqués) | `SlicePlane` / `ClipPlane`  |
| `ui_plane_edit_mode`                      | UI (slice/clip — masqué)  | contrôle de `PlaneWidget.ensure()`  |
| `ui_threshold_chain`                      | engine.threshold_dispatch | (aucun — publié par le moteur)      |
| `ui_scale_z`                              | UI                        | `apply_z_scale` sur chaque wrapper  |

---

## Voir aussi

  - [`dev-guide.md`](dev-guide.md) — architecture complète de
    l'application.
  - [`../PARAVIEW.md`](../../PARAVIEW.md), [`../RESQML.md`](../../RESQML.md)
    — notes de référence locales sur les piles technologiques
    sous-jacentes (ignorées par git).
  - `REFACTOR_PLAN.md` — refactorisation en attente : fusionner
    IjkGrid + EB en une base `Representation` partagée, unifier le
    type d'entrée de chaîne.
