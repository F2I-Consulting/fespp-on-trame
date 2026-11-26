"""trame module of the widget: serves the Vue bundle that vite builds from
vue-components/ into serve/, and registers it as a Vue plugin.

The serve directory name carries the package version, so each release of
the bundle is served under its own URL.
"""
from pathlib import Path

from trame_fespp_assistant import __version__

serve_path = str(Path(__file__).with_name("serve").resolve())
serve_directory = f"__trame_fespp_assistant_{__version__}"

serve = {serve_directory: serve_path}
scripts = [f"{serve_directory}/trame_fespp_assistant.umd.js"]
styles = [f"{serve_directory}/style.css"]
vue_use = ["trame_fespp_assistant"]
