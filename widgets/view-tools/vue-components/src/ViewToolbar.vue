<template>
  <div class="tb">
    <button
      v-for="t in tools"
      :key="t.key"
      :class="['tb-btn', { active: openSet.has(t.key) }]"
      :title="t.title"
      :disabled="!!t.disabled"
      @click="$emit('toggle', t.key)"
    >
      <fp-icon v-if="isFespp(t.icon)" :icon="t.icon" :size="20" mono />
      <v-icon v-else-if="isMdi(t.icon)" size="20">{{ t.icon }}</v-icon>
      <template v-else>{{ t.icon }}</template>
      <!-- live badge (e.g. a time animation playing while its card is closed) -->
      <span v-if="badgeSet.has(t.key)" class="tb-badge" title="Running">&#9654;</span>
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
 * Stateless: the host owns the open-set and handles the actions. A tool the
 * host sends with `disabled` is drawn but dead: its title says why, which is
 * how a tool whose precondition fails accounts for itself instead of
 * vanishing without a word.
 *
 * `icon` may be a name of the application's own set ("fespp-slicers", drawn
 * by FpIcon), an mdi name ("mdi-file-tree") — rendered via the host's global
 * Vuetify <v-icon> — or a plain glyph/emoji rendered as text. A tool that
 * names an OBJECT of the model wears a drawing of the set; a tool that names
 * a gesture (crop, pick, a clock) keeps its mdi glyph. Either way the
 * drawing is MONOCHROME here: a bar has no families to sort, and one
 * coloured button among plain ones reads as a mistake.
 */
import FpIcon from "../../../_shared/components/FpIcon.vue";

export default {
  name: "ViewToolbar",
  components: { FpIcon },
  props: {
    tools: { type: Array, default: () => [] }, // [{ key, icon, title }]
    open: { type: Array, default: () => [] },
    actions: { type: Array, default: () => [] }, // [{ key, icon, title }]
    badges: { type: Array, default: () => [] },  // [tool keys]
  },
  emits: ["toggle", "action"],
  computed: {
    openSet() { return new Set(this.open || []); },
    badgeSet() { return new Set(this.badges || []); },
  },
  methods: {
    isMdi(icon) { return typeof icon === "string" && icon.indexOf("mdi-") === 0; },
    isFespp(icon) { return typeof icon === "string" && icon.indexOf("fespp-") === 0; },
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
/* F2I blue in every state: blue icon at rest, blue fill + white icon when open */
.tb-btn { color: var(--fp-accent); }
.tb-btn:hover { background: #e3ecf3; }
.tb-btn.active { background: var(--fp-accent); color: #fff; }
/* offered, but not here: the tooltip carries the reason */
.tb-btn:disabled { opacity: .38; cursor: default; }
.tb-btn:disabled:hover { background: none; }
.tb-sep { height: 1px; background: #ddd; margin: 2px 0; }
</style>
