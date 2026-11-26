<template>
  <div class="fp-vscroll" :class="{ 'fp-hscroll': horizontal }" @pointerdown.prevent="press">
    <div class="fp-vscroll-thumb" :style="thumbStyle"></div>
  </div>
</template>

<script>
/*
 * A scrollbar drawn by the widget, where the host places it (beside the
 * tracks it moves): a browser's own may show only while it scrolls
 * (Firefox), and this one is how the reader knows the content goes on. A
 * press beside the thumb brings it there; it then follows the pointer.
 * Vertical, or across with `horizontal`.
 *
 * Stateless: `top` is the scroller's offset along the bar (scrollTop, or
 * scrollLeft across), `total` its full extent (scrollHeight / scrollWidth),
 * `view` the extent it shows, `length` the bar's own length in px (the host
 * sets the same in its style). `scroll(offset)` is the offset the pointer
 * asks for; the host sets it.
 */
const THUMB_MIN = 24;

export default {
  name: "FpVScroll",
  props: {
    top: { type: Number, default: 0 },
    total: { type: Number, default: 0 },
    view: { type: Number, default: 0 },
    length: { type: Number, default: 0 },
    horizontal: { type: Boolean, default: false },
  },
  emits: ["scroll"],
  computed: {
    thumb() {
      const { total, view, length } = this;
      if (!(total > view) || !(length > 0)) return { top: 0, height: length };
      const size = Math.min(length, Math.max(THUMB_MIN, (length * view) / total));
      const at = Math.min(1, Math.max(0, this.top / (total - view)));
      return { top: (length - size) * at, height: size };
    },
    thumbStyle() {
      const t = this.thumb;
      return this.horizontal
        ? { left: t.top + "px", width: t.height + "px" }
        : { top: t.top + "px", height: t.height + "px" };
    },
  },
  methods: {
    press(e) {
      const bar = e.currentTarget;
      const box = bar.getBoundingClientRect();
      const along = (ev) => (this.horizontal ? ev.clientX - box.left : ev.clientY - box.top);
      const on = along(e) - this.thumb.top;
      const grab = on >= 0 && on <= this.thumb.height ? on : this.thumb.height / 2;
      const move = (ev) => {
        const room = this.length - this.thumb.height;
        const span = this.total - this.view;
        if (room <= 0 || span <= 0) return;
        this.$emit("scroll", Math.max(0, Math.min(span, ((along(ev) - grab) / room) * span)));
      };
      const up = () => {
        bar.removeEventListener("pointermove", move);
        bar.removeEventListener("pointerup", up);
        bar.removeEventListener("pointercancel", up);
      };
      bar.setPointerCapture(e.pointerId);
      bar.addEventListener("pointermove", move);
      bar.addEventListener("pointerup", up);
      bar.addEventListener("pointercancel", up);
      move(e);
    },
  },
};
</script>

<style>
.fp-vscroll {
  position: absolute;
  width: 10px;
  border-radius: 5px;
  background: rgba(0, 0, 0, 0.08);
  cursor: pointer;
  z-index: 4;
  touch-action: none;
}
.fp-vscroll-thumb {
  position: absolute;
  left: 1px;
  right: 1px;
  border-radius: 4px;
  background: var(--fp-accent, #00436d);
  opacity: 0.7;
}
.fp-vscroll.fp-hscroll { width: auto; height: 10px; }
.fp-hscroll .fp-vscroll-thumb { top: 1px; bottom: 1px; right: auto; }
.fp-vscroll:hover .fp-vscroll-thumb { opacity: 1; }
</style>
