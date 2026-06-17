# Refactor — Hiérarchie de types d'éléments (ElementType)

> Statut : **proposition / design**. Rien n'est encore implémenté.
> Objectif : remplacer le `if kind == ...` éparpillé par une hiérarchie de
> classes par héritage, pour qu'une modification sur un type ne casse plus
> les autres.

---

## 1. Pourquoi ce refactor

### Le symptôme
Le comportement diverge réellement par type d'élément RESQML (IjkGrid,
surface, trajectoire, frame de logs, frame de markers, …), mais aujourd'hui
cette divergence est exprimée par des branches `if kind == "..."` **dispersées
sur ~7 fichiers indépendants** :

| Couche | Fichier | Branches par type |
|---|---|---|
| Arbre (modèle) | [tree.py](../../fespp_on_trame/app/core/tree.py) | `_representation_type_in`, `is_grouping`, routage reservoir/surface/well |
| Tracking | [data_load.py](../../fespp_on_trame/app/core/engine/data_load.py) | `_DATA_ARRAY_KINDS`, `_update_data_array_tracking`, `_update_marker_tracking` |
| Arbre (vue) | [tree_views.py](../../fespp_on_trame/app/ui/drawer/tree_views.py) | `_eye_slot` (œil rep / array / marker) |
| Coloration | [active_array.py](../../fespp_on_trame/app/core/engine/active_array.py) | `is_channel` |
| Visibilité | [visibility.py](../../fespp_on_trame/app/core/engine/visibility.py) | `toggle_rep_visibility` (cas Frame), `toggle_marker_visibility` |
| Source par-vue | [rep_in_scene.py](../../fespp_on_trame/app/core/sources/rep_in_scene.py) | `_is_ijk_grid`, `_is_wellbore_frame`, `_is_marker_frame`, `_channelless_frame` |
| Source legacy | [ijkgrid.py](../../fespp_on_trame/app/core/sources/ijkgrid.py), [extract_block.py](../../fespp_on_trame/app/core/sources/extract_block.py) | classes par type (déjà) |

### L'incident déclencheur
En ajoutant la feature « logs affichables un par un » (au départ un retarget
de l'ExtractPath d'un extracteur partagé ; depuis retravaillé en un extracteur
par channel — voir [TYPES_PARTICULARITES.md](TYPES_PARTICULARITES.md)),
on a **cassé l'affichage des réservoirs et des surfaces** : la logique de
visibilité par-vue (`_ensure_extractor`, `_refresh_parent_rep_visibility`)
est partagée par TOUS les types, et un changement pensé pour les frames de
logs a dérivé le comportement des grilles/surfaces. C'est exactement le
genre de régression que l'héritage élimine : le code partagé vit dans la
classe de base, les spécificités dans les sous-classes — modifier un
override ne touche pas les frères.

### Le constat clé
La couche **source** a déjà des classes par type (`IjkGrid`,
`ExtractBlockRepresentation`). Le problème, c'est que :
1. `RepInScene` **branche sur le kind** au lieu de déléguer ;
2. les couches arbre / tracking / visibilité / couleur branchent **chacune
   de leur côté** sur les strings de kind, sans point de vérité commun.

On ne veut donc **pas** « une classe à partir de zéro » (qui dupliquerait
toute la plomberie par-vue, orthogonale au type), mais **une hiérarchie de
types d'éléments à laquelle les couches délèguent**.

---

## 2. Principe : héritage à 3 niveaux (général → groupe → unitaire)

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

- **Niveau général (`ElementType`)** : le comportement par défaut + le contrat
  (méthodes que toute sous-classe peut surcharger).
- **Niveau groupe** (`GridRep`, `SurfaceRep`, `FrameRep`, …) : ce qui est commun
  à une famille (ex. toutes les grilles partagent le pipeline slicers).
- **Niveau unitaire** (`IjkGrid`, `MarkerFrameRep`, …) : la spécificité d'un seul
  type.

### La règle d'or (ce que tu cherchais)
> Avant d'écrire une modif, on se demande : **à quel niveau ce comportement
> est-il vrai ?**
> - Vrai pour tout → `ElementType` (base).
> - Vrai pour une famille → la classe de groupe (`GridRep`, `FrameRep`, …).
> - Vrai pour un seul type → la classe unitaire.
>
> On écrit la modif **au plus haut niveau où elle est correcte**, et **jamais
> plus haut**. Résultat : zéro duplication, et un override ne peut pas casser
> un frère.

---

## 3. Le contrat (ce que chaque classe possède)

Chaque `ElementType` expose un contrat unique que les 7 couches consomment au
lieu de brancher sur le kind :

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

Exemple de spécialisation (ce qui aurait évité l'incident logs→surface) :

| Comportement | Niveau où il vit | Classes concernées |
|---|---|---|
| « hide en non-actif au load » | `Representation` (base des reps) | toutes les reps, **une seule fois** |
| « 1 log à la fois » | `ChannelFrameRep` | uniquement les frames de logs |
| « N markers, œil par marker » | `MarkerFrameRep` | uniquement les frames de markers |
| « slicers I/J/K + volume » | `GridRep` | IjkGrid + UnstructuredGrid + Sub |
| « pas de couleur, visibilité seule » | `color_policy()` surchargé | `MarkerLeaf` |

---

## 4. Intégration avec l'architecture par-vue existante

L'archi par-vue (`ViewScene` / `RepInScene`) **ne change pas de rôle** : elle
reste le multiplexage (rep, vue). On lui ajoute juste un membre `element_type`
et on remplace ses `if self._is_*()` par des appels au contrat :

```python
class RepInScene:
    def __init__(self, scene, rep_path):
        self.element_type = ElementType.for_path(scene.tree, rep_path)  # ← 1 résolution
    def source(self):
        return self.element_type.make_source(self.scene)               # ← délégation
    def _refresh_parent_rep_visibility(self):
        self.element_type.visibility_policy().refresh(self, self.scene) # ← délégation
```

Deux options pour le « où vit l'état par-vue » :
- **(A) Stratégie sans état** : `ElementType` est un singleton stateless ;
  `RepInScene` garde l'état (extracteurs, channel sélectionné, markers visibles)
  et le passe en argument. *Recommandé* — minimise le couplage, réutilise
  `RepInScene` tel quel.
- **(B) Sous-classes de `RepInScene`** : `IjkRepInScene`, `MarkerFrameRepInScene`,
  … Plus « pur objet » mais duplique la plomberie par-vue et complique le split
  de vue. *À éviter au premier tour.*

→ On part sur **(A)** : `RepInScene` délègue la *sémantique* à `element_type`,
et garde la *mécanique par-vue*.

---

## 5. Plan de migration incrémental (faible risque)

On ne réécrit **pas** d'un coup. Ordre proposé, chaque étape testable seule :

1. **Étape 0 — `element_type.py` + `ElementType.for_path()`**
   Créer la hiérarchie de classes + un résolveur `kind → classe`. Aucun appelant
   encore. *Zéro changement de comportement.*

2. **Étape 1 — Consolider les décisions de tracking** (data_load)
   Remplacer `_DATA_ARRAY_KINDS` / `_update_marker_tracking` par
   `element_type.tracking_bucket()`. Un seul endroit pour « ce kind nourrit
   quel bucket ».

3. **Étape 2 — Consolider l'œil** (tree_views + tree)
   Remplacer les conditions `is_loaded_rep / array / marker` et la suppression
   `item.type !== 'MarkerFrame'` par `element_type.eye_descriptor()`.

4. **Étape 3 — Consolider la visibilité** (rep_in_scene + visibility)
   Remplacer `_is_ijk_grid / _is_wellbore_frame / _is_marker_frame /
   _channelless_frame` et les branches de `_ensure_extractor` /
   `_refresh_parent_rep_visibility` par `visibility_policy()`.

5. **Étape 4 — Consolider la source** (rep_in_scene)
   `source()` / `make_source()` délègue ; `IjkGrid` et `ExtractBlockRepresentation`
   deviennent les `SourceHandle` retournés par `GridRep` / `SurfaceRep`.

6. **Étape 5 — Coloration** (active_array)
   `is_channel` → `color_policy()` + `visibility_policy() == ONE_AT_A_TIME`.

Après chaque étape : l'app doit se comporter **exactement** comme avant
(refactor pur). On garde les `_is_*` comme alias dépréciés tant qu'un appelant
les utilise, puis on les supprime.

---

## 6. Ce que ça change concrètement (rejouer l'incident)

**Avant** (aujourd'hui) : « 1 log à la fois » a touché `_ensure_extractor`
(partagé) → cassé grilles + surfaces. Fix = rajouter des gardes `_channelless_frame`
partout, qui re-branchent sur le kind.

**Après** (cible) : « 1 log à la fois » = surcharger `visibility_policy()` dans
`ChannelFrameRep` uniquement. `GridRep` et `SurfaceRep` héritent du
comportement standard, **inchangé**, **impossible à casser** depuis le code des
frames.

---

## 7. Risques & garde-fous

- **Gros périmètre, chemins chauds.** → migration incrémentale (§5), chaque
  étape = refactor pur testé.
- **Le kind runtime ≠ nom d'enum C++.** `SimplifyXmlTag` produit `'Frame'`,
  `'MarkerFrame'`, `'Marker'` (pas `'WellboreFrame'` / `'WellboreMarker'`). La
  table `KINDS` doit utiliser les strings **runtime**. Cf. le piège déjà présent
  dans `_representation_type_in` (`'WellboreMarker'` y est mort).
- **L'axe par-vue reste orthogonal.** Ne pas fusionner `ElementType` et
  `RepInScene` (option A, pas B).
- **Partial / partiel.** `Partial` reste un `Grouping`-like non sélectionnable —
  garder `find_all_selectable_descendant_ids` qui l'exclut.

---

## 8. Inventaire de migration (table de correspondance)

| Aujourd'hui (`if kind`) | Demain (classe / méthode) |
|---|---|
| `tree._representation_type_in` | `ElementType.tree_role() == REPRESENTATION` |
| `tree.is_grouping` | `ElementType.is_grouping()` |
| `data_load._DATA_ARRAY_KINDS` | `PropertyLeaf.tracking_bucket() == "array"` |
| `data_load._update_marker_tracking` | `MarkerLeaf.tracking_bucket() == "marker"` |
| `tree_views` is_loaded_rep/array/marker | `ElementType.eye_descriptor()` |
| `active_array.is_channel` | `ChannelFrameRep` + `visibility_policy() == ONE_AT_A_TIME` |
| `rep_in_scene._is_ijk_grid` | `isinstance(element_type, GridRep)` |
| `rep_in_scene._is_wellbore_frame` | `isinstance(element_type, ChannelFrameRep)` |
| `rep_in_scene._is_marker_frame` | `isinstance(element_type, MarkerFrameRep)` |
| `rep_in_scene._channelless_frame` | `FrameRep.visibility_policy().primary_hidden()` |
| `visibility.toggle_marker_visibility` | `MarkerLeaf` / `MarkerFrameRep.set_visible()` |

---

## 8 bis. Clarification importante : FOLDER (arbre) ≠ Grouping (famille)

Une investigation sur le sous-système Frame/MarkerFrame a fait émerger une
distinction que la hiérarchie doit acter explicitement :

> **Le rôle « FOLDER » dans l'arbre est orthogonal à la possession d'une
> source.** Un `FrameRep` (WellboreFrame / WellboreMarkerFrame) est un
> **FOLDER dans l'arbre** (pas d'œil, cocher = sélectionner tous les enfants,
> case tri-state) **mais une Representation dans la couche source** (il
> possède le clone + l'`EnergisticsExtractor` per-vue ; c'est l'ancre de rendu
> des channels/markers). Côté C++ c'est un `MapperType::MapperSet` — un
> conteneur qui possède la géométrie de ses enfants — pas un `isGroupingType`.

Conséquences pour le contrat :
- `tree_role()` doit pouvoir renvoyer `FOLDER` **sans** impliquer
  `is_grouping()=="pas de source"`. `FrameRep` : `tree_role()==FOLDER`,
  `eye_descriptor()==None`, `propagates_selection()==True`, **mais reste une
  sous-classe de `Representation`** (il a `make_source()`).
- `ChannelFrameRep` : `visibility_policy()==ONE_AT_A_TIME` ; enfants =
  `PropertyLeaf` (`tracking_bucket=='array'`, `COLORABLE`).
- `MarkerFrameRep` : `visibility_policy()==MULTI` ; enfants = `MarkerLeaf`
  (`tracking_bucket=='marker'`, `VISIBILITY_ONLY`).

**Étape 2/3 partiellement amorcée** (hors hiérarchie, en correctif) : Frame /
MarkerFrame sont déjà devenus des folders-pour-l'arbre via `is_grouping`
(propagation de sélection + suppression de l'œil), tout en restant dans
`_representation_type_in` (ancre de rendu). Le refactor consolidera ce
double rôle en `FrameRep` au lieu de l'exprimer par deux mécanismes séparés
(`is_grouping` vs `_representation_type_in`).

## 9. Décision attendue

Avant de lancer l'implémentation :
- **Option A** (stratégie déléguée, `RepInScene` garde l'état) — recommandée.
- Démarrer par **Étape 0 + 1** (création hiérarchie + tracking) qui sont les
  moins risquées et donnent déjà « un seul endroit par type ».

> Une fois ce doc validé, on attaque Étape 0 dans une branche dédiée, séparée
> des bug-fixes en cours.
