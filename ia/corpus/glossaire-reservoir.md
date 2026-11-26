# Glossaire du réservoir et de RESQML (glossary of reservoir modelling and RESQML)

Notions que les utilisateurs de fespp_on_trame nomment, en français et en anglais, avec ce qu'elles sont dans un modèle RESQML et dans l'application. Rédigé le 28/09/2026 pour l'assistant ; à faire relire par un géologue : ce sont des définitions générales, pas la doctrine d'un projet.

## Grille et géométrie (grid and geometry)

### Grille IJK (IJK grid, IjkGridRepresentation)
Une grille structurée en trois indices : I et J dans le plan (les colonnes), K en profondeur (les couches). Chaque maille est un hexaèdre défini par ses huit coins. C'est la grille des simulateurs de réservoir (Eclipse, Petrel) ; dans RESQML c'est une IjkGridRepresentation, à géométrie explicite (tous les coins donnés) ou paramétrique (les coins portés par des piliers).

### Pilier (pillar)
Dans une grille IJK, un pilier est la ligne (droite, ou courbe paramétrique) qui joint les coins d'une colonne de mailles du toit à la base : les nœuds de la grille sont placés le long des piliers, un par couche. Une grille « à piliers » (pillar grid, corner-point grid) est décrite par ses piliers et, pour chaque pilier, la position des nœuds de chaque couche. Un pilier vertical donne des colonnes droites ; un pilier incliné suit une faille. Dans fesapi : IjkGridParametricRepresentation, « pillar information », pillar kind (vertical, straight, curved).

### Colonne (column)
L'ensemble des mailles d'une grille IJK qui ont les mêmes indices I et J, du toit à la base : une pile de mailles selon K, bordée par quatre piliers.

### Couche (layer)
Les mailles d'une grille IJK qui ont le même indice K : une tranche horizontale du modèle, souvent une unité stratigraphique ou une subdivision de celle-ci.

### Maille, cellule (cell)
L'élément de volume élémentaire d'une grille : dans une grille IJK, un hexaèdre à huit coins ; dans une grille non structurée, un polyèdre quelconque. Une propriété de grille porte une valeur par maille. Une maille « morte » ou inactive (dead cell, inactive cell) est exclue du calcul ; fespp_on_trame la masque via vtkGhostType.

### Grille non structurée (unstructured grid, UnstructuredGridRepresentation)
Une grille dont les mailles sont des polyèdres décrits par leurs faces et leurs nœuds, sans indices I J K : maillages tétraédriques, prismatiques, ou hybrides.

### Nœud, coin (node, corner point)
Un sommet de maille. Dans une grille à piliers, un nœud est repéré par son pilier et sa couche ; une maille a huit coins (corner points) et une colonne en partage avec ses voisines, sauf le long d'une faille où la géométrie est dédoublée (split nodes).

### Grille 2D (Grid2dRepresentation)
Une surface régulière en (i, j) portant une élévation : un horizon ou une carte, maillée en cellules rectangulaires.

### Surface triangulée (TriangulatedSetRepresentation)
Une surface faite de triangles : horizon interprété, faille, toit ou base d'un réservoir.

### Polyligne (PolylineRepresentation, PolylineSetRepresentation)
Une ligne brisée (ou un ensemble de lignes) : une trajectoire de puits, un contour, une faille en carte.

### Nuage de points (PointSetRepresentation)
Un ensemble de points sans connexion : des picks, des pointés sismiques, des points de contrôle.

## Objets géologiques (geological objects)

### Horizon
Une surface géologique qui suit une limite de temps ou de couches : le toit (top) ou la base (base) d'une formation. Dans RESQML, une HorizonInterpretation portée par une surface (Grid2d ou triangulée).

### Faille (fault)
Une cassure des couches avec déplacement. Dans RESQML, une FaultInterpretation portée par une surface ; dans une grille à piliers, une faille se voit par des piliers inclinés ou des nœuds dédoublés (split pillars).

### Chenal (channel, fluvial channel)
Un corps sédimentaire allongé et sinueux déposé par une rivière : un chenal est en général du sable (bon réservoir) entouré d'argiles de plaine d'inondation. Dans un modèle de faciès, les chenaux sont une catégorie de faciès (« channel sand ») répartie dans la grille ; on les voit en filtrant ou en surlignant les mailles de cette catégorie. À ne pas confondre avec le « channel » de WITSML, qui est une courbe de diagraphie (voir Log).

### Faciès (facies)
Une classe de roche définie par ses caractères sédimentaires (sable de chenal, argile, calcaire…). Dans un modèle, une propriété catégorielle (codes entiers, noms dans un lookup) portée par les mailles de la grille ou par un log de puits.

### Lithologie (lithology)
La nature de la roche : grès (sandstone), argile (shale), silt (siltstone), calcaire (limestone), charbon (coal)… Souvent une propriété catégorielle (Lithology1 sur Volve).

### Zone, unité (zone, unit)
Une subdivision du réservoir, en général un intervalle de couches K, ou un volume défini par une valeur (la « zone à huile » : les mailles où le fluide est l'huile). Dans RESQML une zone peut être une sous-représentation (SubRepresentation) qui liste les mailles concernées.

### Contact (fluid contact)
La surface qui sépare deux fluides dans le réservoir : contact huile–eau (OWC, oil-water contact), contact gaz–huile (GOC), contact gaz–eau (GWC). Une profondeur, souvent plane ; l'outil Volumetrics de fespp_on_trame l'utilise pour compter les volumes au-dessus et au-dessous.

### Réservoir (reservoir)
La roche poreuse et perméable qui contient les hydrocarbures. Aquifère (aquifer) : la zone à eau sous le contact.

### Compartiment (compartment)
Une partie du réservoir isolée des autres par des failles ou des barrières : sur Volve, des sous-représentations « Compartment_1… ».

## Puits (wells)

### Puits, forage (well, wellbore)
Le trou foré. Dans RESQML/WITSML un WellboreFeature avec ses représentations : la trajectoire, les logs (frames), les marqueurs, les complétions.

### Trajectoire (wellbore trajectory)
Le chemin du puits dans l'espace, une polyligne de points (x, y, z) repérés par la profondeur mesurée (MD, measured depth) le long du trou. Une trajectoire verticale, déviée ou horizontale.

### Log, diagraphie (well log, channel)
Une mesure le long du puits en fonction de la profondeur : gamma ray (GR), résistivité, densité (RHOB), porosité neutron, sonique… Dans WITSML un « channel » d'un ChannelSet ; dans RESQML un WellboreFrameRepresentation portant des propriétés. La vue Log de fespp_on_trame les trace.

### Marqueur (wellbore marker)
Un pointé le long du puits, à une profondeur MD : le passage d'un horizon ou d'une faille (« top Hugin à 3 200 m »). Un WellboreMarkerFrameRepresentation en porte plusieurs.

### Blocked wellbore, puits bloqué (BlockedWellboreRepresentation)
La liste des mailles de la grille traversées par la trajectoire, avec les entrées et sorties : le lien entre le puits et le modèle. Quand le fichier n'en a pas, fespp_on_trame calcule cette intersection par la géométrie (« les mailles traversées par les puits »).

### Complétion, perforation (completion, perforation)
L'équipement du puits et les intervalles ouverts à la production.

### Profondeur mesurée, verticale (MD, TVD)
MD : la longueur le long du trou depuis la surface ; TVD (true vertical depth) : la profondeur verticale vraie.

## Propriétés (properties)

### Propriété (property)
Une valeur par élément d'une représentation : une par maille de grille, un par nœud, ou une par pas de temps. Continue (ContinuousProperty : porosité, perméabilité), discrète (DiscreteProperty : entiers), catégorielle (CategoricalProperty : codes entiers avec un lookup de noms).

### Porosité (porosity, PHI, PHIT, PHIE)
La fraction du volume de roche occupée par les pores, entre 0 et 1 (ou en %). PHIT : porosité totale ; PHIE : porosité effective (les pores connectés).

### Perméabilité (permeability, PERMX, PERMY, PERMZ, k)
L'aptitude de la roche à laisser passer un fluide, en millidarcy (mD). Souvent trois composantes selon les axes ; la verticale est en général bien plus faible.

### Saturation (saturation, Sw, So, Sg)
La fraction du volume poreux occupée par un fluide : eau (Sw, water saturation), huile (So), gaz (Sg) ; leur somme vaut 1.

### Net to gross (NTG, net sur brut)
La fraction de l'épaisseur (ou du volume) qui est du réservoir utile (« net ») sur l'épaisseur totale (« gross »), entre 0 et 1 : 0,6 signifie que 60 % de la maille est de la roche réservoir.

### Gamma ray (GR)
La radioactivité naturelle mesurée dans le puits, en API : élevée dans les argiles, basse dans les sables et calcaires. Sert à distinguer les faciès.

### Densité (bulk density, RHOB)
La masse volumique de la roche mesurée dans le puits, en g/cm³.

### Volume d'argile (shale volume, Vsh)
La fraction d'argile de la roche, déduite du gamma ray.

### Série temporelle (time series)
Une propriété qui a une valeur par pas de temps (time step) : les saturations d'une simulation au fil de la production. Dans fespp_on_trame, la carte Temps/Réalisations choisit le pas de temps affiché.

### Réalisation (realization)
Une version d'une propriété issue d'une simulation stochastique : plusieurs réalisations d'un même faciès ou d'une porosité, également probables ; une propriété multi-réalisations en porte plusieurs.

### Propriété dérivée (derived property)
Dans fespp_on_trame, une propriété calculée par la Calculatrice à partir d'autres (« OilSat__t5 - OilSat__t0 ») : elle sert aux statistiques et aux graphiques, elle n'est pas dessinée dans la vue 3D.

### Genre de propriété (property kind, PWLS)
Le sens d'une propriété (porosity, permeability, saturation…) pris dans le dictionnaire PWLS d'Energistics, organisé en arbre : « total porosity » est une porosité.

## Le standard (the standard)

### RESQML
Le standard Energistics d'échange des modèles de sous-sol : géométries (grilles, surfaces), propriétés, puits, interprétations et features, dans un paquet EPC (un zip de fichiers XML) plus un fichier HDF5 pour les tableaux de valeurs.

### EPC
Le conteneur : une archive zip de parties XML (une par objet, identifié par un UUID) et de relations.

### HDF5
Le fichier binaire qui porte les grands tableaux (coordonnées, valeurs de propriétés) référencés par les XML.

### Feature, interprétation, représentation (feature, interpretation, representation)
Les trois niveaux de RESQML : la feature est l'objet géologique (un horizon, une faille, un puits), l'interprétation en est une lecture (cette faille est normale), la représentation en est la géométrie (cette surface triangulée). Une propriété s'attache à une représentation.

### Sous-représentation (SubRepresentation)
Une liste d'éléments (mailles, faces, nœuds) d'une représentation existante : une zone, un compartiment, les mailles d'une région, sans copier la géométrie.

### UUID, citation
Chaque objet a un identifiant unique (UUID) et une citation (titre, auteur, dates de création et de mise à jour, format).

### WITSML, PRODML
Les standards frères d'Energistics : WITSML pour les puits (trajectoires, logs, marqueurs), PRODML pour la production.

### ETP (Energistics Transfer Protocol)
Le protocole d'échange en direct avec un serveur (WebSocket) : lire un dataspace sans passer par un fichier EPC. fespp_on_trame s'y connecte par l'onglet OSDU/ETP.

### fesapi, fetpapi, FESPP
fesapi : la bibliothèque C++ qui lit et écrit RESQML ; fetpapi : sa jumelle pour ETP ; FESPP : le plugin ParaView qui, avec fesapi, transforme les objets en données VTK. fespp_on_trame : l'application web (trame) bâtie sur ParaView et FESPP.

## L'application (the application)

### Seuil, filtre (threshold)
Ne garder que les mailles dont la valeur d'une propriété est dans une plage (ou d'une catégorie donnée) : les autres disparaissent de la vue. Plusieurs seuils s'enchaînent (une intersection).

### Surbrillance (highlight)
Allumer les mailles qui vérifient une condition sans rien cacher : une sélection d'identifiants dessinée par-dessus la grille.

### Coupe (slice), tranches IJK
Couper la grille selon un plan ou ne montrer qu'une tranche d'indices I, J ou K.

### Isolat (isolate)
Ne montrer qu'un objet, ou la grille seule, les autres cachés.

### Table de couleurs (colormap, colour table)
La correspondance valeur → couleur d'une propriété (viridis, jet, turbo…), avec sa plage ; une propriété catégorielle a une palette par code.

### Exagération verticale (vertical exaggeration, Z scale)
Multiplier l'axe vertical pour rendre lisibles des couches minces.

### Vue Globe (Globe view)
La projection des données sur la Terre, quand le système de coordonnées (CRS, code EPSG) est connu.

### Volumétrie (volumetrics)
Le calcul des volumes de roche, de pores et d'hydrocarbures d'une grille à partir de la porosité, du NTG et des saturations, au-dessus des contacts.

### Statistiques, distribution, cross-plot (statistics, histogram, cross-plot)
Les panneaux qui résument une propriété (moyenne, min, max, médiane, P10, P90), tracent son histogramme, ou comparent deux propriétés point par point.

### Santé des données (data health)
Le panneau qui vérifie les objets chargés : bornes déclarées et réelles, CRS, journal VTK, nœuds sans géométrie.

### Session
L'état de l'application (fichiers, sélection, yeux des vues, tables de couleurs, panneaux) sauvegardé dans un fichier .fespp.json et restauré ensuite.
