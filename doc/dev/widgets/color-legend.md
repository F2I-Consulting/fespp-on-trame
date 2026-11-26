# Widget: Colour legend (per-view)

The scalar bar for **this view's** active coloured property.

## Scope
Per-view — scoped to a `view_id`.

## Input
- `view_id`.
- The active node + its coloured array in this view.

## Behaviour
- Shows the LUT scalar bar of **this view's active node's** coloured property.
- **Single-bar policy** (already agreed): exactly one bar — the active node's;
  if the active node has no active property, **no bar**.
- Optional: title shows the property (and, if needed later, the rep name to
  disambiguate same-named properties across reps).

## Reads
- This view's `active_color_array_path` / `_name` **[per-view]**, the
  per-`(scene, array)` LUT (scoped `f"{base}__{view_id}"`).

## Writes (back-end / global)
- **[per-view]** scalar-bar visibility in this view's pv_view. No global state.

## Notes / open
- In v2 the "single active colorbar" policy is **naturally per-view** — each view
  shows its own active node's bar, with no cross-view marshalling. (In v1 this
  needed the `show_only_active_bar` helper reconciling one policy across views.)
