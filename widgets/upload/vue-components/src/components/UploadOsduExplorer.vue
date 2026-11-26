<template>
  <div class="uox" data-fp-osdu-explorer>
    <!-- the search box, the match count and the scan button on one line -->
    <div class="uox-tools">
      <input class="uox-inp uox-filter" v-model.trim="filter" type="text" data-fp-osdu-search
             placeholder="Search: a well, a property, a horizon, an EPSG code, a type… (epsg:23031, type:ijkgrid, since:2026-06)"
             spellcheck="false"
             title="Looks everything the server holds up — dataspace names, wells, properties, horizons, EPSG codes, types (type:ijkgrid, epsg:23031, since:2026-06); Enter searches at once"
             @keydown.enter.prevent="findNow" />
      <span class="uox-count" :title="countTitle" data-fp-osdu-count>{{ countText }}</span>
      <fp-btn tiny class="uox-scan" data-fp-osdu-scan :label="scanLabel" :title="scanTitle"
              :disabled="scanDisabled" @click="$emit('scan')" />
    </div>

    <!-- the progress of the inventory scan -->
    <fp-progress v-if="ex.status === 'scanning'" data-fp-osdu-progress
                 :label="'Inventory: ' + ex.scanned + ' / ' + ex.total" :value="progressPct" />

    <div class="uox-wrap">
      <table class="uox-table">
        <thead>
          <tr>
            <th v-for="c in columns" :key="c.key"
                :class="{ num: c.num, 'uox-sorted': isOrderedBy(c.key), 'uox-nosort': searchActive }"
                tabindex="0" :aria-sort="sortKey === c.key && !searchActive ? (sortDir > 0 ? 'ascending' : 'descending') : 'none'"
                :title="headerTitle(c)"
                @click="sortBy(c.key)" @keydown.enter.prevent="sortBy(c.key)"
                >{{ c.label }}<span class="uox-arrow" v-if="sortKey === c.key && !searchActive">{{ sortDir > 0 ? "▲" : "▼" }}</span
                ><span class="uox-ranked" v-if="c.key === 'why' && serverMode" title="The rows keep the server's ranking, best match first">ranked</span></th>
            <th class="uox-act"></th>
          </tr>
        </thead>
        <tbody>
          <template v-for="r in shown" :key="r.uri">
          <tr data-fp-osdu-row :data-path="r.path" :data-fp-osdu-scan-state="r.scan || null"
              :class="{ 'uox-row-locked': r.locked || r.read_only, 'uox-loaded': r.loaded }">
            <td class="uox-path" :title="pathTitle(r)">
              <div class="uox-path-in">
                <span v-if="r.scan === 'done'" class="uox-scan-dot" data-fp-osdu-scanned
                      title="Inventory read"></span>
                <span v-if="r.loaded" class="uox-loaded-mark" data-fp-osdu-loaded>✓</span>
                <span class="uox-path-name">{{ r.path }}</span>
                <span v-if="r.published" class="uox-pub" data-fp-osdu-published
                      title="Published: the OSDU catalog knows this dataspace for these words">published</span>
              </div>
            </td>
            <td v-if="searchActive" class="uox-why" :title="whyTitle(r)">{{ whyText(r) }}</td>
            <td class="uox-date" :title="r.last_write || 'Last write unknown'">{{ shortDate(r.last_write) }}</td>
            <td class="num" :title="r.size === null || r.size === undefined ? 'Size unknown' : r.size + ' bytes'">{{ human(r.size) }}</td>
            <td class="uox-lock" :title="lockTitle(r)">{{ lockMark(r) }}</td>
            <!-- while the scan has not read this row, one cell spans the fact
                 columns (Grids to EPSG): an empty bar, which then fills; the
                 columns the list already knows stay visible -->
            <td v-if="scanMark(r)" class="uox-scan-cell" :colspan="FACT_SPAN" :title="rowScanTitle(r)">
              <fp-progress data-fp-osdu-scan-bar :value="scanMark(r) === 'line' ? 0 : 100 * scanProgress(r)" />
            </td>
            <template v-else>
            <td class="num" :title="factTitle(r)">{{ fact(r, "grids") }}</td>
            <td class="num" :title="factTitle(r)">{{ fact(r, "wells") }}</td>
            <!-- the Props count is a button: clicked, the plugin reads the
                 property KINDS of the dataspace over ETP, without loading it -->
            <td class="num uox-props" :title="propsTitle(r)">
              <span v-if="canKinds(r)" @click.stop>
                <fp-btn tiny class="uox-kinds-btn" data-fp-osdu-kinds
                        :data-fp-osdu-kinds-state="kindsState(r)" :label="propsText(r)"
                        :title="propsTitle(r)"
                        :disabled="busy || kindsState(r) === 'reading'" @click="kinds(r)" />
              </span>
              <template v-else>{{ fact(r, "properties") }}</template>
            </td>
            <td class="num" :title="factTitle(r)">{{ fact(r, "surfaces") }}</td>
            <td class="uox-epsg" :title="factTitle(r)">{{ epsg(r) }}</td>
            </template>
            <td class="uox-act">
              <!-- a clicked Load becomes a progress bar until the dataspace
                   is in the tree — indeterminate: the plugin reads a
                   dataspace in ONE call, nothing says how far it is — and a
                   dataspace read in this session wears a green Loaded, which
                   reads it again when clicked (the bar keeps the column's
                   width, so the rows do not shift) -->
              <!-- a dataspace read before on this server: the bar fills at
                   the pace of that read; a first read: the bar runs -->
              <fp-progress v-if="isLoading(r)" class="uox-loading" data-fp-osdu-loading data-fp-osdu-load-elapsed
                           :data-fp-osdu-load-fill="expectedSeconds(r) ? '' : null"
                           :aria-label="'Loading ' + r.path" :title="loadingTitle(r)" :label="loadingText(r)"
                           :value="expectedSeconds(r) ? loadFillPercent(r) : null" />
              <fp-btn v-else-if="r.loaded" tiny variant="on" class="uox-loaded-btn" data-fp-osdu-load label="Loaded"
                      :title="loadTitle(r)" :disabled="busy" @click="load(r)" />
              <fp-btn v-else tiny variant="primary" data-fp-osdu-load label="Load"
                      :title="loadTitle(r)" :disabled="busy" @click="load(r)" />
            </td>
          </tr>
          <!-- the property kinds the plugin read, on one thin line -->
          <tr v-if="kindsState(r) === 'done'" class="uox-row-kinds" data-fp-osdu-kinds-row :data-path="r.path">
            <td class="uox-kinds" :colspan="columnCount" :title="kindsTitle(r)">{{ kindsText(r) }}</td>
          </tr>
          <!-- the objects the search matched in this dataspace, on one thin line -->
          <tr v-if="r.objects && r.objects.length" class="uox-row-objects" data-fp-osdu-objects :data-path="r.path">
            <td class="uox-objects" :colspan="columnCount" :title="objectsTitle(r)">{{ objectsText(r) }}</td>
          </tr>
          </template>
        </tbody>
      </table>
      <div class="uox-more" v-if="hidden > 0" data-fp-osdu-more>
        … and {{ hidden }} more, narrow the search
      </div>
      <div class="uox-none" v-if="serverMode && !shown.length" data-fp-osdu-none>
        No dataspace matches "{{ filter }}"
      </div>
    </div>

    <!-- the results only the OSDU catalogue knows (a locked, published
         dataspace the ETP server does not list): counted once, under the
         table -->
    <div class="uox-cat-only" v-if="serverMode && catalogueOnly > 0" data-fp-osdu-catalogue-only
         title="The OSDU catalog knows these dataspaces for these words, the ETP server does not list them: no facts, but Load still asks for them">
      Also in the OSDU catalogue: {{ catalogueOnly }} dataspace{{ catalogueOnly === 1 ? "" : "s" }} the server did not list
    </div>

    <div class="uox-msg" v-if="ex.message" data-fp-osdu-message>{{ ex.message }}</div>
  </div>
</template>

<script>
/*
 * The dataspace explorer of the OSDU import: what the server holds, as a
 * table the reader can search, sort and load from. The Python side owns
 * every fact (engine/osdu_explorer, mirrored in the `osdu_explorer`
 * state); this component renders it and sends the requests.
 *   props in   — explorer (the `osdu_explorer` state: status / message /
 *                rest / dataspaces[] / scanned / total / find{}),
 *                busy (a load in flight: the Load buttons wait, the clicked
 *                one shows a running bar until the dataspace is in the tree)
 *   events out — select(uri)         load this dataspace (the ETP URI)
 *                scan()              start or refresh the inventory scan
 *                find({text})        search everything the server holds
 *                kinds({uri, refresh?})  read the property kinds of a
 *                                    dataspace (the Props count, clicked):
 *                                    its row's `kinds` goes "reading", then
 *                                    {total, kinds: [{kind, count}], unknown}
 *                                    or {error}; shown on a thin line under
 *                                    the row and in the Props cell's tooltip
 *
 * ONE SEARCH BOX for the server's inventory and the OSDU catalogue alike:
 * the Python side queries the catalogue behind it and merges the answer
 * into `find`. Two boxes would read as two different searches, and the
 * reader would not know which one to type in.
 *
 * THE SEARCH BOX works like a search engine over everything the server
 * has inventoried, not only the dataspace names: a well ("15/9-F-1"), a
 * property ("PORO"), a horizon ("Hugin"), an EPSG code, a type
 * ("ijkgrid", "wells"), a date filter ("since:YYYY-MM"). Every change of
 * the text is sent as find({text}), debounced by FIND_DEBOUNCE_MS (at
 * once on Enter; an empty text too, which clears the search). The server
 * ranks: `find` comes back as {text, status, total, results: [{uri, path,
 * score, why[], objects[]}]}, best first. Until its answer for the typed
 * text has arrived (the debounce, the round trip, a "searching" status)
 * the rows are filtered HERE, by name and project, so typing feels
 * instant; then the server's results take over, in its order, each joined
 * by uri to its listed row (dates, facts, the loaded mark), with WHY it
 * matches in a Match column and the objects it matched on a thin line
 * under it. A Python side that never answers leaves the local filter in
 * place.
 *
 * THOUSANDS OF ROWS. A tenant may list a few thousand dataspaces: the
 * local filter is a computed over a normalised key built once per state
 * update, and only the first `CAP` rows of the match are put in the DOM;
 * the line under the table says how many more there are and asks for a
 * narrower word. The table scrolls inside the dialog (max-height), the
 * header stays.
 *
 * SORT. A click on a header sorts by it, a second click reverses; a value
 * the server has not given yet (facts before the scan, a size without the
 * facade) sorts last either way. The default is the last write, newest
 * first: the most recently written dataspace is the likeliest target.
 * While a search is active the headers do not sort: the results keep the
 * server's ranking, and the Match header says "ranked" where the arrow
 * would be.
 *
 * ACCENTS. The local filter folds case and accents on both sides (NFD,
 * marks dropped): "reservoir" finds "Réservoir".
 *
 * THE CATALOGUE, merged. Once the OSDU catalogue has answered the text
 * (the Python side asks it for three letters or more, when the server has
 * the REST facade), it completes `find.results`: a result the catalogue
 * also knows carries `published: true` (its `why` ends with "published:
 * N components") and shows a small muted "published" badge after its
 * name; a dataspace ONLY the catalogue knows (a locked one the ETP server
 * does not list) comes as a result whose uri no listed row has. It is
 * shown from its `path`, with empty fact cells, and Load works all the
 * same; a muted line under the table counts these. A result is joined to
 * its row by uri, else by path (the catalogue spells the uri itself).
 *
 * THE SCAN, ROW BY ROW. With the REST facade each row carries `scan`
 * ("pending" | "scanning" | "done" | "error") and `progress` (0..1: 0.15
 * as the row starts, 0.6 once its facts are in, 1 at the end). Over the
 * FACT columns only (Grids to EPSG, one cell spanning them) a pending row
 * without facts shows a thin blue line, a scanning row a bar whose fill
 * grows with `progress` and turns from the F2I blue to the logo green
 * (facts that arrive early wait for "done"). Modified, Size, Lock and
 * Match stay visible: the list knows them before any scan, and Modified
 * is the default sort. A done row shows its facts and a small green dot
 * before its name; an error row shows ⚠. A row without `scan` (no facade)
 * shows its facts plainly. The row states its scan state in
 * `data-fp-osdu-scan-state`.
 */
import FpBtn from "../../../../_shared/components/FpBtn.vue";
import FpProgress from "../../../../_shared/components/FpProgress.vue";
import { fmtBytes } from "../../../../_shared/numfmt.js";

// rows put in the DOM at most: past this the reader narrows the word
const CAP = 200;
// the pause after the last keystroke before the text goes to the server
const FIND_DEBOUNCE_MS = 250;
// matched objects listed under a result row at most
const OBJECTS_MAX = 5;
// the kinds a row's thin line names before "+N more"
const KINDS_MAX = 8;

const COLUMNS = [
  { key: "path", label: "Dataspace", title: "the dataspace path", asc: true },
  { key: "last_write", label: "Modified", title: "the last write", asc: false },
  { key: "size", label: "Size", title: "the size", num: true, asc: false },
  { key: "lock", label: "Lock", title: "locked or read-only first", asc: false },
  { key: "grids", label: "Grids", title: "the number of grids", num: true, asc: false },
  { key: "wells", label: "Wells", title: "the number of wells", num: true, asc: false },
  { key: "properties", label: "Props", title: "the number of properties", num: true, asc: false },
  { key: "surfaces", label: "Surfaces", title: "the number of surfaces", num: true, asc: false },
  { key: "epsg", label: "EPSG", title: "the EPSG code", asc: true },
];
// the column that only exists while a search is active: why a row matches
const WHY_COLUMN = { key: "why", label: "Match", title: "why the dataspace matches" };
const FACT_KEYS = new Set(["grids", "wells", "properties", "surfaces"]);
// the columns the scan fills, spanned by the line or the bar until it has
const FACT_SPAN = COLUMNS.filter((c) => FACT_KEYS.has(c.key) || c.key === "epsg").length;
// how long a clicked Load spins while the server has not yet said it is busy
const LOAD_START_MS = 10000;

// the text lower-cased with its accents dropped (NFD, combining marks
// removed): the key the local filter compares
function fold(s) {
  return String(s === null || s === undefined ? "" : s)
    .normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
}

export default {
  name: "UploadOsduExplorer",
  components: { FpBtn, FpProgress },
  props: {
    explorer: { type: Object, default: () => ({}) },
    busy: { type: Boolean, default: false },
  },
  emits: ["select", "scan", "find", "kinds"],
  data() {
    // the dialog is rebuilt on every open: the box starts from the text the
    // server last searched for, so a search survives a close and a reopen
    const f = (this.explorer || {}).find || {};
    return {
      filter: typeof f.text === "string" ? f.text.trim() : "",
      sortKey: "last_write", sortDir: -1, findTimer: null,
      // the dataspace whose Load was clicked, spinning until the load ends
      loadingUri: null, loadTimer: null,
      // the seconds since that click, counted HERE: the server does not
      // answer while the plugin reads a dataspace (one blocking call, up to
      // a minute on a hosted store), so a count it would push stops with
      // it — this one keeps going, and says the page is alive. The PO's
      // manager, 13/10: "on ne sait pas si ça a planté ou pas".
      loadSeconds: 0, loadTick: null,
      FACT_SPAN,
    };
  },
  computed: {
    // the state with every field present, whatever the server sent
    ex() {
      const e = this.explorer || {};
      return {
        status: e.status || "idle",
        message: e.message || "",
        rest: !!e.rest,
        dataspaces: Array.isArray(e.dataspaces) ? e.dataspaces : [],
        scanned: Number(e.scanned) || 0,
        total: Number(e.total) || 0,
      };
    },
    // the server's answer to the search box
    find() {
      const f = (this.explorer || {}).find || {};
      return {
        text: typeof f.text === "string" ? f.text : "",
        status: f.status || "idle",
        total: Number(f.total) || 0,
        results: Array.isArray(f.results) ? f.results.filter((r) => r && r.uri) : [],
      };
    },
    // something is typed in the search box
    searchActive() {
      return this.filter.length > 0;
    },
    // the server has answered THIS text: its ranked results are what is shown
    serverMode() {
      return this.searchActive && this.find.status === "done"
        && fold(this.find.text).trim() === fold(this.filter);
    },
    // typed, but the server's answer is not here yet: the local filter holds
    pending() {
      return this.searchActive && !this.serverMode;
    },
    columns() {
      return this.searchActive ? [COLUMNS[0], WHY_COLUMN, ...COLUMNS.slice(1)] : COLUMNS;
    },
    // the columns plus the Load one: what the objects line spans
    columnCount() {
      return this.columns.length + 1;
    },
    // each row with its folded search key, built once per state update
    rows() {
      return this.ex.dataspaces
        .filter((r) => r && r.uri)
        .map((r) => ({ r, key: fold(r.path) + " " + fold(r.project) + " " + fold(r.name) }));
    },
    byUri() {
      const m = new Map();
      for (const x of this.rows) m.set(x.r.uri, x.r);
      return m;
    },
    byPath() {
      const m = new Map();
      for (const x of this.rows) if (x.r.path) m.set(x.r.path, x.r);
      return m;
    },
    words() {
      return fold(this.filter).split(/\s+/).filter(Boolean);
    },
    matched() {
      const words = this.words;
      if (!words.length) return this.rows;
      return this.rows.filter((x) => words.every((w) => x.key.includes(w)));
    },
    sorted() {
      const key = this.sortKey;
      const dir = this.sortDir;
      const keyed = this.matched.map((x) => ({ r: x.r, v: this.sortValue(x.r, key) }));
      keyed.sort((a, b) => {
        const an = a.v === null;
        const bn = b.v === null;
        if (an || bn) return an === bn ? 0 : an ? 1 : -1;   // unknown last, either way
        if (a.v < b.v) return -dir;
        if (a.v > b.v) return dir;
        return 0;
      });
      return keyed.map((x) => x.r);
    },
    // the server's results in its order, each joined to its listed row by
    // uri, else by path (a result the list does not hold — a published,
    // locked one only the catalogue knows — is shown from what the result
    // says: its path, no facts, its uri for Load)
    ranked() {
      const seen = new Set();
      const out = [];
      for (const res of this.find.results) {
        const row = this.byUri.get(res.uri) || (res.path ? this.byPath.get(res.path) : undefined);
        const base = row || { uri: res.uri, path: res.path || res.uri };
        if (seen.has(base.uri)) continue;
        seen.add(base.uri);
        out.push({
          ...base,
          listed: !!row,
          published: res.published === true,
          score: typeof res.score === "number" ? res.score : null,
          why: Array.isArray(res.why) ? res.why.filter(Boolean).map(String) : [],
          objects: Array.isArray(res.objects) ? res.objects.filter(Boolean) : [],
        });
      }
      return out;
    },
    // the results only the catalogue knows: no listed row holds them
    catalogueOnly() {
      return this.ranked.filter((r) => !r.listed).length;
    },
    ordered() {
      return this.serverMode ? this.ranked : this.sorted;
    },
    shown() {
      return this.ordered.slice(0, CAP);
    },
    hidden() {
      return Math.max(0, this.ordered.length - this.shown.length);
    },
    anyFacts() {
      return this.ex.dataspaces.some((r) => r && r.facts);
    },
    countText() {
      const n = this.rows.length;
      if (this.pending) return "Searching…";
      if (this.serverMode) {
        // every result, the catalogue-only ones included, so the total may
        // exceed the listed rows: "N of M match" only while N <= M
        const t = this.find.total || this.ranked.length;
        return t > n ? `${t} match` : `${t} of ${n} match`;
      }
      return `${n} dataspace${n === 1 ? "" : "s"}`;
    },
    countTitle() {
      if (this.pending) return "The search is on its way to the server; meanwhile the names are filtered here";
      if (this.serverMode) return "The dataspaces found for these words (the OSDU catalog's included), best match first";
      return "The dataspaces this server lists";
    },
    progressPct() {
      return this.ex.total ? Math.round((100 * this.ex.scanned) / this.ex.total) : 0;
    },
    scanLabel() {
      if (this.ex.status === "scanning") return "Scanning…";
      // without the facade there is nothing to refresh, whatever the status
      if (!this.ex.rest) return "Scan facts";
      return this.anyFacts || this.ex.status === "done" ? "Refresh" : "Scan facts";
    },
    scanDisabled() {
      return !this.ex.rest || this.ex.status === "scanning";
    },
    scanTitle() {
      if (this.ex.status === "scanning") return "The inventory is being read, one dataspace after the other";
      if (!this.ex.rest) return "This server has no REST facade beside its ETP endpoint: names only, no facts";
      return this.anyFacts
        ? "Read the inventory of every dataspace again (grids, wells, properties, surfaces, EPSG, object names)"
        : "Read the inventory of every dataspace (grids, wells, properties, surfaces, EPSG, object names)";
    },
  },
  watch: {
    // every change of the text goes to the server, after a pause; the
    // empty text too, it clears the search there
    filter() {
      this.clearFindTimer();
      this.findTimer = setTimeout(() => {
        this.findTimer = null;
        this.emitFind();
      }, FIND_DEBOUNCE_MS);
    },
    // the load has ended, well or not: the circle turns back into its button
    busy(now) {
      if (now) return;
      this.loadingUri = null;
      this.clearLoadTimer();
      this.stopLoadClock();
    },
  },
  beforeUnmount() {
    this.clearFindTimer();
    this.clearLoadTimer();
    this.stopLoadClock();
  },
  methods: {
    clearFindTimer() {
      if (this.findTimer !== null) {
        clearTimeout(this.findTimer);
        this.findTimer = null;
      }
    },
    emitFind() {
      this.$emit("find", { text: this.filter });
    },
    clearLoadTimer() {
      if (this.loadTimer !== null) {
        clearTimeout(this.loadTimer);
        this.loadTimer = null;
      }
    },
    // the spinner shows at the click, before the server reports busy; if
    // the server never turns busy (the session is gone), it stops after
    // LOAD_START_MS. A Load asks no confirmation: it reads only the
    // objects' descriptions (the XML); the arrays are read when an object
    // is ticked in the tree, where a large read asks first and proceeds
    // step by step
    load(r) {
      if (this.busy) return;
      this.loadingUri = r.uri;
      this.clearLoadTimer();
      this.loadTimer = setTimeout(() => {
        this.loadTimer = null;
        if (!this.busy) {
          this.loadingUri = null;
          this.stopLoadClock();
        }
      }, LOAD_START_MS);
      this.startLoadClock();
      this.$emit("select", r.uri);
    },
    isLoading(r) {
      return this.loadingUri !== null && this.loadingUri === r.uri;
    },
    // the clock of the load in progress, run by this page alone
    startLoadClock() {
      this.stopLoadClock();
      this.loadSeconds = 0;
      this.loadTick = setInterval(() => { this.loadSeconds += 1; }, 1000);
    },
    stopLoadClock() {
      if (this.loadTick !== null) {
        clearInterval(this.loadTick);
        this.loadTick = null;
      }
      this.loadSeconds = 0;
    },
    // the seconds the last read of this dataspace took on this server, as
    // the server remembers them (`load_seconds` on the row); 0 when unknown
    expectedSeconds(r) {
      const s = Number(r.load_seconds);
      return Number.isFinite(s) && s > 0 ? Math.round(s) : 0;
    },
    // the bar's fill, at the pace of the last read: it reaches the end at
    // that time and waits there, full, if this read is longer
    loadFillPercent(r) {
      const expected = this.expectedSeconds(r);
      if (!expected) return 0;
      return Math.min(100, Math.round((100 * this.loadSeconds) / expected));
    },
    loadingText(r) {
      const expected = this.expectedSeconds(r);
      const elapsed = this.loadSeconds + " s";
      return expected ? "Loading… " + elapsed + " of ~" + expected + " s" : "Loading… " + elapsed;
    },
    loadingTitle(r) {
      const expected = this.expectedSeconds(r);
      return "Loading " + r.path + this.objectsNote(r) + " into the tree. The page waits for the"
        + " server during the whole read (" + (expected ? "about " + expected + " s last time" : "up to a minute on a hosted store")
        + "): the count here says the page is alive. If the server goes away, the page says so.";
    },
    // ---- the property kinds, read by the plugin over ETP on demand ----
    // A row the server lists can be inventoried (the catalogue-only rows
    // cannot: the server has no such dataspace). `r.kinds` is "reading",
    // {error} or {total, kinds: [{kind, count}], unknown}.
    canKinds(r) {
      return r.listed !== false && !!r.uri;
    },
    kindsState(r) {
      const k = r.kinds;
      if (k === "reading") return "reading";
      if (k && typeof k === "object" && k.error) return "error";
      if (k && typeof k === "object" && Array.isArray(k.kinds)) return "done";
      return "none";
    },
    kinds(r) {
      if (this.busy || this.kindsState(r) === "reading") return;
      // a second click on a row already read asks the store again
      const refresh = this.kindsState(r) === "done" || this.kindsState(r) === "error";
      this.$emit("kinds", refresh ? { uri: r.uri, refresh: true } : { uri: r.uri });
    },
    propsText(r) {
      const state = this.kindsState(r);
      if (state === "reading") return "…";
      if (state === "error") return "⚠";
      const n = this.fact(r, "properties");
      if (n !== "") return n;
      // no facade counted them: the plugin's own count once read, else a word
      return state === "done" ? String(r.kinds.total) : "Kinds";
    },
    propsTitle(r) {
      const state = this.kindsState(r);
      if (state === "reading") return "Reading the property kinds over ETP…";
      if (state === "error") return "The property kinds could not be read: " + r.kinds.error + "\nClick to try again";
      if (state === "done") {
        return this.kindsLines(r).join("\n") + "\nClick to read them again";
      }
      if (!this.canKinds(r)) return this.factTitle(r);
      return this.factTitle(r) + "\nClick to read the property kinds (porosity, permeability…):"
        + " the plugin reads the properties over ETP, a few seconds, nothing is loaded";
    },
    // "porosity 4", "permeability 3", …, then "no kind read 2"
    kindsLines(r) {
      const k = r.kinds || {};
      const lines = (k.kinds || []).map((e) => e.kind + " " + e.count);
      if (k.unknown) lines.push("no kind read " + k.unknown);
      return lines;
    },
    kindsText(r) {
      const lines = this.kindsLines(r);
      const k = r.kinds || {};
      if (!lines.length) return "Kinds: none — " + (k.total || 0) + " properties";
      const shown = lines.slice(0, KINDS_MAX);
      return "Kinds: " + shown.join(" · ") + (lines.length > KINDS_MAX ? " · +" + (lines.length - KINDS_MAX) + " more" : "");
    },
    kindsTitle(r) {
      const k = r.kinds || {};
      return "The kinds of the " + (k.total || 0) + " properties, as the plugin read them over ETP\n" + this.kindsLines(r).join("\n");
    },
    objectCount(r) {
      const f = r.facts;
      return f && !f.error && typeof f.objects === "number" ? f.objects : null;
    },
    // " (1 234 objects)" when the scan counted them
    objectsNote(r) {
      const n = this.objectCount(r);
      return n === null ? "" : " (" + n.toLocaleString("en-US").replace(/,/g, " ") + " objects)";
    },
    // Enter: no waiting for the pause
    findNow() {
      this.clearFindTimer();
      this.emitFind();
    },
    sortBy(key) {
      // a search keeps the server's ranking: the headers do not sort
      if (this.searchActive || key === WHY_COLUMN.key) return;
      if (this.sortKey === key) {
        this.sortDir = -this.sortDir;
        return;
      }
      const col = COLUMNS.find((c) => c.key === key) || {};
      this.sortKey = key;
      this.sortDir = col.asc ? 1 : -1;
    },
    // the column the rows are ordered by: the server's ranking (the Match
    // column) during a search, the sort key otherwise
    isOrderedBy(key) {
      if (this.serverMode) return key === WHY_COLUMN.key;
      return !this.searchActive && this.sortKey === key;
    },
    headerTitle(c) {
      if (this.serverMode && c.key === WHY_COLUMN.key) return "Why each dataspace matches; the rows keep the server's ranking";
      if (this.searchActive) return "Sorting is off while a search is active: the results keep the server's ranking";
      return "Sort by " + c.title + (this.sortKey === c.key ? " (click again to reverse)" : "");
    },
    // the value a row sorts by, null when the server has not said
    sortValue(r, key) {
      if (key === "path") return fold(r.path);
      if (key === "last_write") {
        if (!r.last_write) return null;
        const t = Date.parse(r.last_write);
        return Number.isNaN(t) ? String(r.last_write) : t;
      }
      if (key === "size") return typeof r.size === "number" ? r.size : null;
      if (key === "lock") return (r.locked ? 2 : 0) + (r.read_only ? 1 : 0);
      const f = r.facts;
      if (!f || f.error) return null;
      if (FACT_KEYS.has(key)) return typeof f[key] === "number" ? f[key] : null;
      if (key === "epsg") return Array.isArray(f.epsg) && f.epsg.length ? Number(f.epsg[0]) || null : null;
      return null;
    },
    whyText(r) {
      return Array.isArray(r.why) ? r.why.join(" · ") : "";
    },
    whyTitle(r) {
      if (!Array.isArray(r.why) || !r.why.length) {
        return this.serverMode ? "The server gave no reason" : "The reasons come with the server's answer";
      }
      const score = typeof r.score === "number" ? "\nscore " + r.score : "";
      return r.why.join("\n") + score;
    },
    // "ContinuousProperty PORO · WellboreTrajectoryRepresentation 15/9-F-1 …"
    objectsText(r) {
      const objs = Array.isArray(r.objects) ? r.objects : [];
      const parts = objs.slice(0, OBJECTS_MAX)
        .map((o) => [o.type, o.name].filter(Boolean).join(" ")).filter(Boolean);
      return parts.join(" · ") + (objs.length > OBJECTS_MAX ? " …" : "");
    },
    objectsTitle(r) {
      const objs = Array.isArray(r.objects) ? r.objects : [];
      return "The objects the search matched in this dataspace"
        + (objs.length > OBJECTS_MAX ? " (the first " + OBJECTS_MAX + " of " + objs.length + ")" : "");
    },
    shortDate(iso) {
      if (!iso) return "";
      const s = String(iso);
      if (/^\d{4}-\d{2}-\d{2}/.test(s)) return s.slice(0, 10);
      const t = Date.parse(s);
      return Number.isNaN(t) ? s : new Date(t).toISOString().slice(0, 10);
    },
    // decimal units (powers of 1000), as the server writes them: its
    // "514 MB" shows as 514 MB here, not 490.2
    human(n) { return fmtBytes(n); },
    lockMark(r) {
      if (r.locked) return "🔒";
      if (r.read_only) return "ro";
      return "";
    },
    lockTitle(r) {
      if (r.listed === false) return "Lock unknown: the server does not list this dataspace";
      if (r.locked && r.read_only) return "Locked and read-only";
      if (r.locked) return "Locked";
      if (r.read_only) return "Read-only";
      return "Open to writes";
    },
    // what the fact columns of a row show instead of the facts: "line" (the
    // scan has not reached it), "bar" (being read), "" (the facts)
    scanMark(r) {
      if (r.scan === "scanning") return "bar";
      if (r.scan === "pending" && !r.facts) return "line";
      return "";
    },
    scanProgress(r) {
      const p = Number(r.progress);
      return Number.isFinite(p) ? Math.min(1, Math.max(0, p)) : 0;
    },
    rowScanTitle(r) {
      if (this.scanMark(r) === "line") return "Waiting for the inventory scan";
      const pct = Math.round(100 * this.scanProgress(r));
      return (r.facts ? "Facts read, the inventory is being read: " : "The facts are being read: ") + pct + " %";
    },
    fact(r, key) {
      const f = r.facts;
      // a scan that failed before any facts came says so the same way
      if (r.scan === "error" && (!f || !f.error)) return key === "grids" ? "⚠" : "";
      if (!f) return "";
      if (f.error) return key === "grids" ? "⚠" : "";
      const v = f[key];
      return typeof v === "number" ? String(v) : "";
    },
    factTitle(r) {
      const f = r.facts;
      if (r.listed === false) return "No facts: the server does not list this dataspace, the OSDU catalog knows it";
      if (f && f.error) return "The facts could not be read: " + f.error;
      if (r.scan === "error") return "The facts could not be read";
      if (!f) return this.ex.rest ? "Facts not read yet" : "No facts without the REST facade";
      const parts = [];
      if (typeof f.objects === "number") parts.push(f.objects + " objects");
      if (typeof f.horizons === "number") parts.push(f.horizons + " horizons");
      if (typeof f.faults === "number") parts.push(f.faults + " faults");
      return parts.join(", ") || "Facts read";
    },
    epsg(r) {
      const f = r.facts;
      if (!f || f.error || !Array.isArray(f.epsg)) return "";
      return f.epsg.join(", ");
    },
    loadTitle(r) {
      if (this.busy) return "Loading in progress";
      const expected = this.expectedSeconds(r);
      return "Read the dataspace " + r.path + this.objectsNote(r) + " into this session"
        + (expected ? " (about " + expected + " s last time)" : "");
    },
    pathTitle(r) {
      if (r.listed === false) return r.uri + " — known from the OSDU catalog only, the server does not list it";
      return r.loaded ? r.uri + " — read in this session; click to read it again" : r.uri;
    },
  },
};
</script>

<style>
@import "../../../../_shared/tokens.css";
</style>

<style scoped>
.uox { display: flex; flex-direction: column; gap: 6px; font-family: system-ui, sans-serif; font-size: 12px; }
.uox-tools { display: flex; align-items: center; gap: 6px; }
.uox-inp { padding: 5px 6px; border: 1px solid #ccc; border-radius: 4px; font: inherit; font-size: 12px; }
.uox-filter { flex: 1; min-width: 0; }
.uox-count { color: var(--fp-ink-mute); font-size: var(--fp-size-small); white-space: nowrap; }
/* the table scrolls inside the dialog; the header stays put */
.uox-wrap { max-height: 320px; overflow: auto; border: 1px solid var(--fp-line-soft); border-radius: 4px; }
.uox-table { border-collapse: collapse; width: 100%; font-size: var(--fp-size-small); }
.uox-table th { position: sticky; top: 0; z-index: 1; background: #f5f5f5; text-align: left;
  padding: 3px 5px; border-bottom: 1px solid var(--fp-line); color: var(--fp-ink-soft);
  font-weight: 600; white-space: nowrap; cursor: pointer; user-select: none; }
.uox-table th:hover { color: var(--fp-accent); }
.uox-table th.uox-sorted { color: var(--fp-accent); }
/* a search keeps the server's ranking: the headers are not buttons meanwhile */
.uox-table th.uox-nosort { cursor: default; }
.uox-table th.uox-nosort:hover { color: var(--fp-ink-soft); }
.uox-table th.uox-nosort.uox-sorted, .uox-table th.uox-nosort.uox-sorted:hover { color: var(--fp-accent); }
.uox-table th.num, .uox-table td.num { text-align: right; font-variant-numeric: tabular-nums; }
.uox-table td { padding: 2px 5px; border-bottom: 1px solid var(--fp-line-faint); white-space: nowrap; }
.uox-table tbody tr:hover { background: var(--fp-accent-soft); }
/* the table fits its box: the Dataspace column takes the slack (and the
   ellipsis, the full path in its title), every other column its content
   width, the Load button never cut. A horizontal scroll only appears
   below the sum of those content widths plus the path's minimum. */
.uox-path { width: 100%; max-width: 0; min-width: 160px; overflow: hidden; }
/* the name takes the ellipsis, the marks around it never cut */
.uox-path-in { display: flex; align-items: center; gap: 4px; min-width: 0; }
/* a row the scan has read: the logo green, a small dot before the name */
.uox-scan-dot { flex: none; width: 8px; height: 8px; border-radius: 50%; background: #8FC31F; }
/* the fact columns while the scan has not read the row: centred in the
   row, which keeps its height (the other cells set it) */
.uox-table td.uox-scan-cell { vertical-align: middle; padding-top: 0; padding-bottom: 0; }
.uox-path-name { flex: 0 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
/* the dataspace the OSDU catalogue also knows: a small muted badge */
.uox-pub { flex: none; padding: 0 4px; border: 1px solid var(--fp-line); border-radius: 3px;
  color: var(--fp-ink-mute); font-size: var(--fp-size-tiny); font-weight: 400; line-height: 1.4; }
/* why a row matches the search: bounded, the full list in its title */
.uox-why { max-width: 240px; overflow: hidden; text-overflow: ellipsis; color: var(--fp-ink-soft); }
/* the ranking tag where the sort arrow would be */
.uox-ranked { margin-left: 4px; font-size: var(--fp-size-tiny); font-weight: 400; letter-spacing: 0.03em;
  text-transform: uppercase; color: var(--fp-accent); }
/* the matched objects under a result row: one thin muted line, no border
   between it and its row (the two read as one) */
.uox-table tbody tr:has(+ .uox-row-objects) td,
.uox-table tbody tr:has(+ .uox-row-kinds) td { border-bottom: none; }
/* the Props count, a button: the kinds come on a click */
.uox-kinds-btn[data-fp-osdu-kinds-state="error"] { color: var(--fp-error-ink); }
.uox-table td.uox-kinds { padding: 0 5px 3px 22px; color: var(--fp-ink-mute); font-size: var(--fp-size-tiny);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 0; }
.uox-table td.uox-objects { padding: 0 5px 3px 22px; color: var(--fp-ink-mute); font-size: var(--fp-size-tiny);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 0; }
/* a dataspace read in this session: the green of the logo's "i", like the
   "Connected" line of the form */
.uox-loaded .uox-path { color: #8FC31F; font-weight: 600; }
.uox-loaded-mark { flex: none; }
.uox-date, .uox-epsg { color: var(--fp-ink-soft); }
.uox-lock { text-align: center; font-size: var(--fp-size-tiny); color: var(--fp-warn-ink); }
.uox-act { position: relative; text-align: right; padding-right: 5px; white-space: nowrap; width: 1%; }
/* the clicked Load: a bar running across the cell, as wide as the button
   it replaces, with its word; the Loaded button of a dataspace read */
.uox-loading { display: inline-flex; min-width: 78px; height: 20px; vertical-align: middle; }
.uox-loading :deep(.fp-progress-label) { white-space: nowrap; }
.uox-loaded-btn { border-color: #8FC31F; color: #4f7a00; background: #f3f9e6; }
.uox-arrow { font-size: 8px; margin-left: 2px; }
.uox-more, .uox-none { padding: 4px 6px; color: var(--fp-ink-mute); font-size: var(--fp-size-small); }
/* the results only the catalogue knows, counted: one muted line */
.uox-cat-only { color: var(--fp-ink-mute); font-size: var(--fp-size-small); white-space: nowrap;
  overflow: hidden; text-overflow: ellipsis; }
.uox-msg { color: #b26a00; background: #fff7e6; border-radius: 3px; padding: 4px 6px; font-size: 12px; }
</style>
