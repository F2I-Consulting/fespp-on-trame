<template>
  <div class="up-root">
    <fp-btn class="up-launch" title="Import an EPC file (and its HDF5) or read an OSDU dataspace into this session"
            @click="open = true">
      <fp-icon class="up-launch-ico" icon="fespp-import-data" mono :size="17" />
      Import data
    </fp-btn>

    <Teleport to="body">
      <!-- a click beside the card does not close it: only its cross, Esc,
           or a batch read in full -->
      <div class="fp-scrim" v-if="open" @keydown.esc="open = false">
        <!-- `tabindex="-1"`: focusable but not tabbable, so a click on the
             card's text keeps the focus inside it and the Esc the scrim
             listens for still reaches it -->
        <div class="fp-dialog up-dialog" :class="{ 'up-dialog-wide': wide }" role="dialog" aria-modal="true" tabindex="-1">
          <div class="fp-dialog-head">
            <fp-icon class="up-title-ico" icon="fespp-import-data" mono :size="19" />
            <span class="fp-title">Import data</span>
            <fp-btn variant="bare" title="Close" @click="open = false">×</fp-btn>
          </div>

          <!-- The two sources SIDE BY SIDE, not behind tabs: a dialog
               labelled "Import data" that opens on a drop zone alone reads
               as "files only", and a second tab gives no reason to press
               it. Both are on screen at once, each under its own heading,
               so what the application can read is visible without a
               gesture. -->
          <!-- ONE COLUMN once the OSDU explorer is on screen: its table
               needs the dialog's whole width, and the files half becomes a
               strip above it, one line high, with the same drop target and
               Browse link. Both parts keep their `.up-src` in every mode. -->
          <div class="up-sources" :class="{ 'up-sources-stack': wide }">
            <section class="up-src" :class="{ 'up-src-compact': wide }">
              <fp-icon v-if="wide" class="up-compact-ico" icon="fespp-import-data" mono :size="17" />
              <h3 class="up-src-h">From this computer</h3>
              <upload-file :upload-url="uploadUrl" :session-id="sessionId" :accept="accept"
                           :loaded="loadedFiles" :compact="wide"
                           :class="{ 'up-file-compact': wide }"
                           @uploaded="onUploaded" @error="$emit('error', $event)"
                           @close="open = false" />
            </section>
            <div class="up-rule" role="separator"></div>
            <section class="up-src">
              <h3 class="up-src-h">From an OSDU dataspace (ETP)</h3>
              <upload-osdu :etp-connected="etpConnected" :etp-connecting="etpConnecting"
                           :etp-step="etpStep"
                           :etp-dataspaces="etpDataspaces" :etp-status="etpStatus"
                           :osdu-explorer="osduExplorer"
                           @etp-connect="$emit('etp-connect', $event)"
                           @etp-select="$emit('etp-select', $event)"
                           @etp-disconnect="$emit('etp-disconnect')"
                           @osdu-scan="$emit('osdu-scan')"
                           @osdu-find="$emit('osdu-find', $event)"
                           @osdu-search="$emit('osdu-search', $event)"
                           @osdu-kinds="$emit('osdu-kinds', $event)" />
            </section>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script>
/*
 * Import shell: the "Import data" toolbar button + a modal dialog holding
 * BOTH import sources at once. Each is a FINE-GRAINED widget (also usable
 * standalone): <upload-file> (EPC/H5 -> /upload endpoint) and <upload-osdu>
 * (OSDU RDDMS / ETP 1.2 credentials, connection server-side). This shell
 * only forwards their props/events; see each component for its contract.
 *
 * SIDE BY SIDE, NOT TABBED. Behind tabs, a dialog labelled "Import data"
 * would open on a drop zone alone and read as "files only", with the
 * second source behind a tab nobody has a reason to press. What the
 * application can read is on screen the moment the dialog opens, each
 * source under its own heading.
 *
 * The files half closes the dialog once every file of a batch is read and
 * none failed (the manager, 15/10); a failure keeps it open. The OSDU half
 * (connect -> pick dataspace -> load) closes it once a dataspace is read
 * (the manager, 12/11): the server says "Dataspace … loaded." or marks one
 * more row loaded; a failed load keeps it open with its message.
 */
import FpBtn from "../../../_shared/components/FpBtn.vue";
import FpIcon from "../../../_shared/components/FpIcon.vue";
import UploadFile from "./components/UploadFile.vue";
import UploadOsdu from "./components/UploadOsdu.vue";


export default {
  name: "UploadData",
  components: { FpBtn, FpIcon, UploadFile, UploadOsdu },
  props: {
    uploadUrl: { type: String, default: "/upload" },
    sessionId: { type: String, default: "" },
    accept: { type: String, default: ".epc,.h5" },
    etpConnected: { type: Boolean, default: false },
    etpConnecting: { type: Boolean, default: false },
    // the step of a connection in progress, for the Connect button
    etpStep: { type: String, default: "" },
    etpDataspaces: { type: Array, default: () => [] },
    etpStatus: { type: String, default: "" },
    // the dataspace explorer's state (`osdu_explorer`), handed verbatim to
    // <upload-osdu> — see UploadOsduExplorer.vue for its shape
    osduExplorer: { type: Object, default: () => ({}) },
    // what this session has already read, listed by <upload-file> so that
    // a reopened dialog shows the files the session holds
    loadedFiles: { type: Array, default: () => [] },
    // does the session hold anything at all? A session that holds nothing
    // can do nothing until something is imported, so the dialog opens
    // itself once (see `mounted`)
    hasData: { type: Boolean, default: false },
  },
  emits: ["uploaded", "error", "etp-connect", "etp-select", "etp-disconnect", "osdu-scan", "osdu-find", "osdu-search", "osdu-kinds"],
  data() {
    return { open: false };
  },
  watch: {
    etpStatus(now) {
      if (this.open && /^Dataspace .+ loaded\.$/.test(now || "")) this.open = false;
    },
    loadedCount(now, before) {
      if (this.open && now > before) this.open = false;
    },
  },
  computed: {
    // the dataspaces this session has read (the explorer marks their rows)
    loadedCount() {
      const rows = (this.osduExplorer || {}).dataspaces;
      return Array.isArray(rows) ? rows.filter((r) => r && r.loaded).length : 0;
    },
    // the explorer's table needs the dialog's whole width: while it is on
    // screen the dialog widens and the two sources stack, files as a strip
    wide() {
      const e = this.osduExplorer || {};
      return this.etpConnected && Array.isArray(e.dataspaces) && e.dataspaces.length > 0;
    },
  },
  mounted() {
    // AN EMPTY SESSION OPENS THE DIALOG, ONCE. With nothing loaded there is
    // nothing to look at and every panel button is disabled: the one thing
    // to do is import, so the application does not make the reader find the
    // button first. Only on MOUNT, and only while the session is empty: a
    // dialog that came back on its own after being closed would be worse
    // than one that never opened.
    if (!this.hasData) this.open = true;
    // a file let go anywhere but on a drop zone would make the browser open
    // it in place of the application: the page refuses it
    window.addEventListener("dragover", this.refuseFiles);
    window.addEventListener("drop", this.refuseFiles);
  },
  beforeUnmount() {
    window.removeEventListener("dragover", this.refuseFiles);
    window.removeEventListener("drop", this.refuseFiles);
  },
  methods: {
    refuseFiles(ev) {
      const types = (ev.dataTransfer && ev.dataTransfer.types) || [];
      // a drop zone under the pointer has taken it already
      if (!Array.from(types).includes("Files") || ev.defaultPrevented) return;
      ev.preventDefault();
      if (ev.type === "dragover") ev.dataTransfer.dropEffect = "none";
    },
    onUploaded(names) {
      // the files half closes the dialog itself (its `close`), once the
      // whole batch is read: closing on this first answer would hide a
      // second file still going up, or one that never made it at all
      this.$emit("uploaded", names);
    },
  },
};
</script>

<style>
@import "../../../_shared/panel.css";
</style>

<style scoped>
.up-root { display: inline-flex; }
.up-launch { display: inline-flex; align-items: center; gap: 6px; padding: 5px 12px;
  border: none; border-radius: 4px; background: rgba(21, 101, 192, 0.12);
  color: var(--fp-accent); font: 600 12.5px/1.4 system-ui, sans-serif; letter-spacing: 0.03em;
  text-transform: uppercase; cursor: pointer; }
.up-launch:hover { background: rgba(21, 101, 192, 0.2); }
.up-launch-ico { width: 17px; height: 17px; }
/* The scrim and the card are the shared dialog of widgets/_shared/panel.css,
   so the application has ONE modal shape and not several that drift apart. */
.up-title-ico { width: 19px; height: 19px; color: var(--fp-accent); }
/* Two sources side by side need more room than the shared 420px dialog;
   below the breakpoint they stack, and the rule between them turns
   horizontal. */
.up-dialog { width: 860px; }
.up-dialog.up-dialog-wide { width: min(1040px, 96vw); }
.up-sources { display: flex; align-items: stretch; gap: 0; }
.up-src { flex: 1 1 0; min-width: 0; display: flex; flex-direction: column; }
.up-src-h { margin: 10px 12px 0; font: 600 12px/1.4 system-ui, sans-serif;
  letter-spacing: 0.03em; text-transform: uppercase; color: var(--fp-ink-soft); }
.up-rule { width: 1px; background: var(--fp-line); margin: 10px 0; flex: 0 0 auto; }
/* the explorer mode: the sources stacked, the files half a one-line strip
   (icon, heading, drop zone) and the OSDU half the full width */
.up-sources-stack { flex-direction: column; }
.up-sources-stack .up-rule { width: auto; height: 1px; margin: 0 12px; }
.up-src-compact { flex: 0 0 auto; flex-direction: row; align-items: center; gap: 8px;
  padding: 8px 12px 6px; }
.up-src-compact .up-src-h { margin: 0; white-space: nowrap; }
.up-compact-ico { width: 17px; height: 17px; color: var(--fp-accent); flex: 0 0 auto; }
.up-file-compact { flex: 1 1 auto; min-width: 0; }
@media (max-width: 720px) {
  .up-sources { flex-direction: column; }
  .up-rule { width: auto; height: 1px; margin: 0 12px; }
}
</style>
