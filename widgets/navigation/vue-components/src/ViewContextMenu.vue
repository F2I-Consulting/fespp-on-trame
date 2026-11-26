<template>
  <!-- The render's right-click menu. Rendered INSIDE the view container, so
       x / y are element coordinates and the menu cannot escape the panel
       (<fp-menu inside>: it flips back from the right and bottom edges and
       scrolls — the globe lists one entry per object it can fly to). -->
  <fp-menu
    class="fvm-ctx"
    inside
    :at="menu && menu.open ? menu : null"
    :title="(menu && menu.title) || 'This point of the view'"
    :items="(menu && menu.items) || []"
    empty-why="Nothing to do on this point of the view"
    @pick="(it) => $emit('pick', it.key)"
    @close="$emit('close')"
  />
</template>

<script>
import FpMenu from "../../../_shared/components/FpMenu.vue";

export default {
  name: "ViewContextMenu",
  components: { FpMenu },
  props: {
    // {open, x, y, title, path, items: [{key, label}]}; the server closes
    // it on a pick (view_context_action) and on `close`
    menu: { type: Object, default: () => ({}) },
  },
  emits: ["pick", "close"],
};
</script>

<style>
@import "../../../_shared/panel.css";
</style>
