# trame-fespp-health

The Data health panel: what is wrong with the loaded data — partial
objects, unreadable datasets, kinds, units, CRS, declared bounds — as one
table with its counts by severity, a Refresh, Copy CSV, and a focus on one
object when another panel sends the reader here. Pure display: the table
is `engine/health_dispatch`'s payload (`data`), `focus` names the row to
scroll to, the events are `refresh` and `activate` (a row's object made the
active node).
