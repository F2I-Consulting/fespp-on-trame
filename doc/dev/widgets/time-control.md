# Widget: Time control (per-view)

Time-series playback for **this view**. Shown only when the view holds a
TimeSeries / multi-realization-time-series rep.

## Scope
Per-view — scoped to a `view_id`.

## Input
- `view_id`.
- Whether this view has a TS rep (`panel_has_ts`).

## Behaviour
- Time slider + play / stop + speed (0.25×–5×). Scrubs the time index for
  **this view's** time-series reps; the displayed array swaps per time step.
- Optional realization picker (for multi-realization series).

## Reads
- This view's active time index + realization **[per-view]**, the TS array set.

## Writes (back-end / global)
- **[per-view]** time index / realization → re-colour / re-extract the TS arrays
  in this view → render. No cross-view sync.

## Notes / open
- v1 already keeps time per-view (with a divergence-detect + resync button across
  views). In v2 it is simply **local** to the panel — the divergence/resync
  machinery disappears (each view is independent by construction).
