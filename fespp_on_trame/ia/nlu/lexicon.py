"""The words of the trade, French and English: property kinds, panels,
colour tables, axes, groups of objects, bounds, category values, the
camera's directions, time steps, drawing styles, colour scales, tool cards
and the notions a question may name. Every entry is a canonical name and the ways a
reader says it, already normalised (text.normalize: lower case, no
accents).

KINDS maps a canonical property kind to:
    "say"   what a reader types ("porosite", "phi", "poro"…)
    "kinds" the kind names a property may carry in the data: PWLS 4.0 titles
            (assets/pwls40_kinds.json, their descendants count too) and the
            RESQML 2.0.1 standard kinds ("net to gross ratio", absent from PWLS)
    "titles" the usual property titles (mnemonics), matched whole: "PHIT"
"""
KINDS = {
    "porosity": {
        "say": ("porosite", "porosity", "poro", "phi", "porosite totale", "total porosity",
                "porosite effective", "effective porosity"),
        "kinds": ("porosity", "total porosity", "effective porosity"),
        "titles": ("phit", "phie", "poro", "porosity", "phi")},
    "permeability": {
        "say": ("permeabilite", "permeability", "perm", "perme", "perma"),
        "kinds": ("permeability", "permeability rock", "rock permeability", "permeability length"),
        "titles": ("perm", "permx", "permy", "permz", "kx", "ky", "kz", "klogh", "permeability")},
    "net to gross": {
        "say": ("net to gross", "ntg", "net sur brut", "rapport net brut", "net brut", "n g"),
        "kinds": ("net to gross ratio",),
        "titles": ("ntg", "net to gross", "net_to_gross")},
    "water saturation": {
        "say": ("saturation en eau", "saturation eau", "water saturation", "sw", "swat", "water sat", "watsat"),
        "kinds": ("water saturation",),
        "titles": ("sw", "swat", "swt", "swe", "watsat", "wsat", "water_sat")},
    "gas saturation": {
        "say": ("saturation en gaz", "saturation gaz", "gas saturation", "sg", "sgas", "gassat", "gas sat"),
        "kinds": ("gas saturation",),
        "titles": ("sg", "sgas", "gassat", "gsat", "gas_sat")},
    # "so" is a title only: said, it is the English word ("so show me…")
    "oil saturation": {
        "say": ("saturation en huile", "saturation huile", "oil saturation", "soil", "oil sat"),
        "kinds": ("oil saturation",),
        "titles": ("so", "soil", "oilsat", "osat", "oil_sat")},
    "saturation": {
        "say": ("saturation",),
        "kinds": ("saturation",),
        "titles": ()},
    "gamma ray": {
        "say": ("gamma ray", "gamma", "gr", "radioactivite naturelle", "rayons gamma"),
        "kinds": ("gamma ray", "gamma ray api unit"),
        "titles": ("gr", "sgr", "cgr", "gamma ray")},
    "bulk density": {
        "say": ("densite", "density", "bulk density", "rhob", "masse volumique", "densite apparente"),
        "kinds": ("bulk density", "density"),
        "titles": ("rhob", "rhoz", "den", "density")},
    "neutron porosity": {
        "say": ("neutron", "porosite neutron", "neutron porosity", "nphi", "tnph"),
        "kinds": ("neutron porosity",),
        "titles": ("nphi", "tnph", "npor")},
    "resistivity": {
        "say": ("resistivite", "resistivity", "rt", "rdeep", "resis"),
        "kinds": ("resistivity",),
        "titles": ("rt", "rdep", "rdeep", "ild", "lld", "rmed")},
    "sonic": {
        "say": ("sonique", "sonic", "dt", "lenteur acoustique", "acoustic slowness", "dtc"),
        "kinds": ("acoustic slowness", "compressional slowness"),
        "titles": ("dt", "dtc", "dts", "ac")},
    "shale volume": {
        "say": ("volume d argile", "vsh", "vshale", "shale volume", "argilosite", "vcl", "clay volume"),
        "kinds": ("clay volume fraction", "shale volume fraction"),
        "titles": ("vsh", "vshale", "vcl", "vclay")},
    "facies": {
        "say": ("facies", "lithologie", "lithology", "litho"),
        "kinds": ("facies type", "lithology type", "facies"),
        "titles": ("facies", "lithology", "litho")},
    "fluids": {
        "say": ("fluide", "fluides", "fluid", "fluids", "type de fluide", "fluid type", "reservoir fluid",
                "fluide de reservoir"),
        "kinds": ("fluid type", "reservoir fluid"),
        "titles": ("fluids", "fluid", "fluides", "reservoir fluid", "fluid type")},
    # "pres" and "cote" are titles only: said, they are "près" (near) and
    # "à côté" (beside)
    "pressure": {
        "say": ("pression", "pressure"),
        "kinds": ("pressure",),
        "titles": ("pressure", "pres")},
    "temperature": {
        "say": ("temperature", "temp"),
        "kinds": ("temperature", "thermodynamic temperature"),
        "titles": ("temperature", "temp")},
    "depth": {
        # "deeper", "plus profond" are bounds ("deeper than 2500 m", engine.py
        # reads the depth from them): said alone they are a move ("go deeper")
        "say": ("profondeur", "depth", "elevation", "altitude", "deep"),
        "kinds": ("depth", "elevation"),
        "titles": ("depth", "tvd", "md", "tvdss", "cote")},
    "thickness": {
        "say": ("epaisseur", "thickness", "thick"),
        "kinds": ("thickness",),
        "titles": ("thickness",)},
    "cell volume": {
        "say": ("volume des mailles", "volume de maille", "cell volume", "volume de roche",
                "bulk volume", "rock volume", "volume of cells", "volume of the cells", "volume des cellules"),
        "kinds": ("rock volume", "volume"),
        "titles": ("bulk volume", "cell volume", "bv")},
}

# the analysis panels: canonical name (the controller is open_<name>) -> words
PANELS = {
    "stats": ("statistiques", "statistique", "stats", "stat", "statistics", "statistic", "histogramme",
              "histogram"),
    "welllog": ("log view", "vue des logs", "vue log", "logs", "diagraphies", "diagraphie",
                "well log", "well logs", "log viewer", "courbes de puits", "log track", "log tracks", "logs view", "well log view", "log du puits", "logs du puits", "log of the well", "logs of the well", "log of well", "log for", "la courbe du puits", "les courbes du puits",
                "courbes du puits", "courbe du puits", "well curves", "log curves"),
    "reconcile": ("log grid", "log grille", "reconciliation", "reconcile", "comparaison puits grille",
                  "puits grille", "well grid", "log vs grid", "logs vs grid", "log versus grid", "logs versus grid",
                  "logs contre grille", "diagraphies et grille", "reconcile with logs", "reconcile with the logs",
                  "reconcilier avec les diagraphies", "reconcilier avec les logs", "log to grid", "logs to grid",
                  "log to grid check"),
    "compare": ("compare", "comparaison", "comparer", "comparison"),
    "crossplot": ("cross plot", "crossplot", "nuage de points", "scatter", "scatter plot", "cross-plot",
                  "graphique croise", "graphe croise", "diagramme croise"),
    "distribution": ("distribution", "repartition", "distributions", "distributed"),
    "xml": ("xml", "explorateur xml", "xml explorer"),
    "stratigraphy": ("stratigraphie", "stratigraphy", "colonne stratigraphique", "strati", "stratigraphic column",
                     "stratigraphic columns", "strat column", "colonnes stratigraphiques"),
    # "calculer une nouvelle propriété", "calcule une propriété", "compute a
    # new property", "le produit de la porosité et du NTG": a property
    # computed from others — "calcule la moyenne" stays a value
    "calculator": ("calculatrice", "calculateur", "calculator", "calcul", "calculette", "calculer une nouvelle",
                   "calculer un nouveau", "calculer une propriete", "creer une propriete", "compute a new",
                   "calcule une propriete", "calcule une nouvelle propriete", "calcule une nouvelle",
                   "calcule un nouveau", "cree une propriete", "cree une nouvelle propriete",
                   "creer une nouvelle propriete", "produit de",
                   "compute a property", "create a property", "build a property", "make a property",
                   "derive a property", "create a new property", "build a new property", "make a new property",
                   "derive a new property", "propriete derivee", "proprietes derivees", "derived property",
                   "derived properties"),
    "health": ("data health", "sante des donnees", "sante", "health", "qualite des donnees",
               "controle qualite", "data quality", "qc", "quality check", "controle de qualite",
               "controle de la qualite"),
}

# colour tables: the ParaView preset -> words
PRESETS = {
    "Viridis (matplotlib)": ("viridis",),
    "Inferno (matplotlib)": ("inferno",),
    "Plasma (matplotlib)": ("plasma",),
    "Turbo": ("turbo",),
    "Jet": ("jet",),
    "Rainbow Uniform": ("arc en ciel", "rainbow", "arc-en-ciel"),
    "Cool to Warm": ("froid chaud", "cool to warm", "bleu rouge", "blue red", "divergente", "diverging",
                     "blue to red", "bleu a rouge", "bleu au rouge", "du bleu au rouge"),
    "Grayscale": ("gris", "niveaux de gris", "grayscale", "greyscale", "gray", "grey", "noir et blanc",
                  "black and white", "black & white"),
    "Blue Orange (divergent)": ("bleu orange", "blue orange"),
    # a palette for categories — "une propriété catégorielle" is a kind of
    # property, not a palette
    "Brewer Qualitative Set1": ("qualitative", "categorical", "palette categorielle", "palette qualitative",
                                "couleurs categorielles", "en categorielle"),
}

# slice axes: the grid's index direction -> words; a lone letter counts as
# an axis only where a slice is spoken of (slots.spans)
AXES = {
    "i": ("i", "axe i", "direction i", "i direction", "colonne", "colonnes", "column", "columns"),
    "j": ("j", "axe j", "direction j", "j direction", "rangee", "rangees", "ligne", "lignes", "row", "rows"),
    "k": ("k", "axe k", "direction k", "k direction", "couche", "couches", "layer", "layers", "niveau",
          "niveaux"),
}

# groups of objects: a sort of object, every one of it in the session
# ("hide all the wells") — the sort is matched against the RESQML type
GROUPS = {
    "well": ("tous les puits", "les puits", "all wells", "all the wells", "the wells", "every well",
             "tous les forages", "les trajectoires", "all trajectories"),
    "horizon": ("les horizons", "tous les horizons", "toutes les surfaces", "les surfaces", "the horizons",
                "all horizons", "all the horizons", "the surfaces", "all surfaces", "all the surfaces"),
    "fault": ("les failles", "toutes les failles", "the faults", "all faults", "all the faults"),
    "grid": ("les grilles", "toutes les grilles", "the grids", "all grids", "all the grids"),
}

# the verbs that turn a filter over: "HIDE the cells below 0.08" keeps what
# is above 0.08 — the bound said is the other one
HIDING = ("cache", "caches", "masque", "masquer", "cacher", "enleve", "enlever", "retire", "retirer",
          "supprime", "vire", "exclus", "exclure", "hide", "remove", "exclude", "drop", "cut off", "discard",
          "get rid of", "filter out", "take out", "screen out", "cut out", "throw away", "leave out", "weed out",
          "coupe tout", "cut everything", "cut away", "elimine", "eliminer")

# a lone number said with one of these is a maximum / a minimum. A limit
# says neither on its own ("la limite basse", "the lower limit"): its side
# does; "top" is a place ("au top du réservoir"), a bound only as the top
# of the colour scale
MAX_WORDS = ("max", "maximum", "plafonne", "plafonner", "plafond", "cap", "caps", "capped", "ceiling", "jusqu a",
             "up to", "au plus", "limiter", "limite haute", "limite superieure", "borne superieure", "upper limit",
             "high limit", "upper bound", "top de la palette", "top de la legende", "top de l echelle",
             "top of the scale", "top of the colour scale", "top of the color scale", "top of the legend",
             "top of the palette", "top of the colormap", "top of the colorbar")
MIN_WORDS = ("min", "minimum", "plancher", "floor", "a partir de", "au moins", "at least", "limite basse",
             "limite inferieure", "borne inferieure", "lower limit", "low limit", "lower bound", "bas de la palette",
             "bas de la legende", "bas de l echelle", "bottom of the scale", "bottom of the colour scale",
             "bottom of the color scale", "bottom of the legend", "bottom of the palette", "bottom of the colormap",
             "bottom of the colorbar")

# bounds: the words that make the NEXT number a minimum, a maximum, the
# value itself, or a pair; the longest phrase wins ("pas plus de" is a
# maximum, "plus de" a minimum)
ABOVE = ("au dessus de", "au dessus d", "superieur a", "superieure a", "superieurs a", "superieures a",
         "superieur ou egal a", "superieure ou egale a", "superieur ou egale a", "superieurs ou egaux a",
         "superieures ou egales a", "plus grand que", "plus grande que", "plus grand ou egal a",
         "plus grande ou egale a", "plus de", "plus que", "au moins", "a partir de", "des", "sup a", "pas moins de",
         "au dela de", "au dela d", "depasse", "depassent", "depassant", "excede", "excedant",
         "plus profond que", "plus profonde que", "plus profonds que", "plus profondes que",
         "above", "greater than", "greater than or equal to", "greater or equal to", "more than",
         "more than or equal to", "over", "at least", "higher than", "bigger than", "at or above",
         "above or equal to", "no less than", "not less than", "no lower than", "exceeding", "exceeds", "exceed",
         "beyond", "deeper than", "from", ">", ">=")
BELOW = ("en dessous de", "en dessous d", "au dessous de", "inferieur a", "inferieure a", "inferieurs a",
         "inferieures a", "inferieur ou egal a", "inferieure ou egale a", "inferieur ou egale a",
         "inferieurs ou egaux a", "inferieures ou egales a", "plus petit que", "plus petite que",
         "plus petit ou egal a", "plus petite ou egale a", "moins de", "moins que", "pas plus de", "pas plus que",
         "au plus", "jusqu a", "sous", "inf a", "en deca de", "en deca d", "plafonne a", "plafonnee a",
         "limite a", "moins profond que", "moins profonde que", "moins profonds que", "moins profondes que",
         "below", "less than", "less than or equal to", "less or equal to", "under", "at most", "lower than",
         "smaller than", "at or below", "below or equal to", "no more than", "not more than", "no greater than",
         "no higher than", "capped at", "limited to", "shallower than", "up to", "<", "<=")
EQUAL = ("=", "==", "egal a", "egale a", "egaux a", "egales a", "equal to", "equals", "is equal to", "vaut")
BETWEEN = (("entre", "et"), ("between", "and"), ("de", "a"), ("from", "to"))

# the words that set an on / off parameter; an OFF word wins (slots.read)
ON = ("active", "activer", "allume", "allumer", "mets", "mettre", "affiche", "on", "enable", "turn on",
      "show", "oui", "yes")
OFF = ("desactive", "desactiver", "enleve", "enlever", "retire", "retirer", "eteins", "eteindre",
       "coupe", "couper", "off", "disable", "turn off", "remove", "sans", "without", "non", "no", "plus de")

# values of a categorical property (a StringTableLookup: "Reservoir Fluid"
# water / oil / gas, a lithology Shale / Sandstone…): the canonical label,
# as data files usually write it, and the ways a reader says it. A word
# becomes a category value only where the session HAS such a label
# (slots.spans): "eau" means water only on a property that lists water.
CATEGORIES = {
    "oil": ("huile", "huiles", "oil", "petrole", "hydrocarbure liquide", "petrolifere", "petroliferes",
            "huileux", "huileuse", "huileuses"),
    "gas": ("gaz", "gas", "gazeux", "gazeuse", "gazeuses"),
    "water": ("eau", "water", "aquifere", "aquifer", "aquiferes"),
    "sandstone": ("gres", "sandstone", "sable", "sand", "sands", "sables", "sableux", "sableuse", "sableuses",
                  "reservoir sableux", "greseux", "greseuse", "greseuses", "sandy"),
    "shale": ("argile", "argiles", "shale", "shales", "argileux", "argileuse", "argileuses", "argilite", "schiste",
              "clay", "shaly", "clayey"),
    "siltstone": ("silt", "silts", "siltstone", "siltite", "silteux", "silteuse", "silteuses"),
    "limestone": ("calcaire", "calcaires", "limestone", "carbonate", "carbonates", "carbonatee", "carbonatees"),
    "coal": ("charbon", "coal", "lignite", "charbonneux", "charbonneuse", "charbonneuses"),
    "channel": ("chenal", "chenaux", "channel", "channels"),
}

# where the camera stands to look at the scene (camera_view): "vue de
# dessus" is from the top. A bound word is never one ("au-dessus de 0,2" is a
# minimum: ABOVE), nor the French verb "est" ("c'est", "la vue est vide"):
# east is said after "l'" ("de l'est", "à l'est") or in English. A
# cardinal point said after "vers" / "towards" is where the camera LOOKS:
# it stands on the other side (slots.read)
DIRECTIONS = {
    "top": ("vue de dessus", "vue du dessus", "vu de dessus", "vu du dessus", "de dessus", "du dessus",
            "vue de haut", "vue d en haut", "vu d en haut", "d en haut", "depuis le haut", "par le haut",
            "vue en plan", "vue carte", "vue aerienne", "vue zenithale", "vue plongeante", "vue du ciel",
            "vu du ciel", "regarde vers le bas", "map view", "top view", "plan view", "from above", "bird s eye",
            "birds eye", "seen from above", "view from above", "view from the top", "top down", "looking down",
            "look down", "aerial view", "overhead view", "from overhead", "from the sky"),
    "bottom": ("vue de dessous", "vue du dessous", "vu de dessous", "vu du dessous", "de dessous", "du dessous",
               "vue d en bas", "vu d en bas", "d en bas", "depuis le bas", "par le bas", "par en dessous",
               "par dessous", "regarde vers le haut", "bottom view", "from below", "from underneath",
               "from beneath", "seen from below", "view from below", "view from the bottom", "bottom up",
               "looking up", "look up", "underside"),
    "north": ("nord", "north"),
    "south": ("sud", "south"),
    "east": ("l est", "du cote est", "plein est", "face est", "east"),
    "west": ("ouest", "west"),
}
# a zoom (zoom) is one step closer unless it is said back
ZOOM = {
    "out": ("dezoom", "dezoome", "dezoomer", "dezoomez", "dezoomes", "de zoom", "de zoome", "unzoom", "zoom out",
            "zoome out", "zoom arriere", "zoom en arriere", "eloigne", "eloigner", "eloignez", "eloigne toi",
            "recule la camera", "plus loin", "de plus loin", "moins pres", "prends du recul", "pull back",
            "move back", "move away", "farther", "further away", "zoom back", "back off", "wider"),
    "in": ("zoom in", "zoom avant", "zoom en avant", "zoome", "zoomer", "rapproche", "rapprocher", "rapprochez",
           "approche", "plus pres", "de plus pres", "closer", "nearer", "grossis", "agrandis", "magnify"),
}
# a time step or a realization said by its place (time_step, realization):
# the next one, the one before, the first, the last
STEPS = {
    "next": ("suivant", "suivante", "prochain", "prochaine", "d apres", "une autre", "un autre", "avance",
             "avancer", "avancez", "en avant", "next", "following", "forward", "advance", "another"),
    "previous": ("precedent", "precedente", "d avant", "recule", "reculer", "reculez", "en arriere", "previous",
                 "prev", "backward", "backwards", "back one", "one back", "rewind", "before that"),
    "first": ("premier", "premiere", "initial", "initiale", "debut", "first", "beginning", "start"),
    "last": ("dernier", "derniere", "final", "finale", "fin", "last", "end", "latest"),
}
# … or by its rank in words: "le troisième pas de temps", "the third
# realization" ("3e", "3rd" are read as written: slots.read)
ORDINALS = {
    2: ("deuxieme", "second", "seconde"), 3: ("troisieme", "third"), 4: ("quatrieme", "fourth"),
    5: ("cinquieme", "fifth"), 6: ("sixieme", "sixth"), 7: ("septieme", "seventh"), 8: ("huitieme", "eighth"),
    9: ("neuvieme", "ninth"), 10: ("dixieme", "tenth"),
}
# the drawing styles of a view (rep_style): the ParaView name -> words.
# "nuage de points" is the cross-plot (PANELS), never the Points style;
# hiding the edges is the plain surface (engine.py)
STYLES = {
    "Surface With Edges": ("aretes", "arete", "avec aretes", "avec les aretes", "surface avec aretes",
                           "maillage visible", "mailles visibles", "edges", "edge", "with edges", "with the edges",
                           "surface with edges", "mesh lines", "cell edges", "grid lines"),
    "Wireframe": ("fil de fer", "fils de fer", "filaire", "wireframe", "wire frame"),
    "Points": ("points", "en points", "as points"),
    "Outline": ("contour", "contours", "outline", "boite englobante", "bounding box"),
    "Surface": ("surface pleine", "surface simple", "surface seule", "surface unie", "mode surface",
                "rendu surface", "plain surface", "solid surface", "surface only", "surface mode", "surface style",
                "just the surface", "sans aretes", "sans les aretes", "no edges", "without edges", "without the edges"),
}
# the colour scale (color_scale). "log" alone is a well log ("le log du
# puits"): a scale only with a word of the colours or of a scale in the
# sentence, or right after "en" / "in" / "to" ("passe la perméabilité en
# log") — slots.read
SCALES = {
    "log": ("logarithmique", "logarithmiques", "logarithmic", "logarithme", "log10", "logscale", "log"),
    "linear": ("lineaire", "lineaires", "linear"),
}
SCALE_WORDS = ("echelle", "scale", "couleur", "couleurs", "colour", "colours", "color", "colors", "palette",
               "colormap", "legende", "legend", "colorbar")
# the tool cards of a view (open_tool): the key of app/views/tools_config.py
# -> words. Not the Globe: it rebuilds the scene and drops the filters
TOOLS = {
    "tree": ("explorateur de donnees", "explorateur des donnees", "explorateur", "arbre des donnees", "arbre",
             "arborescence", "data explorer", "data tree", "tree view", "tree"),
    "attributes": ("carte des attributs", "attributs", "attribut", "attributes card", "attributes", "attribute"),
    "colormap": ("carte des couleurs", "carte couleurs", "carte colormap", "carte de la colormap",
                 "carte de la palette", "reglages des couleurs", "reglages de couleur", "reglage des couleurs",
                 "parametres des couleurs", "colormap card", "colour settings", "color settings",
                 "colormap settings", "colour card", "color card"),
    "slicers": ("carte des coupes", "carte de coupe", "outil de coupe", "outils de coupe", "slicers", "slicer",
                "slicer card", "slicers card", "slicing tool", "slice tool"),
    "thresholds": ("carte des seuils", "carte de seuil", "carte seuils", "outil de seuil", "outil seuil",
                   "thresholds card", "threshold card", "threshold tool", "thresholds tool"),
    "volumetrics": ("carte volumetrie", "carte de volumetrie", "volumetrie", "volumetries", "volumetrics card",
                    "volumetric card", "volumetrics"),
    "timereal": ("temps et realisations", "temps et realisation", "carte du temps", "carte temps",
                 "carte des pas de temps", "carte des realisations", "time and realizations",
                 "time and realisations", "time card", "time tool", "time panel", "panneau du temps", "outil temps",
                 "time steps card", "timesteps card", "realizations card"),
    "navigation": ("carte navigation", "carte de navigation", "navigation card", "navigation tool", "navigation"),
    "camlink": ("synchronisation des cameras", "synchronisation de camera", "synchro des cameras", "synchro camera",
                "lien des cameras", "liaison des cameras", "camera sync", "camera link", "camera linking",
                "camera synchronisation", "camera synchronization", "cameras sync"),
}
# words that name a card only when a card is asked for ("ouvre les seuils",
# "open the slicers"): elsewhere "enlève les seuils" is the filter, "pas de
# temps 5" a time step, "coupe" a slice
TOOLS_IF_OPENED = {
    "slicers": ("coupes", "coupe"),
    "thresholds": ("seuils", "seuil", "thresholds", "threshold"),
    "timereal": ("pas de temps", "time steps", "time step", "realisations", "realizations"),
    "colormap": ("colormap", "palette"),
}
OPENING = ("ouvre", "ouvrir", "ouvrez", "ouvres", "rouvre", "open", "opens", "reopen", "deplie", "deplier", "expand",
           "carte", "card", "outil", "outils", "tool", "tools", "panneau", "panel", "volet")

# the things a reader asks ABOUT ("what is a pillar?"): the domain's
# notions and the application's parts — what a question names, in either
# language; the local AI answers from the documentation (catalogue: ask)
TOPICS = (
    "pilier", "piliers", "pillar", "pillars", "chenal", "chenaux", "channel", "channels", "faille", "failles",
    "fault", "faults", "horizon", "horizons", "grille ijk", "ijk grid", "grille", "grid", "maillage", "mesh",
    "maille", "mailles", "cell", "cells", "colonne", "column", "couche", "layer", "layers", "zone", "zones",
    "facies", "lithologie", "lithology", "porosite", "porosity", "permeabilite", "permeability", "saturation",
    "net to gross", "contact", "contacts", "toit", "top", "mur", "base", "reservoir", "aquifere", "aquifer",
    "puits", "well", "wellbore", "trajectoire", "trajectory", "marqueur", "marker", "markers", "log", "logs",
    "diagraphie", "blocked wellbore", "puits bloque", "completion", "perforation", "sous representation",
    "sub representation", "subrepresentation", "representation", "interpretation", "feature", "epc", "resqml",
    "witsml", "prodml", "etp", "fesapi", "fespp", "paraview", "trame", "hdf5", "hdf", "uuid", "citation",
    "propriete", "property", "propriete categorielle", "categorical property", "propriete continue",
    "continuous property", "propriete discrete", "discrete property", "serie temporelle", "time series",
    "realisation", "realization", "realisations", "realizations", "pas de temps", "time step", "crs",
    "systeme de coordonnees", "coordinate system", "epsg", "seuil", "threshold", "isolat", "isolate",
    "surbrillance", "highlight", "table de couleurs", "colormap", "legende", "legend", "cross plot",
    "crossplot", "distribution", "histogramme", "histogram", "statistiques", "statistics", "volumetrie",
    "volumetrics", "stratigraphie", "stratigraphy", "calculatrice", "calculator", "propriete derivee",
    "derived property", "sante des donnees", "data health", "session", "globe", "coupe", "slice",
    "exageration verticale", "vertical exaggeration", "point de vue", "camera", "hexaedre", "hexahedron",
    "geometrie", "geometry", "topologie", "topology", "grille non structuree", "unstructured grid",
    "grille 2d", "2d grid", "surface triangulee", "triangulated surface", "polyligne", "polyline",
    "nuage de points", "point set", "cellule morte", "dead cell", "nan", "valeur absente", "missing value",
)
