"""When a panel button of the top bar can act — its `disabled` and its
tooltip as trame expressions.

The PO, 28/10: "si pas utilisable rien à faire en enabled". Before any
data every panel button is greyed ("import a file first"); after, a panel
whose data is not there is greyed too, its tooltip saying what it needs.
The facts are `ui_data_facts` (app/features/data_facts); a fact missing
from it never greys a button.
"""

# need -> (the JS condition that it is NOT met, what the tooltip says: a
# text, or a JS expression in a 1-tuple)
NEEDS = {
    "crs": ("!ui_globe_ok", ("ui_globe_why",)),
    "properties": ("(ui_data_facts || {}).properties === 0",
                   "the loaded data has no property"),
    "wells": ("(ui_data_facts || {}).wells === 0",
              "the loaded data has no wellbore"),
    "strati": ("(ui_data_facts || {}).strati === 0",
               "the loaded data declares no stratigraphic column"),
    "logs_and_grid": ("((ui_data_facts || {}).logs === 0"
                      " || (ui_data_facts || {}).grid_properties === 0)",
                      "it needs wellbore logs and a grid property"),
}
NO_DATA = "import a file first"


def gate(title, need=None):
    """``(disabled, tooltip)`` of a top-bar panel button: trame
    expressions. `title` carries no single quote (it is quoted in JS)."""
    if need is None:
        return ("!ui_has_data",), (f"ui_has_data ? '{title}' : '{title} — {NO_DATA}'",)
    cond, why = NEEDS[need]
    why = why[0] if isinstance(why, tuple) else f"'{why}'"
    return ((f"!ui_has_data || {cond}",),
            (f"!ui_has_data ? '{title} — {NO_DATA}'"
             f" : ({cond}) ? '{title} — ' + {why} : '{title}'",))
