# trame-fespp-calculator

Derived-property calculator panel, wearing the panel frame (`fp-panel`):
the grid, the name, the unit and the type in the bar, Create / Update at
the right; then the property chips (the `+` of a chip appends its
identifier — no typing, no typos; the chip itself is the name, which a
button written in Title case could not be), the Insert list (functions and
operators, a select that goes back to its word once the pick has landed),
the templates, the formula box, the validation (an error is a band with its
next step), the live preview stats, the P10/P50/P90 uncertainty row, the
A − B row, and the list of existing recipes with their acts.

Pure display + events: parsing, binding, evaluation and refusals all live
server-side in `engine/derived_props`.
