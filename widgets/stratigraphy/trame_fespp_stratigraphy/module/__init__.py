"""Trame module: serves the built Vue bundle and registers it in the client.

The version is part of the served path, so a browser never reuses a cached
bundle of another version.
"""
from pathlib import Path

from trame_fespp_stratigraphy import __version__

serve_path = str(Path(__file__).with_name("serve").resolve())
serve_directory = f"__trame_fespp_stratigraphy_{__version__}"

serve = {serve_directory: serve_path}
scripts = [f"{serve_directory}/trame_fespp_stratigraphy.umd.js"]
styles = [f"{serve_directory}/style.css"]
vue_use = ["trame_fespp_stratigraphy"]
