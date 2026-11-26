<template>
  <div class="fse-root">
    <!-- The trigger wears the look of its neighbours in the app bar (Vuetify
         icon buttons, variant text, colour primary, size small): a round
         36 px target, no frame, the accent ink. -->
    <fp-btn icon class="fse-launch" data-fp-session-launch
            title="Session — save what is shown to a .fespp.json file, or open one to restore it"
            @click="show()">
      <fp-icon class="fse-launch-ico" icon="fespp-session" mono :size="22" />
    </fp-btn>

    <Teleport to="body">
      <div class="fp-scrim fse-scrim" v-if="open" @click.self="hide()">
        <div ref="dialog" class="fp-dialog fse" role="dialog" aria-modal="true" tabindex="-1"
             data-fp-session-dialog :data-fp-phase="phase">
          <div class="fp-dialog-head fse-o-head">
            <fp-icon class="fse-title-ico" icon="fespp-session" mono :size="19" />
            <span class="fp-title">Session</span>
            <fp-btn variant="bare" label="×" title="Close (the session file stays open)" @click="hide()" />
          </div>
          <fp-progress v-if="phase === 'restoring'" class="fse-o-head" data-fp-busy />

          <!-- 1. SAVE -->
          <section class="fse-sec" data-fp-session-save>
            <h3 class="fse-h">Save</h3>
            <div class="fp-sum">
              Saves what is shown and how — the data itself is not in the file:
              it will be loaded again when the session is opened.
            </div>
            <div class="fse-row">
              <input v-model="note" class="fp-input fse-note" type="text" maxlength="500"
                     placeholder="Note (optional)"
                     title="A note kept in the file and shown when the session is opened"
                     @keydown.enter="save()">
              <fp-btn variant="primary" label="Save session" :disabled="!hasData || busy"
                      :title="hasData
                        ? 'Save the state of the application to a .fespp.json file on this computer'
                        : 'Nothing to save: import data first (Import data)'"
                      @click="save()" />
            </div>
            <div v-if="storeNote" class="fp-sum fse-quiet">{{ storeNote }}</div>
          </section>

          <div class="fse-rule" role="separator"></div>

          <!-- 2. OPEN -->
          <section class="fse-sec" data-fp-session-open>
            <h3 class="fse-h">Open</h3>

            <!-- the picker: idle and error, where there is no session file
                 in hand -->
            <template v-if="phase === 'idle' || phase === 'error'">
              <div class="fse-drop" :class="{ 'fse-drop-on': dragging }"
                   @dragenter.prevent="dragging = true" @dragover.prevent="dragging = true"
                   @dragleave.prevent="dragging = false" @drop.prevent="onDrop">
                <fp-empty v-if="phase === 'idle'"
                          shows="A saved session restores the views, what they show and how."
                          gesture="Drop a .fespp.json file here, or press &quot;Choose File&quot;." />
                <fp-btn label="Choose File" title="Pick a .fespp.json session file on this computer"
                        @click="$refs.picker.click()" />
                <input ref="picker" class="fse-hidden" type="file" accept=".json,.fespp.json"
                       @change="onPick">
              </div>
              <fp-note v-if="pickError" severity="error" :text="pickError"
                       next="Pick a file ending in .fespp.json." />
              <fp-note v-if="phase === 'error'" severity="error"
                       :text="(st.file ? st.file + ': ' : '') + (st.error || 'the session file could not be read')"
                       next="Pick another session file." />
            </template>

            <!-- a session file in hand -->
            <template v-else>
              <dl class="fse-facts">
                <dt>File</dt><dd>{{ st.file || DASH }}</dd>
                <dt>Saved</dt><dd>{{ st.saved || DASH }}</dd>
                <dt>By</dt><dd>{{ st.app || DASH }}</dd>
                <dt>Views</dt><dd>{{ viewsText }}</dd>
                <template v-if="st.note"><dt>Note</dt><dd class="fse-pre">{{ st.note }}</dd></template>
              </dl>

              <template v-if="phase !== 'done'">
                <div class="fse-sub">Data to load again ({{ filesSummary }})</div>
                <table v-if="files.length" class="fp-table fse-files">
                  <tbody>
                    <tr v-for="f in files" :key="f.name" :data-fp-file-state="f.state">
                      <td class="fse-fname" :title="f.name">{{ f.name }}</td>
                      <td class="num">{{ sizeText(f.size_mb) }}</td>
                      <td>
                        <fp-chip sm :variant="STATE[f.state] ? STATE[f.state].variant : 'neutral'"
                                 :text="STATE[f.state] ? STATE[f.state].text : (f.state || DASH)"
                                 :title="stateTitle(f)" />
                      </td>
                      <td class="fse-why">{{ f.why || "" }}</td>
                    </tr>
                  </tbody>
                </table>
                <div v-else-if="!etp" class="fp-sum">The session names no file.</div>

                <!-- the OSDU / ETP part: the facts, one row per saved
                     dataspace, and — until it is all back — the host's
                     prefilled OSDU form, where only the token is asked -->
                <template v-if="etp">
                  <div class="fse-sub">OSDU / ETP ({{ etpSummary }})</div>
                  <dl class="fse-facts" data-fp-session-etp :data-fp-etp-ready="etpReady ? '' : null">
                    <dt>Server</dt><dd>{{ etp.url || DASH }}</dd>
                    <dt>Partition</dt><dd>{{ etp.partition || DASH }}</dd>
                  </dl>
                  <table v-if="etpRows.length" class="fp-table fse-files">
                    <tbody>
                      <tr v-for="d in etpRows" :key="d.uri" :data-fp-dataspace-state="d.state">
                        <td class="fse-fname fse-space" :title="d.uri">{{ d.uri }}</td>
                        <td>
                          <fp-chip sm :variant="DS_STATE[d.state].variant" :text="DS_STATE[d.state].text"
                                   :title="DS_STATE[d.state].title" />
                        </td>
                      </tr>
                    </tbody>
                  </table>
                  <div v-else class="fp-sum">The session names no dataspace.</div>
                  <template v-if="!etpReady && (phase === 'waiting' || phase === 'ready')">
                    <div class="fp-sum">
                      Enter your access token to reconnect — the dataspaces load by themselves
                      once connected.
                    </div>
                    <div class="fse-slot" data-fp-session-etp-slot>
                      <slot name="etp" />
                    </div>
                  </template>
                </template>

                <div v-if="phase === 'waiting' && missing.length" class="fse-slot">
                  <slot name="files" />
                </div>

                <div v-if="phase === 'restoring'" class="fp-sum" aria-live="polite">Restoring the session…</div>
              </template>

              <!-- the report, errors first -->
              <template v-else>
                <div class="fse-sub">Restored ({{ reportSummary }})</div>
                <div class="fse-report" data-fp-session-report>
                  <template v-for="g in reportGroups" :key="g.level">
                    <div v-if="g.items.length" class="fse-rgroup" :class="'fse-r-' + g.level">
                      <div class="fse-rhead">{{ g.head }} ({{ g.items.length }})</div>
                      <ul>
                        <li v-for="(r, i) in g.items" :key="i">{{ r.text }}</li>
                      </ul>
                    </div>
                  </template>
                  <div v-if="!report.length" class="fp-sum">The restore said nothing.</div>
                </div>
              </template>
            </template>
          </section>

          <!-- 3. THE LAST AUTOSAVE this browser holds. Shown FIRST (CSS order)
               when the session is empty, where after a crash it is the one
               thing to offer; otherwise last, under Open. -->
          <section v-if="stored" class="fse-sec fse-auto" :class="autoFirst ? 'fse-o-first' : 'fse-o-last'"
                   data-fp-session-autosave>
            <div v-if="!autoFirst" class="fse-rule fse-auto-rule" role="separator"></div>
            <h3 class="fse-h">Last autosave</h3>
            <div v-if="autoFirst" class="fse-offer">
              The last session of {{ storedWhen }} can be resumed: {{ storedViews }},
              files {{ storedFiles }} — the data will be loaded again.
            </div>
            <dl v-else class="fse-facts">
              <dt>Saved</dt><dd>{{ storedWhen }}</dd>
              <dt>Views</dt><dd>{{ storedViewsCount }}</dd>
              <dt>Files</dt><dd>{{ storedFiles }}</dd>
            </dl>
            <div class="fse-row fse-auto-acts">
              <fp-btn v-if="canResume" label="Resume" :variant="autoFirst ? 'primary' : 'default'"
                      title="Open the last autosave as a session file: the files it needs are listed, then Restore"
                      @click="resume()" />
              <fp-btn label="Download"
                      title="Save the last autosave as a .fespp.json file on this computer (works without the server)"
                      @click="downloadStored()" />
              <fp-btn label="Discard"
                      title="Remove the last autosave from this browser — it cannot be undone"
                      @click="discard()" />
            </div>
            <div v-if="autoFirst" class="fse-rule fse-auto-rule" role="separator"></div>
          </section>

          <div v-if="phase !== 'idle' && phase !== 'error'" class="fp-dialog-foot fse-o-foot">
            <fp-btn label="Forget" :disabled="busy"
                    title="Forget this session file: nothing loaded or shown changes"
                    @click="$emit('reset')" />
            <template v-if="phase === 'done'">
              <fp-btn variant="primary" label="Close" title="Close the dialog" @click="hide()" />
            </template>
            <template v-else>
              <fp-btn v-if="!allThere" label="Restore anyway" :busy="busy"
                      :title="'Restore without ' + absentText
                        + ': the objects they hold are skipped and listed in the report'"
                      @click="$emit('apply')" />
              <fp-btn variant="primary" label="Restore" :busy="busy"
                      :disabled="!allThere"
                      :title="!allThere
                        ? 'Load ' + absentText + ' first ('
                          + (missing.length ? 'drop the files above' : 'enter the access token above')
                          + '), or press Restore anyway'
                        : 'Restore the views, what they show and how'"
                      @click="$emit('apply')" />
            </template>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script>
/*
 * The session door: SAVE the state of the whole application to a
 * `.fespp.json` file on the reader's computer, OPEN one to restore it.
 *
 * The file holds the STATE only — what is shown and how. The data (the EPC
 * and its h5, or an OSDU/ETP connection) is loaded again, and the dialog
 * guides it: the expected files are listed with their state, and the host's
 * own drop zone is mounted in the `files` slot so they are dropped without
 * leaving the dialog. A session read from OSDU / ETP keeps the server URL,
 * the data partition and its dataspaces — never the access token: they are
 * listed with their state, and until the host says `etp_ready` its OSDU
 * form, prefilled, is mounted in the `etp` slot, where only the token is
 * asked.
 *
 * Pure display, like every widget of this project:
 *   props in   — hasData, status {phase, file, saved, note, app, views,
 *                files, etp {url, partition, dataspaces, connected, loaded},
 *                etp_ready, report, error}, download {name, text, n},
 *                autosave {text, sig, saved, views, files, n}
 *   events out — save(note), open({name, text}), apply(), reset()
 *
 * The dialog opens BY ITSELF when the phase becomes "waiting" or "done":
 * the reader opened a file or asked for a restore, and what came of it is
 * the next thing to read. It stays closable. Nothing else opens it unasked,
 * not even a stored autosave at start.
 *
 * AUTOSAVE. The host pushes the state on every change (`autosave`); each new
 * `n` is kept in this browser's localStorage under STORE_KEY, so a server
 * that crashed — its session and its temporary files gone — still leaves the
 * reader the last state: on an empty session the dialog shows the Resume
 * offer first, and a lost connection offers the download (`watchConnection`).
 * Storage may be blocked or full: every access is guarded, and a failure is
 * one quiet line, never an error.
 */
import FpBtn from "../../../_shared/components/FpBtn.vue";
import FpChip from "../../../_shared/components/FpChip.vue";
import FpEmpty from "../../../_shared/components/FpEmpty.vue";
import FpIcon from "../../../_shared/components/FpIcon.vue";
import FpNote from "../../../_shared/components/FpNote.vue";
import FpProgress from "../../../_shared/components/FpProgress.vue";
import { fmt, fmtInt, DASH, NBSP } from "../../../_shared/numfmt.js";


const STATE = {
  missing: { text: "Missing", variant: "warn",
    title: "Not loaded in this session yet: drop it in the zone below, or import it through Import data" },
  loaded: { text: "Loaded", variant: "accent",
    title: "Loaded in this session" },
  different: { text: "Different", variant: "warn",
    title: "A file of this name is loaded, but it is not the one the session was saved with" },
};

// a saved dataspace of an OSDU / ETP session
const DS_STATE = {
  loaded: { text: "Loaded", variant: "accent",
    title: "This dataspace is loaded in this session" },
  pending: { text: "To load", variant: "warn",
    title: "Not loaded yet: it loads by itself once the OSDU form below is connected" },
};

const PHASES =["idle", "waiting", "ready", "restoring", "done", "error"];

// a session file is JSON: `.fespp.json` by name, `.json` accepted
const OK_NAME = /\.json$/i;

// where this browser keeps the last autosave
const STORE_KEY = "fespp-on-trame:session-autosave";

function readStore() {
  try {
    const raw = window.localStorage.getItem(STORE_KEY);
    if (!raw) return null;
    const v = JSON.parse(raw);
    return v && typeof v.text === "string" && v.text ? v : null;
  } catch (e) {
    return null;
  }
}

const pad = (x) => String(x).padStart(2, "0");

// an ISO date in the reader's local time: ["YYYY-MM-DD", "HH:MM"], or null
function localParts(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return [d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()),
    pad(d.getHours()) + ":" + pad(d.getMinutes())];
}

// a file handed to the reader's computer: Blob, object URL, a temporary <a download>
function handFile(name, text) {
  const blob = new Blob([text], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.style.display = "none";
  document.body.appendChild(a);
  a.click();
  a.remove();
  // the browser has taken the file once the click returns; the URL is let go
  // a moment later, for the engines that start the download asynchronously
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function autosaveName(stored) {
  const p = localParts(stored && stored.saved);
  return "autosave-" + (p ? p[0] + "-" + p[1].replace(":", "") : "last") + ".fespp.json";
}

// The non-modal notice of a lost connection (see `watchConnection`). Plain
// DOM on <body>: trame swaps its main template on a lost connection, which
// unmounts this widget, and the notice has to outlive it. Written with the
// shared classes, which the page already holds.
function lostNotice() {
  const stored = readStore();
  if (!stored || document.querySelector("[data-fp-session-lost]")) return;
  const p = localParts(stored.saved);
  const box = document.createElement("div");
  box.className = "fse-lost";
  box.setAttribute("data-fp-session-lost", "");
  box.setAttribute("role", "status");
  const text = document.createElement("span");
  text.textContent = "The connection to the server was lost. This browser holds the last state"
    + (p ? " (" + p[0] + " " + p[1] + ")" : "") + ".";
  const get = document.createElement("button");
  get.type = "button";
  get.className = "fp-btn fp-primary";
  get.textContent = "Download the last state";
  get.title = "Save the last autosave as a .fespp.json file on this computer";
  get.addEventListener("click", () => handFile(autosaveName(stored), stored.text));
  const close = document.createElement("button");
  close.type = "button";
  close.className = "fp-btn fp-chip-btn";
  close.textContent = "×";
  close.title = "Dismiss this notice (the last state stays in this browser)";
  close.addEventListener("click", () => box.remove());
  box.append(text, get, close);
  document.body.appendChild(box);
}

export default {
  name: "SessionDoor",
  components: { FpBtn, FpChip, FpEmpty, FpIcon, FpNote, FpProgress },
  props: {
    hasData: { type: Boolean, default: false },
    status: { type: Object, default: () => ({}) },
    download: { type: Object, default: () => ({}) },
    autosave: { type: Object, default: () => ({}) },
  },
  emits: ["save", "open", "apply", "reset"],
  data() {
    return {
      STATE, DS_STATE, DASH,
      open: false,
      note: "",
      dragging: false,
      pickError: "",
      // the download already handed over: a reconnect that replays the
      // state must not save the file a second time
      lastN: null,
      // same rule for the autosave: the n seen at mount is not new
      lastAutoN: null,
      // the last autosave this browser holds: {text, saved, views, files}
      stored: null,
      // one quiet line when the browser refused to keep it
      storeNote: "",
      connSub: null,
    };
  },
  computed: {
    // the session is empty: the autosave is THE thing to offer, first
    autoFirst() {
      return !this.hasData && (this.phase === "idle" || this.phase === "error");
    },
    // not while a session file is already open
    canResume() {
      return !["waiting", "ready", "restoring"].includes(this.phase);
    },
    storedWhen() {
      const p = localParts(this.stored && this.stored.saved);
      return p ? p[0] + " " + p[1] : DASH;
    },
    storedViewsCount() {
      const v = this.stored && this.stored.views;
      return v === undefined || v === null ? DASH : fmtInt(v);
    },
    storedViews() {
      const v = this.stored && this.stored.views;
      if (v === undefined || v === null) return "views unknown";
      return fmtInt(v) + (Number(v) === 1 ? " view" : " views");
    },
    storedFiles() {
      const f = this.stored && this.stored.files;
      return Array.isArray(f) && f.length ? f.join(", ") : DASH;
    },
    st() {
      return this.status || {};
    },
    phase() {
      const p = this.st.phase;
      return PHASES.includes(p) ? p : "idle";
    },
    busy() {
      return this.phase === "restoring";
    },
    files() {
      return Array.isArray(this.st.files) ? this.st.files : [];
    },
    missing() {
      return this.files.filter((f) => f && f.state === "missing");
    },
    missingNames() {
      const n = this.missing.map((f) => f.name);
      return n.length > 3 ? n.slice(0, 3).join(", ") + " and " + fmtInt(n.length - 3) + " more"
        : n.join(", ");
    },
    filesSummary() {
      const loaded = this.files.filter((f) => f && f.state === "loaded").length;
      return fmtInt(loaded) + " of " + fmtInt(this.files.length) + " loaded";
    },
    viewsText() {
      const v = this.st.views;
      return v === undefined || v === null ? DASH : fmtInt(v);
    },
    // the OSDU / ETP part of the session, or null for a files-only session
    etp() {
      const e = this.st.etp;
      return e && typeof e === "object" ? e : null;
    },
    // connected, and every saved dataspace loaded (the host's word)
    etpReady() {
      return !this.etp || this.st.etp_ready === true;
    },
    etpRows() {
      const saved = this.etp && Array.isArray(this.etp.dataspaces) ? this.etp.dataspaces : [];
      const loaded = this.etp && Array.isArray(this.etp.loaded) ? this.etp.loaded : [];
      return saved.map((uri) => ({ uri, state: loaded.includes(uri) ? "loaded" : "pending" }));
    },
    etpPending() {
      return this.etpRows.filter((d) => d.state === "pending").map((d) => d.uri);
    },
    etpSummary() {
      const n = this.etpRows.length;
      const conn = this.etp && this.etp.connected ? "connected" : "not connected";
      return conn + ", " + fmtInt(n - this.etpPending.length) + " of " + fmtInt(n) + " dataspaces loaded";
    },
    // nothing the session needs is absent: Restore is offered as is
    allThere() {
      return !this.missing.length && this.etpReady;
    },
    // what Restore anyway goes without: the missing files, then the ETP part
    absentText() {
      const parts = [];
      if (this.missing.length) parts.push(this.missingNames);
      if (!this.etpReady) {
        const n = this.etpPending.length;
        parts.push(n ? fmtInt(n) + (n === 1 ? " dataspace" : " dataspaces") + " of the OSDU server"
          : "the OSDU connection");
      }
      return parts.join(" and ");
    },
    report() {
      return Array.isArray(this.st.report) ? this.st.report : [];
    },
    reportGroups() {
      const by = (lv) => this.report.filter((r) => r && r.level === lv);
      return [
        { level: "error", head: "Not restored", items: by("error") },
        { level: "warn", head: "Restored with a warning", items: by("warn") },
        { level: "ok", head: "Restored", items: by("ok") },
      ];
    },
    reportSummary() {
      const [e, w, o] = this.reportGroups.map((g) => g.items.length);
      return fmtInt(o) + " ok, " + fmtInt(w) + " with a warning, " + fmtInt(e) + " not restored";
    },
  },
  watch: {
    phase(now, before) {
      // a document applied by itself (a URL, a host page) says `silent`:
      // its report waits in the door, the door does not open on it
      if (now !== before && (now === "waiting" || now === "done") && !this.st.silent) this.show();
      if (now !== "idle" && now !== "error") this.pickError = "";
    },
    "download.n"(n) {
      this.hand(n);
    },
    "autosave.n"(n) {
      this.keep(n);
    },
  },
  mounted() {
    this.lastN = this.download ? this.download.n : null;
    this.lastAutoN = this.autosave ? this.autosave.n : null;
    this.stored = readStore();
    // the browser may still hold the last state (a crash, a reload): the
    // Resume offer waits inside the door, first in line, and the door opens
    // on the reader's click only — nothing opens by itself at start.
    // Esc closes the dialog wherever the focus is: a button that disappears
    // under the click ("Forget") drops the focus to the page, and a handler
    // on the dialog alone would then never hear the key
    window.addEventListener("keydown", this.onKey);
    this.watchConnection();
  },
  beforeUnmount() {
    window.removeEventListener("keydown", this.onKey);
    try {
      if (this.connSub) this.connSub.unsubscribe();
    } catch (e) {
      // gone with the client
    }
  },
  methods: {
    onKey(ev) {
      if (this.open && ev.key === "Escape") this.hide();
    },
    show() {
      this.open = true;
      // the dialog takes the focus, so Esc closes it
      this.$nextTick(() => { if (this.$refs.dialog) this.$refs.dialog.focus(); });
    },
    hide() {
      this.open = false;
      this.dragging = false;
    },
    save() {
      if (!this.hasData || this.busy) return;
      this.$emit("save", (this.note || "").trim());
    },
    sizeText(mb) {
      return mb === undefined || mb === null ? DASH : fmt(mb) + NBSP + "MB";
    },
    stateTitle(f) {
      const s = STATE[f.state];
      const base = s ? s.title : "State unknown";
      return f.why ? base + " — " + f.why : base;
    },
    onPick(ev) {
      const input = ev.target;
      const file = input.files && input.files[0];
      this.read(file);
      // the same file picked twice in a row must still fire `change`
      input.value = "";
    },
    onDrop(ev) {
      this.dragging = false;
      const list = ev.dataTransfer && ev.dataTransfer.files;
      if (!list || !list.length) return;
      if (list.length > 1) {
        this.pickError = "Drop ONE session file, not " + fmtInt(list.length) + " files";
        return;
      }
      this.read(list[0]);
    },
    read(file) {
      if (!file) return;
      if (!OK_NAME.test(file.name)) {
        this.pickError = "“" + file.name + "” is not a session file"
          + " — the EPC and h5 files go through Import data";
        return;
      }
      this.pickError = "";
      const reader = new FileReader();
      reader.onload = () => {
        this.$emit("open", { name: file.name, text: String(reader.result || "") });
      };
      reader.onerror = () => {
        this.pickError = "“" + file.name + "” could not be read by the browser";
      };
      reader.readAsText(file);
    },
    hand(n) {
      const d = this.download || {};
      if (n === undefined || n === null || n === this.lastN || !d.text) return;
      this.lastN = n;
      handFile(d.name || "session.fespp.json", d.text);
    },
    keep(n) {
      const a = this.autosave || {};
      if (n === undefined || n === null || n === this.lastAutoN || !a.text) return;
      this.lastAutoN = n;
      const v = { text: a.text, saved: a.saved || new Date().toISOString(),
        views: a.views, files: Array.isArray(a.files) ? a.files : [] };
      this.stored = v;
      try {
        window.localStorage.setItem(STORE_KEY, JSON.stringify(v));
        this.storeNote = "";
      } catch (e) {
        this.storeNote = "This browser did not keep the autosave (storage blocked or full).";
      }
    },
    resume() {
      if (!this.stored) return;
      this.$emit("open", { name: autosaveName(this.stored), text: this.stored.text });
    },
    downloadStored() {
      if (this.stored) handFile(autosaveName(this.stored), this.stored.text);
    },
    discard() {
      try {
        window.localStorage.removeItem(STORE_KEY);
      } catch (e) {
        // nothing kept, nothing to remove
      }
      this.stored = null;
    },
    /*
     * A lost connection. trame's own client (window.trame, trame-client's
     * vue3 app) subscribes to `client.onConnectionClose` of the wslink
     * client and, on it, REPLACES the main template with its loading /
     * reconnect page — which unmounts this widget. The listener here is the
     * same public subscription; it builds the notice synchronously, as plain
     * DOM on <body>, before the unmount lands.
     */
    watchConnection() {
      try {
        const client = window.trame && window.trame.client;
        if (!client || typeof client.onConnectionClose !== "function") return;
        this.connSub = client.onConnectionClose(() => lostNotice());
      } catch (e) {
        this.connSub = null;
      }
    },
  },
};
</script>

<style>
@import "../../../_shared/panel.css";
</style>

<style scoped>
.fse-root { display: inline-flex; }
/* the app bar's Vuetify icon buttons: round, frameless, accent ink */
.fse-launch.fp-icon { width: 36px; height: 36px; padding: 0; justify-content: center;
  border: none; border-radius: 50%; background: transparent; color: var(--fp-accent); }
.fse-launch.fp-icon:hover { background: var(--fp-accent-soft); }
.fse-launch-ico { width: 22px; height: 22px; }
.fse-title-ico { width: 19px; height: 19px; color: var(--fp-accent); }

.fse { width: 560px; display: flex; flex-direction: column; }
.fse-sec { display: flex; flex-direction: column; gap: 8px; padding: 10px 12px; }
.fse-h { margin: 0; font: 600 12px/1.4 var(--fp-font); letter-spacing: 0.03em;
  text-transform: uppercase; color: var(--fp-ink-soft); }
.fse-rule { border-top: 1px solid var(--fp-line); }
.fse-row { display: flex; gap: 8px; align-items: center; }
.fse-note { flex: 1 1 auto; }
.fse-hidden { display: none; }

.fse-drop { display: flex; flex-direction: column; align-items: center; gap: 8px;
  padding: 14px; border: 2px dashed var(--fp-field-line); border-radius: 6px; text-align: center; }
.fse-drop-on { border-color: var(--fp-accent); background: var(--fp-accent-soft); }

.fse-facts { display: grid; grid-template-columns: max-content 1fr; gap: 2px 12px; margin: 0; }
.fse-facts dt { color: var(--fp-ink-soft); }
.fse-facts dd { margin: 0; min-width: 0; overflow-wrap: anywhere; }
.fse-pre { white-space: pre-wrap; }
.fse-sub { font-weight: 600; color: var(--fp-ink-soft); margin-top: 4px; }
.fse-files { width: 100%; }
.fse-fname { max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fse-why { color: var(--fp-ink-mute); font-size: var(--fp-size-small); }
.fse-space { max-width: 420px; }
.fse-slot { min-height: 0; }

.fse-report { max-height: 40vh; overflow: auto; display: flex; flex-direction: column; gap: 8px;
  border: 1px solid var(--fp-line-soft); border-radius: 4px; padding: 6px 8px; }
.fse-rhead { font-weight: 600; }
.fse-rgroup ul { margin: 2px 0 0; padding-left: 18px; }
.fse-r-error .fse-rhead { color: var(--fp-error-ink); }
.fse-r-warn .fse-rhead { color: var(--fp-warn-ink); }
.fse-r-ok .fse-rhead { color: var(--fp-accent); }
</style>

<style scoped>
/* Above the Import door, should both be open: both scrims carry the shared
   z-index 2400 (_shared/panel.css), and the later in <body> would win by
   chance; the session dialog, with its Resume offer, is the one to read. */
.fse-scrim { z-index: 2410; }
/* where each part sits in the dialog: the autosave FIRST on an empty session */
.fse-o-head { order: -3; }
.fse-o-first { order: -1; }
.fse-o-last { order: 2; }
.fse-o-foot { order: 4; }
.fse-auto-rule { margin: 0 -12px; }
.fse-offer { font-weight: 600; }
.fse-quiet { font-size: var(--fp-size-small); }
</style>

<style>
/* The lost-connection notice: plain DOM on <body> (it outlives the widget,
   see `lostNotice`), so an unscoped rule. Non-modal, bottom left. */
.fse-lost { position: fixed; left: 16px; bottom: 16px; z-index: 2500; max-width: 480px;
  display: flex; align-items: center; gap: 8px; padding: 8px 10px;
  background: var(--fp-warn-bg); color: var(--fp-warn-ink); border-radius: 4px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.25); font-family: var(--fp-font); font-size: var(--fp-size); }
</style>
