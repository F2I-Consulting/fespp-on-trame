<template>
  <div class="uo">
    <div class="uo-form" v-if="!etpConnected">
      <label class="uo-lbl">Server URL
        <input class="uo-inp" v-model.trim="etpUrl" type="text"
               placeholder="wss://host/api/reservoir-ddms-etp/v2" spellcheck="false" />
      </label>
      <label class="uo-lbl">Data partition
        <input class="uo-inp" v-model.trim="etpPartition" type="text"
               placeholder="osdu" spellcheck="false" />
      </label>
      <label class="uo-lbl">Authentication
        <fp-select class="uo-inp" v-model="etpAuth" :options="authOptions"
                   title="How the server checks who you are: a Bearer access token, or a user name and a password (Basic)" />
      </label>
      <!-- masked as a password: the token gives its holder the reader's
           rights for an hour, it must not show on a shared screen (the PO, 28/10) -->
      <label class="uo-lbl" v-if="etpAuth === 'Bearer'">Access token
        <input ref="token" class="uo-inp uo-token" v-model.trim="etpToken" type="password"
               autocomplete="off" placeholder="paste the Bearer token" spellcheck="false" />
      </label>
      <template v-else>
        <label class="uo-lbl">User
          <input ref="user" class="uo-inp" v-model.trim="etpUser" type="text" autocomplete="username"
                 spellcheck="false" />
        </label>
        <label class="uo-lbl">Password
          <input class="uo-inp" v-model="etpPassword" type="password" autocomplete="current-password" />
        </label>
      </template>
      <div class="uo-hint" v-if="hasPrefill && !secretTyped" data-fp-osdu-prefill>
        {{ etpAuth === "Basic"
          ? "The password is never saved in a session file: enter the user and password to connect."
          : "The token is never saved in a session file: enter it to connect." }}
      </div>
      <!-- the browser keeps the server, the partition, the method and the
           user of the last connection; never the token nor the password -->
      <div class="uo-hint" v-else-if="remembered && !secretTyped" data-fp-osdu-remembered>
        {{ etpAuth === "Basic"
          ? "Server, partition and user come from your last connection in this browser: enter the password to connect."
          : "Server and partition come from your last connection in this browser: paste the token to connect." }}
      </div>
      <div class="uo-foot">
        <!-- the button names the step of the connection the server is at;
             a step that lasts says the page is waiting for the server -->
        <fp-btn variant="primary" class="uo-primary" :label="etpConnecting ? connectingLabel : 'Connect'"
                data-fp-osdu-connect
                :title="etpConnecting ? 'Connection in progress: ' + connectingLabel : missing ? `Fill in ${missing} first` : 'Open the ETP session on this server'"
                :disabled="!!missing || etpConnecting"
                @click="connect" />
      </div>
    </div>

    <div class="uo-form" v-else>
      <div class="uo-connected">✓ Connected</div>
      <!-- a reopened session knows its dataspaces: they load by
           themselves, nothing is asked -->
      <div class="uo-hint" v-if="hasPrefill" data-fp-osdu-auto>
        The session's dataspaces load by themselves.
      </div>
      <!-- the explorer, as soon as the server side has mirrored the rows;
           the plain dropdown otherwise (a server side without the explorer,
           or a list not yet mirrored) -->
      <upload-osdu-explorer v-else-if="hasExplorer" :explorer="osduExplorer" :busy="etpConnecting"
                            @select="$emit('etp-select', { dataspace: $event })"
                            @scan="$emit('osdu-scan')"
                            @find="$emit('osdu-find', $event)"
                            @kinds="$emit('osdu-kinds', $event)" />
      <template v-else>
      <label class="uo-lbl">Dataspace
        <fp-select class="uo-inp" v-model="etpDataspace" :options="dataspaceOptions"
                   title="The dataspace to read from the server" />
      </label>
      <div class="uo-warn" v-if="!etpDataspaces.length">
        No dataspace listed by the server.
      </div>
      </template>
      <div class="uo-foot uo-row">
        <fp-btn v-if="!hasPrefill && !hasExplorer" variant="primary" class="uo-primary" :label="etpConnecting ? 'Loading…' : 'Load dataspace'"
                :title="etpConnecting ? 'Loading in progress' : !etpDataspace ? 'Pick a dataspace first' : 'Read the dataspace into this session'"
                :disabled="!etpDataspace || etpConnecting"
                @click="$emit('etp-select', { dataspace: etpDataspace })" />
        <fp-btn class="uo-secondary" label="Disconnect"
                :title="etpConnecting ? 'Wait for the load to end' : 'Close the ETP session'"
                :disabled="etpConnecting" @click="$emit('etp-disconnect')" />
      </div>
    </div>

    <fp-progress class="uo-progress" v-if="etpConnecting || etpStep" />
    <!-- a step after the session is open (the dataspace list) shows here,
         where the form has already given way to "Connected" -->
    <div class="uo-status" v-if="etpStep && !etpConnecting" data-fp-osdu-step>{{ connectingLabel }}</div>
    <div class="uo-status" v-else-if="etpStatus">{{ etpStatus }}</div>
  </div>
</template>

<script>
/*
 * Fine-grained OSDU (ETP 1.2) import widget: credentials for an OSDU RDDMS
 * endpoint. The CONNECTION lives server-side (FESPP's ETP12Store source);
 * this widget only carries the form: events out, server-driven props in.
 *   props in   — etp_connected / etp_connecting / etp_dataspaces / etp_status
 *                / prefill {url, partition} / osdu_explorer {…}
 *   events out — etp-connect({url, partition, auth: "Bearer", token})
 *                  or etp-connect({url, partition, auth: "Basic", user, password})
 *                / etp-select({dataspace}) / etp-disconnect()
 *                / osdu-scan() / osdu-find({text})
 *                (osdu-search({text}) is declared so that a binding naming
 *                it stays valid; the widget never emits it)
 * Basic: the server side turns user + password into the base64 token FESPP
 * sends after "Basic " (fespp_on_trame.engine.etp.credentials). The
 * credentials go out in the event only, never into the shared state.
 *
 * PREFILL. A session file read from OSDU keeps the server URL and the data
 * partition, never the access token nor the password. When `prefill`
 * changes (or is there at mount) the URL and partition fields take its
 * values, the secret fields are emptied and the keyboard focus goes to the
 * one thing asked: the token (Bearer) or the user field (Basic).
 *
 * THE EXPLORER. Once connected, the server side lists the dataspaces in
 * the `osdu_explorer` state (engine/osdu_explorer: rows with their last
 * write, size and lock, then the facts of each as a background scan reads
 * them). While that list is non-empty the dropdown gives way to
 * <upload-osdu-explorer>: a searchable, sortable table with a Load button
 * per row, which emits the SAME etp-select({dataspace: uri}) as the
 * dropdown, so the server side handles both alike. Its one search box
 * queries the server (osdu-find({text}), answered in `osdu_explorer.find`,
 * which the server completes with the OSDU catalogue). An empty list
 * (a server side without the explorer, or a server without the REST
 * facade whose ETP names are not mirrored yet) keeps the dropdown.
 */
import FpBtn from "../../../../_shared/components/FpBtn.vue";
import FpProgress from "../../../../_shared/components/FpProgress.vue";
import FpSelect from "../../../../_shared/components/FpSelect.vue";
import UploadOsduExplorer from "./UploadOsduExplorer.vue";

// THE BROWSER'S MEMORY. The server URL, the data partition, the method and
// the user of the last connection made from this browser are kept in its
// localStorage under this key, so the form comes back filled and only the
// secret is asked (the PO's manager, 13/10: "pour ne pas avoir à le
// recopier/recoller à chaque fois"). The token and the password are NEVER
// written: a short-lived token pasted each time is the whole point. The
// storage can be absent or refused (a private window, blocked site data):
// every access is guarded and the form works without it.
const MEMORY_KEY = "fespp.osdu.connection";
const REMEMBERED_FIELDS = ["url", "partition", "auth", "user"];
// seconds a connection step lasts before the button says the page waits
// for the server (a hosted store opens a session in three to five seconds)
const STEP_WAIT_S = 4;

function readMemory() {
  try {
    const raw = window.localStorage.getItem(MEMORY_KEY);
    if (!raw) return null;
    const m = JSON.parse(raw);
    return m && typeof m === "object" ? m : null;
  } catch (e) {
    return null;
  }
}

function writeMemory(fields) {
  try {
    const kept = {};
    for (const k of REMEMBERED_FIELDS) {
      if (fields[k]) kept[k] = String(fields[k]);
    }
    window.localStorage.setItem(MEMORY_KEY, JSON.stringify(kept));
  } catch (e) {
    // nothing to do: the browser refuses to remember, the form still works
  }
}

export default {
  name: "UploadOsdu",
  props: {
    etpConnected: { type: Boolean, default: false },
    etpConnecting: { type: Boolean, default: false },
    // the step of the connection the server is at ("Requesting new ETP
    // session", "Reading the dataspace list"), "" outside a connection
    etpStep: { type: String, default: "" },
    etpDataspaces: { type: Array, default: () => [] },
    etpStatus: { type: String, default: "" },
    prefill: { type: Object, default: () => ({}) },
    // the `osdu_explorer` state: status / message / rest / dataspaces[] /
    // scanned / total / find{} — see UploadOsduExplorer.vue
    osduExplorer: { type: Object, default: () => ({}) },
  },
  components: { FpBtn, FpProgress, FpSelect, UploadOsduExplorer },
  emits: ["etp-connect", "etp-select", "etp-disconnect", "osdu-scan", "osdu-find", "osdu-search", "osdu-kinds"],
  data() {
    return {
      etpUrl: "", etpPartition: "", etpAuth: "Bearer", etpToken: "",
      etpUser: "", etpPassword: "", etpDataspace: "",
      // the form came back filled from this browser's last connection
      remembered: false,
      // seconds the current connection step has lasted, counted here: past
      // STEP_WAIT_S the label says the page is waiting for the server
      stepSeconds: 0, stepTick: null,
    };
  },
  computed: {
    // the Connect button while the connection runs: the server's step, or
    // "Connecting", with "(waiting for server…)" once the step lasts
    connectingLabel() {
      const step = (this.etpStep || "Connecting").replace(/…$/, "");
      return step + "…" + (this.stepSeconds >= STEP_WAIT_S ? " (waiting for server…)" : "");
    },
    hasPrefill() {
      const p = this.prefill || {};
      return Boolean(p.url || p.partition);
    },
    prefillKey() {
      const p = this.prefill || {};
      return (p.url || "") + "\n" + (p.partition || "");
    },
    // the secret the prefill asks for has been typed
    secretTyped() {
      return this.etpAuth === "Basic" ? !!this.etpPassword : !!this.etpToken;
    },
    hasExplorer() {
      const e = this.osduExplorer || {};
      return Array.isArray(e.dataspaces) && e.dataspaces.length > 0;
    },
    dataspaceOptions() {
      return (this.etpDataspaces || []).map((d) => ({ value: d, label: String(d) }));
    },
    authOptions() {
      return [
        { value: "Bearer", label: "Bearer token" },
        { value: "Basic", label: "Basic (user and password)" },
      ];
    },
    // what still keeps Connect disabled, in words ("" when nothing)
    missing() {
      if (!this.etpUrl) return "the server URL";
      if (this.etpAuth === "Basic") {
        if (!this.etpUser) return "the user";
        if (!this.etpPassword) return "the password";
        return "";
      }
      return this.etpToken ? "" : "the access token";
    },
  },
  watch: {
    etpDataspaces(list) {
      if (list.length && !list.includes(this.etpDataspace)) this.etpDataspace = list[0];
    },
    // on the VALUE, not the object: a state replayed with the same prefill
    // must not empty a token the reader is typing
    prefillKey() {
      this.applyPrefill();
    },
    // a new step, or the start of a connection, restarts the step clock;
    // the end of the connection stops it
    etpStep() {
      this.restartStepClock();
    },
    etpConnecting(now) {
      if (now) this.restartStepClock();
      else if (!this.etpStep) this.stopStepClock();
    },
  },
  mounted() {
    this.applyMemory();
    this.applyPrefill();
  },
  beforeUnmount() {
    this.stopStepClock();
  },
  methods: {
    restartStepClock() {
      this.stopStepClock();
      if (!this.etpConnecting && !this.etpStep) return;
      this.stepTick = setInterval(() => { this.stepSeconds += 1; }, 1000);
    },
    stopStepClock() {
      if (this.stepTick !== null) {
        clearInterval(this.stepTick);
        this.stepTick = null;
      }
      this.stepSeconds = 0;
    },
    connect() {
      const base = { url: this.etpUrl, partition: this.etpPartition, auth: this.etpAuth };
      writeMemory({ ...base, user: this.etpUser });
      this.$emit("etp-connect", this.etpAuth === "Basic"
        ? { ...base, user: this.etpUser, password: this.etpPassword }
        : { ...base, token: this.etpToken });
    },
    // the last connection of this browser into the EMPTY fields (a session
    // file's prefill, applied after, wins on the URL and the partition);
    // the focus goes to the secret, the one thing left to type
    applyMemory() {
      const m = readMemory();
      if (!m) return;
      let used = false;
      if (m.url && !this.etpUrl) { this.etpUrl = m.url; used = true; }
      if (m.partition && !this.etpPartition) { this.etpPartition = m.partition; used = true; }
      if (m.auth === "Basic" || m.auth === "Bearer") this.etpAuth = m.auth;
      if (m.user && !this.etpUser) { this.etpUser = m.user; used = true; }
      this.remembered = used;
      if (used && !this.hasPrefill) {
        this.$nextTick(() => {
          const field = this.etpAuth === "Basic" ? this.$refs.user : this.$refs.token;
          if (field) field.focus();
        });
      }
    },
    // the saved URL and partition in their fields (a field already holding
    // the same value is left alone), the secrets empty and the focus on
    // the first field asked: the token, or the user with Basic
    applyPrefill() {
      if (!this.hasPrefill) return;
      const p = this.prefill;
      if (p.url && this.etpUrl !== p.url) this.etpUrl = String(p.url);
      if (p.partition && this.etpPartition !== p.partition) this.etpPartition = String(p.partition);
      this.etpToken = "";
      this.etpPassword = "";
      this.$nextTick(() => {
        const field = this.etpAuth === "Basic" ? this.$refs.user : this.$refs.token;
        if (field) field.focus();
      });
    },
  },
};
</script>

<style>
@import "../../../../_shared/tokens.css";
</style>

<style scoped>
.uo { display: flex; flex-direction: column; font-family: system-ui, sans-serif; font-size: 13px; }
.uo-form { padding: 8px; display: flex; flex-direction: column; gap: 6px; }
.uo-lbl { display: flex; flex-direction: column; gap: 2px; color: #555; font-size: 12px; }
.uo-inp { padding: 5px 6px; border: 1px solid #ccc; border-radius: 4px;
  font: inherit; font-size: 12px; }
.uo-inp.fp-sel { padding-right: 18px; }
.uo-token { font-family: ui-monospace, monospace; font-size: 11px; }
/* the design tokens' muted note (the ink of fp-sum), at the small size */
.uo-hint { color: var(--fp-ink-mute); font-size: var(--fp-size-small); }
.uo-connected { color: #8FC31F; font-weight: 600; padding: 2px 0; }
.uo-warn { color: #b26a00; background: #fff7e6; border-radius: 3px; padding: 4px 6px;
  margin: 4px 0; font-size: 12px; }
.uo-foot { padding-top: 4px; }
.uo-row { display: flex; gap: 6px; }
.uo-primary { flex: 1; padding: 7px; border: none; border-radius: 4px;
  background: var(--fp-accent); color: #fff; font-weight: 600; cursor: pointer; width: 100%; }
.uo-primary:disabled { background: #b9c6d6; cursor: default; }
.uo-secondary { padding: 7px 10px; border: 1px solid #bbb; border-radius: 4px;
  background: #fff; color: #444; cursor: pointer; }
.uo-status { padding: 4px 8px 8px; color: #555; font-size: 12px; white-space: pre-wrap; }
/* where the wait sits */
.uo-progress { margin: 0 8px 4px; }
</style>
