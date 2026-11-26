<template>
  <div class="uf" :class="{ 'uf-compact': compact }">
    <div class="uf-drop" :class="{ over: dragover }"
         @dragover.prevent="dragover = true"
         @dragleave.prevent="dragover = false"
         @drop.prevent="onDrop">
      <input ref="input" type="file" :accept="accept" multiple class="uf-file-input"
             @change="onPick" />
      <!-- compact: one line when the OSDU explorer needs the room, with the
           same drop target and the same Browse link -->
      <div class="uf-drop-msg" v-if="compact">
        Drop <b>.epc</b> (+ <b>.h5</b>) here, or
        <fp-btn variant="bare" class="uf-browse" title="Choose files on this computer" label="Browse…"
                @click="$refs.input.click()" />
      </div>
      <div class="uf-drop-msg" v-else>
        Drop <b>.epc</b> (+ its <b>.h5</b>) here<br />
        or <fp-btn variant="bare" class="uf-browse" title="Choose files on this computer" label="Browse…"
                   @click="$refs.input.click()" />
      </div>
    </div>

    <!-- What this session has ALREADY read, listed even on a reopened
         dialog. A name here is a name the reader will NOT read again (it
         keeps every path it was given, so a second copy under the same name
         is ignored): it has to be on screen before someone drops the file
         a second time. -->
    <div class="uf-prior" v-if="priorFiles.length">
      <div class="uf-prior-h">Already read in this session</div>
      <div v-for="f in priorFiles" :key="f.name" class="uf-line uf-prior-line">
        <span class="uf-ico">{{ isEpc(f.name) ? "📦" : "📄" }}</span>
        <span class="uf-name" :title="f.name">{{ f.name }}</span>
        <span class="uf-size">{{ f.size_mb }} MB</span>
        <span class="uf-state" :class="f.failed ? 'uf-state-failed' : 'uf-state-done'"
              :title="f.failed ? 'This file did not load' : 'Objects this file added to the tree'"
              >{{ f.failed ? "failed" : f.objects + " obj" }}</span>
      </div>
    </div>

    <div class="uf-files" v-if="entries.length">
      <div v-for="(e, i) in entries" :key="e.name + e.size" class="uf-file">
        <div class="uf-line">
          <span class="uf-ico">{{ isEpc(e.name) ? "📦" : "📄" }}</span>
          <span class="uf-name" :title="e.name">{{ e.name }}</span>
          <span class="uf-size">{{ human(e.size) }}</span>
          <span class="uf-state" :class="'uf-state-' + e.status">{{ word(e) }}</span>
          <fp-btn v-if="e.status === 'waiting' || (e.status === 'sending' && !bodySent)"
                  variant="bare" class="uf-rm"
                  title="Remove this file from the import — the others go on" @click="drop(i)">×</fp-btn>
        </div>
        <!-- one bar per file: the parts of a multipart body go up in the
             order they were appended, so the bytes already sent say exactly
             which file is in flight and how far it is -->
        <fp-progress class="uf-progress" v-if="e.status === 'sending' || e.status === 'done'"
                     :value="e.progress" :done="e.status === 'done'" />
      </div>
      <div class="uf-warn" v-if="missingH5">
        ⚠ An <b>.epc</b> usually needs its companion <b>.h5</b> — add it too, or the load may fail.
      </div>
    </div>

    <div class="uf-foot">
      <!-- No Import button: a file dropped is a file imported. The short
           wait only lets an .epc and its .h5, dropped one after the other,
           travel together: the server reads an .epc against the .h5 of the
           same request. -->
      <span v-if="status" class="uf-status" :class="{ 'uf-status-done': allDone }">{{ status }}</span>
      <!-- while the files go up: once the server has them all, it reads them
           and the page's own wait says so -->
      <fp-btn v-if="sending && !bodySent" class="uf-cancel" label="Cancel"
              title="Stop sending these files: nothing of them is kept" @click="cancel" />
      <fp-btn v-if="allDone" class="uf-close" variant="primary" label="Close"
              title="Close this dialog — every file has been read" @click="$emit('close')" />
    </div>
  </div>
</template>

<script>
/*
 * Fine-grained file-import widget: pick/drop .epc/.h5 -> POST multipart
 * FormData to the server's /upload endpoint (or api/{sessionId}/upload
 * behind the launcher proxy); the server stores the files in the session
 * temp dir and loads each .epc.
 *   props in   — upload_url / session_id / accept / loaded (what the
 *                session has read already, listed even on a reopened
 *                dialog) / compact (the drop zone as a one-line strip)
 *   events out — uploaded(names) / error(message) / close
 *
 * CANCEL stops the request while its bytes go up: the files of the batch
 * leave the list, and the server removes what it had received of them
 * (engine/io/upload_endpoint). Once every byte is sent the server is reading
 * them, and Cancel goes. A file's own cross takes that file alone out: the
 * batch travels as one request (an .epc goes with its .h5), so the request
 * stops and the other files go again without it.
 *
 * THE SEND STARTS BY ITSELF: there is no Import button to press after a
 * drop. The send is only DELAYED, by `SETTLE` ms rearmed on every add: an
 * .epc and its .h5 dropped one after the other must go in the SAME
 * request, because the server reads an .epc against the .h5 it received
 * with it (otherwise it would report "only an .h5 was imported" between
 * the two).
 *
 * ONE BAR PER FILE. A single XHR reports the bytes it has sent, and the
 * parts of a multipart body travel in the order they were appended, so the
 * count of sent bytes says which file is going up and how far it has got.
 * Nothing is estimated: every bar is read off that one byte count.
 *
 * THE URL IS RELATIVE TO THE PAGE, never absolute. When the application is
 * served under a path prefix (TRAME_URL_PREFIX, behind a reverse proxy),
 * the proxy routes only `<prefix>/api/(sid)/(rest)` to the session: an
 * absolute `/api/{sid}/upload` drops the prefix and reaches whatever else
 * the proxy serves, so the upload fails with an unrelated error.
 * Resolving against `window.location` gives `<prefix>/api/…` under a
 * prefix and `/api/…` without one, with nothing to configure either way.
 */
import FpBtn from "../../../../_shared/components/FpBtn.vue";
import FpProgress from "../../../../_shared/components/FpProgress.vue";
import { fmtBytes } from "../../../../_shared/numfmt.js";

// how long a drop waits for the file that belongs with it
const SETTLE = 450;
// how long a batch read in full stays on screen before the dialog closes
const CLOSE_BEAT = 900;

export default {
  name: "UploadFile",
  props: {
    uploadUrl: { type: String, default: "/upload" },
    sessionId: { type: String, default: "" },
    accept: { type: String, default: ".epc,.h5" },
    // what the session read BEFORE this dialog was opened, from the host's
    // own list: [{ name, size_mb, objects, failed }]
    loaded: { type: Array, default: () => [] },
    // the drop zone as a single strip (while the OSDU explorer takes the
    // dialog's width)
    compact: { type: Boolean, default: false },
  },
  components: { FpBtn, FpProgress },
  emits: ["uploaded", "error", "close"],
  data() {
    // entry: { file, name, size, status: waiting|sending|done|failed, progress }
    return { entries: [], dragover: false, sending: false, bodySent: false, timer: null, xhr: null,
             resend: false };
  },
  beforeUnmount() { if (this.timer) clearTimeout(this.timer); },
  computed: {
    // where the files go, resolved against the page so that the prefix the
    // application is served under is kept (see the header note); an
    // absolute http(s) upload_url without a session id is used as given
    endpoint() {
      const tail = this.sessionId
        ? `api/${this.sessionId}/upload`
        : String(this.uploadUrl || "upload").replace(/^\/+/, "");
      if (/^https?:\/\//i.test(this.uploadUrl) && !this.sessionId) return this.uploadUrl;
      try {
        return new URL(tail, window.location.href).toString();
      } catch (e) {
        return "/" + tail;  // no window (a test bench): an absolute path
      }
    },
    // the already-read files, minus the ones this dialog is showing live: a
    // file read a moment ago is in BOTH lists, and would show twice
    priorFiles() {
      const live = new Set(this.entries.map((e) => e.name));
      return (this.loaded || []).filter((f) => f && f.name && !live.has(f.name));
    },
    allDone() {
      return this.entries.length > 0
        && this.entries.every((e) => e.status === "done" || e.status === "failed");
    },
    status() {
      if (!this.entries.length) return "";
      const n = this.entries.length;
      if (this.sending) return this.bodySent ? "Reading…" : "Uploading…";
      if (this.allDone) {
        const failed = this.entries.filter((e) => e.status === "failed").length;
        if (failed) return `${failed} of ${n} file(s) did not go through`;
        return `${n} file(s) read — the data tree is filled`;
      }
      return "Waiting a moment for a file that belongs with this one…";
    },
    missingH5() {
      const hasEpc = this.entries.some((e) => this.isEpc(e.name));
      const hasH5 = this.entries.some((e) => e.name.toLowerCase().endsWith(".h5"));
      return hasEpc && !hasH5 && !this.sending;
    },
  },
  methods: {
    isEpc(name) { return String(name).toLowerCase().endsWith(".epc"); },
    // decimal units, as the OSDU table of this dialog and the server write
    human(n) { return fmtBytes(n); },
    word(e) {
      return { waiting: "", sending: e.progress + "%", done: "read", failed: "failed" }[e.status];
    },
    onPick(ev) { this.add(ev.target.files); ev.target.value = ""; },
    onDrop(ev) { this.dragover = false; this.add(ev.dataTransfer.files); },
    add(list) {
      let added = 0;
      for (const f of Array.from(list || [])) {
        if (!this.entries.some((e) => e.name === f.name && e.size === f.size)) {
          this.entries.push({
            file: f, name: f.name, size: f.size, status: "waiting", progress: 0,
          });
          added += 1;
        }
      }
      if (added) this.arm();
    },
    remove(i) {
      this.entries.splice(i, 1);
      if (!this.entries.some((e) => e.status === "waiting") && this.timer) {
        clearTimeout(this.timer); this.timer = null;
      }
    },
    /* One file out of the import: a waiting one leaves the list; one in
       flight stops the request, which goes again with the others. */
    drop(i) {
      const e = this.entries[i];
      if (!e) return;
      if (e.status === "waiting") { this.remove(i); return; }
      if (e.status !== "sending" || !this.xhr || this.bodySent) return;
      this.entries.splice(i, 1);
      this.resend = true;
      this.xhr.abort();
    },
    /* The batch in flight stopped, and the files waiting for it dropped. */
    cancel() {
      if (this.timer) { clearTimeout(this.timer); this.timer = null; }
      this.resend = false;
      if (this.xhr && !this.bodySent) this.xhr.abort();
    },
    /* Rearmed on every add: the last file of a batch decides when it goes. */
    arm() {
      if (this.timer) clearTimeout(this.timer);
      this.timer = setTimeout(() => { this.timer = null; this.send(); }, SETTLE);
    },
    send() {
      if (this.sending) { this.arm(); return; }
      const batch = this.entries.filter((e) => e.status === "waiting");
      if (!batch.length) return;
      // the .h5 first: the server writes the parts in order and reads an
      // .epc as soon as it has it, so its side file must already be there
      batch.sort((a, b) => (this.isEpc(a.name) ? 1 : 0) - (this.isEpc(b.name) ? 1 : 0));
      const fd = new FormData();
      let total = 0;
      const offsets = [];
      for (const e of batch) {
        offsets.push(total);
        total += e.size;
        fd.append("files", e.file);
        e.status = "sending"; e.progress = 0;
      }
      const xhr = new XMLHttpRequest();
      this.xhr = xhr;
      this.bodySent = false;
      xhr.open("POST", this.endpoint);
      xhr.setRequestHeader("X-File-Size", String(total));
      xhr.upload.onprogress = (ev) => {
        if (!ev.lengthComputable || !total) return;
        // the body carries a little more than the files (part headers): the
        // bars are read against the files' own bytes, and clamped
        const sent = Math.min(ev.loaded, total);
        batch.forEach((e, i) => {
          const done = Math.max(0, Math.min(e.size, sent - offsets[i]));
          e.progress = e.size ? Math.round((done / e.size) * 100) : 100;
        });
      };
      xhr.upload.onload = () => { this.bodySent = true; };
      xhr.onabort = () => {
        this.sending = false;
        this.xhr = null;
        if (this.resend) {
          this.resend = false;
          this.entries.forEach((e) => {
            if (e.status === "sending") { e.status = "waiting"; e.progress = 0; }
          });
          if (this.entries.some((e) => e.status === "waiting")) this.arm();
          return;
        }
        this.entries = this.entries.filter((e) => e.status !== "sending" && e.status !== "waiting");
      };
      xhr.onload = () => {
        this.sending = false;
        this.xhr = null;
        if (xhr.status >= 200 && xhr.status < 300) {
          batch.forEach((e) => { e.status = "done"; e.progress = 100; });
          this.$emit("uploaded", batch.map((e) => e.name));
          // every file read, none failed, none waiting: the dialog closes by
          // itself (the manager, 15/10), after a beat that lets "read" show.
          // A failure keeps it open, the reason under the file.
          setTimeout(() => {
            if (this.allDone && !this.entries.some((e) => e.status === "failed")) {
              this.$emit("close");
            }
          }, CLOSE_BEAT);
        } else {
          batch.forEach((e) => { e.status = "failed"; });
          let reason = "";
          try { reason = (JSON.parse(xhr.responseText) || {}).message || ""; } catch (e) { /* not JSON */ }
          this.$emit("error", reason || "Upload failed: " + xhr.status);
        }
        // a file added while this batch was in flight goes in the next one
        if (this.entries.some((e) => e.status === "waiting")) this.arm();
      };
      xhr.onerror = () => {
        this.sending = false;
        this.xhr = null;
        batch.forEach((e) => { e.status = "failed"; });
        this.$emit("error", "Upload failed (network)");
      };
      this.sending = true;
      xhr.send(fd);
    },
  },
};
</script>

<style>
@import "../../../../_shared/tokens.css";
</style>

<style scoped>
.uf { display: flex; flex-direction: column; font-family: system-ui, sans-serif; font-size: 13px; }
.uf-drop { position: relative; margin: 8px; border: 2px dashed #bbb; border-radius: 5px;
  padding: 18px 10px; text-align: center; color: #666; }
.uf-drop.over { border-color: var(--fp-accent); background: #f0f7ff; }
/* the strip: one line, no margin of its own (the host lays it out) */
.uf-compact .uf-drop { margin: 0; padding: 5px 10px; text-align: left; }
.uf-compact .uf-drop-msg { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.uf-file-input { position: absolute; inset: 0; opacity: 0; cursor: pointer; }
.uf-browse { background: none; border: none; color: var(--fp-accent); cursor: pointer;
  text-decoration: underline; font: inherit; position: relative; z-index: 1; }
.uf-prior { padding: 0 8px 2px; }
.uf-prior-h { font: 600 11px/1.8 system-ui, sans-serif; letter-spacing: 0.03em;
  text-transform: uppercase; color: var(--fp-ink-soft); }
.uf-prior-line { padding: 2px 0; color: #555; }
.uf-files { padding: 0 8px; max-height: 200px; overflow: auto; }
.uf-file { padding: 3px 0; }
.uf-line { display: flex; align-items: center; gap: 6px; }
.uf-ico { width: 18px; }
.uf-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.uf-size { color: #999; font-size: 11px; }
.uf-state { font-size: 11px; font-weight: 600; min-width: 3.2em; text-align: right; }
.uf-state-sending { color: var(--fp-accent); font-variant-numeric: tabular-nums; }
.uf-state-done { color: #2e7d32; }
.uf-state-failed { color: var(--fp-error-ink); }
.uf-rm { cursor: pointer; color: #c33; opacity: 0.7; }
.uf-rm:hover { opacity: 1; }
.uf-warn { color: #b26a00; background: #fff7e6; border-radius: 3px; padding: 4px 6px;
  margin: 4px 0; font-size: 12px; }
.uf-foot { padding: 8px; border-top: 1px solid #eee; display: flex; align-items: center; gap: 8px; }
.uf-status { flex: 1; color: var(--fp-ink-soft); font-size: 12px; }
.uf-status-done { color: #2e7d32; font-weight: 600; }
.uf-close, .uf-cancel { padding: 5px 14px; }
.uf-progress { margin: 2px 0 0 24px; }
</style>
