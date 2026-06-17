# Particularités de chaque type (côté Python)

> Catalogue exhaustif du comportement de chaque \`kind\` à l'exécution côté Python
> — la colonne vertébrale suivie par tous les types, les écarts par famille, le
> contrat C++↔Python, et un guide de décision sur *à quel niveau* placer une
> modification sans casser les types voisins. Document complémentaire à
> [REFACTOR_ELEMENT_TYPE_HIERARCHY.md](REFACTOR_ELEMENT_TYPE_HIERARCHY.md)
> (*ce que l'on veut*) ; ce document décrit *ce qui est*.

---

## Piège 0 : le `kind` d'exécution ≠ le nom d'enum C++ (`SimplifyXmlTag` retire le préfixe `Wellbore` / le suffixe `Representation`)

L'attribut `kind` que lit chaque recherche Python (`tree.find_type`, le test d'appartenance `_representation_type_in`, chaque comparaison `== "Frame"` / `== "Marker"`) n'est **pas** le nom de l'enum `TreeViewNodeType` C++. Pour tous les nœuds représentation/propriété, c'est `SimplifyXmlTag(object->getXmlTag())` ([ResqmlDataRepository…cxx:690](../../../../fespp/work/src/Plugin/Energistics/Mapping/ResqmlDataRepositoryToVtkPartitionedDataSetCollection.cxx#L690)), qui retire **d'abord** le suffixe `Representation`, puis le préfixe `Wellbore` ([SimplifyXmlTag](../../../../fespp/work/src/Plugin/Energistics/Mapping/ResqmlDataRepositoryToVtkPartitionedDataSetCollection.cxx#L265-L280)). Seuls `Collection` / `Partial` / `Wellbore` sont pilotés par l'enum via `treeViewNodeTypeName` ([:674](../../../../fespp/work/src/Plugin/Energistics/Mapping/ResqmlDataRepositoryToVtkPartitionedDataSetCollection.cxx#L674)) ; les wrappers de propriété synthétiques (`TimeSeries`, `MultiRealization`, `MultiRealizationTimeSeries`) et `Perforation` sont eux aussi pilotés par l'enum.

| Tag XML RESQML / FESAPI (`getXmlTag()`) | Nom d'enum C++ (`enum.h`, mort en Python) | **`kind` d'exécution (ce que voit Python)** | Notes |
|---|---|---|---|
| `WellboreTrajectoryRepresentation` | `WellboreTrajectory` | **`Trajectory`** | préfixe+suffixe retirés |
| `WellboreFrameRepresentation` | `WellboreFrame` | **`Frame`** | le conteneur de log-channels ; `_is_wellbore_frame()` teste `== "Frame"` |
| `WellboreMarkerFrameRepresentation` | `WellboreMarkerFrame` | **`MarkerFrame`** | `Wellbore`+`Representation` retirés → `MarkerFrame` |
| `WellboreMarker` (feuille marker) | `WellboreMarker` | **`Marker`** | préfixe `Wellbore` retiré ; `data_load._update_marker_tracking` teste `== "Marker"` |
| un channel = `ContinuousProperty` / `DiscreteProperty` / `CategoricalProperty` sur un frame | `WellboreChannel` | **`ContinuousProperty` / `DiscreteProperty` / `CategoricalProperty`** | un channel est juste une `AbstractValuesProperty` ; son `kind` est le kind de la propriété. La « nature de channel » est dérivée structurellement (propriété dont l'ancêtre rep est un `Frame`), jamais d'une chaîne `kind` |
| `IjkGridRepresentation` | — | **`IjkGrid`** | suffixe retiré (pas de préfixe `Wellbore`) |
| `UnstructuredGridRepresentation` | — | **`UnstructuredGrid`** | |
| `SubRepresentation` | `SubRepresentation` | **`Sub`** | suffixe retiré |
| `Grid2dRepresentation` | — | **`Grid2d`** | |
| `PolylineSetRepresentation` / `TriangulatedSetRepresentation` / `PointSetRepresentation` | — | **`PolylineSet` / `TriangulatedSet` / `PointSet`** | |
| `SeismicWellboreFrameRepresentation` | — | **`SeismicWellboreFrame`** | ⚠ suffixe `Representation` retiré, mais `SeismicWellbore` ne **commence pas** par `Wellbore` (il commence par `Seismic`), donc le strip du préfixe est sans effet → le kind reste `SeismicWellboreFrame`. Voir la dette. |

### Chaînes MORTES encore présentes en Python

Ces littéraux de noms d'enum ne peuvent **jamais** correspondre à un `kind` d'exécution ; tout test contre eux est du code inatteignable :

- **`'WellboreMarker'`** — le kind d'exécution est `Marker`. Mort dans [tree.py:34](../../fespp_on_trame/app/core/tree.py#L34) (`_representation_type_in`), [tree.py:64](../../fespp_on_trame/app/core/tree.py#L64), [:74](../../fespp_on_trame/app/core/tree.py#L74), [:205](../../fespp_on_trame/app/core/tree.py#L205), [:213](../../fespp_on_trame/app/core/tree.py#L213) ; [tree_selection.py:7](../../fespp_on_trame/app/ui/drawer/config/tree_selection.py#L7) ; la rep marker vivante est `MarkerFrame` et la feuille vivante est `Marker`.
- **`'WellboreChannel'`** — les channels apparaissent comme `ContinuousProperty`/`DiscreteProperty`/`CategoricalProperty`. Mort dans [tree.py:74](../../fespp_on_trame/app/core/tree.py#L74) & [:213](../../fespp_on_trame/app/core/tree.py#L213) (routage partiel par `supporttype` uniquement — inoffensif, jamais atteint pour un vrai nœud) ; le seul usage *vivant* est la règle de dépendance structurelle dans [tree_views.py:33](../../fespp_on_trame/app/ui/drawer/tree_views.py#L33) qui s'appuie sur l'attribut `supporttype` du stub partiel, pas sur `kind`. À noter que `tree_selection.py` liste `"WellboreFrame"` (mort lui aussi — le kind d'exécution est `Frame`).

> Lors de l'ajout d'un nouveau type wellbore, enregistrer le kind d'exécution **dépouillé** (stripped), pas le nom d'enum.

## Table maîtresse (une ligne par `kind` d'exécution)

`Rôle dans l'arbre` = regroupement (dossier) vs représentation (porteuse d'œil) vs feuille-propriété. `Source/pipeline` est le modèle **par-(rep,vue)** dans [rep_in_scene.py](../../fespp_on_trame/app/core/sources/rep_in_scene.py). `Bucket` = quelle liste de visibilité du `state` le gouverne. COE = est-ce que le Color Editor s'allume.

| Kind d'exécution | Famille | Rôle dans l'arbre | Œil | Sélection | Source / pipeline | Bucket de visibilité | Couleur | Bucket du « tableau actif » | COE |
|---|---|---|---|---|---|---|---|---|---|
| `IjkGrid` | reservoir | rep | ✔ œil rep | id propre ou descendant coché | `_per_view_ijk` par-vue (IjkGrid : rep_data + slicers + volume + chaîne), miroir legacy | `ui_hidden_rep_paths*` | ColorBy de propriété ou SolidColor | `ui_active_array_by_rep*` | ✔ (LUT continue / catégorielle) |
| `UnstructuredGrid` | reservoir | rep | ✔ | id/descendant | `_extractor` + `_chain` par-vue | `ui_hidden_rep_paths*` | ColorBy / Solid | `ui_active_array_by_rep*` | ✔ |
| `Sub` | reservoir | rep | ✔ | id/descendant | `_extractor` par-vue | `ui_hidden_rep_paths*` | ColorBy / Solid | `ui_active_array_by_rep*` | ✔ |
| `Grid2d`, `PointSet`, `Polyline`, `PolylineSet`, `TriangulatedSet` | surface | rep | ✔ | id/descendant | `_extractor` + `_chain` par-vue | `ui_hidden_rep_paths*` | ColorBy / Solid | `ui_active_array_by_rep*` | ✔ |
| `Trajectory` | well | rep | ✔ | id/descendant | `_extractor` par-vue | `ui_hidden_rep_paths*` | SolidColor (géométrie ; en général aucune prop) | — | ✖ (effacé par `_publish_active_color_state`) |
| `Completion`, `Perfo` | well | rep | ✔ | id/descendant | `_extractor` par-vue | `ui_hidden_rep_paths*` | SolidColor | — | ✖ (chemin COE **non vérifié** — voir la dette) |
| `Frame` (logs WellboreFrame) | well | **regroupement** (`is_grouping`, `_GROUPING_KINDS`) — dossier dans l'arbre, rep dans la source | ✖ dossier (tri-état d'après les logs enfants) | log enfant coché | **le `_extractor` primaire reste MASQUÉ** (`_channelless_frame`). Chaque **channel** possède son **propre** `EnergisticsExtractor` persistant par-(channel,vue) dans `_channel_extractors`, **EXCLUSIF** un-seul-affiché-à-la-fois (`set_channel_visible`) | log enfant via `ui_active_array_by_rep*` (l'œil = le tableau-actif, pas une pastille de visibilité) | ColorBy sur l'extracteur propre du channel visible | chemin du log enfant dans `ui_active_array_by_rep*` | ✔ sur le channel (continu/discret/catégoriel) |
| `MarkerFrame` | well | **regroupement** | ✖ dossier | marker enfant coché | `_extractor` primaire MASQUÉ (`_channelless_frame`). Chaque marker **visible** possède son propre `EnergisticsExtractor` par-(marker,vue) dans `_marker_extractors`, **MULTI** affichés-en-même-temps (`set_marker_visible`) | `ui_visible_marker_paths_by_view` (+ `ui_loaded_marker_paths`) | `solid_color_by_marker` par-marker → repli sur `solid_color_by_rep` | s.o. (les markers sont des feuilles géométriques, pas des tableaux) | ✖ |
| `Marker` (feuille) | well | feuille de type propriété | ✔ œil de visibilité par-marker (MULTI) | id propre | rendu par les `_marker_extractors[marker_path]` du `MarkerFrame` parent | `ui_visible_marker_paths_by_view` | `solid_color_by_marker` | — | ✖ |
| `SeismicWellboreFrame` | well | rep (chemin auto-show) | ✔ | id/descendant | `_extractor` par-vue (auto-show normal — PAS dans `_channelless_frame`) | `ui_hidden_rep_paths*` | SolidColor | — | ✖ (ambigu — voir la dette) |
| `Wellbore`, `Collection`, `Feature`, `Interpretation`, `Partial` | (par onglet) | **regroupement** uniquement | ✖ | sélection en masse des descendants | aucune (dossier pur) | — | — | — | — |
| `ContinuousProperty` / `DiscreteProperty` / `CategoricalProperty` | (onglet de la rep) | feuille propriété | ✔ œil de tableau de données (`ui_active_array_by_rep`) | id propre (PAS « sous rep cochée ») | colore la source de la rep ; **si la rep est un `Frame`, cette feuille EST un channel** → sa propre entrée `_channel_extractors` | `ui_active_array_by_rep*` | le ColorBy de la rep | soi-même | ✔ |
| `TimeSeries`, `MultiRealization`, `MultiRealizationTimeSeries` | (onglet de la rep) | feuille propriété synthétique | ✔ œil de tableau de données | id propre | colore la rep via `<title>_real_<idx>` suffixé (MR) | `ui_active_array_by_rep*` | ColorBy | soi-même | ✔ (kind via l'attr `propKind`) |

**Changement clé par rapport à l'ancien modèle :** un frame n'a plus « un extracteur de frame partagé dont l'`ExtractPath` est reciblé ». La source de chaque channel est créée une fois et *persiste* (masquée quand un autre channel est affiché), donc sa LUT scopée / son COE / ses stats la lisent directement **sans recible** — `visible_channel_extractor()` retourne celui dont `Visibility=1`, `channel_extractor_for(create=True)` matérialise un masqué pour les lectures hors écran.

## Contrat C++ ↔ Python (les invariants)

### 1. Nommage des tableaux — `MakeValidNodeName` ⇔ `make_valid_vtk_name` (miroir octet pour octet)

Le C++ attache les noms de tableaux VTK via `ResqmlPropertyToVtkDataArray::MakeValidNodeName` ; Python recalcule le même nom à partir du titre RESQML via [`make_valid_vtk_name`](../../fespp_on_trame/app/utils/naming.py#L33-L50). La règle (des deux côtés) :

> retirer chaque caractère hors de `[-.0-9A-Z_a-z]` ; puis préfixer d'un `_` si et seulement si le résultat est vide **ou** si son premier caractère survivant est un chiffre / `-` / `.`.

Les deux doivent rester identiques sinon le COE / la clé de LUT / le ColorBy ratent silencieusement (ex. `"123abc"` → `"_123abc"`). `sanitize_proxy_name` ([:53](../../fespp_on_trame/app/utils/naming.py#L53)) est le sanitizer **opposé** (remplace→`_`) pour les noms d'enregistrement de proxy PV uniquement — ne jamais l'utiliser pour une recherche de tableau.

**Les channels sont désormais aussi sanitizés.** [`ResqmlWellboreChannelToVtkPolyData.cxx:100-101`](../../../../fespp/work/src/Plugin/Energistics/Mapping/ResqmlWellboreChannelToVtkPolyData.cxx#L100-L101) fait passer le nom du tableau de scalaires du tube par `MakeValidNodeName` (et `SetActiveScalars` avec le même nom sanitizé, [:153](../../../../fespp/work/src/Plugin/Energistics/Mapping/ResqmlWellboreChannelToVtkPolyData.cxx#L153)). Avant ce correctif, le tableau POINT d'un channel était nommé avec le titre **brut**, donc le chemin de rendu indexait sa LUT scopée sur le nom brut tandis que le COE sanitizait → deux LUT différentes, graphe COE vide.

**Pourquoi cela compte pour la clé de LUT scopée / le COE :** la LUT scopée par-vue est indexée `f"{array_name}__{view_id}"` sur le nom qui *existe réellement sur la source*. `real_base_name` ([source_resolver.py:189-217](../../fespp_on_trame/app/core/engine/source_resolver.py#L189-L217)) sonde toujours brut-vs-sanitizé par précaution (plugin non recompilé), mais avec le plugin recompilé, les channels sont sanitizés comme les grilles et la sonde se réduit à la branche sanitizée. `stats_dispatch._original_source_and_name` privilégie déjà le nom sanitizé en premier pour les channels ([stats_dispatch.py:514-519](../../fespp_on_trame/app/core/engine/stats_dispatch.py#L514)).

### 2. Partitions & indices de dataset ; adressage par `ExtractPath`

- Un **nœud frame n'a aucun index de partition / de dataset propre** — seuls ses channels/markers enfants en ont. Le frame est `isGroupingType` / un dossier. Rendre le `_extractor` primaire du frame (dont l'`ExtractPath` = le nœud frame) fait que l'extracteur C++ fait apparaître la *première partition enfant* du frame, donc le primaire est délibérément maintenu masqué pour tout frame (`_channelless_frame`, [rep_in_scene.py:746-756](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L746)).
- `EnergisticsExtractor.ExtractPath` adresse un nœud par son **chemin d'assembly** (`panel_visibility="never"`, défini via `vtkSMPropertyHelper(...,"ExtractPath").Set(path)`). Un extracteur par-channel/par-marker définit `ExtractPath` = le chemin du nœud **feuille** afin que seuls le tube/la géométrie de cette unique partition + son tableau de points apparaissent ([_create_channel_extractor](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L547-L599), [_create_marker_extractor](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L636-L699)).

### 3. NaN → 0 dans les channels (plage dégénérée) → garde `nondegenerate_range` du COE

Le C++ remplace les valeurs de channel NaN (continu) / int-en-débordement (discret/catégoriel) par **0** ([ResqmlWellboreChannelToVtkPolyData.cxx:112-138](../../../../fespp/work/src/Plugin/Energistics/Mapping/ResqmlWellboreChannelToVtkPolyData.cxx#L112-L138)) et émet un avertissement. Un log entièrement NaN produit donc un tableau constant à 0 → `lo == hi`. Le CanvasGradient du COE normalise les arrêts en `(v-lo)/(hi-lo)` → division par zéro → le client lève « addColorStop: non-finite double », vidant l'éditeur. [`nondegenerate_range`](../../fespp_on_trame/app/core/engine/source_resolver.py#L147-L170) élargit toute plage `lo==hi` (ou non finie) en une minuscule bande finie pour que le gradient s'affiche presque plat au lieu de planter. La même garde couvre aussi une propriété de grille réellement constante.

## Variables d'état transversales

| Variable d'état | Forme | Renseignée par | Lue par |
|---|---|---|---|
| `ui_subtree_reservoir` / `_surface` / `_well` | liste de dicts treeview imbriqués | `Tree.set_tree` ([tree.py:165](../../fespp_on_trame/app/core/tree.py#L165)) | rendu Vue de `tree_views.py` |
| `ui_select_node_reservoir` / `_surface` / `_well` | list[node_id] (état des cases) | case à cocher de l'arbre + `_expand_selection_with_deps` | `Activator._is_node_active_able`, sélecteurs |
| `ui_active_node_reservoir` / `_surface` / `_well` | list[node_id] (≤1) | clic dans l'arbre | `Activator._handle_*_change` |
| `fespp_data_selectors` | list[path] | sélecteurs | `data_load.run` (le pilote de chargement) |
| `ui_loaded_rep_paths` | list[rep_path] | `data_load._update_visibility_tracking` | sync de scène, pastilles |
| `ui_hidden_rep_paths` | list[rep_path] (panneau actif) | `_update_visibility_tracking` | pastilles d'œil |
| `ui_hidden_rep_paths_by_view` | `{panel_id: [rep_path]}` | `_update_visibility_tracking` | `RepInScene._hidden_in_scene` / `_refresh_parent_rep_visibility`, setup anticipé |
| `ui_loaded_array_paths` | list[array_path] | `_update_data_array_tracking` | maintenance de la map active |
| `ui_active_array_by_rep` | `{rep_path: array_path}` (global = panneau actif) | `_update_active_array_maps`, bascule `active_array` | garde ColorBy de l'Activator, `_ensure_extractor` |
| `ui_active_array_by_rep_by_view` | `{panel_id: {rep_path: array_path}}` | `_update_active_array_maps`, bascule `active_array` | ColorBy par-vue |
| `ui_active_realization_by_array_by_view` | `{panel_id: {array_path: idx}}` | `_update_active_array_maps`, dispatch de réalisation | suffixe de `resolve_array_for_path` |
| `ui_loaded_marker_paths` | list[marker_path] (kind `Marker`) | `_update_marker_tracking` | rendu d'œil de marker |
| `ui_visible_marker_paths_by_view` | `{panel_id: [marker_path]}` | `visibility.toggle_marker_visibility` | `set_marker_visible` |
| `solid_color_by_rep` | `{rep_path: hex}` | boucle de couleur de `data_load` | teinte à la création de l'extracteur |
| `solid_color_by_marker` | `{marker_path: hex}` | panneau de couleur unie | teinte de `_create_marker_extractor` |
| **`active_color_array_path`** *(nouveau)* | str (chemin d'assembly du nœud actif) | `Activator` ([:317](../../fespp_on_trame/app/core/activator.py#L317), [:774](../../fespp_on_trame/app/core/activator.py#L774)), bascule de channel `active_array` ([:406](../../fespp_on_trame/app/core/engine/active_array.py#L406)) | `color_editor.py:155`, `solid_color_panel.py:400` — permet au COE de lire l'extracteur **propre au channel actif** (`channel_source_for`) même quand c'est un channel voisin qui est affiché |
| `active_color_array_name` | str (titre UI) | Activator / bascule de channel | changement de mode du COE, clé de LUT scopée |
| `active_property_kind` | str | Activator | éditeur COE continu-vs-catégoriel |
| `active_representation_path` | str (rep_path) | Activator / bascule de channel | cible COE / stats |
| `drawer_target_view_id`, `fespp_active_panel_id` | str (id de panneau) | focus / épinglage de panneau UI | `target_view_and_panel`, résolution de LUT scopée |

**Retiré / disparu :** il n'y a plus d'état `_extractor_channel_path` (l'ancien curseur de recible de l'extracteur unique). Le COE ne « recible » plus — il lit `channel_source_for(active_color_array_path)`.

## Où vit la logique par-type (carte des fichiers)

| Préoccupation | Fichier · symbole |
|---|---|
| classification du kind d'exécution, parcours de l'ancêtre rep, ensemble de regroupement | [tree.py](../../fespp_on_trame/app/core/tree.py) : `_representation_type_in` (L34), `is_grouping` (L103), `find_representation_node` (L395) |
| dérivation du `kind` d'exécution C++ | `…/Mapping/ResqmlDataRepositoryToVtkPartitionedDataSetCollection.cxx` : `addDefaultToDataAssemblyNode` (L659), `SimplifyXmlTag` (L265) |
| tube de channel + tableau sanitizé + NaN→0 | `…/Mapping/ResqmlWellboreChannelToVtkPolyData.cxx` |
| miroir des noms de tableaux | [naming.py](../../fespp_on_trame/app/utils/naming.py) : `make_valid_vtk_name` (L33), `sanitize_proxy_name` (L53) |
| **modèle de source par-(channel,vue)** | [rep_in_scene.py](../../fespp_on_trame/app/core/sources/rep_in_scene.py) : dict `_channel_extractors` (L61), `set_channel_visible` **EXCLUSIF** (L468), `channel_extractor_for(create=)` (L511), `visible_channel_extractor` (L526), `_create_channel_extractor` (L547) |
| modèle de source par-(marker,vue) | même fichier : `_marker_extractors` (L70), `set_marker_visible` **MULTI** (L601), `_create_marker_extractor` (L636), `visible_marker_displays` (L721), `set_marker_color` (L701) |
| règle du primaire-reste-masqué | même fichier : `_channelless_frame` (L746) ; tests frame/marker `_is_wellbore_frame`==`'Frame'` (L126), `_is_marker_frame`==`'MarkerFrame'` (L148) |
| IjkGrid par-vue + chaîne | même fichier : `_ensure_per_view_ijk` (L188), `_chain` / `_add_threshold_local` (L1245) |
| source de channel pour COE/stats (sans recible) | [source_resolver.py](../../fespp_on_trame/app/core/engine/source_resolver.py) : `channel_source_for` (L118), `_scene_rep_for_view` (L99), `real_base_name` (L189), `nondegenerate_range` (L147) |
| dispatch de source rendue/colorable (frame → `visible_channel_extractor`) | source_resolver : `sources_for_rep_path` (L220, L275), `color_sources_for_rep_path` (L317, L376), `resolve_array_for_path` (L433, L468-481) |
| bascule d'œil de channel → `set_channel_visible` + publication COE | [active_array.py](../../fespp_on_trame/app/core/engine/active_array.py) : branche channel (L380, L400-420) |
| bascule d'œil de marker | [visibility.py](../../fespp_on_trame/app/core/engine/visibility.py) : `toggle_marker_visibility` (L77) |
| suivi au chargement | [data_load.py](../../fespp_on_trame/app/core/engine/data_load.py) : `_update_marker_tracking` ==`'Marker'` (L375), `_update_active_array_maps` (L418) |
| nœud actif → état COE | [activator.py](../../fespp_on_trame/app/core/activator.py) : `_publish_active_color_state` (L742), reservoir inline (L307-319) |

**Symboles retirés** (ne pas les chercher) : `set_extract_channel`, `_extractor_channel_path`, `read_only_channel_retarget`. La bascule est désormais un simple masquer/afficher.

## Guide de décision : à quel niveau placer une modification ?

Trois altitudes. Placer une modification au niveau **le plus bas** qui contient entièrement son rayon de souffle.

**Colonne vertébrale générale** — `tree.py`, `naming.py`, l'ordre de `data_load.run`, le squelette de dispatch de `source_resolver`, `RepInScene.delete`/`source()`. Une modification ici touche **toutes** les familles. N'éditer ici que pour des préoccupations réellement universelles (miroir des noms de tableaux, adressage par chemin d'assembly, ordre de chargement). *Piège : éditer la colonne vertébrale pour corriger une seule famille.*

**Famille** — la branche dans un dispatcher pour IjkGrid vs UG/surface vs **frame** vs marker. Ex. les bras `if rep_in_scene._is_wellbore_frame(): … visible_channel_extractor()` dans `sources_for_rep_path` / `color_sources_for_rep_path`. Ajouter un nouveau comportement de type well en ajoutant une branche ici, pas en élargissant le contrat d'une fonction partagée.

**Unité** — un kind d'exécution / une méthode. `_create_channel_extractor`, `set_channel_visible`, une seule publication COE.

### Exemple traité — la modification de log qui a cassé reservoir + surface

Le **mauvais** niveau était une fonction *partagée*. L'ancienne conception avait **un extracteur de frame dont l'`ExtractPath` était reciblé** vers le channel sélectionné, et le « recible en lecture seule » du COE/stats repointait temporairement ce *même* extracteur partagé pour lire les données d'un channel masqué, puis le restaurait. Parce que le recible mutait une source que d'autres chemins de code supposaient stable, et parce que les rafraîchisseurs de visibilité génériques (`_refresh_parent_rep_visibility`, `_refresh_chain_visibility` — utilisés par **chaque** rep, y compris reservoir + surface) faisaient `Show()` sur le primaire du frame, la logique frame fuyait dans la colonne vertébrale partagée : un rafraîchissement en éventail refaisait apparaître le premier channel du frame dans chaque vue, et la danse recible-restaure entrait en concurrence avec le ColorBy reservoir/surface sur la même LUT partagée.

Le **bon** niveau était la *famille/unité* : donner à chaque channel son **propre** extracteur persistant par-(channel,vue) (miroir des markers), faire de la bascule un simple masquer/afficher exclusif, et garder le primaire avec `_channelless_frame()`. Désormais :
- rien ne recible, donc le COE/stats lisent simplement `channel_source_for(path)` directement (une source masquée-mais-matérialisée) — les chemins reservoir/surface sont intacts ;
- la seule modification de colonne vertébrale est la garde `_channelless_frame()` dans les rafraîchisseurs partagés — un crochet de famille *étroit*, pas un changement de comportement du Show/Hide générique.

**Règle de base :** si votre correctif pour les logs wellbore vous oblige à élargir une fonction que IjkGrid/surface appellent aussi, vous êtes à la mauvaise altitude — ajoutez plutôt une branche gardée par `_is_*_frame()` (famille) ou une méthode dédiée par-enfant (unité).

## Dette identifiée / à nettoyer

- **Chaînes mortes de noms d'enum.** `'WellboreMarker'` (le kind d'exécution est `Marker`) et `'WellboreChannel'` (les kinds d'exécution sont les kinds de propriété) sont inatteignables dans [tree.py:34](../../fespp_on_trame/app/core/tree.py#L34), [:64](../../fespp_on_trame/app/core/tree.py#L64), [:74](../../fespp_on_trame/app/core/tree.py#L74), [:205](../../fespp_on_trame/app/core/tree.py#L205), [:213](../../fespp_on_trame/app/core/tree.py#L213). `tree_selection.py:7` liste `"WellboreFrame"` / `"WellboreMarker"` (tous deux morts ; les kinds vivants sont `Frame` / `Marker`). Les entrées de routage partiel basées sur `supporttype` pour `'WellboreChannel'`/`'WellboreMarker'` *pourraient* être vivantes (les stubs partiels portent le supporttype non dépouillé) — vérifier avant de supprimer ces deux-là précisément ; le reste peut être supprimé sans risque.
- **Commentaires obsolètes mentionnant `set_extract_channel`.** [rep_in_scene.py:132](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L132) (la docstring de `_is_wellbore_frame` dit encore « selected via the channel's data-array eye (`set_extract_channel`) ») et [active_array.py:350](../../fespp_on_trame/app/core/engine/active_array.py#L350) (« The per-view extractor Show below (set_extract_channel)… ») référencent la méthode supprimée. Mettre à jour vers `set_channel_visible`.
- **`_restore_channel` de Distribution sans effet.** Comme les channels ne reciblent plus, `_original_source_and_name` retourne une restauration `noop` pour les channels ([stats_dispatch.py:509](../../fespp_on_trame/app/core/engine/stats_dispatch.py#L509), [:523](../../fespp_on_trame/app/core/engine/stats_dispatch.py#L523)) et `distribution_dispatch.py` fait toujours circuler `_restore_channel` ([:406](../../fespp_on_trame/app/core/engine/distribution_dispatch.py#L406), [:456](../../fespp_on_trame/app/core/engine/distribution_dispatch.py#L456), [:538](../../fespp_on_trame/app/core/engine/distribution_dispatch.py#L538)) — désormais toujours un lambda sans effet. Le commentaire « restore the channel extractor's ExtractPath » à [stats_dispatch.py:594](../../fespp_on_trame/app/core/engine/stats_dispatch.py#L594) est obsolète. La tuyauterie peut être retirée une fois confirmé qu'aucun appelant ne dépend de l'arité du tuple.
- **Ambiguïté `SeismicWellboreFrame`.** `SimplifyXmlTag` retire `Representation` mais **pas** `Wellbore` (le tag commence par `Seismic`), donc le kind est `SeismicWellboreFrame` — il reste sur le chemin auto-show normal, **pas** `_channelless_frame`. Il est listé dans `_representation_type_in` et le dispatch d'onglet, mais on ne sait pas si un seismic wellbore frame devrait se comporter comme un `Frame` (conteneur de channels, primaire masqué) ou comme une simple rep géométrique. Aucune gestion de channel/marker n'existe pour lui. Décider et documenter ; actuellement il ferait apparaître automatiquement sa première partition comme n'importe quelle rep.
- **COE de `Completion` / `Perfo` non vérifié.** Tous deux sont dans `_representation_type_in` et traités comme des reps géométriques SolidColor, mais aucun test explicite ne vérifie que leur état COE est effacé (ils n'ont aucun enfant propriété dans les cas observés). `_publish_active_color_state` efface le COE pour tout nœud actif non-propriété, donc il *devrait* se replier sur Solid — mais ce chemin est **non testé** pour ces deux kinds ; confirmer qu'une activation de Completion/Perfo ne laisse pas un `active_color_array_name` périmé.
- **Dérive de la docstring `_is_wellbore_frame`.** [rep_in_scene.py:126-137](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L126) décrit encore « only one channel renders at a time, selected via … `set_extract_channel` » — exacte sur l'exclusivité, fausse sur le mécanisme. Reformuler vers le modèle de l'extracteur persistant par-channel.

---

J'ai maintenant une image complète et exacte du code actuel. Rédaction des deux sections assignées.

## La colonne vertébrale complète du cycle de vie (chaque type la suit ; les différences par-type en sont des écarts)

Voici le chemin canonique de bout en bout que parcourt un objet RESQML, de la sélection EPC jusqu'au teardown. Chaque kind (IjkGrid, surface, polyline, wellbore Frame/MarkerFrame, …) exécute les *mêmes* étapes numérotées ; le comportement spécifique au type est toujours un **écart à une étape**, jamais un pipeline parallèle. Placer une modification à l'étape la plus basse qui possède la préoccupation.

| # | Étape | Fonction(s) | Variable(s) d'état clé | Notes |
|---|-------|-------------|------------------|-------|
| 1 | **Load** | [`data_load.run`](../../fespp_on_trame/app/core/engine/data_load.py#L40) → `active_source.SetPropertyWithName('Selectors', …)` + un `UpdatePipeline` ; `source_registry.sync(...)` | `fespp_data_selectors` (entrée) ; `_selector_rep_cache`, `solid_color_by_rep`, `solid_color_next_idx` | Pousse les sélecteurs vers l'EPCCollector une fois, masque la rep multiblock parente, réserve une couleur de pastille par nouvelle rep *avant* la sync du registry pour que les sources soient teintées immédiatement. |
| 1b | **Load — suivi du bucket de visibilité** | [`_update_visibility_tracking`](../../fespp_on_trame/app/core/engine/data_load.py#L283) | `ui_loaded_rep_paths`, `ui_hidden_rep_paths`, `ui_hidden_rep_paths_by_view` | Les nouvelles reps restent visibles dans le **panneau actif**, sont ajoutées au bucket masqué de chaque panneau **non actif**. C'est la garde que lit tout contrôle ultérieur « dois-je Show ici ? ». |
| 1c | **Load — suivi tableau-de-données / marker / tableau-actif** | [`_update_data_array_tracking`](../../fespp_on_trame/app/core/engine/data_load.py#L342), [`_update_marker_tracking`](../../fespp_on_trame/app/core/engine/data_load.py#L375), [`_update_active_array_maps`](../../fespp_on_trame/app/core/engine/data_load.py#L418) | `ui_loaded_array_paths`, `ui_loaded_marker_paths`, `ui_active_array_by_rep` (+`_by_view`), `ui_active_realization_by_array_by_view` | « Le dernier tableau ajouté à une rep devient automatiquement son œil actif » — mais **uniquement dans le panneau actif**. L'auto-activation MR sème aussi le bucket de réalisation *avant* l'écriture du tableau-actif (l'ordre des handlers est porteur). |
| 2 | **Construction de l'arbre** | [`Tree.set_tree`](../../fespp_on_trame/app/core/tree.py#L165) / [`add_subtreeview_data`](../../fespp_on_trame/app/core/tree.py#L36) ; [`find_representation_node`](../../fespp_on_trame/app/core/tree.py#L395), [`find_type`](../../fespp_on_trame/app/core/tree.py#L372), [`is_grouping`](../../fespp_on_trame/app/core/tree.py#L103) | `ui_subtree_reservoir/well/surface` | Le `kind` pilote tout en aval. `_representation_type_in` (incl. `Frame`, `MarkerFrame`) décide vers quel ancêtre l'œil d'une feuille remonte (UP). `is_grouping` fait de Frame/MarkerFrame *des dossiers pour l'arbre mais des reps pour la source*. Chaque nœud publie aussi `rep_path` pour que le côté Vue résolve « ce tableau est-il actif pour ma rep » sans aller-retour Python. |
| 3 | **Sélection** | `Selector.select_node_*` (écrit `fespp_data_selectors`, déclenchant l'étape 1) | `ui_select_node_reservoir/well/surface`, `fespp_data_selectors` | État des cases. Cocher un regroupement sélectionne en masse les descendants via `find_all_selectable_descendant_ids` (partiels exclus). |
| 4 | **Activation** | [`Activator._handle_reservoir_change`](../../fespp_on_trame/app/core/activator.py#L240) / `_handle_well_change` / `_handle_surface_change` ; gardé par [`_is_node_active_able`](../../fespp_on_trame/app/core/activator.py#L194) ; `refresh_active()` se réexécute après load | `ui_active_node_reservoir/well/surface`, `active_representation_path`, `active_representation_has_properties`, `ui_active_node_reservoir_type[_rep]`, `active_property_kind`, `active_color_array_name/path` | **Nœud** actif ≠ **œil** actif. Une feuille propriété ne s'active que quand son propre id est coché ; les reps/regroupements s'activent via un descendant coché. L'onglet Reservoir fait le ColorBy inline ([`_apply_color_for_active_property`](../../fespp_on_trame/app/core/activator.py#L451)) ; well/surface ne font que *publier* l'état COE ([`_publish_active_color_state`](../../fespp_on_trame/app/core/activator.py#L742)) et laissent l'œil posséder le ColorBy. |
| 5 | **Création de source par-vue** | [`SceneRegistry.sync_loaded_reps`](../../fespp_on_trame/app/core/sources/scene_registry.py#L133) → [`_eager_setup_rep_in_scene`](../../fespp_on_trame/app/core/sources/scene_registry.py#L169) → [`RepInScene.source()`](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L169) → [`_ensure_extractor`](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L346) / [`_ensure_per_view_ijk`](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L188) | (aucune variable d'état — le graphe de proxy lui-même) | Un `RepInScene` par (rep, vue), créant paresseusement son `EnergisticsExtractor` par-vue (non-IJK) ou son `IjkGrid` par-vue (IJK). Le setup anticipé réplique aussi le ColorBy du panneau actif sur les vues splittées et honore le bucket masqué via [`hide_in_scene_view`](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L779). |
| 6 | **Rendu / visibilité** | [`visibility.toggle_rep_visibility`](../../fespp_on_trame/app/core/engine/visibility.py#L140) ; [`sources_for_rep_path`](../../fespp_on_trame/app/core/engine/source_resolver.py#L220) ; par-vue [`_refresh_parent_rep_visibility`](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L1020) | `ui_hidden_rep_paths_by_view` (garde), `ui_hidden_rep_paths` (miroir) | Pastille d'œil à 3 états (masqué / SolidColor / tableau). La **garde hidden-in-scene** ([`_hidden_in_scene`](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L758)) est vérifiée à chaque site de Show pour qu'une première sélection n'apparaisse que dans la vue active tout en se construisant partout. |
| 7 | **Couleur** | [`source_resolver.apply_color_array`](../../fespp_on_trame/app/core/engine/source_resolver.py#L757) → [`displays_for_rep_path`](../../fespp_on_trame/app/core/engine/source_resolver.py#L420) → [`color_sources_for_rep_path`](../../fespp_on_trame/app/core/engine/source_resolver.py#L317) → `ColorBy` ; [`resolve_array_for_path`](../../fespp_on_trame/app/core/engine/source_resolver.py#L433) ; LUT par-vue via [`swap_to_scene_tfs`](../../fespp_on_trame/app/core/engine/source_resolver.py#L545) | `ui_active_array_by_rep[_by_view]`, `ui_active_realization_by_array_by_view` | Piloté par [`active_array.on_active_array_change`](../../fespp_on_trame/app/core/engine/active_array.py#L44) et [`toggle_dataarray_color`](../../fespp_on_trame/app/core/engine/active_array.py#L231). La LUT est par-(scène, tableau) (`name__view_id`) pour qu'une édition COE ne déborde pas entre vues. |
| 8 | **COE (éditeur de couleur)** | `controller.update_color_editor(...)` ; [`resolve_target_scoped_lut`](../../fespp_on_trame/app/core/engine/source_resolver.py#L584), [`real_base_name`](../../fespp_on_trame/app/core/engine/source_resolver.py#L189) | `active_color_array_name`, `active_property_kind`, `active_color_array_path`, `coe_panels` | Le COE indexe sa LUT sur le nom VTK qui **existe réellement** (sanitizé pour les grilles/surfaces, titre brut pour les channels — voir la note de sanitization des channels ci-dessous). Le clic sur l'œil ([`toggle_dataarray_color`](../../fespp_on_trame/app/core/engine/active_array.py#L400)) republie ces valeurs pour que le COE suive le channel réellement affiché. |
| 9 | **Stats / distribution** | `channel_source_for` / `visible_channel_extractor` / `slice_output` / `clip_output` alimentent la liste de sources rendues | (état du panneau) | Lit le même ensemble de sources par-vue que le chemin de rendu utilise (extracteur par-vue, extracteur de channel visible, feuille de threshold visible la plus profonde). |
| 10 | **Split / réplication** | [`SceneRegistry.replicate_view`](../../fespp_on_trame/app/core/sources/scene_registry.py#L390) ; par-préoccupation [`snapshot_*` / `apply_*`](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L1518) ; [`apply_visible_markers`](../../fespp_on_trame/app/core/sources/scene_registry.py#L265) ; [`ViewScene.replicate_tfs_from`](../../fespp_on_trame/app/core/sources/view_scene.py#L312) | `ui_active_array_by_rep_by_view`, `ui_visible_marker_paths_by_view`, `fespp_active_panel_id` | Le bootstrap (extracteur par-vue + ColorBy) vient de `_eager_setup_rep_in_scene` ; `replicate_view` ajoute la copie par-préoccupation (threshold/slice/clip/ijk_slicers) dans l'ordre des dépendances (ijk_slicers en premier). |
| 11 | **Teardown** | [`RepInScene.delete`](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L849) ; [`ViewScene.remove_rep`/`destroy`](../../fespp_on_trame/app/core/sources/view_scene.py#L141) ; **teardown synchrone de désélection** dans [`data_load.run`](../../fespp_on_trame/app/core/engine/data_load.py#L230) | `ui_loaded_rep_paths` (pilote le `sync_loaded_reps` différé) | L'ordre compte : chaîne → slice/clip → IjkGrid par-vue → `_extractor` primaire → extracteurs par-enfant. Les reps désélectionnées sont détruites **synchronement à l'intérieur de `run()` avant tout rendu** — rendre une source périmée contre un clone dont la partition a disparu segfaulte nativement. |

**Écarts par-type à la colonne vertébrale (chacun est une branche à une étape, par `kind`) :**

- **IjkGrid** — les étapes 5/6/7 délèguent à un [`IjkGrid`](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L188) par-vue (slicers + volume + chaîne de threshold) au lieu d'un seul `_extractor` ; `source()` retourne l'extracteur rep_data ; la visibilité défère à `ijk.show(view=…)` (il possède le mode slice-vs-range). L'IjkGrid partagé legacy est masqué par-vue pour éviter le Z-fighting.
- **Wellbore Frame (logs)** / **MarkerFrame** — l'étape 6 garde le `_extractor` primaire masqué en permanence ([`_channelless_frame`](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L746)) ; les enfants sont rendus via des extracteurs par-enfant (voir la section suivante). L'étape 1c les route via `ui_loaded_array_paths` (channels) vs `ui_loaded_marker_paths` (markers).
- **Surfaces / polylines non-IJK** — le chemin « par défaut » sans écart : un `_extractor`, une chaîne de threshold par-vue optionnelle, slice/clip.

---

## L'architecture de scène par-vue (clone, RepInScene, extracteurs enfants, chaîne)

Chaque panneau de rendu possède une [`ViewScene`](../../fespp_on_trame/app/core/sources/view_scene.py#L24) ; le [`SceneRegistry`](../../fespp_on_trame/app/core/sources/scene_registry.py#L40) mappe `view_id → ViewScene` et est la façade que l'engine appelle. Une scène possède un **clone**, un dict de `RepInScene`, et des proxies LUT/PWF par-(scène, tableau).

### Clone — l'ancre structurelle par-vue

- [`ViewScene._create_clone`](../../fespp_on_trame/app/core/sources/view_scene.py#L69) instancie un proxy `vtkEPCCollectorClone` (nom d'enreg. `EPCCollector_View{view_id}`) chaîné sur la source globale `EPCCollector`. C'est un passthrough ShallowCopy — **zéro duplication de données**, propagation 100% native PV (toute mise à jour du collector invalide le clone → invalide les filtres en aval).
- Le clone n'est **jamais affiché** — c'est un nœud structurel du graphe SM, forcé à `Visibility=0` dans chaque vue pour que l'affichage paresseux par défaut de PV ne peigne pas un Outline fantôme.
- **Repli de la Phase 2 :** quand la DLL du plugin ne dispose pas de `EPCCollectorClone`, `clone` se replie sur `collector.get_source()` (la source partagée). Chaque méthode de création de filtre par-vue ([`_ensure_extractor`](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L366), `_ensure_per_view_ijk`, `_create_channel_extractor`, `_create_marker_extractor`) vérifie explicitement `clone is collector.get_source()` et **bascule en legacy** dans ce cas — chaîner des filtres par-vue sur le collector partagé entrerait en collision sur `id()` entre vues.

### RepInScene — le propriétaire par-(rep, vue)

[`RepInScene`](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L33) est une rep telle que vue depuis une vue. Il possède chaque proxy qui doit diverger entre vues. La détection de type est mise en cache (`_is_ijk_cache`, `_is_frame_cache`, `_is_marker_frame_cache`) car le hot path de dispatch branche dessus à chaque appel.

| Champ | Ce qu'il contient | Quand créé |
|-------|---------------|--------------|
| `_extractor` | `EnergisticsExtractor` primaire par-vue (ExtractPath = rep_path) | Paresseux, non-IJK uniquement, au premier `source()`/slice/clip/ColorBy |
| `_per_view_ijk` | Pipeline `IjkGrid` par-vue (rep_data + slicers + volume + chaîne) | Paresseux, IJK uniquement |
| `_channel_extractors: dict` | Un extracteur par **channel** wellbore (log), indexé par chemin de channel | Paresseux, au premier show / lecture COE-stats |
| `_marker_extractors: dict` | Un extracteur par **marker** visible, indexé par chemin de marker | Paresseux, au premier show |
| `_chain: list[ChainEntry]` | Chaîne de threshold par-vue (non-IJK ; IJK utilise `_per_view_ijk._chain`) | À `add_threshold` |
| `_slice_plane` / `_clip_plane` | Filtres Slice / Clip par-(rep, vue) chaînés sur la source par-vue | Au premier `slice_set` / `clip_set` |

### `_extractor` primaire vs dicts d'extracteurs par-enfant

Le `_extractor` primaire représente la *rep entière*. Mais un **Frame** (conteneur de logs wellbore) et un **MarkerFrame** sont des conteneurs dont la première partition enfant apparaîtrait automatiquement si le primaire était affiché (ExtractPath = chemin du frame → le C++ résout vers le premier enfant du frame). Donc les deux kinds gardent le primaire **masqué en permanence** via [`_channelless_frame`](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L746) (retourne `_is_marker_frame() or _is_wellbore_frame()`), et rendent leurs enfants à travers des extracteurs par-enfant dédiés, chacun avec son **propre** `ExtractPath` pointé sur la feuille enfant.

**`_channel_extractors` (EXCLUSIF) vs `_marker_extractors` (MULTI) — la différence précise :**

| | `_channel_extractors` (logs) | `_marker_extractors` (markers) |
|---|---|---|
| Kind de rep | `Frame` (`_is_wellbore_frame`) | `MarkerFrame` (`_is_marker_frame`) |
| Cardinalité d'affichage | **EXCLUSIF — un à la fois** | **MULTI — plusieurs à la fois** |
| Point d'entrée Show | [`set_channel_visible`](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L468) | [`set_marker_visible`](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L601) |
| Effet de bord du Show | **Masque tous les AUTRES channels du frame** avant d'afficher celui choisi | Aucun effet de bord — bascule indépendante |
| Constructeur | [`_create_channel_extractor`](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L547) | [`_create_marker_extractor`](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L636) |
| Persistance | La source **persiste** une fois créée (masquée quand une autre est affichée) → LUT scopée/COE/stats la lisent directement, sans recible | Persiste ; chacune recolorable indépendamment (`solid_color_by_marker`) |
| Accesseur « actuellement affiché » | [`visible_channel_extractor`](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L526) (l'unique visible) | [`visible_marker_displays`](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L721) (la liste des visibles) |
| Matérialiser-tout-en-restant-masqué | [`channel_extractor_for(create=True)`](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L511) — permet au COE/stats de lire le channel actif même quand un *autre* est affiché | s.o. (les markers affichés sont ceux lus) |
| État de couleur par-entrée | `solid_color_by_rep` du frame | `solid_color_by_marker` par-marker, avec repli sur le frame |

**Pourquoi les deux utilisent des extracteurs par-enfant :** un frame/markerframe n'a **aucune géométrie significative propre** — seuls ses enfants en ont, et chaque enfant est une partition distincte dans la sortie composite du collector. Donner à chaque enfant son propre `EnergisticsExtractor` (au lieu de recibler l'ExtractPath d'un extracteur de frame partagé) signifie que la source de chaque enfant est **persistante et adressable indépendamment** : sa LUT scopée, son graphe COE et ses stats la lisent tous directement **sans danse de recible**. C'est le grand refactor récent — l'ancien « extracteur de frame partagé unique dont l'ExtractPath est RECIBLÉ » (`set_extract_channel`, `read_only_channel_retarget`) est **supprimé** ; la bascule de channel est désormais un simple masquer/afficher.

**Comment fonctionne le show exclusif :** `set_channel_visible(channel_path, True)` appelle `channel_extractor_for(create=True)`, puis **itère sur `_channel_extractors` et `Hide()` chaque voisin** dans la `pv_view` de cette scène avant de `Show()` celui choisi. Les markers sautent entièrement cette boucle. Lors d'une simple *sélection* de channel (sans clic d'œil), [`active_array.on_active_array_change`](../../fespp_on_trame/app/core/engine/active_array.py#L84) → `_show_channel_active_view` affiche le channel *avant* de colorer, car `apply_color_array` relit les tableaux propres du channel désormais visible via `resolve_array_for_path`.

> **Nommage des channels (sanitization C++) :** `ResqmlWellboreChannelToVtkPolyData.cxx` sanitize désormais le nom du tableau de channel via `MakeValidNodeName`, donc les channels portent un nom sanitizé comme les grilles. [`real_base_name`](../../fespp_on_trame/app/core/engine/source_resolver.py#L189) sonde toujours la source par-vue pour choisir le nom qui *existe réellement* (brut vs sanitizé) afin que le COE indexe la même LUT que le chemin de rendu a indexée.

### La chaîne de threshold (non-IJK)

La chaîne par-vue ([`_add_threshold_local`](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L1245), [`_refresh_chain_visibility`](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L1399)) reflète la conception `ChainEntry` de `ExtractBlockRepresentation` mais : l'amont est `self._extractor` (par-vue), les suffixes de nom d'enreg. `_v{view_id}` pour que les chaînes de différentes vues n'entrent pas en collision dans le registry de proxy de PV, et le Show/Hide cible `self.scene.pv_view`. Règle de visibilité : une entrée s'affiche si et seulement si `entry.visible AND aucun descendant visible` ; le **primaire** se masque quand une extrémité de chaîne est affichée OU que slice/clip est actif OU que l'utilisateur a masqué la rep OU que `_channelless_frame()` le force. Les reps IJK retournent tôt — elles utilisent `_per_view_ijk._chain` à la place.

### Slice / clip

[`SlicePlane`](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L916) / [`ClipPlane`](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L953) par-(rep, vue), chacun conscient de son `view_id`/`pv_view` propriétaire, chaîné sur `self.source()` (l'extracteur par-vue ou le rep_data de l'IjkGrid par-vue). Activer l'un ou l'autre **masque le primaire de la rep dans la seule pv_view de cette scène** ([`_refresh_parent_rep_visibility`](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L1020)) pour que ce soit la coupe/le morceau clippé qui soit visible — les autres scènes gardent la rep visible. Pour IJK, cette méthode délègue à `ijk.show(view=…)` (l'IjkGrid par-vue possède sa propre politique de show/hide) ; pour un `_channelless_frame`, elle force le masquage du primaire ; sinon elle Show/Hide selon `slice_on | clip_on | chain_visible`. `clip_output()` / `slice_output()` exposent les proxies de filtre pour que l'éventail ColorBy et le dispatch de stats incluent la bonne sortie rendue.

---

J'ai maintenant une compréhension exhaustive du code. Rédaction des sections assignées.

## Regroupement (Collection / Wellbore / Feature / Interpretation / Partial)

**Rôle dans l'arbre.** Des dossiers purement organisationnels — aucune source VTK, aucun œil, aucune couleur propre. Ils n'existent que pour sélectionner en masse leur sous-arbre et rendre une case à cocher tri-état. Le C++ les estampille `kind ∈ {Collection, Wellbore, Feature, Interpretation, Partial}` (`Feature`/`Interpretation` n'apparaissent que dans les modes de hiérarchie non-Flat). L'ensemble canonique de regroupement vit à **trois** endroits qui doivent rester synchronisés :

| Emplacement | Constante | Utilisé pour |
|---|---|---|
| [tree.py#L103](../../fespp_on_trame/app/core/tree.py#L103) `is_grouping` | `Collection, Wellbore, Feature, Interpretation, Partial, Frame, MarkerFrame` | publie `is_grouping` + `descendant_ids` vers l'arbre Vue |
| [tree_views.py#L19](../../fespp_on_trame/app/ui/drawer/tree_views.py#L19) `_GROUPING_KINDS` | les mêmes 7 | cascade de sélection en masse UI + case à cocher tri-état |
| [activator.py#L41](../../fespp_on_trame/app/core/activator.py#L41) `_GROUPING_KINDS` | les mêmes 7 | `_is_node_active_able` (un regroupement peut s'activer via un descendant coché) |

> **Piège (le piège des 3 listes) :** `Frame`/`MarkerFrame` sont dans les trois listes de regroupement **mais sont aussi des reps** (dans `_representation_type_in`). Ils sont « dossier-pour-l'arbre, représentation-pour-la-source » — voir la section FrameRep. Un regroupement simple (`Collection`/`Wellbore`/`Feature`/`Interpretation`/`Partial`) est un regroupement dans **tous** les sens et n'est **jamais** dans `_representation_type_in`.

**Type d'œil :** aucun (M/A/R tous absents). Le regroupement ne porte qu'une case *select* tri-état ([`_select_checkbox_icon`](../../fespp_on_trame/app/ui/drawer/tree_views.py#L223)) : cochée quand chaque `descendant_ids` ∩ `ui_select_node_*` est complet, `mdi-minus-box` quand partiel, vide sinon.

**Cascade de sélection / bucket.** Cocher un regroupement ajoute en masse son sous-arbre ; la cascade est symétrique à la suppression. Deux couches :
- [`tree_toggle_select`](../../fespp_on_trame/app/ui/drawer/tree_views.py#L640) : le clic sur un regroupement cycle « certains→tous » puis « tous→vide » sur `find_all_selectable_descendant_ids`.
- [`_expand_selection_with_deps`](../../fespp_on_trame/app/ui/drawer/tree_views.py#L36) : ajouter un regroupement ajoute tous les descendants sélectionnables ; **retirer** un regroupement (ou n'importe quelle rep) supprime chaque descendant.

**`Wellbore` est spécial parmi les regroupements.** C'est le dossier WellboreFeature (ex. `"55/33-3"`) — PAS une rep (commentaire [tree.py#L28-L33](../../fespp_on_trame/app/core/tree.py#L28)). Ses enfants (Trajectory / Frame / MarkerFrame / Completion) sont les reps. Un `WellboreChannel`/`WellboreMarker` coché coche automatiquement la `WellboreTrajectory` **sœur** (la géométrie d'ancrage), via [`_WELLBORE_LEAF_KINDS_NEEDING_TRAJECTORY`](../../fespp_on_trame/app/ui/drawer/tree_views.py#L33).

**`Partial` est spécial : référence seule.** Un nœud partiel (`kind ∈ {partial, Partial}`) n'a que Titre + UUID, aucune donnée. Il est :
- marqué dans le titre `!!!PARTIAL!!!` et `disabled=True` ([tree.py#L57-L59](../../fespp_on_trame/app/core/tree.py#L57)) ; aucune case ne s'affiche.
- **exclu** de l'univers sélectionnable de chaque regroupement via [`find_all_selectable_descendant_ids`](../../fespp_on_trame/app/core/tree.py#L324) (vs `find_all_descendant_ids`), pour que le tri-état d'un regroupement puisse quand même atteindre « tout sélectionné » et qu'une sélection en masse ne ramasse jamais un stub non chargeable.

> **Piège (verrouillage de `disabled`) :** le flag partiel par-nœud doit être local — `set_tree` réinitialise `disabled=False` à chaque itération de premier niveau ([tree.py#L188](../../fespp_on_trame/app/core/tree.py#L188)) et `add_subtreeview_data` utilise un `node_is_partial` séparé pour NE PAS muter le `disabled` à portée de fonction transmis aux enfants ([tree.py#L52-L59](../../fespp_on_trame/app/core/tree.py#L52)) ; sinon un stub de rep partielle désactiverait ses vrais descendants.

**Dispatch d'onglet.** Les regroupements de premier niveau n'ont pas de kind propre sur lequel router. `set_tree` descend dans `Feature`/`Interpretation` via [`_resolve_dispatch_kind`](../../fespp_on_trame/app/core/tree.py#L144) pour trouver le premier kind de descendant réel, et route un stub `partial` de premier niveau par son attribut `supporttype` ([tree.py#L209-L216](../../fespp_on_trame/app/core/tree.py#L209)).

**Source / pipeline / visibilité / couleur / COE / threshold :** **aucun** — les regroupements ne possèdent rien. **Où modifier :** les changements de sélection en masse ou de tri-état vont dans `tree_views.py` ; les changements de « ce qui compte comme un dossier » doivent toucher ensemble les trois listes `_GROUPING_KINDS`/`is_grouping`. Ne jamais ajouter un regroupement à `_representation_type_in` sauf s'il gagne aussi une source par-vue (le précédent du Frame).

---

## GridRep — IjkGrid (le plus spécial) + UnstructuredGrid / Sub

Ces trois sont des reps de l'onglet reservoir (`kind ∈ {IjkGrid, UnstructuredGrid, Sub}`). Elles divergent fortement : **IjkGrid est la SEULE rep avec une classe de pipeline par-vue sur mesure** ([`IjkGrid`](../../fespp_on_trame/app/core/sources/ijkgrid.py)) ; UnstructuredGrid / Sub sont des reps non-IJK génériques qui passent par le chemin `EnergisticsExtractor` simple comme les surfaces.

### IjkGrid

| Préoccupation | Comportement | Fichier:ligne |
|---|---|---|
| Rôle dans l'arbre | Rep avec descendants propriété (feuilles Continuous/Discrete/Categorical/TS/MR). | — |
| Œil | **R** (œil rep) sur la grille + **A** (œil de tableau de données) sur chaque propriété. | [tree_views.py#L390](../../fespp_on_trame/app/ui/drawer/tree_views.py#L390) |
| Sélection | Une propriété n'est activable que cochée sur son propre id ; la rep s'active via un descendant coché. | [activator.py#L194](../../fespp_on_trame/app/core/activator.py#L194) |
| Source / pipeline | **DOUBLE** : un `IjkGrid` partagé legacy (possédé par `SourceRegistry`, pilote la sélection de propriété à travers l'engine) ET un `IjkGrid` par-`(rep,vue)` ([`_per_view_ijk`](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L81)) chaîné sur le clone de scène. Chaque grille possède : `_src_extract_init` (extracteur rep_data), des slicers `ExplicitStructuredGridCrop` par-axe (i/j/k), `_src_slicer_volume`, et une chaîne de threshold `_IjkChainEntry` dont les proxies sont indexés **par amont** (`pv_proxies[id(src)]`). | [ijkgrid.py#L66](../../fespp_on_trame/app/core/sources/ijkgrid.py#L66) |
| Visibilité | `IjkGrid.show()` fait autorité — le mode slice affiche les crops par-axe, le mode range affiche `slicervolume` (ou rep_data à pleine étendue, PV6 dégénère le crop), avec un repli rep_data quand chaque œil de slicer est éteint. | [ijkgrid.py#L527](../../fespp_on_trame/app/core/sources/ijkgrid.py#L527) |
| Couleur | Le ColorBy s'étale sur les slicers + le volume + les feuilles de chaîne (PAS `_src_extract_init`, exclu intentionnellement). | [source_resolver.py#L347](../../fespp_on_trame/app/core/engine/source_resolver.py#L347) |
| Mode COE | kind de propriété depuis la feuille activée ; LUT scopée par `(scène, tableau)`. | [activator.py#L300](../../fespp_on_trame/app/core/activator.py#L300) |
| Threshold | chaîne par-amont ; le flip-de-mode / l'ajout-de-slicer recâble via `_refresh_chain_pipeline`. | [ijkgrid.py#L1019](../../fespp_on_trame/app/core/sources/ijkgrid.py#L1019) |

**Le miroir legacy↔par-vue.** `_ensure_per_view_ijk` ([rep_in_scene.py#L188](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L188)) lit le `_property_path` de l'IjkGrid legacy, le convertit en id de nœud, construit l'`IjkGrid(view_id, clone, pv_view)` par-vue, puis **masque les slicers legacy dans la vue de cette scène** (`_hide_legacy_ijk_in_scene_view`). L'engine les maintient en phase via `SceneRegistry.refresh_per_view_ijk_for_rep` / `mirror_legacy_ijk_state`.

> **Pièges (spécifiques à IjkGrid, haute densité) :**
> - **Assembly vide → mauvais type de sortie.** Le clone doit être `UpdatePipeline()`-é AVANT la création de l'IjkGrid par-vue, sinon le `RequestDataObject` peek de l'extracteur retourne null, se replie sur `vtkPolyData`, et chaque `ExplicitStructuredGridCrop` rejette l'entrée ([rep_in_scene.py#L234-L253](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L234)).
> - **Z-fight au swap de propriété.** `refresh_per_view_ijk_property` doit re-masquer les slicers legacy ET re-masquer-dans-la-scène si le bucket dit masqué — le `set_node_id→show()` legacy réaffirme `Visibility=1` dans la vue active ([rep_in_scene.py#L307](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L307)).
> - **Ne jamais `Show(_src_extract_init)` depuis le rafraîchisseur générique.** `_refresh_parent_rep_visibility` délègue le cas IJK à `ijk.show(view=...)` ([rep_in_scene.py#L1075](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L1075)) ; un Show brut rastérise la grille entière non croppée avec une teinte SolidColor par défaut (le bug du « bloc rouge en Z-fighting avec les slicers » après un 2e sélecteur de propriété).
> - **Passe de données du slicer au chargement.** [data_load.py#L159-L194](../../fespp_on_trame/app/core/engine/data_load.py#L159) fait un `UpdatePipeline()` complet (pas seulement les infos) sur rep_data + chaque slicer, sinon la sortie de slicer en cache a le bon nombre de cellules mais **aucun tableau CellData** et l'activator rate la propriété.
> - **`update_block_visibility`** retire le chemin de propriété IJK des `BlockSelectors` du multiblock parent pour qu'il ne soit rendu qu'à travers les slicers de la grille, cumulatif-safe entre grilles ([ijkgrid.py#L1151](../../fespp_on_trame/app/core/sources/ijkgrid.py#L1151)).
> - **Les snapshots lisent par-vue UNIQUEMENT**, jamais legacy — une copie de l'état slicer/threshold ne doit pas capturer l'état partagé ([rep_in_scene.py#L1662](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L1662)).

### UnstructuredGrid / Sub

Reps non-IJK génériques : un seul `EnergisticsExtractor` par-`(rep,vue)` (`_extractor`) + une `_chain` de threshold par-vue de `ChainEntry`, exactement comme les surfaces. Résolution de source : `source() → _ensure_extractor()` ([rep_in_scene.py#L346](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L346)) ; couleur/threshold/visibilité passent par les branches non-IJK de `source_resolver`, `_refresh_parent_rep_visibility`, `_refresh_chain_visibility`. `Sub` est un enfant de sous-représentation mais se comporte identiquement à la couche source.

**Où modifier :** la logique d'affichage propre à IJK (mode slice/range, œils de slicer, volume) appartient à `ijkgrid.py` — elle est partagée par les instances legacy et par-vue (le toggle `view_id/clone/pv_view` du constructeur est tout-ou-rien). Une modification touchant « toutes les grilles reservoir » mais PAS les surfaces va au niveau de la branche `_is_ijk_grid()` dans `rep_in_scene.py` / `source_resolver.py`. Une modification pour « toutes les reps non-IJK » va dans le chemin extracteur/chaîne générique — et affectera automatiquement aussi les surfaces (voir la section suivante) ; en cadrer soigneusement la portée.

---

## SurfaceRep / WellboreGeom (Grid2d, PointSet, Polyline, PolylineSet, TriangulatedSet, Trajectory, Completion, Perfo)

Ce sont les **reps génériques non-IJK, non-frame**. Les kinds de l'onglet surface (`Grid2d, PointSet, Polyline, PolylineSet, TriangulatedSet`) et les kinds de géométrie well (`Trajectory, Completion, Perfo`) partagent un seul pipeline identique : un unique `EnergisticsExtractor` par-`(rep,vue)` chaîné sur le clone de scène + une `_chain` de threshold par-vue optionnelle. Ils ne diffèrent que par le routage d'onglet et par les objets compagnons que le Selector engendre.

| Préoccupation | Comportement | Fichier:ligne |
|---|---|---|
| Rôle dans l'arbre | Reps quasi-feuilles. `Trajectory` est l'ancre de géométrie wellbore (cochée automatiquement quand un channel/marker est coché). | [tree_views.py#L91](../../fespp_on_trame/app/ui/drawer/tree_views.py#L91) |
| Œil | **R** œil rep ; **A** œil de tableau sur tout descendant propriété (les surfaces peuvent porter des propriétés Continuous/Discrete ; Trajectory/Completion/Perfo en général non). | [tree_views.py#L456](../../fespp_on_trame/app/ui/drawer/tree_views.py#L456) |
| Sélection | `Trajectory` coché → compagnon `Wellhead` créé ; les surfaces ne font que pousser des chemins. | [selector.py#L84](../../fespp_on_trame/app/core/selector.py#L84) |
| Source | `source() → _ensure_extractor()` (`EnergisticsExtractor`, `ExtractPath = rep_path`). Auto-affiché à la création sauf si masqué-dans-la-scène. | [rep_in_scene.py#L346](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L346) |
| Visibilité | `_refresh_parent_rep_visibility` Show l'extracteur sauf si slice/clip/extrémité-de-chaîne/œil-masqué. | [rep_in_scene.py#L1091](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L1091) |
| Couleur | le `_extractor` par-vue + `all_chain_proxies` reçoivent l'éventail ColorBy + la LUT scopée par-vue. | [source_resolver.py#L384](../../fespp_on_trame/app/core/engine/source_resolver.py#L384) |
| Mode COE | publié par `_publish_active_color_state` (onglets well/surface) pour les feuilles propriété uniquement. | [activator.py#L742](../../fespp_on_trame/app/core/activator.py#L742) |
| Threshold | chaîne locale par-vue (`_add_threshold_local`), machinerie identique à UG. | [rep_in_scene.py#L1245](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L1245) |
| Slice / Clip | `SlicePlane` / `ClipPlane` par-`(rep,vue)`, activer l'un ou l'autre masque le primaire dans cette vue. | [rep_in_scene.py#L916](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L916) |

> **Pièges :**
> - **Z-fight avec l'EB legacy.** À la création de l'extracteur, le Show de l'`ExtractBlockRepresentation` legacy dans cette vue est masqué ([rep_in_scene.py#L443-L458](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L443)).
> - **Trajectory est l'ancre de dépendance.** Les channels/markers en ont besoin ; désélectionner une Trajectory supprime les feuilles dépendantes via la cascade de suppression.
> - **`Completion`/`Perfo` ne portent aucune propriété** — leur branche d'œil-de-tableau ne rend jamais ; seul l'œil rep. `Perfo` est nommé `"Perfo"+...` en C++ ([ResqmlDataRepository...cxx#L1176](../../../../fespp/work/src/Plugin/Energistics/Mapping/ResqmlDataRepositoryToVtkPartitionedDataSetCollection.cxx#L1176)).
> - **`Polyline` vs `PolylineSet`.** Les deux sont dans `_representation_type_in` ; la map d'icônes de l'arbre n'a que `PolylineSet`, donc `Polyline` tombe à travers la correspondance par sous-chaîne de `get_icon_for_type`.

**Où modifier :** tout ce qui touche « toutes les reps génériques » (création d'extracteur, chaîne de threshold, slice/clip) vit dans la **branche non-IJK, non-`_channelless_frame`** de `RepInScene` — partagée par les surfaces, la géométrie well, UG, **et** les primaires de frame (qui sont forcés masqués). Pour changer le comportement des surfaces sans toucher la géométrie well, il faut brancher sur `kind` (il n'y a pas d'objet « famille surface » partagé — elles sont unifiées au niveau `RepInScene`). Seul le routage d'onglet est dans les listes `treeview_type` de `tree.py`.

---

## FrameRep — Frame (logs) et MarkerFrame (markers) : la double nature

Un frame est **« dossier-pour-l'arbre, représentation-pour-la-source »** : il apparaît À LA FOIS dans `is_grouping`/`_GROUPING_KINDS` ([tree.py#L103](../../fespp_on_trame/app/core/tree.py#L103), [tree_views.py#L19](../../fespp_on_trame/app/ui/drawer/tree_views.py#L19)) ET dans `_representation_type_in` ([tree.py#L34](../../fespp_on_trame/app/core/tree.py#L34)). Conséquences :
- Dans l'**arbre** c'est un dossier : case à cocher tri-état, aucun œil rep propre (`_eye_slot` exclut explicitement `Frame`/`MarkerFrame` de la garde d'œil-rep à [tree_views.py#L390-L393](../../fespp_on_trame/app/ui/drawer/tree_views.py#L390)). Le cocher sélectionne en masse chaque log/marker enfant.
- Pour la **source**, `find_representation_node` sur une feuille channel/marker remonte (UP) vers le frame — le nœud frame est l'ancre de rendu qui **héberge les extracteurs par-`(enfant,vue)`**. Le nœud frame lui-même n'a **aucun index de dataset** ; ses enfants en ont.
- Le `_extractor` primaire propre au frame n'est **JAMAIS rendu** (`_channelless_frame()` retourne True pour les deux kinds, [rep_in_scene.py#L746](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L746)). Si les rafraîchisseurs génériques le Show, le côté C++ résout `ExtractPath = frame_path` vers la **première** partition enfant du frame, refaisant apparaître un log/marker que l'utilisateur n'a jamais choisi. D'où le fait que chaque chemin de visibilité générique force le masquage du primaire pour les frames.

Les deux kinds se séparent sur la **cardinalité** : **channels de Frame = exclusif (un log à la fois)** ; **markers de MarkerFrame = multi (plusieurs à la fois)**. Le C++ estampille les kinds d'exécution `Frame`, `MarkerFrame`, et les feuilles `WellboreChannel`/`Marker` (enfants) ; `_is_wellbore_frame` teste `== 'Frame'` et `_is_marker_frame` teste `== 'MarkerFrame'` exactement ([rep_in_scene.py#L126](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L126), [#L148](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L148)).

### La NOUVELLE architecture par-channel (Frame, logs)

**Chaque channel possède son PROPRE `EnergisticsExtractor`**, indexé par chemin de channel dans `_channel_extractors: dict` ([rep_in_scene.py#L61](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L61)) — structurellement identique aux markers (`_marker_extractors`) mais **exclusif** au lieu de multi. L'ANCIENNE conception de l'extracteur-de-frame-partagé-unique-dont-l'ExtractPath-est-reciblé (`set_extract_channel`, `_extractor_channel_path`, `read_only_channel_retarget`) est **SUPPRIMÉE**. La bascule est désormais un simple masquer/afficher ; la source de chaque channel PERSISTE pour que sa LUT scopée/COE/stats la lisent directement **sans recible**.

| Méthode | Rôle | Fichier:ligne |
|---|---|---|
| `set_channel_visible(channel_path, visible)` | Show EXCLUSIF : matérialise l'extracteur du channel, puis **Masque tous les AUTRES channels** de ce frame avant le Show. Visibilité seule. | [rep_in_scene.py#L468](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L468) |
| `channel_extractor_for(channel_path, create=True)` | Retourne (et MATÉRIALISE, masqué, si absent) l'extracteur du channel — pour que le COE/stats d'un channel ACTIF-mais-non-affiché le lisent quand même. | [rep_in_scene.py#L511](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L511) |
| `visible_channel_extractor()` | L'unique extracteur actuellement à `Visibility=1` — ancre de rendu/couleur/vue-stats. | [rep_in_scene.py#L526](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L526) |
| `_create_channel_extractor(channel_path)` | Construit le proxy (`ExtractPath = feuille channel`, tube + tableau de points), masqué dans les autres vues, teinte solide du frame. Miroir de `_create_marker_extractor`. | [rep_in_scene.py#L547](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L547) |

**Chemin de sélection (sans clic d'œil) :** `data_load` auto-active frame→dernier channel ; `on_active_array_change` appelle `_show_channel_active_view` pour AFFICHER le channel exclusivement AVANT de colorer ([active_array.py#L27](../../fespp_on_trame/app/core/engine/active_array.py#L27), [#L84](../../fespp_on_trame/app/core/engine/active_array.py#L84)). **Clic d'œil :** `toggle_dataarray_color` détecte `is_channel` (`rep_kind == 'Frame' and r_id != node_id`), appelle `set_channel_visible(...)` d'abord, puis `apply_color_array`, puis publie le channel affiché comme tableau actif du COE pour que l'éditeur suive le log affiché ([active_array.py#L380-L420](../../fespp_on_trame/app/core/engine/active_array.py#L380)).

**Pourquoi le COE/stats d'un channel actif-mais-masqué lit quand même correctement :** `resolve_array_for_path` et `channel_source_for` appellent `channel_extractor_for(array_path, create=True)` — la source du channel existe toujours (juste masquée quand un voisin est affiché), donc les requêtes `GetArrayInformation`/range frappent un vrai proxy portant le tableau de ce channel ([source_resolver.py#L468-L475](../../fespp_on_trame/app/core/engine/source_resolver.py#L468), [#L118](../../fespp_on_trame/app/core/engine/source_resolver.py#L118)).

**Bascule OFF** (`new_value is None`) ne fait que Masquer l'extracteur de ce channel et remettre l'état COE à Solid ([active_array.py#L416-L420](../../fespp_on_trame/app/core/engine/active_array.py#L416)).

### Markers (MarkerFrame) — le contraste multi

`set_marker_visible` ([rep_in_scene.py#L601](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L601)) est une machinerie identique **moins la boucle d'exclusivité** — il Show le marker sans masquer les voisins. Chaque marker visible garde sa propre teinte `solid_color_by_marker` ([rep_in_scene.py#L687](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L687)) ; `visible_marker_displays()` alimente l'éventail SolidColor ([rep_in_scene.py#L721](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L721)). Les markers ne portent **aucun tableau de couleur** — ils sont visibilité-seule, suivis dans `ui_visible_marker_paths_by_view` et basculés par `visibility.toggle_marker_visibility` ([visibility.py#L75](../../fespp_on_trame/app/core/engine/visibility.py#L75)), avec leur propre liste d'œil `ui_loaded_marker_paths` ([data_load.py#L375](../../fespp_on_trame/app/core/engine/data_load.py#L375)).

**MapperSet C++ & sanitization.** Le frame est un `MapperSet` (une partition par enfant) ; le nœud frame ne porte aucun index de dataset, les enfants si. Le nom du tableau POINT du channel **passe désormais par `MakeValidNodeName`** (sanitizé, comme grilles/UG) tandis que le `title` d'assembly reste brut ([ResqmlWellboreChannelToVtkPolyData.cxx#L100-L153](../../../../fespp/work/src/Plugin/Energistics/Mapping/ResqmlWellboreChannelToVtkPolyData.cxx#L100)). D'où le fait que `real_base_name` ([source_resolver.py#L189](../../fespp_on_trame/app/core/engine/source_resolver.py#L189)) sonde la source : il ne retourne le titre brut que lorsque ce nom brut existe réellement sur la source par-vue — pour les channels sanitizés, il se replie désormais correctement sur le nom sanitizé, indexant la MÊME LUT que le chemin de rendu utilise.

> **Pièges :**
> - **Ne jamais laisser le primaire Show.** Chaque chemin générique (`_refresh_parent_rep_visibility`, `_refresh_chain_visibility`, `_ensure_extractor`) garde sur `_channelless_frame()` ([rep_in_scene.py#L420](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L420), [#L1100](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L1100), [#L1457](../../fespp_on_trame/app/core/sources/rep_in_scene.py#L1457)).
> - **Rescale-from-fresh.** Un choix de channel repointe un extracteur sur une seule feuille ; le rescale interne de `pvsimple.ColorBy` lit un cache périmé → tube plat `[0,1]`. `apply_color_array` re-rescale depuis le tableau côté client ([source_resolver.py#L805-L825](../../fespp_on_trame/app/core/engine/source_resolver.py#L805)).
> - **`toggle_rep_visibility` saute l'intermédiaire clear-coloring pour `Frame`** ([visibility.py#L154-L175](../../fespp_on_trame/app/core/engine/visibility.py#L154)) — l'œil d'un frame est un simple show/hide.
> - **Héritage au split** affiche le channel actif exclusivement dans la nouvelle vue ([scene_registry.py#L232](../../fespp_on_trame/app/core/sources/scene_registry.py#L232)) et réapplique les markers visibles via `apply_visible_markers` ([scene_registry.py#L265](../../fespp_on_trame/app/core/sources/scene_registry.py#L265)).

**Où modifier :** la logique d'exclusivité de channel vit entièrement dans `set_channel_visible` (le seul endroit qui masque les voisins) — y changer un-à-la-fois→N-à-la-fois. La logique multi des markers est dans `set_marker_visible`. « Le primaire de frame reste masqué » est `_channelless_frame()` — ajouter un nouveau kind de type frame signifie l'y ajouter AINSI QUE dans les listes regroupement/rep pertinentes. « Le COE-suit-le-channel-affiché » est dans le bloc `is_channel` de `toggle_dataarray_color`.

---

## Feuilles — propriétés (Continuous / Discrete / Categorical / TimeSeries / MultiRealization*) vs Marker

Les feuilles propriété et les feuilles Marker sont toutes deux des feuilles d'arbre sous une rep, mais ce sont des **types d'œil fondamentalement différents** : une propriété porte un œil **A** (tableau de données / couleur) ; un marker porte un œil **M** (visibilité seule).

### Feuilles propriété

| Aspect | Continuous / Discrete / Categorical | TimeSeries | MultiRealization / MultiRealizationTimeSeries |
|---|---|---|---|
| Synthétique ? | Non — vraie feuille propriété RESQML | Oui (collapse les nœuds par-timestep ; `propKind` porte le vrai kind) | Oui (`propKind` + `propTitle` portent le vrai kind / nom VTK) |
| Badge d'arbre | icône de propriété | horloge (`is_ts`) | pastille « MR » (`is_mr`) [+ horloge pour MRTS] |
| `_DATA_ARRAY_KINDS` | les trois | oui | les deux |
| Kind COE | `active_property_kind = kind` directement | attr `propKind` | attr `propKind` |
| Nom de tableau VTK | titre sanitizé | titre sanitizé | `<propTitle_sanitizé>_real_<idx>` (suffixé) |

- **Œil = A.** Les propriétés chargées apparaissent dans `ui_loaded_array_paths` et rendent l'œil de tableau ([data_load.py#L342](../../fespp_on_trame/app/core/engine/data_load.py#L342)). Cliquer colore la rep parente par ce tableau dans la vue cible ; le tableau actif précédent sur la même rep/vue perd son œil ([active_array.py#L231](../../fespp_on_trame/app/core/engine/active_array.py#L231)).
- **Sélection.** Une propriété n'est activable QUE lorsqu'elle est cochée sur son PROPRE id — être sous une rep cochée ne suffit pas (l'expansion de dépendances auto-ajoute la rep, donc une règle « sous rep cochée » activerait chaque voisin — le bug signalé, [activator.py#L213-L238](../../fespp_on_trame/app/core/activator.py#L213)).
- **Auto-activation au chargement.** Le dernier tableau ajouté par rep devient automatiquement l'œil actif dans le **panneau actif uniquement** ([data_load.py#L418](../../fespp_on_trame/app/core/engine/data_load.py#L418)). Pour MR, le bucket de réalisation est semé avec l'idx par défaut D'ABORD, sinon le résolveur ne peut trouver aucun tableau `_real_<idx>` et la rep reste SolidColor ([data_load.py#L489-L506](../../fespp_on_trame/app/core/engine/data_load.py#L489)).
- **Le choix de réalisation MR** est par-`(vue, tableau)` dans `ui_active_realization_by_array_by_view` ; `resolve_array_for_path` essaie le nom suffixé en premier ([source_resolver.py#L497](../../fespp_on_trame/app/core/engine/source_resolver.py#L497)).
- **TS pilote le TimeControl** — `panel_has_ts_by_id` est dérivé par panneau selon que tout tableau actif résout vers un nœud TS / MRTS ou un descendant ([active_array.py#L203](../../fespp_on_trame/app/core/engine/active_array.py#L203)) ; l'activator garde `on_data_loaded()` sur `is_ts_property` ([activator.py#L296-L299](../../fespp_on_trame/app/core/activator.py#L296)).
- **Source/visibilité/COE :** une propriété n'a aucune source propre — elle colore la source de sa rep. La COULEUR résout vers les proxies rendus que la rep expose (slicers IJK / extracteur de surface / **l'extracteur de channel affiché pour un frame**). Le mode COE est publié par `_handle_reservoir_change` (reservoir) ou `_publish_active_color_state` (well/surface) ([activator.py#L307](../../fespp_on_trame/app/core/activator.py#L307), [#L742](../../fespp_on_trame/app/core/activator.py#L742)).

> **Pièges :**
> - **Les nœuds MultiRealization sont des feuilles** — `add_subtreeview_data` ne récurse PAS dedans ([tree.py#L136](../../fespp_on_trame/app/core/tree.py#L136)).
> - **`title` vs `propTitle`.** Pour MR, le nom de tableau VTK est dans `propTitle`, pas `title` ([activator.py#L327](../../fespp_on_trame/app/core/activator.py#L327), [source_resolver.py#L456](../../fespp_on_trame/app/core/engine/source_resolver.py#L456)).
> - **Repli de recherche sanitizée.** `_find_array_in_store` / `resolve_array_for_path` réessaient avec `make_valid_vtk_name(title)` car FESPP retire les caractères hors de `[-.0-9A-Z_a-z]` ([activator.py#L11](../../fespp_on_trame/app/core/activator.py#L11), [source_resolver.py#L510](../../fespp_on_trame/app/core/engine/source_resolver.py#L510)).
> - **Un channel de LOG wellbore est une feuille propriété dans l'arbre WELL** — mais son ancêtre rep est un `Frame`, donc il est `is_channel` et passe par le chemin de l'extracteur par-channel, PAS par le chemin de couleur-de-rep générique. C'est le seul cas de feuille propriété où la feuille possède indirectement une source (son extracteur de channel).

### Feuilles marker (`WellboreMarker`, kind d'exécution `Marker`)

- **Œil = M (visibilité seule), MULTI.** Aucun tableau de couleur. Suivi dans `ui_loaded_marker_paths` (garde de rendu d'œil) + `ui_visible_marker_paths_by_view` (ensemble affiché par-vue), muté par `toggle_marker_visibility` ([data_load.py#L375](../../fespp_on_trame/app/core/engine/data_load.py#L375), [visibility.py#L75](../../fespp_on_trame/app/core/engine/visibility.py#L75)).
- **Source :** chaque marker visible possède un `EnergisticsExtractor` par-`(marker,vue)` sur le RepInScene du MarkerFrame (voir la section FrameRep).
- **Couleur :** SolidColor par-marker uniquement, via `solid_color_by_marker` ; `_publish_active_color_state` efface le mode COE pour un marker (pas une propriété) pour que le panneau se replie sur Solid ([activator.py#L765](../../fespp_on_trame/app/core/activator.py#L765)).
- **Sélection :** un `WellboreMarker` coché coche automatiquement la Trajectory du Wellbore ([tree_views.py#L33](../../fespp_on_trame/app/ui/drawer/tree_views.py#L33)).

> **Piège :** le test de kind de la liste d'œil est `"Marker"` (kind d'exécution), mais les listes de routage-d'arbre/regroupement utilisent `"WellboreMarker"` (kind de `supporttype` / de dépendance). Ne pas les confondre — `_update_marker_tracking` filtre sur `== "Marker"` ([data_load.py#L393](../../fespp_on_trame/app/core/engine/data_load.py#L393)).

**Où modifier :** la logique de couleur/activation des feuilles propriété est répartie entre `activator.py` (publie le COE + l'état actif, reservoir fait le gros du ColorBy inline) et `active_array.py` (la bascule d'œil + l'éventail). Les spécificités MR/TS se concentrent dans `realization_dispatch` + les branches `is_mr`/`is_ts`. La logique des feuilles marker est entièrement séparée (suivi de visibilité dans `data_load._update_marker_tracking`, bascule dans `visibility.py`, source dans `RepInScene._marker_extractors`) — une modification des markers ne touche jamais le chemin des propriétés et inversement.