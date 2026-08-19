# Build and Run

## TL;DR

```bash
# 1. Build the ParaView base image (slow, 1-2 h — only needed once / on PV bump)
docker build -t paraview:6.0.x -f Dockerfile.paraview .

# 2. Build the app image (compiles FESAPI/FETPAPI/FESPP, installs the Python app)
docker build -f Dockerfile -t fespp_on_trame:local .

# 3. Run it
docker run -p 8080:8080 fespp_on_trame:local          # CPU
docker run --gpus all -p 8080:8080 fespp_on_trame:local   # GPU

# 4. Open
#   http://localhost:8080/index.html
```

Run the two `docker build` steps above manually — that is the supported build. Note `build.bash` at the repo root is **not** a host-side wrapper: it's the ParaView superbuild script that `Dockerfile.paraview` copies into the `paraview:6.0.x` image (`COPY build.bash /work/build.bash`) and runs inside the build, so you never invoke it directly.

## The image, stage by stage

The app `Dockerfile` is **two-stage** (see the file for the authoritative version):

1. **`builder`** (`FROM paraview:6.0.x`) — compiles ParaView (`build.bash`, `PVSB_GIT_TAG=v6.0.1`), then FESAPI + its deps, FETPAPI + its deps, and finally **FESPP**: from `fespp-src-local*` when `build.ps1` was given a local source path, else cloned from `F2I-Consulting/fespp` at the **pinned ref `FESPP_GIT_TAG`** (Dockerfile ENV, e.g. `fot-v1.2.0-a5` — a floating `master` would break this branch whenever FESPP moves; each fespp-on-trame release has a matching `fot-*` anchor tag on the FESPP repo). Output: `/work/pvsb-build/install` (ParaView) and `/work/ttl` (FESPP + libs).
2. **`runtime`** (`FROM kitware/trame:uv-...-ubuntu22.04`) — copies ParaView to `/opt/paraview`, FESPP to `/work/ttl`, and the app to `/deploy`. Installs Python deps + the app with `uv pip install -r setup/requirements.txt && uv pip install .`, then regenerates the static client with `entrypoint.sh build www` (and a sanity `test -s /deploy/server/www/index.html` — an empty `www/` causes an Apache `FallbackResource` loop → HTTP 500 with no logs).

Key facts a forker needs:
- **ParaView version is 6.0** (`PVSB_GIT_TAG=v6.0.1`). This matters: several ParaView APIs changed at 5.13 (e.g. the display `Position` property → `Translation`; see [[Engine — Dispatchers|Engine-Dispatchers]] and [[Glossary]]).
- The **FESPP plugin** lands under `/work/ttl/install-fespp/lib/paraview-6.0/plugins/Fespp/Fespp.so` and is passed to the app via `--fespp-plugin-path`.
- The Python app is installed into the trame image's **uv venv** under `/deploy/server/venv/...`. The source also sits at `/deploy/fespp_on_trame`. ⚠️ **The venv copy shadows `/deploy`** on `PYTHONPATH` — see *Gotchas* below.

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
- **Two pipeline models coexist** (legacy vs per-view); behaviour can differ by which is live. See [[Architecture]] and [[Core — Sources|Core-Sources]].

## Tests

Unit tests live under `tests/` and run **without** ParaView (the `element_type` layer and tree helpers are import-safe by design):

```bash
python -m pytest tests/ -q --ignore=tests/unit/test_fespp_tree.py
```

> `tests/unit/test_fespp_tree.py` imports a long-renamed module (`fespp_tree`) and currently fails to collect — a stale test, unrelated to the app. Fixing or deleting it is a good first fork chore.
