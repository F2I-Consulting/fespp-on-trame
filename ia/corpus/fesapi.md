# fesapi — la bibliothèque

Source : documentation rédigée pour fespp_on_trame à partir des sources du projet fesapi (F2I Consulting, licence Apache-2.0), version 2.14.0.0.

### Ce qu'est fesapi (what fesapi is)
fesapi est une bibliothèque C++ open source qui aide un logiciel à importer et exporter des données RESQML, et en partie WITSML et PRODML : XML Energistics par gSOAP, paquet EPC par minizip, tableaux HDF5 par la bibliothèque HDF5 officielle, construction CMake. Dans fespp_on_trame, elle est liée au plugin FESPP, qui lit avec elle les EPC (et, avec fetpapi, les dataspaces ETP) puis en fait des données VTK. Voir RESQML, EPC et HDF5 dans le glossaire.

fesapi is an open-source C++ library that helps software import and export RESQML, and partly WITSML and PRODML: Energistics XML via gSOAP, EPC via minizip, HDF5 via the official library, CMake build. In fespp_on_trame it is linked into the FESPP plugin, which reads EPC files (and, with fetpapi, ETP dataspaces) and turns them into VTK data.

### Standards, versions et langages (standards, versions and languages)
Le dépôt connaît RESQML 2.0.1 et 2.2, EML 2.0 et 2.3, WITSML 2.1 et PRODML 2.3 (EnergisticsStandard) ; setDefaultStandard fixe la version des objets créés. RESQML 2.2 est expérimental (option CMake WITH_RESQML2_2, « à ne pas utiliser en production »). La 2.14.0.0, celle que construit l'image de fespp_on_trame, demande un compilateur C++17. SWIG génère des liaisons Python 3, Java et C# ; un paquet Python est publié sur PyPI : import fesapi, tableaux par fesapi.DoubleArray(n).

The repository knows RESQML 2.0.1 and 2.2, EML 2.0 and 2.3, WITSML 2.1 and PRODML 2.3; setDefaultStandard sets the version of created objects. RESQML 2.2 is experimental (WITH_RESQML2_2, "don't use it in production"). Version 2.14.0.0, built by the fespp_on_trame image, needs C++17. SWIG generates Python 3, Java and C# wrappers; a Python package is on PyPI.

### Paquet EPC (EpcDocument)
EpcDocument ouvre un .epc, en verse objets et relations dans un dépôt (deserializeInto rend une chaîne vide, ou le texte des avertissements) ou l'écrit depuis un dépôt (serializeFrom). deserializePartiallyInto ne crée que des objets partiels. Un objet que gSOAP ne valide pas (un genre de propriété hors énumération, par exemple) est ignoré avec un avertissement, sans arrêter le chargement. Les classes Package, FilePart, Relationship et ContentType gèrent le zip.

EpcDocument opens an .epc, loads its objects and relationships into a repository (deserializeInto returns an empty string or the warnings) or writes it from a repository (serializeFrom). deserializePartiallyInto creates partial objects only. An object gSOAP cannot validate is ignored with a warning; loading goes on.

### Proxy HDF5 (AbstractHdfProxy)
Les grands tableaux sont hors des XML : un EpcExternalPartReference désigne le fichier HDF5, qu'un proxy HDF (AbstractHdfProxy, implémenté par HdfProxy) lit et écrit, en entier ou par hyperslab, sans compression par défaut. Si le .h5 désigné manque, HdfProxy essaie <nom de l'epc>.h5 puis .hdf5. « The HDF5 dataset … could not be read » : fichier ouvert mais lecture refusée, souvent faute du filtre de compression dans le HDF5 lié. Le proxy se dérive (HdfProxyFactory) : MPI, S3 (ROS3), ETP avec fetpapi.

Large arrays live outside the XML: an EpcExternalPartReference names the HDF5 file, read and written by an HDF proxy (HdfProxy), whole or by hyperslab, uncompressed by default. A missing .h5 falls back to <epc name>.h5 then .hdf5. "could not be read" often means a missing compression filter. Proxies can be derived: MPI, S3, ETP.

### Dépôt d'objets (DataObjectRepository)
DataObjectRepository est le conteneur en mémoire des objets lus d'un EPC ou reçus par ETP, et de ceux à écrire ou à pousser vers un store. Ce n'est pas une base de données : il crée et détruit les objets qu'il contient et ne garde que leurs définitions XML, pas les valeurs numériques. Il tient leurs relations, un CRS et un proxy HDF par défaut (setDefaultCrs, setDefaultHdfProxy) et les avertissements (getWarnings). Un constructeur prend un dossier de ressources.

DataObjectRepository is the in-memory container of objects read from EPC files or fetched over ETP, and of those to write or push. It is not a database: it owns its objects and keeps only their XML definitions, not numerical values. It keeps relationships, a default CRS and HDF proxy, and warnings. One constructor takes a resource directory.

### Trouver un objet dans le dépôt (getting objects)
Par uuid : getDataObjectByUuid, dont la version typée lève une exception si le type ne correspond pas. Par type : getDataObjects<T>() en C++, ou les accès nommés getIjkGridRepresentationSet, getWellboreTrajectoryRepresentationSet, getLocal3dCrsSet… avec leurs variantes Count et index (utiles en SWIG), et des filtres par interprétation (getHorizonGrid2dRepresentationSet, getFaultTriangulatedSetRepresentationSet). Aussi getDataObjectsByContentType, getDataObjectsGroupedByDataType, getUuids.

By uuid: getDataObjectByUuid, whose typed version throws on a type mismatch. By type: getDataObjects<T>() in C++, or named getters such as getIjkGridRepresentationSet or getLocal3dCrsSet, with Count and index variants, and interpretation filters. Also getDataObjectsByContentType and getUuids.

### Objet et relations (AbstractObject and relationships)
Tout objet dérive d'AbstractObject : uuid, titre, dates, version (voir UUID, citation) ; getXmlTag et getQualifiedType donnent son type, serializeIntoString son XML, getExtraMetadata ses métadonnées libres, buildEtp12Uri son URI ETP 1.2. Le dépôt tient les références dans les deux sens : getTargetObjects (ce que l'objet désigne), getSourceObjects (ce qui le désigne). D'une représentation on va à ses propriétés (getPropertySet), à son interprétation (getInterpretation), puis à la feature (getInterpretedFeature).

Every object derives from AbstractObject: uuid, title, dates, version; getXmlTag gives its type, serializeIntoString its XML, buildEtp12Uri its ETP 1.2 URI. getTargetObjects and getSourceObjects give references both ways; getPropertySet, getInterpretation and getInterpretedFeature walk from a representation.

### Objet partiel (partial object)
Un objet partiel ne connaît que son type, son uuid et son titre : une simple référence vers un objet absent du dépôt, jamais un fichier du paquet. fesapi en crée quand un objet chargé en référence un qui manque ; isPartial le signale, et bien des accès typés lèvent alors une exception. resolvePartial peut le compléter par un DataFeeder enregistré. createPartialIjkGridRepresentation permet d'attacher une propriété à une grille absente.

A partial object only knows its type, uuid and title: a reference to an object missing from the repository, never a package file. fesapi creates one when a loaded object references a missing one; isPartial tells it, and many typed accessors then throw. resolvePartial can complete it through a registered DataFeeder.

### Features et interprétations (features and interpretations)
Les trois couches sont décrites à l'entrée Feature, interprétation, représentation du glossaire. Features : BoundaryFeature (horizon, faille), RockVolumeFeature, WellboreFeature, CulturalFeature (limite arbitraire du modèle), features sismiques (SeismicLatticeFeature, SeismicLineSetFeature). Interprétations : HorizonInterpretation, FaultInterpretation, WellboreInterpretation, GeobodyInterpretation, GenericFeatureInterpretation (feature de type inconnu).

Features: BoundaryFeature (horizon, fault), RockVolumeFeature, WellboreFeature, CulturalFeature (arbitrary model boundary), seismic features. Interpretations: HorizonInterpretation, FaultInterpretation, WellboreInterpretation, GeobodyInterpretation, GenericFeatureInterpretation (unknown feature type).

### Organisations et cadres (organizations and frameworks)
EarthModelInterpretation rassemble des organisations stratigraphique, structurale et roche-fluide cohérentes entre elles. StructuralOrganizationInterpretation regroupe horizons, failles, frontières et leurs contacts ; RockFluidOrganizationInterpretation décrit le réservoir et ses unités fluides. Les cadres SealedSurfaceFrameworkRepresentation, NonSealedSurfaceFrameworkRepresentation et SealedVolumeFrameworkRepresentation dérivent de RepresentationSetRepresentation.

EarthModelInterpretation gathers consistent stratigraphic, structural and rock-fluid organizations. StructuralOrganizationInterpretation groups horizons, faults, frontiers and their contacts; RockFluidOrganizationInterpretation describes the reservoir and its fluid units. The sealed and non-sealed frameworks derive from RepresentationSetRepresentation.

### Grilles IJK : quatre géométries (IJK grids: four geometries)
Voir Grille IJK et Pilier dans le glossaire. getGeometryKind distingue : IjkGridExplicitRepresentation, chaque coin en XYZ ; IjkGridParametricRepresentation, coins placés par paramètres le long des piliers ; IjkGridLatticeRepresentation, régulière, surtout pour les cubes sismiques ; IjkGridNoGeometryRepresentation, sans géométrie (grille centrée mailles, raffinement local). AbstractIjkGridRepresentation seule sert au transfert partiel.

getGeometryKind tells: IjkGridExplicitRepresentation, every corner in XYZ; IjkGridParametricRepresentation, corners set by parameters along pillars; IjkGridLatticeRepresentation, regular, mostly seismic cubes; IjkGridNoGeometryRepresentation, no geometry. AbstractIjkGridRepresentation alone serves partial transfer.

### Grilles IJK : piliers, failles, K gaps (IJK grids: pillars, faults, K gaps)
Les coins voisins ne sont pas répétés, sauf le long des lignes ou nœuds dédoublés (split) qui portent les failles (getSplitCoordinateLineCount). getMostComplexPillarGeometry rend la forme de pilier la plus complexe : verticale, droite ou courbe. getKGapsCount compte les vides entre couches K. getXyzPointsOfKInterface lit les nœuds d'une interface K, pour charger une grande grille par tranches.

Neighbouring corners are not repeated, except along split lines or nodes that carry faults (getSplitCoordinateLineCount). getMostComplexPillarGeometry returns the most complex pillar shape: vertical, straight or curved. getKGapsCount counts gaps between K layers. getXyzPointsOfKInterface reads the nodes of one K interface.

### Grilles non structurées et en couches (unstructured and column-layer grids)
UnstructuredGridRepresentation est « caractérisée par un nombre de mailles, et potentiellement rien d'autre » ; les formats de simulation anciens comme récents reposent sur elle (voir Grille non structurée). getFaceCountOfCell décrit ses polyèdres. AbstractColumnLayerGridRepresentation, parent des grilles IJK, rend par getIntervalStratigraphicUnitIndices l'unité stratigraphique de chaque couche K.

UnstructuredGridRepresentation is "characterized by a cell count, and potentially nothing else"; both old and new simulation formats rely on it. getFaceCountOfCell describes its polyhedra. AbstractColumnLayerGridRepresentation, parent of IJK grids, gives the stratigraphic unit of each K layer via getIntervalStratigraphicUnitIndices.

### Surfaces, lignes et points (surfaces, polylines and point sets)
Grid2dRepresentation : surface régulière en (i, j). TriangulatedSetRepresentation : triangles liés par nœuds et arêtes. PlaneSetRepresentation : plans horizontaux ou inclinés, un contact de fluide par exemple. PolylineRepresentation : une polyligne ouverte ou fermée ; PolylineSetRepresentation : plusieurs, rangées par patch. PointSetRepresentation : patches de points XYZ sans lien. Voir Grille 2D, Surface triangulée, Polyligne et Nuage de points dans le glossaire.

Grid2dRepresentation: regular (i, j) surface. TriangulatedSetRepresentation: triangles linked by nodes and edges. PlaneSetRepresentation: flat or tilted planes, such as a fluid contact. PolylineRepresentation: one open or closed polyline; PolylineSetRepresentation: several, by patch. PointSetRepresentation: unconnected XYZ points.

### Puits et trajectoire (wellbore and trajectory)
WellboreFeature désigne un puits, un trou foré ou un sidetrack ; WellboreInterpretation en est une lecture, relative à une trajectoire. WellboreTrajectoryRepresentation est une ligne paramétrée par la MD (getMdValues). Le zéro de la MD est un MdDatum (getMdDatum), placé dans un CRS qui peut différer de celui de la trajectoire. DeviationSurveyRepresentation (RESQML 2.0.1) garde les stations d'un levé de déviation, qui ne fixent pas à elles seules la trajectoire.

WellboreFeature is a wellbore, borehole or sidetrack; WellboreInterpretation is an opinion of it. WellboreTrajectoryRepresentation is a line parameterized by MD (getMdValues). The MD zero is an MdDatum, possibly in another CRS. DeviationSurveyRepresentation (RESQML 2.0.1) keeps survey stations, which alone do not fix the trajectory.

### Cadres de puits et marqueurs (wellbore frames and markers)
WellboreFrameRepresentation organise des valeurs le long d'une trajectoire (getWellboreTrajectory) par leurs MD : les propriétés s'attachent aux points ou aux intervalles ; c'est le support des logs RESQML (voir Log, diagraphie). WellboreMarkerFrameRepresentation est un cadre dont chaque entrée est un WellboreMarker, un par MD, dans l'ordre de ses nœuds ; un marqueur peut nommer sa limite (getBoundaryFeatureInterpretation).

WellboreFrameRepresentation organizes values along a trajectory by MD: properties attach to points or intervals; it carries RESQML logs. WellboreMarkerFrameRepresentation is a frame whose entries are WellboreMarker objects, one per MD, in node order; a marker may reference its boundary interpretation.

### Puits bloqué (BlockedWellboreRepresentation)
BlockedWellboreRepresentation localise, sur une ou plusieurs grilles existantes ou prévues, l'intersection des mailles et des faces avec une trajectoire (voir Blocked wellbore dans le glossaire). getCellIndices rend des indices plats de mailles de la grille support : le même espace d'indices qu'une sous-représentation de mailles. getCellCount donne leur nombre.

BlockedWellboreRepresentation locates, on one or several grids, the intersection of cells and faces with a trajectory, existing or planned. getCellIndices returns flat cell indices of the supporting grid: the same index space as a cell sub-representation. getCellCount gives their count.

### Sous-représentation et connexions (SubRepresentation, GridConnectionSetRepresentation)
SubRepresentation est une liste ordonnée d'éléments indexables (nœuds, arêtes, faces, mailles) ou de paires d'éléments d'une représentation existante, sans copier sa géométrie ; getElementIndicesOfPatch rend ces indices. GridConnectionSetRepresentation liste des connexions (grille, maille, face) ⇔ (grille, maille, face) : le moyen préféré de porter les failles sur une grille, sans distinguer connexions standard et non standard.

SubRepresentation is an ordered list of indexable elements, or element pairs, of an existing representation, without copying geometry. GridConnectionSetRepresentation lists (grid, cell, face) ⇔ (grid, cell, face) connections: the preferred way to carry faults on a grid, with no standard vs non-standard distinction.

### Ensembles et lignes de courant (representation sets and streamlines)
RepresentationSetRepresentation regroupe des représentations en « sac », homogène ou non, sans cohérence géologique implicite : un ensemble de trajectoires, de cadres ou de puits bloqués. StreamlinesRepresentation porte des lignes de courant (getLineCount) ; StreamlinesFeature précise le champ tracé : flux d'une phase (eau, huile, gaz, total), d'un composant comme le CO2, ou température.

RepresentationSetRepresentation groups representations into a "bag", homogeneous or not, with no implied geological consistency. StreamlinesRepresentation carries streamlines; StreamlinesFeature names the traced field: phase flux (water, oil, gas, total), a component such as CO2, or temperature.

### Propriétés : les classes (property classes)
Une propriété (voir le glossaire) dérive d'AbstractProperty et s'attache à une représentation. ContinuousProperty : flottants avec une unité (getUomAsString). DiscreteProperty : entiers, souvent des index, sans noms. CategoricalProperty : entiers liés à une StringTableLookup (clé → chaîne, un faciès et son nom, par getStringLookup) ou à une DoubleTableLookup (réel → réel, table PVT). PointsProperty porte des points, CommentProperty des commentaires.

A property derives from AbstractProperty and attaches to a representation. ContinuousProperty: floats with a unit. DiscreteProperty: integers, often indices, without names. CategoricalProperty: integers tied to a StringTableLookup (key to string, such as a facies name) or a DoubleTableLookup (double to double, PVT). PointsProperty holds points, CommentProperty comments.

### Élément indexable et valeurs (indexable element and values)
getAttachmentKind rend l'élément qui porte les valeurs : mailles, nœuds, faces, arêtes, piliers… Plusieurs valeurs par élément (vecteur, tenseur) : getValueCountPerIndexableElement ; ce nombre est la dimension la plus rapide du HDF5, donc (nk, nj, ni, count) pour des mailles IJK. getArrayOfValuesOfPatch(patch, tampon), générique sur le type des valeurs, lit un patch et rend des statistiques (valeur nulle, minimum, maximum…) ; des lectures par hyperslab existent aussi.

getAttachmentKind returns the element carrying the values: cells, nodes, faces, edges, pillars… Several values per element: getValueCountPerIndexableElement, the fastest HDF5 dimension. getArrayOfValuesOfPatch(patch, buffer), generic on the value type, reads a patch and returns statistics; hyperslab reads also exist.

### Valeur nulle (null value)
Une propriété entière (discrète, catégorielle) déclare une valeur nulle pour les éléments non renseignés. Le plus sûr est de la lire dans les statistiques rendues par getArrayOfValuesOfPatch (getNullValue), valable en RESQML 2.0.1 comme en 2.2 ; getNullValueOfPatch ne marche qu'en 2.0.1. Par défaut c'est le plus grand entier du type ; les fichiers écrivent souvent 2147483647. Pour des flottants, la valeur nulle par défaut est NaN.

An integer property declares a null value for uncovered elements. Read it from the statistics returned by getArrayOfValuesOfPatch (getNullValue), valid for RESQML 2.0.1 and 2.2; getNullValueOfPatch only works on 2.0.1. The default is the type's largest integer, files often store 2147483647; for floats the default null is NaN.

### Genre de propriété (PropertyKind)
PropertyKind porte le sens des valeurs (voir Genre de propriété dans le glossaire). En RESQML 2.0.1, une propriété vise soit un genre standard Energistics (isAssociatedToOneStandardEnergisticsPropertyKind, getEnergisticsPropertyKind201 ; getPropertyKind rend alors nul), soit un PropertyKind local doté d'un parent (getPropertyKindParentAsString). En EML 2.3, getBaseUomAsString donne l'unité de base du genre, si le dictionnaire des unités est chargé.

PropertyKind carries the meaning of values. In RESQML 2.0.1 a property points either to a standard Energistics kind (getEnergisticsPropertyKind201; getPropertyKind is then null) or to a local PropertyKind with a parent. In EML 2.3, getBaseUomAsString gives the kind's base unit when the units dictionary is loaded.

### Fichiers de ressources (resource files)
Le dossier resources livre trois fichiers. Le constructeur de DataObjectRepository qui reçoit ce dossier lit Energistics_Unit_of_Measure_Dictionary_V1.0.xml, le dictionnaire des unités UOM 1.0 (environ 1 440 unités, 175 classes de grandeur), et PropertyKindMapping.xml, fichier propre à fesapi qui relie les genres standard 2.0.1 aux noms d'autres logiciels « en attendant PWLS ». Le dictionnaire PWLS v3.0 (environ 3 660 genres) n'est pas lu depuis ce dossier. FESPP cherche PropertyKindMapping.xml à côté de sa bibliothèque.

The resources folder ships three files. The DataObjectRepository constructor taking this folder reads the UOM 1.0 units dictionary and PropertyKindMapping.xml, a fesapi file mapping standard 2.0.1 kinds to other software names "waiting for PWLS support". The PWLS v3.0 dictionary is not read from there.

### Temps et réalisations (time series and realizations)
TimeSeries range une liste ordonnée d'instants (getTimestampCount, getTimestamp) pour des propriétés, géométries ou représentations qui varient dans le temps ; elle s'emploie avec un index de temps. Une propriété s'y rattache par setTimeSeries ou porte un instant unique (getSingleTimestamp) ; une représentation a getTimeIndex. Réalisations : hasRealizationIndices, getRealizationIndices. Voir Série temporelle et Réalisation.

TimeSeries stores an ordered list of times for time-dependent properties, geometries or representations, used with a time index. A property links to it (setTimeSeries) or holds a single timestamp (getSingleTimestamp). Realizations: hasRealizationIndices, getRealizationIndices.

### CRS locaux (local CRS)
Une géométrie est posée dans un CRS local ; toutes ces classes dérivent d'EML2_NS::AbstractLocal3dCrs et getLocal3dCrsSet les liste. RESQML 2.0.1 a LocalDepth3dCrs (profondeur) et LocalTime3dCrs (temps) ; RESQML 2.2 a LocalEngineeringCompoundCrs, un LocalEngineering2dCrs plus un VerticalCrs, isATimeCrs disant si l'axe vertical est un temps. Un CRS local a une origine, une rotation (getArealRotation) et un sens de Z (isDepthOriented). getXyzPointsOfAllPatchesInGlobalCrs rend les points dans le CRS global.

A geometry sits in a local CRS; all classes derive from EML2_NS::AbstractLocal3dCrs, listed by getLocal3dCrsSet. RESQML 2.0.1 has LocalDepth3dCrs and LocalTime3dCrs; RESQML 2.2 has LocalEngineeringCompoundCrs, a LocalEngineering2dCrs plus a VerticalCrs. getXyzPointsOfAllPatchesInGlobalCrs returns global coordinates.

### CRS projeté et vertical (projected and vertical CRS)
Les CRS projeté et vertical d'un CRS local sont donnés par code EPSG, par une définition WKT, ou déclarés inconnus avec une raison. Les lectures sont gardées : isProjectedCrsDefinedWithEpsg avant getProjectedCrsEpsgCode, isProjectedCrsDefinedWithWkt avant getProjectedCrsWkt, isProjectedCrsUnknown avant getProjectedCrsUnknownReason, de même pour le vertical ; sans son test, l'accès lève. À la création, une définition commençant par PROJCRS ou PROJCS (VERT) est un WKT, sinon la raison d'un CRS inconnu.

Projected and vertical CRS come as EPSG code, WKT, or unknown with a reason. Reads are guarded: test isProjectedCrsDefinedWithEpsg, …WithWkt or isProjectedCrsUnknown before the matching getter; an unguarded read throws. On creation, a definition starting with PROJCRS, PROJCS or VERT is WKT.

### Stratigraphie (stratigraphy)
StratigraphicColumn est l'interprétation globale de la stratigraphie, faite de rangs ordonnés par âge. Une StratigraphicColumnRankInterpretation tient une liste ordonnée de StratigraphicUnitInterpretation (getStratigraphicUnitInterpretationSet) et les contacts entre unités ; isAChronoStratiRank dit seulement que le rang est ordonné par âge. StratigraphicOccurrenceInterpretation décrit la stratigraphie le long d'un puits.

StratigraphicColumn is the global interpretation of stratigraphy, made of ranks ordered by age. A StratigraphicColumnRankInterpretation holds an ordered list of StratigraphicUnitInterpretation and the contacts between units; isAChronoStratiRank only says the rank is ordered by age. StratigraphicOccurrenceInterpretation describes stratigraphy along a wellbore.

### Flux de lecture type (typical read workflow)
EpcDocument pck(chemin) ; DataObjectRepository repo ; pck.deserializeInto(repo) — une chaîne non vide signale des avertissements, listés par repo.getWarnings ; pck.close(), le dépôt garde les objets et leurs proxys HDF. Puis parcourir par type (getIjkGridRepresentationCount, getIjkGridRepresentation(i), getLocal3dCrsSet) ou par uuid, tester isPartial, lire la géométrie (getXyzPointCountOfPatch, getXyzPointsOfPatch) et les propriétés (getPropertySet, getValuesCountOfPatch, getArrayOfValuesOfPatch).

Open an EpcDocument, deserializeInto a DataObjectRepository (a non-empty string means warnings, see getWarnings), close the package: the repository keeps objects and HDF proxies. Then iterate by type or uuid, test isPartial, read geometry (getXyzPointsOfPatch) and properties (getArrayOfValuesOfPatch).

### Flux d'écriture type (typical write workflow)
EpcDocument et DataObjectRepository (setDefaultStandard pour viser RESQML 2.2) ; createHdfProxy(…, OVERWRITE) puis setDefaultHdfProxy ; createLocalDepth3dCrs (code EPSG ou définition WKT) puis setDefaultCrs ; créer features, interprétations, représentations et propriétés (create…) et pousser leurs tableaux (pushBackGeometryPatch, pushBackArray3dOfValues, avec la valeur nulle pour des entiers) ; fermer le proxy HDF ; serializeFrom. Pour compléter un paquet : deserializeInto en READ_WRITE, créer, serializeFrom.

Create the document and repository; createHdfProxy (OVERWRITE) and setDefaultHdfProxy; createLocalDepth3dCrs (EPSG or WKT) and setDefaultCrs; create objects and push their arrays (pushBackArray3dOfValues); close the HDF proxy; serializeFrom. To extend a package: deserializeInto in READ_WRITE, create, serializeFrom.
