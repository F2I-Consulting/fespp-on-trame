# trame-fespp-timereal

A **decoupled** Trame widget: the fespp-on-trame **per-view time & realization
controls** (custom Vue, no Vuetify) — a per-panel TimeControl and
RealizationPicker in one card.

- **Time**: first / previous / play-stop / next / last, play speed, the time
  label and a slider — applied to THIS view only (`view.ViewTime`), so two
  views can show different time steps side by side.
- **Realizations**: one row per multi-realization property active in the view
  (first / previous / next / last, index dropdown, slider on the position —
  the index domain may be sparse). The chosen realization drives the view's
  colouring through the `<name>_real_<idx>` array.

## Contract

**Props (in)**
- `time` — `{nb, index, value, label, playing, speed}`; `nb == 0` hides the
  time section.
- `specs` — `[{array_path, title, available_indices, current_idx}, ...]`.
- `view_id` — the owning view id.

**Events (out)**
- `set_time_index(i)`, `play(bool)`, `set_speed(x)`,
  `set_realization([array_path, idx])`.

## Build

```bash
cd vue-components
npm install
npm run build   # -> trame_fespp_timereal/module/serve/{*.umd.js, style.css}
```
