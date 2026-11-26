# trame-fespp-volumetrics

The Volumetrics card of one 3D view: GRV → NRV → PV → HCPV per fluid zone
and region from the grid's own properties — and, with the surface factors,
STOIIP / GIIP and the recoverable part. The grid, Compute and Copy CSV on
the first row; then ONE line of chips saying what the card understood
(the terms, the contacts, the factors) with an Edit button, behind which
sit the terms (porosity, NTG, Sw, region), the contacts (GOC, OWC, exact
fields; a box draws them in the 3D view, greyed until a contact is typed) and the Surface line (Bo, Bg, RF oil,
RF gas, optional — each adds its column). Above the table, one display
unit per family of columns (reservoir m³ / rbbl, oil stb, gas scf), each
select shown only with its columns; the CSV stays in (standard) cubic
metres. Pure display: `data` is `engine/volumetrics_dispatch`'s payload
(the grids, the properties, the parameters, the rows and totals, the note,
the CSV name and header); the events are `set([key, value])` and
`compute`. The card frame names the grid.
