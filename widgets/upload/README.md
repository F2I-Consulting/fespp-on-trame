# trame-fespp-upload

**Decoupled** Trame widgets to **import data into the session** — one shell,
two fine-grained widgets (each usable standalone):

- **`<upload-data>` (shell)** — the "Import data" toolbar button + a modal
  dialog with one tab per import source. Owns only the open/close/tab state;
  forwards the fine widgets' props/events verbatim.
- **`<upload-file>`** — drop/pick `.epc` (+ its `.h5`) → POST multipart
  `FormData` to the server's `/upload` endpoint → the server writes them into
  the **session temp dir** and loads each `.epc` (the companion `.h5` lands in
  the same dir, so the EPC reader finds it).
- **`<upload-osdu>`** — credential form for an OSDU RDDMS / ETP 1.2 endpoint
  (server URL `wss://…`, data partition, access token). The connection itself
  is **server-side** (FESPP's `ETP12Store` source): the widget only emits
  events and mirrors server-driven state (connected / connecting / dataspace
  list / status line). Once connected, pick a dataspace and *Load dataspace* —
  the data tree then populates exactly like an EPC load.

The split mirrors the server: the EPC path (upload endpoint + `Collector`) and
the ETP path (`ETPConnector` + selectors on the ETP proxy) are different loads
behind one entry point. Both are **server-side and session-shared** (loaded
data shows in every view).

## Contract

**`upload-file` props**: `upload_url` (POST target, default `/upload`),
`session_id` (if set, POST to `/api/{session_id}/upload`, proxied), `accept`
(input filter, default `.epc,.h5`).
**Events**: `uploaded(names)`, `error(message)`.

**`upload-osdu` props** (all server-driven): `etp_connected`,
`etp_connecting`, `etp_dataspaces`, `etp_status`; and `prefill` (`{}` or
`{url, partition}`, what a session file read from OSDU keeps — never the
token): each new value fills the URL and partition fields, empties the token
field and focuses it, with a muted line saying the token is never saved.
**Events**: `etp_connect({url, partition, auth: "Bearer", token})` or
`etp_connect({url, partition, auth: "Basic", user, password})` (the server
side turns user + password into the base64 token FESPP sends after
"Basic "; the credentials go out in the event only, never into the state),
`etp_select({dataspace})` with the dataspace's ETP uri, `etp_disconnect()`.

**The dataspace explorer** (`upload-osdu`, once connected): the prop
`osdu_explorer` mirrors the state of the same name, filled by
`app/boot.py` from `engine/osdu_explorer.py` — `{status, message, rest,
dataspaces: [{uri, path, project, name, last_write, size, locked,
read_only, scan, progress, facts: null | {objects, grids, wells,
properties, surfaces, horizons, faults, epsg, error}, kinds?: "reading" |
{total, kinds: [{kind, count}], unknown} | {error}}], scanned, total,
find: {text, status, total, results}}`. With a non-empty `dataspaces` the dropdown gives way to a
searchable, sortable table (a "Load" per row emits `etp_select` with the
row's uri) and an inventory scan (`osdu_scan()`; `facts.objects` is the
number of objects inventoried, the progress line reads "Inventory: 12 /
37"). There is ONE search box: the separate "Search the catalogue" box is
gone, the OSDU catalogue is merged into the box's results (below). The
`osdu_search({text})` event and the `search` field of the state it fills
are legacy: still declared and relayed by both elements, harmless, but the
widget no longer emits the event nor reads the field.

**The scan, row by row.** With the REST facade every row carries `scan`
(`"pending"` | `"scanning"` | `"done"` | `"error"`) and `progress` (0..1:
0.15 as the row starts, 0.6 once its facts are in, 1.0 at the end); a
server without the facade sends neither and the rows are drawn as before.
The row says its state in `data-fp-osdu-scan-state`. Only the FACT
columns (Grids to EPSG) are covered, by one cell spanning them
(`.uox-scan-cell`): Modified, Size, Lock and Match stay visible, the list
knows them before any scan and Modified is the default sort.
- `pending` without facts: a thin line in the F2I blue (`--fp-accent`,
  `.uox-scan-line`), vertically centred, the row keeping its height.
- `scanning`: a bar (`.uox-scan-track` / `.uox-scan-fill`) whose fill has
  the width of `progress` and a colour interpolated from the blue #00436D
  to the logo green #8FC31F, both transitioned over 0.6 s (none under
  `prefers-reduced-motion: reduce`); facts already there wait for `done`.
- `done`: the facts, and a green dot (8 px, `.uox-scan-dot`,
  `data-fp-osdu-scanned`) first in the Dataspace cell, before the ✓ of a
  loaded row.
- `error`: the ⚠ in the Grids cell, as a `facts.error` always gave.

**The property kinds (2026-10-10).** The Props count of a listed row is a
button (`.uox-kinds-btn`, `data-fp-osdu-kinds`, its state in
`data-fp-osdu-kinds-state`: `none` / `reading` / `done` / `error`): clicked,
it emits `osdu_kinds({uri})` and the server reads the property KINDS of
that dataspace over ETP without loading it (FESPP's inventory channel,
`repo_query.inventory_lines`). The row's `kinds` goes `"reading"` (the cell
shows "…"), then `{total, kinds: [{kind, count}], unknown}` — the cell's
tooltip lists them and a thin line under the row
(`.uox-row-kinds`, `data-fp-osdu-kinds-row`) reads "Kinds: porosity 4 ·
permeability 3 · …" — or `{error}` (a ⚠ in the cell, the words in the
tooltip). A second click emits `osdu_kinds({uri, refresh: true})` and asks
the store again. Without a REST facade the cell reads "kinds" until read,
then the plugin's own count. The search box then finds a property by its
kind ("porosity" or `kind:porosity`), whatever it is called.

**The search box** (`data-fp-osdu-search`) answers over everything the
server holds — a well ("15/9-F-1"), a property ("PORO"), a horizon
("Hugin"), an EPSG code, a type, and the filters `epsg:23031`,
`type:ijkgrid`, `since:2026-06`; the words `locked` and `readonly`; and `modified` or `new` for the dataspaces the store wrote since this process last listed the server (the application keeps the facts of the unchanged ones from one connection to the next, so they are not scanned again). The widget emits `osdu_find({text})` on
every change of the box, debounced 250 ms (at once on Enter); an empty
text is emitted too and clears the search. The server answers in
`osdu_explorer.find`: `{text: "PORO", status: "idle" | "searching" |
"done", total: 3, results: [{uri, path, score, why: ["property PORO",
"EPSG 23031"], objects: [{type: "ContinuousProperty", name: "PORO"}]}]}` —
`results` already ranked best first, `why` a short list of human reasons,
`objects` at most 5 matched objects per dataspace, `total` the number of
matching dataspaces. While the box is non-empty and the server's `find.text`
is that text with status `done`, the table shows only `find.results`, in
that order, each joined by uri to its listed row, with a "Match" column
(`.uox-why`, the reasons joined by " · ", the full list in its title) after
Dataspace and, under a row with objects, a thin line (`.uox-objects`,
`data-fp-osdu-objects`) naming them; the count line says "3 of 37 match"
and "No dataspace matches "PORO"" (`data-fp-osdu-none`) on zero. Until the
server has answered that text the rows are filtered locally by name and
project and the count line says "Searching…". Sorting is off while a search
is active; the Match header carries "ranked" (`.uox-ranked`) where the
arrow would be.

**The catalogue, merged.** When the server has the REST facade and the
text has three letters or more, the server asks the OSDU catalogue too and
completes `find.results` with its answer (a second `find` update, status
`done` again): a result the catalogue also knows carries `published: true`
(its `why` ends with "published: 75 components") and the row reads a small
muted "published" badge after the dataspace name (`.uox-pub`,
`data-fp-osdu-published`); a dataspace only the catalogue knows (a locked
one the ETP server does not list, its `why` saying "(not listed by the
server)") comes as a result whose uri no listed row has. A result is
joined to its row by uri, else by path; one joined to none is shown from
its `path`, fact, date, size and lock cells empty, and its Load emits
`etp_select` with the result's uri all the same. The count line counts
every result, those included: "12 of 37 match", or "40 match" when the
results outnumber the listed dataspaces ("40 of 37" would not read). A
muted line under the table (`data-fp-osdu-catalogue-only`) says "Also in
the OSDU catalogue: 2 dataspaces the server did not list".

**Load.** The clicked Load turns into a spinning circle
(`data-fp-osdu-loading`, the button hidden underneath so the column keeps
its width) until `busy` falls back — the dataspace is in the tree, or the
load failed; a server that never turns `busy` (the session gone) does not
leave it spinning: it gives up after 10 s. Its title names the object
count the scan found. No question before a Load: it reads the objects'
descriptions only (the XML), the arrays come when an object is ticked.
Sizes read in units of 1000, as the server writes them ("514 MB", not
"490.2 MB").

Hooks for tests: `data-fp-osdu-explorer`,
`data-fp-osdu-search`, `data-fp-osdu-count`, `data-fp-osdu-row`
(`data-path`, `data-fp-osdu-scan-state`), `data-fp-osdu-objects`
(`data-path`), `data-fp-osdu-none`, `data-fp-osdu-load`,
`data-fp-osdu-loading`,
`data-fp-osdu-loaded`, `data-fp-osdu-scanned`, `data-fp-osdu-published`,
`data-fp-osdu-catalogue-only`, `data-fp-osdu-scan`,
`data-fp-osdu-progress`, `data-fp-osdu-more`.

**`upload-data` (shell)**: union of both contracts.

## Server side (host app)

Files: reuse the existing `/upload` aiohttp route (`engine/io/upload_endpoint.py`)
+ the session temp dir (`engine/io/temp_dir.py`). The endpoint already writes
the files and calls `controller.load_epc_file(path)` for each `.epc`.

OSDU: `app/boot.py` binds `etp_connect` / `etp_select` / `etp_disconnect`
controllers over the engine's `ETPConnector` (`engine/sources/etp_connector.py`,
FESPP `ETP12Store` proxy — needs the plugin built **with fetpapi**) and
`engine/etp.py`. `set_dataspace` ends with `controller.update_data_information()`,
so the tree/assembly refresh is the same path as an EPC load. The explorer
(`osdu_scan` / `osdu_find` controllers; `osdu_search`, legacy) is plain HTTP on the Reservoir
DDMS REST facade beside the ETP endpoint (`wss://host/api/reservoir-ddms-etp/v2/`
→ `https://host/api/reservoir-ddms/v2`) and on the OSDU Search, with the
connection's credentials, in threads: a server without the facade (a bare
open-etp-server) shows the names ETP listed, without facts.

## Build

```bash
cd vue-components
npm install
npm run build   # -> trame_fespp_upload/module/serve/{*.umd.js, style.css}
```

Open `demo.html` — picking files / the `.h5` warning work standalone; the actual
upload needs the running app.
