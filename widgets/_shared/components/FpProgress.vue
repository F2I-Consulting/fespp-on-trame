<template>
  <div class="fp-progress" role="progressbar" aria-valuemin="0" aria-valuemax="100"
       :aria-valuenow="known ? Math.round(percent) : null">
    <span v-if="label" class="fp-progress-label">{{ label }}</span>
    <div class="fp-busy" :data-fill="known ? '' : null" :data-done="done ? '' : null"
         :style="known ? { '--fp-fill': percent + '%' } : null"></div>
    <slot />
  </div>
</template>

<script>
/*
 * THE wait of the application, everywhere one is shown: what is waited for,
 * the kit's bar, what can be done about it. The bar runs while the length is
 * unknown and fills when it is known (`value`, 0 to 100); `done` says it
 * ended well. The look is panel.css (`fp-progress`, `fp-busy`), which the
 * page's own pill (fespp_on_trame.__main__) writes too.
 */
export default {
  name: "FpProgress",
  props: {
    label: { type: String, default: "" },
    value: { type: Number, default: null },
    done: { type: Boolean, default: false },
  },
  computed: {
    known() {
      return this.value !== null && Number.isFinite(Number(this.value));
    },
    percent() {
      return Math.min(100, Math.max(0, Number(this.value)));
    },
  },
};
</script>
