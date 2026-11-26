<template>
  <div class="tb">
    <button
      v-for="b in buttons"
      :key="b.id"
      :class="['tb-btn', { active: b.active, 'tb-sub': b.sub }]"
      :title="b.title"
      :disabled="!!b.disabled"
      @click="$emit('toggle', b.key)"
    >
      <fp-icon v-if="isFespp(b.icon)" :icon="b.icon" :size="b.sub ? 15 : 20" mono />
      <v-icon v-else-if="isMdi(b.icon)" :size="b.sub ? 15 : 20">{{ b.icon }}</v-icon>
      <span v-else-if="isText(b.icon)" class="tb-txt">
        <span v-for="(w, i) in textLines(b.icon)" :key="i" class="tb-txt-line">{{ w }}</span>
      </span>
      <template v-else>{{ b.icon }}</template>
      <!-- live badge (e.g. a time animation playing while its card is closed) -->
      <span v-if="b.badge" class="tb-badge" title="Running">&#9654;</span>
    </button>
    <div v-if="actions.length && tools.length" class="tb-sep"></div>
    <button
      v-for="a in actions"
      :key="a.key"
      class="tb-btn"
      :title="a.title"
      @click="$emit('action', a.key)"
    >
      <fp-icon v-if="isFespp(a.icon)" :icon="a.icon" :size="20" mono />
      <v-icon v-else-if="isMdi(a.icon)" size="20">{{ a.icon }}</v-icon>
      <span v-else-if="isText(a.icon)" class="tb-txt">
        <span v-for="(w, i) in textLines(a.icon)" :key="i" class="tb-txt-line">{{ w }}</span>
      </span>
      <template v-else>{{ a.icon }}</template>
    </button>
  </div>
</template>

<script>
/*
 * Per-view toolbar: a vertical strip of buttons.
 *   - `tools`   -> toggle buttons (open/close a FloatingCard); emits toggle(key).
 *   - `actions` -> one-shot action buttons (e.g. reset camera); emits action(key).
 *   - `badges`  -> tool keys to mark with a green "running" play badge (the host
 *                  decides, e.g. this view's time animation is playing).
 *   - a GROUP (tools sharing `group`, titled `group_title`): ONE button, the
 *     tools being modes of one gesture that exclude each other (the
 *     selection on the surface / through the volume). Off, it turns on the
 *     mode used last (at first the one the host sends with `group_default`);
 *     on, it turns it off, and a small button under it
 *     switches to the other mode (the manager, 15/10: two icons for one
 *     gesture).
 * The host owns the open-set and handles the actions. A tool the
 * host sends with `disabled` is drawn but inert, and its title says why: a
 * tool whose precondition fails explains itself instead of disappearing.
 *
 * `icon` may be a name of the application's own set ("fespp-slicers", drawn
 * by FpIcon), an mdi name ("mdi-file-tree", rendered via the host's global
 * Vuetify <v-icon>), "text:" and letters drawn as a glyph, framed, a "/"
 * stacking them ("text:TS/MR": TS over MR, which a 30 px button holds where
 * "TS/MR" on one line would not), or a plain glyph/emoji rendered as text. A tool that
 * names an object of the model uses a drawing of the set; a tool that names
 * a gesture (crop, pick, a clock) keeps its mdi glyph. Either way the
 * drawing is monochrome here: a toolbar has no families to sort, and one
 * coloured button among plain ones reads as a mistake.
 */
import FpIcon from "../../../_shared/components/FpIcon.vue";

export default {
  name: "ViewToolbar",
  components: { FpIcon },
  props: {
    tools: { type: Array, default: () => [] }, // [{ key, icon, title, tip?, disabled?, group?, group_title? }]
    open: { type: Array, default: () => [] },
    actions: { type: Array, default: () => [] }, // [{ key, icon, title }]
    badges: { type: Array, default: () => [] },  // [tool keys]
  },
  emits: ["toggle", "action"],
  data() {
    // per group, the mode used last: what the group's button turns on
    return { lastOf: {} };
  },
  watch: {
    open: {
      immediate: true,
      handler(keys) {
        for (const t of this.tools || []) {
          if (t.group && (keys || []).includes(t.key)) this.lastOf = { ...this.lastOf, [t.group]: t.key };
        }
      },
    },
  },
  computed: {
    openSet() { return new Set(this.open || []); },
    badgeSet() { return new Set(this.badges || []); },
    // one entry per button drawn: a tool, a group's button, and, while a
    // group is on, the button that switches it to its other mode
    buttons() {
      const out = [];
      const done = new Set();
      for (const t of this.tools || []) {
        if (!t.group) {
          // `tip`: the tooltip when it says more than the card's title
          out.push({ id: t.key, key: t.key, icon: t.icon, title: t.tip || t.title,
                     active: this.openSet.has(t.key), disabled: t.disabled,
                     badge: this.badgeSet.has(t.key) });
          continue;
        }
        if (done.has(t.group)) continue;
        done.add(t.group);
        const members = this.tools.filter((m) => m.group === t.group);
        const on = members.find((m) => this.openSet.has(m.key));
        // the mode used last, else the group's default mode, else its first
        const shown = on || members.find((m) => m.key === this.lastOf[t.group])
          || members.find((m) => m.group_default) || members[0];
        const name = t.group_title || t.title;
        out.push({
          id: "g:" + t.group, key: shown.key, icon: shown.icon, active: !!on,
          disabled: members.every((m) => m.disabled),
          title: on ? name + " (on) — " + on.title + ". Click to turn it off; the button below switches the mode."
                    : name + " — click to turn it on: " + shown.title,
        });
        if (on) {
          for (const m of members) {
            if (m.key !== on.key) {
              out.push({ id: "sw:" + m.key, key: m.key, icon: m.icon, sub: true,
                         title: "Switch to: " + m.title });
            }
          }
        }
      }
      return out;
    },
  },
  methods: {
    isMdi(icon) { return typeof icon === "string" && icon.indexOf("mdi-") === 0; },
    isFespp(icon) { return typeof icon === "string" && icon.indexOf("fespp-") === 0; },
    isText(icon) { return typeof icon === "string" && icon.indexOf("text:") === 0; },
    textLines(icon) { return icon.slice("text:".length).split("/"); },
  },
};
</script>

<style>
@import "../../../_shared/tokens.css";
</style>

<style scoped>
/* Docked full-height vertical toolbar (sits beside the render, not over it). */
.tb {
  height: 100%; box-sizing: border-box; flex: 0 0 auto;
  display: flex; flex-direction: column; gap: 4px;
  background: #f5f5f5; border-right: 1px solid #ccc; padding: 4px;
  font-family: system-ui, sans-serif;
}
.tb-btn {
  width: 30px; height: 30px; border: none; background: transparent;
  border-radius: 3px; cursor: pointer; font-size: 15px; line-height: 1;
  display: flex; align-items: center; justify-content: center;
  position: relative;
}
.tb-badge {
  position: absolute; right: 1px; bottom: 1px; font-size: 9px; line-height: 1;
  color: #8FC31F; background: #fff; border-radius: 50%; padding: 1px 2px;
  border: 1px solid #8FC31F;
}
/* accent blue in every state: blue icon at rest, blue fill + white icon when open */
.tb-btn { color: var(--fp-accent); }
.tb-btn:hover { background: #e3ecf3; }
.tb-btn.active { background: var(--fp-accent); color: #fff; }
/* offered, but not here: the tooltip carries the reason */
.tb-btn:disabled { opacity: .38; cursor: default; }
.tb-btn:disabled:hover { background: none; }
.tb-sep { height: 1px; background: #ddd; margin: 2px 0; }
/* a group's mode switch: smaller, tucked under its group's button, framed so
   it reads as part of it */
.tb-btn.tb-sub { height: 22px; margin-top: -3px; border: 1px dashed var(--fp-accent);
  background: #fff; }
/* letters as a glyph: framed like the XML door of the top bar, the lines
   stacked and split by a rule, in the button's ink (white when open) */
/* the frame and the bar in the green of F2I, the letters in the button's
   ink (the PO, 15/10: the toolbar's second ink, as in the drawn icons) */
.tb-txt {
  display: flex; flex-direction: column; align-items: stretch;
  border: 1.5px solid var(--fp-ic-f2i, #8FC31F); border-radius: 3px; padding: 1px 2px;
  font: 700 8px/1 system-ui, sans-serif; letter-spacing: 0.3px; text-align: center;
}
.tb-txt-line + .tb-txt-line { border-top: 1.5px solid var(--fp-ic-f2i, #8FC31F); margin-top: 1px; padding-top: 1px; }
</style>
