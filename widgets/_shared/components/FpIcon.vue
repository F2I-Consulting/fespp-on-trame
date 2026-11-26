<template>
  <svg
    viewBox="0 0 24 24"
    :width="size"
    :height="size"
    :style="disabled ? { filter: 'grayscale(1)', opacity: 0.55 } : null"
    :data-fp-incomplete="resolved.complete ? null : ''"
    v-bind="$attrs"
  ><title v-if="tooltip">{{ tooltip }}</title><path
      v-for="(part, i) in resolved.parts"
      :key="i"
      :d="part.d"
      :fill="part.fill ? colour(part.c, part.m) : 'none'"
      :stroke="part.fill ? 'none' : colour(part.c, part.m)"
      :stroke-width="part.fill ? null : 1.8"
      stroke-linecap="round"
      stroke-linejoin="round"
  /></svg>
</template>

<script>
/*
 * The one icon of the application.
 *
 * It holds three rules a class cannot:
 *
 *  1. TWO VOCABULARIES, one drawing. `icon` takes a drawing of the set
 *     (`{ parts }`), the NAME of one ("fespp-grid-ijk" — what the Python
 *     side sends, since it cannot carry a shape), or a bare SVG path, which
 *     is how an @mdi/js glyph arrives. A host therefore never has to know
 *     which kind it is holding.
 *  2. THE COLOUR THE DATA DECLARES WINS. A part normally paints itself in
 *     its family (`var(--fp-ic-rock)`); when the object carries a colour of
 *     its own — a RESQML GraphicalInformationSet, arriving as `colorRGB` on
 *     the tree node — `declared` paints the WHOLE icon in it, so the tree
 *     says what the 3D view shows.
 *     The corollary is `mono`: colour is there to SORT A TREE, where a
 *     reader runs down dozens of rows of several families. A toolbar has no
 *     families to sort — every button is another tool — so a drawing takes
 *     the ink of its neighbours there, and a single coloured button among
 *     plain ones reads as a mistake rather than as meaning.
 *  3. DISABLED IS A FILTER, never a colour. A greyed row cannot be done by
 *     changing `currentColor`, which a part painted from the palette does
 *     not follow; the whole drawing is desaturated instead.
 *
 * Nothing silent: a name the set does not hold, or an mdi NAME (which only
 * the host's <v-icon> can resolve), draws the "unknown" mark, says so in
 * the tooltip and raises `data-fp-incomplete`, which the browser harness
 * fails on. An icon that quietly draws nothing is a blank row.
 */
import { FESPP_ICONS } from "../icons/fespp-icons.js";

const camel = (name) => name.replace(/-([a-z0-9])/g, (_, c) => c.toUpperCase());

export default {
  name: "FpIcon",
  inheritAttrs: false,
  props: {
    // { parts: [...] } | "fespp-<name>" | an SVG path (an mdi glyph)
    icon: { type: [Object, String], default: "" },
    size: { type: [Number, String], default: 15 },
    // the colour the data declares for THIS object, any CSS colour
    declared: { type: String, default: "" },
    // a TOOLBAR draws it: one ink, like the glyphs beside it (see rule 2 in
    // the header)
    mono: { type: Boolean, default: false },
    // on the dark chrome (a view's title bar, a card's head): the same two
    // inks, made for a dark ground
    chrome: { type: Boolean, default: false },
    disabled: { type: Boolean, default: false },
    title: { type: String, default: "" },
  },
  computed: {
    resolved() {
      const icon = this.icon;
      if (icon && typeof icon === "object" && Array.isArray(icon.parts)) {
        return { parts: icon.parts, complete: true };
      }
      if (typeof icon === "string" && icon.indexOf("fespp-") === 0) {
        const found = FESPP_ICONS[camel(icon.slice(6))];
        if (found) return { parts: found.parts, complete: true };
        return { parts: FESPP_ICONS.unknown.parts, complete: false };
      }
      if (typeof icon === "string" && icon.indexOf("mdi-") === 0) {
        return { parts: FESPP_ICONS.unknown.parts, complete: false };
      }
      if (typeof icon === "string" && icon) {
        return { parts: [{ d: icon, fill: true }], complete: true };
      }
      return { parts: FESPP_ICONS.unknown.parts, complete: false };
    },
    tooltip() {
      if (this.resolved.complete) return this.title;
      const name = typeof this.icon === "string" && this.icon ? this.icon : "(none)";
      const why = name.indexOf("mdi-") === 0
        ? "an mdi name reaches the icon of the set: the host renders those with v-icon"
        : "this icon name is not in the set";
      return `${this.title ? this.title + " — " : ""}${name}: ${why} — a defect`;
    },
  },
  methods: {
    // A part's colour: its family's, or a literal "#rrggbb" (the steps of the
    // Colormap's bar, whose colours ARE the drawing). A `mono` toolbar draws
    // in one ink — its own, the blue of F2I — except the green of F2I and
    // the literal colours, its second ink, the green also on a part whose
    // toolbar ink `m` says so; and the grey of what stands back in a
    // drawing (`mute`), which stays grey whatever the ink.
    colour(family, monoInk) {
      if (this.declared) return this.declared;
      if (family && family[0] === "#") return family;
      const green = family === "f2i" || monoInk === "f2i";
      const mute = family === "mute" ? "var(--fp-ic-mute, #8e9aa3)" : "";
      if (this.chrome) return green ? "var(--fp-chrome-ic-f2i, #a6d63f)" : mute || "var(--fp-chrome-ic, #8cc8f0)";
      if (this.mono) return green ? "var(--fp-ic-f2i, #8FC31F)" : mute || "currentColor";
      return family ? `var(--fp-ic-${family})` : "currentColor";
    },
  },
};
</script>
