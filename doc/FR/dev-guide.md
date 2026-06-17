# FESPP-on-Trame — Guide du développeur

Ce document s'adresse aux développeurs qui contribuent à FESPP-on-Trame. Il
couvre l'architecture, le flux de données entre les couches, ainsi que les
variables d'état et conventions clés à comprendre avant de modifier le code.

Pour la documentation de l'utilisateur final, voir [`user-guide.md`](user-guide.md).

---

## Table des matières

- [Architecture de haut niveau](#high-level-architecture)
- [Organisation du dépôt](#repository-layout)
- [Le côté C++ : le plugin FESPP](#the-c-side-fespp-plugin)
  - [Dépôt de données → vtkDataAssembly](#data-repository--vtkdataassembly)
  - [Modes de sélection](#selection-modes)
  - [Modes de hiérarchie de l'arbre](#tree-hierarchy-modes)
  - [Extraction par rep : ExtractRepWithoutCopy](#per-rep-extract-extractrepwithoutcopy)
  - [Clone par vue : vtkEPCCollectorClone](#per-view-clone-vtkepccollectorclone)
  - [Reconstruction de l'assembly à chaud](#live-assembly-rebuild)
- [Le côté Python : l'application Trame](#the-python-side-trame-app)
  - [Cartographie des modules](#module-map)
  - [Vue d'ensemble du cycle de vie](#lifecycle-overview)
  - [Orchestrateur du moteur (`engine/boot.py`)](#engine-orchestrator-enginebootpy)
  - [Parseur d'arbre (`tree.py`)](#tree-parser-treepy)
  - [Selector (`selector.py`)](#selector-selectorpy)
  - [Activator (`activator.py`)](#activator-activatorpy)
  - [Couche des sources](#sources-layer)
  - [Couche View-Scenes](#view-scenes-layer)
  - [Couche UI](#ui-layer)
- [Variables d'état (Trame)](#state-variables-trame)
- [Modèle de sélection / visibilité / coloration](#selection--visibility--coloring-model)
- [Flux de données critiques](#critical-data-flows)
  - [Chargement de fichier](#file-load)
  - [Clic sur une case à cocher](#checkbox-click)
  - [Clic sur l'œil (visibilité)](#eye-click-visibility)
  - [Clic sur l'œil (DataArray)](#eye-click-dataarray)
  - [Ajouter une vue / scinder / vue vide](#add-view--split--empty-view)
  - [Copier depuis une vue](#copy-from-view)
  - [Changement du mode de hiérarchie de l'arbre](#tree-hierarchy-mode-change)
- [Pièges courants](#common-pitfalls)
- [Ajouter une fonctionnalité : recettes](#adding-a-feature-cookbook)

---

## Architecture de haut niveau

```
┌─────────────────────────────────────────────────────┐
│                     Browser                          │
│   Vue 3 + Vuetify 3 (rendered by Trame templates)    │
└──────────────────────┬──────────────────────────────┘
                       │  (websocket, JSON state)
┌──────────────────────┴──────────────────────────────┐
│                Python (Trame server)                 │
│ ┌──────────────────────────────────────────────────┐ │
│ │ Engine (orchestration), Selector, Activator,     │ │
│ │ Tree (assembly→state), RepSources, IjkGrid,      │ │
│ │ panels (color, slicers, …)                       │ │
│ └────────────────────────┬─────────────────────────┘ │
│                          │  pvsimple, vtkSMPropertyHelper
│ ┌────────────────────────┴─────────────────────────┐ │
│ │ ParaView server-side proxy (vtkEPCCollector)     │ │
│ └────────────────────────┬─────────────────────────┘ │
└──────────────────────────┴──────────────────────────┘
                           │
┌──────────────────────────┴──────────────────────────┐
│              C++ FESPP plugin                        │
│  vtkEPCCollector ─→ ResqmlDataRepository…Collection  │
│  uses fesapi to parse EPC + drive vtkDataAssembly    │
└─────────────────────────────────────────────────────┘
```

Chemin des données :

1. fesapi analyse le fichier `.epc` / `.h5` dans un
   `DataObjectRepository` en mémoire.
2. `ResqmlDataRepositoryToVtkPartitionedDataSetCollection` parcourt le
   dépôt et construit un `vtkDataAssembly` (l'arbre visible par
   l'utilisateur). Chaque nœud porte `kind`, `title`, `path`, plus des
   métadonnées par type (`propKind`, `realization_count`, …).
3. Le parseur Python `Tree` lit l'assembly et l'écrit sous forme de
   dictionnaires imbriqués dans l'état Trame (`ui_subtree_reservoir`, `_surface`, `_well`).
4. Les templates Vuetify rendent les arbres à partir de ces dictionnaires.
5. Sélectionner / activer / basculer les yeux dans l'UI modifie l'état
   Trame, ce qui déclenche les gestionnaires `@state.change` qui pilotent
   le pipeline ParaView (selectors, ColorBy, Visibility, …).

---

## Organisation du dépôt

```
.
├── fespp_on_trame/              # Python Trame application
│   ├── __main__.py              # entry point, CLI args, wires the engine
│   ├── constants.py
│   └── app/
│       ├── core/                # backend: engine, selectors, sources
│       │   ├── tree.py                # vtkDataAssembly → Trame dicts
│       │   ├── selector.py            # checkbox → fespp_data_selectors
│       │   ├── activator.py           # active node → ColorBy + LUT
│       │   ├── wellhead.py            # wellbore trajectory helpers
│       │   ├── timeseries.py
│       │   ├── color_palette.py       # default per-rep colors
│       │   ├── engine/                # orchestration sub-package
│       │   │   ├── boot.py                  # initialize_fespp_engine (main wiring)
│       │   │   ├── state_defaults.py        # state.setdefault(...) seeds
│       │   │   ├── data_load.py             # fespp_data_selectors handler
│       │   │   ├── active_array.py          # ColorBy fan-out (rep / view buckets)
│       │   │   ├── slice_dispatch.py        # per-view slice plane writes
│       │   │   ├── clip_dispatch.py         # per-view clip plane writes
│       │   │   ├── slicer_dispatch.py       # per-view IJK slicer writes
│       │   │   ├── threshold_dispatch.py    # per-view threshold chain writes
│       │   │   ├── realization_dispatch.py  # per-view MR realization picks
│       │   │   ├── source_resolver.py       # rep_path → PV proxies / displays
│       │   │   ├── panel_resolver.py        # panel_id → pv_view / html_view
│       │   │   ├── visibility.py            # rep eye click flow
│       │   │   ├── view_ops.py              # camera reset / view update
│       │   │   ├── selection_dispatch.py    # checkbox → selectors plumbing
│       │   │   ├── hierarchy.py             # tree-hierarchy-mode flow
│       │   │   ├── diff.py                  # A − B diff scene
│       │   │   ├── etp.py                   # ETP/OSDU connect
│       │   │   ├── time_realization.py      # per-view TC labels
│       │   │   └── vtk_log.py               # stderr tee + log panel
│       │   ├── sources/                # PV proxy wrappers
│       │   │   ├── collector.py             # wraps vtkEPCCollector
│       │   │   ├── etp_connector.py
│       │   │   ├── extract_block.py         # legacy non-IJK per-rep wrapper
│       │   │   ├── ijkgrid.py               # IJK pipeline (legacy + per-view)
│       │   │   ├── slice_plane.py           # SlicePlane (per (rep, view))
│       │   │   ├── clip_plane.py            # ClipPlane (per (rep, view))
│       │   │   ├── plane_widget.py          # 3D widget channel
│       │   │   ├── representation.py        # ExtractBlock helpers
│       │   │   ├── source_registry.py       # legacy per-rep registry
│       │   │   ├── view_scene.py            # one ViewScene per render panel
│       │   │   ├── rep_in_scene.py          # per-(rep, view) wrapper
│       │   │   └── scene_registry.py        # view → ViewScene map
│       │   └── common/
│       ├── ui/                  # Vue/Vuetify templates
│       │   ├── view.py                # main layout
│       │   ├── tree_views.py          # the 3 VTreeviews + eye slots
│       │   ├── toolbar.py
│       │   ├── import_dialog.py
│       │   ├── helpers.py
│       │   ├── content/                # multi-view content area
│       │   │   ├── content.py
│       │   │   ├── view/
│       │   │   │   └── multi_view.py        # FesppMultiView (ptc.MultiView)
│       │   │   ├── dialog/
│       │   │   │   └── new_view_content_dialog.py  # split: Copy / Empty / Diff
│       │   │   └── widget/
│       │   │       ├── time_control.py
│       │   │       ├── realization_picker.py
│       │   │       ├── view_link_menu.py        # per-view camera-link menu
│       │   │       └── per_view_camera_toolbar.py
│       │   ├── drawer/
│       │   │   └── panel/                   # per-feature panels
│       │   │       ├── solid_color_panel.py
│       │   │       ├── color_editor.py
│       │   │       ├── categorical_color_editor.py
│       │   │       ├── representation_type_panel.py
│       │   │       ├── slicers.py                  # IJK tab body
│       │   │       ├── slicers_panel.py            # Slicers card (IJK / Slice / Clip tabs)
│       │   │       ├── slice_plane_panel.py
│       │   │       ├── clip_plane_panel.py
│       │   │       ├── threshold_panel.py
│       │   │       └── copy_from_view_menu.py      # "Copy from view X" helper
│       │   ├── config/
│       │   │   ├── tree_icons.py
│       │   │   └── tree_selection.py
│       │   └── widget/
│       └── io/
│           ├── upload_endpoint.py     # /upload HTTP route (multipart)
│           ├── drop_files.py
│           └── http.py
└── doc/                         # docs (this file lives here)
```

Les sources du **plugin FESPP C++** se trouvent dans un dépôt séparé (sous
`e:\Dev\fespp\work\src\Plugin\Energistics\` dans la configuration de
développement). Une étape de build copie ces sources vers l'arbre de
déploiement (`/work/ttl/fespp/Plugin/Energistics/...`) avant d'invoquer CMake.

---

## Le côté C++ : le plugin FESPP

Le plugin expose `vtkEPCCollector`, un `vtkPartitionedDataSetCollectionAlgorithm`
adossé à `ResqmlDataRepositoryToVtkPartitionedDataSetCollection` (le
« wrapper de dépôt ») qui enveloppe lui-même un `DataObjectRepository` de fesapi.

### Dépôt de données → vtkDataAssembly

`buildDataAssemblyFromDataObjectRepo(fileName)` traverse chaque
représentation du dépôt (grilles, surfaces, polylignes, points,
grilles non structurées) et appelle `searchRepresentations(rep)` pour
chacune. Des parcoureurs spécialisés gèrent les wellbores (`searchWellboreTrajectory`),
les ensembles de propriétés (`searchPropertySet`), les séries temporelles (`searchTimeSeries`)
et les réalisations (`searchRealization`).

Chaque nœud est ajouté via `addNodeToDataAssembly(object, type, parent)`
qui définit :

- `type` (int) — la valeur de l'enum `TreeViewNodeType` (voir `Tools/enum.h`).
- `kind` (string) — nom convivial pour l'humain/Python (`"IjkGrid"`,
  `"ContinuousProperty"`, …).
- `title` (string) — titre original de l'objet RESQML.
- `label` (string) — nom valide pour VTK pour l'affichage hérité.
- Plus des métadonnées optionnelles : `propKind`, `realization_count`,
  `realization_indices`, `minvalue`, `maxvalue`, `colorRGB`, …

**Les types de nœuds synthétiques** (`MultiRealization`, `MultiRealizationTimeSeries`,
`Feature`, `Interpretation`) n'ont pas d'objet fesapi derrière eux ; ce
sont de purs auxiliaires de mise en forme de l'arbre.

### Modes de sélection

Deux sémantiques de sélection, choisies à l'exécution par la propriété
de proxy `ExplicitSelection` :

- `ExplicitSelection = 0` *(par défaut, compatibilité avec l'IHM ParaView)* —
  sélectionner un chemin inclut implicitement tous les descendants. Cela
  correspond au widget `data_assembly_editor` de ParaView qui réduit les
  sous-arbres entièrement cochés au chemin du parent.
- `ExplicitSelection = 1` *(défini au démarrage par fespp_on_trame)* — les
  selectors sont pris au sens littéral pour les nœuds non groupants.
  Sélectionner une grille ne charge PAS automatiquement ses propriétés ;
  sélectionner une frame de wellbore ne charge PAS automatiquement ses
  channels. Les nœuds groupants (`Collection`, `Wellbore`, `Partial`,
  `Feature`, `Interpretation`) propagent toujours.

La distinction est implémentée dans `selectNodeId` / `selectNodeIdChildren` :
la propagation aux descendants n'a lieu que lorsque `!_explicitSelection ||
isGroupingType(node_type)`. Voir `isGroupingType` dans `Tools/enum.h`.

### Modes de hiérarchie de l'arbre

`SetTreeHierarchyMode(value)` bascule la disposition de l'arbre entre trois
modes (enum `TreeHierarchyMode` dans `enum.h`) :

| Valeur | Nom | Disposition |
|-------|------|--------|
| 0 | `Flat` | Reps directement sous la racine (hérité). |
| 1 | `ByInterpretation` | Reps groupés sous leur parent Interpretation. |
| 2 | `ByFeatureAndInterpretation` | Groupement Feature supplémentaire au-dessus d'Interpretation. |

`resolveGroupingParent(rep, parent)` est l'auxiliaire qui, dans les modes
non Flat, recherche ou crée les nœuds `Feature` / `Interpretation`
correspondants (idempotent — indexé par uuid) et retourne l'identifiant du
nœud parent effectif. Il est appelé depuis `buildDataAssemblyFromDataObjectRepo`
pour chaque rep de premier niveau.

### Extraction par rep : EnergisticsExtractor (chaîné sur le collector)

Chaque rep chargé reçoit sa propre source ParaView à sortie unique via un
filtre `EnergisticsExtractor` chaîné au-dessus du collector. Le côté
Python (`ExtractBlockRepresentation._create_source` dans
`extract_block.py`) construit l'extracteur via
`_create_plugin_filter_proxy("EnergisticsExtractor", …)` et l'enregistre
sous un nom déterministe `rep_<rep_path-with-_>`. La teinte de couleur
diffuse par défaut et le ColorBy côté Python opèrent sur cette source
individuelle.

La sémantique « WithoutCopy » effectue une copie superficielle (shallow-copy)
des données de partition dans `RequestData`, de sorte que la sous-source
suit automatiquement les changements en amont (ajout/suppression de
selector, échange de réalisation, ajout de propriété sur place).

**Pourquoi Python et pas la commande de proxy C++ `SetExtractRepPath` :** le
côté C++ du collector possède bien une commande de propriété
`SetExtractRepPath(path)` qui appelle en interne
`controller->RegisterPipelineProxy(extract, regName)` — mais ce chemin
échoue silencieusement à re-publier le proxy lorsqu'il est appelé une
seconde fois sous le même `regName` après un cycle Python `pvsimple.Delete`
(tout-désélectionner + re-sélectionner sur le même rep). Voir PARAVIEW.md
« `controller->RegisterPipelineProxy` silently fails the second time
under the same name » pour le motif de contournement documenté. Le chemin
Python-direct contourne entièrement le controller
(`spm->NewProxy + spm->RegisterProxy("sources", …)`), ce qui est
ré-appelable N fois d'affilée.

### Clone par vue : vtkEPCCollectorClone

`vtkEPCCollectorClone` est un filtre passthrough pur chaîné sur la source
`vtkEPCCollector` de premier niveau. Il effectue un ShallowCopy de la
sortie en amont dans `RequestData` (zéro duplication de données) et existe
pour une seule raison : donner à chaque `ViewScene` Python son propre proxy
racine dans le graphe du ServerManager PV. Les pipelines par vue
(`EnergisticsExtractor` + slicers + threshold) s'ancrent sur le clone,
afin que deux vues puissent contenir des proxies aval divergents sans
partager d'état. Le clone lui-même n'est jamais `Show()` dans aucune vue
(c'est un nœud structurel, pas un nœud à rendre).

Lorsque la DLL du plugin FESPP est livrée sans `vtkEPCCollectorClone`
(build périmé), le côté Python se rabat sur l'ancrage sur la source
collector partagée à la place. Cela est journalisé à la création de la vue
sous la forme `clone=shared` et désactive la divergence par vue pour cette
scène (chaque proxy « par vue » entre en collision sur `id()` entre les
vues).

### Reconstruction de l'assembly à chaud

`rebuildAssembly()` (ajouté avec la fonctionnalité TreeHierarchyMode) :

1. Vide tous les caches par node-id (`_nodeIdToMapper`,
   `_nodeIdToMapperSet`, `_selection`, `_currentSelection`,
   `_oldSelection`, `_blocksColors`, `_blockColorsMap`).
2. Appelle `vtkDataAssembly::Initialize()` sur l'assembly existant,
   puis réapplique `SetRootNodeName("data")` (Initialize réinitialise le
   nom de la racine au défaut VTK, ce qui casserait la correspondance des
   chemins).
3. Re-traverse chaque fichier précédemment chargé via
   `buildDataAssemblyFromDataObjectRepo` — cela re-sollicite fesapi mais
   ne relit pas le fichier depuis le disque car le dépôt est déjà en
   mémoire.

`SetTreeHierarchyMode` appelle `rebuildAssembly()` automatiquement après
avoir basculé le mode, en effaçant aussi `selectorNotLoaded` / `selectors`
(les chemins de la disposition précédente provoqueraient sinon des
avertissements `vtkDataAssembly: Invalid parameters` au prochain
`RequestData`).

### API publique notable utilisée depuis Python

| Méthode | Objet |
|--------|---------|
| `Set/GetExplicitSelection(bool)` | Basculer la sémantique de sélection. |
| `Set/GetTreeHierarchyMode(int)` | Basculer la disposition de l'arbre (reconstruit sur place). |
| `GetAssembly()` / `GetLiveAssembly()` | Accès direct au `vtkDataAssembly` vivant (contourne le DeepCopy du pipeline dans `GetOutput`). `GetLiveAssembly` existe sous un nom unique pour éviter les problèmes de wrapping avec le `GetAssembly` de la classe parente. |
| `SetExtractRepPath(path)` + `GetExtractedRepProducerName()` | Paire source extraite par rep (écriture + relecture). |
| `SetRealizationIndex(int)` / `SetRealizationIndexAsString(str)` | Défilement multi-réalisations. |

---

## Le côté Python : l'application Trame

L'application utilise Trame en mode single-page-avec-drawer. L'état est
partagé entre le serveur (Python) et le client (Vue) via le mécanisme
réactif de Trame : écrire dans `state.foo` propage au navigateur, et
`@state.change("foo")` déclenche un gestionnaire Python à chaque mutation.

### Cartographie des modules

| Module | Responsabilité |
|--------|----------------|
| `__main__.py` | Parsing de la CLI, instancie `App`, câble `initialize_fespp_engine`, appelle `ui(server)`. |
| `app/core/engine/boot.py` | `initialize_fespp_engine(server, ...)` — le gros orchestrateur. Charge les plugins, crée la vue de rendu initiale, instancie `Tree` / `Collector` / `SourceRegistry` / `SceneRegistry` / `Selector` / `Activator`, enregistre chaque `@state.change` et `@controller.set`. |
| `app/core/engine/state_defaults.py` | `state.setdefault(...)` pour chaque variable dont dépendent le moteur / l'UI. Groupé de manière déclarative afin qu'ajouter un drapeau n'oblige pas à faire défiler `boot.py`. |
| `app/core/engine/data_load.py` | `run(state, ...)` — le corps du gestionnaire `fespp_data_selectors` : pousser les selectors, masquer le parent multiblock, synchroniser les registres, rafraîchir l'actif, rendre. |
| `app/core/engine/{slice,clip,slicer,threshold,realization}_dispatch.py` | Dispatchers par préoccupation routant les événements UI via `scene_registry → RepInScene → proxies par vue` (repli hérité quand scene_registry n'est pas prêt). |
| `app/core/engine/active_array.py` | Diffusion (fan-out) du ColorBy : `toggle_dataarray_color` (clic œil) + `on_active_array_change` + `apply_panel_coloring` (re-coloration par panneau). |
| `app/core/engine/source_resolver.py` | Résolution `(rep_path, view) → list[PV proxy]` pour la visibilité / la diffusion ColorBy. Sensible aux vues. |
| `app/core/engine/panel_resolver.py` | Résolution `panel_id → pv_view / html_view` via `server.context.multi_view`. |
| `app/core/engine/visibility.py`, `view_ops.py`, `time_realization.py` | Œil de visibilité du rep, réinitialisation caméra / diffusion de mise à jour de vue, libellés TimeControl par vue. |
| `app/core/engine/diff.py` | Calcul de la scène diff A − B + configuration de la LUT. |
| `app/core/engine/stats_dispatch.py` | `publish_descriptive_stats(...)` — construit une chaîne transitoire `Threshold(no-NaN) → DescriptiveStatistics` sur la source rendue de la vue active, lit la sortie, peuple `state.ui_descriptive_stats`. Déclenché par les modifications de propriété active / rep / panneau / réalisation / chaîne de threshold + les changements de pas de temps. |
| `app/core/engine/vtk_log.py` | dérivation (tee) de stderr → `state.vtk_log_messages`. |
| `app/core/tree.py` | Classe `Tree` — enveloppe `vtkDataAssembly`. `set_tree(assembly)` re-parse vers `state.ui_subtree_*` et expose les auxiliaires `find_*`. |
| `app/core/selector.py` | `Selector` — convertit les listes de cases à cocher de l'UI (`ui_select_node_*`) en chemins d'assembly et les écrit dans `state.fespp_data_selectors`. |
| `app/core/activator.py` | `Activator` — écoute sur `ui_active_node_*`, résout le rep actif, applique conditionnellement `ColorBy`, rafraîchit le panneau LUT/PWF. |
| `app/core/sources/collector.py` | Enveloppe le proxy `vtkEPCCollector` : `add_file`, `show`, `set_realization_index`. |
| `app/core/sources/source_registry.py` | Registre hérité par rep — conservé comme repli. Le nouveau code cible `SceneRegistry`. |
| `app/core/sources/extract_block.py` | Wrapper hérité non-IJK par rep (`ExtractBlockRepresentation`). La plupart des méthodes sont dépréciées ; l'extracteur par vue vit désormais sur `RepInScene`. |
| `app/core/sources/ijkgrid.py` | Pipeline slicer / volume / chaîne IJK. Chaque `RepInScene` pour un rep IJK instancie son PROPRE `IjkGrid` par vue (ancré sur le clone de la scène). Le `IjkGrid` partagé hérité survit comme porteur de métadonnées. |
| `app/core/sources/slice_plane.py`, `clip_plane.py` | Filtres `SlicePlane` et `ClipPlane` par-(rep, vue), détenus par `RepInScene`. |
| `app/core/sources/scene_registry.py` | **`SceneRegistry`** — cycle de vie `{panel_id: ViewScene}`, miroir vue → reps, `replicate_view` (snapshot/apply entre vues). |
| `app/core/sources/view_scene.py` | **`ViewScene`** — une par panneau de rendu. Détient le proxy `vtkEPCCollectorClone` + la carte `{rep_path: RepInScene}` du panneau. |
| `app/core/sources/rep_in_scene.py` | **`RepInScene`** — wrapper par-(rep, vue). Détient l'`EnergisticsExtractor` par vue (non-IjkGrid), le pipeline `IjkGrid` par vue (IjkGrid), le `SlicePlane` / `ClipPlane` par vue, la chaîne de threshold par vue. Expose `snapshot_*` / `apply_*` par préoccupation pour la réplication de vue. |
| `app/core/sources/etp_connector.py` | Client ETP/OSDU (source de données alternative). |
| `app/ui/view.py` | Disposition principale : drawer, onglets, cartes d'attributs, section d'affichage général, zone de rendu, panneau de journal. |
| `app/ui/tree_views.py` | Les trois `VTreeview` + ligne de pastilles œil par vue + gestionnaires d'expansion des dépendances. |
| `app/ui/content/view/multi_view.py` | `FesppMultiView` (sous-classe de ptc.MultiView) — détient les panneaux dockview, la carte `pv_view` par panneau, le cycle de vie ajout-vue / fermeture-vue, la synchro de lien caméra, la réplication de visibilité au split. |
| `app/ui/content/dialog/new_view_content_dialog.py` | Modale d'action de split : scène Copy / scène Empty / scène Diff. |
| `app/ui/content/widget/{time_control,realization_picker,view_link_menu,per_view_camera_toolbar}.py` | Superpositions par vue dans la zone 3D. |
| `app/ui/toolbar.py` | Barre de titre, boutons **Import**, **Load**, sélecteur global de Realization. |
| `app/ui/import_dialog.py` | Téléversement de fichier + dialogue de connexion ETP/OSDU. |
| `app/ui/drawer/panel/solid_color_panel.py` | Panneau couleur/LUT du nœud actif. |
| `app/ui/drawer/panel/{slice,clip}_plane_panel.py`, `threshold_panel.py`, `slicers.py`, `slicers_panel.py` | UI Slice / Clip / Threshold / slicers IJK. Chaque en-tête de panneau porte un menu déroulant `render_copy_menu(concern)` (« Copy from view X »). |
| `app/ui/content/panel/descriptive_stats_panel.py` | `DescriptiveStatsPanel` — VExpansionPanel rendant `state.ui_descriptive_stats` sous forme de table HTML compacte (Variable / Cardinality / Min / Max / Mean / Std Dev / Variance / Sum / Skewness / Kurtosis / M2-M4). Masqué quand la liste d'état est vide. |
| `app/ui/drawer/panel/copy_from_view_menu.py` | Auxiliaire réutilisable de menu déroulant copy-from-view, enregistre les triggers `copy_<concern>_from_view`. |
| `app/ui/drawer/panel/color_editor.py`, `categorical_color_editor.py` | Widgets LUT / PWF. |
| `app/ui/drawer/panel/representation_type_panel.py` | Type d'affichage ParaView par rep (Surface / Wireframe / …). |
| `app/ui/config/tree_icons.py` | Carte `kind` → icône mdi. |
| `app/ui/config/tree_selection.py` | Types sélectionnables par onglet (utilisé par le sélecteur `item_props` du VTreeview). |
| `app/io/upload_endpoint.py` | Route HTTP d'upload patchée, appelle `controller.load_epc_file` après chaque upload. |

### Vue d'ensemble du cycle de vie

`__main__.py` construit une `App` qui :

1. Crée le `server` Trame (`get_server(client_type="vue3")`).
2. Appelle `initialize_fespp_engine(server, fespp_plugin_path=...)`.
3. Appelle `ui(server)`.
4. Exécute `server.start()`.

`initialize_fespp_engine` effectue l'essentiel du câblage :

- Charge le `.so` FESPP plus le plugin `ExplicitStructuredGrid`.
- Crée la vue de rendu ParaView.
- Construit les objets cœur : `Tree`, `Collector`, `ETPConnector`,
  `IjkGrid`, `RepSources`, `Selector`, `Activator`.
- Définit `ExplicitSelection=1` sur le proxy collector.
- Pousse la valeur initiale de `tree_hierarchy_mode`.
- Appelle `state.setdefault(...)` pour chaque variable d'état (voir ci-dessous).
- Enregistre les gestionnaires `@state.change` et les actions `@controller.set`.

### Orchestrateur du moteur (`engine/boot.py`)

C'est le plus gros module. Responsabilités, par section :

- **Capture du journal VTK** — installe une dérivation (tee) de stderr afin
  que les messages au format VTK aboutissent à la fois dans les journaux
  docker et dans `state.vtk_log_messages`.
- **Init du pipeline** — collector / view / extract.
- **Valeurs par défaut de l'état** — chaque variable d'état dont dépend le
  reste de l'application.
- **`controller.load_epc_file(path)`** — appelle `_collector.add_file`,
  qui définit `Files`, appelle `UpdatePipelineInformation`, et déclenche
  `controller.update_data_information`.
- **`controller.update_data_information`** — lit le `vtkDataAssembly`
  vivant (en préférant `GetLiveAssembly` à la sortie deep-copiée du
  pipeline) et appelle `_tree.set_tree(assembly)`.
- **`@state.change("fespp_data_selectors")`** — le gestionnaire de
  chargement : pousse les selectors au collector, masque le multiblock
  parent, synchronise `RepSources`, bump le MTime de chaque producteur
  pour invalider les caches d'info de proxy, met à jour
  `ui_loaded_rep_paths` et `ui_active_array_by_rep`, appelle
  `notify_active_reps` sur l'activator, définit la source active, exécute
  `refresh_active`, rend.
- **`controller.toggle_rep_visibility(rep_path)`** — clic œil du rep :
  bascule `ui_hidden_rep_paths` et applique `pvsimple.Show` / `Hide`
  + `display.Visibility` sur chaque source rendant le rep.
- **`controller.toggle_dataarray_color(array_path)`** — clic œil du
  data-array : écrit dans `ui_active_array_by_rep` (une entrée par rep).
- **`@state.change("ui_active_array_by_rep")`** — applique le
  `ColorBy` (ou l'efface pour SolidColor) sur chaque rep chargé.
- **`@state.change("tree_hierarchy_mode")`** — pousse le mode au
  collector (ce qui déclenche la reconstruction C++), efface chaque
  variable d'état de sélection, appelle `UpdatePipeline` afin que le
  deep-copy de la sortie du pipeline rattrape le nouvel assembly vivant,
  puis `update_data_information` pour re-parser, et fait apparaître le
  snackbar d'avertissement si une sélection a été effacée.
- **`@state.change("load_mode")`** — auto / manuel.
- **`controller.apply_pending_selection`** — point d'entrée du bouton
  `Load` du mode manuel.
- **`@state.change("ui_scale_z")`** — diffuse l'échelle Z à chaque source
  de rep.
- **Gestionnaires de slicer**, **gestionnaires de réalisation**,
  **contrôles temporels**, **réinitialisation caméra**, **cycle de vie de
  la session** (suppression des répertoires temporaires à la sortie du
  dernier client).

### Parseur d'arbre (`tree.py`)

`Tree.set_tree(data_assembly)` parcourt l'assembly vivant avec deux
auxiliaires récursifs (`set_tree` pour le premier niveau +
`add_subtreeview_data` pour les sous-arbres) et écrit trois listes de
dictionnaires imbriqués : `state.ui_subtree_{reservoir,surface,well}`.

Chaque dictionnaire a : `id`, `parent_id`, `title`, `path`, `type`, `icon`,
`is_ts`, `is_mr`, `disabled` optionnel, `children` optionnel.

**Ordre des frères.** L'assembly C++ émet les enfants dans son propre
ordre ; les dictionnaires `ui_subtree_*` émis sont ensuite triés
**alphabétiquement à chaque niveau** (la hiérarchie est conservée ; seuls
les frères sont réordonnés) via `_sibling_sort_key` — insensible à la
casse, accents repliés (`Éclair` se trie avec `E`), tri naturel-numérique
(`Grid2` avant `Grid10`), le marqueur `!!!PARTIAL!!!` étant retiré pour
qu'un partiel se trie par son vrai nom. C'est **purement présentationnel** :
on réordonne les trois listes émises et les `children` de chaque nœud ;
l'identité d'un nœud partout ailleurs passe par `id`/`path`, jamais par la
position dans la liste (le parcours de l'assembly, `find_*`, l'indexation
dataset/partition, MR/timeseries, la sélection sont tous indépendants de
l'ordre).

Le dispatch vers le bon onglet gère les modes de hiérarchie de l'arbre :
les nœuds `Feature` / `Interpretation` de premier niveau récurrent via
`_resolve_dispatch_kind` jusqu'à ce que le premier descendant non groupant
soit trouvé, et *ce* kind décide de l'onglet de destination.

La classe expose aussi un ensemble d'auxiliaires en lecture seule utilisés
par le reste de la base de code : `find_node_id(path)`, `find_path(node_id)`,
`find_type(node_id)`, `find_title(node_id)`,
`find_attribute_value(node_id, attr)`,
`find_representation_node(node_id)`,
`find_parent_node_id_with_type(node_id, kind)`,
`find_first_child_of_type(node_id, kind)`,
`find_all_descendant_ids(node_id)` (utilisé par l'expansion de
dépendances de l'UI), `has_property_descendant(node_id)`.

### Selector (`selector.py`)

Le `Selector` détient les listes de chemins par onglet
(`_selection_path_{reservoir,surface,well}`) et les instances
`TimeSeries` / `Wellhead` actives. Chaque méthode `select_node_*`
lit `state.ui_select_node_*`, traverse les ids vers les chemins, définit
l'une des trois listes locales, et écrit la concaténation dans
`state.fespp_data_selectors`.

Reservoir / surface / well sont symétriques : ils émettent la liste
complète des chemins cochés (avec `ExplicitSelection=1`, chaque propriété
doit être listée explicitement).

### Activator (`activator.py`)

Écoute sur `ui_active_node_{reservoir,surface,well}`. Le gestionnaire
reservoir est le plus complexe à cause des grilles IJK :

1. Valide que le nœud actif est « activable » (son sous-arbre est
   coché) — sinon réinitialise `ui_active_node_*` à `[]`.
2. Résout le type, le titre, le propKind du rep.
3. Pour les activations de propriété, définit `active_color_array_name` et
   résout la bonne source ParaView (filtre rep_data, slicers,
   volume — plusieurs sources peuvent rendre la même grille IJK).
4. **Applique conditionnellement ColorBy** — uniquement quand l'œil de
   l'array actif est ouvert dans `ui_active_array_by_rep`. L'œil est la
   source de vérité ; l'activation n'est qu'un rafraîchissement.
5. Rafraîchit la LUT du panneau via `controller.update_color_editor`.
6. Force la plage de la LUT à partir du tableau VTK sous-jacent (le cache
   d'info du proxy n'est pas fiable lorsque des tableaux sont ajoutés sur
   place par le pipeline C++).

`refresh_active()` réexécute les trois gestionnaires sans passer par des
mutations d'état — utilisé par le chemin de chargement manuel et par le
gestionnaire de chargement pour rattraper les activations qui se sont
déclenchées avant le chargement des données.

`notify_active_reps(present_paths)` est appelé par le moteur après chaque
chargement pour masquer les barres de couleur obsolètes des reps qui ne
sont plus dans la sélection.

### Couche des sources

- **`Collector`** enveloppe un proxy `pvsimple.FESPP`. `add_file(path)`
  pousse le fichier, appelle `UpdatePipelineInformation`, et exécute
  `controller.update_data_information`.
- **`SourceRegistry`** est le registre hérité par rep : maintient
  `{rep_path: ExtractBlockRepresentation | IjkGrid}` et expose une
  fine surface de compatibilité (`get`, `get_ijk_grid`, `get_extract_block`,
  `add_threshold`, `slice_set`, …). La plupart des méthodes par rep sont
  dépréciées et ne sont atteignables qu'en repli lorsque `SceneRegistry`
  ne peut pas honorer la requête (démarrage précoce, `vtkEPCCollectorClone`
  manquant) ; le premier appel émet un print `[DEPRECATED]` unique. Le
  nouveau code cible `SceneRegistry`.
- **`ExtractBlockRepresentation`** est le wrapper hérité non-IJK.
  Ses méthodes slice / clip / threshold sont désormais aussi dépréciées —
  le `RepInScene` par-(rep, vue) détient ces préoccupations.
- **`IjkGrid`** a un double usage : il existe toujours comme instance
  héritée porteuse de métadonnées (une par rep, indexée par node id de
  propriété), ET chaque `RepInScene` pour un rep IJK instancie son PROPRE
  `IjkGrid` par vue, paramétré avec `view_id` / `clone` / `pv_view`. L'instance
  par vue a son propre rep_data + slicers + volume + chaîne,
  ancré sur le clone de la scène. `set_node_id` bascule la propriété
  active ; `apply_slice_positions` / `apply_range` / `apply_mode` /
  `apply_volume_visible` patchent l'état du slicer.

### Couche View-Scenes

La couche view-scenes se situe entre le moteur et la couche de sources
héritée. Chaque panneau de rendu détient un `ViewScene` qui, à son tour,
détient un `RepInScene` par rep chargé. Tout l'état par-(rep, vue) vit ici.

```
SceneRegistry              ← single instance, on server.context.scene_registry
└── ViewScene (per panel)  ← created on FesppMultiView.add_view
    ├── _clone: vtkEPCCollectorClone        # the structural anchor
    └── _reps: { rep_path: RepInScene }
         └── RepInScene
              ├── _extractor       # per-(rep, view) EnergisticsExtractor (non-IJK)
              ├── _chain           # per-view threshold chain (non-IJK)
              ├── _per_view_ijk    # per-(rep, view) IjkGrid pipeline (IJK)
              ├── _slice_plane     # per-(rep, view) SlicePlane
              └── _clip_plane      # per-(rep, view) ClipPlane
```

#### `SceneRegistry`

- `add_view(panel_id, pv_view)` — appelé depuis `FesppMultiView.add_view`.
  Crée un `ViewScene` pour le panneau, qui instancie paresseusement un
  proxy `vtkEPCCollectorClone` sur le collector. Journalise
  `[SCENE_REG] add_view(...) clone=...` afin que la comptabilité par vue
  soit visible sans instrumentation de l'UI.
- `remove_view(panel_id)` — détruit le `ViewScene` (qui détruit chaque
  `RepInScene` qu'il détenait).
- `sync_loaded_reps(loaded_rep_paths)` — déclenché à chaque
  `state.change("ui_loaded_rep_paths")`. Pour chaque scène, ajoute tout
  rep chargé qui n'y est pas encore et retire tout rep qui n'est plus
  chargé. Après chaque ajout de rep, `_eager_setup_rep_in_scene`
  force-construit l'extracteur par vue (masque l'hérité dans la vue de
  scène) et reflète le ColorBy du panneau actif sur la nouvelle scène.
- `replicate_view(src_view_id, dst_view_id, *, concerns=(...))` —
  itération snapshot/apply : pour chaque rep de src, applique le
  `snapshot_X()` → `apply_X(snap)` de chaque préoccupation sur dst. Les
  préoccupations valent par défaut `("threshold", "slice", "clip", "ijk_slicers")`,
  appliquées dans l'ordre des dépendances (ijk_slicers avant threshold afin
  que la chaîne s'attache au bon ensemble en amont).
- `get_rep(view_id, rep_path)` — la façade principale pour les dispatchers.
- `mirror_legacy_ijk_state(rep_path, legacy_ijk)` — définie mais plus
  auto-déclenchée ; réservée à un usage snapshot/apply ponctuel.

#### `ViewScene`

Détenteur léger du proxy de clone par vue + la carte des reps. Cycle de vie
`add_rep` / `remove_rep`, itérateur `reps()`, `destroy()` démonte tout.

`_create_clone()` utilise `representation._create_plugin_filter_proxy`
qui se rabat de manière transparente de `pvsimple` vers
`vtkSMSessionProxyManager.NewProxy` quand l'espace de noms pvsimple n'a pas
été rafraîchi après `LoadPlugin`. Si le plugin ne livre pas du tout
`vtkEPCCollectorClone`, la scène s'ancre sur la source collector partagée à
la place (journalisé `clone=shared`).

#### `RepInScene`

> **Refactor ElementType (Option A).** `RepInScene` détient toujours l'ÉTAT
> par-(rep, vue) décrit ci-dessous (`_extractor`, `_per_view_ijk`,
> `_channel_extractors` / `_marker_extractors`, `_slice_plane` / `_clip_plane`,
> `_chain`), mais le COMPORTEMENT par-type (construction de la source,
> visibilité, gestion des enfants channel/marker, sources rendues / colorées)
> est délégué à `self.element_type` — la hiérarchie `app/core/element_type/`,
> résolue via `for_path` — à qui `RepInScene` se passe en `ris`. Les méthodes
> ci-dessous (`source()`, `_ensure_extractor`, `_ensure_per_view_ijk`,
> `set_channel_visible`, `_refresh_parent_rep_visibility`…) sont des
> **délégateurs minces**. Détails :
> [REFACTOR_ELEMENT_TYPE_HIERARCHY.md](REFACTOR_ELEMENT_TYPE_HIERARCHY.md) +
> [TYPES_PARTICULARITES.md](TYPES_PARTICULARITES.md).

Le cœur du refactor par-(rep, vue). Trois responsabilités :

1. **Résolution de source.** `source()` retourne le proxy qui
   représente ce rep dans cette vue — l'extracteur par vue pour le
   non-IJK, le rep_data de l'IjkGrid par vue pour l'IJK, en se rabattant
   sur la source partagée héritée quand le chemin par vue ne peut pas
   être construit (repli de la Phase 2 / aucune propriété encore choisie
   sur IJK).

2. **Détention de slice / clip / threshold.** `slice_set` / `clip_set`
   créent paresseusement des filtres `SlicePlane` / `ClipPlane` chaînés
   sur la source par vue. `_chain` (non-IJK) ou `_per_view_ijk._chain`
   (IJK) détiennent la chaîne de threshold par vue. La visibilité est gérée
   par `_refresh_chain_visibility` (la source primaire est masquée
   lorsqu'une extrémité de chaîne est affichée).

3. **Primitives snapshot / apply** par préoccupation :
   `snapshot_threshold_chain / apply_threshold_chain`,
   `snapshot_slice / apply_slice`,
   `snapshot_clip / apply_clip`,
   `snapshot_ijk_slicers / apply_ijk_slicers`.
   Les quatre sont strictement par vue — ne touchent jamais aux
   instances partagées héritées. Utilisées par `replicate_view` (héritage
   au split de vue) et par les controllers `copy_<concern>_from_view` (UI
   de Copy par préoccupation).

Le suffixe `_v<view_id>` sur les noms d'enregistrement est la convention
qui permet à `multi_view._is_per_view_source(name)` de détecter les proxies
par vue et de les ignorer lors de la réplication de la visibilité depuis
une vue de référence vers une nouvelle vue (sinon `GetDisplayProperties`
créerait paresseusement des affichages fantômes Vis=1 dans la mauvaise
vue).

#### Pièges du pipeline IjkGrid par vue

Un ensemble de bugs d'ordonnancement subtils vit dans le chemin IjkGrid par
vue (`RepInScene._ensure_per_view_ijk` → `IjkGrid.set_node_id`). Les quatre
ont été nécessaires pour qu'un IjkGrid à TimeSeries (`dynamicDiscreteProp.epc`)
rende et recolore correctement :

1. **Le clone doit s'exécuter avant que l'extracteur par vue ne soit
   construit.** `_ensure_per_view_ijk` appelle `clone.UpdatePipeline()`
   *avant* de construire l'`EnergisticsExtractor` par vue. Le
   `RequestDataObject` de l'extracteur jette un œil à l'assembly du clone
   pour décider de son type de sortie ; un clone non exécuté a un assembly
   vide → l'extracteur se rabat sur un placeholder `vtkPolyData` → chaque
   `ExplicitStructuredGridCrop` aval le rejette avec
   "Input ... is of type vtkPolyData, but a vtkExplicitStructuredGrid
   is required".
2. **rep_data a besoin d'un `UpdatePipeline()` complet (passe de données)
   avant que les slicers ne s'y chaînent** — `UpdatePipelineInformation()`
   seul ne stabilise pas le type de sortie concret. Le `data_load.run` du
   moteur force aussi une passe de données sur l'extracteur rep_data + chaque
   slicer (pas seulement une passe d'info) afin que les tableaux de
   propriété se propagent en aval.
3. **`_refresh_parent_rep_visibility` délègue à `ijk.show()` pour les reps
   IJK.** Pour le non-IJK la « source du rep » est la géométrie rendue ; pour
   l'IJK l'extracteur `_src_extract_init` ne l'est PAS — `ijk.show()` le masque
   dès qu'un slicer est visible. Un `Show(self.source())` aveugle ici
   repeignait la grille non rognée comme un bloc SolidColor par-dessus les
   slicers (la superposition rouge vue après qu'un 2e selector de propriété
   ait basculé l'array actif via `on_active_array_change`).
4. **L'`ijk_lookup` de l'activator est sensible aux vues**
   (`boot._ijkgrid_by_rep_path` résout l'IjkGrid par vue de la vue cible du
   drawer, repli hérité). Les sources de l'IjkGrid hérité sont masquées dans
   le panneau, donc une recherche purement héritée faisait que
   `_resolve_color_target_source` ne trouvait aucune cible visible et
   abandonnait avant `update_color_editor` — laissant le panneau Colors
   bloqué sur SolidColor quand le nœud actif différait de celui coloré par
   l'œil.

#### Nommage de LUT / PWF à portée par vue

`source_resolver.resolve_target_scoped_lut` et le chemin de rendu
(`apply_color_array` → `swap_to_scene_tfs`) DOIVENT indexer la LUT
par-(scène, array) sur le **nom de tableau VTK assaini**
(`utils.naming.make_valid_vtk_name`), pas sur le titre RESQML brut. Un
titre comme `"Pressure (PRESSURE)"` se matérialise en le tableau VTK
`"PressurePRESSURE"` ; indexer la LUT à portée du COE sur le titre brut
faisait que l'éditeur cherchait un tableau inexistant (plage vide) et
éditait un proxy de LUT différent de celui par lequel les affichages
rendaient.

> **Invariant C++ (nommage des arrays).** Depuis le fix de cohérence du
> nommage, **tout** nom de tableau VTK colorable est produit par le C++
> `MakeValidNodeName` — les propriétés de grille/UG (constructeur
> multi-proc **ET** mono-proc/par défaut) comme les channels de log. Avant
> le fix, le constructeur grille mono-proc et le mapper de channel
> nommaient les arrays avec le titre **brut**, obligeant Python à sonder
> la source pour découvrir le vrai nom porté (`source_resolver.real_base_name`).
> `make_valid_vtk_name` est désormais un **miroir octet-pour-octet** du
> C++ `MakeValidNodeName`, y compris le préfixe `_` ajouté quand le
> résultat est vide ou commence par un chiffre / `-` / `.` (ex.
> `"123abc"` → `"_123abc"`). Les helpers de sondage Python
> (`real_base_name`, les fallbacks titre-puis-assaini dans
> `resolve_array_for_path` / `_original_source_and_name` des stats) sont
> conservés comme **couche défensive** tolérant un plugin obsolète
> (arrays bruts) ; ils pourront être retirés une fois le plugin corrigé
> partout déployé.

Les nouveaux PWF par scène valent par défaut une **opacité plate à 1**
(`ViewScene.get_or_create_pwf` aplatit la rampe 0→1 amorcée par ParaView
quand c'est encore le défaut intact à deux arrêts, en préservant l'étendue
en X). L'opacité NaN est un `NanOpacity` distinct sur la LUT (défaut
0 — transparent), de sorte qu'une courbe de valeurs valides plate à 1 et des
cellules NaN transparentes coexistent, et les éditions d'opacité ultérieures
d'un utilisateur ne sont jamais ré-aplaties (les PWF mis en cache retournent
tôt).

### Couche UI

L'UI est décrite de manière déclarative avec les widgets vuetify3 de Trame
au sein de Python. Conventions clés :

- **Liaison par tuple** `prop=("state_name", default)` expose l'état à
  Vue avec une réactivité bidirectionnelle.
- **`click=(callable, "[args_js]")`** enregistre automatiquement un trigger
  et évalue la seconde chaîne comme une expression JS retournant la liste
  d'arguments.
- **`v_if=`, `v_else_if=`, `v_for=`** correspondent directement aux
  directives Vue.
- **`v_slot_prepend="{ item }"`** etc. exposent les données du nœud d'arbre
  à l'intérieur des templates personnalisés.

`_eye_slot(controller)` (dans `tree_views.py`) rend l'œil de visibilité sur
les nœuds de représentation et l'œil d'array actif sur les nœuds de
data-array. Les deux sont mutuellement exclusifs (`v_if` / `v_else_if`).

`_wire_dependency_expansion(...)` (également dans `tree_views.py`) est un
gestionnaire `@state.change` qui intercepte chaque changement de
`ui_select_node_*` et étend la sélection pour inclure les dépendances
implicites (`Channel/Marker → Trajectory du Wellbore parent`,
`grouping → tous les descendants`).

`_wire_select_to_active(...)` active automatiquement le nœud coché le plus
récemment afin que l'utilisateur voie son panneau immédiatement.

---

## Variables d'état (Trame)

Les variables d'état les plus importantes — il y en a plus, mais ce sont
celles que vous devez connaître pour câbler une nouvelle fonctionnalité.

### Arbres / Sélection

- `ui_subtree_{reservoir,surface,well}` — liste de dictionnaires imbriqués
  rendus par les trois `VTreeview`.
- `ui_opened_{reservoir,surface,well}` — ensemble des ids de nœuds
  développés.
- `ui_select_node_{reservoir,surface,well}` — liste des ids de nœuds cochés
  par onglet.
- `ui_active_node_{reservoir,surface,well}` — liste des ids de nœuds actifs
  par onglet (un seul élément quand actif, vide sinon).
- `_prev_select_{reservoir,surface,well}` — cache interne de l'état
  précédent utilisé par les câblages d'expansion de dépendances +
  select-to-active.

### Pipeline FESPP

- `fespp_data_selectors` — la liste concaténée de chemins poussée au proxy
  collector. Pilotée par le `Selector`.
- `file_loaded` — True une fois que le premier `add_file` a réussi.

### Visibilité / Coloration

Les buckets plats (hérités) et par vue coexistent : les variables plates
reflètent le bucket du **panneau actif** afin que les consommateurs qui ne
connaissent pas les vues fonctionnent encore. Les variables bucket-de-buckets
sont la source de vérité.

- `ui_loaded_rep_paths` — chemins des représentations actuellement
  matérialisées dans ParaView (à travers chaque vue). L'icône œil est
  rendue à côté de ces lignes.
- `ui_loaded_array_paths` — chemins des nœuds de data-array (Property,
  TimeSeries, MultiRealization, …) dont les données sont chargées.
- `ui_hidden_rep_paths_by_view` — `{panel_id: [rep_path, …]}`, l'ensemble
  « masqué » par vue (œil fermé sur la pastille de cette vue). Source de
  vérité pour les pastilles œil par vue dans l'arbre.
- `ui_hidden_rep_paths` — miroir plat du bucket du panneau **actif**.
  Maintenu synchronisé par `multi_view._mirror_active_hidden_state`
  lors des événements d'activation de panneau.
- `ui_active_array_by_rep_by_view` — `{panel_id: {rep_path:
  array_path}}`, choix de ColorBy par vue.
- `ui_active_array_by_rep` — miroir plat du bucket du panneau **actif** ;
  écrit aussi directement par le gestionnaire de chargement à la première
  activation.
- `ui_active_realization_by_array_by_view` — `{panel_id: {array_path:
  idx}}`, le choix de réalisation par vue pour chaque array MR. Pilote
  la superposition RealizationPicker par vue ; consommé par
  `source_resolver.apply_color_array(realization_idx=…)` et par
  `threshold_dispatch._resolve_vtk_array_name`.
- `solid_color_by_rep` — `{rep_path: "#RRGGBBAA"}`, valeur du sélecteur
  par rep (pas par vue — la couleur unie est une propriété du rep).
- `tree_chip_color_by_path` — dérivé : `{rep_path: "PROPERTY" |
  hex_color}`, pilote la pastille de couleur par ligne dans les arbres.
- `active_representation_path`, `active_color_array_name`,
  `active_property_kind` — définis par l'activator à partir du nœud actif,
  pilotent le panneau Attributes.

### Multi-vue

- `fespp_render_panels` — `[{id, title}, …]`, la liste des panneaux de
  rendu (non-diff) actuellement ouverts. Pilote les pastilles œil par vue
  dans l'arbre et les menus déroulants « Copy from view X ».
- `fespp_active_panel_id`, `fespp_active_panel_title` — le panneau de
  rendu actuellement focalisé. Les dispatchers ne le lisent désormais que
  comme repli de fenêtre de démarrage ; les panneaux d'édition du drawer
  Attributes résolvent leur cible via `drawer_target_view_id` (qui
  suit lui-même `fespp_active_panel_id` sauf s'il est épinglé).
- `drawer_target_view_id`, `drawer_target_view_pinned` — le sélecteur de
  vue cible de la carte Attributes. `drawer_target_view_id` est
  l'id de panneau sur lequel opèrent les dispatchers d'édition
  (`slice_dispatch`, `clip_dispatch`, `threshold_dispatch`,
  `slicer_dispatch`). En mode suivi (`drawer_target_view_pinned=False`) il
  se synchronise automatiquement sur `fespp_active_panel_id` ; en mode
  épinglé l'utilisateur l'a choisi via le VSelect rendu en haut du corps de
  la carte Attributes (PAS dans la barre d'outils de la carte — le sélecteur
  a été déplacé dans le corps afin que les largeurs de drawer étroites ne
  l'écrasent pas). Le désépinglage automatique se déclenche quand la vue
  épinglée est fermée (géré dans `boot._on_render_panels_change`).
- `fespp_stats_panel_id` — chaîne non vide quand l'onglet dockview
  singleton « Stats » est actuellement ouvert. Défini par
  `multi_view._add_stats_panel`, effacé lors de son `_on_view_closed`.
  Lu par `controller.toggle_stats_display` pour décider s'il faut
  créer un nouvel onglet de stats lorsque l'utilisateur épingle sa
  première propriété (en évitant les onglets dupliqués / un nouveau à
  chaque épinglage).
- `ui_stats_compare` — `{array_path: [item_key, …]}`, le panier
  **unifié** par propriété qui pilote À LA FOIS le panneau flottant
  Compare-stats (matrice numérique) ET le panneau singleton
  Compare-distribution (traces superposées). Un panier par
  propriété — les paniers `_num` / `_dist` séparés ont été fusionnés en
  cette unique variable selon le refactor de 2026-06 (mélanger des
  propriétés est structurellement impossible puisque le dictionnaire est
  indexé par array_path).
  Les clés d'items sont `f"{array_path}|{row_kind}|{row_id}"`. Muté par
  `stats_dispatch.toggle_compare` (trigger serveur
  `stats_compare_toggle`) ; entièrement vidé pour une propriété par
  `stats_compare_clear`. Les paniers persistent à travers les recalculs de
  `ui_stats_tables` — les clés obsolètes dont la ligne n'existe plus sont
  filtrées hors de `ui_stats_compare_items` plutôt que dans les templates
  de panneau.
- `ui_stats_compare_panel` — `{array_path: panel_id}`, traqueur singleton
  pour les panneaux flottants Compare-stats (a remplacé l'ancien
  `VDialog` selon le refactor de 2026-06 — voir
  `_add_stats_compare_panel` dans `multi_view.py`). Le bouton
  **Compare** par carte dans `descriptive_stats_panel` déclenche le
  trigger `open_compare_stats(array_path)` ; `boot._open_compare_stats`
  fait apparaître un nouveau panneau dockview via
  `mv.add_view(kind="stats_compare")` si aucune entrée n'existe, sinon
  re-pousse les derniers items dans le panneau existant. Les entrées
  sont effacées par `multi_view._on_view_closed` quand l'onglet du
  panneau est fermé. La présence d'une entrée est ce qui conditionne la
  mise à jour en direct `_refresh_compare_stats(array_path)` lors du
  toggle / clear.
- `ui_stats_compare_dist_panel` — `{array_path: panel_id}`,
  traqueur singleton pour les panneaux flottants
  Compare-distribution. Peuplé par le trigger
  `open_compare_distributions` (déclenché depuis le bouton de barre
  d'outils **Show distributions** du panneau Compare-stats — plus depuis
  un bouton d'en-tête de carte distinct) ; les entrées sont retirées par
  `multi_view._on_view_closed` quand l'onglet dockview du panneau est
  fermé (de sorte que le prochain clic sur *Show distributions* fait
  apparaître un nouveau panneau plutôt que d'orpheliner le panier). La
  présence d'une entrée est ce qui conditionne
  `_refresh_compare_dist` et les mises à jour en direct toggle / clear.
- **Variables d'option par panneau (Compare-stats)** —
  `_open_compare_stats` amorce et lit les variables suivantes
  suffixées par `panel_id` (un jeu par panneau stats_compare actif),
  liées par `StatsComparePanel(panel_id)` :
  `ui_stats_compare_array_path_<panel_id>` (la propriété à laquelle le
  panneau est lié),
  `ui_stats_compare_visible_metrics_<panel_id>` (liste des clés de
  métriques AFFICHÉES dans la matrice — sémantique inversée vs l'ancien
  drapeau `hidden_metrics` ; défaut = chaque métrique, le menu de barre
  d'outils retire des clés individuelles),
  `ui_stats_compare_baseline_<panel_id>` (item_key utilisé comme
  ligne de référence en mode comparaison Δ ; la chaîne vide `""` signifie
  `(no baseline)` → repli sur l'ombrage des extrema),
  `ui_stats_compare_order_<panel_id>` (liste d'item_keys
  capturant la disposition de réordonnancement par glisser de
  l'utilisateur ; appliquée dans `_refresh_compare_stats` AVANT
  l'épinglage de la baseline afin que la baseline reste ancrée à gauche de
  l'ordre choisi par l'utilisateur),
  `ui_stats_compare_transposed_<panel_id>` (bool),
  `ui_stats_compare_sort_key_<panel_id>` (clé de métrique pour le tri),
  `ui_stats_compare_sort_asc_<panel_id>` (bool),
  `ui_stats_compare_items_<panel_id>` (liste d'items résolue poussée
  par `_refresh_compare_stats`),
  `ui_stats_compare_csv_<panel_id>` (URL de données base64 pour le
  bouton de téléchargement),
  `ui_stats_compare_annotations_<panel_id>`
  (dictionnaire `{metric_key: {item_idx: tag}}` poussé par
  `compare_matrix.highlight_annotations_for_items` ; le template de
  table le lit pour les liaisons de cellule `:class="{cmp-cell-min/max/pos/
  neg/eq}"` AINSI QUE la pastille Δ pilotée par `it.row[mk]`
  en mode baseline via les entrées auxiliaires
  `annotations._deltas[metric_key][item_idx]` — voir
  la section du module `compare_matrix` ci-dessous). Toutes sont
  effacées sur `multi_view._on_view_closed` quand l'onglet du panneau
  est fermé (la boucle de nettoyage dans multi_view.py itère la
  liste complète y compris `order` / `annotations` afin qu'aucun état
  obsolète ne fuie à travers les réapparitions de panneau).
  Les anciennes variables `ui_stats_compare_highlight_<panel_id>` /
  `ui_stats_compare_normalize_<panel_id>` /
  `ui_stats_compare_topN_<panel_id>` /
  `ui_stats_compare_hidden_metrics_<panel_id>` /
  `ui_stats_compare_pinned_<panel_id>` ont été supprimées lors
  du tour de retours de 2026-06 — le mode de surbrillance dérive
  désormais de `baseline_key` (vide → extrema, défini → baseline) et
  les fonctionnalités heatmap / Top-N / pin ont été retirées en bloc.
- Le panneau dockview Stats s'ouvre comme une **superposition
  flottante** — `_add_stats_panel` appelle
  `self.add_panel(panel_id, title, template, floating={"width":
  1400, "height": 450, "position": {"left": 100, "top": 100}})`.
  Dockview route le kwarg `floating` directement vers son
  API interne `addFloatingGroup` (vérifié dans le bloc de
  routage de panneau du bundle JS : `typeof e.floating === "object" ?
  this.addFloatingGroup(group, e.floating) : ...`). Le
  cadre flottant apporte son propre chrome — bordure de 1px + ombre
  portée + 8 poignées de redimensionnement + glisser-pour-déplacer sur la
  zone vide du tabstrip — donc le template de stats ne peint plus son
  propre encart bleu « panneau actif » (il se battait visuellement avec la
  bordure flottante sans valeur sémantique ; Stats est un singleton donc
  l'indice actif-pour-édition n'est pas nécessaire).

  Points d'entrée + cycle de vie :
  * Bouton de barre d'outils `mdi-chart-box-outline` →
    `controller.open_stats_panel` — toggle ouvrir/fermer pur. Si
    le panneau existe, appelle `mv.remove_panel(existing)` ; sinon
    `mv.add_view(kind="stats")`. Pour remonter une fenêtre flottante
    masquée, l'utilisateur clique deux fois (fermer + rouvrir) et le
    groupe fraîchement ajouté atterrit en haut du singleton de z-index
    de dockview (`be.push(el)` dans le bundle). Des itérations
    antérieures essayaient fermer+rouvrir à chaque clic pour « remonter au
    premier plan » automatiquement, mais cela signifiait qu'un clic sur une
    fenêtre Stats visible la détruisait et la recréait (flash visible,
    aucune valeur sémantique) — le toggle est plus simple et correspond au
    modèle mental « cliquer pour fermer » que les utilisateurs ont pour les
    panneaux flottants.
  * Icône graphique de l'arbre par ligne de Property →
    `controller.toggle_stats_display` →
    `_open_stats_if_closed()` (auxiliaire renommé depuis l'ancien
    `_ensure_stats_panel`). Le premier épinglage sur une propriété ouvre
    la fenêtre flottante ; les épinglages suivants sont des no-ops
    (l'utilisateur ne fait qu'ajouter plus de cartes, pas demander un focus
    ou une remontée).
  * Fermeture = le `×` de l'onglet (dockview émet l'événement
    `remove_panel` de façon identique pour les panneaux flottants, donc
    `_on_view_closed` gère le nettoyage de la même manière qu'il le faisait
    pour les onglets dockés).
  * Re-docker = `Shift+glisser` le titre de l'onglet dans une zone de
    dépôt de la grille — geste dockview natif, aucun code personnalisé
    nécessaire.

  Le même geste `Shift+glisser` promeut n'importe quel panneau DOCKÉ
  (render, diff) en fenêtre flottante sans code de notre côté :
  le gestionnaire de pointeur d'onglet de dockview dispatche sur le
  modificateur `shiftKey` et appelle `addFloatingGroup` sur le
  panneau source directement (`if (r && !h && o.shiftKey) ...
  addFloatingGroup(...)` dans le bundle). L'instance de panneau est
  réutilisée (`skipDispose: true` à l'intérieur du verrou de
  déplacement), donc le pv_view, le montage VtkRemoteView, l'entrée
  scene_registry par vue, les view_links et les variables d'état par
  panneau survivent tous à la transition — même garantie de préservation
  que le chemin d'ouverture de la superposition Stats. Nous n'ajoutons
  délibérément PAS de bouton dédié « rendre ce panneau flottant » sur le
  chrome par panneau : le geste existe, l'exposer comme un bouton
  exigerait de vendoriser un `trame_dockview.umd.js` patché (le
  wrapper n'exporte que addPanel / removePanel / activePanel depuis le
  setup), et le modificateur Shift est une convention suffisamment
  découvrable pour les utilisateurs avancés.

  L'état par propriété (`ui_stats_panel_state[array_path]` —
  liste Originals, instantanés de lignes Custom, etc.) est découplé
  de l'existence de l'onglet : fermer l'onglet n'efface PAS le
  dictionnaire, donc rouvrir via le bouton de barre d'outils restaure
  chaque carte avec ses lignes Custom précédentes en place. Le retrait
  d'une propriété de `ui_stats_pinned_paths` (via l'icône graphique de
  l'arbre ou le × de la carte) ne supprime que cette clé de l'état.
- `ui_stats_panel_minimized` — booléen basculé par le bouton de
  minimisation dans le template du panneau Stats
  (multi_view._add_stats_panel le rend via l'astuce de débordement
  negative-top dans la zone du tabstrip de la fenêtre flottante).
  Quand True, le watcher JS dans
  ui/shared/scripts.py (setupStatsMinimize) reflète le drapeau vers
  une classe `fespp-stats-minimized` sur `<body>` ; le CSS dans
  ui/shared/styles.py réduit ensuite la coque flottante à une
  unique ligne de tabstrip via
  `body.fespp-stats-minimized .dv-resize-container:has(.fespp-stats-panel)`.
  La même règle `:has()` épingle aussi l'élément miroir
  `.dv-render-overlay-float` (l'observateur de redimensionnement de
  dockview copie le rect englobant de la coque dessus à chaque
  changement). `!important` bat le style.height inline de dockview. La
  règle désactive aussi les événements de pointeur de
  `[class*='dv-resize-handle']` pendant la minimisation afin que
  l'utilisateur ne puisse pas glisser-redimensionner vers une valeur qui
  devient la hauteur « restaurée ». La restauration est automatique — effacer
  la classe du body laisse la hauteur inline d'origine (celle à laquelle
  l'utilisateur avait redimensionné avant de minimiser) reprendre effet.
- `ui_stats_panel_maximized` — compagnon mutex de
  `ui_stats_panel_minimized`. Basculé par le bouton
  `mdi-window-maximize` à côté du bouton de minimisation dans le
  chrome de l'onglet Stats ; les gestionnaires de clic Vue dans
  `_add_stats_panel` effacent le drapeau opposé à chaque toggle afin
  que les deux états restent exclusifs (aucune mise en application au
  niveau JS ou CSS — purement une convention UX).
  `setupStatsMinimize` dans `ui/shared/scripts.py` reflète LES DEUX
  drapeaux vers des classes de body en une passe (`fespp-stats-minimized` /
  `fespp-stats-maximized`) et interroge les deux dans le watcher.
  La règle CSS dans `ui/shared/styles.py` pour la maximisation épingle
  `top:0; left:0; right:auto; bottom:auto; width:100%;
  height:100%` sur la coque `.dv-resize-container:has(.fespp-stats-
  panel)` — `right:auto` et `bottom:auto` sont explicites
  parce que le `setBounds` de dockview peut écrire `bottom`/`right`
  au lieu de `top`/`left` quand l'utilisateur a redimensionné via le
  coin inférieur droit ; sans l'auto explicite, la valeur résiduelle
  `right` pousserait la coque maximisée hors écran. Même
  `pointer-events: none` sur `[class*='dv-resize-handle']` afin qu'un
  glisser-redimensionner pendant la maximisation ne fasse pas saigner de
  mauvaises bornes dans le style inline.
- `ui_distribution_figure` — unique dictionnaire `{"data": [...], "layout":
  {...}}` lié au widget Plotly Figure de la superposition Distribution
  flottante. Le `Figure(state_variable_
  name="ui_distribution_figure", ...)` de trame-plotly détient la liaison
  d'état en interne — il écrit `data=(f"{var}.data",)` et
  `layout=(f"{var}.layout",)` à son super, donc passer ces
  kwargs depuis notre côté planterait avec "got multiple values
  for keyword argument 'data'". Les mises à jour côté serveur affectent le
  dictionnaire entier d'un coup (par ex. `state.ui_distribution_figure =
  {"data": [trace], "layout": layout}`). Les traces sont pré-binnées
  via `numpy.histogram` (pour le continu) ou `Counter` (pour le
  discret) et poussées comme `type:"bar"` — JAMAIS `type:
  "histogram"` (qui re-binnerait côté client à partir des valeurs brutes
  et s'étoufferait sur des tableaux d'un million de cellules). La charge
  utile WS reste de quelques Ko quelle que soit la taille du tableau
  source.
- `distribution_dispatch.compute_histogram_figure(state, tree,
  scene_registry, source_registry, array_path, row_kind, row_id,
  *, display_mode, nbins, log_y, show_stats, cumulative, norm,
  return_meta)` — construit une `plotly.graph_objects.Figure` à partir
  d'une ligne Stats. Chaque kwarg d'option peut être laissé à None pour
  prendre le défaut dans `_DEFAULTS` (`bars`, 50 bins, Y linéaire, pas de
  superposition de stats, comptes bruts). Quand `return_meta=True` la
  fonction retourne `(fig, meta)` où meta est `{kept, total, nan,
  bin_centers, bin_heights, bin_widths, chart_title, xaxis_title,
  yaxis_title}` — les données binnées sont remontées afin que l'export CSV
  ne réexécute pas le calcul. La logique de mode d'affichage vit dans
  `_shape_trace_for_mode` : `bars` → `go.Bar` ; `line` →
  `go.Scatter(mode="lines+markers", line.shape="hv")` (escalier) ;
  `curve` → `go.Scatter(mode="lines", line.shape="spline",
  fill="tozeroy")` (aire lissée sous la courbe). La résolution de source
  reflète `stats_dispatch` : les lignes Original chevauchent
  `source_registry.get(rep_path)` (non filtrées), les lignes View
  chevauchent `_resolve_rendered_inputs(scene_registry, source_registry,
  rep_path, view_id)` (sortie post-clip/slice/threshold). Les valeurs NaN
  sont supprimées avant le binning afin que les pairs de kurtosis /
  skewness dans la table Stats restent significatives pour le même
  sous-ensemble. Le titre de l'axe X est construit comme `<Property name> (<unit>)` via
  `stats_dispatch._unit_for_array_path(tree, array_path)` —
  quand l'auxiliaire retourne `""` (build FESPP actuel, voir
  l'accumulateur RESQML), il se dégrade proprement en `<Property name>`
  seul sans parenthèse de fin. Les lignes discrètes / catégorielles
  forcent l'étiquette de l'axe X à `"Category"` quoi qu'il en soit. Le
  dictionnaire meta porte maintenant une clé supplémentaire `legend_label` —
  `", ".join(label_parts)` où `label_parts` est la même
  séquence `[real N, ts <label>]` que le titre du graphique
  intègre déjà pour son suffixe `(real, ts)`. Vide quand ni MR
  ni TS ne s'applique, auquel cas les consommateurs en aval se rabattent
  sur `chart_title` ou la clé de ligne.
- `distribution_dispatch.compute_compare_figure(..., selection_keys,
  *, return_meta=...)` — même surface d'options que le calcul de
  ligne unique, propagée à chaque trace par ligne afin que le panneau de
  comparaison rende toutes les lignes dans une forme cohérente (mode, log,
  norm). Le toggle `show_stats` est intentionnellement supprimé pour les
  panneaux de comparaison (les lignes de moyenne / médiane par ligne
  s'empilent et masquent les formes de trace) ; l'UI du panneau masque
  l'interrupteur via le drapeau
  `ui_distribution_is_compare_<panel_id>`. Les noms de légende
  par trace proviennent du `legend_label` de la meta par ligne
  (pas du `chart_title` plus long) — le panier garantit que chaque
  ligne sélectionnée partage le même `array_path`, donc le nom de la
  propriété est redondant dans la légende ; seuls les axes real / TS
  varient entre les traces. Le titre de l'axe X de comparaison réutilise
  `_unit_for_array_path` contre ce premier `array_path` partagé
  afin que les panneaux de ligne unique et de comparaison étiquettent
  l'axe de manière cohérente.
- `distribution_dispatch.build_csv_from_meta(meta)` — rend une chaîne CSV
  à partir du dictionnaire meta. Ligne unique → 3 colonnes (center, height,
  width). Comparaison → un triplet de colonnes par trace, comblé par index.
  L'étiquette `height` de l'en-tête suit le `yaxis_title` (en minuscules)
  afin que les rendus density / probability portent le bon nom de colonne.
- `@server.trigger("open_row_histogram")(array_path, row_kind,
  row_id)` — déclenché par l'icône `mdi-eye-outline` par ligne à côté
  de l'étiquette Source dans le panneau Stats (pas de colonne `Distr.`
  séparée). Appelle `_spawn_distribution_panel(kind="single",
  context={array_path, row_kind, row_id})`.
- `@server.trigger("open_compare_distributions")(array_path)` —
  variante singleton de superposition multi-traces. Lit le panier
  unifié `state.ui_stats_compare[array_path]` de la propriété, appelle
  `_spawn_distribution_panel(kind="compare",
  context={"array_path": array_path, "kind": "compare"})` à la
  première invocation, puis enregistre le `panel_id` résultant dans
  `state.ui_stats_compare_dist_panel[array_path]` afin que les appels
  suivants réutilisent le même panneau (voir `_refresh_compare_dist` pour
  le flux de mise à jour en direct / désenregistrement). Câblé au
  bouton **Show distributions** de la barre d'outils du panneau
  Compare-stats (plus de bouton d'en-tête de carte).
- `boot._spawn_distribution_panel(kind, context)` —
  fabrique de panneau multi-instance. Effectue
  `mv.add_view(kind="distribution")` (retourne le nouvel id de panneau),
  stocke `context` sous
  `state.ui_distribution_contexts[panel_id]`, amorce les variables
  d'option par panneau avec leurs défauts afin que les liaisons `v_model`
  de la barre d'outils se lient à des valeurs connues, enregistre un
  watcher `state.change` par panneau sur chaque variable d'option (forme
  d'exécution : `state.change(*var_names)(callback)`), et déclenche la
  poussée initiale `_refresh_distribution(panel_id)`. Le watcher appelle
  `_refresh_distribution(panel_id)` qui lit le contexte stocké
  + les variables d'option, réexécute soit `compute_histogram_figure` soit
  `compute_compare_figure` avec `return_meta=True`, pousse la
  figure via
  `controller.update_distribution_figure_<panel_id>(fig)`, et
  écrit la meta (`{kept, total, nan}`) + l'URL de données CSV
  (`data:text/csv;base64,...`) vers leurs variables d'état par panneau afin
  que le badge de barre d'outils + le lien de téléchargement se mettent à
  jour en lockstep.
- Les panneaux de Distribution sont MULTI-INSTANCE : pas de traqueur
  singleton, pas de point d'entrée de barre d'outils, pas de chrome
  minimize/maximize. Chaque clic Hist par ligne et chaque clic
  Compare-histograms fait apparaître un nouveau panneau dockview flottant
  via `multi_view.add_view(kind="distribution")`. L'utilisateur ferme
  avec le `×` de l'onglet dockview ; le glisser/redimensionner sont des
  poignées dockview natives. Liaisons d'état par panneau :
  `ui_distribution_figure_<panel_id>` (charge utile de figure Plotly,
  définie par le widget Figure de trame-plotly),
  `ui_distribution_mode_<panel_id>` (`"bars"|"line"|"curve"`),
  `ui_distribution_nbins_<panel_id>` (int 5..500),
  `ui_distribution_log_y_<panel_id>` (bool),
  `ui_distribution_show_stats_<panel_id>` (bool),
  `ui_distribution_cumulative_<panel_id>` (bool),
  `ui_distribution_norm_<panel_id>` (`"count"|"density"|"probability"`),
  `ui_distribution_meta_<panel_id>` (charge utile de badge),
  `ui_distribution_csv_<panel_id>` (URL de données d'export),
  `ui_distribution_is_compare_<panel_id>` (drapeau de gating UI).
  La méthode de controller `controller.update_distribution_figure_<panel_id>`
  est enregistrée par `DistributionPanel(panel_id).render()`.
  `_on_view_closed` efface toutes les variables d'état par panneau + retire
  l'entrée du panneau de `ui_distribution_contexts` + supprime (delattr) la
  méthode de controller.

Points d'entrée :
- `fespp_settings_scopes` — `[{value, title}, …]`, pilote le
  select Scope dans `GlobalSettingsDialog` (« Global » + chaque panneau
  y compris diff).
- `fespp_diff_panel_id`, `fespp_diff_ready`, `fespp_diff_computing` —
  le cycle de vie du panneau diff singleton.
- `view_links` — `{panel_id: [panel_id, …]}`, groupe de
  diffusion caméra par panneau. Symétrique (l'appartenance est reflétée des
  deux côtés). Lu par `_sync_camera_from` lors d'`EndAnimation`.
- `new_view_dialog_*` — état ouvrir / pré-remplir pour
  `NewViewContentDialog`.

### Threshold / Slice / Clip / slicers IJK (variables UI plates)

Les panneaux du drawer Attributes se lient à des variables plates ; le
gestionnaire de changement de `fespp_active_panel_id` republie l'état de la
vue active dans celles-ci via `slice_dispatch.publish_slice_state` /
`clip_dispatch.publish_clip_state` /
`threshold_dispatch.refresh_threshold_ui_for_active_grid` /
`_push_active_ijk_state_to_ui`.

- `ui_slice_enabled`, `ui_slice_axis`, `ui_slice_offset`,
  `ui_slice_offset_{min,max,step}`, `ui_slice_bounds`.
- `ui_clip_enabled`, `ui_clip_axis`, `ui_clip_offset`,
  `ui_clip_inside_out`, `ui_clip_offset_{min,max,step}`.
- `ui_threshold_chain`, `ui_threshold_arrays_available`,
  `ui_threshold_pending_action` (sentinelle pour les événements add /
  delete / set_range / set_visible). Chaque entrée de chaîne porte maintenant
  `kind` (`"Continuous"` / `"Discrete"` / `"Categorical"`) plus
  `unique_values` (valeurs distinctes triées pour les graduations Discrete /
  Categorical) et `labels` (carte `{value: name}` pour les
  entrées Categorical, lue depuis les `Annotations` de la LUT à la
  création du threshold). Le panneau threshold dispatche la variante de
  slider sur `entry.kind`. La résolution vit dans
  `extract_block.resolve_chain_kind(tree, rep_path, array,
  source_proxy, assoc)` ; les entrées dépassant 64 valeurs uniques sont
  rétrogradées en `"Continuous"` afin que l'UI reste utilisable.
- `ui_stats_pinned_paths` — `[array_path, …]`, l'ensemble piloté par
  l'arbre des propriétés dont les stats sont affichées dans l'onglet
  dockview Stats singleton (`multi_view._add_stats_panel`). Basculé par
  `controller.toggle_stats_display(array_path)` déclenché par le
  bouton `mdi-chart-box-outline` de l'arbre (voir `_stats_slot` dans
  `tree_views.py`). L'icône graphique ne se rend que sur les nœuds de
  propriété dont l'`id` est dans la liste de sélection de l'arbre (par
  arbre : `ui_select_node_reservoir` / `_surface` / `_well`). Épingler
  les stats sur une propriété non cochée n'a pas de cas d'usage et ne
  ferait qu'encombrer la ligne. Au premier épinglage (pas de
  `fespp_stats_panel_id`), `toggle_stats_display` ouvre l'onglet Stats
  lui-même ; les épinglages suivants réutilisent l'onglet existant.
- `ui_stats_panel_state` — `{array_path: {"originals":
  [{"id", "pinned", "real_idx", "ts_idx"}, …]}}`, état du panneau par
  propriété épinglée. La première entrée `originals` est toujours
  `{"id": "default", "pinned": False, "real_idx": None, "ts_idx":
  None}` et la **ligne par défaut** porte des sélecteurs real / TS
  inline que l'utilisateur peut éditer (câblés via
  `controller.stats_set_original_real_idx` /
  `controller.stats_set_original_ts_idx`). L'icône d'épingle prend un
  instantané des sélecteurs actuels de la ligne par défaut dans une nouvelle
  ligne `custom-<n>` (figée — les lignes custom sont en lecture seule).
  Les lignes custom peuvent être retirées via
  `controller.stats_unpin_original`. La ligne par défaut n'est jamais
  retirable.
- `ui_stats_tables` — `{array_path: {"title": str,
  "rep_title": str, "kind": str,
  "rows": [{"kind": "original"|"view", "id", "label", "real_idx",
  "ts_idx", "ts_label": str, "pinned"?: bool,
  …vtkDescriptiveStatistics output}, …],
  "available_realizations": [int, …],
  "available_timesteps": [float, …]}}`. Calculé par
  `stats_dispatch.publish_descriptive_stats` à partir de l'ensemble épinglé
  + l'état du panneau par propriété + l'état actuel de chaque vue de rendu.
  `rep_title` porte le titre humain de la représentation englobante
  (résolu via `_rep_title_for_array_path`) ; utilisé par l'en-tête de la
  carte de stats comme préfixe `<RepTitle> /` atténué afin que deux reps
  partageant une propriété au nom identique puissent encore être
  distingués. Les lignes Original s'ancrent sur
  `source_registry.get(rep_path)` (non filtrées) ; les lignes View
  s'ancrent sur `_resolve_rendered_inputs(scene_registry, source_registry,
  rep_path, view_id)` qui appelle `sources_for_rep_path` ET
  augmente avec les `clip_output` / `slice_output` par vue du rep, puis
  filtre par Visibility=1. Sans l'augmentation, activer clip / slice sur
  un rep non-IJK masquerait la source en amont et la ligne par vue
  disparaîtrait — le résolveur ne voit que la liste de sources canonique.
  `kind`, `available_realizations` et `available_timesteps` pilotent les
  VSelects real / TS inline de la ligne Original par défaut.

  Le `label` de ligne porte le texte de la colonne Source — titre de
  propriété pour les lignes Original, `f"{title} On {view_title}"` pour les
  lignes View. L'index de réalisation et le pas de temps vivent maintenant
  dans leurs propres colonnes gardées par kind plutôt que dans le suffixe
  du label ; `real_idx` / `ts_idx` sont les valeurs brutes, `ts_label` est
  la date lisible par l'humain (`YYYY-MM-DD`, l'heure du jour retirée par
  `time_realization._shorten_time_label`).
- `ui_stats_compare_items` — `[{"key", "row", "propertyTitle",
  "column_label", "extrema": {metric_key: "min"|"max"}}, …]`.
  `extrema` est peuplé côté serveur dans `publish_compare_items`
  dès que ≥ 2 items sont sélectionnés : pour chaque métrique numérique nous
  trouvons la valeur min / max à travers le panier et taguons les
  items porteurs. `StatsComparePanel` lit `item.extrema[metric_key]`
  et peint la cellule en vert (max) / ambre (min). Fait
  côté serveur afin que les liaisons `:style` de Vue n'aient pas à agréger
  à travers les pairs v-for à chaque rendu. La liste de clés traversée
  (`_COMPARE_METRIC_KEYS` dans `stats_dispatch.publish_compare_items`)
  inclut maintenant `"Q1"`, `"Median"`, `"Q3"` aux côtés des
  clés vtkDescriptiveStatistics, afin que les cellules IQR dans le dialogue
  portent la même surbrillance d'extrema que Min / Max / Mean.
  `column_label` est le texte d'en-tête par item rendu dans la
  matrice Compare-stats ; pour les lignes non-View il porte un
  préfixe `<rep_title> / <real N, ts label>` issu du
  `rep_title` de la table parente (voir `ui_stats_tables` ci-dessus) afin que
  deux reps livrant le même nom de propriété restent distinguables
  au niveau de l'en-tête de colonne. Les lignes View réutilisent leur propre
  label inchangé (il encode déjà l'identité de la vue).

Ajouts au contrat de ligne de stats à signaler (en lockstep avec
`stats_dispatch._compute_one_variable`, autour de la ligne 235 de ce
module) :

- **`Q1` / `Median` / `Q3`** — trois nouvelles clés numériques sur chaque
  dictionnaire de ligne, calculées via `numpy.percentile(arr, [25, 50, 75])` sur
  le même tableau dépouillé des NaN que `_compute_one_variable` construit
  déjà pour le filtre vtk (la sortie du threshold, récupérée via
  `dsa.WrapDataObject(...).PointData / CellData`). `Median` est
  le centre de l'IQR — il diffère du `Mean` de vtk par définition, donc
  les deux sont exposés. Les échecs (tableau de longueur nulle, dalle
  entièrement NaN) passent silencieusement — les clés sont simplement
  absentes de la ligne et l'UI rend le même tiret cadratin que pour toute
  métrique manquante.
- **`stats_dispatch._unit_for_array_path(tree, array_path)`** —
  auxiliaire qui parcourt le `vtkDataAssembly` depuis l'array_path,
  inspecte `find_attribute_value(node_id, "uom")`, et retourne
  la chaîne d'unité élaguée (ou `""` quand absente). Retourne
  actuellement toujours `""` car le
  `ResqmlDataRepositoryToVtkPartitionedDataSetCollection` de FESPP n'écrit
  pas encore `uom` (ni `resqmlKind`) comme
  attributs de nœud `vtkDataAssembly` — voir l'accumulateur RESQML
  pour le correctif côté C++ qui allume ceci. Une fois le côté C++
  livré, l'étiquette de l'axe X du panneau Distribution
  (`<Property> (<unit>)`) et tout futur widget tenant compte de l'unité
  prendront la valeur sans aucun changement côté Python.
- **`stats_dispatch.{toggle,clear}_compare`** — les primitives de panier
  unifié par propriété (le refactor de 2026-06 a fusionné
  les paniers `_num` / `_dist` séparés en un seul).
  `toggle_compare(state, array_path, item_key)` bascule `item_key`
  dans `state.ui_stats_compare[array_path]` ; `clear_compare(state,
  array_path)` supprime tout le panier pour une propriété. Câblé via
  les triggers serveur `stats_compare_toggle` / `stats_compare_clear`
  (enregistrés dans `boot.py`) ; les deux triggers appellent en plus
  `_refresh_compare_stats(array_path)` et
  `_refresh_compare_dist(array_path)` pour tout panneau actuellement
  enregistré sur cette propriété afin que les mises à jour en direct
  gardent la matrice + la superposition en lockstep. Parce que le panier de
  chaque propriété est une liste séparée, aucun gating inter-propriétés /
  snackbar de rejet n'est nécessaire — mélanger des pommes avec des kg est
  structurellement impossible. L'UI garde la colonne **Cmp** +
  le bouton **Compare** aux seules cartes MR / TS : les cellules se rendent sous
  `ui_stats_tables[array_path].is_mr || .is_ts` et le
  bouton `Compare` se trouve sous la même garde (`_can_cmp` dans
  `descriptive_stats_panel._render_card_header`). Les cartes
  Continuous simples n'exposent donc jamais l'UI du panier du tout.
- **Cycle de vie du panneau flottant Compare-stats** — a remplacé l'ancien
  `VDialog`. Trois pièces :
    * **`multi_view._add_stats_compare_panel(panel_id,
      template_name, panel_title)`** — construit le corps du panneau
      dockview flottant via
      `StatsComparePanel(panel_id).render()` (HTML pur — pas de
      pv_view, pas d'entrée scene_registry), puis appelle
      `self.add_panel(..., floating={"width": 1100, "height":
      600, "position": {"left": 180, "top": 100}})`. Enregistré
      via `add_view(kind="stats_compare")` depuis
      `_open_compare_stats`.
    * **`boot._open_compare_stats(array_path)`** (trigger
      `open_compare_stats`) — singleton par propriété : recherche
      `state.ui_stats_compare_panel[array_path]`. S'il est présent,
      appelle simplement `_refresh_compare_stats(array_path)` pour pousser
      les derniers items dans le panneau existant. S'il est absent,
      appelle `mv.add_view(kind="stats_compare")` pour faire apparaître un
      nouveau panneau, enregistre le nouveau `panel_id` dans
      `ui_stats_compare_panel[array_path]`, amorce les variables d'option
      par panneau (`ui_stats_compare_*_<panel_id>`) avec leurs
      défauts, puis exécute le rafraîchissement initial.
    * **`boot._refresh_compare_stats(array_path)`** — réexécute
      `stats_dispatch.publish_compare_items(...)` contre le
      panier actuel `ui_stats_compare[array_path]`, applique la
      **clé de tri + direction** par panneau côté serveur (afin que
      les indices d'annotation de classe de cellule s'alignent avec l'ordre
      des lignes rendu), applique la disposition de réordonnancement par
      glisser de l'utilisateur depuis `ui_stats_compare_order_<panel_id>` (les
      clés non présentes dans la liste traînent à la fin afin que les
      nouvelles additions au panier atterrissent en dernier), épingle la
      ligne baseline en premier quand l'une est définie afin qu'elle reste
      ancrée à gauche de la zone de défilement, tague chaque ligne
      survivante avec `it["profile"] = compare_matrix.profile_tag(row.Skewness,
      row.Kurtosis)`, dérive le **mode** de surbrillance de
      `baseline_key` (vide → `"extrema"`, défini → `"baseline"`
      — plus de `"heatmap"`, pas de variable de toggle séparée), calcule
      le dictionnaire de surbrillance de cellule via
      `compare_matrix.highlight_annotations_for_items(items,
      mode, baseline_key=...)`, puis écrit le résultat dans
      `ui_stats_compare_items_<panel_id>` (la source de données de la
      table) et `ui_stats_compare_annotations_<panel_id>`
      (la recherche de classe de cellule), et reconstruit l'URL de données
      CSV via `compare_matrix.items_to_csv(items,
      hidden_metrics=...)` → écrit
      `ui_stats_compare_csv_<panel_id>` pour le `<a :href download>` du
      bouton Download. Pas de tranche `Top N` — le
      slider a été supprimé lors du tour de 2026-06.
    * **watcher `state.change` dans `_open_compare_stats`** —
      après que les variables d'option par panneau ont été amorcées, le
      chemin de spawn enregistre un unique watcher (forme d'exécution
      `state.change(*watched)(_on_compare_stats_options_changed)`)
      sur les variables d'option qui mutent la forme / le contenu de la
      matrice : `ui_stats_compare_baseline_<panel_id>`,
      `ui_stats_compare_sort_key_<panel_id>`,
      `ui_stats_compare_sort_asc_<panel_id>`,
      `ui_stats_compare_order_<panel_id>`. Le gestionnaire
      appelle simplement `_refresh_compare_stats(array_path)` —
      chaque interaction de barre d'outils qui bascule le tri, la baseline
      ou le réordonnancement par glisser déclenche donc un unique tour de
      re-publication. Visible-metrics + transpose ne sont PAS dans la
      liste du watcher : ils ne mutent que la projection de colonnes
      visibles (un computed Vue-template pur), donc une
      re-publication ne ferait que dupliquer le travail.
    * **Désenregistrement** — `multi_view._on_view_closed(panel_id)`
      itère `ui_stats_compare_panel` et retire l'entrée
      dont la valeur correspond au `panel_id` fermé (reflète la
      passe de nettoyage de stats_compare_dist_panel) ; les variables
      d'option par panneau sont aussi effacées dans le même gestionnaire.
- **`boot._refresh_compare_dist(array_path)`** — auxiliaire de cycle de
  vie du panneau Compare-distribution singleton. Cycle de vie :
    * **Spawn** — le trigger `open_compare_distributions(array_path)`
      appelle `_spawn_distribution_panel(kind="compare",
      context={"array_path": array_path, "kind": "compare"})`,
      qui retourne un nouveau `panel_id`.
    * **Enregistrement** — `state.ui_stats_compare_dist_panel[array_path]
      = panel_id` afin que les appels suivants à
      `open_compare_distributions(array_path)` trouvent le
      panneau existant et rafraîchissent sur place (singleton par
      propriété).
    * **Mise à jour en direct** — chaque `stats_compare_toggle` /
      `stats_compare_clear` vérifie si la propriété a un
      panneau enregistré et appelle `_refresh_compare_dist` pour
      réexécuter `compute_compare_figure` à partir de la sélection
      `ui_stats_compare[array_path]` actuelle et pousser la
      figure via le
      `controller.update_distribution_figure_<panel_id>` du panneau. Quand
      le panier tombe en dessous de 2 items, une figure Plotly placeholder
      avec l'annotation « Add 2 or more rows… » est poussée à la place
      (le panneau reste monté avec une figure valide).
    * **Désenregistrement** — `multi_view._on_view_closed(panel_id)`
      itère `ui_stats_compare_dist_panel` et retire l'entrée
      dont la valeur correspond au `panel_id` fermé ; le prochain
      `open_compare_distributions(array_path)` fait alors apparaître un
      nouveau panneau plutôt que de se rattacher à l'id mort.
- **`@server.trigger("open_compare_distributions")(array_path)`**
  — ouvre ou focalise le panneau Compare-distribution singleton
  pour `array_path`. Câblé au bouton de barre d'outils **Show distributions**
  du panneau Compare-stats (plus un bouton d'en-tête de carte — le
  point d'entrée a été déplacé dans le panneau Compare-stats
  lors du refactor de 2026-06). L'implémentation vit dans `boot.py` ;
  voir `_refresh_compare_dist` ci-dessus pour le cycle de vie singleton.
- **module `compare_matrix.py`** — primitives Python pures pour
  le panneau Compare-stats (aucun accès PV / état ; prend une liste
  de dictionnaires d'items tels que produits par
  `stats_dispatch.publish_compare_items`). Cinq fonctions
  publiques :
    * `visible_metric_keys(hidden_metrics)` — retourne les clés de
      métriques dans l'ordre canonique moins celles que l'utilisateur a
      masquées via le multi-select de la barre d'outils. Soutient à la fois
      le rendu de la table et l'export CSV afin qu'ils restent synchronisés.
    * `sort_items(items, sort_key, sort_asc)` — tri stable par
      une clé de métrique. Les valeurs None / non numériques coulent au
      fond. (Actuellement utilisé côté serveur comme base du
      tri par clic d'en-tête en mode transposé du panneau ; le template de
      table trie aussi côté client sur la même clé.)
    * `highlight_annotations(items, mode, baseline_key=None)`
      — retourne `{metric_key: {item_idx: tag}}` où le tag
      dépend de `mode` : `extrema` → `'min' | 'max'`,
      `baseline` → `'pos' | 'neg' | 'eq'` (signe du delta vs
      la ligne baseline), `heatmap` → float dans `[0, 1]` (position
      relative dans min..max). Le panneau applique le tag comme une
      classe CSS sur la cellule correspondante.
    * `items_to_csv(items, hidden_metrics=None)` — rend la
      matrice de comparaison en CSV (lignes × métriques visibles).
      `_csv_escape` / `_csv_num` (auxiliaires privés du module)
      gèrent l'échappement + le formatage numérique. Utilisé par
      `boot._refresh_compare_stats` pour produire l'URL de données
      liée au bouton Download.
    * `profile_tag(skewness, kurtosis)` — classificateur de forme de
      distribution pilotant la pastille par ligne dans le panneau
      Compare-stats. Seuils (conventionnels ; ajustables dans la tête du
      module si un projet veut un jour des coupures plus strictes) :
      `|excess kurtosis| > 3` → `"heavy_tail"` (l'emporte quoi qu'il en soit
      du skew) ; `skew >= 0.5` → `"skewed_right"` ;
      `skew <= -0.5` → `"skewed_left"` ;
      `|skew| < 0.5 AND |excess kurtosis| < 1` → `"symmetric"`.
      Tout le reste (par ex. skew modéré + kurtosis modéré)
      retourne `""`. Les entrées vides / non numériques retournent aussi
      `""` afin que le template de panneau puisse masquer la pastille
      proprement via `v_if="it.profile"`. vtkDescriptiveStatistics émet
      une kurtosis de Pearson (déjà en excès) ; l'auxiliaire traite
      l'entrée comme un excès (centré sur 0).
    * `highlight_annotations_for_items(items, mode,
      baseline_key=None)` — wrapper au-dessus de
      `highlight_annotations` qui plonge dans `item['row']`
      (le dictionnaire où `_compute_one_variable` stocke Mean /
      Std Dev / …) afin que le panneau puisse garder sa forme d'item plus
      riche (`{key, label, row, profile, …}`) sans
      l'aplatir. Retourne la même forme `{metric_key: {item_idx:
      tag}}` ; en mode `baseline` il peuple AUSSI un
      dictionnaire auxiliaire `out["_deltas"][metric_key][item_idx] =
      {abs, rel}` afin que le template puisse rendre la pastille Δ inline
      `↑ / ↓ + value + %` sans re-dériver l'arithmétique côté
      client. La recherche de baseline correspond à
      `it['key'] == baseline_key` au niveau du wrapper (le
      dictionnaire `row` ne porte pas la clé du panier). Appelé depuis
      `boot._refresh_compare_stats` une fois par rafraîchissement ; le
      template lit
      `((annotations || {})[metric_key] || {})[row_index]`
      comme une expression Vue pure pour à la fois la liaison `:class`
      et le `v_if` de la pastille Δ.
- `ui_descriptive_stats` — liste héritée de ligne unique de la Brique A,
  gardée par défaut à `[]` pour le chemin de repli de démarrage. La Brique B
  l'écrit à `[]` à chaque recalcul afin qu'aucune liaison de panneau
  résiduelle ne montre de lignes obsolètes.
- `ui_slices_{i,j,k}_list`, `ui_slices_{i,j,k}_visible_list`,
  `ui_slices_range_{i,j,k}`, `ui_slices_range_mode`,
  `ui_slices_volume_visible`, `ui_range_{i,j,k}` (les bornes d'étendue
  IJK).
- `ui_plane_edit_mode` (`"slice" | "clip" | null`) — quel widget de plan
  3D est en cours d'édition. Partagé entre slice et clip — un seul
  widget visible à la fois.

### Affichage général

- `tree_hierarchy_mode` — `"flat"` / `"by_interpretation"` /
  `"by_feature_and_interpretation"`.
- `tree_hierarchy_snackbar_visible` — fait apparaître le snackbar
  d'avertissement quand une sélection non vide est effacée.
- `load_mode` — `"auto"` / `"manual"`.
- `show_mode` *(alias déprécié)* — conservé pour compatibilité.
- `ui_scale_z` — exagération globale de l'axe Z.
- `representation_active` — Surface / Wireframe / Points …

### Réalisation / Temps

- `ui_panel_active_mr_specs_by_id` — `{panel_id: [{array_path,
  title, available_indices, current_idx}, …]}`, pilote la
  superposition RealizationPicker par vue.
- `panel_has_mr_by_id`, `panel_has_ts_by_id` — `{panel_id: bool}`,
  dérivés de la carte des specs ; gardent la visibilité de
  RealizationPicker / TimeControl par vue.
- `ui_global_mr_specs`, `ui_global_mr_selected_path`,
  `ui_global_mr_selected_spec` — le sélecteur « définir cette réalisation
  partout » de la barre d'outils.
- `time_value_<panel_id>`, `ui_time_label_<panel_id>` — valeurs
  TimeControl par panneau.

### Journalisation VTK / Upload

- `vtk_log_messages`, `log_panel_open`.
- `upload_uploading`, `upload_progress`, `upload_file_count`,
  `upload_file_names`, `upload_session_id`.

---

## Modèle de sélection / visibilité / coloration

Trois concepts orthogonaux :

| Concept | Source d'état | Effet |
|---------|--------------|--------|
| **Chargement** | `ui_select_node_*` (UI) → `fespp_data_selectors` (Selector) → collector C++ | Les données sont matérialisées dans ParaView. |
| **Visibilité** | `ui_hidden_rep_paths` (œil sur le rep) | `display.Visibility` sur chaque source rendant le rep. Indépendant du chargement — un rep masqué est toujours chargé. |
| **Coloration active** | `ui_active_array_by_rep` (œil sur le data-array) | `ColorBy(array)` sur le rep quand présent, `ColorArrayName=""` (→ DiffuseColor) quand absent. |

Le **nœud actif** (`ui_active_node_*`) est encore un autre concept,
purement-UI : il indique au panneau Attributes quoi rendre. Il n'a aucune
incidence sur ce qui est chargé ou visible.

La **teinte par défaut** est enregistrée dans `solid_color_by_rep` au
premier chargement (une couleur par rep, choisie depuis
`color_palette.color_for_index`) et reste dans `display.DiffuseColor`
indépendamment de ce que fait le ColorBy — donc quand l'utilisateur ferme
tous les yeux de data-array sur un rep, la couleur diffuse prend le relais
instantanément.

---

## Flux de données critiques

### Chargement de fichier

1. L'utilisateur choisit un fichier dans le dialogue d'import → POST `/upload`.
2. `upload_endpoint.py` enregistre le fichier dans un répertoire temporaire,
   appelle `controller.load_epc_file(path)`.
3. `Collector.add_file` définit la propriété de proxy `Files` et exécute
   `UpdatePipelineInformation`. `RequestData` déclenche une construction de
   l'assembly de données C++ via `addFile`.
4. `controller.update_data_information` lit l'assembly vivant
   (`GetLiveAssembly` si disponible, sinon le `GetDataAssembly` de la
   sortie du pipeline) et appelle `_tree.set_tree(assembly)` →
   `state.ui_subtree_*` peuplé.
5. Vuetify rend les arbres.

### Clic sur une case à cocher

1. L'utilisateur clique sur une case à cocher → l'événement `update_selected`
   mute `ui_select_node_*`.
2. `_wire_dependency_expansion` s'exécute en premier : ajoute les
   descendants des groupements et les deps `Channel/Marker → Trajectory`.
   Écrit la liste étendue de retour dans `ui_select_node_*`.
3. `_wire_select_to_active` s'exécute ensuite : active le nœud
   nouvellement coché en écrivant dans `ui_active_node_*`.
4. `Selector.select_node_*` s'exécute : traverse les ids → chemins, écrit
   `state.fespp_data_selectors`.
5. Le gestionnaire de chargement (`@state.change("fespp_data_selectors")`)
   pousse les selectors au collector, synchronise `RepSources`,
   met à jour le suivi chargement/visibilité, exécute `refresh_active`,
   rend.

### Clic sur l'œil (visibilité)

1. L'utilisateur clique sur l'œil du rep → `controller.toggle_rep_visibility(item.path)`.
2. Le gestionnaire bascule l'appartenance à `ui_hidden_rep_paths`.
3. Résout toutes les sources rendant le rep via `_sources_for_rep_path`
   (ExtractBlock unique pour le non-IJK ; filtre rep_data + slicers pour
   la grille IJK active).
4. Appelle `pvsimple.Show` / `Hide` *et* définit `display.Visibility` —
   ceinture-et-bretelles car l'un ou l'autre seul a été observé échouer
   sur Grid2D.
5. Rend.

### Clic sur l'œil (DataArray)

1. L'utilisateur clique sur l'œil d'un array → `controller.toggle_dataarray_color(item.path)`.
2. Le gestionnaire résout le rep_path parent via
   `_tree.find_representation_node(node_id)`.
3. Met à jour `ui_active_array_by_rep[rep_path]` : retire s'il était
   l'actif courant, le définit sinon (en fermant tout actif précédent
   pour le même rep).
4. `@state.change("ui_active_array_by_rep")` se déclenche :
   `_apply_color_array(rep_path, array_path)` exécute `pvsimple.ColorBy`
   pour chaque affichage, ou efface `ColorArrayName` pour SolidColor.

### Ajouter une vue / scinder / vue vide

1. L'utilisateur clique sur **Split right / below** sur la ligne d'onglet
   d'un panneau → `controller.open_new_view_dialog(direction, reference_panel_id)`.
2. `NewViewContentDialog.open_for(...)` pré-remplit l'état de la modale
   et l'affiche. L'utilisateur choisit l'une des trois actions :
   - **Copy "<source>" scene** → `mv.add_view(kind="render",
     replicate=True, direction=..., reference_panel_id=...)`.
   - **Empty scene** → idem mais avec `replicate=False`.
   - **Diff scene** → `mv.get_or_create_diff_view(...)` (singleton).
3. `FesppMultiView.add_view`:
   - Crée une nouvelle `pvsimple.RenderView`, l'enregistre dans
     `self._pv_internal[panel_id]`.
   - `scene_registry.add_view(panel_id, pv_view)` — instancie
     le `ViewScene` (qui crée son propre
     `vtkEPCCollectorClone`).
   - `scene_registry.sync_loaded_reps(loaded_rep_paths)` — ajoute un
     `RepInScene` pour chaque rep actuellement chargé, avec une
     configuration anticipée (construction de l'extracteur par vue + miroir ColorBy).
   - Quand `replicate=True` et que `ref_view` existe :
     - `_replicate_visibility(ref_view, pv_view)` — reflète la visibilité
       de source partagée (non-par-vue) de ref vers new. Filtre
       les proxies par vue via `_is_per_view_source` afin qu'ils ne
       fuient pas entre scènes.
     - `scene_registry.replicate_view(ref_panel_id, panel_id)` —
       snapshot/apply de chaque préoccupation (ijk_slicers → threshold →
       slice → clip) du `RepInScene` de ref vers celui de new.
   - Quand `replicate=False` et `kind="render"` :
     - `_force_hide_all_sources(pv_view)` — pré-masque chaque source
       partagée afin que les appels paresseux `GetDisplayProperties` ne
       peignent pas de contours fantômes.
   - `_seed_per_view_hidden_state(panel_id, ref_panel_id, kind,
     replicate)` — initialise les buckets `ui_hidden_rep_paths_by_view`
     et `ui_active_array_by_rep_by_view` du panneau (copie depuis ref ou
     démarre vide).
   - Construit le DivLayout du panneau (vue vtk.js + pastille ACTIVE +
     TimeControl + RealizationPicker + chrome caméra + actions).
   - `add_panel(panel_id, title, template, position=...)` —
     dockview ajoute le panneau dans la direction choisie.
   - Si `replicate=True` : `apply_panel_coloring(panel_id)` réexécute
     ColorBy sur les affichages de la nouvelle vue (reflétés depuis le
     bucket d'array actif de ref), puis `_enforce_view_visibility_from_ref`
     effectue une passe de visibilité finale.

### Copier depuis une vue

L'en-tête de chaque panneau de drawer par vue (Slice / Clip / Threshold /
slicers IJK) porte un menu déroulant `copy_from_view_menu.render_copy_menu(concern)`.

1. L'utilisateur clique sur l'icône → le menu s'ouvre listant
   `(fespp_render_panels || []).filter(p => p.id !==
   fespp_active_panel_id)`.
2. L'utilisateur sélectionne une vue pair → déclenche
   `trigger('copy_<concern>_from_view', [src_view_id])`.
3. `_wire_triggers_once()` (dans `copy_from_view_menu.py`) route le
   trigger vers `controller.copy_<concern>_from(src_view=...)`.
4. `boot.py` `_copy_concern(src_view, dst_view, concern,
   rep_path=None)`:
   - Si `rep_path` est donné, prend un instantané depuis le `RepInScene`
     de src et l'applique directement à celui de dst (variante mono-rep).
   - Sinon appelle `scene_registry.replicate_view(src, dst,
     concerns=(concern,))` (tous les reps de src).
   - Rend le pv_view de dst, republie les variables d'état UI plates
     correspondantes (`publish_slice_state` / `publish_clip_state` /
     `refresh_threshold_ui_for_active_grid` /
     `_push_active_ijk_state_to_ui`) quand dst est le panneau actif.

### Changement du mode de hiérarchie de l'arbre

1. L'utilisateur clique sur un mode différent → `tree_hierarchy_mode` mute.
2. `@state.change("tree_hierarchy_mode")`:
   - Pousse la nouvelle valeur au collector via `vtkSMPropertyHelper`.
     Le `SetTreeHierarchyMode` C++ appelle `repository.rebuildAssembly()`
     qui vide les caches de mapper, ré-`Initialize` l'assembly,
     re-traverse chaque fichier chargé, et bump `AssemblyTag`.
     `selectorNotLoaded` et `selectors` sont effacés aussi.
   - Détecte si une sélection non vide était sur le point d'être effacée →
     fait apparaître le snackbar d'avertissement.
   - Efface chaque variable d'état de sélection / visibilité / coloration.
   - `UpdatePipeline()` afin que `RequestData` re-deep-copie l'assembly
     fraîchement reconstruit dans la sortie du pipeline (le
     `update_data_information` Python se rabat sur cette sortie quand
     `GetLiveAssembly` n'est pas lié).
   - Appelle `update_data_information` → `_tree.set_tree(assembly)` →
     les arbres se re-rendent avec la nouvelle disposition.

---

## Pièges courants

- **Le cache d'info du proxy est obsolète** quand le pipeline C++ mute les
  données de partition sur place (`addDataArray`, échange de réalisation).
  Bumpez le MTime du TrivialProducer via `src.GetClientSideObject().Modified()`
  + `src.UpdatePipelineInformation()` avant de lire
  `GetCellDataInformation` / `GetPointDataInformation`. Mieux : interrogez
  l'objet VTK sous-jacent directement via
  `src.GetClientSideObject().GetOutputDataObject(0)`.
- **`vtkDataAssembly::Initialize()` réinitialise le nom du nœud racine** au
  défaut VTK. Re-`SetRootNodeName("data")` toujours après
  `Initialize` — toute correspondance de chemin côté Python est codée en
  dur contre `/data/...`.
- **`GetAssembly()` n'est pas toujours wrappé vers Python.** Utilisez
  `GetLiveAssembly()` (ajouté sous un nom unique pour éviter la collision
  de classe parente) ou rabattez-vous sur
  `GetOutput().GetDataAssembly()` après un `UpdatePipeline`.
- **Mode de chargement « manual » + nœud actif faisant la course avec le
  gestionnaire de chargement.** L'activation peut se déclencher avant que
  le rep n'existe côté C++ ; `Activator.refresh_active()` est le chemin de
  rattrapage utilisé après `apply_pending_selection`.
- **Les noms de propriété multi-réalisations / TimeSeries vivent dans
  `propTitle`, pas `title`** pour les nœuds synthétiques. Ce dernier est la
  variante assainie pour VTK ; vérifiez les deux lors de la recherche
  d'arrays dans les données de cellule/point.
- **Les mutations d'état Trame sont groupées (batched).** Un
  clear-puis-restore dans le même flush se réduit à un no-op, donc les
  callbacks `@state.change` ne se déclenchent pas. Appelez directement les
  fonctions de gestionnaire (comme le fait `Activator.refresh_active`)
  quand vous avez besoin d'une réexécution.
- **`pvsimple.ColorBy(display, None)` est cassé dans PV6** ; utilisez
  `display.SMProxy.SetScalarColoring("", 0)` à la place (voir
  `_apply_color_array` dans le moteur).
- **`click_stop=` de Trame n'est pas une forme de liaison valide.** Utilisez
  le motif de tuple `click=(callable, "[args]")` et acceptez que le clic
  puisse remonter (bubble) (ou enveloppez l'icône dans un div avec un
  `@click.stop` explicite).
- **`GetDisplayProperties(src, view=v)` n'est pas en lecture seule.** Il
  crée paresseusement un proxy d'affichage par défaut (Visibility=1,
  Representation='Outline') si aucun n'existe. Lorsque vous itérez
  chaque source PV dans un contexte où certaines sources sont par vue
  (tout ce qui est créé par `RepInScene` / `ViewScene`), filtrez-les
  via `multi_view._is_per_view_source(name)` d'abord — sinon
  la vue A finit par rendre l'extracteur par vue + la chaîne de la vue B
  comme des contours fantômes.
- **La propriété par vue est taguée par nom via le suffixe `_v<panel_id>`.**
  Chaque nom d'enregistrement par vue DOIT embarquer `self.scene.view_id`
  (ou l'équivalent) quelque part, sinon `_is_per_view_source`
  ne peut pas le filtrer. Même convention pour les sous-proxies IjkGrid
  (`{base}_v<view_id>`). Diverger de la convention fait fuir
  silencieusement la visibilité entre les vues.
- **Les méthodes héritées threshold/slice/clip de
  `ExtractBlockRepresentation` / `SourceRegistry` sont dépréciées** mais
  conservées comme repli de filet de sécurité. Elles journalisent un
  `[DEPRECATED]` unique au premier appel — si vous en voyez un dans les
  journaux de production, quelque chose a transité par l'hérité alors qu'il
  aurait dû passer par le chemin par vue ; enquêtez (typiquement :
  extracteur par vue pas encore construit parce qu'aucune propriété n'a été
  choisie, ou `vtkEPCCollectorClone` est manquant de la DLL du plugin).
- **Les titres de propriété MR ne sont pas des noms de tableau VTK.** Quand
  l'utilisateur applique un threshold sur une propriété MR,
  `state.active_color_array_name` contient le titre (`"VOIL"`) mais le
  tableau de données de cellule réel est `VOIL_real_<idx>` selon le choix
  de réalisation par vue. `threshold_dispatch._resolve_vtk_array_name`
  parcourt le sous-arbre du rep par titre + suffixe la réalisation active ;
  choisit automatiquement le premier index disponible quand la vue n'en a
  aucun. Ne contournez pas ce résolveur si vous ajoutez de nouveaux
  dispatchers qui prennent un « nom de tableau » depuis une chaîne d'UI.

  Le panneau COE applique la même convention : le `_resolve_coe_lut` de
  `solid_color_panel` résout titre → suffixé + le porte à la portée de la
  vue cible du drawer (voir « LUT / PWF par vue » ci-dessous).

- **LUT / PWF par vue.** Le
  `GetColorTransferFunction(name)` par défaut de ParaView retourne un
  singleton indexé par nom de tableau — chaque affichage ColorBy'd avec le
  même nom partage la même LUT, donc une édition COE dans une vue saigne
  vers toutes les autres vues rendant le même tableau. FESPP surcharge cela
  en donnant à chaque `ViewScene` sa propre LUT par-(scène, array)
  enregistrée sous `f"{array_name}__{view_id}"`, puis en re-liant chaque
  `LookupTable` / `ScalarOpacityFunction` d'affichage à cette
  paire à portée juste après `pvsimple.ColorBy`. La surcharge vit dans
  deux auxiliaires :

    - `source_resolver.swap_to_scene_tfs(displays, view, name)` —
      appelé depuis `apply_color_array` ET directement depuis
      `activator._apply_color_for_active_property` (qui fait son
      propre fan-out ColorBy). Retourne la LUT à portée afin que les
      appelants puissent y lier leur barre scalaire.

    - `ViewScene.get_or_create_lut(base)` / `get_or_create_pwf` —
      création paresseuse ; s'amorce depuis le singleton global au premier
      appel afin que la nouvelle scène démarre avec quel que soit le
      choix automatique de PV pour ce tableau.

  Les panneaux COE (`solid_color_panel`, `categorical_color_editor`)
  résolvent vers la LUT à portée de la vue cible du drawer via
  `source_resolver.resolve_target_scoped_lut(name)` à la fois pour les
  lectures et les écritures — la symétrie reste la règle de gating.

  Sur `MultiView.add_view(replicate=True)`, les LUTs de la nouvelle scène
  sont amorcées depuis le singleton global par `swap_to_scene_tfs` ;
  nous appelons ensuite `new_scene.replicate_tfs_from(ref_scene)` pour copier
  les RGBPoints / Points / NanColor / IndexedColors
  / Annotations de la scène de ref sur les proxies à portée de la nouvelle
  scène afin que la première frame de la nouvelle vue montre les éditions de
  l'utilisateur, pas un défaut frais.

  Nettoyage : `ViewScene.destroy()` supprime chaque proxy de LUT / PWF à
  portée. Les singletons globaux indexés par le nom de tableau brut ne sont
  PAS les nôtres — laissez-les tranquilles.

  Récolte de barre obsolète : `activator._apply_color_for_active_property`
  reflète `source_resolver.hide_unused_scalar_bars` après chaque
  ColorBy en appelant `vtkSMTransferFunctionManager().UpdateScalarBars(active_view.SMProxy, 1)`.
  Sans ce balayage, basculer les LUTs à portée pour le même tableau
  entre les activations laisse la barre précédente échouée dans
  `view.Representations` (le manager indexe les barres par `(lut, view)`
  et n'en récolte pas une dont la LUT a perdu sa référence d'affichage
  visible). Cela compte parce que le clic VIcon de stats de l'arbre remonte
  vers la ligne du VTreeview — il n'y a pas de forme de liaison `click.stop`
  fonctionnelle dans trame (voir la note explicite ci-dessus) — donc chaque
  pin/unpin re-déclenche `active.reservoir`, et seul le balayage
  UpdateScalarBars empêche les barres de s'accumuler une-par-array-touché.

  Chemin de rendu : les gestionnaires d'édition COE / catégorielle doivent
  pousser vers la cible du drawer, pas le panneau focalisé. `source_resolver`
  fournit `render_and_push_target(controller)` qui `Render` sur le
  `pv_view` de la scène cible puis appelle
  `view_update_for(target_panel_id)` (se rabattant sur
  `view_update`). Tous les gestionnaires de surcharge COE
  (`_FesppColorOpacityEditor.on_colors_changed` / `on_opacities_changed`
  / `on_preset_name_changed` / `on_nan_color_changed`,
  `CategoricalColorEditor.on_color_change`, `_apply_solid`) l'appellent.
  Sans cela la LUT est mutée côté serveur mais le mauvais
  client vtk.js du panneau reçoit le rafraîchissement en mode épinglé.

  Garde de rescale : `solid_color_panel._update_color_editor` force un
  `RescaleTransferFunction(data_min, data_max)` sur la LUT à portée
  UNIQUEMENT quand elle est encore à la plage par défaut `[0, 1]` de PV (une
  `GetColorTransferFunction(name)` fraîche porte le preset Cool-to-Warm
  sur [0, 1] quel que soit ce à quoi `name` se réfère). Une fois que la LUT
  à portée porte des valeurs de données (après le premier auto-rescale de
  ColorBy ou toute édition COE de l'utilisateur), nous laissons ses
  `RGBPoints` tranquilles — rescaler une LUT éditée par l'utilisateur
  effacerait ses arrêts personnalisés. Le PWF à portée correspondant est
  rescalé en lockstep quand il est aussi à des positions par défaut `[0, 1]`
  — sinon le `background_shape="opacity"` du composant COE
  échantillonne hors plage et rend le gradient comme une unique couleur
  unie (l'arrêt de LUT le plus à gauche).

  Recherche d'info de tableau : `update_scalar_range` et
  `_data_range_for_active_array` interrogent le
  `RepInScene.source()` de la **scène cible** (EnergisticsExtractor par vue) — PAS
  le `self.source_proxy` de ptc (= `GetActiveSource`). L'`ExtractBlock`
  partagé hérité retourné par `GetActiveSource` ne
  porte pas les arrays MR `_real_<idx>` que l'extracteur par vue
  émet, donc la recherche passerait silencieusement à travers jusqu'à
  `scalar_range = [0, 0]` et le gradient rendrait uni.

- **`representation_active` (Surface / Wireframe / …) se diffuse
  à travers les scènes par vue.** `ptc.RepresentBy` n'écrit que
  `Representation` sur un seul affichage (source active × vue active).
  Les pipelines par vue de la Phase 3a signifient que cet affichage est la
  source partagée héritée, qui est MASQUÉE dans les scènes dont
  l'EnergisticsExtractor par vue est en train de rendre. Pour rendre le
  changement visible, `slicer_dispatch.propagate_representation` itère chaque
  `scene_registry.all_scenes()` et applique `Representation` aux
  proxies par vue de chaque scène (extracteur + chaîne + sorties slice / clip
  + pipeline IjkGrid par vue) dans le `pv_view` de cette scène,
  plus les proxies hérités comme filet de sécurité. Il pousse ensuite une
  frame vtk.js fraîche vers chaque panneau via
  `controller.view_update_all()` parce que la propre poussée
  `on_data_change` de ptc se déclenche AVANT ce gestionnaire de
  state.change, donc le client montrerait sinon la frame pré-fan-out.

---

## Ajouter une fonctionnalité : recettes

Un changement typique « ajouter un nouveau toggle qui affecte le côté
C++ » :

1. **Enum / propriété C++** — déclarez dans `Tools/enum.h` si c'est une
   valeur typée, ajoutez les macros `Set/Get` dans `vtkEPCCollector.h`,
   implémentez le setter dans `vtkEPCCollector.cxx`. Faites suivre vers le
   dépôt via `repository.setMyProp(...)`.
2. **Liaison XML C++** — ajoutez un bloc `<IntVectorProperty>` /
   `<StringVectorProperty>` dans `Energistics.xml`. Utilisez
   `panel_visibility="never"` pour le masquer de l'IHM de ParaView.
3. **Variable d'état Python** — `state.setdefault("my_prop", default)` dans
   `fespp_engine.initialize_fespp_engine`.
4. **Auxiliaire de push Python** — fonction qui résout le proxy et
   appelle `vtkSMPropertyHelper(proxy, "MyProp").Set(value)` +
   `proxy.UpdateVTKObjects()`.
5. **`@state.change` Python** — écoute sur la variable d'état, appelle
   l'auxiliaire de push, et tout effet de bord (rebuild, reset).
6. **UI** — ajoutez un `VBtnToggle` / `VSwitch` / etc. lié à la
   variable d'état via `v_model=("my_prop", default)`.
7. **Testez depuis une session fraîche.** Ne supposez pas qu'une variable
   d'état obsolète définisse le défaut du côté C++ : le `state.setdefault`
   du moteur ne s'exécute que la première fois, donc différents chemins de
   code doivent s'accorder sur le défaut.

Pour une fonctionnalité purement UI (par ex. une nouvelle infobulle) :

1. Éditez le template pertinent dans `app/ui/`.
2. Ajoutez toute nouvelle variable d'état dans `fespp_engine.py` (cohérence).
3. Évitez les cycles `@state.change` — écrivez dans une variable d'état
   uniquement quand la valeur a réellement changé (`if new != prev: state.x = new`).

Pour une fonctionnalité de flux de chargement :

1. Trouvez le bon hook dans
   `_on_change_fespp_data_selectors_impl` — la plupart des effets de bord
   du pipeline appartiennent ici.
2. Mettez à jour `ui_loaded_*` / `ui_active_array_by_rep` si votre
   fonctionnalité affecte ce qui apparaît dans l'état d'œil des arbres.
3. N'oubliez pas `notify_active_reps` si vous changez quels reps sont
   affichés.

---

En cas de doute, faites un grep pour une fonctionnalité similaire existante
et suivez la même forme — `ExplicitSelection` (une propriété de proxy
booléenne) et `TreeHierarchyMode` (une propriété de proxy enum + rebuild à
chaud) sont les deux références les plus propres pour les changements
inter-couches.
