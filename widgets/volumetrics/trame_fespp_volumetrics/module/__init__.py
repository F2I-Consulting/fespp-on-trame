"""trame module: serves the built Vue bundle and registers it as a Vue plugin.

The served URL carries the package version: a version bump changes the URL
the browser fetches the bundle from.
"""
from pathlib import Path

from trame_fespp_volumetrics import __version__

serve_path = str(Path(__file__).with_name("serve").resolve())
serve_directory = f"__trame_fespp_volumetrics_{__version__}"

serve = {serve_directory: serve_path}
scripts = [f"{serve_directory}/trame_fespp_volumetrics.umd.js"]
styles = [f"{serve_directory}/style.css"]
vue_use = ["trame_fespp_volumetrics"]
