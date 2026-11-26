# Local development with ParaView's pvpython (no Docker)

The whole application runs **locally** on the `pvpython` of a ParaView binary
that carries the FESPP plugin, so boot, import and wiring errors surface at
once, without the Docker round-trip. The browser is still where the 3D is
seen.

The commands below are PowerShell, run from the root of this repository. They
name the ParaView install `$env:PARAVIEW_HOME`, set once per shell:

```powershell
$env:PARAVIEW_HOME = "<paraview-install>"    # the folder that holds bin\pvpython.exe
$pvpy = "$env:PARAVIEW_HOME\bin\pvpython.exe"
```

## The ParaView used

A ParaView Windows binary with Python 3.12 (6.0.1, MPI build), with the FESPP
plugin built against it and copied into its plugin folder:

```
<paraview-install>\
  bin\pvpython.exe                                 # Python 3.12
  bin\paraview-<x.y>\plugins\Fespp\Fespp.dll       # the FESPP plugin
  bin\paraview-<x.y>\plugins\Fespp\Energistics.dll # and its libraries beside it
                                                   # (FesapiCpp-<v>.dll, Fetpapi-<v>.dll, ...)
```

The ExplicitStructuredGrid plugin (the IJK crops) ships with ParaView; the
application finds it under the same install (`engine/plugins.py`).

## One-time environment setup

ParaView's embedded Python is slightly stripped: it lacks `_ssl.pyd`,
`tomllib` and `pip`. They are patched in (all reversible):

1. **`_ssl.pyd`** (compiled; trame's aiohttp / wslink need `ssl`). The OpenSSL
   DLLs (`libssl-3.dll`, `libcrypto-3.dll`) are already shipped, only the
   Python extension is missing. Drop in the `_ssl.pyd` of the python.org
   **embeddable** package that matches ParaView's Python (3.12.7 for ParaView
   6.0.1: `python-3.12.7-embed-amd64.zip`) as `bin\DLLs\_ssl.pyd`.
2. **`tomllib`** (pure Python; pip needs it). Copy `tomllib/` from the same
   package's `python312.zip` to `bin\Lib\tomllib\`.
3. **pip**: `& $pvpy get-pip.py` (works once `ssl` and `tomllib` are present).
4. **The trame stack**, at the versions `setup/requirements.txt` pins for the
   image, but **without `vtk` / `numpy` / `Pillow`**: ParaView provides them,
   and pip's copies would clobber the rendering stack:
   ```powershell
   & $pvpy -m pip install trame==3.13.2 trame-vtk==2.11.8 trame-vuetify==3.2.5 `
       trame-dockview==1.4.0 trame-plotly==3.1.2 trame-iframe==1.1.1 plotly dataclasses_json
   ```
   `trame-vtk` stays at 2.11.8: 2.11.9 imports the monolithic `vtk`, which
   ParaView's VTK does not fully ship. `trame-dockview` stays at 1.x: 2.x
   renames the containers the application's CSS targets.
5. **The colour / opacity editor and the trame components**, `--no-deps` so
   they do not pull another `trame-vtk`:
   ```powershell
   & $pvpy -m pip install --no-deps paraview-trame-components==0.17.0 `
       trame-color-opacity-editor==1.1.0 trame-components==2.5.0
   ```
6. **pyproj**, for the Globe view (projected CRS to latitude / longitude):
   `& $pvpy -m pip install pyproj`. Without it, `engine/geo.py` falls back to a
   built-in UTM inverse. The Earth textures are
   `fespp_on_trame/assets/earth-{2k,4k,8k,16k}.jpg` (NASA Blue Marble, public
   domain); the Globe card picks the level, and `geo.earth_texture_path`
   falls back to the finest one present below the one asked for.

Sanity check:

```powershell
& $pvpy -c "import paraview; from trame.app import get_server; from trame.widgets import paraview as p; import numpy; print('OK', numpy.__version__, hasattr(p, 'VtkRemoteView'))"
```

## Running the application

```powershell
# The repository and each widgets\<x> folder on PYTHONPATH: `pip install -e`
# of the widget packages fails in the embedded pvpython (hatchling's build
# isolation), so the sources are imported where they are. A widget's
# front-end is rebuilt with `npm run build` in widgets\<x>\vue-components.
$repo = $PWD.Path
$env:PYTHONPATH = ($repo + ";" + ((Get-ChildItem "$repo\widgets" -Directory | ForEach-Object { $_.FullName }) -join ";"))
# The BlockScope engine, as in the image (Globe view, one composite
# representation per view). Without it the legacy per-rep pipeline runs,
# silently.
$env:FESPP_BLOCKSCOPE = "1"
$fespp = (Get-Item "$env:PARAVIEW_HOME\bin\paraview-*\plugins\Fespp\Fespp.dll").FullName
& $pvpy -m fespp_on_trame `
    --fespp-plugin-path $fespp `
    --local-epc-file-path "<file>.epc" `
    --server --port 8766 --timeout 0
```

then open <http://localhost:8766>. `--local-epc-file-path` is optional (the
file is read once the server is ready); `--timeout 0` keeps the server up with
no client; drop `--server` to open a browser.

> The `WRN - The configuration file has not been found` line on every
> pvpython start is ParaView's own and harmless.

## Widget changes & browser cache

Each widget bundle is served under a **version-pinned URL**
(`__trame_fespp_<widget>_<version>/...`). After rebuilding a widget (`npm run
build`), a plain refresh may keep serving the OLD JS/CSS from browser cache,
which looks like "my fix didn't work". To pick up changes, do one of:
- keep DevTools open with **Network → Disable cache**, then refresh (best for dev),
- use a private/incognito window, or
- bump the widget's `__version__` (changes the URL → forces a fresh fetch).

## In a container

`.\build.ps1 <fespp-sources>` builds the image `fespp_on_trame:local` and
`.\run.ps1 8080:80` serves it on <http://localhost:8080/>; the header of each
script lists its options, and `doc/wiki/Build-and-Run.md` describes the image.

## Local HDF5 pitfall: no gzip filter

fesapi links HDF5 statically. An HDF5 built without zlib
(`H5Zfilter_avail(H5Z_FILTER_DEFLATE) == 0`) opens a gzip-compressed dataset
but cannot read it (`H5Dopen` succeeds, `H5Dread` fails): every EPC whose .h5
is compressed (Drogon, for one) then reports "The HDF5 dataset … could not be
read", its geometry comes back empty and the IJK crops are fed polydata. The
.h5 files fesapi writes itself are not compressed, so a local test run can
stay green while real data fails.

The cure: an HDF5 built with zlib (`$env:HDF5_DIR`, for instance HDF5 1.14.2
with zlib), the `HDF5_DIR` entry of fesapi's CMake cache pointed at it,
fesapi rebuilt, and its `FesapiCpp-<version>.dll` copied into the plugin
folder (`bin\paraview-<x.y>\plugins\Fespp`). The image is not concerned: it
builds fesapi against the system HDF5 of its Linux base, which has zlib.

## Debug switches

Environment variables the server reads when it starts; unset, every one is
off. Locally, set them in the shell before starting pvpython
(`$env:FESPP_ETP_DEBUG = "1"`); in a container, `docker run -e NAME=value`
hands them to every session, as the test harnesses do for `FESPP_STRICT`.
The first three take `1` and nothing else.

- **`FESPP_DEBUG_ROUTES=1`** serves `GET /debug/etp`
  (`engine/io/etp_debug_endpoint.py`): a plain-text dump of the live session
  (the ETP connection, the source's partitions and assembly, the IJK
  extractors, each view's visible representations with their cell counts and
  bounds), to read with `curl http://localhost:<port>/debug/etp` after
  driving the session in a browser. The route has no authentication of its
  own: never set the switch on an instance others can reach. When it is on,
  the session log says `[etp-debug] GET /debug/etp is served`.
- **`FESPP_ETP_DEBUG=1`** turns on the trace of `engine/etp_debug.py`:
  time-stamped lines for the ETP connection, the dataspace selection and each
  step of a load on the ETP path, plus a summary of every view after a load or
  an eye click. They are appended to `etp_debug.log` in the process's temp
  directory, which the first line written names on stderr; past 8 MiB the file
  starts over, the previous one kept as `etp_debug.log.1`. The temp directory
  is removed on a clean stop and stays after a crash, so the trace's last line
  names the step a native crash stopped at. Off, every trace call is a no-op.
- **`FESPP_DEBUG_ASSEMBLY=1`** writes the reader's assembly, the XML every tree
  is built from, to `last_assembly.xml` in the process's temp directory each
  time it is refreshed (a file read, an ETP dataspace loaded, a change of the
  tree's hierarchy mode), over the previous one, and prints its size and path
  on stderr.
- **`FESPP_STRICT`** reports the exceptions the application's handlers swallow
  (`engine/strict.py`, armed first thing in `__main__`, so it sees the boot
  too). `1` reports the types that mean a bug (`NameError`, `AttributeError`,
  `TypeError`, `KeyError`, `IndexError`, ...), `all` every exception raised
  inside the application; unset, `0`, `false`, `off` or `no` is off, and any
  other value acts as `1`. Each site (file, line, type) is printed once on
  stderr as `[fespp-strict] ...`, then only counted, and a summary sorted by
  count comes out at exit. It rests on Python 3.12's `sys.monitoring`, which
  sees an exception as it is raised, before any handler: nothing in the
  application's behaviour changes, a swallowed exception stays swallowed.
  `test-visual.ps1` and `tests/browser/instance.ps1` arm it with `1` (a
  `FESPP_STRICT` set on the host overrides that), and a run fails on any
  report.
