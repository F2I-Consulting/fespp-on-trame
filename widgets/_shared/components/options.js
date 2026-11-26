/*
 * ONE option shape for <fp-select> and <fp-seg>: {value, label, title?}
 * (<fp-select> also draws `done?`: a green tick, its result already there).
 *
 * `label` is the word drawn, `title` the tooltip, defaulting to the label.
 * The two components sit side by side in the same sub-bar, so an option array
 * is often copied from one to the other: one shape means it draws the same
 * words in both. Both validate against this, and both draw an accusation in
 * place of a missing word, because a production build strips validators.
 */
export function optionsAreWritten(list) {
  return Array.isArray(list) && list.every(
    (o) => o && o.value !== undefined
      && typeof o.label === "string" && o.label !== "");
}
