# Build and Run

## TL;DR

```bash
# 1. Build the toolchain image (compilers, CMake, a clone of paraview-superbuild;
#    minutes — only needed once). Its name predates 6.1: it holds no ParaView.
docker build -t paraview:6.0.x -f Dockerfile.paraview .

# 2. Build the app image: ParaView (superbuild, hours on a version bump, cached
#    after), FESAPI/FETPAPI/FESPP, the Python app. build.ps1 wraps it and takes
#    a local FESPP source; -Tag builds a candidate next to `local`.
docker build -f Dockerfile -t fespp_on_trame:local .
#   .\build.ps1 <path-to-fespp-sources> [-Tag pv6.1]

# 3. Run it (the container serves on port 80)
docker run -p 8080:80 fespp_on_trame:local          # CPU
docker run --gpus all -p 8080:80 fespp_on_trame:local   # GPU
#   .\run.ps1 8080   (Windows: the host's GPU when reachable; -NoGpu, -Stop)

# 4. Open
#   http://localhost:8080/index.html
```

The two `docker build` steps above are the whole build; `build.ps1` (Windows, run from the repo root) runs step 2, from a local FESPP checkout when given one. Note `build.bash` at the repo root is **not** a host-side wrapper: it's the ParaView superbuild script that the app `Dockerfile` copies into its `pvbuild` stage (`COPY build.bash /work/build.bash`; the toolchain image does not hold it) and runs with **bash** (`RUN bash /work/build.bash`), so you never invoke it directly. It fails on the first error (`set -eo pipefail`) and checks that `pvpython` was installed.

**Rendering is EGL, and says so.** Until 2026-09-24 the script chose "GPU/EGL" or "CPU/OSMesa" from `nvidia-smi` — which never answers inside a `docker build` — but it was run by `sh`, and under dash `nvidia-smi &> /dev/null` means "nvidia-smi in the background, then a bare redirection", which succeeds: the EGL branch was taken by accident, and that is what built the validated image (no Mesa, no LLVM compiled into `/opt/paraview`; X, EGL and OSMesa windows all present in `libvtkRenderingOpenGL2`). Now run by bash, the test would have switched to OSMesa, so the EGL options are written out unconditionally. Software rendering goes through the system Mesa (llvmpipe) behind EGL.

## Linux behind Apache (the public site)

On an Ubuntu or Debian machine with Docker (and, for the GPU, the NVIDIA driver and the NVIDIA Container Toolkit), from a clone of this repository:

```bash
bash build.sh                                          # once: ParaView, FESPP, the app (1-2 h the first time)
bash deploy/linux/run.sh                               # the app on 127.0.0.1:8090/fespp, restarts by itself
sudo bash deploy/apache/setup.sh <domain> <user> [email]   # once: Apache, the password, HTTPS
```

The site is then `https://<domain>/fespp/`. Before `setup.sh`, the domain must point to the machine and its ports 80 and 443 be open; no other web server may hold them.

| What | Command |
|---|---|
| Update after a `git pull` | `bash deploy/linux/run.sh` (rebuilds from Docker's cache: minutes) |
| Back to the previous version | `bash deploy/linux/run.sh --rollback` (each update keeps it, stopped) |
| Is the site up? | `bash deploy/linux/run.sh --status` |
| Stop it | `bash deploy/linux/run.sh --stop` |
| Change a password, add a user | `sudo bash deploy/apache/setup.sh <domain> <user>` again |
| What the app says | `docker logs --tail 100 fespp` |

The container uses the GPU when Docker reaches an NVIDIA one (`--gpu` / `--no-gpu` to force), and falls back to software rendering when the GPU start fails. Apache keeps the WebSocket of each session open (`upgrade=websocket`, one-hour timeout) and accepts uploads of any size (`LimitRequestBody 0`): see `deploy/apache/fespp.conf`.

## The image, stage by stage

The app `Dockerfile` has **six stages** (see the file for the authoritative version). `build.ps1` builds `--target deps` first, tagged `fespp_deps:<tag>`, then the whole image: **a build that fails keeps nothing of its long steps in BuildKit's cache** (measured 2026-09-24 — the 49-minute ParaView compile of a build that then failed on FESPP left no cache record, and the next attempt started it over), while a `--target deps` build that succeeds is kept. The `fespp_deps` image is also where FESPP can be compiled by hand against the ParaView it will ship with, before a full build.

1. **`pvbuild`** (`FROM paraview:6.0.x`, the toolchain) — compiles ParaView (`build.bash`, `PVSB_GIT_TAG=v6.1.1`, 8 parallel jobs so that a running instance of the application sharing the Docker VM keeps its memory, 49 min on the reference machine).
2. **`deps`** — FESAPI and FETPAPI with their own dependencies (system HDF5, not ParaView's).
3. **`builder`** — `build-fespp.sh` (copied here, after the libraries, so editing it does not rebuild them), then **FESPP**: from `fespp-src-local*` when `build.ps1` was given a local source path, else cloned from `F2I-Consulting/fespp` at the **pinned ref `FESPP_GIT_TAG`** (Dockerfile ENV, e.g. `fot-v1.2.0-a5` — a floating `master` would break this branch whenever FESPP moves; each fespp-on-trame release has a matching `fot-*` anchor tag on the FESPP repo). Output: `/work/pvsb-build/install` (ParaView) and `/work/ttl` (FESPP + libs).

   The **pip stack is frozen** the same way (`setup/requirements.txt`): `trame==3.13.2`, `trame-vuetify==3.2.5`, `trame-vtk==2.11.8`, `trame-dockview==1.4.0`, `trame-plotly==3.1.2`, `trame-iframe==1.1.1`, `trame-color-opacity-editor==1.1.0`, `trame-components==2.5.0`, `paraview-trame-components==0.17.0`. An unpinned rebuild once drifted `trame-dockview` to 2.0.0, whose reworked DOM defeats the `overflow: visible` CSS that lets the per-view action chrome poke into the dockview tab row (buttons rendered but clipped invisible); and the previous `ptc @ git main` install carried a stale `__version__` while shipping post-release code, hiding exactly what a rebuild would resolve. Revisit the pins deliberately, one at a time.
4. **`vtkpatch`** (`FROM builder`) — applies `patches/vtk-*.patch` to the ParaView source tree that is already compiled, then `ninja install` in its build tree: only the patched files recompile and the libraries that link them are reinstalled (under a minute), instead of the whole superbuild. Today one patch: VTK 9.6's composite mapper held one texture unit per batched mapper and never gave it back, so a whole Volve wellbore (33 coloured log channels) used 31 of the 32 units and the wellhead labels turned the view's background magenta. A patch that no longer applies **fails the build** (`patch -N`): after a ParaView bump, drop the patches VTK has fixed. Patch files are kept in LF (`.gitattributes`).
5. **`slim`** (`FROM vtkpatch`) — deletes what only a build reads, so the runtime copies less (a deletion in the runtime stage would only mask the files, never shrink the image): ParaView's headers, CMake files and static libraries (`libpython3.12.a` included), Python's own test suite, the build tools the numpy build left in ParaView's site-packages (Cython, pythran, meson, pip, setuptools, wheel, flit), docs and locales; of `/work/ttl` only `install-fespp` is kept — `Fespp.so` finds fesapi, fetpapi and `PropertyKindMapping.xml` next to itself (RUNPATH `$ORIGIN`). Measured on the 6.0.1 image: ≈ 450 MB of ParaView, ≈ 80 MB of `/work/ttl`.
6. **`runtime`** (`FROM kitware/trame:uv-...-ubuntu22.04`) — copies the slimmed ParaView to `/opt/paraview`, FESPP to `/work/ttl/install-fespp`, and the app to `/deploy`. Installs Python deps + the app with `uv pip install -r setup/requirements.txt && uv pip install .`, then regenerates the static client with `entrypoint.sh build www` (and a sanity `test -s /deploy/server/www/index.html` — an empty `www/` causes an Apache `FallbackResource` loop → HTTP 500 with no logs).

Key facts a forker needs:
- **ParaView version is 6.1** (`PVSB_GIT_TAG=v6.1.1`, VTK 9.6.2, Python 3.12, numpy 1.26.4 — the same Python as the trame venv, which `PV_VENV` requires). 6.2.0 was at RC2 (VTK 9.7.0, a development VTK) on 2026-09-24: not a base until released; the bump is `PVSB_GIT_TAG` and a rebuild. Several ParaView APIs changed at 5.13 (e.g. the display `Position` property → `Translation`; see [[Engine — Dispatchers|Engine-Dispatchers]] and [[Glossary]]).
- **What the superbuild leaves out, and adds** (`build.bash`): no MPI (one pvpython per session, never a distributed pvserver; FESPP needs only `VTK::ParallelCore`), no OpenCASCADE, no default ParaView plugin except `ExplicitStructuredGrid` (its crops serve the slicers; no plugin is auto-loaded); `VTK_SMP_IMPLEMENTATION_TYPE=STDThread` as the compiled default (the superbuild picks Sequential unless TBB is on). `PARAVIEW_USE_SERIALIZATION` is ON in superbuild 6.1.1 unconditionally, but it only yields serializers for classes annotated `VTK_MARSHAL…`: VTK's modules have them (`RegisterClasses_vtkRenderingCore`), ParaView's have none (`vtkRemotingViews`, which holds `vtkPVLODActor`, exports no registrar; the header is not annotated in 6.2.0-RC2 either). So `trame-vtklocal` still cannot carry a ParaView view — measured on the 6.1.1 image, 2026-09-24.
- The **FESPP plugin** lands under `/work/ttl/install-fespp/lib/paraview-<major.minor>/plugins/Fespp/Fespp.so`; `build-fespp.sh` finds that directory and links **`/work/ttl/install-fespp/lib/paraview`** to it, the stable path the launcher (`setup/apps.yml`) and the harnesses pass to `--fespp-plugin-path`.
- **No `vtk` wheel in the venv** (2026-09-24): pvpython imports ParaView's own VTK first, the wheel (a second VTK, 565 MB with the matplotlib and fonttools it pulled) was imported by nothing at run time. `test-unit.ps1` installs it, without dependencies, for the three unit tests that build VTK objects from the venv's Python, from a pip cache in `_local\pip-cache`.
- The Python app is installed into the trame image's **uv venv** under `/deploy/server/venv/...`. The source also sits at `/deploy/fespp_on_trame`. ⚠️ **The venv copy shadows `/deploy`** on `PYTHONPATH` — see *Gotchas* below.

## Rebuilding FESPP for this app (the query channel and the ETP session)

The app reads RESQML through FESPP only, and several of its features exist only on a FESPP build that carries them — there is no fallback reader. The plugin's source of truth is the FESPP branch `feature/welllog-enablement` on `F2I-Consulting/fespp` (anchor tags `fot-*`; `FESPP_GIT_TAG` in the `Dockerfile` names the one the image compiles). What that branch adds over FESPP `dev`, and what the app probes for at run time (never a version string — the classes are ClientServer-wrapped only, so the presence of a ServerManager property is the one visible fact):

| Feature | Plugin side | Probe |
|---|---|---|
| **Query channel** — the XML of any object, the uuids of a type, the typed fields of a CRS, a marker frame, a representation (its extent: `extent_xy`, a 2D grid from its lattice, an IJK grid from its top and base interfaces, the rest from their points) or a log channel (`md`, `xyz` in the global CRS, `values`, `uom`, `depth_oriented` — what the velocity model's pre-fill reads, 31/10), the relationships both ways, the enum table | `ObjectXmlKey`/`ObjectXml`, `ObjectUuidsKey`/`ObjectUuids`, `ObjectFieldsKey`/`ObjectFields`, `ObjectRelationsKey`/`ObjectRelations`, `TypeEnumXml` on both readers (`vtkEPCCollector`, `vtkETPSource`; the logic once, in `Mapping/ResqmlDataRepositoryToVtkPartitionedDataSetCollection`) | `repo_query.has_channel` |
| **Dataspace inventory** without loading (the property kinds; a full fetch the load reuses) | `InventoryKey`/`Inventory` on `vtkETPSource` | `repo_query.has_inventory` — also the probe of the three below, from the same build |
| **Reconnection without a crash** — the HDF proxies of the objects already read are rebound to the new session | `connect()` | (same) |
| **Keep-alive** — a Core Ping every `FESPP_ETP_PING_SECONDS` (60; 0 = none) | `startKeepAlive()` | (same) |
| **Read bound** — `ArrayReadTimeout` closes the session past N seconds of one read (`FESPP_ETP_READ_TIMEOUT`) | `vtkETPSource::setArrayReadTimeout` | the property |
| Timed loads — one `[fespp] etp load <ds>: …` line per dataspace load | `addDataspace` | (log) |

The recipe, on Windows, from the app's root: `.\build.ps1 E:\Dev\fespp\work\src` compiles the **local** FESPP checkout into `fespp_on_trame:local` (the sources are copied into `fespp-src-local\`, the Docker build context); without a path the image clones `FESPP_GIT_TAG` from GitHub. Then check the plugin by behaviour or by the `.so` date in the container, never by grepping a comment: in the browser the Attributes card shows fesapi's view of an object (`xsi:type` everywhere, the root without `obj_`), and over ETP the Props count of a dataspace reads its kinds. The design notes, the hard rules and the verification steps of each phase are in `doc/private/fesapi-query-channel.md` (private: it quotes the PO's machine). A fetpapi fix ahead of its release is tried with `docker build --build-arg FETPAPI_GIT_TAG=<sha>` (`fespp/build_scripts/build-fetpapi.sh` accepts a tag or a sha).

## How the app is launched (runtime internals)

The `kitware/trame` runtime does **not** run your Python directly. It runs **Apache** (serving the static client + proxying websockets) plus the **wslink launcher**, which spawns **one `pvpython` process per browser session**:

```
/opt/paraview/bin/pvpython /deploy/fespp_on_trame \
  --host 0.0.0.0 --port <session-port> --server \
  --fespp-plugin-path /work/ttl/.../Fespp/Fespp.so \
  --local-epc-file-path /deploy/data/empty.epc \
  --remote-epc-file-location ${...} --remote-h5-file-location ${...}
```

Consequences:
- The entry point is `fespp_on_trame/__main__.py` → `App` (`@TrameApp`) → `initialize_fespp_engine(...)` → `ui(server)`. See [[Core, IO & Utils|Core-IO-and-Utils]].
- **`stdout`/`stderr` of your code do NOT appear in `docker logs`.** `docker logs` shows only Apache + the launcher banner. Per-session output (your `print()`s, tracebacks) goes to **`/deploy/server/logs/launcher/<session-uuid>.txt`** inside the container. This is the single most important debugging fact — to read app output:
  ```bash
  docker exec <container> bash -c 'tail -f $(ls -t /deploy/server/logs/launcher/*.txt | head -1)'
  ```
- A fresh **page reload starts a new session = a new `pvpython` = a fresh import** of the Python modules. You do *not* need to restart the container to pick up changed Python — see the dev loop below.

### The session pool (trial, 2026-10-21)

`deploy/pool/fespp_pool.py` replaces the wslink launcher with sessions ready **before** anyone asks: a *template* `pvpython` imports ParaView, the FESPP plugin and the application once, then keeps `FESPP_POOL_SIZE` forked children ready (the application started on its own port, waiting for a client), reforked as they are taken or exit; a small HTTP front answers `POST /paraview` exactly as wslink's launcher does (`id`, `sessionURL`, `secret`) but hands a ready session over at once. Measured: the websocket opens 0.2 s after the page instead of 4.2 s, the 3D view shows at 1.0 s instead of 5.7–8 s; a ready session costs 116–123 MB of its own (the ParaView, plugin and Python pages are shared), a replacement is ready 1.5 s after its fork. Every image carries both launchers (the Dockerfile installs `deploy/pool`, `run.ps1` injects it into a trial image): `FESPP_POOL=1` at `docker run` — `run.ps1 -Pool [-PoolSize N]` — picks the pool, otherwise wslink's launcher runs as before; `GET <prefix>/paraview/pool` says what waits. See `deploy/pool/README.md`; the pool writes the Apache mapping itself and gives every child its session id **at the fork** — the application reads that id off `/opt/trame/proxy-mapping.txt` at start to build its `/api/<id>/upload` URL. Per-session logs: `/deploy/server/logs/launcher/pool-<port>-<pid>.txt`; `docker logs` shows the pool's own lines (`forked`, `ready`, `handed over`, `exited`). The original script stays as `/opt/trame/run-wslink.sh`. The launcher is also the **REST front** (`GET <prefix>/paraview/openapi.json`): `POST /sessions [document]` hands a ready session over with the document applied, `POST /sessions/{id}/apply`, `GET /sessions/{id}/state`, `DELETE /sessions/{id}`; the per-session routes are the session's own (`engine/io/session_endpoint`: `/apply`, `/state`, also at `<prefix>/api/<id>/…`). A page that embeds FesTrame drives it the same way by `postMessage` (`widgets/embed`, `FESPP_EMBED_ORIGINS`); `doc/notes-partagees/host-demo.html` is a host page to try it.

## Dev loop (iterating on Python)

The robust way (matches how the project is developed): **edit source, rebuild the image, relaunch.** The Python layer rebuilds fast (the slow ParaView/FESPP stages are cached).

For a faster inner loop **without a full rebuild**, copy the changed file into a running container and reload the browser tab (new session re-imports):

```bash
# copy into BOTH the source tree and the venv copy (the venv shadows /deploy — see Gotchas)
docker cp path/to/file.py <container>:/deploy/fespp_on_trame/.../file.py
docker cp path/to/file.py <container>:/deploy/server/venv/lib/python3.12/site-packages/fespp_on_trame/.../file.py
# drop stale bytecode, then reload the browser tab
docker exec <container> bash -c 'find /deploy -name "file.*.pyc" -delete'
```

> On Windows + Git Bash, prefix `docker` commands with `MSYS_NO_PATHCONV=1` so `/deploy/...` paths aren't mangled into `C:\...`.

## CLI arguments (`__main__.py`)

| Flag | Meaning |
|---|---|
| `--server` | run as a wslink server (set by the launcher) |
| `--host` / `--port` | bind address (set by the launcher) |
| `--fespp-plugin-path` | absolute path to `Fespp.so` (required) |
| `--local-epc-file-path` | EPC opened at boot in *local* mode (the image ships `/deploy/data/empty.epc`) |
| `--remote-epc-file-location` / `--remote-h5-file-location` | base64-encoded URLs; *remote* mode downloads them at boot and calls `controller.load_epc_file(...)` |

Data is otherwise loaded at runtime via the **Import dialog** (URL / local upload / OSDU-ETP) — see [[UI — Drawer & Toolbar|UI-Drawer-Toolbar-Shared]] and `app/io/upload_endpoint.py`.

## Gotchas

- **The venv copy shadows `/deploy`.** `uv pip install .` installs a *copy* of the package into `/deploy/server/venv/.../site-packages/fespp_on_trame`. Depending on `PYTHONPATH` order, that copy — not `/deploy/fespp_on_trame` — is what's imported. When patching a running container, update **both** (or you'll edit a file that isn't the one running). When in doubt, `grep` the venv copy to confirm what's live.
- **`pvpython -c "import paraview.simple"` aborts** in a bare shell on this image (`String token collision vtkDGEdge`, SIGABRT). That's a VTK static-init issue for ad-hoc imports — it does **not** affect the real app (which initializes ParaView properly). Don't use bare `pvpython -c` to sanity-check imports; use `py_compile` locally and read the session logs at runtime.
- **`docker logs` is the wrong place** for app output — see runtime internals above.
- **Empty `www/` → HTTP 500 loop.** If the static client wasn't generated, Apache's `FallbackResource /index.html` recurses. The Dockerfile guards this with an explicit `test -s`.
- **A rebuilt widget bundle keeps its URL** (`/__trame_<pkg>_<version>/…umd.js`), and the base image served `www/` with no `Cache-Control`: the browser applied heuristic freshness on `Last-Modified` and a plain reload revalidates the page only, so a user kept seeing the previous card for hours (2026-09-18). The Dockerfile now inserts `Header set Cache-Control "no-cache"` into the `<Directory /deploy/server/www>` block of BOTH `/etc/apache2/sites-available/001-trame.conf` (the baked config, used without `TRAME_URL_PREFIX`) and `/opt/trame/apache.tpl` (rendered over it by `runtime_patch.sh` when the prefix is set): every request revalidates, the ETag answers 304. A container of an older image needs a hard reload (Ctrl+F5) once.
- **Two pipeline models coexist** (legacy vs per-view); behaviour can differ by which is live. See [[Architecture]] and [[Core — Sources|Core-Sources]].

## Environment knobs (for comparing, both said in the session log)

- `FESPP_VTK_THREADS=0` — keep VTK filters on one thread. The app switches
  `vtkSMPTools` to STDThread at start and prints the backend it ended on.
- `FESPP_LOD_MB=<MB>` — force ParaView's interactive LOD threshold on any
  backend (`0` = always, `102400` = never, trame's own setting). By itself
  the app turns the LOD on above 20 MB of delivered geometry ONLY when the
  render window names a software engine — a drag on a 930 000-cell grid at
  155 ms a frame instead of 621 — and leaves it off on a GPU, where it buys
  nothing anyone sees.
- `FESPP_INTERACTIVE_RATIO=<0.25..1>` and `FESPP_INTERACTIVE_QUALITY=<1..100>`
  — what a drag frame is made of. By itself the app streams drags at full
  resolution and JPEG 90 on a GPU (measured 2026-09-23 on a 930 000-cell
  grid at 1761x1001, seven alternated passes: 11-16 sharp images/s of 58 KB
  against 12-17 blurred ones of 11 KB at trame's quarter-resolution default
  — the blur buys two or three images a second, within the pass-to-pass
  noise) and keeps trame's quarter at quality 60 in software rendering,
  where a rasteriser pays per pixel. A deployment behind a thin link may
  prefer the small frames. A value that is not a number or out of range is
  said and ignored.

- `FESPP_TIMING=1` — the FESPP reader clocks every request on the output
  window: `[fespp] timing: request: collection x ms, copy and close y ms`
  and, from the mapper, `delete / process / attach` with the node and
  partition counts. What found the per-request rebuild of every selected
  well frame (fixed 2026-10-12).

- `FESPP_ETP_CACHE=1` — the disk cache of a dataspace's XML, OFF unless
  set (the files hold the objects' XML in clear on the host: well names,
  CRS origins and EPSG codes, stratigraphic units — the one who runs the
  server decides; `deploy\caddy\run.ps1 -EtpCache` sets it). A file lives
  `FESPP_ETP_CACHE_HOURS` (24) and is removed past that, by the lookup
  that finds it stale or by the trim after a write. When on (2026-10-13),
  a dataspace load keeps what it fetched under
  `FESPP_ETP_CACHE_DIR` (`/tmp/fespp-etp-cache`) as
  `<server url>/<data partition>/<dataspace>.<store stamp>.<lean|full>.fespp`
  (a dataspace name is only unique within a server and a partition), and
  the next load of a dataspace the store has not written since (its
  `storeLastWrite`, checked with one GetDataspaces) reads the file instead
  of the store: the load line says `N data objects (x MB) from the disk
  cache, store stamp S unchanged, in y s`, or `cached to disk in y s` on a
  fetch. The oldest files go once the directory passes
  `FESPP_ETP_CACHE_MB` (2048). `deploy\caddy\run.ps1` mounts the named
  Docker volume `fespp-etp-cache` on that directory, so the cache survives
  a container swap and the public and trial containers share it; a
  container started otherwise keeps it on its own disk. Every session of a
  container reads the same files: the first load of a dataspace pays the
  store, the others read the file (demo/Volve on ADME: 17 s, then 3.4 s).

- `FESPP_ETP_LEAN=0` — load EVERY object's XML of a dataspace, as before
  2026-10-13. By default the lean load leaves the heavy types the tree
  does not need on the store (stratigraphic occurrence interpretations,
  activities and their templates: 17 of the 45.6 MB of ADME's demo/Volve)
  and fetches one when the query channel or a marker frame's fields ask
  for it (`[fespp] etp fetch: …` on the output window; the load line says
  `left on the store: N <type>`). Set it to 0 to compare, or if a panel
  misses an object the lean load kept away.

- `FESPP_ETP_VERBOSE=1` — fetpapi logs every ETP message it sends and
  receives on stdout (headers, byte counts, the body of each request:
  dataset path, subarray starts and counts). What showed that the Volve
  grid read from ADME follows the same exchange as from the local server,
  and comes back zero-filled from the store (2026-10-12). Verbose: a
  dataspace load writes thousands of lines; never set it on a served
  container.

- `FESPP_STEP_LOCAL=1` — read a FILE in steps as a server is read
  (engine/progressive_load; otherwise a file goes in one load): what the
  `step_cost` bench and the stepping tests use. Each step says its cost on
  stderr, `[fespp] load: step of N object(s), M selected: read x s, redraw
  y s`, the redraw being everything already loaded drawn again.

## Tests

Unit tests live under `tests/` and run **without** ParaView (the `element_type` layer and tree helpers are import-safe by design):

```bash
python -m pytest tests/ -q --ignore=tests/unit/test_fespp_tree.py
```

> `tests/unit/test_fespp_tree.py` imports a long-renamed module (`fespp_tree`) and currently fails to collect — a stale test, unrelated to the app. Fixing or deleting it is a good first fork chore.
