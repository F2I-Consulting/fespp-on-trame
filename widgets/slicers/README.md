# trame-fespp-slicers

The Slicers card of one 3D view: Enable on / off (the host turns it on
when the card opens), then Volume (one or more I/J/K boxes, every visible
one renders) or Slice (positioned cut planes along I, J and K); a two-thumb slider and a stepper per bound, clamped to the
grid's extent; "Copy from…" another view's slicing. Pure display: the
extent, the volumes, the cuts and their eyes come from the host
(`ui_slicers__<vid>`), a drag edits a local draft and the engine hears the
value on release; the events are `set-mode`, `set-volumes`,
`set-volumes-visible`, `set-positions`, `set-visibility` and `copy-from`.
The card frame names the grid it cuts.
