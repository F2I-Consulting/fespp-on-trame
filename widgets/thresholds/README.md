# trame-fespp-thresholds

The Thresholds card of one 3D view: a chain of thresholds on the
properties of the view's IJK grid — a new root is a union with the other
roots, a chain under an entry an intersection — each entry with its kind
chip, a two-thumb slider (categories picked by name, whole numbers for a
discrete property), an eye and a delete. Pure display: the chain and the
arrays come from the host (`ui_thresholds__<vid>`), a precondition not met
(the active object is not the grid) is the empty state's why, or a band
over the chain; the events are `add([array, parent])`, `remove(name)`,
`set-range([name, [lo, hi]])` and `set-visible([name, visible])`.
