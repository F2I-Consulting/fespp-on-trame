"""trame module of the cross-plot widget: serves the Vue bundle built into
`serve/` (see vue-components/vite.config.js) and installs its plugin.

The served directory name carries the package version, so a browser never
keeps a stale bundle across releases.
"""
from pathlib import Path

from trame_fespp_crossplot import __version__

serve_path = str(Path(__file__).with_name("serve").resolve())
serve_directory = f"__trame_fespp_crossplot_{__version__}"

serve = {serve_directory: serve_path}
scripts = [f"{serve_directory}/trame_fespp_crossplot.umd.js"]
styles = [f"{serve_directory}/style.css"]
vue_use = ["trame_fespp_crossplot"]
