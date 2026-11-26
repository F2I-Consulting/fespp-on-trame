<template>
  <div class="fcl">
    <fp-empty v-if="!others.length"
              shows="The other 3D views this one moves with."
              gesture="There is no second 3D view yet — open one with “New 3D view” in the top bar." />
    <template v-else>
      <label v-for="p in others" :key="p.id" class="fp-check fcl-row"
             :title="linked(p.id) ? 'Synchronized: the two views move together. Untick to stop' : 'Tick to move this view and ' + p.title + ' together'">
        <input type="checkbox" :checked="linked(p.id)" @change="$emit('toggle', p.id)" />
        <span>{{ p.title }}</span>
      </label>
      <div class="fp-sum fcl-how">Rotating / zooming this view moves every ticked view the same way on mouse release (and vice versa). A new view starts UNsynchronized: this is where you say otherwise.</div>
    </template>
  </div>
</template>

<script>
/*
 * The Synchronize camera card of ONE render view: one tick per OTHER render
 * view, ticked when the two move together. A view opened as a copy of
 * another is NOT synchronized with it: a copy is a starting point of its
 * own, and linking it is an explicit choice made here. The link is
 * symmetric: the host toggles it on both sides. Pure display:
 *   props in  — viewId, views [{id, title, globe?}] (every panel the layout
 *               holds; a Globe view is not offered), links {id: [id]}
 *   events out — toggle(otherId)
 */
import FpEmpty from "../../../_shared/components/FpEmpty.vue";

export default {
  name: "CameraLinkPanel",
  components: { FpEmpty },
  props: {
    viewId: { type: String, default: "" },
    views: { type: Array, default: () => [] },
    links: { type: Object, default: () => ({}) },
  },
  emits: ["toggle"],
  computed: {
    others() {
      return (this.views || []).filter((x) => x && x.id !== this.viewId && !x.globe);
    },
  },
  methods: {
    linked(id) {
      const mine = (this.links || {})[this.viewId] || [];
      return mine.indexOf(id) >= 0;
    },
  },
};
</script>

<style>
@import "../../../_shared/panel.css";
</style>

<style scoped>
.fcl { display: flex; flex-direction: column; gap: 6px; padding: 8px; font-family: var(--fp-font); font-size: var(--fp-size); width: 260px; max-width: 100%; }
.fcl-row { white-space: normal; }
.fcl-how { line-height: 1.25; }
</style>
