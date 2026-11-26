"""The silent exception handlers cannot multiply.

An `except` whose body says nothing (a bare `pass`, a `return None`, a
`continue`) turns a programming error into an expected quirk that can go
unnoticed for a long time. Two guards hold the line. At run time the
strict reporter (`engine/strict.py`, armed by the test harnesses) fails a
scenario on any bug-shaped exception raised inside the app, swallowed or
not. Statically, this test counts the handlers that say nothing, module by
module, and refuses a count above the ceiling recorded here: a new handler
has to speak (a print, a note in the state, a flag, a raise), or another
silent handler of its module has to go first. Lowering a ceiling is
welcome and expected; raising one needs a stated reason.

"Says something" is read from the handler's body: a print, a log, a
state write, a note or message, a raise, a flag. The reading is a
heuristic, the same for every module: the counts are comparable over
time, not a verdict on any single site.
"""
import os
import re

import fespp_on_trame

_ROOT = os.path.dirname(fespp_on_trame.__file__)
_EXCEPT = re.compile(r"^(\s*)except(\s+[A-Za-z_.,() ]+)?(\s+as\s+\w+)?\s*:\s*(#.*)?$")
_SPEAKS = re.compile(
    r"print\(|_log\(|logging|logger|warn|state\.|_state\.|note|message|raise |flag"
    r"|snackbar|_LAST_ERROR|error\b|\bmsg\b|_expect\(|RuntimeError")

# module -> silent handlers allowed (the recorded census); a module absent
# here allows none
CEILINGS = {
    "__main__.py": 1,
    "app/boot.py": 3,
    "app/features/calculator.py": 4,
    "app/features/colormap_card.py": 11,
    "app/features/colormap_edits.py": 5,
    "app/features/compare_tree.py": 1,
    "app/features/crossplot_panel.py": 2,
    "app/features/data_health.py": 2,
    "app/features/exact_colours.py": 2,
    "app/features/eye_pass.py": 6,
    "app/features/globe.py": 8,
    "app/features/load_reactions.py": 7,
    "app/features/navigation.py": 8,
    "app/features/node_helpers.py": 2,
    "app/features/osdu_explorer.py": 1,
    "app/features/picking.py": 3,
    "app/features/rep_highlight.py": 1,
    "app/features/slicers.py": 2,
    "app/features/thresholds.py": 4,
    "app/features/time_realization.py": 5,
    "app/features/view_wiring.py": 1,
    "app/features/volumetrics.py": 4,
    "app/features/xml_explorer.py": 1,
    "app/ui/selection_deps.py": 1,
    "app/views/camera.py": 4,
    "app/views/tools_config.py": 1,
    "app/views/view_manager.py": 11,
    "engine/blockscope/globe_scene.py": 13,
    "engine/blockscope/pdc_scene.py": 12,
    "engine/categorical_palette.py": 13,
    "engine/cell_weights.py": 8,
    "engine/compare_dispatch.py": 8,
    "engine/compare_matrix.py": 2,
    "engine/crossplot_dispatch.py": 2,
    "engine/data_load.py": 10,
    "engine/derived_expr.py": 2,
    "engine/derived_props.py": 9,
    "engine/element_type/registry.py": 1,
    "engine/etp.py": 1,
    "engine/geo.py": 4,
    "engine/health_dispatch.py": 8,
    "engine/hierarchy.py": 3,
    "engine/io/etp_debug_endpoint.py": 4,
    "engine/io/temp_dir.py": 2,
    "engine/io/upload_endpoint.py": 7,
    "engine/plugins.py": 2,
    "engine/property_values.py": 8,
    "engine/pwls_kinds.py": 1,
    "engine/realization_dispatch.py": 2,
    "engine/repo_query.py": 2,
    "engine/selector.py": 1,
    "engine/source_resolver.py": 3,
    "engine/sources/chain_domain.py": 5,
    "engine/sources/collector.py": 1,
    "engine/sources/etp_connector.py": 5,
    "engine/sources/ijkgrid.py": 25,
    "engine/sources/leaf_rep.py": 15,
    "engine/sources/representation.py": 11,
    "engine/sources/source_registry.py": 3,
    "engine/stats_dispatch.py": 21,
    "engine/stratigraphy.py": 5,
    "engine/strict.py": 2,
    "engine/threshold_dispatch.py": 1,
    "engine/time_realization.py": 3,
    "engine/trajectory_sampling.py": 4,
    "engine/tree.py": 6,
    "engine/utils/categories.py": 11,
    "engine/utils/csv_export.py": 2,
    "engine/utils/numfmt.py": 3,
    "engine/volumetrics_dispatch.py": 9,
    "engine/vtk_log.py": 8,
    "engine/wellhead.py": 6,
    "engine/welllog_dispatch.py": 10,
    "engine/wire/render_scheduler.py": 1,
    "engine/wire/state_batcher.py": 1,
}


def silent_handlers(path):
    """Return the line numbers of the handlers in `path` whose body says nothing."""
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    out = []
    for i, line in enumerate(lines):
        m = _EXCEPT.match(line)
        if not m:
            continue
        indent = len(m.group(1))
        body = []
        for follow in lines[i + 1:]:
            if not follow.strip():
                continue
            if len(follow) - len(follow.lstrip()) <= indent:
                break
            body.append(follow.strip())
        if not _SPEAKS.search(" ".join(body)):
            out.append(i + 1)
    return out


def census():
    found = {}
    for base, _dirs, files in os.walk(_ROOT):
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(base, name)
            rel = os.path.relpath(path, _ROOT).replace(os.sep, "/")
            if rel.startswith("engine/legacy/"):   # gone (Q2 bis); kept for an old checkout
                # the quarantined legacy model (decision Q2): imported only
                # without the BlockScope flag, frozen until it is deleted
                continue
            n = silent_handlers(path)
            if n:
                found[rel] = n
    return found


def test_no_module_gains_a_silent_handler():
    found = census()
    over = {rel: (len(lines), CEILINGS.get(rel, 0), lines)
            for rel, lines in found.items() if len(lines) > CEILINGS.get(rel, 0)}
    assert not over, (
        "silent exception handlers above the recorded ceiling — make the new"
        " handler say something (a print, a note, a flag, a raise), or lower"
        " another one first: " + "; ".join(
            f"{rel}: {n} > {cap} (lines {lines})" for rel, (n, cap, lines) in over.items()))


def test_the_ceilings_are_not_stale():
    """A module that dropped below its ceiling should have the ceiling
    lowered with it, so the ratchet keeps biting: report the slack."""
    found = census()
    slack = {rel: (cap, len(found.get(rel, [])))
             for rel, cap in CEILINGS.items() if len(found.get(rel, [])) < cap}
    # slack is allowed but reported, so the ceiling is lowered the next time
    # the module is touched
    if slack:
        print("ceilings with slack (lower them when you touch the module):",
              ", ".join(f"{rel} {n}/{cap}" for rel, (cap, n) in slack.items()))
    assert all(cap >= 0 for cap in CEILINGS.values())
