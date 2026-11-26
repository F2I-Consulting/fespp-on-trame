<template>
  <div class="fp-cpick" v-bind="$attrs">
    <!-- saturation across, value up, on the hue picked -->
    <div ref="sv" class="fp-cpick-sv" :style="{ backgroundColor: hueHex }"
         role="slider" tabindex="0" :aria-label="'Saturation and brightness of ' + label"
         :aria-valuetext="hex" :title="'Saturation across, brightness up: ' + hex"
         @pointerdown.prevent="grab('sv', $event)" @pointermove="move" @pointerup="drop" @pointercancel="drop"
         @keydown="key('sv', $event)">
      <span class="fp-cpick-dot" :style="{ left: s * 100 + '%', top: (1 - v) * 100 + '%', background: hex }"></span>
    </div>
    <div ref="hue" class="fp-cpick-bar fp-cpick-hue" role="slider" tabindex="0"
         :aria-label="'Hue of ' + label" aria-valuemin="0" aria-valuemax="360" :aria-valuenow="Math.round(h)"
         title="Hue"
         @pointerdown.prevent="grab('hue', $event)" @pointermove="move" @pointerup="drop" @pointercancel="drop"
         @keydown="key('hue', $event)">
      <span class="fp-cpick-knob" :style="{ left: h / 360 * 100 + '%' }"></span>
    </div>
    <div ref="alpha" class="fp-cpick-bar fp-cpick-alpha" role="slider" tabindex="0"
         :aria-label="alphaLabel" aria-valuemin="0" aria-valuemax="100" :aria-valuenow="Math.round(a * 100)"
         :title="alphaTitle || alphaLabel"
         @pointerdown.prevent="grab('alpha', $event)" @pointermove="move" @pointerup="drop" @pointercancel="drop"
         @keydown="key('alpha', $event)">
      <span class="fp-cpick-ramp" :style="{ background: 'linear-gradient(to right, ' + rgba(0) + ', ' + rgba(1) + ')' }"></span>
      <span class="fp-cpick-knob" :style="{ left: a * 100 + '%' }"></span>
    </div>
    <div class="fp-cpick-foot">
      <span class="fp-cpick-swatch"><span :style="{ background: rgba(a) }"></span></span>
      <input class="fp-cpick-hex" :value="hexDraft" spellcheck="false" maxlength="7"
             :aria-label="'Colour of ' + label + ', #rrggbb'" title="The colour as #rrggbb: Enter or leaving the field applies it"
             @input="hexDraft = $event.target.value" @keydown.enter="typed" @blur="typed" />
      <span class="fp-cpick-pct">{{ Math.round(a * 100) }} %</span>
    </div>
  </div>
</template>

<script>
/*
 * The one colour picker that stays open: a saturation × brightness square
 * on the hue picked, a hue bar, an opacity bar, the #rrggbb field (the PO,
 * 03/11: "the palette directly, with its opacity" — no swatch to open
 * first). A drag shows the colour as it goes; its release reports it:
 * `commit-color` ("#rrggbb"), `commit-alpha` (0..1). The arrow keys move
 * a focused square or bar, each step reported. `color` and `alpha` are
 * the host's; a grey keeps the hue it was picked on.
 */
const clamp = (x, lo = 0, hi = 1) => Math.min(hi, Math.max(lo, x));

function hexToRgb(hex) {
  const h = String(hex || "").replace("#", "");
  if (!/^[0-9a-fA-F]{6}$/.test(h.slice(0, 6))) return null;
  return [0, 2, 4].map((k) => parseInt(h.slice(k, k + 2), 16));
}

function rgbToHex(rgb) {
  return "#" + rgb.map((x) => Math.round(clamp(x, 0, 255)).toString(16).padStart(2, "0")).join("");
}

function rgbToHsv([r, g, b]) {
  r /= 255; g /= 255; b /= 255;
  const mx = Math.max(r, g, b), d = mx - Math.min(r, g, b);
  let h = 0;
  if (d) {
    if (mx === r) h = ((g - b) / d) % 6;
    else if (mx === g) h = (b - r) / d + 2;
    else h = (r - g) / d + 4;
    h *= 60;
    if (h < 0) h += 360;
  }
  return [h, mx ? d / mx : 0, mx];
}

function hsvToRgb(h, s, v) {
  const c = v * s, x = c * (1 - Math.abs(((h / 60) % 2) - 1)), m = v - c;
  const [r, g, b] = h < 60 ? [c, x, 0] : h < 120 ? [x, c, 0] : h < 180 ? [0, c, x]
    : h < 240 ? [0, x, c] : h < 300 ? [x, 0, c] : [c, 0, x];
  return [(r + m) * 255, (g + m) * 255, (b + m) * 255];
}

export default {
  name: "FpColorPicker",
  inheritAttrs: false,
  props: {
    color: { type: String, default: "#cccccc" },
    alpha: { type: Number, default: 1 },
    // what is coloured, for the controls' names
    label: { type: String, default: "the object" },
    alphaLabel: { type: String, default: "Opacity" },
    alphaTitle: { type: String, default: "" },
  },
  emits: ["commit-color", "commit-alpha"],
  data() {
    const [h, s, v] = rgbToHsv(hexToRgb(this.color) || [204, 204, 204]);
    return { h, s, v, a: clamp(Number(this.alpha)), hexDraft: this.color, dragging: "" };
  },
  computed: {
    rgb() { return hsvToRgb(this.h, this.s, this.v); },
    hex() { return rgbToHex(this.rgb); },
    hueHex() { return rgbToHex(hsvToRgb(this.h, 1, 1)); },
  },
  watch: {
    color(c) {
      const rgb = hexToRgb(c);
      if (!rgb || this.dragging || rgbToHex(rgb) === this.hex) return;
      this.setRgb(rgb);
      this.hexDraft = rgbToHex(rgb);
    },
    alpha(x) {
      if (this.dragging !== "alpha") this.a = clamp(Number(x));
    },
    hex(x) { this.hexDraft = x; },
  },
  methods: {
    // the square and the bar on `rgb`: a grey keeps the hue it was picked on
    setRgb(rgb) {
      const [h, s, v] = rgbToHsv(rgb);
      if (s > 0 && v > 0) this.h = h;
      this.s = s;
      this.v = v;
    },
    rgba(a) {
      const [r, g, b] = this.rgb.map(Math.round);
      return `rgba(${r},${g},${b},${a})`;
    },
    grab(what, ev) {
      this.dragging = what;
      ev.currentTarget.setPointerCapture?.(ev.pointerId);
      this.read(ev);
    },
    move(ev) {
      if (this.dragging) this.read(ev);
    },
    drop(ev) {
      if (!this.dragging) return;
      this.read(ev);
      const what = this.dragging;
      this.dragging = "";
      this.report(what);
    },
    read(ev) {
      const box = this.$refs[this.dragging].getBoundingClientRect();
      const fx = clamp((ev.clientX - box.left) / (box.width || 1));
      if (this.dragging === "sv") {
        this.s = fx;
        this.v = 1 - clamp((ev.clientY - box.top) / (box.height || 1));
      } else if (this.dragging === "hue") {
        this.h = fx * 359.9;
      } else {
        this.a = Math.round(fx * 100) / 100;
      }
    },
    key(what, ev) {
      const step = ev.shiftKey ? 0.1 : 0.02;
      const dx = { ArrowLeft: -1, ArrowRight: 1 }[ev.key] || 0;
      const dy = { ArrowDown: -1, ArrowUp: 1 }[ev.key] || 0;
      if (!dx && !dy) return;
      ev.preventDefault();
      if (what === "sv") {
        this.s = clamp(this.s + dx * step);
        this.v = clamp(this.v + dy * step);
      } else if (what === "hue") {
        this.h = clamp(this.h + (dx || dy) * step * 360, 0, 359.9);
      } else {
        this.a = Math.round(clamp(this.a + (dx || dy) * step) * 100) / 100;
      }
      this.report(what);
    },
    report(what) {
      if (what === "alpha") this.$emit("commit-alpha", this.a);
      else this.$emit("commit-color", this.hex);
    },
    typed() {
      const rgb = hexToRgb(String(this.hexDraft || "").trim().replace(/^#?/, "#"));
      if (!rgb) {
        this.hexDraft = this.hex;
        return;
      }
      const hex = rgbToHex(rgb);
      if (hex === this.hex) return;
      this.setRgb(rgb);
      this.$emit("commit-color", hex);
    },
  },
};
</script>

<style scoped>
.fp-cpick { display: flex; flex-direction: column; gap: 6px; }
.fp-cpick-sv { position: relative; height: 112px; border-radius: 4px; cursor: crosshair; touch-action: none;
  background-image: linear-gradient(to top, #000, rgba(0, 0, 0, 0)), linear-gradient(to right, #fff, rgba(255, 255, 255, 0)); }
.fp-cpick-dot { position: absolute; width: 12px; height: 12px; margin: -6px 0 0 -6px; border-radius: 50%;
  border: 2px solid #fff; box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.45); pointer-events: none; }
.fp-cpick-bar { position: relative; height: 12px; border-radius: 6px; cursor: pointer; touch-action: none; }
.fp-cpick-hue { background: linear-gradient(to right, #f00, #ff0 17%, #0f0 33%, #0ff 50%, #00f 67%, #f0f 83%, #f00); }
.fp-cpick-alpha { background: #fff; box-shadow: inset 0 0 0 1px var(--fp-line, #ddd); }
/* checkerboard under the result so a see-through colour reads */
.fp-cpick-swatch {
  background: repeating-conic-gradient(#ccc 0% 25%, #fff 0% 50%) 0 0 / 8px 8px; }
.fp-cpick-ramp { position: absolute; inset: 0; border-radius: 6px; }
.fp-cpick-knob { position: absolute; top: 50%; width: 14px; height: 14px; margin: -7px 0 0 -7px; border-radius: 50%;
  background: #fff; border: 1px solid rgba(0, 0, 0, 0.45); box-shadow: 0 1px 2px rgba(0, 0, 0, 0.3); pointer-events: none; }
.fp-cpick-sv:focus-visible, .fp-cpick-bar:focus-visible { outline: 2px solid var(--fp-accent, #00436d); outline-offset: 2px; }
.fp-cpick-foot { display: flex; align-items: center; gap: 6px; }
.fp-cpick-swatch { width: 26px; height: 20px; border-radius: 3px; border: 1px solid var(--fp-btn-line, #bbb); overflow: hidden; flex: 0 0 auto; }
.fp-cpick-swatch > span { display: block; width: 100%; height: 100%; }
.fp-cpick-hex { width: 6.5em; font: inherit; font-variant-numeric: tabular-nums; padding: 1px 4px;
  border: 1px solid var(--fp-field-line, #ccc); border-radius: 3px; }
.fp-cpick-pct { margin-left: auto; color: var(--fp-ink-soft, #555); font-variant-numeric: tabular-nums; }
</style>
