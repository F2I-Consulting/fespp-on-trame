# trame-fespp-reconcile

The Log ↔ Grid panel, wearing the panel frame: every checked log of the log
view's wells against the grid property of its kind sampled along the
trajectory, zone by zone — the means, the medians, Δ, z — with the sampling
step, a well filter, Refresh, Auto-pair and Copy CSV in the bar, the pairs
(auto by kind, editable) as chips in the sub-bar, a sortable table. Pure
display: `data` is `engine/reconcile_dispatch`'s payload; the events are
`compute([step])`, `auto-pairs` and `set-pairs(pairs)`. The empty state
carries the server's note as its why.
