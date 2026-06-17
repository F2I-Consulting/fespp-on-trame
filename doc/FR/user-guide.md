# FESPP-on-Trame — Guide de l'utilisateur

Un visualiseur web pour les données RESQML / Energistics, construit par-dessus
le plugin ParaView FESPP et le framework [Trame](https://kitware.github.io/trame/).
Ouvrez des fichiers EPC + H5 dans votre navigateur, parcourez la hiérarchie des
données et affichez en 3D des grilles, des surfaces et des puits.

---

## Table des matières

- [Premiers pas](#getting-started)
- [L'interface en un coup d'œil](#the-interface-at-a-glance)
- [Chargement des données](#loading-data)
- [Parcourir les arbres](#browsing-the-trees)
  - [Sélectionner des éléments](#selecting-items)
  - [Les icônes en forme d'œil (visibilité et coloration)](#the-eye-icons-visibility--coloring)
  - [Nœud actif et panneau Attributs](#active-node-and-attributes-panel)
- [Coloration et opacité](#coloring--opacity)
  - [Mode couleur unie](#solid-color-mode)
  - [Mode propriété (LUT/PWF)](#property-lutpwf-mode)
  - [Propriétés catégorielles / discrètes](#categorical--discrete-properties)
- [Découpe de la géométrie : tranchoirs IJK, plans de coupe (Slice) et de découpe (Clip)](#cutting-geometry-ijk-slicers-slice--clip-planes)
- [Filtre par seuil (Threshold)](#threshold-filter)
- [Statistiques descriptives](#descriptive-statistics)
- [Séries temporelles](#time-series)
- [Propriétés multi-réalisations](#multi-realization-properties)
- [Travailler avec plusieurs vues](#working-with-multiple-views)
  - [Ajouter une vue (division ou vide)](#adding-a-view-split-or-empty)
  - [La vue active](#the-active-view)
  - [Visibilité et coloration par vue](#per-view-visibility-and-coloring)
  - [Copier depuis une vue](#copy-from-view)
  - [Lier les caméras](#linking-cameras)
  - [Vue de différence (Diff)](#diff-view)
- [Paramètres d'affichage généraux](#general-display-settings)
  - [Exagération verticale (échelle Z)](#vertical-exaggeration-z-scale)
  - [Mode de chargement (Auto / Manuel)](#load-mode-auto--manual)
  - [Hiérarchie de l'arbre](#tree-hierarchy)
  - [Couleur d'arrière-plan](#background-color)
- [Contrôles de la caméra](#camera-controls)
- [Panneau de journal (Log)](#log-panel)
- [Astuces et limites](#tips--limits)

---

## Premiers pas

L'application est servie sous forme d'application web monopage (single-page).
Ouvrez l'URL fournie par votre administrateur (p. ex. `http://<server>:9500/`).
Chaque onglet de navigateur constitue sa propre session — fermer l'onglet
abandonne votre sélection et les fichiers téléversés. Pour déployer votre
propre instance, consultez [`elba.md`](elba.md) pour l'installation basée sur
conteneur.

---

## L'interface en un coup d'œil

| Zone | Ce qu'elle fait |
|--------|--------------|
| **Barre d'outils supérieure** | Titre de l'application, bouton **Import data**, bouton **Load** (mode manuel uniquement). |
| **Tiroir de gauche** | Trois onglets (`Reservoir`, `Surface`, `Well`) comportant chacun un arbre **Data Explorer** et un panneau **Attributes**. En dessous : **General Display Settings**. |
| **Vue principale** | Le rendu 3D avec des contrôles de caméra flottants (en haut à gauche) et des contrôles temporels (en haut au centre, le cas échéant). |
| **Panneau inférieur** | Panneau de journal VTK rétractable (visible uniquement lorsque des avertissements/erreurs sont émis). |

Faites glisser le bord droit du tiroir pour le redimensionner.

---

## Chargement des données

1. Cliquez sur **Import data** dans la barre d'outils.
2. Déposez ou choisissez des fichiers `.epc` et leurs fichiers `.h5`
   correspondants (les deux sont requis). Vous pouvez aussi coller une URL
   OSDU ou vous connecter à un serveur ETP/OSDU depuis la même boîte de
   dialogue.
3. Attendez la fin de la barre de progression du téléversement. Les arbres
   du tiroir se remplissent alors avec ce que contient le fichier.

> **Note :** La session conserve vos données dans un répertoire temporaire
> qui est effacé lorsque le dernier client se déconnecte.

---

## Parcourir les arbres

Chaque onglet montre un type d'objet différent :

- **Reservoir** — grilles IJK et grilles non structurées.
- **Surface** — grilles 2D, ensembles de points, polylignes, ensembles
  triangulés.
- **Well** — trajectoires de forage (wellbore), frames, channels, markers,
  complétions et perforations.

Les arbres sont indépendants : vous pouvez avoir des éléments sélectionnés et
visibles dans plusieurs onglets à la fois.

Dans chaque arbre, les éléments sont triés **alphabétiquement à chaque
niveau** (la hiérarchie est préservée — seuls les frères sont ordonnés). Le
tri ignore la casse et les accents et tient compte des nombres, si bien que
`Grid2` précède `Grid10`.

### Sélectionner des éléments

Chaque ligne possède une case à cocher sur la gauche. Cocher une ligne indique
à FESPP de **charger** cet élément.

- Cocher un nœud de **regroupement** (`Wellbore`, `Collection`, `Partial`, et
  dans les modes de hiérarchie non Flat également `Feature` / `Interpretation`)
  coche automatiquement tous les descendants.
- Cocher une **représentation** (une grille, une surface, une trajectoire…)
  charge *uniquement* cette géométrie — ses propriétés restent décochées sauf
  si vous les cochez vous-même.
- Cocher un **WellboreChannel** ou un **WellboreMarker** coche automatiquement
  la `WellboreTrajectory` du forage parent (la géométrie sur laquelle le channel
  / marker est ancré).

Une petite **pastille colorée** apparaît à côté d'une ligne de représentation
une fois celle-ci chargée :
- une pastille **arc-en-ciel** signifie que la représentation est actuellement
  colorée par un tableau de propriété,
- un **point de couleur unie** signifie que la représentation est en mode
  couleur unie.

### Les icônes en forme d'œil (visibilité et coloration)

Deux variantes d'œil apparaissent à droite des lignes chargées :

| Icône | Où | Signification |
|------|-------|---------|
| **Œil** bleu / **œil fermé** gris | À côté de chaque représentation chargée | Bascule la visibilité — œil ouvert = la représentation est affichée dans la vue 3D, œil fermé = masquée mais toujours chargée. |
| **Œil** violet / **œil fermé** gris | À côté de chaque tableau de données chargé (Property, TimeSeries, MultiRealization, …) | Choisit quel tableau colore actuellement la représentation parente. Au plus **un** œil ouvert par représentation — en ouvrir un ferme les autres. Tous fermés → la représentation revient à sa couleur unie. |

Lorsque vous cochez une nouvelle propriété, son œil s'ouvre automatiquement
(et l'œil actif précédent sur la même représentation se ferme). Décocher la
propriété active la décharge et la représentation revient à sa couleur unie.

### Nœud actif et panneau Attributs

Cliquez sur le **libellé** d'une ligne (et non sur la case à cocher ou l'œil)
pour en faire le nœud *actif*. Le panneau **Attributes** de droite reflète le
nœud actif :

- Actif = une représentation → sélecteur de couleur unie.
- Actif = un tableau de données → l'éditeur LUT / PWF de ce tableau (tableaux
  continus) ou la liste de couleurs par catégorie (discret / catégoriel).

L'état actif est purement un concept d'interface — il ne change pas ce qui est
chargé ni ce qui est actuellement visible.

> **Une propriété doit être cochée pour pouvoir devenir active.** Cliquer sur
> le libellé d'une propriété dont la case est décochée ne fait rien — le
> panneau Attributes reste sur ce qui était actif auparavant. Cochez d'abord
> la propriété (ce qui la charge), puis cliquez sur son libellé pour modifier
> ses couleurs. Un nœud de représentation ou de regroupement s'active toujours
> dès que l'un de ses enfants est coché.

---

## Coloration et opacité

Le panneau **Colors & Opacity** sous la carte *Attributes* de chaque onglet est
piloté par le type du nœud actif.

### Mode couleur unie

Si le nœud actif est une représentation, le panneau affiche un sélecteur de
couleur avec alpha. Chaque représentation reçoit une couleur par défaut unique
lors de son premier chargement ; choisissez une nouvelle valeur RGBA pour
changer la couleur diffuse et l'opacité. Le réglage est mémorisé par
représentation — rouvrez le même nœud plus tard et la couleur réapparaît.

La couleur unie est ce que vous voyez lorsqu'aucun tableau de données n'est
actif sur la représentation (tous les yeux dataArray fermés).

### Affichage des markers (orientation & taille)

Quand le nœud actif est un **marker** ou un **Marker Set** (MarkerFrame),
un panneau **Marker display** apparaît (tag **global**) :

- **Orientation** — activée, un marker qui porte un *dip angle* + une *dip
  direction* RESQML est dessiné comme un **disque orienté** montrant cette
  orientation ; sinon (ou désactivée) c'est une simple **sphère**.
- **Taille** — le rayon du disque/de la sphère.

> ⚠️ Ces deux réglages sont **globaux** : ils s'appliquent à **tous les
> markers de toutes les vues** (la géométrie du marker est construite une
> seule fois par le loader et partagée entre les vues). Pas de variante
> par-marker / par-vue.

### Mode propriété (LUT/PWF)

Si le nœud actif est un tableau de données continu, le panneau affiche
l'éditeur LUT/PWF classique avec un dégradé de couleurs et une courbe
d'opacité. Vous pouvez :

- Faire glisser les points d'arrêt (stops) pour modifier les couleurs et les
  opacités.
- Cliquer sur le dégradé pour insérer de nouveaux points d'arrêt.
- Modifier la plage scalaire en saisissant des valeurs dans les champs min/max.
- La couleur NaN est préservée entre les activations.

Par défaut, une propriété fraîchement activée a une **opacité plate de 1** sur
toute la plage de valeurs (la grille est totalement opaque) et les **cellules
NaN sont totalement transparentes** — les cellules sans valeur (cellules de
grille inactives, propriétés partielles non couvertes, pas de séries
temporelles vides) ne s'affichent tout simplement pas. Les deux sont
indépendants : augmentez l'alpha NaN dans le sélecteur de couleur NaN pour
rendre à nouveau visibles les données manquantes, et remodelez la courbe
d'opacité pour les valeurs valides sans affecter la gestion des NaN.

La LUT s'applique dès que l'œil est ouvert sur le tableau. Lorsque l'œil est
fermé, vous pouvez tout de même ajuster la LUT (p. ex. pour la préparer avant
de rouvrir l'œil).

Pour une **propriété multi-réalisations**, le dégradé affiché correspond à la
LUT de la **réalisation actuellement choisie dans la vue cible** (le sélecteur
dans l'en-tête de la carte *Attributes*). Changer la vue cible ou la
réalisation recharge le COE pour refléter la LUT réellement appliquée dans
cette vue.

**Isolation des couleurs par vue.** Chaque vue de rendu possède sa propre
fonction de transfert couleur / opacité pour chaque propriété — modifier le
COE dans une vue ne déborde jamais sur une autre, même pour des propriétés
simples à réalisation unique. Dupliquer une vue (le bouton *Copy view*)
réplique le dégradé de la vue source sur la nouvelle vue comme point de départ,
après quoi les deux évoluent indépendamment.

### Propriétés catégorielles / discrètes

Pour `DiscreteProperty` et `CategoricalProperty`, le panneau bascule vers une
liste de sélecteurs de couleur/opacité spécifiques par catégorie (une ligne par
valeur distincte). La liste est triée par valeur et vous pouvez modifier chaque
cellule indépendamment.

---

## Découpe de la géométrie : tranchoirs IJK, plans de coupe (Slice) et de découpe (Clip)

La carte **Slicers** dans le panneau d'attributs Reservoir héberge trois façons
de découper la représentation active. Elles peuvent être combinées librement.

**Onglet IJK** *(grilles IJK uniquement)* : recadrage aligné sur les axes selon
les indices i/j/k propres à la grille.

- Basculez entre le mode **Range** (recadrage de volume, une seule boîte
  englobante par axe) et le mode **Slice** (un ou plusieurs plans individuels
  par axe).
- En mode Slice, chaque axe peut contenir plusieurs tranchoirs (utilisez **+**
  / **−** pour ajouter / supprimer) avec des positions et des yeux de
  visibilité indépendants.
- Un œil à côté de « Volume » contrôle si le volume recadré est rendu en mode
  Range.

**Onglet Slice** *(tous les types de représentation)* : un unique plan
arbitraire aligné sur un axe qui remplace la représentation par sa
section transversale 2D. Changez l'axe normal (X / Y / Z), faites glisser le
curseur de décalage, ou cliquez sur **Edit 3D** pour saisir le plan de façon
interactive dans la vue 3D. Un seul widget (slice ou clip) peut être en mode
édition à la fois.

**Onglet Clip** *(tous les types de représentation)* : mêmes contrôles d'axe +
décalage que Slice, plus une bascule **Invert side** qui inverse la moitié
conservée. Le clip peut être combiné avec le slice et avec les tranchoirs IJK.

Ces trois aspects sont par vue (voir [Travailler avec plusieurs
vues](#working-with-multiple-views)) — les modifier dans un panneau ne touche
aucune autre vue.

Lorsque vous cliquez sur l'œil d'une propriété, le ColorBy est appliqué à la
sortie de découpe actuellement visible (tranchoirs IJK / recadrage de volume,
plan de slice, plan de clip, ou la représentation entière lorsque aucun n'est
activé).

---

## Filtre par seuil (Threshold)

La carte **Thresholds** vous permet de filtrer les cellules d'une
représentation selon la valeur d'une propriété. Chaque seuil apparaît comme une
ligne dans la chaîne (les filtres empilés font l'union de leurs plages
conservées) ; les boutons **+** ajoutent un nouveau seuil racine
(`mdi-set-all`) ou enchaînent un enfant sous un seuil existant
(`mdi-set-center` → intersection) ; l'œil bascule la contribution du seuil ; la
corbeille le supprime.

Le curseur qui pilote une ligne de seuil s'adapte au type de la propriété :

- **Propriété continue** — un curseur de plage classique avec deux poignées sur
  la plage de valeurs. Faites glisser les deux poignées pour encadrer les
  cellules que vous voulez conserver.
- **Propriété discrète** (valeurs entières) — même curseur de plage mais aligné
  sur des pas entiers. Les libellés des poignées affichent la borne entière
  courante afin que vous voyiez exactement quelles valeurs sont incluses.
- **Propriété catégorielle** (catégories nommées) — curseur de plage avec une
  graduation étiquetée par catégorie (lue depuis les annotations de la LUT
  renseignées par le Color Editor). Les poignées s'alignent entre les
  catégories ; les cellules dont la catégorie tombe dans la plage choisie sont
  conservées.

Pour les propriétés multi-réalisations, le seuil se lie à la réalisation
actuellement choisie dans la vue active. Changer de réalisation par la suite ne
**recible pas** les seuils existants — ils continuent de filtrer sur la
réalisation avec laquelle ils ont été créés.

---

## Statistiques descriptives

Les statistiques se trouvent dans une **superposition flottante** au-dessus de
la multi-vue — ni ancrée dans la grille, ni dans le tiroir. Ouvrez-la via le
bouton `mdi-chart-box-outline` dans la barre d'outils supérieure (à gauche de
la roue dentée des réglages), ou en épinglant une propriété depuis l'arbre. La
fenêtre flottante apparaît ancrée près du coin supérieur gauche de la zone de
contenu en 1400×450, et vous pouvez :

- La **déplacer** en faisant glisser la zone vide à droite du titre de
  l'onglet.
- La **redimensionner** depuis n'importe quel bord / coin (8 poignées).
- La **fermer** avec le `×` sur l'onglet.
- La **ré-ancrer** dans la grille via `Shift+glisser` le titre de l'onglet dans
  l'une des zones d'ancrage (haut / bas / gauche / droite de n'importe quel
  panneau) — le même geste que dockview utilise partout.
- La **réduire (Minimize)** en une pastille de la taille d'une bande d'onglets
  (hauteur + largeur rétrécissent toutes deux, juste assez pour le titre de
  l'onglet + les trois boutons de chrome) via le bouton `mdi-window-minimize`.
  Utile lorsque vous voulez garder le panneau monté (pour que sa réouverture
  soit instantanée) tout en libérant l'écran derrière lui. Cliquez sur
  `mdi-window-restore` pour le ramener à sa position et sa taille précédentes.
- **Agrandir (Maximize)** la fenêtre flottante pour couvrir toute la zone de
  contenu de la multi-vue via le bouton `mdi-window-maximize`. Utile pour
  inspecter les statistiques à travers de nombreuses vues à la fois. Cliquez à
  nouveau (`mdi-window-restore`) pour revenir à sa taille flottante précédente.
  Minimize et Maximize sont mutuellement exclusifs — cliquer sur l'un annule
  l'autre automatiquement.

Tant qu'elle est réduite OU agrandie, les poignées de redimensionnement sont
désactivées afin que la coque rétractée/agrandie ne puisse pas être déplacée
par erreur (ce qui réécrirait les limites en ligne et ferait atterrir Restore à
la mauvaise taille).

Recliquer sur le bouton de la barre d'outils alors que les Stats sont ouvertes
**ferme** la fenêtre flottante — le bouton est une pure bascule
ouverture/fermeture. Pour faire passer une fenêtre flottante masquée au-dessus
de ses pairs, cliquez deux fois (fermer, puis rouvrir) : la fenêtre fraîchement
ajoutée atterrit en haut de la pile d'index z de dockview. Les propriétés
épinglées + leurs instantanés par Original vivent dans l'état de l'application
indépendamment de la fenêtre, de sorte que la fermer et la rouvrir plus tard
restaure chaque carte inchangée.

### Épingler une propriété

Chaque ligne de propriété dans l'arbre porte une petite icône de graphique
(`mdi-chart-box-outline`) **une fois que vous avez coché la case de la
propriété** — tant que la propriété n'est pas sélectionnée pour le chargement,
son bouton de statistiques reste masqué. Cliquez sur l'icône de graphique pour
**épingler** la propriété : l'onglet Stats s'ouvre (s'il n'est pas déjà ouvert)
et une nouvelle carte apparaît pour cette propriété. L'icône bascule vers
`mdi-chart-box` tant que la propriété est épinglée. Cliquez à nouveau (ou sur le
`×` dans l'en-tête de la carte) pour la désépingler.

Vous pouvez épingler plusieurs propriétés côte à côte pour les comparer.

### Lignes à l'intérieur de chaque table

La carte de chaque propriété épinglée contient une table de statistiques.
Colonnes :

- **Cmp** *(cartes MR / TS uniquement)* — icône ⊕ par ligne pour ajouter la
  ligne au **panier de comparaison** de cette propriété (bascule vers ✓ une fois
  ajoutée). Les cartes Continuous simples masquent entièrement la colonne — une
  carte à une seule ligne n'a rien à comparer.
- **Source** — ce sur quoi la ligne est calculée. Pour une ligne Original c'est
  simplement le nom de la propriété ; pour une ligne par vue c'est
  `<property> On <View N>`. Une icône `mdi-eye-outline` se trouve à côté du
  libellé sur chaque ligne — cliquer dessus ouvre un **panneau de Distribution**
  flottant pour cette ligne (histogramme à intervalles pour les tableaux
  continus, barres par catégorie pour discret / catégoriel ; voir
  [Distribution (Histogramme)](#distribution-histogram)).
- **Realization Index** *(propriétés MR / MR+TS uniquement)* — la réalisation
  qu'utilise la ligne. La ligne Original par défaut reçoit une liste déroulante
  éditable ; les lignes Custom (épinglées) et View affichent la valeur statique.
- **Time Step** *(propriétés TS / MR+TS uniquement)* — le pas de temps auquel la
  ligne a été calculée, formaté en `YYYY-MM-DD` (l'heure du jour est abandonnée
  — en pratique les séries temporelles de réservoir sont datées au jour). Même
  règle liste déroulante vs statique que Realization Index.
- **Value count** — cellules ayant une valeur numérique finie (= ce sur quoi les
  statistiques ci-dessous ont été calculées ; les cellules NaN sont écartées en
  amont).
- **No value count** — cellules dont la valeur n'a pas pu être évaluée (NaN).
  `Value count + No value count = total des cellules`.
- Métriques numériques de `vtkDescriptiveStatistics` : Min, Max, Mean, Std Dev,
  Variance, Sum, Skewness, Kurtosis, M2 / M3 / M4 (moments centraux bruts —
  consultez le guide du développeur si vous souhaitez re-dériver Variance /
  Skewness / Kurtosis selon une autre convention).
- **Q1 / Median / Q3** — les trois marqueurs de l'écart interquartile, calculés
  côté serveur via `numpy.percentile([25, 50, 75])` sur le même tableau de
  valeurs dépouillé des NaN que le reste des métriques, afin que les chiffres
  panier-vs-histogramme restent cohérents.

Les lignes elles-mêmes :

- **1+ lignes Original** — statistiques sur le tableau VTK non filtré de la
  représentation, indépendamment du slicer / clip / threshold d'une vue. La
  ligne **Default** suit les real / TS auto-résolus de la propriété ; cliquez
  sur son **icône d'épingle** dans la colonne Source pour instantanéiser les
  `(real, TS)` courants dans une nouvelle ligne **Custom** éditable, puis le
  Default se réinitialise sur auto pour que vous puissiez continuer à itérer.
  Chaque ligne Custom porte l'icône `×` pour la supprimer.
- **Une ligne par vue** qui colore actuellement par cette propriété —
  statistiques sur ce que chaque vue affiche réellement (post-slicer /
  post-clip / post-threshold). La ligne reprend la réalisation actuellement
  choisie dans cette vue, le pas de temps de son TimeControl par vue, et
  recalcule chaque fois que le slicer / clip / threshold ou la réalisation de la
  vue change.

**Panier de comparaison par propriété (MR / TS uniquement).** Chaque carte dont
la propriété porte un axe Multi-Réalisations ou Série Temporelle fait apparaître
la colonne unique **Cmp** ci-dessus et un bouton **Compare** dans l'en-tête de
la carte — les deux réservés aux cartes MR / TS. Cochez des lignes dans la
colonne `Cmp`, puis cliquez sur **Compare** dans l'en-tête de la carte (devient
actif à ≥ 2 lignes cochées) pour ouvrir le **panneau Compare-stats** flottant
(kind `stats_compare`) lié à cette propriété. Les paniers sont cloisonnés par
propriété : le panier de la propriété A est physiquement séparé de celui de la
propriété B, de sorte que mélanger les propriétés est structurellement
impossible (pas besoin de snackbar de rejet). Les propriétés Continuous simples
sans axe MR / TS masquent à la fois la colonne et le bouton — une carte à une
seule ligne n'a rien de significatif à comparer.

**Barre d'outils du panneau Compare-stats.** Le panneau Compare-stats flottant
est un **singleton par propriété** — le bouton **Compare** ouvre ou met au
premier plan le même panneau pour cette propriété ; les événements de cochage /
décochage du panier mettent à jour le panneau en direct sur place. Sa barre
d'outils comporte, de gauche à droite :

1. **Badge en direct** — pastille `<property title> — N rows` indiquant quelle
   propriété est concernée et la taille du panier. Mise à jour à chaque cochage
   / décochage sans re-rendu.
2. **Sélecteur de référence (baseline, toujours actif).** Un VSelect listant
   chaque ligne du panier, avec une sentinelle `(no baseline)` en tête de liste
   par défaut. Choisir une ligne bascule la matrice en **mode comparaison Δ** :
   chaque cellule se peint en vert (`cmp-cell-pos`) lorsqu'elle est au-dessus de
   la référence, en rouge (`cmp-cell-neg`) lorsqu'elle est en dessous, avec une
   **pastille Δ** en ligne (`↑ / ↓ / =` + delta absolu + `%` relatif lorsque la
   référence n'est pas nulle) juste à côté de la valeur. Laisser le sélecteur
   sur `(no baseline)` revient à un ombrage par **extrema** (bleu
   `cmp-cell-min` pour le min par métrique, orange `cmp-cell-max` pour le max
   par métrique) afin que l'utilisateur garde un repère visuel utile. Pas de
   bascule de mode de surlignage distincte, pas de contrôles Z-score / heatmap /
   Top N — le sélecteur de référence EST l'interrupteur de surlignage.
3. **Marqueur visuel de référence.** La ligne / colonne de référence choisie est
   teintée d'indigo avec une pastille **BASELINE** sur son en-tête afin que la
   référence soit reconnaissable au premier coup d'œil. En **layout A** (lignes
   = métriques, colonnes = éléments), la colonne de référence est **collée à
   gauche** (sticky-left) juste après la colonne de libellé Metric, de sorte
   qu'elle reste ancrée sur le bord gauche de la zone de défilement pendant que
   l'utilisateur fait défiler horizontalement les autres lignes. Classes CSS :
   `cmp-baseline-chip` (la pastille), `cmp-baseline-anchor-bg` (la teinte indigo
   de la cellule), `cmp-baseline-anchor-bar` (le positionnement sticky-left).
4. **Menu de visibilité des métriques** — liste déroulante à sélection multiple
   pour retirer les métriques bruyantes (`M2`, `M3`, `M4`, `Variance`, `Sum`,
   `Skewness`, `Kurtosis`, …) à la fois de la matrice visible et de l'export
   CSV. Par défaut « tout visible » ; des préréglages en haut du menu
   (*Central tendency* / *Spread* / *Shape* / *All*) préremplissent la liste en
   un clic.
5. **Icône de transposition** (`mdi-table-pivot`, avec un repli en variante
   rotate lorsque la police d'icônes est manquante) — échange lignes ↔ colonnes
   de sorte que les métriques deviennent des en-têtes de colonne (cliquables
   pour trier en layout B).
6. **Show distributions** — ouvre ou met au premier plan le panneau flottant
   singleton **Compare-distribution** pour le MÊME panier (même `array_path`),
   affichant chaque ligne du panier comme un tracé superposé. Les clics
   ultérieurs sur ce bouton recentrent sur le même panneau ; les événements de
   cochage / décochage du panier mettent à jour la superposition en direct sur
   place. Lorsque le panier descend en dessous de 2 lignes, le panneau de
   distribution reste monté et affiche un espace réservé *« Add 2 or more
   rows... »* — fermez via le `×` de l'onglet pour le désinscrire.
7. **Download CSV** — exporte la matrice de comparaison en CSV (lignes ×
   métriques visibles, projection issue du menu de visibilité).

**Glisser-déposer pour réordonner.** Tout en-tête de colonne (layout A) ou
en-tête de ligne (layout B) est déplaçable : saisissez-en un et déposez-le sur
un autre en-tête pour le placer avant celui-ci. Le nouvel ordre persiste dans la
variable d'état `ui_stats_compare_order_<panel_id>` du panneau — il survit aux
modifications du panier (les nouvelles lignes s'ajoutent à la fin) et se
rafraîchit lors du tri / de l'épinglage de référence.

**Pastille de profil de distribution à côté de chaque en-tête d'élément.**
L'en-tête de chaque ligne du panier porte toujours une petite pastille dérivée
de ses Skewness + Kurtosis : `sym` (symétrique), `↦ skew` (asymétrie à droite),
`↤ skew` (asymétrie à gauche), ou `heavy` (à queue lourde, excès de kurtosis >
3). Survolez la pastille pour le rappel des seuils ; la pastille est masquée
lorsque Skewness / Kurtosis sont manquants.

**Préfixe de représentation parente.** Les en-têtes de carte et les libellés de
colonne de Compare-stats portent un préfixe atténué `<RepTitle> /` lorsque la
représentation englobant la propriété a un titre — afin que deux représentations
partageant le même nom de propriété (p. ex. `VOIL` sur deux grilles
différentes) restent distinguables dans l'en-tête de la carte ET dans les
libellés de colonne par élément de la matrice.

Le panneau Compare-stats est une fenêtre flottante dockview ordinaire : déplacez
-la en faisant glisser la bande d'onglets, redimensionnez depuis n'importe quel
bord, fermez via le `×` de l'onglet, ré-ancrez avec `Shift+glisser`. Fermer
l'onglet désinscrit le panneau — le prochain clic sur **Compare** pour cette
propriété en génère un nouveau (ses réglages de barre d'outils reviennent aux
valeurs par défaut).

Ce que vous voyez exactement :

- **Ancré sur ce qui est rendu** — les statistiques sont calculées sur la
  géométrie actuellement visible dans la vue active. Si un slice / clip /
  tranchoir IJK ou seuil est actif, les statistiques reflètent uniquement les
  cellules survivantes (et non la représentation entière).
- **Une ligne à la fois** — pour une propriété multi-réalisations, la ligne
  montre la réalisation actuellement choisie dans la vue active (via la
  superposition RealizationPicker par vue). Changez de réalisation pour voir une
  autre ligne.
- **Les valeurs NaN sont exclues** avant le calcul des statistiques, de sorte
  que Std Dev, Skewness, Kurtosis restent significatives au lieu de se dégrader
  en `–` lorsque le tableau contient quelques cellules invalides.
- **Sensible au temps** — déplacer le curseur sur la chronologie met à jour les
  statistiques en direct pour la vue active, à la fois avec le TimeControl
  global et avec les TimeControl par vue. Les libellés Time Step (à la fois dans
  la pastille TC et dans la colonne Time Step des statistiques) affichent
  uniquement la date (`YYYY-MM-DD`) ; la partie heure du jour de l'horodatage
  ISO sous-jacent est masquée car les TS de réservoir sont datées au jour.
- **Les propriétés discrètes / catégorielles** font actuellement remonter les
  mêmes métriques numériques que les tableaux continus — ce n'est *pas* une
  statistique significative (la moyenne de catégories non ordonnées n'a aucune
  sémantique). Une vue histogramme par catégorie est prévue en suivi.

Le panneau est masqué lorsqu'aucune propriété n'est active ou lorsque la
géométrie active n'a rien à calculer.

**Ajustements UX récents à connaître :** les cellules numériques s'affichent
désormais à trois décimales (`toFixed(3)`) afin que les métriques d'amplitude
variée restent lisibles sans défilement horizontal. Les VSelect **Realization
Index** et **Time Step** de la ligne Default Original ne portent plus le `×`
effaçable — ils prennent par défaut le premier real / TS disponible au lieu de
pouvoir être effacés vers « rien », puisqu'un index manquant rend simplement la
ligne incalculable. Les deux sélecteurs sont rendus **compacts** afin de tenir
confortablement même lorsque de nombreuses colonnes partagent la même ligne ;
cliquer sur la liste déroulante ouvre un menu qui **s'élargit jusqu'à 360 px**
afin que les longs libellés Time-Step restent lisibles. Le point d'entrée de
distribution par ligne est l'icône `mdi-eye-outline` à côté du libellé Source
(pas de colonne distincte), gardant la table étroite lorsque ni l'axe MR ni
l'axe TS n'exigent une colonne Cmp.

---

## Distribution (Histogramme)

Chaque ligne des tables de **Statistiques descriptives** porte une icône
`mdi-eye-outline` **à côté du libellé Source** (pas de colonne dédiée — garde la
table étroite sur les cartes Continuous simples). Cliquez dessus pour ouvrir un
**panneau de Distribution flottant** montrant la distribution des valeurs de
cette ligne — histogramme à intervalles pour les propriétés continues (50
intervalles par défaut), barres par catégorie pour discret / catégoriel. Le
titre de la figure reprend la cellule Source de la ligne avec le suffixe
(real, ts) le cas échéant. L'axe X est étiqueté `<Property name> (<unit>)`
lorsque l'unité de mesure est disponible sur l'assemblage de l'arbre, sinon
simplement `<Property name>` seul (aujourd'hui le `vtkDataAssembly` construit
par FESPP ne fait pas encore remonter l'UOM, vous verrez donc le nom nu —
consultez la note RESQML / FESPP dans le guide du développeur pour ce qui est
nécessaire côté C++ pour activer cela).

**Multi-instance :** chaque clic sur eye-outline ouvre un NOUVEAU panneau de
Distribution — vos histogrammes précédents ne sont pas remplacés, ce qui vous
permet de disposer plusieurs distributions côte à côte. Fermez-en une avec son
`×`, déplacez-la en faisant glisser la barre de titre, redimensionnez depuis
n'importe quel bord / coin, ré-ancrez dans la grille dockview via
`Shift+glisser` le titre de l'onglet. Même chrome que les Stats et les vues de
rendu.

**Superposition multi-tracés (singleton).** Cochez les lignes que vous voulez
superposer dans la colonne **Cmp** de la carte de propriété, cliquez sur
**Compare** dans l'en-tête de la carte pour ouvrir le panneau Compare-stats
flottant, puis cliquez sur **Show distributions** dans la barre d'outils de ce
panneau. Le bouton de la barre d'outils ouvre ou met au premier plan le panneau
flottant singleton **Compare-distribution** pour le même panier (par propriété)
: le cochage / décochage ultérieur de la colonne `Cmp` met à jour en direct sur
place à la fois la matrice et la superposition de distribution. Un panier < 2
garde le panneau de distribution monté avec l'espace réservé *« Add 2 or more
rows... »* — utile lorsque vous voulez laisser le panneau ouvert et construire
la superposition de façon incrémentale ligne par ligne. Comme le panier est par
propriété, les entrées de légende sont réduites à simplement `real N, ts <label>`
(le nom de la propriété est redondant). Pour les lignes propriété+TS, la légende
indique uniquement `ts <label>` ; pour les lignes MR+TS vous obtenez les deux
axes. Cliquez sur n'importe quelle entrée de légende pour basculer la visibilité
de ce tracé — Plotly natif, sans aller-retour serveur.

**Contrôles par panneau** — chaque panneau de Distribution porte une barre
d'outils compacte au-dessus du graphique :

- **Shape** — trois boutons font alterner entre `bars` (histogramme), `line`
  (tracé en escalier, plus agréable sur des comptages d'intervalles denses) et
  `curve` (spline lissée passant par les centres d'intervalles, visuellement
  proche d'une KDE).
- **Bins** — curseur 5 → 500 (propriétés continues uniquement ; discret /
  catégoriel affiche toujours une barre par catégorie).
- **log Y** — bascule l'axe Y en échelle logarithmique. Utile lorsqu'un
  intervalle domine (porosité nulle dans les couches d'argile, etc.).
- **stats** — superpose des lignes verticales pour la moyenne (sarcelle pleine),
  la médiane (indigo pointillé), Q1 / Q3 (gris en pointillés) avec des libellés
  textuels au-dessus. Panneaux à une seule ligne uniquement — les panneaux de
  comparaison masquent ce contrôle car les superpositions par ligne encombrent
  vite la figure.
- **cumul** — bascule en distribution cumulative (les hauteurs deviennent la
  somme courante). Se lit comme « fraction des cellules en dessous de cette
  valeur » lorsqu'il est combiné avec la normalisation `p`.
- **n / dens / p** — normalisation des hauteurs. `n` conserve les comptages
  bruts, `dens` rééchelonne pour que l'intégrale vaille 1 (comparer des
  distributions de tailles d'échantillon différentes), `p` rééchelonne pour que
  les intervalles somment à 1 (lire les hauteurs d'intervalle comme des
  probabilités).
- **Badge Kept / total** — pastille ambre en haut à droite indiquant combien de
  cellules ont contribué à l'histogramme et combien ont été écartées comme NaN.
  Se masque lorsque le total est nul.
- **Download** — bouton `mdi-download` qui exporte les intervalles courants en
  CSV (colonnes `center, height, width` ; un triplet de colonnes par tracé en
  mode comparaison).

Toutes les mutations de la barre d'outils recalculent la figure côté serveur et
poussent des intervalles + méta + CSV frais dans le même flush, de sorte que le
graphique, le badge et le lien de téléchargement restent synchronisés.

---

## Séries temporelles

Les nœuds `TimeSeries` et `MultiRealizationTimeSeries` sont des feuilles. Le
type de propriété sous-jacent (Continuous / Discrete / Categorical) est préservé
sur l'icône du nœud.

Activez-en un et les **Time controls** apparaissent en haut de la vue 3D (barre
de lecture avec play/pause, boutons pas-à-pas et une chronologie). Les libellés
temporels suivent les métadonnées de la série temporelle.

Toutes les propriétés n'ont pas une valeur à chaque pas de temps (certaines ne
portent qu'un seul pas, p. ex. une région statique). Se déplacer jusqu'à un pas
où la propriété active n'a pas de données affiche la grille comme **totalement
transparente** (chaque cellule est remplie de NaN) — un signal clair « pas de
données à ce pas » — et les données réapparaissent lorsque vous revenez à un pas
qui a des valeurs.

---

## Propriétés multi-réalisations

`MultiRealization` et `MultiRealizationTimeSeries` regroupent toute une pile de
réalisations dans une unique feuille d'arbre. En charger une active chaque
réalisation disponible comme un tableau distinct sur la source — chaque vue de
rendu choisit ensuite indépendamment quelle réalisation afficher.

Un **Realization picker** apparaît en haut de chaque vue activement colorée par
une propriété MR (basculable via l'icône de calques dans la barre d'outils de la
vue). La première réalisation est auto-sélectionnée la première fois qu'une
propriété MR est activée dans une vue ; cliquez sur le curseur / les flèches
pour parcourir les autres. Les vues peuvent afficher différentes réalisations de
la même propriété côte à côte.

Un **Realization picker global** dans la barre d'outils supérieure apparaît
lorsque deux vues ou plus rendent des propriétés MR. Choisir un index à cet
endroit diffuse le choix vers chaque vue qui colore actuellement par cette
propriété — utile pour « régler la réalisation N partout ».

Les seuils ajoutés sur une propriété MR se lient à une réalisation spécifique
(celle actuellement choisie dans cette vue) — changer de réalisation par la
suite ne déplacera pas le seuil existant.

La plage de la LUT peut être **verrouillée** afin que la correspondance des
couleurs reste comparable entre réalisations.

---

## Travailler avec plusieurs vues

FESPP-on-Trame peut rendre plusieurs vues indépendantes des mêmes données côte à
côte. Chaque vue possède sa propre visibilité, coloration, tranchoirs, plan de
slice, plan de clip, chaîne de seuils, choix de réalisations et caméra. Diviser
une vue hérite de l'état de la source une fois ; à partir de là chaque vue
diverge indépendamment.

### Ajouter une vue (division ou vide)

Chaque panneau de rendu porte trois icônes dans sa rangée d'onglets :

| Icône | Action |
|------|--------|
| Division verticale (▢│▢) | Ajoute une nouvelle vue à **droite** de celle-ci. |
| Division horizontale (▢／▢) | Ajoute une nouvelle vue **en dessous** de celle-ci. |
| Roue dentée | Renommer cette vue / réglages. |

Une fenêtre modale s'ouvre avec trois choix de contenu pour la nouvelle vue :

- **Copy "{this view}" scene** — réplique l'état complet de la vue source
  (visibilité, coloration, tranchoirs, slice / clip, chaîne de seuils, choix de
  réalisations). La nouvelle vue démarre comme un clone, puis diverge lors des
  modifications ultérieures.
- **Empty scene** — aucune représentation n'est visible. Chaque représentation
  chargée apparaît avec un œil fermé dans la rangée de pastilles par vue de
  l'arbre ; cliquez sur un œil pour remplir la vue vide de façon incrémentale.
- **Diff scene (A − B)** — voir [Vue de différence (Diff)](#diff-view).

**Faire flotter une vue.** Toute vue ancrée peut être promue en **fenêtre
flottante** qui se superpose au reste de la multi-vue : maintenez `Shift` et
faites glisser le titre d'onglet de la vue dans un espace vide. La fenêtre
flottante a le même chrome que la superposition Stats (ombre portée, 8 poignées
de redimensionnement, déplacement par bande d'onglets). La caméra, les
affichages, les tranchoirs, la chaîne de seuils et l'éditeur de couleurs sont
tous préservés à travers la transition — dockview garde l'instance du panneau
montée, de sorte que le contenu 3D ne se réinitialise pas. Faites glisser le
titre flottant de retour sur la zone d'ancrage d'un autre onglet (sans `Shift`)
pour le ré-ancrer. La même paire de gestes fonctionne sur la superposition
Stats.

### La vue active

La vue actuellement focalisée est mise en évidence par une bordure intérieure
bleue et une pastille **ACTIVE**. Cliquez n'importe où dans le corps d'une autre
vue, ou sur son onglet, pour changer le focus.

Par défaut, la carte **Attributes** du tiroir édite l'état de la **vue active**
— slice, clip, chaîne de seuils, tranchoirs IJK et éditeur de couleurs ciblent
tous la vue qui a le focus. Une petite bascule **pin** (épingle) dans la barre
d'outils Attributes vous permet d'épingler les panneaux à une vue spécifique à
la place : choisissez cette vue dans la liste déroulante qui apparaît à côté de
l'épingle, et les panneaux continuent de l'éditer même lorsque vous cliquez dans
la zone 3D d'une autre vue. Cliquez à nouveau sur l'épingle pour revenir au
suivi de la vue active. Si la vue épinglée est fermée, les panneaux reviennent
automatiquement au suivi de la vue active.

### Visibilité et coloration par vue

Chaque ligne de représentation chargée dans l'arbre porte une *rangée de
pastilles en forme d'œil* — une par vue de rendu. Chaque pastille indique si la
représentation est affichée dans cette vue spécifique ; cliquez pour basculer.
Fermer une représentation dans la vue A n'affecte pas la vue B.

Les pastilles d'œil de propriété fonctionnent de la même façon : cliquer sur la
pastille d'une propriété dans la vue A applique le ColorBy sur cette propriété
dans la vue A uniquement. Chaque vue conserve sa propre correspondance ColorBy
indépendamment.

### Copier depuis une vue

Le panneau Threshold, le panneau Slice, le panneau Clip et le panneau IJK
Slicers ont chacun une petite icône **copy** dans leur en-tête. Cliquer dessus
ouvre une liste déroulante répertoriant toutes les autres vues de rendu ; en
choisir une instantanéie l'état de cette vue pour **ce seul aspect** et
l'applique à la vue active. Après la copie, les deux vues possèdent toujours un
état indépendant — une modification ultérieure dans l'une ne se propagera pas.

Le même mécanisme est utilisé lorsque vous choisissez « Copy scene » lors de la
division d'une vue (il instantanéie simplement tous les aspects d'un coup).

### Lier les caméras

La barre d'outils de caméra de chaque vue (en haut à gauche de la zone 3D) porte
une icône **aimant**. Cliquez dessus pour ouvrir un menu des autres vues :
cochez celles dont la caméra doit suivre cette vue. Le lien est symétrique et ne
se déclenche qu'au relâchement de la souris (pas de synchronisation par image,
de sorte que la rotation interactive reste réactive).

### Vue de différence (Diff)

La scène Diff est une vue singleton dédiée à l'affichage de la différence A − B
entre deux propriétés de la même grille. La vue s'ouvre avec un formulaire de
sélection A/B ; choisissez deux propriétés, cliquez sur **Compute**, et le champ
résultant est rendu de la même façon qu'une propriété ordinaire (LUT, éditeur de
couleurs, palette). Modifier la LUT ou les entrées utilise les petits boutons
d'action qui apparaissent dans le coin supérieur gauche du panneau diff après le
premier calcul.

---

## Paramètres d'affichage généraux

La carte du bas du tiroir héberge les options globales.

### Exagération verticale (échelle Z)

Faites glisser le champ d'échelle Z pour appliquer la même exagération verticale
à chaque représentation. Cliquez sur **Apply** pour pousser la modification.
Utile pour les couches géologiques fines où une échelle 1:1 aplatit trop de
détails.

### Mode de chargement (Auto / Manuel)

- **Auto** *(par défaut)* — chaque bascule de case à cocher est poussée
  immédiatement vers le pipeline ParaView, de sorte que la vue 3D se met à jour
  au fur et à mesure que vous cliquez.
- **Manual** — les bascules de cases à cocher ne mettent à jour que l'état de
  sélection ; la vue 3D reste figée. Cliquez sur le bouton **Load** de la barre
  d'outils (visible uniquement en mode manuel) pour tout pousser d'un coup.
  Pratique lorsque vous voulez préparer une grande sélection multi-onglets sans
  payer un coût de chargement à chaque clic.

> **Note :** Le mode de chargement contrôle le **chargement** (présence des
> données dans ParaView). Il ne contrôle pas la **visibilité** — ce sont les
> icônes en forme d'œil sur chaque ligne chargée qui le font, indépendamment.

### Hiérarchie de l'arbre

Trois dispositions vous permettent de réorganiser la façon dont les
représentations sont regroupées dans les arbres :

- **Flat** *(par défaut)* — la disposition héritée : représentations directement
  sous la racine, propriétés sous leur représentation.
- **By Interpretation** — les représentations sont regroupées sous leur parent
  Interpretation.
- **By Feature & Interpretation** — ajoute un regroupement Feature
  supplémentaire au-dessus de l'Interpretation.

Ceci est surtout utile lorsque plusieurs représentations partagent le même nom
mais diffèrent par Interpretation (p. ex. des variantes de la même grille).

> ⚠ **Changer de mode efface toutes les sélections, visibilités et états de
> coloration courants.** Un snackbar vous avertit lorsque cela se produit
> réellement. L'arbre est reconstruit sur place — pas besoin de réimporter le
> fichier.

### Couleur d'arrière-plan

Un sélecteur de palette pour l'arrière-plan de la vue 3D. Choisissez parmi les
échantillons ou saisissez une couleur hexadécimale.

---

## Contrôles de la caméra

En haut à gauche de la vue 3D : bande verticale de boutons avec des boutons de
réinitialisation/visée le long d'un axe (`+X`, `-X`, `+Y`, `-Y`, `+Z`, `-Z`,
ajustement de la caméra). Utilisez la souris à l'intérieur de la vue pour faire
des panoramiques / pivoter / zoomer de façon interactive.

---

## Panneau de journal (Log)

Lorsque VTK / ParaView émettent des avertissements ou des erreurs pendant un
chargement ou un rendu, ils s'accumulent au bas de l'écran derrière un panneau
replié. L'en-tête du panneau affiche le décompte en direct des erreurs et des
avertissements ; dépliez-le pour lire les messages, cliquez sur **Clear** pour
vider la file.

Le panneau est masqué lorsque la file est vide — il ne prend pas de place à
l'écran tant que rien n'a été journalisé.

---

## Astuces et limites

- **Les sessions sont isolées.** Fermer l'onglet du navigateur perd vos données
  et votre état de sélection.
- **La couleur par représentation est mémorisée**, mais uniquement au sein de la
  session courante.
- **Les états des yeux (visibilité, tableau actif) sont réinitialisés lors d'un
  changement de mode de hiérarchie de l'arbre.** C'est volontaire — les
  identifiants et les chemins de nœuds changent d'une disposition à l'autre.
- **Les chargements de propriétés lourds** (grandes grilles IJK avec de
  nombreuses propriétés) bénéficient du mode de chargement Manual — choisissez
  d'abord tout ce dont vous avez besoin, puis cliquez sur **Load** une seule
  fois.
- **Les Grid2D et autres surfaces** sont rendues via leur propre source
  ExtractBlock. Masquer via l'œil retire véritablement l'acteur de la vue.
- Le **panneau de journal VTK** est votre ami lorsque quelque chose semble aller
  de travers — il fait remonter des messages qui ne seraient autrement pas
  visibles depuis un navigateur.
