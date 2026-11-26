<template>
  <span class="fvd">
    <v-btn ref="btn" variant="text" color="primary" size="small" icon :title="title"
           :active="open" @click="toggleOpen">
      <fp-icon icon="fespp-view3d" mono :size="20" />
    </v-btn>
    <Teleport to="body">
      <div v-if="open" class="fvd-scrim" @click.self="open = false">
        <div ref="pop" class="fp-dialog fvd-pop" :style="place" role="dialog" aria-label="3D views"
             tabindex="-1" @keydown.esc="open = false">
          <div class="fp-dialog-head"><span class="fp-title">3D views</span></div>
          <div class="fvd-tiles">
            <div v-for="v in rows" :key="v.id" role="button" tabindex="0" class="fvd-tile"
                 :class="{ 'fvd-hidden': v.hidden, 'fvd-active': v.id === active && !v.hidden }"
                 :title="tipOf(v)" @click="go(v.id)" @keydown.enter.self="go(v.id)">
              <fp-icon icon="fespp-view3d" mono :size="30" :disabled="!!v.hidden" />
              <span class="fvd-name">{{ v.title }}</span>
              <fp-btn icon variant="bare" class="fvd-eye" :aria-pressed="v.hidden ? 'false' : 'true'"
                      :title="eyeTipOf(v)" @click.stop="$emit('toggle', v.id)">
                <v-icon size="16">{{ v.hidden ? "mdi-eye-off-outline" : "mdi-eye-outline" }}</v-icon>
              </fp-btn>
            </div>
            <div role="button" tabindex="0" class="fvd-tile fvd-add" title="Open a new 3D view"
                 @click="add" @keydown.enter.self="add">
              <span class="fvd-plus" aria-hidden="true">+</span>
              <span class="fvd-name">New 3D view</span>
            </div>
          </div>
        </div>
      </div>
    </Teleport>
  </span>
</template>

<script>
/*
 * The top bar's door to the 3D views, a toggle like the other doors: a click
 * opens a pop-over with one tile per 3D view — a click on a tile makes that
 * view the active one (shown again first when it was hidden), its eye alone
 * hides the view (it leaves the screen and keeps everything: its objects,
 * its camera, its cards) or shows it again where it was — and a "+" tile
 * that opens a new 3D view as before. The Globe has its own door: it is not
 * listed.
 *
 * Pure display, like every widget here:
 *   props in   — views [{id, title, globe, hidden}], active (the active view's id), title
 *   events out — activate(id), toggle(id), add()
 */
import FpBtn from "../../../_shared/components/FpBtn.vue";
import FpIcon from "../../../_shared/components/FpIcon.vue";
import { popPlace } from "../../../_shared/popPlace.js";

const WIDTH = 300;

export default {
  name: "ViewsDoor",
  components: { FpBtn, FpIcon },
  props: {
    views: { type: Array, default: () => [] },
    active: { type: String, default: "" },
    title: { type: String, default: "3D views — go to one, show or hide each, or open a new one" },
  },
  emits: ["activate", "toggle", "add"],
  data() {
    return { open: false, place: {} };
  },
  computed: {
    rows() {
      return (this.views || []).filter((v) => v && !v.globe);
    },
  },
  methods: {
    tipOf(v) {
      return v.hidden ? "Show " + v.title + " again and make it the active view" : "Make " + v.title + " the active view";
    },
    eyeTipOf(v) {
      return v.hidden
        ? "Show " + v.title + " again, where it was"
        : "Hide " + v.title + ": it leaves the screen and keeps everything — its objects, its camera, its cards";
    },
    go(id) {
      this.open = false;
      this.$emit("activate", id);
    },
    toggleOpen() {
      if (this.open) {
        this.open = false;
        return;
      }
      const btn = this.$refs.btn && (this.$refs.btn.$el || this.$refs.btn);
      // its height grows with the tiles: placed for a few rows, the page keeps it inside
      this.place = btn ? popPlace(btn, WIDTH, 96 + 52 * (this.rows.length + 1)) : {};
      this.open = true;
      this.$nextTick(() => this.$refs.pop && this.$refs.pop.focus());
    },
    add() {
      this.open = false;
      this.$emit("add");
    },
  },
};
</script>

<style>
@import "../../../_shared/panel.css";
</style>

<style scoped>
.fvd { display: inline-flex; }
.fvd-scrim { position: fixed; inset: 0; z-index: 2400; }
.fvd-pop { position: fixed; max-height: 70vh; overflow: auto; outline: none; }
.fvd-tiles { display: flex; flex-direction: column; gap: 6px; padding: 10px; }
.fvd-tile {
  display: flex; align-items: center; gap: 10px; width: 100%;
  padding: 8px 10px; border: 1px solid var(--fp-line-soft); border-radius: 6px;
  background: var(--fp-surface, #fff); cursor: pointer; text-align: left;
  font: inherit; color: var(--fp-ink, #263238);
}
.fvd-tile:hover { border-color: var(--fp-accent, #00436d); }
.fvd-tile:focus-visible { outline: 2px solid var(--fp-accent, #00436d); outline-offset: 1px; }
.fvd-active { border-color: var(--fp-accent, #00436d); box-shadow: inset 3px 0 0 var(--fp-accent, #00436d); }
.fvd-hidden { color: var(--fp-ink-mute, #90a4ae); background: var(--fp-surface-alt, #f5f7f8); }
.fvd-name { flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fvd-eye { flex: 0 0 auto; color: inherit; }
.fvd-add { border-style: dashed; color: var(--fp-accent, #00436d); }
.fvd-plus { width: 30px; text-align: center; font-size: 22px; line-height: 1; }
</style>
