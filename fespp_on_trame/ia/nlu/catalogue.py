"""The commands the engine can give. Each one names its parameters
("slots"), which of them it cannot do without ("needs", "a|b" for either),
whether it only reads, the application gesture that will carry it out
("does": a controller of app/boot.py, run by the assistant's adapter —
never by the engine), and a short French description ("fr": the help table,
also given to the local AI service).

Parameters:
    object   an object of the session (grid, well, surface…), by its title
    kind     a property kind ("porosity") — the lexicon's canonical name
    min/max  bounds, from "above 0.2", "between 10 and 20"
    panel    an analysis panel (lexicon.PANELS)
    preset   a colour table (lexicon.PRESETS)
    factor   a number without bound ("x 5" for the vertical exaggeration)
    axis     i / j / k, for a slice
    on       true / false, for a switch (a play / a stop, a bar shown /
             hidden)
    question the question itself, for ask
    direction where the camera stands (top, bottom, north, south, east,
             west), or a zoom's in / out
    step     a time step or a realization: a number as said, or next,
             previous, first, last (a date or a year is kept as said)
    style    a drawing style, by its ParaView name ("Wireframe")
    scale    the colour scale: log / linear
    tool     a tool card of the view (the keys of app/views/tools_config.py)
"""

INTENTS = {
    # ------------------------------------------------------------ show / hide
    "show": {"slots": ("object", "kind"), "needs": ("object|kind",), "readonly": False,
             "does": "select_paths + eye", "fr": "afficher un objet ou une propriété dans la vue"},
    "hide": {"slots": ("object", "kind"), "needs": ("object|kind",), "readonly": False,
             "does": "eye off", "fr": "masquer un objet de la vue"},
    "isolate": {"slots": ("object", "kind"), "needs": ("object|kind",), "readonly": False,
                "does": "eye off on every other", "fr": "ne montrer que cet objet"},
    # ------------------------------------------------------------ filters
    "threshold": {"slots": ("object", "kind", "min", "max"), "needs": ("min|max",), "readonly": False,
                  "does": "threshold_add + threshold_range", "fr": "filtrer les mailles par valeur"},
    "clear_threshold": {"slots": ("object", "kind"), "needs": (), "readonly": False,
                        "does": "threshold_remove", "fr": "enlever le filtre par valeur"},
    # a highlight keeps every cell and LIGHTS the ones that match (the ParaView
    # ID selection the Values table already draws); a threshold hides the rest
    "highlight": {"slots": ("object", "kind", "min", "max"), "needs": ("min|max",), "readonly": False,
                  "does": "node_highlight", "fr": "surligner les mailles qui vérifient une condition"},
    "clear_highlight": {"slots": (), "needs": (), "readonly": False,
                        "does": "node_highlight([])", "fr": "enlever la surbrillance"},
    # the cells of the grid a well goes THROUGH — the data's blocked
    # wellbores (RESQML: the grid cells along a trajectory) — shown, and
    # lit where a value holds: "the oil-zone cells the wells cross",
    # "which wells cross the oil zone"
    "well_cells": {"slots": ("object", "kind", "min", "max"), "needs": (), "readonly": False,
                   "does": "select_paths + eye on the blocked wellbores, well_cells_where",
                   "fr": "les mailles traversées par les puits"},
    "slice": {"slots": ("object", "axis", "min", "max"), "needs": ("axis",), "readonly": False,
              "does": "slicer_range", "fr": "couper la grille selon I, J ou K"},
    "hide_nan": {"slots": ("on",), "needs": (), "readonly": False,
                 "does": "cmap_hide_nan", "fr": "masquer ou montrer les valeurs absentes"},
    # ------------------------------------------------------------ colours
    "colormap": {"slots": ("object", "kind", "preset"), "needs": ("preset",), "readonly": False,
                 "does": "cmap_preset", "fr": "changer la table de couleurs"},
    "color_range": {"slots": ("object", "kind", "min", "max"), "needs": ("min|max",), "readonly": False,
                    "does": "cmap_range", "fr": "fixer la plage de la table de couleurs"},
    "rescale": {"slots": ("object", "kind"), "needs": (), "readonly": False,
                "does": "cmap_rescale", "fr": "recaler la table de couleurs sur les données"},
    "flat_colors": {"slots": ("on",), "needs": (), "readonly": False,
                    "does": "set_flat_colors", "fr": "couleurs exactes (sans ombrage)"},
    "color_scale": {"slots": ("object", "kind", "scale"), "needs": ("scale",), "readonly": False,
                    "does": "activate the property, then cmap_scale(scale, vid)",
                    "fr": "passer l'échelle des couleurs en logarithmique ou en linéaire"},
    "color_bar": {"slots": ("object", "kind", "on"), "needs": (), "readonly": False,
                  "does": "activate the property, then cmap_bar(on, vid)",
                  "fr": "afficher ou masquer la barre de couleurs"},
    # ------------------------------------------------------------ view
    "reset_camera": {"slots": ("object",), "needs": (), "readonly": False,
                     "does": "view_reset_camera", "fr": "recadrer la vue"},
    "z_scale": {"slots": ("factor",), "needs": ("factor",), "readonly": False,
                "does": "set_zscale", "fr": "exagération verticale"},
    "new_view": {"slots": (), "needs": (), "readonly": False,
                 "does": "open_render_view", "fr": "ouvrir une nouvelle vue 3D"},
    "camera_view": {"slots": ("direction",), "needs": ("direction",), "readonly": False,
                    "does": "nav_axis(vid, axis)", "fr": "orienter la caméra (vue de dessus, depuis le nord…)"},
    "zoom": {"slots": ("direction",), "needs": (), "readonly": False,
             "does": "nav_zoom_step(vid, 0.8 or 1.25)", "fr": "zoomer ou dézoomer d'un cran"},
    "rep_style": {"slots": ("style",), "needs": ("style",), "readonly": False,
                  "does": "set_rep_style(vid, style)",
                  "fr": "changer le mode de dessin (surface, arêtes, fil de fer, points)"},
    # emptying the view hides everything — nothing is unloaded
    "hide_all": {"slots": (), "needs": (), "readonly": False,
                 "does": "on_eye_changed(vid, [])", "fr": "vider la vue (tout masquer, rien n'est déchargé)"},
    # ------------------------------------------------------------ time series, realizations
    "time_step": {"slots": ("step",), "needs": ("step",), "readonly": False,
                  "does": "time_index(idx, vid)",
                  "fr": "aller à un pas de temps (numéro, suivant, précédent, premier, dernier)"},
    "time_play": {"slots": ("on",), "needs": (), "readonly": False,
                  "does": "time_play(on, vid)", "fr": "lancer ou arrêter l'animation des pas de temps"},
    "realization": {"slots": ("object", "kind", "step"), "needs": ("step",), "readonly": False,
                    "does": "set_realization([array_path, idx], vid)",
                    "fr": "montrer une autre réalisation d'une propriété"},
    # ------------------------------------------------------------ panels, cards
    "open_panel": {"slots": ("panel", "object", "kind"), "needs": ("panel",), "readonly": False,
                   "does": "open_<panel>", "fr": "ouvrir un panneau d'analyse"},
    "close_panel": {"slots": ("panel",), "needs": ("panel",), "readonly": False,
                    "does": "mv.remove_panel(pid) of an ANALYSIS panel", "fr": "fermer un panneau d'analyse"},
    "open_tool": {"slots": ("tool",), "needs": ("tool",), "readonly": False,
                  "does": "toggle_tool(key, vid), only when the card is closed and offered",
                  "fr": "ouvrir une carte outil de la vue"},
    # ------------------------------------------------------------ questions
    "describe": {"slots": ("object", "kind"), "needs": ("object|kind",), "readonly": True,
                 "does": "xml / citation", "fr": "décrire un objet"},
    "list": {"slots": ("object", "kind"), "needs": (), "readonly": True,
             "does": "tree", "fr": "lister ce qui est chargé"},
    "value": {"slots": ("object", "kind"), "needs": ("object|kind",), "readonly": True,
              "does": "stats", "fr": "donner une statistique (moyenne, min, max)"},
    # ------------------------------------------------------------ the session
    "undo": {"slots": (), "needs": (), "readonly": False,
             "does": "session restore of the last snapshot", "fr": "annuler le dernier geste"},
    "save_session": {"slots": (), "needs": (), "readonly": True,
                     "does": "session_save", "fr": "enregistrer la session"},
    # "that is not what I wanted": not a gesture — the previous answer
    # missed; the assistant offers to undo it and learns what was meant
    "complain": {"slots": (), "needs": (), "readonly": True,
                 "does": "undo + rephrase of the previous turn", "fr": "dire que la réponse ne convient pas"},
    "help": {"slots": (), "needs": (), "readonly": True,
             "does": "", "fr": "ce que l'assistant sait faire"},
    # "what is a pillar?": a question about the domain or the application,
    # answered by the local AI service from the documentation (fespp_ia,
    # /v1/ask) — nothing is done to the view
    "ask": {"slots": ("question",), "needs": (), "readonly": True,
            "does": "fespp_ia /v1/ask (RAG)", "fr": "répondre à une question sur le métier ou l'application"},
    # "take a screenshot", "make the grid transparent", "show the pillars": a
    # request of the domain the assistant cannot carry out — answered
    # honestly, with the place of the gesture when the application has it
    "unsupported": {"slots": (), "needs": (), "readonly": True,
                    "does": "none: an honest answer, and where the gesture lives when it exists",
                    "fr": "une demande que l'assistant ne sait pas encore faire"},
}

NAMES = tuple(sorted(INTENTS))


def missing(intent, slots):
    """The parameters `intent` cannot do without and `slots` lacks; "a|b"
    is satisfied by either."""
    out = []
    for need in INTENTS[intent]["needs"]:
        if not any(slots.get(n) not in (None, "", []) for n in need.split("|")):
            out.append(need)
    return out
