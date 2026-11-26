"""Trame module of the tree widget: serves the Vue bundle built into ``serve/``.

The served directory name carries the package version: bumping the version
keeps a browser from answering with a stale bundle from its cache.
"""

from pathlib import Path

from trame_fespp_tree import __version__

serve_path = str(Path(__file__).with_name("serve").resolve())
serve_directory = f"__trame_fespp_tree_{__version__}"

serve = {serve_directory: serve_path}
scripts = [f"{serve_directory}/trame_fespp_tree.umd.js"]
styles = [f"{serve_directory}/style.css"]
vue_use = ["trame_fespp_tree"]
