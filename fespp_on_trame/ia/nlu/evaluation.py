"""How the command engine is measured — one place for scripts/train_nlu.py and
tests/unit/test_nlu.py, so a score means the same thing everywhere.

The hand-written sets of tests/unit/data, one JSON object per line ({"text",
"intent"} plus the parameters the sentence states):

    nlu_eval       written by hand, never tuned on
    nlu_dev_*      by independent writers, open for tuning (nlu_dev2_*: the
                   view's gestures — camera, time, styles, cards)
    nlu_journal    the sentences of real sessions, each with the context the
                   application held when it was typed (the last command that
                   worked) and the session it was typed in; open
    nlu_regress_*  sentences once read wrong, pinned with their right
                   reading (the targets, whether the reading is sure, the
                   next requests' readings included); open
    nlu_heldout*   sealed: scored, never shown — a sentence read is a
                   sentence tuned on

A row reads against its own "objects", the session its "session" names
(SESSIONS; a name no session has is an error), or the default objects of
the set — plus the bare titles its "objects" may list instead. A row whose
"intent" is null names no command of the catalogue: the right reading is
"not understood", or "unsupported" (a request the assistant cannot do yet;
neither touches the view). A row may carry "then": the commands of the next requests
of the sentence, cut apart by multi.split as the application does — a
command's name, or a row of its own (its intent and the parameters it
states).

Three numbers per set: the command (intent), its parameters (each slot the
row states, exact, among the rows whose command is right; "targets" the
titles of the objects acted on, "sure" whether the application acts without
asking), and the readings the engine is SURE of and gets wrong — the ones
the application carries out without asking.
"""
import json
import os

from fespp_on_trame.ia.nlu import corpus, multi

DATA_DIR = corpus.EVAL_DIR

# the objects the hand-written sentences refer to (a Volve-like project)
OBJECTS = [
    {"path": "/g/hugin", "title": "Hugin", "type": "IjkGrid"},
    {"path": "/g/hugin/phit", "title": "PHIT", "type": "ContinuousProperty", "kind": "total porosity",
     "parent": "/g/hugin"},
    {"path": "/g/hugin/perm", "title": "PERMX", "type": "ContinuousProperty", "kind": "permeability",
     "parent": "/g/hugin"},
    {"path": "/g/hugin/ntg", "title": "NTG", "type": "ContinuousProperty", "kind": "net to gross ratio",
     "parent": "/g/hugin"},
    {"path": "/w/f4", "title": "15/9-F-4", "type": "WellboreFeature"},
    {"path": "/w/f4/gr", "title": "GR", "type": "WellboreFrameRepresentation", "kind": "gamma ray",
     "parent": "/w/f4"},
    {"path": "/w/f11", "title": "15/9-F-11 A", "type": "WellboreFeature"},
    {"path": "/s/top", "title": "Top Hugin", "type": "Grid2dRepresentation"},
]
# … and a richer session for the writers' sets: a second grid whose name
# ends like a French word ("Draupne fine"), a saturation, a facies
EVAL_OBJECTS = OBJECTS + [
    {"path": "/g/hugin/sw", "title": "SW", "type": "ContinuousProperty", "kind": "water saturation",
     "parent": "/g/hugin"},
    {"path": "/g/hugin/facies", "title": "Facies", "type": "DiscreteProperty", "kind": "facies type",
     "parent": "/g/hugin"},
    {"path": "/g/draupne", "title": "Draupne fine", "type": "IjkGrid"},
    {"path": "/g/draupne/poro", "title": "Poro", "type": "ContinuousProperty", "kind": "porosity",
     "parent": "/g/draupne"},
    {"path": "/w/f12", "title": "15/9-F-12", "type": "WellboreFeature"},
    {"path": "/s/base", "title": "Base Hugin", "type": "Grid2dRepresentation"},
]


def _volve():
    """The Volve session of the real journal: the grid with its Fluids (water,
    oil, gas), a water saturation and the fault blocks, its zone
    sub-representations, thirteen wells with their logs."""
    g = "/v/grid"
    out = [{"path": g, "title": "Volve_SGrid", "type": "IjkGrid"}]

    def prop(path, title, kind="", typ="ContinuousProperty", parent=g, cats=None):
        d = {"path": path, "title": title, "type": typ, "kind": kind, "parent": parent,
             "rep_type": "IjkGrid" if parent == g else "Wellbore"}
        if cats:
            d["categories"] = cats
        return d

    out += [prop(g + "/fluids", "Fluids", "", "CategoricalProperty", cats={0: "water", 1: "oil", 2: "gas"}),
            prop(g + "/watsat", "WatSat", "water saturation"),
            prop(g + "/fb", "fault_blocks", "", "DiscreteProperty")]
    for zone in ("GasZone", "OilZone", "WaterZone"):
        out.append({"path": f"/v/sub_{zone}", "title": f"Volve_SGrid_{zone}", "type": "Sub"})
    wells = ("NO_15_9-F-15_A_1739B7", "NO_15_9-F-11_T2_4BEC81", "NO_15_9-19_SR_EBECD2", "NO_15_9-F-14_B6CE15",
             "NO_15_9-F-4_5DA715", "NO_15_9-19_A_B5088C", "NO_15_9-F-12_DC912C", "NO_15_9-F-1_A_84B691",
             "NO_15_9-F-15_0320E3", "NO_15_9-F-9_44FD2F", "NO_15_9-F-1_A3EF7D", "NO_15_9-19_BT2_25E8AC",
             "NO_15_9-F-5_B75BED")
    for i, w in enumerate(wells):
        wp = f"/v/w{i}"
        out.append({"path": wp, "title": f"well_feature_{w}", "type": "Wellbore", "trajectory": wp + "/traj"})
        out += [prop(wp + "/fac", "Facies_Wilfried", "facies", "CategoricalProperty", parent=wp,
                     cats={0: "Sand", 1: "Shale", 2: "Silt"}),
                prop(wp + "/rhob", "RHOB_WIL", "bulk density", parent=wp),
                prop(wp + "/sw", "SW", "water saturation", parent=wp),
                prop(wp + "/dt", "DT_EDIT", "", parent=wp),
                prop(wp + "/pick", "Pick_(Depth)", "measured depth", parent=wp)]
        if i % 3 == 0:
            out += [prop(wp + "/fcode", "FACIES_WIL_CODE", "facies", "DiscreteProperty", parent=wp),
                    prop(wp + "/gm", "GM09_FACIES", "facies", "CategoricalProperty", parent=wp,
                         cats={0: "Sand", 1: "Shale"}),
                    prop(wp + "/rw", "RW_RES", "", parent=wp), prop(wp + "/vf", "VOLVE_FACIES", "facies", parent=wp),
                    prop(wp + "/dta", "DT_AAKA_EDIT", "", parent=wp),
                    prop(wp + "/swat", "SWAT", "water saturation", parent=wp)]
    return out


_FV = "/data/_gridfolder_v/_propsfolder_v/_v"
# a small Volve-like grid whose values are said by name: the Fluids (water,
# oil, gas), a lithology, a water saturation, two wells and a facies log
FLUIDS = [
    {"path": _FV, "title": "Volve_SGrid", "type": "IjkGrid"},
    {"path": _FV + "/_f", "title": "Fluids", "type": "CategoricalProperty", "parent": _FV,
     "categories": {0: "water", 1: "oil", 2: "gas"}},
    {"path": _FV + "/_l", "title": "Lithology1", "type": "CategoricalProperty", "parent": _FV,
     "categories": {0: "Shale", 1: "Sandstone", 2: "Siltstone", 3: "Limestone"}},
    {"path": _FV + "/_w", "title": "WatSat", "type": "ContinuousProperty", "kind": "saturation", "parent": _FV},
    {"path": "/data/_w1", "title": "well_feature_NO_15_9-F-1_ABC", "type": "Wellbore"},
    {"path": "/data/_w2", "title": "well_feature_NO_15_9-F-2_ABC", "type": "Wellbore"},
    {"path": "/data/_w1/_fa", "title": "Facies_Wilfried", "type": "CategoricalProperty", "kind": "facies",
     "parent": "/data/_w1", "categories": {0: "Sand", 1: "Shale"}},
]


def _drogon():
    """The Drogon project: a grid and its properties (a facies with a
    Channel value), horizons named in camel case (TopVolantis), its zones,
    twelve wells with two logs each."""
    g = "/data/_g"

    def prop(title, kind, typ="ContinuousProperty", parent=g, **more):
        return dict({"path": f"{parent}/{title}", "title": title, "type": typ, "kind": kind, "parent": parent},
                    **more)

    out = [{"path": g, "title": "Geogrid", "type": "IjkGrid"},
           prop("Total Porosity", "porosity"), prop("Water Saturation", "saturation"),
           prop("Horizontal Permeability", "rock permeability"), prop("Net-to-Gross Ratio (PEM)", "net to gross ratio"),
           prop("Facies", "facies", "CategoricalProperty",
                categories={0: "Floodplain", 1: "Channel", 2: "Crevasse", 3: "Coal"}),
           prop("Zone Index", "", "DiscreteProperty"), prop("Fault Block Index", "", "DiscreteProperty"),
           prop("Temperature", "thermodynamic temperature")]
    out += [{"path": f"/h/{t}", "title": t, "type": "Grid2dRepresentation"}
            for t in ("TopVolantis", "TopTherys", "TopVolon", "BaseVolantis")]
    out += [{"path": f"/z/{t}", "title": t, "type": "Sub"} for t in ("Valysar", "Therys", "Volon")]
    for w in ("55/33-A-1", "55/33-A-2", "55/33-A-3", "55/33-A-4", "55/33-A-5", "55/33-A-6", "55/33-1", "55/33-2",
              "55/33-3", "OP5_Y1", "OP5_Y2", "OP6"):
        wp = "/w/" + w.replace("/", "_")
        out += [{"path": wp, "title": w, "type": "WellboreFeature"},
                prop("Total Porosity (Original Log)", "porosity", "WellboreFrameRepresentation", parent=wp),
                prop("Bulk Density", "bulk density", "WellboreFrameRepresentation", parent=wp)]
    return out


# titles that look like everyday words or numbers: Top Reservoir, a water
# saturation WatSat, mnemonics joined to a number or a word, wells whose
# names end in numbers (25/11-15, 15/9-19 A), a zone K1, a facies of values
TRAPS = OBJECTS + [
    {"path": "/s/topres", "title": "Top Reservoir", "type": "Grid2dRepresentation"},
    {"path": "/g/hugin/watsat", "title": "WatSat", "type": "ContinuousProperty", "kind": "water saturation",
     "parent": "/g/hugin"},
    {"path": "/g/hugin/ntg24", "title": "NTG_2024", "type": "ContinuousProperty", "kind": "net to gross ratio",
     "parent": "/g/hugin"},
    {"path": "/g/hugin/phitf", "title": "PHIT_final", "type": "ContinuousProperty", "parent": "/g/hugin"},
    {"path": "/w/2511", "title": "25/11-15", "type": "WellboreFeature"},
    {"path": "/w/159_19", "title": "15/9-19 A", "type": "WellboreFeature"},
    {"path": "/z/k1", "title": "K1", "type": "Sub"},
    {"path": "/g/hugin/fac", "title": "Facies", "type": "CategoricalProperty", "parent": "/g/hugin",
     "categories": {0: "Sandstone", 1: "Shale", 2: "Coal"}},
]
# a property titled with a little word (SO), a horizon titled with a letter
# (J), a zone K1
LITTLE = OBJECTS + [
    {"path": "/g/hugin/so", "title": "SO", "type": "ContinuousProperty", "kind": "oil saturation",
     "parent": "/g/hugin"},
    {"path": "/g/hugin/sw2", "title": "SW", "type": "ContinuousProperty", "kind": "water saturation",
     "parent": "/g/hugin"},
    {"path": "/s/j", "title": "J", "type": "Grid2dRepresentation"},
    {"path": "/z/k1", "title": "K1", "type": "Sub"},
]
# the session the second sealed sets are written against: a Volve-like
# project whose titles trap a reader (PHIT, WatSat, Top Reservoir), two
# categorical properties, three wells, a log, two surfaces
HELDOUT2_OBJECTS = [
    {"path": "/g/volve", "title": "Volve_SGrid", "type": "IjkGrid"},
    {"path": "/g/volve/phit", "title": "PHIT", "type": "ContinuousProperty", "kind": "porosity",
     "parent": "/g/volve"},
    {"path": "/g/volve/permx", "title": "PERMX", "type": "ContinuousProperty", "kind": "permeability",
     "parent": "/g/volve"},
    {"path": "/g/volve/watsat", "title": "WatSat", "type": "ContinuousProperty", "kind": "water saturation",
     "parent": "/g/volve"},
    {"path": "/g/volve/ntg", "title": "NTG", "type": "ContinuousProperty", "kind": "net to gross",
     "parent": "/g/volve"},
    {"path": "/g/volve/fluids", "title": "Fluids", "type": "CategoricalProperty", "kind": "fluids",
     "parent": "/g/volve", "categories": {"1": "water", "2": "oil", "3": "gas"}},
    {"path": "/g/volve/litho", "title": "Lithology1", "type": "CategoricalProperty", "kind": "facies",
     "parent": "/g/volve", "categories": {"0": "Shale", "1": "Sandstone", "2": "Siltstone", "3": "Limestone"}},
    {"path": "/g/hugin", "title": "Hugin", "type": "IjkGrid"},
    {"path": "/g/hugin/poro", "title": "Poro", "type": "ContinuousProperty", "kind": "porosity",
     "parent": "/g/hugin"},
    {"path": "/w/f4", "title": "15/9-F-4", "type": "WellboreFeature"},
    {"path": "/w/f4/gr", "title": "GR", "type": "WellboreFrameRepresentation", "kind": "gamma ray",
     "parent": "/w/f4"},
    {"path": "/w/f12", "title": "15/9-F-12", "type": "WellboreFeature"},
    {"path": "/w/f11a", "title": "15/9-F-11 A", "type": "WellboreFeature"},
    {"path": "/s/top", "title": "Top Reservoir", "type": "Grid2dRepresentation"},
    {"path": "/s/base", "title": "Base Hugin", "type": "Grid2dRepresentation"},
]

# the sessions a row may name ("session": "volve")
SESSIONS = {"volve": _volve(), "fluids": FLUIDS, "drogon": _drogon(), "traps": TRAPS, "little": LITTLE,
            "objects": OBJECTS, "eval": EVAL_OBJECTS, "heldout2": HELDOUT2_OBJECTS}

# the open sets and the objects each reads against; the sealed ones are
# listed apart, so no code prints their sentences by mistake
OPEN_SETS = (("nlu_eval.jsonl", OBJECTS), ("nlu_dev_fr.jsonl", EVAL_OBJECTS), ("nlu_dev_en.jsonl", EVAL_OBJECTS),
             ("nlu_journal.jsonl", EVAL_OBJECTS), ("nlu_regress_fr.jsonl", EVAL_OBJECTS),
             ("nlu_regress_en.jsonl", EVAL_OBJECTS), ("nlu_dev2_fr.jsonl", EVAL_OBJECTS),
             ("nlu_dev2_en.jsonl", EVAL_OBJECTS))
SEALED_SETS = (("nlu_heldout_fr.jsonl", EVAL_OBJECTS), ("nlu_heldout_en.jsonl", EVAL_OBJECTS),
               ("nlu_heldout2_fr.jsonl", HELDOUT2_OBJECTS), ("nlu_heldout2_en.jsonl", HELDOUT2_OBJECTS),
               ("nlu_heldout3_fr.jsonl", EVAL_OBJECTS), ("nlu_heldout3_en.jsonl", EVAL_OBJECTS))

# the parameters a row may state, compared one by one
SLOT_KEYS = ("kind", "category", "categories", "panel", "preset", "axis", "on", "factor", "min", "max",
             "exclude", "well_filter", "raw", "direction", "step", "style", "scale", "tool", "targets", "sure")


def rows(name, data_dir=DATA_DIR):
    """The rows of a set, [] when the file is absent."""
    path = os.path.join(data_dir, name)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def objects_of(row, default):
    """The session a row is read against: its own objects, the session it
    names, or the default — to which bare titles a row lists are added. A
    session no SESSIONS entry holds is an error: read against the default,
    the row would measure another session than its writer's."""
    own = row.get("objects") or ()
    if own and all(isinstance(o, dict) for o in own):
        return list(own)
    name = row.get("session")
    if name is not None and name not in SESSIONS:
        raise ValueError(f"unknown session {name!r}: one of {sorted(SESSIONS)}")
    base = SESSIONS[name] if name is not None else default
    have = {o.get("title") for o in base}
    return list(base) + [{"path": f"/row/{i}", "title": str(t)} for i, t in enumerate(own)
                         if not isinstance(t, dict) and str(t) not in have]


def same(want, got):
    """Does a slot read match the one stated? Numbers within a rounding, a
    switch by its truth (absent is off), nothing as nothing (null, an empty
    list), names without case, lists in order, a dict key by key."""
    if isinstance(want, bool):
        return bool(got) is want
    if want is None:
        return got is None or got == [] or got == "" or got is False
    if isinstance(want, dict):
        return isinstance(got, dict) and all(same(v, got.get(k)) for k, v in want.items())
    if got is None or isinstance(got, bool):
        return False
    if isinstance(want, (int, float)):
        return isinstance(got, (int, float)) and abs(float(want) - float(got)) <= 1e-6 * max(1.0, abs(want))
    if isinstance(want, list):
        return isinstance(got, (list, tuple)) and len(want) == len(got) and all(
            same(w, g) for w, g in zip(want, got))
    return str(want).lower() == str(got).lower()


def readings(row, default, m=None, split=True):
    """The engine's readings of a row as the application makes them: the
    sentence cut into its requests (multi.split), each part parsed with the
    context the row carries. Without `split`, the whole sentence at once."""
    from fespp_on_trame.ia.nlu.engine import parse
    objs = objects_of(row, default)
    ctx = row.get("context") if isinstance(row.get("context"), dict) else None
    parts = multi.split(row["text"]) if split else [row["text"]]
    if len(parts) <= 1:
        parts = [row["text"]]
    return [parse(p, objs, m, context=ctx) for p in parts]


def stated(row, reading):
    """{key: matches} for each parameter `row` states of `reading` (a
    parse result): the slots, the titles acted on ("targets", in any
    order), whether the reading is sure."""
    out = {}
    for key in SLOT_KEYS:
        if key not in row:
            continue
        if key == "targets":
            got = sorted(str(t.get("title")) for t in reading.get("targets") or ())
            out[key] = sorted(str(t) for t in row[key]) == got
        elif key == "sure":
            out[key] = bool(reading.get("sure")) is bool(row[key])
        else:
            out[key] = same(row[key], (reading.get("slots") or {}).get(key))
    return out


def same_intent(want, got):
    """Is the command read the one wanted? A row that names no command
    (null) is read right as "not understood" or as "unsupported" — the
    request the assistant cannot do yet: neither touches the view."""
    return got == want or (want is None and got == "unsupported")


def wrong(row, default, m=None, split=True):
    """What the engine reads wrong in `row`, read as the application reads
    it: [] when every request's command and every parameter it states are
    right, else the faults ("intent", "then[1].intent", "min"…)."""
    got = readings(row, default, m, split)
    out = [] if same_intent(row.get("intent"), got[0]["intent"]) else ["intent"]
    out += [k for k, good in stated(row, got[0]).items() if not good]
    for k, nxt in enumerate(row.get("then") or (), 1):
        if k >= len(got):
            out.append(f"then[{k}] missing")
            continue
        want = nxt.get("intent") if isinstance(nxt, dict) else nxt
        if not same_intent(want, got[k]["intent"]):
            out.append(f"then[{k}].intent")
        if isinstance(nxt, dict):
            out += [f"then[{k}].{key}" for key, good in stated(nxt, got[k]).items() if not good]
    return out


def score(items, default, m=None, split=True):
    """{"n", "right", "full", "sure", "sure_wrong", "slots": {key: [right,
    stated]}, "misses": [(text, wanted, got, confidence, sure)]} over
    `items`. A row is right when the first request's command is the one
    wanted and, when the row lists the next ones ("then"), each of them too;
    "full" counts the right rows whose stated parameters are all read — the
    next requests' included when "then" states them."""
    out = {"n": 0, "right": 0, "full": 0, "sure": 0, "sure_wrong": 0, "slots": {}, "misses": []}
    for row in items:
        got = readings(row, default, m, split)
        first = got[0]
        want = row.get("intent")
        ok = same_intent(want, first["intent"])
        then = list(row.get("then") or ())
        for k, nxt in enumerate(then):
            nxt = nxt.get("intent") if isinstance(nxt, dict) else nxt
            ok = ok and k + 1 < len(got) and same_intent(nxt, got[k + 1]["intent"])
        sure = bool(first.get("sure"))
        out["n"] += 1
        out["right"] += ok
        out["sure"] += sure
        out["sure_wrong"] += sure and not ok
        if not ok:
            out["misses"].append((row["text"], want, first["intent"], first.get("confidence", 0.0), sure))
            continue
        full = True
        for key, good in stated(row, first).items():
            n_ok = out["slots"].setdefault(key, [0, 0])
            n_ok[1] += 1
            n_ok[0] += good
            full = full and good
        for k, nxt in enumerate(then):
            if isinstance(nxt, dict):
                full = full and all(stated(nxt, got[k + 1]).values())
        out["full"] += full
    return out


def slot_line(res):
    """The per-slot scores, one line: "kind 98/100 min 40/41 …"."""
    return " ".join(f"{k} {v[0]}/{v[1]}" for k, v in sorted(res["slots"].items()))
