/*
 * What can be done to a row of the matrix: whether it can be pinned, and what
 * its right-click menu offers. An entry it refuses says why in its tooltip
 * (R16: a right-click is never mute).
 */
import { plural } from "../../../_shared/numfmt.js";

/* A pinned copy keeps the realization and the time step its row reads: a row
   choosing neither has nothing to keep. */
export function pinnable(r) {
  return (r.reals || []).length > 0 || (r.ts_opts || []).length > 0;
}

function pinAct(r) {
  if (r.pinned) {
    return { key: "pin", label: "Remove this pinned row", title: "The pinned copy goes; its source stays" };
  }
  return pinnable(r)
    ? { key: "pin", label: "Pin a copy of this row",
      title: "A copy as read now, its realization and time step fixed; this row moves on" }
    : { key: "pin", label: "Pin a copy of this row", disabled: true,
      title: "Nothing to pin a copy at: this property has no realization and no time step" };
}

/* What the right-click offers on a row of the selection. */
export function itemActs(r, isBase, pinnedOfPath) {
  const hasTs = (r.ts_opts || []).length > 0;
  const hasReal = (r.reals || []).length > 0;
  return [
    isBase
      ? { key: "baseline_off", label: "Clear baseline", title: "No row of this kind is read against another any more" }
      : { key: "baseline", label: "Set as baseline", title: "Every other row of this kind is read against this one" },
    pinAct(r),
    { key: "pin_all_ts", label: "Pin all time steps", disabled: !hasTs,
      title: hasTs ? "One pinned row per time step of this property, at this realization" : "Not a time series" },
    { key: "pin_all_real", label: "Pin all realizations", disabled: !hasReal,
      title: hasReal ? "One pinned row per realization of this property, at this time step" : "Not a multi-realization property" },
    { key: "unpin_all", label: "Unpin all", disabled: !pinnedOfPath,
      title: pinnedOfPath ? "Remove the " + plural(pinnedOfPath, "pinned row") + " of this property" : "No row of this property is pinned" },
  ];
}

/* What it refuses on a following row. */
export function followingActs() {
  const follows = "This row follows the row above it";
  return [
    { key: "baseline", label: "Set as baseline", disabled: true, title: "The baseline is a row of the property itself" },
    { key: "pin", label: "Pin a copy of this row", disabled: true, title: follows },
    { key: "pin_all_ts", label: "Pin all time steps", disabled: true, title: follows },
    { key: "pin_all_real", label: "Pin all realizations", disabled: true, title: follows },
    { key: "unpin_all", label: "Unpin all", disabled: true, title: follows },
  ];
}
