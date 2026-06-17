# Panneaux Compare-stats / Distribution — feuille de route des travaux à venir

Consigné après la série de retours du Tier 1 (2026-06). La version
actuelle livre le mode baseline toujours actif, le panier de
comparaison unifié par propriété, la colonne baseline figée, le
glisser-déposer pour réordonner, les chips de profil de distribution,
le menu de visibilité des Métriques avec préréglages, le préfixe
rep-parent dans la chip de la barre d'outils, et le panneau singleton
Compare-distribution avec superposition barres/ligne/courbe.

Ce document recense ce qui a été délibérément laissé pour plus tard.
Choisissez les éléments par priorité lorsqu'une branche de suivi
arrive.

---

## Tier 2 — Visualisations comparatives (prochain lot)

Ces fonctionnalités étendent les panneaux de comparaison avec des
formes de graphiques plus riches. Elles vont principalement sur le
**panneau Compare-distribution** pour la superposition de
boxplots / violons / histogrammes, et ajoutent une visualisation
heatmap / radar sur le **panneau Compare-stats** comme vues
alternatives.

### 1. Boxplots + Violons sur Compare-distribution

- **Pourquoi** — les modes actuels `bars / line / curve` donnent la
  forme mais pas les statistiques de synthèse. Les boxplots montrent
  les quartiles + valeurs aberrantes par élément en un coup d'œil ;
  les violons combinent les deux.
- **Où** — étendre `compute_compare_figure` dans
  `distribution_dispatch.py` avec deux nouvelles valeurs de mode
  d'affichage (`box`, `violin`). Plotly prend en charge les deux
  nativement (`go.Box`, `go.Violin`).
- **UI** — ajouter 2 boutons dans la barre d'outils du panneau
  Compare-distribution (à côté de la bascule existante
  bars/line/curve). Chacun correspond à
  `display_mode = "box"` / `"violin"`.
- **Chemin des données** — chaque ligne du panier alimente son
  tableau brut `finite_values` (déjà produit par
  `_build_continuous_trace`) dans une seule trace. Pour
  boxplot/violon, le calcul des classes (bins) est ignoré ; Plotly
  gère le calcul des quartiles / KDE côté client.
- **Cas limite** — propriétés discrètes / catégorielles : masquer
  les boutons boxplot/violon via `v_if=!is_discrete`. Bars + line
  ont du sens ; box non.

### 2. Visualisation heatmap sur Compare-stats

- **Pourquoi** — le panneau Compare-stats actuel rend une matrice
  métrique × élément sous forme de tableau. Une heatmap montre la
  même matrice avec l'intensité de couleur = magnitude relative, ce
  qui repère les motifs plus vite sur des paniers plus grands
  (10+ éléments).
- **Où** — nouvelle bascule dans la barre d'outils Compare-stats :
  `View: table | heatmap`. Lorsque `heatmap` est sélectionné, le
  panneau remplace le `<table>` par une figure Plotly `go.Heatmap`
  avec les métriques en Y, les éléments en X, valeur = z (ou
  normalisée en z-score).
- **Backend** — déjà à moitié fait :
  `compare_matrix.highlight_annotations` produit l'intensité
  normalisée par métrique utilisée par l'ancien mode heatmap au
  niveau cellule (abandonné). Réutiliser cette intensité pour
  alimenter une heatmap Plotly.
- **État** — ajouter `ui_stats_compare_view_<panel_id>` ∈
  `{"table", "heatmap"}` par panneau.
- **Pourquoi distinct du mode heatmap abandonné du Tier 1** — la
  peinture heatmap par cellule du Tier 1 était trop contrainte par
  la sémantique des cellules de tableau (texte superposé vs dégradé
  d'arrière-plan). Un canevas heatmap Plotly dédié offre une vraie
  barre de couleurs + libellés d'axes + zoom + infobulles au survol,
  ce que l'approche peinture-cellule ne pouvait pas.

### 3. Visualisation graphique radar sur Compare-stats

- **Pourquoi** — pour caractériser un élément sur N métriques à la
  fois. Chaque ligne du panier devient un polygone sur N axes
  (= métriques visibles) ; les polygones superposés rendent les
  valeurs aberrantes évidentes.
- **Où** — nouvelle option de bascule dans le même sélecteur de vue
  que la heatmap : `View: table | heatmap | radar`. Utilise Plotly
  `go.Scatterpolar` (une trace par élément).
- **Cas limite** — le radar nécessite des échelles d'axes
  comparables. Normaliser chaque métrique en z-score avant le tracé
  (réutiliser le chemin de normalisation construit pour la heatmap
  de cellule abandonnée), sinon les métriques à grande magnitude
  dominent la forme du polygone.
- **UX** — limiter à ≤ 6-8 éléments dans le panier pour rester
  lisible ; sur des paniers plus grands, masquer automatiquement
  certaines traces avec un sélecteur de chips.

---

## Tier 3 — Pro-statistique (différé, doc uniquement)

Consigné comme des idées qui méritent d'être revisitées si des
utilisateurs avancés les demandent. Effort lourd, audience étroite.
Ne pas les intégrer sans demande explicite.

### Tests statistiques

- **Test t de Student** entre deux éléments quelconques : différence
  des moyennes significative ou non, avec p-value.
- **Test de Levene** pour l'égalité des variances.
- **Kolmogorov-Smirnov** pour la comparaison de forme de
  distribution.
- **UI** — sélectionner par paire deux éléments du panier, cliquer
  sur "Test", obtenir une petite modale montrant le nom du test +
  p-value + verdict (✓ / ✗).
- **Backend** — imports scipy.stats. Ajouter une fonction utilitaire
  `compare_matrix.run_pairwise_tests(items, baseline_key)`.

### Métriques de distance

- **Distance de Wasserstein** entre distributions (EMD 1D).
- **Divergence KL** avec lissage.
- **UI** — matrice par paire ou une colonne "distance à la baseline"
  ajoutée au tableau Compare-stats lorsqu'une baseline est définie.
- **Backend** — scipy.stats / scipy.spatial.

### Classement par similarité

- "La ligne A est similaire à 92% à la ligne B" — calculer via un
  embedding à l'échelle du panier (cosinus sur des vecteurs de
  métriques normalisés). Afficher sous forme de liste triée sous
  chaque ligne.
- Probablement excessif mais listé par souci d'exhaustivité.

### Détection des valeurs aberrantes

- Mettre en évidence les éléments qui sont à > 2σ de la moyenne par
  métrique du panier sur N métriques ou plus. Ajoute une chip de tag
  sur le libellé de colonne.
- Pourrait réutiliser l'emplacement de la chip de profil de
  distribution (montre actuellement symétrique / queue lourde).

### Suggestions automatiques

- "Cette ligne a une variance anormalement élevée" — des indices
  tranchés pilotés par seuil dans un panneau latéral.
- Risque élevé de dire des bêtises ; à éviter jusqu'à ce qu'un vrai
  cas d'usage l'exige.

---

## Suivis du Tier 1 (petits correctifs à envisager)

Ceux-ci ont été remarqués pendant les travaux du Tier 1 mais non
implémentés dans la même série. Faciles à intégrer dans une branche
de maintenance.

- **Panneau Compare-distribution : rognage du libellé de légende** —
  vérifier que la légende affiche `real X, ts_label` uniquement (pas
  le nom de la propriété + le titre de la vue). Le travail pour les
  libellés de colonnes Compare-stats l'a déjà fait côté serveur ;
  revérifier que Compare-distribution le reprend aussi.

- **Retour visuel du glisser-déposer pour réordonner** —
  actuellement seul `cursor: move` suggère la possibilité de
  glisser. Ajouter un contour `:hover` ou un indicateur de cible de
  dépôt en pointillés sur `dragover`.

- **Remplacement du Top-N via une affordance "more"** — le filtre
  Top-N a été abandonné suite aux retours utilisateurs (le défilement
  horizontal gère le débordement). Si un utilisateur se plaint de
  paniers trop chargés, envisager une bascule "réduire au top 5 par
  Moyenne" qui masque le reste derrière un expandeur.

- **Nommage de l'export CSV** — actuellement `compare.csv` pour chaque
  téléchargement. Intégrer `<property_title>` dans le nom de fichier
  pour que le navigateur n'écrase pas les téléchargements précédents.

- **Figé pour la Disposition B (transposée)** — le figé à gauche
  n'était câblé que pour la Disposition A (éléments en colonnes).
  Dans la Disposition B (éléments en lignes), les en-têtes de
  métriques vont horizontalement et les libellés de lignes vont
  verticalement. Une combinaison en-tête figé en haut + libellé de
  ligne figé à gauche refléterait la sensation tableur.

---

## Hors périmètre (coupes intentionnelles)

- **Filtrage avancé (seuils de plage / variance / quartile)** —
  chevauchement avec le tri + la sélection manuelle du panier.
- **Regroupement / clustering** — flux de travail différent, mérite
  son propre panneau.
- **Export de rapport PDF** — le CSV suffit pour l'instant ; le PDF
  ajoute une dépendance de templating.
- **Infobulles avec mini-histogrammes** — chaque infobulle
  déclencherait un aller-retour de calcul. Ne vaut pas la latence
  pour une infobulle.
