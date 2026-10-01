/*
 * ONE option shape for <fp-select> and <fp-seg>: {value, label, title?}.
 *
 * `label` is the word drawn, `title` the tooltip, defaulting to the label.
 * The two components used to disagree — label drawn in the strip, title drawn
 * in the dropdown — and they sit side by side in the same sub-bar, so an
 * array copied from one to the other rendered blank rows and said nothing.
 * Both now validate against this, and both draw an accusation in place of a
 * missing word, because a production build strips validators.
 */
export function optionsAreWritten(list) {
  return Array.isArray(list) && list.every(
    (o) => o && o.value !== undefined
      && typeof o.label === "string" && o.label !== "");
}
