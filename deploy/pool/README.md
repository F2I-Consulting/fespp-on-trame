# The session pool (trial)

Sessions ready **before** anyone asks, in place of the wslink launcher of
the container: `fespp_pool.py` (what it does is in its docstring) and
`run-pool.sh`, the container's run script with the pool.

Measured on 2026-10-21 (S0 probe, then the trial image): the websocket
opens 0.2 s after the page instead of 4.2 s, the 3D view shows at 1.0 s
instead of 5.7–8 s; a ready session costs 116–123 MB of its own, a
replacement is ready 1.5 s after its fork; five ready sessions ≈ 1 GB
instead of 2.3.

## In the image, chosen at start

Every image carries both launchers: `run.sh` here replaces the container's
`/opt/trame/run.sh` and dispatches on `FESPP_POOL` — `1` starts the pool
(`run-pool.sh`: the launcher's config generated as wslink's script did,
then the template in the background and the HTTP front in the
foreground), anything else the wslink launcher kept as `run-wslink.sh`.
The Dockerfile installs the three files; `deploy/caddy/run.ps1` injects
them into a trial image built from the working tree.

```powershell
# a trial image from the working tree, started with the pool, two sessions waiting
.\deploy\caddy\run.ps1 -Port 8082 -Name fespp_new -Image fespp_on_trame:deploy-<date>-s<n> -Pool -PoolSize 2
# the same image with wslink's launcher
.\deploy\caddy\run.ps1 -NoBuild -Port 8082 -Name fespp_new -Image fespp_on_trame:deploy-<date>-s<n>
```

`FESPP_POOL_SIZE` is how many sessions wait, `FESPP_POOL_MAX_AGE` (seconds,
3600) how long a waiting one lives before a fresh fork replaces it,
`FESPP_SESSION_IDLE` (seconds; wslink's 300 when unset) how long a session
lives with no browser on it — a session created by REST that loads a store
for minutes before a browser attaches needs more (`run.ps1 -SessionIdle N`).
`GET <prefix>/paraview/pool` says `{ready, taken, size}`; `run.ps1 -Pool`
reads it to say when the first session is ready.

## The REST front

The launcher is also the REST front of the sessions, under
`<prefix>/paraview/` (what Apache proxies to it); its OpenAPI document is
at `GET <prefix>/paraview/openapi.json`, and `GET <prefix>/paraview/docs`
reads it in Swagger UI (Try it out included; the page loads Swagger UI
from a CDN, so it needs the internet). The noun is the session document
(`.fespp.json`, every group optional — `app/features/session_api.py`
says the rules), the verb is apply:

| | |
|---|---|
| `POST /sessions` [document] | a ready session handed over, the document applied on it: `{id, sessionURL, secret, page, port, status}` — `page` is the address a browser opens to attach to that session |
| `GET /sessions` | the sessions in use |
| `GET /sessions/{id}` · `DELETE` | one session; closed |
| `POST /sessions/{id}/apply` document | applied on it; the answer is the Session door's status (its report, or the refusal, 400) |
| `GET /sessions/{id}/state` | the session as one document |
| `GET /pool` | `{ready, taken, size}` |
| `GET /openapi.json` · `GET /docs` | the API as OpenAPI 3.0 (the document's schema key by key, examples in the POST blocks, the page's URL door under *Page*); read in Swagger UI |

An `Authorization: Bearer <token>` header on an apply connects the
document's ETP store with that token first (the token never travels in a
document); the dataspaces load and the document applies once connected.
The per-session routes are served by the session's own HTTP server
(`engine/io/session_endpoint`, beside the upload), which Apache also
reaches at `<prefix>/api/<id>/apply` and `/state`.

```powershell
curl.exe -s -X POST -H "Content-Type: application/json" --data "@doc.json" http://127.0.0.1:8082/fespp/paraview/sessions
curl.exe -s http://127.0.0.1:8082/fespp/paraview/sessions/<id>/state
```

### Sources and Objects

Beside the document, two resources for a host that speaks of objects by
uuid (an explorer, a catalogue): no document, short answers that are
final. The rules are `engine/session_objects.py`, the gestures
`app/features/session_api.py` (`session_select`, the views' eyes,
`load_file`), the session's routes `engine/io/session_endpoint`.

| | |
|---|---|
| `GET /sessions/{id}/sources` | `{files: [{name, size_mb, failed}], etp: {url, partition, connected, dataspaces, available} \| null}` |
| `POST /sessions/{id}/sources/files` | `{"path"}` under the open directory, or multipart (an `.epc` and its `.h5`, streamed to the session's `/upload`): the sources |
| `POST /sessions/{id}/sources/etp` | `{"url", "partition", "dataspaces"}`, connected and loaded; the credentials in `Authorization`, Bearer or Basic (401 without, 502 when the store refuses) |
| `GET /sessions/{id}/catalogue` | every object of the data, read or not: `{view, objects: [{uuid, type, title, read, shown}], total, truncated}`; `?type=`, `?q=` (in the title), `?limit=` (500) |
| `GET /sessions/{id}/objects` | `{view, objects: [{uuid, type, title, shown, loaded}], missing, loading}` |
| `POST /sessions/{id}/objects` | `{"uuids", "show": true}` read and shown, added to the scene; `missing`: the uuids not in the data; `?wait=<s>` (110 at most) answers once the reads are over |
| `PUT /sessions/{id}/objects` | the same, the whole of it |
| `DELETE /sessions/{id}/objects/{uuid}` · `DELETE /sessions/{id}/objects` | one object, or all, no longer read nor shown |

The object routes take `?view=<id>` (the first 3D view otherwise); a
session no browser has attached to yet opens its 3D view on the first
show. A title is the object's, not its drawing leaf's (SolidColor): the
topmost tree folder of the same uuid.

```powershell
curl.exe -s -X POST -H "Content-Type: application/json" --data '{\"path\": \"private/drogon.epc\"}' http://127.0.0.1:8082/fespp/paraview/sessions/<id>/sources/files
curl.exe -s -X POST -H "Content-Type: application/json" --data '{\"uuids\": [\"0eb751ef-219b-4e1f-8e4e-06187f16e61a\"]}' http://127.0.0.1:8082/fespp/paraview/sessions/<id>/objects
```

## What to know

- The pool writes `/opt/trame/proxy-mapping.txt` itself, and gives every
  child its session id **at the fork**, before the application starts: the
  application reads that id off the mapping at start, to build the
  `/api/<id>/upload` URL the import door posts to. A session put on the
  map only when handed over would lose its uploads.
- Per-session output: `/deploy/server/logs/launcher/pool-<port>-<pid>.txt`;
  the pool's own lines (`forked`, `ready`, `handed over`, `exited`) are in
  `docker logs`.
- Session ids are random (uuid4), not time-based as wslink's.
- Python warned that the template is multi-threaded at the fork (two
  threads, VTK's); no effect seen in the trial, the warning is silenced
  in the template with that reason.
- Still to do: the REST front (`POST /sessions {document}`, `apply`,
  `state`), which needs the state document as the language (S1).
