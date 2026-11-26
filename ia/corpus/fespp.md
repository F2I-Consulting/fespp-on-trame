# FESPP — le plugin ParaView

Source : documentation rédigée pour fespp_on_trame à partir des sources du projet FESPP (F2I Consulting, licence Apache-2.0), version 3.3.1.

### Ce qu'est FESPP (what FESPP is)
FESPP (F2I Energistics Standard ParaView Plugin) est un plugin ParaView qui affiche des données Energistics, surtout RESQML, lues dans un paquet EPC ou sur un serveur ETP comme le RDDMS d'OSDU. Il lit les objets avec fesapi (et fetpapi pour ETP) puis les traduit en jeux de données VTK. Il sert dans ParaView et dans fespp_on_trame, qui charge le même plugin (dossier plugins/Fespp) et le pilote par ses proxys. Voir fesapi, fetpapi, FESPP dans le glossaire.

FESPP is a ParaView plugin that displays Energistics data, mainly RESQML, read from an EPC package or an ETP server such as the OSDU RDDMS. It reads objects with fesapi (and fetpapi for ETP) and turns them into VTK datasets. It is used in ParaView and in fespp_on_trame, which loads the same plugin and drives it through its proxies.

### Construction et dépendances (build and dependencies)
FESPP 3.3.1 se construit avec CMake contre fesapi 2.14 et un ParaView 5.13 ou plus récent, lié aux mêmes bibliothèques HDF5 que fesapi. Le support ETP, dit expérimental, demande fetpapi (0.2.0.0 au moins), Boost, Avro, OpenSSL et l'option WITH_ETP_SSL, désactivée par défaut. L'installation copie le dossier plugins/Fespp, les bibliothèques fesapi et PropertyKindMapping.xml à côté du plugin.

FESPP 3.3.1 builds with CMake against fesapi 2.14 and ParaView 5.13 or later linked to the same HDF5 as fesapi. ETP support, called experimental, needs fetpapi 0.2.0.0 or later, Boost, Avro, OpenSSL and the WITH_ETP_SSL option, off by default. Installation copies the plugins/Fespp folder, the fesapi libraries and PropertyKindMapping.xml.

### Les proxys du plugin (plugin proxies)
Energistics.xml déclare trois sources, EPCCollector, EPCReader (« Energistics Packaging Conventions (EPC) Reader ») et ETPsource (« ETP1.2 Store ») ; deux filtres, EnergisticsExtractor (« Extract Energistics block ») et EPCCollectorClone, copie légère (ShallowCopy) de la sortie d'un collector ; un writer, EPCWriter. Les sources rendent une vtkPartitionedDataSetCollection munie d'un vtkDataAssembly. fespp_on_trame tient un clone par vue de rendu.

Energistics.xml declares three sources (EPCCollector, EPCReader, ETPsource "ETP1.2 Store"), two filters (EnergisticsExtractor, and EPCCollectorClone, a shallow copy of a collector output) and one writer (EPCWriter). Sources output a vtkPartitionedDataSetCollection with a vtkDataAssembly. fespp_on_trame keeps one clone per render view.

### EPCReader (EPC reader)
EPCReader est l'entrée « fichier » de ParaView pour les *.epc. Sa seule propriété, FileName (« add file »), ne lit rien elle-même : le reader cherche la source « EPC Collector » de la session, la crée au besoin, et lui transmet chaque fichier par sa propriété Files. Tout le travail est donc fait par EPCCollector ; EPCReader n'a pas d'autre réglage (ni sélection ni hiérarchie).

EPCReader is ParaView's file entry for *.epc. Its only property, FileName ("add file"), reads nothing itself: the reader finds the session's "EPC Collector" source, creates it if needed, and hands it each file through its Files property. EPCCollector does all the work; EPCReader has no other setting.

### EPCCollector : fichiers et chargement (EPCCollector: files and loading)
EPCCollector verse les EPC dans un seul dépôt fesapi : chaque valeur poussée dans Files (propriété cachée) ajoute un fichier et les objets s'accumulent, mais Files ne garde que le dernier chemin poussé. Un chemin inexistant ne lève pas d'erreur. Chaque chargement change AssemblyTag. Après chaque exécution (RequestData), le collector ferme les proxys HDF5. fespp_on_trame le crée sous le nom « EPCCollector ».

EPCCollector loads EPC files into one fesapi repository: each value pushed into Files adds a file and objects accumulate, but Files only keeps the last path. A missing path raises no error. Each load changes AssemblyTag. After each RequestData the collector closes the HDF5 proxies. fespp_on_trame creates it as "EPCCollector".

### EPCCollector : sélection (EPCCollector: selection)
Selectors reçoit des chemins de l'assembly : seuls les objets sélectionnés sont lus et produits. Par défaut, un chemin inclut tous les descendants du nœud, comme le veut l'éditeur d'assembly de ParaView. Avec ExplicitSelection à 1, réglé par fespp_on_trame pour ses cases à cocher indépendantes, seul un nœud de regroupement propage : cocher une grille ne charge que sa géométrie, pas ses propriétés ; cocher un puits charge tout son contenu.

Selectors takes assembly paths: only selected objects are read and output. By default a path includes all descendants. With ExplicitSelection set to 1, as fespp_on_trame does, only grouping nodes propagate: checking a grid loads its geometry only, checking a wellbore loads everything under it.

### Hiérarchie de l'arbre (Tree Hierarchy, TreeHierarchyMode)
La propriété TreeHierarchyMode (« Tree Hierarchy ») d'EPCCollector choisit la forme de l'arbre : Flat (0, par défaut), représentations sous la racine ; By Interpretation (1), groupées sous leur interprétation ; By Feature and Interpretation (2), sous la feature puis l'interprétation. Changer de mode reconstruit l'assembly sur place depuis le dépôt déjà chargé, sans relire les fichiers.

EPCCollector's TreeHierarchyMode ("Tree Hierarchy") sets the tree layout: Flat (0, default), representations under the root; By Interpretation (1); By Feature and Interpretation (2). Changing it rebuilds the assembly in place from the loaded repository, without rereading files.

### Extraction d'un bloc (EnergisticsExtractor)
EnergisticsExtractor extrait de sa collection d'entrée le bloc désigné par ExtractPath, un chemin d'assembly. Le collector offre extractMode : 1 « Extract without copy » crée un tel filtre, qui suit les changements en amont ; 2 « Extract with copy » fait une copie figée, détachée du pipeline. fespp_on_trame utilise ExtractRepPath (crée le filtre ; son nom revient dans ExtractedRepProducerName) et RemoveExtractRepPath (le supprime).

EnergisticsExtractor extracts the block named by ExtractPath, an assembly path. The collector's extractMode 1 "Extract without copy" creates such a live filter; 2 "Extract with copy" makes a frozen, detached copy. fespp_on_trame uses ExtractRepPath and RemoveExtractRepPath.

### ETPsource : connexion (ETPsource: connection)
ETPsource lit un dataspace ETP. Propriétés : ETPUrl, OSDUDataPartition (en-tête data-partition-id, « osdu » par défaut), ETPTokenType (0 Bearer, par défaut, ou 1 Basic), ETPToken, et pour un proxy ProxyUrl, ProxyTokenType (Basic par défaut), ProxyToken. Connect ouvre la session avec l'en-tête « <type> <jeton> » et fait passer ConnectionTag de 1 à 0 ; Disconnect la ferme. ConnectionTag n'est pas remis à 1 quand le serveur coupe.

ETPsource reads an ETP dataspace. Properties: ETPUrl, OSDUDataPartition (data-partition-id header, "osdu" by default), ETPTokenType (0 Bearer, default, or 1 Basic), ETPToken, and ProxyUrl, ProxyTokenType, ProxyToken. Connect opens the session with "<type> <token>" and sets ConnectionTag from 1 to 0; it is not reset when the server drops.

### ETPsource : dataspaces (ETPsource: dataspaces)
Une fois connecté, AllDataspaceNames (ou DataspacesInfo) liste les URI des dataspaces, plus « eml:/// » ajouté à la fin ; NumberOfDataspaces les compte. Donner un dataspace à Dataspaces le charge dans le dépôt, de façon synchrone, et complète l'assembly. vtkETPSource n'est pas accessible en Python : fespp_on_trame (source « ETP12Store ») passe par les propriétés, force l'envoi de Dataspaces et n'y pousse jamais une chaîne vide.

Once connected, AllDataspaceNames lists the dataspace URIs plus a trailing "eml:///". Setting Dataspaces loads that dataspace synchronously and extends the assembly. vtkETPSource is not Python-wrapped: fespp_on_trame ("ETP12Store") drives it through properties and never pushes an empty string.

### EPCWriter (EPC writer)
EPCWriter écrit un .epc depuis une vtkUnstructuredGrid, ou depuis chaque grille non structurée d'une vtkPartitionedDataSetCollection (les autres types sont ignorés). Chaque grille devient une UnstructuredGridRepresentation ; chaque tableau de points ou de mailles, une ContinuousProperty (réels) ou une DiscreteProperty (entiers), vectorielle s'il a plusieurs composantes, d'unité Euc. Le HDF5 se nomme <epc>.h5. La documentation XML d'EPCWriter est une copie de celle du reader.

EPCWriter writes an .epc from a vtkUnstructuredGrid, or from each unstructured grid of a vtkPartitionedDataSetCollection. Each grid becomes an UnstructuredGridRepresentation; each point or cell array a ContinuousProperty (reals) or DiscreteProperty (integers), vector-valued if multi-component. The HDF5 file is <epc>.h5.

### Sortie et assembly (output and data assembly)
La sortie est une vtkPartitionedDataSetCollection : un jeu partitionné par objet sélectionné, nommé en général « titre(uuid) ». Son vtkDataAssembly est l'arbre présenté à l'utilisateur. Les noms de nœuds sont stables d'un chargement à l'autre : « _<uuid> » pour un objet, « _gridfolder_<uuid> », « _propsfolder_<uuid> », « _subrepfolder_<uuid> », « _feature_<uuid> », « _interp_<uuid> », « _multireal_<titre> ». Les identifiants numériques changent : on adresse un nœud par son chemin.

The output is a vtkPartitionedDataSetCollection: one partitioned dataset per selected object, usually named "title(uuid)". Its vtkDataAssembly is the tree shown to the user. Node names are stable across loads ("_<uuid>" for an object, "_gridfolder_<uuid>"…); numeric node ids are not: address nodes by path.

### Attributs des nœuds (node attributes)
Chaque nœud porte typeCode (le code TreeViewNodeType), type (le type fin tiré de la balise XML : IjkGrid, TriangulatedSet, Trajectory, Frame, Marker…), title (titre brut) et label (assaini). Une propriété ajoute propType (ContinuousProperty…), propertyKind (titre de l'objet PropertyKind, absent pour un genre standard 2.0.1), uom, minvalue, maxvalue, componentCount. La racine porte time<i> = date ISO de chaque pas de temps.

Each node carries typeCode (TreeViewNodeType code), type (fine type from the XML tag: IjkGrid, Trajectory, Frame…), title and label. A property adds propType, propertyKind (title of its PropertyKind object, absent for a standard 2.0.1 kind), uom, minvalue, maxvalue, componentCount. The root carries time<i> = ISO date of each time step.

### Codes des nœuds (TreeViewNodeType codes)
0 Unknown, 1 Collection, 2 Representation, 3 SubRepresentation, 4 Properties, 5 Wellbore, 6 WellboreTrajectory, 7 WellboreFrame, 8 WellboreChannel, 9 WellboreMarkerFrame, 10 WellboreMarker, 11 WellboreCompletion, 12 TimeSeries, 13 Realization, 14 Perforation, 15 Partial, 16 MultiRealization, 17 MultiRealizationTimeSeries, 18 Feature, 19 Interpretation, 20 BlockedWellbore, 21 GridContainer, 22 BlockedWellboreFolder, 23 PropertiesFolder, 24 SubRepresentationFolder, 25 WellboreLogsFolder, 26 WellboreMarkersFolder, 27 WellboreCompletionsFolder. Le code donne le rôle, la chaîne type la classe RESQML : le code 4 couvre les trois classes de propriétés.

The code gives the role, the type string the RESQML class: code 4 covers all three property classes. New codes are appended so existing values never change; TypeEnumXml publishes the table.

### Rôles et regroupements (MapperType and grouping nodes)
getMapperType classe chaque code : Folder ne dessine rien (dossiers, Collection, Wellbore, Partial) ; Data s'ajoute à la représentation parente (Properties, WellboreChannel, WellboreMarker, Perforation, TimeSeries, réalisations) ; Mapper a sa géométrie (Representation, SubRepresentation, WellboreTrajectory, BlockedWellbore) ; MapperSet est un ensemble (WellboreFrame, WellboreMarkerFrame, WellboreCompletion). isGroupingType marque les nœuds dont la sélection se propage ; PropertiesFolder n'en est pas, exprès.

getMapperType classes each code: Folder draws nothing; Data rides on the parent representation; Mapper has its own geometry; MapperSet is a set. isGroupingType marks nodes whose selection cascades; PropertiesFolder deliberately is not one. Both predicates are published in TypeEnumXml.

### Une grille dans l'arbre (a grid in the tree)
Une IjkGridRepresentation ou UnstructuredGridRepresentation est placée dans un dossier GridContainer (« _gridfolder_<uuid> ») qui ne dessine rien. Dedans : un dossier « properties » où la feuille de géométrie « _<uuid> », titrée « SolidColor », côtoie les propriétés ; un dossier « SubRep » pour ses sous-représentations ; un dossier « block wellbore » pour ses puits bloqués. Cocher un sous-objet n'entraîne donc jamais la grille entière. Une grille connue seulement par référence reçoit la même forme avec une feuille Partial.

An IJK or unstructured grid sits in a GridContainer folder that draws nothing, holding a "properties" folder (geometry leaf titled "SolidColor" next to the properties), a "SubRep" folder and a "block wellbore" folder. Checking a sub-object never pulls in the whole grid.

### Un puits dans l'arbre (a wellbore in the tree)
Le nœud Wellbore (la WellboreFeature, « _<uuid> ») est un dossier sans géométrie ni couleur. Sa trajectoire en est un enfant direct ; les cadres de logs sont sous « logs » (chaque log, un WellboreChannel), les cadres de marqueurs sous « markers » (un WellboreMarker par marqueur), les complétions WITSML sous « completions » (une Perforation par connexion). Les puits bloqués ne sont jamais sous le puits : ils sont rangés sous leur grille support.

The Wellbore node is a folder with no geometry. Its trajectory is a direct child; log frames sit under "logs", marker frames under "markers", WITSML completions under "completions". Blocked wellbores are never under the well: they sit under their supporting grid.

### Grilles vers VTK (grids to VTK)
ResqmlIjkGridToVtkExplicitStructuredGrid fait d'une grille IJK une vtkExplicitStructuredGrid ; les mailles sans géométrie définie sont masquées (BlankCell) et, en lecture multi-processus, la grille est découpée par couches K. ResqmlUnstructuredGridToVtkUnstructuredGrid fait une vtkUnstructuredGrid : chaque maille devient tétraèdre, prisme, pyramide, hexaèdre, prisme pentagonal ou hexagonal quand sa forme le permet, sinon polyèdre. Une grille non structurée sans géométrie n'est pas dessinée.

An IJK grid becomes a vtkExplicitStructuredGrid; cells without defined geometry are blanked and multi-process reads split it by K layers. An unstructured grid becomes a vtkUnstructuredGrid: each cell maps to a tetra, wedge, pyramid, hexahedron or prism when its shape allows, else a polyhedron.

### Surfaces, lignes et points vers VTK (surfaces, lines and points to VTK)
Grid2dRepresentation devient une vtkStructuredGrid dont les nœuds de Z NaN sont masqués ; TriangulatedSetRepresentation, un jeu partitionné d'une vtkPolyData par patch (« Patch N ») ; PolylineSetRepresentation et PolylineRepresentation, des vtkPolyData de vtkPolyLine qui respectent les polylignes fermées ; PointSetRepresentation, une vtkPolyData de vtkPolyVertex. Toutes les coordonnées sont prises dans le CRS global, Z inversé quand le CRS compte la profondeur vers le bas.

Grid2d becomes a vtkStructuredGrid with NaN-Z nodes blanked; a triangulated set one vtkPolyData per patch; polylines vtkPolyData of vtkPolyLine; point sets vtkPolyVertex. Coordinates come in the global CRS, Z negated for a depth-oriented CRS.

### Sous-représentations vers VTK (sub-representations to VTK)
Une SubRepresentation de mailles d'une grille IJK devient une vtkUnstructuredGrid des mailles listées (seules les mailles sont prises en charge, pas les paires d'éléments) ; sur une grille non structurée, des mailles donnent une vtkUnstructuredGrid et des faces une vtkPolyData. Les points sont ceux de la grille support, et les propriétés de mailles de la grille sont recopiées sur la sous-représentation. Le chemin IJK suppose des indices triés et sans doublon.

A cell SubRepresentation of an IJK grid becomes a vtkUnstructuredGrid of the listed cells; on an unstructured grid, cells give a vtkUnstructuredGrid and faces a vtkPolyData. Points are the supporting grid's, and its cell properties are mirrored onto the subset. The IJK path expects sorted, duplicate-free indices.

### Puits bloqués vers VTK (blocked wellbores to VTK)
ResqmlBlockedWellboreToVtkUnstructuredGrid fait d'une BlockedWellboreRepresentation une vtkUnstructuredGrid qui ne contient que les mailles traversées de la grille support, IJK ou non structurée, mais partage tous ses points : ses bornes sont celles de la grille entière. Le nœud porte cellIndices, cellCount, supportingGridUuid et trajectoryUuid ; les propriétés de mailles de la grille sont recopiées sur ces mailles.

A BlockedWellboreRepresentation becomes a vtkUnstructuredGrid holding only the supporting grid's crossed cells but sharing all its points, so its bounds are the whole grid's. The node carries cellIndices, cellCount, supportingGridUuid and trajectoryUuid; grid cell properties are mirrored.

### Trajectoires et logs vers VTK (trajectories and logs to VTK)
Une trajectoire devient une vtkPolyData, polyligne de ses stations, avec un tableau de points « MD » quand la MD est stockée. Un log (propriété d'un WellboreFrameRepresentation) devient un tube (vtkTubeFilter, 10 côtés) dont le rayon suit la valeur, avec un tableau de points au nom du log, un champ « MD » et un champ « <nom>_nanCount ». Une valeur NaN est écrite -0,0 (le tube ne supporte pas NaN), avec un avertissement.

A trajectory becomes a vtkPolyData polyline of its stations, with an "MD" point array when MD is stored. A log becomes a tube whose radius follows the value, with a point array named after the log, an "MD" field array and a "<name>_nanCount" field. NaN samples are written as -0.0, with a warning.

### Marqueurs et complétions vers VTK (markers and completions to VTK)
Chaque marqueur devient une vtkPolyData : un disque orienté par son pendage et sa direction de pendage quand il les a et que MarkerOrientation est actif, sinon une sphère ; MarkerSize règle la taille (10 par défaut). Il porte le tableau de mailles MarkerNameId, le champ MarkerNames et sa MD. Les perforations d'une complétion WITSML deviennent des tubes le long de la trajectoire avec un champ « Skin » ; il faut une trajectoire et son MdDatum.

Each marker becomes a disk oriented by dip and dip direction when available and MarkerOrientation is on, else a sphere; MarkerSize sets its size (10 by default). It carries MarkerNameId, MarkerNames and its MD. WITSML perforations become tubes along the trajectory with a "Skin" field.

### Propriétés vers tableaux VTK (properties to VTK arrays)
Une propriété de mailles (ou de triangles) devient un tableau de mailles, une propriété de nœuds un tableau de points ; tout autre élément indexable est refusé, comme un nombre de valeurs qui ne correspond pas. ContinuousProperty donne un vtkDoubleArray ; DiscreteProperty et CategoricalProperty avec StringTableLookup, un vtkDoubleArray où la valeur nulle devient NaN. Le nom du tableau est le titre privé des caractères hors [-.0-9A-Z_a-z] (« GR (gAPI) » donne « GRgAPI »).

Cell or triangle properties become cell arrays, node properties point arrays; other elements are refused. ContinuousProperty gives a vtkDoubleArray; DiscreteProperty and CategoricalProperty with a StringTableLookup a vtkDoubleArray whose null value becomes NaN. The array name is the title stripped of characters outside [-.0-9A-Z_a-z].

### Catégories et couleurs (categories and colours)
Pour une CategoricalProperty, la StringTableLookup est recopiée dans la table de couleurs ParaView : mode IndexedLookup, Annotations clé → nom et palette par défaut ; une DiscreteProperty n'a jamais de noms. Si un GraphicalInformationSet donne une table de couleurs au genre de la propriété, elle s'applique avec son min et son max. La commande ApplyColors applique à la vue active les couleurs par défaut lues pour les ensembles de représentations.

For a CategoricalProperty the StringTableLookup is copied into the ParaView lookup table (IndexedLookup, key → name Annotations, default palette); a DiscreteProperty never has names. A GraphicalInformationSet colour map attached to the property kind is applied with its range. ApplyColors applies default block colours read from the file.

### Pas de temps (time steps)
Les propriétés continues ou discrètes d'une même TimeSeries et de même titre sont réunies sous un nœud TimeSeries synthétique ; chacune doit porter un instant unique (modèle RESQML 2.0.1, un objet par pas de temps). Les pas de temps exposés (TimestepValues) sont les index dans la série, la date ISO étant sur la racine (time<i>). Au changement de pas, le tableau est remplacé ; un pas sans valeurs reçoit un tableau rempli de NaN.

Continuous or discrete properties of one TimeSeries sharing a title are grouped under a synthetic TimeSeries node; each must hold a single timestamp (one object per step, RESQML 2.0.1). Exposed time steps are indices in the series, ISO dates on the root. A step without values gets a NaN-filled array.

### Réalisations multiples (multiple realizations)
Les propriétés de même titre qui portent des index de réalisation sont réunies sous un nœud MultiRealization (« _multireal_<titre> »), avec un enfant par réalisation ; une propriété à la fois multi-réalisations et temporelle donne un nœud MultiRealizationTimeSeries. Ces nœuds portent propTitle, propType, propertyKind, realization_count et realization_indices. Chaque réalisation chargée devient un tableau suffixé sur le même bloc.

Same-title properties with realization indices are grouped under a MultiRealization node, one child per realization; realizations with time steps give a MultiRealizationTimeSeries node. Each loaded realization becomes a suffixed array on the same block.

### Canal de requête : principe (query channel: principle)
Les classes de FESPP ne sont pas accessibles en Python : seul le ServerManager les atteint. Le canal de requête passe donc par des paires de propriétés, une question qu'on écrit et une réponse en lecture seule, présentes à l'identique sur EPCCollector et ETPsource. Chaque clé commence par un tag, en pratique l'AssemblyTag, qui sert de clé de cache. fespp_on_trame (repo_query) force l'envoi de la question puis relit la seule propriété réponse.

FESPP classes are not Python-wrapped; only the ServerManager reaches them. The query channel therefore uses property pairs, a writable question and a read-only answer, identical on EPCCollector and ETPsource. Each key starts with a tag, the AssemblyTag, used as a cache key.

### Canal de requête : les questions (query channel: the questions)
ObjectXmlKey « tag|uuid[,uuid…] » → ObjectXml : le XML de chaque objet tel que fesapi le tient, un marqueur <PartialObject> pour un objet partiel, ou vide. ObjectUuidsKey « tag|Type » → ObjectUuids : les uuid d'un type (StratigraphicColumnRankInterpretation, AbstractLocal3dCrs), ou avec « * » l'index « uuid|balise|partiel|titre ». ObjectFieldsKey → ObjectFields : des lignes clé=valeur (CRS locaux). ObjectRelationsKey → ObjectRelations : « sens|uuid|balise|partiel|titre », cibles et sources.

ObjectXml returns each object's XML as fesapi holds it (or a <PartialObject> marker); ObjectUuids the uuids of a type, or with "*" the whole index; ObjectFields key=value lines (local CRS); ObjectRelations both directions, including objects that point at this one.

### Limites et comportements connus (limits and known behaviours)
FESPP ne dessine pas GridConnectionSetRepresentation, StreamlinesRepresentation, PlaneSetRepresentation ni la stratigraphie ; une CategoricalProperty sans StringTableLookup est refusée. Après un échec de lecture HDF5, recharger l'EPC est nécessaire. Un cadre de puits dont une MD dépasse la trajectoire est ignoré, avec le message « Cannot compute the frame MD … », et le reste du puits se charge. ETP n'existe que si le plugin a été construit avec WITH_ETP_SSL.

FESPP does not draw grid connection sets, streamlines, plane sets or stratigraphy; a CategoricalProperty without a StringTableLookup is refused. After an HDF5 read failure the EPC must be reloaded. Frames whose MD lies beyond the trajectory are skipped with a message. ETP exists only in builds with WITH_ETP_SSL.
