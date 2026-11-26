<template>
  <div class="fgl">
    <!-- The view's scene is built after the view (the projection runs over
         every block and the eyes are replayed), which takes seconds: the
         card shows this band meanwhile. Not an fp-note: a note is a warning
         or an error, and this is neither. -->
    <fp-progress v-if="busy" label="Projecting the data onto the Earth" />
    <template v-else>
      <!-- A code declared by the file is read, not typed: it is shown and
           the field stays closed. When the file declares none, the card says
           so as a warning and opens the field, since nothing can be placed
           on the Earth until a code is given. -->
      <template v-if="globe.from_data">
        <div class="fgl-crs">{{ globe.crs }}</div>
        <div class="fp-lab" title="The data declares this code, so it is not typed here">EPSG
          <!-- the code links to its epsg.io entry (see epsgUrl) -->
          <a class="fgl-epsg-read" :href="epsgUrl" target="_blank" rel="noopener"
             :title="'Open EPSG:' + globe.epsg + ' on epsg.io — its definition, axes and area of use'">{{ globe.epsg }}</a>
          <span class="fp-sum">{{ globe.where || '' }}</span>
        </div>
      </template>
      <template v-else>
        <fp-note severity="warning"
                 :text="globe.crs || 'CRS: unknown — enter the projected EPSG code'" />
        <label class="fp-lab" title="The EPSG code of the projected CRS the data is in; Enter or leave the field to apply">EPSG
          <input class="fp-input fgl-epsg" type="text" inputmode="numeric" :value="globe.epsg || ''"
                 title="The EPSG code of the projected CRS the data is in; Enter or leave the field to apply"
                 @keyup.enter="$emit('epsg', $event.target.value)" @blur="$emit('epsg', $event.target.value)" />
          <a v-if="globe.epsg" class="fgl-epsg-link" :href="epsgUrl" target="_blank" rel="noopener"
             :title="'Open EPSG:' + globe.epsg + ' on epsg.io — its definition, axes and area of use'">epsg.io</a>
          <span class="fp-sum">{{ globe.where || '' }}</span>
        </label>
      </template>
      <!-- The extent as the file reader reports it, then its warnings. X and
           Y are in metres, and the label says so: a projected CRS measures
           the ground in metres from its own origin, and the data is stored
           in it. The same box in degrees follows, the reading expected of
           anything on the Earth; showing both also exposes a wrong EPSG
           code, whose metric extent lands on the wrong continent. -->
      <div v-if="globe.extent" class="fp-sum fgl-extent-lab"
           title="The data's own coordinates: a projected CRS measures the ground in meters from its origin">Extent, in the projected CRS (meters)<span
           v-if="globe.axes" class="fgl-axes"> — {{ globe.axes }}</span></div>
      <pre v-if="globe.extent" class="fgl-extent">{{ globe.extent }}</pre>
      <div v-if="globe.geo_extent" class="fgl-geo"
           title="The same box on the globe, in degrees">{{ globe.geo_extent }}</div>
      <fp-note v-if="globe.hint" :text="globe.hint" severity="warning" />
      <div class="fgl-row">
        <fp-btn :variant="globe.mode === 'earth' ? 'on' : 'default'" label="Whole Earth"
                title="Frame the whole Earth" @click="$emit('frame', 'earth')" />
        <!-- flying to one object needs its name, which the right-click menu of the view lists -->
        <span class="fp-sum">Right-click the view to fly to an object</span>
      </div>
      <!-- Earth imagery is session-wide: two Globes at different sharpness would look like a bug -->
      <label v-if="(textures || []).length > 1" class="fp-lab" title="The Earth imagery, the same for every Globe of the session">Earth imagery
        <fp-select :model-value="texture" :options="textureOptions"
                   title="The Earth imagery, the same for every Globe of the session"
                   @update:model-value="$emit('set-texture', $event)" />
      </label>
      <fp-note v-if="textureNote" :text="textureNote" severity="warning" />
      <label class="fp-lab fgl-opacity" title="How opaque the Earth is drawn, 0 hides it">Earth opacity
        <fp-range class="fgl-slider" single fill="left" :min="0" :max="1" :step="0.05" :low="opacity"
                  low-title="How opaque the Earth is drawn, 0 hides it"
                  @commit="(_w, v) => $emit('opacity', v)" />
        <span class="fp-sum fgl-num">{{ fmt(opacity) }}</span>
      </label>
    </template>
  </div>
</template>

<script>
/*
 * The card of the Globe view: the projected CRS as the file reader reports
 * it or as typed (EPSG), the extent and its warnings, the whole-Earth
 * framing, the imagery and the Earth's opacity. Pure display:
 *   props in  — globe {crs, epsg, from_data, axes, where, extent, geo_extent,
 *               hint, mode, opacity}, busy (the view's scene is being
 *               built), textures [name], texture, textureNote
 *   events out — epsg(text), frame('earth'), set-texture(name),
 *               opacity(number)
 */
import FpBtn from "../../../_shared/components/FpBtn.vue";
import FpNote from "../../../_shared/components/FpNote.vue";
import FpProgress from "../../../_shared/components/FpProgress.vue";
import FpRange from "../../../_shared/components/FpRange.vue";
import FpSelect from "../../../_shared/components/FpSelect.vue";
import { fmt } from "../../../_shared/numfmt.js";

export default {
  name: "GlobePanel",
  components: { FpBtn, FpNote, FpProgress, FpRange, FpSelect },
  props: {
    globe: { type: Object, default: () => ({}) },
    // the view's scene is being built: the card shows its progress band
    busy: { type: Boolean, default: false },
    textures: { type: Array, default: () => [] },
    texture: { type: String, default: "" },
    textureNote: { type: String, default: "" },
  },
  emits: ["epsg", "frame", "set-texture", "opacity"],
  computed: {
    opacity() {
      const v = this.globe && this.globe.opacity;
      return v === null || v === undefined ? 1 : Number(v);
    },
    // What a reader wants of an EPSG number is the definition behind it:
    // its axes, its unit, its area of use. epsg.io publishes it, with the
    // code as the address; a non-numeric code falls back to the home page.
    epsgUrl() {
      const c = String((this.globe && this.globe.epsg) || "").trim();
      return /^\d+$/.test(c) ? "https://epsg.io/" + c : "https://epsg.io/";
    },
    // An option arrives as {value, label, title} or as a bare string. An
    // object is mapped field by field, never wrapped whole, or the select
    // would show "[object Object]".
    textureOptions() {
      return (this.textures || []).map((t) => (t && typeof t === "object"
        ? { value: t.value, label: t.label || t.title || String(t.value), title: t.title || t.label }
        : { value: t, label: String(t) }));
    },
  },
  methods: { fmt },
};
</script>

<style>
@import "../../../_shared/panel.css";
</style>

<style scoped>
.fgl { display: flex; flex-direction: column; gap: 8px; padding: 8px; font-family: var(--fp-font); font-size: var(--fp-size); width: 300px; max-width: 100%; }
.fgl-crs { color: var(--fp-accent); white-space: normal; }
.fgl-epsg { max-width: 110px; }
.fgl-epsg-read { font-family: ui-monospace, Consolas, monospace; color: var(--fp-accent);
  text-decoration: underline; }
.fgl-epsg-link { font-size: var(--fp-size-small); color: var(--fp-accent); }
.fgl-axes { font-style: italic; }
.fgl-extent-lab { margin-bottom: -4px; }
.fgl-extent { margin: 0; font-family: ui-monospace, Consolas, monospace; font-size: var(--fp-size-small); white-space: pre; color: var(--fp-ink-soft); }
.fgl-geo { font-family: ui-monospace, Consolas, monospace; font-size: var(--fp-size-small); color: var(--fp-accent); }
.fgl-row { display: flex; align-items: center; gap: 8px; }
.fgl-opacity { gap: 8px; }
.fgl-slider { flex: 1 1 auto; min-width: 0; }
.fgl-num { min-width: 2.5em; text-align: right; }
</style>
