# Running the widget in Trame

`examples/app.py` mounts the `WellLogCorrelation` widget in a standalone Trame
app with mock data — the way to see the widget render in real Trame (not just
the static `demo.html`).

## One-time setup

**1. Build the JS bundle** (needs Node 18+ on the PATH):
```powershell
Set-Location vue-components
npm install
npm run build          # -> trame_welllog/module/serve/trame_welllog.umd.js
Set-Location ..
```

**2. Python venv + dependencies** (isolated, gitignored):
```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install trame trame-vuetify
.\.venv\Scripts\python -m pip install -e .
```

## Run

```powershell
.\.venv\Scripts\python examples\app.py --server --port 8765 --timeout 0
```
Then open <http://localhost:8765>.

- `--server` = headless (don't auto-open a browser); drop it to auto-open.
- `--timeout 0` = **stay up even with no client connected**. Without it, Trame
  auto-closes the server ~5 min after the last client disconnects (e.g. when you
  close the browser tab).

Stop with `Ctrl+C`.

## After editing `src/correlation.js`

The bundle embeds the renderer at build time, so rebuild before re-running:
```powershell
Set-Location vue-components; npm run build; Set-Location ..
```
(`demo.html` loads `correlation.js` directly, so it needs no rebuild.)
