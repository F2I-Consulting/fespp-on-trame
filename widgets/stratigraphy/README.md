# trame-fespp-stratigraphy

The stratigraphic column of a loaded data set: units in stratigraphic
order, each a coloured band, with the chronostratigraphic bracket the
RESQML file declares.

Pure display — the column is parsed server-side from the EPC XML parts by
`engine/stratigraphy.py` (no fesapi, no FESPP, no HDF5).

Two tabs, on top of everything (the PO, 31/10 and 01/11): the column the file
declares — its own bar (title, rank, summary), filters and notes under its
tab —, and the session's
**time-depth model** (`TimeDepthLaw`, the velocity model). The tab shown is
the host's (`tab` prop, `switch-tab` event), because the model tab carries
the host's own 3D in the `scene` slot, above the model and out of what
scrolls — kept mounted and hidden with the tab, so the remote view keeps its
stream; the host's title-bar strip lies over that 3D's top edge, inside the
slot, so it goes with the tab too.
