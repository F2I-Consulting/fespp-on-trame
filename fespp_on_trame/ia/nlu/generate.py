"""The generated training sentences, made from the catalogue: every
command in every shape the patterns know, with the words of the trade.
The corpus (corpus.py) adds the sentences people wrote.

Each intent has patterns, French and English, written without accents as
the normalised text reads. In a pattern:
    {o} an object title      {k} a property kind     {n} {m} numbers
    {p} a panel              {c} a colour table      {a} an axis
    {f} a factor             {i} {j} whole numbers, j after i
    {g} a group of objects ("tous les puits", "all the wells")
    {v} a value of a categorical property ("huile", "gas", "grès")
    {t} a notion of the trade (lexicon.TOPICS), for the questions
    [..] a part said half of the time
    (a b|c) one of the options, which may be several words; they nest
    a|b one of two single words
    N* in front: the pattern is drawn N times as often (the plain forms)

Then noise, as readers type: a letter dropped or swapped, "stp",
"please", capitals. Everything is drawn from one seeded generator: the same
seed gives the same sentences, hence the same model.

The HONEST measure is not on these: tests/unit/data/nlu_eval.jsonl holds
sentences written by hand, never generated.
"""
import re

import numpy as np

from fespp_on_trame.ia.nlu import lexicon

# titles like the ones data carries: grids, wells, surfaces, properties
OBJECTS = (
    "Hugin", "Geogrid", "Volve", "Drogon", "Sleipner", "Draupne", "Heimdal", "Johan", "Norne",
    "15/9-F-4", "15/9-F-11 A", "15/9-F-12", "15/9-19 BT2", "F-1 C", "NO 15/9-F-5", "25/11-15",
    "Top Reservoir", "Base Hugin", "Top Draupne", "Base Cretaceous", "Grid 1", "fine grid",
    "Eclipse grid", "simgrid", "modele fin", "grille principale", "Structural model", "Fault F1",
    "Faille nord", "Horizon H2", "Zone 3", "Well 7", "Puits A", "Layer 12", "PHIT_final",
    "Poro_cleaned", "NTG_2024", "Sw_model", "Facies_SIS", "Perm_log", "GR_norm", "Hugin fmt",
)

_P = {
    "show": (
        "3*(montre|affiche|visualise|fais voir|ouvre|charge|montre moi|affiche moi) {o}",
        "(montre|affiche|visualise) [(la grille|le puits|la surface|l objet) ]{o}",
        "(montre|affiche|visualise|montre moi) la {k} [(de|sur) [(la grille|le puits) ]{o}]",
        "je veux voir la {k} [de {o}]", "je veux voir {o}",
        "(colore|colorie) [la grille ]{o} (par|avec|selon) (la|le|les) {k}", "mets la {k} [sur {o}]",
        "peux tu afficher {o}", "voir {o}", "voir la {k}", "(charge|ajoute) {o} dans la vue",
        "rends visible {o}", "coche {o}",
        "(montre|affiche) (le puits|la faille|l horizon|la zone|la grille) {i}",
        "(montre|affiche|visualise|charge) (la grille|le modele|le maillage|la surface|l horizon)",
        "2*(montre|affiche|montre moi|affiche moi) (la|le|les) {k} (de|sur|dans) (la grille|le modele)",
        "2*(montre|affiche|montre moi|visualise) (les|le|la) {k} [(de|sur) {o}]",
        "(show|display) the {k} (of|on) the (grid|model)",
        "(show|display) the (grid|model|surface|horizon)",
        "3*(show|display|view|open|load|show me) {o}",
        "(show|display|view) [(the grid|the well|the surface|the object) ]{o}",
        "(show|display) the {k} [(of|on) {o}]",
        "i want to see [the ]{k} [of {o}]", "(color|colour) {o} by [the ]{k}", "let me see {o}",
        "can you display {o}", "put {o} in the view", "add {o} to the view", "open {o} in 3d",
        "visualize the {k} [on {o}]", "turn on {o}",
        "(show|display) (well|fault|horizon|zone|grid) {i}",
        "(fais apparaitre|reaffiche|remets) {o}", "(montre|affiche|reaffiche) {g}", "(show|display) {g}",
    ),
    "hide": (
        "3*(cache|masque|enleve|retire) {o}", "(cache|masque|enleve|retire) {o} [de la vue]",
        "(cache|masque) la {k} [de {o}]", "je ne veux plus voir {o}", "ferme l oeil de {o}",
        "decoche {o}", "rends invisible {o}", "fais disparaitre {o}", "enleve la {k} de la vue",
        "enleve moi {o}", "(cache|masque) (le puits|la faille|l horizon|la zone) {i}",
        "3*(hide|remove) {o}", "(hide|remove) {o} [from the view]", "hide the {k} [of {o}]",
        "turn off {o}", "i don t want to see {o} anymore", "make {o} invisible", "uncheck {o}",
        "get rid of {o}", "hide (well|fault|horizon|zone) {i}",
        "vire {o}", "(cache|masque|enleve|retire|vire) {g} [de (la vue|l affichage)]",
        "(cache|retire) {o} de l affichage", "(hide|remove|get rid of) {g}",
        "(hide|remove|get rid of) {o} (in|from) the [3d ]view",
        "(desactive|eteins|coupe l affichage de|enleve l affichage de) [(la grille|le puits|la surface) ]{o}",
        "(desactive|eteins) (la|le|les) {k} [(de|sur) {o}]",
        "(turn off|switch off|turn|switch) [the ]{k} (display|layer) [off]", "turn [the ]{o} off",
        "(turn off|switch off|disable) [the display of ][the ]{o}", "mask {o}", "(mask|masque) (the|les) (wells|puits|grid|grille|surfaces)",
    ),
    "isolate": (
        "(ne montre que|n affiche que|ne garde que) {o}", "isole {o}", "(isole|n affiche que|ne montre que) la {k} [de {o}]", "seulement {o}",
        "que {o} [dans la vue]", "(cache|masque) tout sauf {o}", "masque tout le reste sauf {o}",
        "juste {o} stp", "(only show|show only) {o}", "isolate {o}", "isolate the {k} [of {o}]", "hide everything (except|but) {o}",
        "just {o} please", "nothing but {o}",
        "(montre|affiche|garde) (uniquement|seulement) {o}", "(show|display|keep) only {o}",
        "(ne montre que|n affiche que) {g}", "only [show ]{g}",
        "(ne laisse que|ne laissez que|laisse seulement|laissez seulement|laisse uniquement) [(le puits|la grille|la surface) ]{o} [(sur la scene|dans la vue|a l ecran)]",
        "(leave only|leave just|keep just) {o} [(on the scene|in the view|on screen)]",
    ),
    "threshold": (
        "(filtre|seuille) [la {k} de ]{o} (au dessus de|superieur a|plus de) {n}",
        "(filtre|seuille) la {k} (au dessus de|superieure a|a partir de) {n}",
        "(montre|affiche) la {k} [de {o} ](au dessus de|superieure a) {n}",
        "(montre|affiche) la {k} [de {o} ](en dessous de|inferieure a|sous) {n}",
        "(montre|garde) les mailles avec [une ]{k} entre {n} et {m}", "seuil [de {k} ]entre {n} et {m}",
        "(garde|ne garde que) les mailles ou la {k} (est superieure a|depasse) {n}",
        "filtre les cellules de {o} [avec {k} ]inferieure a {n}", "seuil a {n} sur la {k}",
        "les mailles avec une {k} > {n}", "{k} > {n}", "{k} < {n}", "{k} entre {n} et {m}",
        "applique un seuil de {n} [sur {k}]", "filtre par valeur [la {k} ]de {n} a {m}",
        "threshold [the {k} of ]{o} (above|over|greater than) {n}",
        "show [the ]{k} [of {o} ](above|greater than|more than) {n}",
        "show [the ]{k} [of {o} ](below|less than|under) {n}",
        "keep cells with [a ]{k} between {n} and {m}", "filter [the ]{k} between {n} and {m}",
        "only cells where {k} is (above|over) {n}", "filter cells of {o} with {k} below {n}",
        "{k} greater than {n}", "threshold at {n}", "cells with {k} from {n} to {m}",
        "apply a {n} cutoff on [the ]{k}",
        "3*(affiche|montre|montre moi|visualise) (les zones|la zone|les mailles|les cellules) (d|a|de|en) {v} [(de|dans) [la grille ]{o}]",
        "2*(ne garde que|garde seulement|garde uniquement) (les zones|les mailles|le|la|les) [(d|a|de|en) ]{v} [(de|dans) {o}]",
        "(affiche|montre) (le|la|les) (facies|lithologie|fluide|fluides) {v} [(de|dans) [la grille ]{o}]",
        "(filtre|seuille) (sur|les zones) [(d|a) ]{v}", "que (le|la|les) {v} [(de|dans) {o}]", "ou est (l|le|la) {v}",
        "3*(show|display) [me ]the {v} (zones|zone|cells|facies) [(of|in) [the grid ]{o}]",
        "keep [only ]the {v} (cells|zones)", "filter [on ]{v} [(cells|zones)]", "only [the ]{v} [(cells|zones)]",
        "where is the {v}",
        "3*(cache|masque|enleve|retire) les (mailles|cellules) [(dont la|ou la|avec une) ]{k} [est ](en dessous de|inferieure a|au dessus de|superieure a) {n}",
        "3*(hide|remove) cells where [the ]{k} is (below|above|under|over) {n}",
        "cut off [everything ](below|under|above) {n} [{k}]",
        "(ne garde que|garde seulement) [les ]{k} (de {i} a {j}|entre {i} et {j})", "keep only {k} {i} to {j}",
        "(filtre|filter) {k} (>|<) {n} [(sur|on) {o}]",
        "(filtre|garde|seuille) [la ]{k} {n}-{m}", "(filter|keep) [the ]{k} {n}-{m}",
        "(garde|filtre) les mailles (ou|dont) la {k} (est superieure ou egale a|est inferieure ou egale a|vaut|est egale a) {n}",
        "(keep|filter) [the ]cells (where|whose) [the ]{k} is (greater than or equal to|less than or equal to|at or above|at or below|no more than|no less than|equal to) {n}",
        "(garde|filtre) [les mailles ](avec|ou) {k} (<=|>=|=) {n}", "{k} (<=|>=|=) {n}",
        "[(garde|filtre) ][la ]{k} (pas plus de|pas moins de|au plus|au moins|en deca de|au dela de|jusqu a) {n}",
        "[(keep|filter) ][the ]{k} (no more than|no less than|at most|at least|up to|exceeding|beyond) {n}",
        "(filter out|take out|screen out|throw away|cut out) [the ]cells (where|with) [the ]{k} [is ](below|above|under|over) {n}",
        "(montre|garde) les mailles plus profondes que {n} [m]", "(show|keep) [the ]cells (deeper|shallower) than {n} [m]",
    ),
    "clear_threshold": (
        "(enleve|supprime|retire) (le filtre|les filtres|le seuil|les seuils) [de {o}]",
        "plus de (filtre|seuil)", "annule (le seuil|le filtre) [sur la {k}]", "remets toutes les mailles",
        "affiche toutes les mailles", "sans filtre", "vire le seuil", "reinitialise (le filtre|le seuil)",
        "(remove|clear|delete) the (threshold|filter|thresholds|filters) [on {o}]",
        "no more (threshold|filter)", "show all cells [again]", "reset the (threshold|filter)",
        "drop the cutoff",
        "(remets|affiche|montre|redonne moi) (la grille entiere|toute la grille|la grille complete|la grille en entier|le maillage entier) [(de|pour) {o}]",
        "(show|display|bring back|give me back) the (whole|entire|full|complete) (grid|model) [again]",
        "(enleve|retire|vire) (la coupure|le cutoff|la restriction|les seuils) [sur {k}]",
    ),
    "highlight": (
        "(surligne|mets en evidence|fais ressortir|allume|colore en rouge|marque) les (mailles|cellules) [(ou la|dont la|avec une|de) ]{k} [est ](au dessus de|superieure a|en dessous de|inferieure a|depasse) {n}",
        "(surligne|mets en evidence|fais ressortir|marque) les (mailles|cellules) [(de|avec une) ]{k} entre {n} et {m}",
        "(surligne|mets en evidence|fais ressortir) [dans {o} ]les (mailles|cellules) qui (correspondent a|ont) [une ]{k} (superieure a|inferieure a|>|<) {n}",
        "(surligne|highlight) {k} (>|<) {n} [(sur|on) {o}]", "(surligne|mets en evidence) (la|les) {k} (au dessus de|en dessous de) {n}",
        "(highlight|mark|emphasize|light up|flag) [the ](cells|voxels) [(where|with|of) ][the ]{k} [is ](above|over|greater than|below|under|less than) {n}",
        "(highlight|mark|emphasize) [the ](cells|voxels) [(with|of) ][the ]{k} between {n} and {m}",
        "(highlight|flag) [the ]cells (matching|that match) [the ]{k} (>|<|above|below) {n} [(in|on) {o}]",
        "(highlight|mark) where [the ]{k} (is above|exceeds|is below) {n}",
        "(surligne|mets en evidence|fais ressortir|allume|colore en rouge) (les zones|les mailles|les cellules) (d|a|de|en) {v} [(de|dans) {o}]",
        "(affiche|montre) en surbrillance (les zones|les mailles) (d|a|de) {v}", "surligne (le|la|les) {v}",
        "(highlight|mark|light up|emphasize) [the ]{v} (zones|cells|zone) [(of|in) {o}]", "highlight [the ]{v}",
        "2*(fais ressortir|mets en evidence|signale|signale moi|repere|repere moi|pointe|pointe moi) les (mailles|cellules|zones) (d|de|a|en) {v} [(sans cacher|sans masquer|en gardant) (le reste|les autres|tout)]",
        "(surligne|surlignes|surligne moi) les (mailles|zones|cellules) (d|de|a|en) {v} (mais|et) (garde tout visible|sans cacher le reste|garde le reste)",
        "(signale|signale moi|repere|pointe) les (mailles|cellules) (ou|dont) la {k} (depasse|est au dessus de|est en dessous de) {n}",
        "(make|let) the {v} (cells|zones|zone) stand out [without hiding anything]",
        "(spotlight|flag|point out|mark) the (cells|zones) (where|with|whose) [the ]{k} (above|over|below|under|tops|exceeds|is above|is below) {n}",
        "(show|display) the {v} (cells|zones) in (a bright colour|a bright color|colour|red) [without hiding anything]",
        "(highlight|highlite|hilight) [the ]{v} (cells|zones) [(please|pls)]",
        "(make|let) the {v} (cells|zones) (glow|pop|pop out)", "(colore|marque) (le|la|les) {v} en rouge",
        "(colour|color|paint|outline) the {v} (cells|zones) [in red]",
    ),
    "well_cells": (
        "3*(surligne|montre|affiche|montre moi|marque|fais ressortir) les (mailles|cellules|blocs) (traversees|percees|croisees|rencontrees) par (les puits|le puits {o}|les forages|les trajectoires|{g})",
        "3*(surligne|montre|affiche|montre moi) (ou|les endroits ou|les mailles ou|les zones ou) (les puits|les forages|les wellbores|les trajectoires|le puits {o}) (traversent|intersectent|croisent|passent|rencontrent) [(la grille|le reservoir|la zone {v}|les zones {v}|la zone de {v}|la {k})]",
        "2*(montre|affiche|surligne|liste|donne moi|je veux) les (blocked wellbores|puits bloques|block wellbores|block wellbore|wellbores bloques|blocs de puits) [(de|dans|sur) (la zone {v}|la zone de {v}|les zones {v}|{o}|la grille)]",
        "2*(quels|quel) (puits|forages) (traversent|traverse|croisent|intersectent|rencontrent|passent par|passent dans) (la zone {v}|les zones {v}|la zone de {v}|le {v}|la grille|{o}|les mailles ou la {k} depasse {n})",
        "(ou|a quel endroit) (les puits|le puits {o}|les forages) (traversent|traverse|intersectent|croisent|rencontrent) (la zone {v}|le {v}|la grille|{o}|le reservoir)",
        "(intersection|intersections|l intersection) (des puits|des trajectoires|du puits {o}|des forages) (avec|et) (la zone {v}|la grille|{o}|les zones {v}|le reservoir)",
        "(les mailles|les cellules|mailles) (des puits|du puits {o}|traversees par les puits|le long des puits|le long du puits {o}) [(dans|en|de) (la zone {v}|le {v})]",
        "(surligne|montre|affiche) les (mailles|cellules) (de la zone {v}|{v}|en {v}|a {v}) (traversees|percees|croisees) par (les puits|le puits {o}|{g})",
        "(surligne|montre|affiche) (les endroits|la ou|les mailles ou) (les puits|les wellbores|les forages) (les intersectent|intersectent la grille|traversent le reservoir|traversent la zone {v}|passent)",
        "(surligne|montre) les (mailles|cellules) (ou|dont) la {k} (depasse|est au dessus de|est superieure a) {n} (traversees|percees) par (les puits|le puits {o})",
        "3*(highlight|show|display|mark|light up|flag|show me) the (cells|blocks|grid cells) (crossed|penetrated|intersected|drilled|traversed|hit) by (the wells|the well {o}|the wellbores|the trajectories|{g})",
        "3*(highlight|show|display|show me) (where|the cells where|the zones where|the places where) (the wells|the wellbores|the trajectories|the well {o}|{g}) (cross|intersect|go through|pass through|penetrate|hit|run through) [(the grid|the reservoir|the {v} zone|the {v} zones|the {v}|the {k}|{o})]",
        "2*(show|display|highlight|list|give me|i want) the (blocked wellbores|blocked wells|well blocks|blocked wellbore cells|block wellbores) [(of|in|on) (the {v} zone|the {v} zones|{o}|the grid)]",
        "2*(which|what) wells (cross|intersect|go through|pass through|penetrate|hit|reach) (the {v} zone|the {v} zones|the {v}|the grid|{o}|the reservoir|the cells where {k} is above {n})",
        "where (do|does) (the wells|the well {o}|the trajectories) (cross|intersect|hit|penetrate|go through) (the {v} zone|the {v}|the grid|{o}|the reservoir)",
        "(intersection|intersections|the intersection) of (the wells|the trajectories|the well {o}|the wellbores) (with|and) (the {v} zone|the grid|{o}|the reservoir)",
        "(cells|grid cells|the cells) (along the wells|along the well {o}|of the wells|the wells go through|drilled by the wells|the well {o} goes through) [(in|of) (the {v} zone|the {v})]",
        "(highlight|show) the {v} (cells|zone) (crossed|penetrated|intersected|drilled) by (the wells|the well {o}|{g})",
        "(highlight|show) the cells (where|with) [the ]{k} (above|over) {n} (crossed|penetrated|hit) by (the wells|the well {o})",
        "well (to|vs|against) (grid|reservoir|zone) (intersection|intersections)",
        "2*(enleve|cache|masque|retire|vire) les (puits|forages|trajectoires|wellbores) qui (ne traversent pas|ne passent pas par|ne croisent pas|n atteignent pas|ne rencontrent pas|n ont pas de mailles dans|n ont pas de blocs dans|ne touchent pas) (la zone {v}|le {v}|la zone de {v}|la grille|le reservoir|{o})",
        "(ne garde que|garde seulement|garde uniquement|conserve) les (puits|forages|trajectoires) qui (traversent|passent par|croisent|atteignent|rencontrent) (la zone {v}|le {v}|la grille|{o})",
        "(montre|affiche|montre moi) [tous ]les (blocs|blocks|mailles) des (puits|wellbores|forages) [qui (traversent|passent par|sont dans) ](la zone {v}|cette zone|le {v}|ces zones)",
        "2*(hide|remove|drop|get rid of) the (wells|wellbores|trajectories) that (do not|don t|never) (cross|reach|go through|pass through|intersect|hit) (the {v} zone|the {v}|the grid|{o})",
        "(keep only|only keep|keep) the wells that (cross|reach|go through|intersect) (the {v} zone|the {v}|the grid|{o})",
        "(show|display|show me) [all ]the (blocks|cells) of the (wells|wellbores) [(in|that cross|that are in) ](the {v} zone|this zone|the {v}|these zones)",
    ),
    "clear_highlight": (
        "(enleve|retire|efface|eteins|supprime) (la surbrillance|le surlignage|la mise en evidence)",
        "plus de surbrillance", "(efface|vide) la selection [en 3d]", "desurligne [tout]",
        "(remove|clear|turn off) the (highlight|highlighting|selection)", "no more highlight", "unhighlight [everything]",
    ),
    "slice": (
        "coupe [la grille ]{o} (selon|suivant|en) {a}", "coupe en {a} [de {i} a {j}]",
        "fais une coupe [(en|selon) ]{a} [a {i}]", "tranche {a} {i}", "montre la {a} {i} [de {o}]",
        "garde les {a} de {i} a {j}", "coupe {a} entre {i} et {j}", "slice selon {a}",
        "slice [the grid ]{o} along {a}", "cut [along ]{a} [at {i}]", "show {a} {i} [of {o}]",
        "keep {a} from {i} to {j}", "slice {a} between {i} and {j}", "section along {a} [at {i}]",
        "(cut|slice) the grid (in|along) the {a} direction", "[show me ](a|an) {a} section [(through|of) {o}]",
        "(fais|montre moi) une coupe {a} [(de|dans) {o}]",
        "(garde|montre) les {a} {i}-{j}", "(keep|show) [the ]{a} {i}-{j}",
        "(coupe|slice|cut) (a|at|en) {a} = {i}", "{a} = {i}", "(show|keep) (rows|columns) {i} to {j}",
        "(cut|slice) [the grid ](on|by|in) {a}", "(make|do) (a|an) {a} cut [(at|from) {i}]",
        "(montre|garde) (la couche|le niveau|la colonne|la rangee) {i}", "(show|keep) (layer|row|column) {i}",
    ),
    "hide_nan": (
        "(cache|masque) les valeurs (absentes|manquantes|nan)", "(montre|affiche) les (valeurs absentes|nan)",
        "(enleve|retire) les nan", "masque les mailles sans valeur", "cacher les valeurs vides",
        "(hide|mask) the (nan|missing values|no data)", "show [the ](nan|missing values)",
        "remove the nan", "hide cells without (value|values)",
        "(remets|reaffiche|fais reapparaitre) les (valeurs absentes|nan|mailles sans valeur)",
        "(show|bring back) the (nan|missing values|empty cells) [again]",
        "je ne veux (pas|plus) voir les (nan|valeurs absentes)", "(i don t|i do not) want to see the (nan|missing values)",
        "make the (nan|missing values) (visible|invisible)",
    ),
    "colormap": (
        "(passe|mets) [la {k} ]en {c}", "table de couleurs {c}", "colormap {c} [(sur {k}|pour {o})]",
        "(change|utilise) (la palette|la table de couleurs) [(en|pour) ]{c}", "palette {c}", "couleurs {c}",
        "mets la palette {c} [sur {o}]", "je veux du {c}", "applique {c}", "affiche en {c}",
        "use [the ]{c} [(colormap|palette|color map)]", "switch [the {k} ]to {c}", "colormap {c}",
        "change the (colors|colours|colormap) to {c}", "set palette to {c} [for {o}]", "apply {c}",
        "make it {c}", "{c} colors please",
    ),
    "color_range": (
        "(plage|echelle) de couleurs [(de|entre) ]{n} [(a|et) ]{m}", "couleurs entre {n} et {m}",
        "fixe l echelle de couleurs [de la {k} ]de {n} a {m}", "borne la palette entre {n} et {m}",
        "(min|max) (de la palette|de l echelle) a {n}", "echelle de {n} a {m} [pour la {k}]",
        "legende de {n} a {m}", "colorbar de {n} a {m}",
        "(color range|color scale|colour range) from {n} to {m}",
        "set the (color|colour) range [of {k} ]to {n} {m}", "colors between {n} and {m}",
        "clamp the colormap between {n} and {m}", "colormap min {n} max {m}", "legend from {n} to {m}",
        "range {n} to {m} for [the ]{k}",
        "(legende|echelle|palette) {n}-{m}", "(legend|colorbar|scale) {n}-{m}",
        "(limit|cap) the (legend|colorbar|colormap|scale) (to|at) {n}",
        "(plafonner|limiter) (la legende|la palette|l echelle) a {n}",
        "(plafonne|borne) (la legende|la palette|l echelle) a {n}", "cap the (colorbar|colormap|legend|scale) at {n}",
        "(max|maximum) de la (legende|palette) a {n}", "(min|minimum) de la (legende|palette) a {n}",
    ),
    "rescale": (
        "(recale|reajuste|recalcule) (l echelle de couleurs|la palette|la plage) [sur les donnees]",
        "echelle automatique", "remets l echelle (par defaut|auto)", "ajuste la palette aux donnees",
        "rescale [(the colormap|the colors|the range) ][to data]", "(auto range|auto scale)",
        "fit the colormap to [the ]data", "reset the color range",
        "(remets|recale) la legende (sur|a) (l etendue des valeurs|les donnees|toute la plage)",
        "fit the (legend|colorbar) to the (data|values)",
    ),
    "flat_colors": (
        "couleurs exactes", "(enleve|retire|coupe) (l ombrage|l eclairage|la lumiere)",
        "sans (ombrage|eclairage)", "(remets|active) (l ombrage|l eclairage)", "desactive la lumiere",
        "(pas de|sans|enleve le|vire le) degrade", "des couleurs (franches|unies|a plat|nettes) [(stp|s il te plait)]", "je veux pas de degrade[, des couleurs franches]",
        "(no|without|remove the) (gradient|shading|gradients)", "(solid|flat|plain) (colours|colors) [please]",
        "exact (colors|colours)", "(turn off|disable) [the ](shading|lighting)", "no (shading|lighting)",
        "(turn on|enable) [the ](shading|lighting)", "flat (colors|colours)",
        "(desactive|enleve) les couleurs plates", "(remets|active|enleve|retire) les ombres",
        "(turn off|disable) [the ]flat (colors|colours)",
    ),
    "reset_camera": (
        "recadre [la vue ][sur {o}]", "(reinitialise|remets) (la camera|la vue)", "zoom sur {o}",
        "(la vue est partie|je suis perdu|je me suis perdu|la camera est partie) [(n importe ou|remets la d aplomb|recadre)]", "remets (la|la vue|la camera) d aplomb",
        "(the view is gone|i m lost|i am lost|the camera went away) [(reset it|bring it back|recentre)]",
        "centre [la vue ]sur {o}", "vue d ensemble", "cadre tout", "on ne voit rien recentre",
        "reset [the ](camera|view)", "zoom (to|on) {o}", "center [the view ]on {o}", "fit [the ]view",
        "frame everything", "zoom to fit", "recenter",
    ),
    "z_scale": (
        "(exageration verticale|echelle verticale) [(de|a) ]{f}", "exagere le z [par ]{f}",
        "multiplie [(le|les) ]z par {f}", "etire verticalement [(de|par) ]{f}", "z x {f}", "facteur z {f}",
        "echelle z {f}", "mets le z a {f}",
        "vertical exaggeration [(of|to) ]{f}", "z scale [to ]{f}", "stretch z by {f}",
        "exaggerate z [by ]{f}", "set z scaling to {f}", "multiply z by {f}",
    ),
    "new_view": (
        "(ouvre|cree) [une ]nouvelle vue [3d]", "ajoute une vue [3d]", "une autre vue", "nouvelle fenetre 3d",
        "deuxieme vue", "(open|create) [a ]new [3d ]view", "add a [3d ]view", "another view", "second view",
        "split the view",
    ),
    "open_panel": (
        "(ouvre|affiche|lance) [(le panneau|la vue|les|le|la) ]{p} [(de {o}|de la {k})]",
        "je veux (les|le|la) {p} [(de|pour) {o}]", "{p} [(de|sur) la ]{k}", "{p} [de {o}]",
        "montre moi (les|le|la) {p} [de la {k}]", "fais [(un|une) ]{p} [(de {k}|de {o})]",
        "panneau {p}", "peux tu ouvrir [(le|la) ]{p}",
        "(open|show|launch) [the ]{p} [(panel|view) ][(for|of) {o}]", "{p} of [the ]{k}", "{p} for {o}",
        "i want the {p} [of {o}]", "(show me|montre moi) (le|la|les|the) {p} (de|du|of) [(la grille |the grid |le puits |the well )]{o}", "bring up [the ]{p}", "make a {p} [of the {k}]",
        "(run|lance|fais) [(a|un|une) ]{p} [(check|controle) ][(on|sur) (everything|tout|{o})]",
    ),
    "describe": (
        "3*(decris|presente) {o}", "qu est ce que {o}", "c est quoi {o}", "que contient {o}",
        "donne moi des (infos|informations) sur {o}", "explique [moi ]{o}", "(detail|details) de {o}",
        "qui a cree {o}", "d ou vient {o}", "quelle est l origine de {o}",
        "(decris|c est quoi) (le puits|la faille|l horizon) {i}", "(decris|presente) (la grille|le modele|la surface|l horizon)",
        "describe the (grid|model|surface)",
        "3*describe {o}", "what is {o}", "tell me about {o}", "(info|information) (on|about) {o}",
        "explain {o}", "details of {o}", "who created [the ]{o} [(property|grid|well|surface)]", "qui a cree (la|le) {o} [(propriete|grille|puits|surface)]", "where does {o} come from",
        "describe (well|fault|horizon) {i}", "(what s|whats) {o}",
    ),
    "list": (
        "liste [(les|toutes les) ]proprietes [de {o}]", "quelles proprietes [(a {o}|sont chargees)]",
        "quels puits [(sont charges|y a t il)]", "qu est ce qui est charge", "liste les (grilles|puits|objets)",
        "quelles sont les (grilles|surfaces) [disponibles]", "qu y a t il dans (le fichier|le projet|la session)", "qu est ce qu il y a dans (le fichier|le projet|la session)",
        "combien de (puits|grilles)", "montre la liste des (proprietes|puits|logs)", "quels logs [a {o}]",
        "list [(the|all) ]properties [of {o}]", "which properties [(does {o} have|are loaded)]",
        "what (wells|grids) are loaded", "what is loaded", "list the (grids|wells|objects|logs)",
        "what is in the (file|project|session)", "how many (wells|grids)", "which logs [does {o} have]",
    ),
    "value": (
        "quelle est la {k} moyenne [de {o}]", "(moyenne|min|max|minimum|maximum) de la {k} [de {o}]",
        "combien vaut la {k} [de {o}]", "donne moi la {k} (moyenne|max|min) [de {o}]",
        "quelle est la valeur de la {k} [de {o}]", "la {k} va de combien a combien",
        "quelle est la plage de la {k}", "ecart type de la {k}", "mediane de la {k} [de {o}]",
        "what is the (mean|average|minimum|maximum) {k} [of {o}]", "(average|mean|max|min) {k} [of {o}]",
        "how much is the {k} [of {o}]", "what is the range of [the ]{k}", "{k} range [of {o}]",
        "standard deviation of [the ]{k}", "median {k} [of {o}]", "give me the mean {k}",
        "(moyenne|mediane|min|max|ecart type) (du|de la|de l) {k} [(de|sur) {o}]",
        "c est quoi la (moyenne|mediane|valeur max|valeur min) (du|de la) {k} [sur {o}]",
        "c est quoi la {k} [de {o}]", "what is the {k} [of {o}]",
        "how (high|low) does the {k} go [in {o}]", "jusqu ou va la {k} [dans {o}]",
        "how deep (is|does) {o} [go]", "(quelle est la profondeur|a quelle profondeur est) [de ]{o}",
    ),
    "undo": (
        "(annule|defais) [(ca|le dernier geste|ce que tu viens de faire)]", "reviens en arriere",
        "retour arriere", "c est pas ca annule", "non annule", "remets comme avant", "ctrl z",
        "undo [(that|the last step|it)]", "(undo|cancel|revert) the last (action|step|change|command)", "(annule|defais) (la derniere action|le dernier changement|la derniere commande)", "go back", "revert [that]", "put it back as it was", "cancel that",
    ),
    "save_session": (
        "(enregistre|sauvegarde) [(la session|mon travail|l etat)]", "garde la session",
        "fais une sauvegarde", "exporte la session",
        "save [(the session|my work|the state)]", "save session", "export the session", "make a backup",
    ),
    "complain": (
        "(ta|la) reponse ne me (convient|plait|satisfait|va) pas", "ta reponse [precedente ]ne me (convenait|plaisait) pas",
        "la reponse (du|de la|de l) (masquage|filtre|surbrillance|seuil|coupe|couleur|affichage) ne me (convient|satisfait) pas",
        "ce n est pas (ce que je voulais|ce que j attendais|ca|bon)", "c est (faux|pas bon|pas ca|n importe quoi)",
        "(je vois|i see) (que du gris|rien|rien du tout|plus rien|plus les puits|plus la grille|nothing|nothing at all|no wells|nothing anymore)",
        "(i don t|i dont|i do not) see (the wells|the grid|anything|the property|it) [(anymore|at all)]", "je ne vois (plus|pas) (les puits|la grille|la propriete|rien)",
        "(de quoi|de quel puits|de quelle propriete|de quelle grille|de quelle zone|de quelle valeur) (tu parles|parles tu|parlez vous)",
        "(which|what) (well|wells|property|grid|zone|value|values|one|ones) ?", "(mean|average|value|values|statistic) of what [?]", "(valeur|moyenne|statistique) de quoi [?]",
        "(what|which) do you mean", "(i don t|i dont) (understand|get) (your question|the question|you)", "je ne comprends pas (ta question|la question|ce que tu demandes)",
        "(non|nan) (pas ca|ce n est pas ca)", "mauvaise reponse", "tu t es trompe", "tu n as pas compris",
        "(ca|cela) ne (va|marche|convient) pas", "pas du tout ce que je (voulais|demandais)",
        "(that s|that is|this is) (not what i wanted|wrong|not right|not it)", "wrong answer", "you misunderstood",
        "not what i meant", "no that s not it", "this doesn t (help|work)", "i don t like (that|this) answer",
    ),
    "ask": (
        "3*(c est quoi|qu est ce que|qu est ce qu|qu est ce que c est qu|c est quoi exactement) (un|une|le|la|les|l |des|) ?{t} ?[(dans resqml|dans fespp|dans paraview|ici|dans l application)]",
        "2*(explique moi|explique|definis|decris moi|dis moi ce qu est|a quoi sert|a quoi servent|comment fonctionne|comment marche|comment on utilise|que veut dire|que signifie) (un|une|le|la|les|l |) ?{t}",
        "(quelle est la difference entre|difference entre) (un|une|le|la|) ?{t} et (un|une|le|la|) ?{t}",
        "(je ne sais pas ce qu est|je ne comprends pas|j ai pas compris) (un|une|le|la|les|) ?{t}", "{t} ?", "{t} c est quoi", "(definition|def) (de|du|d) ?{t}",
        "3*(what is|what s|whats|what are|what does) (a|an|the|) ?{t} [(mean|in resqml|in fespp|in paraview|here|in the app)]",
        "2*(explain|define|describe|tell me about|what is meant by|how does|how do i use|what is the use of) (a|an|the|) ?{t}",
        "(what is the difference between|difference between) (a|an|the|) ?{t} and (a|an|the|) ?{t}", "{t} ?", "{t} meaning", "(definition|def) of (a|an|the|) ?{t}",
        "(i don t know what|i don t understand what|not sure what) (a|an|the|) ?{t} (is|are|means)",
        "pour quelle raison (le|la|les) {t} (reste|restent|apparait|apparaissent) [(a l ecran|dans la vue)]",
        "est ce qu il y a (des|un|une) {t} (dans le modele|dans ce projet|dans ces donnees|quelque part)",
        "le (terme|mot|sigle) {t} (designe|represente|signifie) quoi",
        "why (is|are) the {t} (still shown|still there|highlighted|visible|shown)",
        "(do you see|can you see) (any|a|an|the|) ?{t} [in the grid]",
    ),
    # ------------------------------------------------------------ the view's gestures
    "close_panel": (
        "3*(ferme|fermez|ferme moi) (le panneau|la vue|les|le|la|l) {p}",
        "2*(ferme|fermez|enleve|retire|vire|supprime) (le panneau|l onglet|la fenetre|le graphique) (des|du|de la|de l) {p}",
        "(ferme|fermez) [(le panneau|la fenetre) ](des|du|de la|de l) {p} [de {o}]",
        "(peux tu|tu peux|je voudrais|j aimerais) fermer (le panneau|les|le|la|l) {p}",
        "(j ai plus besoin|je n ai plus besoin|plus besoin) (du panneau|des|du|de la) {p} [(ferme le|tu peux le fermer)]",
        "(cache|range|replie) le panneau (des|du|de la) {p}",
        "3*(close|shut) [the ]{p} [(panel|view|window|tab|chart)]",
        "2*(get rid of|remove|dismiss) the {p} (panel|view|window|tab|chart)",
        "close the {p} (panel|view|window|tab) [(of|for) {o}]",
        "(i m done with|i am done with|done with|no need for) the {p} [(panel|view)] [close it]",
        "(can you|could you|please) close the {p} [(panel|view)]",
    ),
    "camera_view": (
        "3*(vue|passe en vue|mets la vue|bascule en vue|affiche la vue|donne moi une vue) (de dessus|du dessus|de haut|d en haut|en plan|carte|aerienne|zenithale|plongeante|de dessous|du dessous|d en bas)",
        "2*(regarde|vue|place la camera|mets la camera|oriente la camera|tourne la camera|positionne la camera|montre la scene) (depuis le|du|au|par le|vers le) (nord|sud)",
        "2*(regarde|vue|place la camera|mets la camera|oriente la camera|tourne la camera|positionne la camera|montre la scene) (depuis l|de l|a l|par l|vers l) (est|ouest)",
        "(vue|camera) (nord|sud|ouest|plein est|plein nord|plein sud)",
        "(montre|affiche|fais voir) [(la grille|le modele|le reservoir|tout) ](de dessus|vu de dessus|d en haut|vu d en haut|de dessous|par en dessous|depuis le nord|depuis le sud|depuis l est|depuis l ouest)",
        "(montre|affiche) {o} (vu de dessus|de dessus|d en haut|depuis le nord|depuis le sud|depuis l ouest|depuis l est)",
        "(je veux|j aimerais|je voudrais) (voir|regarder) (la grille|le modele|le reservoir|tout|la scene) (de dessus|d en haut|par en dessous|depuis le nord|depuis le sud|depuis l est|depuis l ouest)",
        "(remets|repasse|reviens) en vue (de dessus|du dessus|en plan|de dessous)",
        "regarde vers le (bas|haut) [(stp|svp)]",
        "(oriente|tourne|pivote) la (camera|vue) (vers le nord|vers le sud|vers l est|vers l ouest|face au nord|face au sud)",
        "3*(top|bottom|plan|map|aerial|overhead) view [(please|of the grid|of the model)]",
        "2*(view|look|put the camera|place the camera|point the camera|move the camera|turn the camera|show the scene) from the (north|south|east|west)",
        "(view|look|look at it|see it|show it) from (above|below|underneath|overhead|the sky)",
        "(switch|go|change) to [a ](top|bottom|plan|map|bird s eye|top down) view",
        "(bird s eye|birds eye|top down) view [please]",
        "(show|display) [(the grid|the model|everything) ](from above|from below|from the north|from the south|from the east|from the west)",
        "(show|display) {o} (from above|from below|from the north|from the south|from the east|from the west)",
        "(north|south|east|west) view",
        "(look|looking) (down|up) at the (model|grid|scene)",
        "(turn|point|orient) the camera (towards|toward) the (north|south|east|west)",
        "(i want|i d like) to see (it|the grid|the model|the scene) from (above|below|the north|the south|the east|the west)",
    ),
    "zoom": (
        "3*(zoome|zoom|zoomer|zoomez) [(un peu|un cran|encore|plus|davantage|un petit peu)]",
        "2*(zoom|zoome) (avant|arriere|en avant|en arriere) [(un peu|un cran)]",
        "2*(dezoome|dezoomer|dezoom|dezoomez) [(un peu|un cran|encore|un petit peu)]",
        "(rapproche|rapproche toi|approche|approche toi|rapproche la camera|approche la camera) [(un peu|un cran|encore)]",
        "(eloigne|eloigne toi|recule la camera|eloigne la camera|prends du recul) [(un peu|un cran|encore)]",
        "(plus pres|plus loin|de plus pres|de plus loin|un peu plus pres|un peu plus loin) [(stp|svp)]",
        "(agrandis|grossis) [(un peu|la vue|l image)]",
        "(je veux|j aimerais|je voudrais) (zoomer|dezoomer|voir de plus pres|voir de plus loin)",
        "(peux tu|tu peux) (zoomer|dezoomer|zoomer un peu|dezoomer un peu)",
        "fais un (zoom|zoom avant|zoom arriere)",
        "3*zoom (in|out) [(a bit|a little|one notch|some more|more|slightly)]",
        "2*zoom [(a bit|a little|some more|closer)]",
        "(get|move|come) (closer|nearer) [(to the model|with the camera)]",
        "(pull|move) (back|away|further away) [(a bit|a little|the camera)]",
        "(unzoom|dezoom) [(a bit|a little)]",
        "(can you|could you) zoom (in|out) [(a bit|a little)]",
        "(i want|i d like) to (zoom in|zoom out|get closer|see it from further away)",
        "(magnify|enlarge) the view [a bit]",
    ),
    "rep_style": (
        "3*(passe|mets|affiche|montre|dessine|rends) [(la grille|la vue|le modele|la surface|tout) ](en|avec les|avec des|en mode) (fil de fer|filaire|aretes|points|contour|surface pleine|surface avec aretes)",
        "2*(affiche|montre|active|mets|fais voir) les aretes [(des mailles|du maillage|de la grille|de {o})]",
        "2*(enleve|retire|cache|masque|desactive|vire) les aretes [(des mailles|du maillage|de la grille)]",
        "(mode|rendu|representation|style) (fil de fer|filaire|surface|points|contour|aretes|surface avec aretes|boite englobante)",
        "(juste|seulement|uniquement) (le contour|la boite englobante|les points|les aretes|le fil de fer)",
        "(rends|mets) le maillage visible",
        "(remets|repasse|reviens) en (surface|mode surface|surface pleine|surface simple)",
        "(affiche|montre) (la grille|{o}|le modele) (sans|avec) (les aretes|aretes)",
        "(je veux|j aimerais) voir (les aretes|le fil de fer|les mailles en filaire) [de la grille]",
        "3*(show|display|render|draw|switch|set) [(the grid|the model|it|everything|{o}) ](as|in|with|to) (wireframe|points|outline|edges|surface with edges|plain surface|bounding box)",
        "2*(show|display|turn on) the (edges|cell edges|mesh lines|grid lines) [(of the grid|of the cells|of {o})]",
        "2*(hide|remove|turn off) the (edges|cell edges|mesh lines|grid lines)",
        "(wireframe|outline|points|surface with edges|plain surface) (mode|style|representation|rendering) [please]",
        "(switch|change|set) the (representation|rendering|display style|style) to (wireframe|points|outline|surface|surface with edges)",
        "(just|only) the (outline|bounding box|edges|points)",
        "(back to|go back to) (plain surface|surface|solid surface)",
        "(no|without) edges [please]",
    ),
    "hide_all": (
        "3*(cache|masque|enleve|retire|vire|eteins) tout [(de la vue|dans la vue|a l ecran|de l ecran|de la scene)]",
        "2*(vide|nettoie) (la vue|l ecran|la scene|la vue 3d)",
        "(masque|cache|eteins|decoche) (tous les objets|tous les elements|toute la scene|tout ce qui est affiche|tout ce qui est visible)",
        "(coupe|desactive) tout l affichage",
        "(fais|fait) (le vide|table rase) (dans la vue|a l ecran)",
        "(tout|tous les objets) (masques|caches|invisibles) [(stp|svp)]",
        "(repars|recommence) (d une vue vide|avec une vue vide)",
        "(je veux|j aimerais) une vue vide",
        "3*(hide|remove|clear|turn off) everything [(from the view|in the view|on screen|from the scene)]",
        "2*(clear|empty|wipe|clean) the (view|scene|screen|3d view)",
        "(hide|turn off|uncheck) (all objects|all the objects|everything that is shown|everything displayed|the whole scene)",
        "(start|begin) (from|with) an empty (view|scene)",
        "(make|set) everything (invisible|hidden)",
        "(i want|i d like) an empty view",
    ),
    "time_step": (
        "3*(va|passe|aller|saute|avance|reviens|retourne) (au|a la) (pas de temps|date|annee) [numero ]{i}",
        "2*(pas de temps|instant|timestep) [numero ]{i}",
        "2*(passe|va|avance|saute) au pas de temps (suivant|precedent|d apres|d avant)",
        "(pas de temps|instant|date) (suivant|suivante|precedent|precedente|d apres|d avant)",
        "(va|passe|saute|reviens|retourne) au (premier|dernier) pas de temps",
        "(montre|affiche) (le pas de temps|la date|l annee|l instant) {i}",
        "(montre|affiche) le (premier|dernier) pas de temps",
        "(avance|recule) d un pas de temps",
        "(avance|recule) dans le temps [d un cran]",
        "(montre|affiche) (la|le) {k} (au pas de temps|a la date|en) {i}",
        "(reviens|retourne) au (debut|pas de temps initial|premier pas de temps) [de la serie]",
        "(je veux|j aimerais) voir le pas de temps (suivant|precedent|{i})",
        "3*(go|jump|move|skip|switch) to (time step|timestep|step|date|year) [number ]{i}",
        "2*(time step|timestep) [number ]{i}",
        "2*(next|previous|first|last) (time step|timestep|date)",
        "(go|jump|move|skip) to the (next|previous|first|last) (time step|timestep|date)",
        "(step|move|go) (forward|backward) in time",
        "(show|display) (time step|timestep|the year|the date) {i}",
        "(show|display) the {k} at (time step|timestep|step) {i}",
        "(back to|go back to) the (first|initial) time step",
        "(advance|rewind) one time step",
    ),
    "time_play": (
        "3*(lance|joue|demarre|anime|relance|reprends) (l animation|les pas de temps|la serie temporelle|le film|l evolution dans le temps)",
        "2*(arrete|stoppe|fige|suspends|interromps|coupe) (l animation|les pas de temps|la lecture|le film|la serie temporelle|le defilement)",
        "(mets|met) (l animation|la lecture|les pas de temps) en pause",
        "(anime|fais defiler|fais tourner|deroule) (les pas de temps|le temps|la serie temporelle|les dates)",
        "(lecture|pause) (de l animation|des pas de temps)",
        "(fais|lance) (une animation|un film) (des pas de temps|dans le temps|de la propriete)",
        "(je veux voir|montre moi) (l evolution|l animation) (dans le temps|des pas de temps)",
        "3*(play|start|run|resume|restart) (the animation|the time steps|the timesteps|the time series|the movie)",
        "2*(stop|pause|halt|freeze) (the animation|the time steps|playback|the playback|the movie|the time series)",
        "(animate|play through|loop through|cycle through|step through) (the time steps|the timesteps|time|the dates|the time series)",
        "(start|stop|pause) (playing|animating) [the time steps]",
        "(show|let me see) the (evolution|changes) (over|through) time",
    ),
    "realization": (
        "3*(montre|affiche|passe a|va a|charge|prends) la realisation [(numero|n) ]{i} [(de la {k}|de {o})]",
        "2*(realisation|tirage) [(numero|n) ]{i} [(de la {k}|de {o}|stp)]",
        "2*(passe|va) a la realisation (suivante|precedente|d apres|d avant)",
        "(realisation|tirage) (suivante|precedente|suivant|precedent)",
        "(montre|affiche) la (premiere|derniere) realisation [(de la {k}|de {o})]",
        "(montre|affiche) une autre realisation [(de la {k}|de {o})]",
        "(change|change de) realisation [pour la {k}]",
        "(montre|affiche) (la|le) {k} [de {o} ](realisation|tirage) {i}",
        "(je veux|j aimerais) voir la realisation {i} [(de {o}|de la {k})]",
        "3*(show|display|load|use|switch to|go to) realization [(number|no) ]{i} [(of the {k}|of {o})]",
        "2*(realization|realisation) [number ]{i} [(of the {k}|of {o}|please)]",
        "2*(next|previous|first|last) realization [(of the {k}|of {o})]",
        "(go|move|switch) to the (next|previous|first|last) realization",
        "(show|display) [the ]{k} realization {i}",
        "(show|display) another realization [of the {k}]",
        "(i want|i d like) to see realization {i} [of {o}]",
    ),
    "color_scale": (
        "3*(passe|mets|affiche) [(la {k}|les couleurs|la palette|l echelle) ]en (log|echelle log|echelle logarithmique|logarithmique|lineaire|echelle lineaire)",
        "2*(echelle|palette|couleurs|legende) (log|logarithmique|lineaire) [(pour|sur) (la {k}|{o})]",
        "(utilise|applique|prends) une echelle (log|logarithmique|lineaire) [(pour|sur) la {k}]",
        "(echelle de couleurs|colormap|palette) en (log|logarithmique|lineaire)",
        "(remets|repasse|reviens) (l echelle|la palette|les couleurs) en lineaire",
        "(enleve|retire|desactive|vire) (l echelle log|l echelle logarithmique) [(de la {k}|sur {o})]",
        "(je veux|j aimerais) [voir ]la {k} en (log|echelle logarithmique)",
        "3*(switch|set|put|change|show) [(the {k}|the colours|the colors|the colormap|the scale) ](to|on|in) (log|a log scale|log scale|logarithmic|a logarithmic scale|linear|a linear scale|linear scale)",
        "2*(log|logarithmic|linear) (scale|colour scale|color scale|colormap|legend) [(for|on) (the {k}|{o})]",
        "(use|apply) a (log|logarithmic|linear) (scale|colour scale|color scale) [(for|on) the {k}]",
        "(turn off|remove|disable) the (log scale|logarithmic scale) [(on|for) the {k}]",
        "(back to|go back to|return to) (a linear scale|linear|linear scale)",
        "make the (colour|color) scale (logarithmic|linear)",
        "(colour|color) [the ]{k} on a (log|logarithmic) scale",
    ),
    "color_bar": (
        "3*(affiche|montre|active|mets|reaffiche|allume) (la barre de couleurs|la legende|la colorbar|la barre de couleur) [(de la {k}|de {o})]",
        "3*(cache|masque|enleve|retire|desactive|vire|eteins|supprime) (la barre de couleurs|la legende|la colorbar|la barre de couleur) [(de la {k}|de {o})]",
        "(sans|pas de|plus de) (legende|barre de couleurs|colorbar)",
        "(je veux|j aimerais) (voir|avoir) la (legende|barre de couleurs) [de la {k}]",
        "(je ne veux plus|je veux plus) [voir ]la (legende|barre de couleurs)",
        "(legende|barre de couleurs|colorbar) (on|off|visible|invisible)",
        "(montre|affiche) moi la legende (de la {k}|des couleurs)",
        "3*(show|display|turn on|enable|bring back|add) the (colour bar|color bar|colorbar|legend|colour legend|color legend|scalar bar) [(of the {k}|for {o})]",
        "3*(hide|remove|turn off|disable|get rid of|drop) the (colour bar|color bar|colorbar|legend|colour legend|scalar bar) [(of the {k}|for {o})]",
        "(no|without) (legend|colour bar|colorbar) [please]",
        "(i want|i d like) to see the (legend|colour bar|colorbar)",
        "(i don t want|i do not want) to see the (legend|colour bar) [anymore]",
        "(legend|colorbar|colour bar) (on|off)",
    ),
    "open_tool": (
        "3*(ouvre|ouvrez|affiche|montre|deplie) (la carte|l outil|le panneau) (des seuils|des coupes|des couleurs|des attributs|de navigation|de volumetrie|temps et realisations|du temps|de synchronisation des cameras|de la palette)",
        "3*(ouvre|ouvrez|affiche|montre) (l explorateur de donnees|l arbre|l arborescence|les attributs|la navigation|la volumetrie|les reglages des couleurs|la synchronisation des cameras|les slicers|le slicer)",
        "2*(ouvre|ouvrez) (les seuils|les coupes|les pas de temps|la colormap|la palette|les realisations)",
        "(je veux|j aimerais|peux tu ouvrir) (la carte|l outil) (des seuils|des coupes|de navigation|des attributs|de volumetrie)",
        "(carte|outil) (des seuils|des coupes|des couleurs|des attributs|de navigation|de volumetrie|temps et realisations) [(stp|svp)]",
        "(montre|affiche) moi (l arbre des donnees|l explorateur|les attributs) [de {o}]",
        "3*(open|show|display|bring up|expand) the (thresholds|slicers|attributes|navigation|volumetrics|colormap|time|camera sync|time and realizations) (card|tool|panel)",
        "3*(open|show|bring up) the (data explorer|data tree|tree|attributes|navigation|volumetrics|camera sync|slicers|colour settings|color settings)",
        "2*open the (thresholds|slicers|time steps|realizations|colormap)",
        "(i want|i d like) the (thresholds|slicers|attributes|navigation|volumetrics) card",
        "(thresholds|slicers|attributes|navigation|volumetrics|colormap) card [please]",
    ),
    "unsupported": (
        "2*(fais|prends) une (capture|capture d ecran|photo|image|copie d ecran) [(de la vue|de l ecran|de la scene)]",
        "(enregistre|sauvegarde|exporte) (une image|une capture|un png|un jpeg|la vue en image|une copie d ecran) [(de la vue|de l ecran)]",
        "imprime (la vue|l ecran|la scene)",
        "2*(exporte|copie|telecharge|enregistre) (les valeurs|les statistiques|les stats|le tableau|les donnees|la table|les resultats) (en|au format|dans un) (csv|excel|fichier csv|tableur)",
        "(exporte|export) (en|vers) (csv|excel)",
        "2*(ouvre|charge|importe) (un fichier|le fichier|un epc|un autre fichier|un nouveau fichier|un projet|le projet) [(epc|resqml|{o}|de {o})]",
        "(importe|ajoute) (des donnees|un fichier|un epc) (depuis|a partir de) (mon disque|mon ordinateur|un dossier)",
        "(connecte|connecte toi|branche toi) (a|au|sur) (osdu|un serveur osdu|un serveur etp|le serveur etp|l etp|un serveur)",
        "(charge|recupere|telecharge) (les donnees|un dataspace|un dataset) (depuis|du|d) (osdu|le serveur etp|un serveur etp)",
        "2*(rends|mets) (la grille|le modele|la surface|{o}|la vue|les puits) (transparente|transparent|semi transparente|translucide|plus transparente)",
        "(mets|regle|fixe|change) (l opacite|la transparence) [(de la grille|de {o}|a {n})]",
        "(opacite|transparence) (a|de) {n}",
        "2*(change|mets|passe) (la couleur du fond|le fond|l arriere plan|le fond de la vue) (en|a) (noir|blanc|bleu|{c})",
        "(fond|arriere plan) (noir|blanc|gris clair|sombre|clair)",
        "2*(montre|affiche|selectionne|surligne|donne moi|liste) les piliers [(de la grille|de {o}|qui touchent une faille|le long de la faille)]",
        "(montre|affiche) le pilier [numero ]{i}",
        "2*(lie|relie|synchronise|couple) les cameras [(des deux vues|des vues|entre les vues)]",
        "(synchronise|lie|relie) (les deux vues|les vues|la vue 1 et la vue 2)",
        "2*(ouvre|affiche|montre|active) (le globe|la terre|la vue globe|le globe terrestre)",
        "(place|positionne|situe) (le champ|le projet|les donnees|la grille) sur (le globe|la carte du monde|la terre)",
        "2*(decharge|decharger|dechargez) [(la grille|le puits|les donnees|tout|le fichier) ][{o}]",
        "ferme le fichier [(epc|courant)]",
        "(redemarre|relance|mets a jour) (l application|le serveur|paraview)",
        "(quel temps fait il|quelle heure est il|quel jour sommes nous) [(aujourd hui|demain|a paris)]",
        "(ecris|redige) (un poeme|une chanson|un mail|une lettre) [sur la geologie]",
        "(traduis|traduire) (ce texte|cette phrase) en (anglais|espagnol)",
        "(commande|reserve) (une pizza|un taxi|un billet de train|une salle de reunion)",
        "2*(take|make|grab|save) a (screenshot|screen capture|snapshot|picture) [(of the view|of the scene|of the screen)]",
        "(save|export) the view (as|to) (an image|a png|a picture|a jpeg)",
        "print the (view|screen|scene)",
        "2*(export|copy|download|save) the (values|statistics|stats|table|data|results) (to|as|in) (csv|excel|a csv file|a spreadsheet)",
        "(export|dump) [it ]to (csv|excel)",
        "2*(open|load|import) (a file|the file|an epc|another file|a new file|a project|the project) [(epc|resqml|from disk|{o})]",
        "(import|add) (data|a file|an epc) from (my disk|my computer|a folder)",
        "(connect|log in|hook up) to (osdu|an osdu server|an etp server|the etp server|the server)",
        "(fetch|load|download) (data|a dataspace|a dataset) from (osdu|the etp server|an etp server)",
        "2*make (the grid|the model|the surface|{o}|the wells|it) (transparent|semi transparent|translucent|see through|more transparent)",
        "(set|change|lower) the (opacity|transparency) [(of the grid|of {o}|to {n})]",
        "(opacity|transparency) (to|at) {n}",
        "2*(change|set|make) the background [(colour|color) ](to|in) (black|white|blue|{c})",
        "(black|white|dark|light) background [please]",
        "2*(show|display|select|highlight|list|give me) the pillars [(of the grid|of {o}|touching a fault|along the fault)]",
        "(show|display) pillar [number ]{i}",
        "2*(link|sync|synchronise|synchronize|couple|lock) the cameras [(of both views|of the views|between the views)]",
        "(link|sync|synchronize) (the two views|both views|the views)",
        "2*(open|show|display|switch to) the (globe|earth|globe view)",
        "(place|put|locate) the (field|project|data|grid) on the (globe|world map|earth)",
        "2*unload [(the grid|the well|the data|everything|the file) ][{o}]",
        "close the (file|epc|project)",
        "(restart|reinstall|update) the (application|server|app|paraview)",
        "(what time is it|what day is it|what s the date) [(today|now|in paris)]",
        "(write|draft) (a poem|a song|an email|a letter) [about geology]",
        "translate (this text|this sentence) (into|to) (french|spanish)",
        "(order|book) (a pizza|a taxi|a train ticket|a meeting room)",
    ),
    "help": (
        "aide", "aide moi", "que sais tu faire", "qu est ce que tu sais faire", "comment ca marche",
        "que peux tu faire", "quelles commandes", "bonjour", "salut", "tu fais quoi",
        "help", "help me", "what can you do", "how does this work", "which commands", "hello", "hi",
        "(is there|do you have) (some|any|a) (guidance|documentation|manual|tutorial|guide|instructions) [(on|about) (how to use|using) (this tool|this|the assistant)]",
        "(how do i|how to|how can i) (use|talk to|drive|work with) (this|this tool|the assistant|you)",
        "(what|which) (commands|sentences|requests|phrases) (do you understand|can i say|can i type|work)",
        "(y a t il|as tu|il y a) (une|de la|un) (aide|documentation|doc|notice|mode d emploi|tutoriel|guide) [(pour|sur) (utiliser|l outil|l assistant)]",
        "(comment|comment je) (t utilise|t utiliser|utiliser cet outil|me servir de toi|te parler|faire)",
        "(quelles|quel genre de) (phrases|commandes|demandes|requetes) (comprends tu|marchent|tu comprends|acceptes tu)",
        "(mode d emploi|manuel|documentation|tutoriel|instructions|guide|notice)",
    ),
}
PATTERNS = _P

_SLOT = re.compile(r"\{([okcnmpafijgvt])\}")


def _pick(rng, seq):
    return seq[int(rng.integers(len(seq)))]


def _number(rng, big=False):
    """A number as readers type it: a fraction (half the time with a
    decimal comma), a percentage or a large whole number; `big`, a whole
    number for a factor."""
    if big:
        return str(int(rng.integers(1, 200)))
    r = rng.random()
    if r < 0.4:
        v = f"{rng.random():.2f}".rstrip("0").rstrip(".") or "0"
        return v.replace(".", ",") if rng.random() < 0.5 else v
    if r < 0.7:
        return str(int(rng.integers(0, 100))) + _pick(rng, ("", "%", " %"))
    return str(int(rng.integers(0, 5000)))


_GROUP = re.compile(r"\(([^()\[\]]*)\)|\[([^()\[\]]*)\]")
_WEIGHT = re.compile(r"^(\d+)\*")


def weight(pattern):
    """A pattern said N times as often: "3*(montre|affiche) {o}" — the plain
    "verb + object" forms, which a handful of samples among a few dozen
    patterns would otherwise barely teach."""
    m = _WEIGHT.match(pattern)
    return int(m.group(1)) if m else 1


def _expand(rng, pattern):
    """(a b|c) one of the options, [x] x half of the time — innermost first,
    so they nest — then the bare one-word alternatives a|b."""
    s = _WEIGHT.sub("", pattern)
    while True:
        m = _GROUP.search(s)
        if not m:
            break
        if m.group(1) is not None:
            rep = _pick(rng, m.group(1).split("|"))
        else:
            rep = m.group(2) if rng.random() < 0.5 else ""
        s = s[:m.start()] + rep + s[m.end():]
    s = re.sub(r"(\S+(?:\|\S+)+)", lambda m: _pick(rng, m.group(1).split("|")), s)
    return re.sub(r"\s+", " ", s).strip()


def _pick_pattern(rng, pats):
    w = np.array([weight(p) for p in pats], dtype=float)
    return pats[int(rng.choice(len(pats), p=w / w.sum()))]


def _fill(rng, s):
    kinds = [w for v in lexicon.KINDS.values() for w in v["say"]]
    panels = [w for v in lexicon.PANELS.values() for w in v]
    presets = [w for v in lexicon.PRESETS.values() for w in v]
    axes = [w for v in lexicon.AXES.values() for w in v]
    fill = {"o": lambda: _pick(rng, OBJECTS), "k": lambda: _pick(rng, kinds),
            "n": lambda: _number(rng), "m": lambda: _number(rng),
            "p": lambda: _pick(rng, panels), "c": lambda: _pick(rng, presets),
            "a": lambda: _pick(rng, axes),
            "f": lambda: _pick(rng, ("", "x", "x ")) + _number(rng, big=True)
            if rng.random() < 0.3 else _number(rng, big=True)}
    # {i} {j}: whole numbers, j after i — layer indices, "the well 7"
    last = {"i": 1}

    def _i():
        last["i"] = int(rng.integers(1, 60))
        return str(last["i"])

    fill["i"] = _i
    fill["g"] = lambda: _pick(rng, [w for v in lexicon.GROUPS.values() for w in v])
    fill["v"] = lambda: _pick(rng, [w for v in lexicon.CATEGORIES.values() for w in v])
    fill["j"] = lambda: str(last["i"] + int(rng.integers(1, 40)))
    fill["t"] = lambda: _pick(rng, lexicon.TOPICS)
    return _SLOT.sub(lambda m: fill[m.group(1)](), s)


_POLITE = ("", "", "", "stp ", "svp ", "peux tu ", "please ", "can you ", "could you ", "merci de ")


def _noise(rng, s):
    """`s` as a reader may type it: a polite word, a closing word, a letter
    dropped or swapped, a capital."""
    if rng.random() < 0.3:
        s = _pick(rng, _POLITE) + s
    if rng.random() < 0.15:
        s = s + _pick(rng, (" stp", " merci", " please", " thanks", " !", " ?"))
    if rng.random() < 0.12 and len(s) > 6:
        i = int(rng.integers(1, len(s) - 1))
        op = rng.random()
        if s[i].isalpha():
            s = (s[:i] + s[i + 1:]) if op < 0.5 else (s[:i] + s[i + 1] + s[i] + s[i + 2:])
    if rng.random() < 0.2:
        s = s.capitalize()
    return s


def sentences(per_intent=400, seed=7):
    """[(sentence, intent)], `per_intent` of each, shuffled."""
    rng = np.random.default_rng(seed)
    out = []
    for intent in sorted(_P):
        pats = _P[intent]
        for _ in range(per_intent):
            out.append((_noise(rng, _fill(rng, _expand(rng, _pick_pattern(rng, pats)))), intent))
    order = rng.permutation(len(out))
    return [out[i] for i in order]


def objects():
    """The generator's objects, as the session hands its own to the engine."""
    out = [{"path": f"/gen/{i}", "title": t} for i, t in enumerate(OBJECTS)]
    # a categorical property listing every value the lexicon knows: in the
    # training sentences "huile" is then a <category>, as in a session
    # whose Fluids lists oil
    out.append({"path": "/gen/categories", "title": "Fluids_gen", "type": "CategoricalProperty",
                "categories": {i: c for i, c in enumerate(lexicon.CATEGORIES)}})
    return out
