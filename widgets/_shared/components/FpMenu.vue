<template>
  <!-- over the viewport, the menu leaves for the page's body: a dock panel
       contains what it holds (dockview draws it in a layer of its own), and a
       `fixed` box inside it would start from the panel's corner -->
  <Teleport to="body" :disabled="inside">
  <div
    v-if="at && !shut"
    ref="root"
    class="fp-menu-root"
    :class="{ 'fp-menu-inside': inside }"
    :data-fp-incomplete="incomplete ? '' : null"
    v-bind="$attrs"
    @click="shutNow"
    @contextmenu.prevent="rightClickBeside"
  >
    <div
      ref="box"
      class="fp-menu"
      :class="{ 'fp-menu-iconed': iconed }"
      role="menu"
      :style="style"
      @click.stop
      @contextmenu.prevent.stop
    >
      <div class="fp-menu-title" :title="heading">{{ heading }}</div>
      <template v-for="(it, i) in rows" :key="it.key != null && it.key !== '' ? it.key : 'row' + i">
        <div v-if="it.separatorBefore && i > 0" class="fp-menu-sep" role="separator"></div>
        <button
          type="button"
          role="menuitem"
          class="fp-menu-item"
          :class="{ 'fp-menu-danger': it.danger }"
          :aria-disabled="it.disabled ? 'true' : null"
          :title="tip(it)"
          @click="pick(it)"
        >
          <span v-if="iconed" class="fp-menu-ic" aria-hidden="true">
            <fp-icon v-if="String(it.icon || '').startsWith('fespp-')" :icon="it.icon" mono :size="16"
                     :disabled="!!it.disabled" />
            <v-icon v-else-if="it.icon" size="16">{{ it.icon }}</v-icon>
          </span>
          <span>{{ it.label || "(no label — a defect)" }}</span>
        </button>
      </template>
    </div>
  </div>
  </Teleport>
</template>

<script>
/*
 * The one right-click menu.
 *
 * Rn = rule n of the UI charter (doc/wiki/UI-Drawer-Toolbar-Shared.md).
 *
 * R16 — a right-click is never mute: a menu with nothing to offer still
 *       opens, with one disabled line saying why (`emptyWhy`), and a
 *       disabled entry says why in its tooltip. A disabled entry stays
 *       focusable (aria-disabled, not `disabled`): a disabled button shows
 *       no tooltip in every browser, and the reason IS the tooltip.
 * It names what it acts on — `title`, the menu's first line.
 * An entry may carry its action's icon (`icon`: "fespp-<name>" of the app's
 *       set, or "mdi-<name>"): the icons then stand in a column of their
 *       own, the words aligned whether an entry has one or not.
 * It asks to close (`close`) on Escape, on a click beside it and on a
 *       right-click beside it, which then reaches what lies under the pointer:
 *       another row opens its own menu at once; and when another menu opens,
 *       wherever it is (a tree, a 3D view): one menu at a time, across the
 *       widget bundles (`fp-menu-open` on the window). The host clears `at`;
 *       the menu leaves the screen at once all the same (`shut`), a host
 *       that clears it through the server included — the right-click
 *       beside it must reach what lies under it, not the menu again. A pick
 *       (`pick`, the entry) is the host's to act on, and it clears `at` as it
 *       acts.
 * It stays where it can be read: placed at the pointer, then flipped to the
 *       other side of it when it would cross the right or bottom edge, and
 *       it scrolls rather than run out of its frame. The frame is the
 *       viewport, or with `inside` the nearest positioned ancestor (a 3D
 *       view: x / y are then that element's coordinates).
 */
import FpIcon from "./FpIcon.vue";

export default {
  name: "FpMenu",
  components: { FpIcon },
  inheritAttrs: false,
  props: {
    // {x, y} where the right-click was made; null (or absent) = closed
    at: { type: Object, default: null },
    // what the menu acts on, its first line
    title: { type: String, required: true },
    // [{key, label, title?, icon?, disabled?, danger?, separatorBefore?}];
    // a disabled entry carries its reason in `title`
    items: {
      type: Array,
      required: true,
      validator: (v) => Array.isArray(v)
        && v.every((it) => it && it.label && (!it.disabled || it.title)),
    },
    // the disabled line an empty menu shows
    emptyWhy: { type: String, default: "" },
    inside: { type: Boolean, default: false },
  },
  emits: ["pick", "close"],
  data() {
    return { pos: null, shut: false };
  },
  computed: {
    rows() {
      const items = Array.isArray(this.items) ? this.items : [];
      if (items.length) return items;
      return [{ key: "", label: this.emptyWhy || "Nothing to do here", disabled: true,
        title: this.emptyWhy || "This menu holds nothing and does not say why — a defect" }];
    },
    iconed() {
      return this.rows.some((it) => it && it.icon);
    },
    heading() {
      return this.title || "(no title — a defect)";
    },
    incomplete() {
      const items = Array.isArray(this.items) ? this.items : null;
      return !this.title || !items
        || items.some((it) => !it || !it.label || (it.disabled && !it.title))
        || (items.length === 0 && !this.emptyWhy);
    },
    style() {
      // hidden until measured: placed at the pointer first, it would flash
      // across the edge before the flip
      const p = this.pos || { x: (this.at && this.at.x) || 0, y: (this.at && this.at.y) || 0 };
      return { left: p.x + "px", top: p.y + "px", visibility: this.pos ? "visible" : "hidden" };
    },
  },
  watch: {
    at: {
      handler() {
        this.pos = null;
        this.shut = false;
        if (!this.at) return;
        this.$nextTick(this.place);
        window.dispatchEvent(new CustomEvent("fp-menu-open", { detail: this }));
      },
      immediate: true,
    },
    items() {
      if (this.at) this.$nextTick(this.place);
    },
  },
  mounted() {
    this._esc = (e) => {
      if (e.key === "Escape" && this.at) this.shutNow();
    };
    window.addEventListener("keydown", this._esc);
    this._other = (e) => {
      if (e.detail !== this && this.at) this.shutNow();
    };
    window.addEventListener("fp-menu-open", this._other);
  },
  beforeUnmount() {
    window.removeEventListener("keydown", this._esc);
    window.removeEventListener("fp-menu-open", this._other);
  },
  methods: {
    place() {
      const root = this.$refs.root;
      const box = this.$refs.box;
      if (!this.at || !root || !box) return;
      const w = root.clientWidth;
      const h = root.clientHeight;
      const bw = box.offsetWidth;
      const bh = box.offsetHeight;
      let x = Number(this.at.x) || 0;
      let y = Number(this.at.y) || 0;
      if (x + bw > w) x = x - bw;
      if (y + bh > h) y = y - bh;
      // too big for either side: against the far edge, never off the near one
      x = Math.max(0, Math.min(x, w - bw));
      y = Math.max(0, Math.min(y, h - bh));
      this.pos = { x, y };
    },
    tip(it) {
      if (it.disabled && !it.title) return "Disabled, and it does not say why — a defect";
      return it.title || null;
    },
    pick(it) {
      if (it.disabled) return;
      this.$emit("pick", it);
    },
    shutNow() {
      this.shut = true;
      this.$emit("close");
    },
    rightClickBeside(ev) {
      const { clientX, clientY } = ev;
      this.shutNow();
      this.$nextTick(() => {
        const under = document.elementFromPoint(clientX, clientY);
        if (under) {
          under.dispatchEvent(new MouseEvent("contextmenu", {
            bubbles: true, cancelable: true, view: window, button: 2, clientX, clientY,
          }));
        }
      });
    },
  },
};
</script>
