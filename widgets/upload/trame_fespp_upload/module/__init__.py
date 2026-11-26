"""trame web module of the upload widgets: serves the Vue bundle built by
vite into serve/ under a versioned directory, and registers it with Vue."""

from pathlib import Path

from trame_fespp_upload import __version__

serve_path = str(Path(__file__).with_name("serve").resolve())
serve_directory = f"__trame_fespp_upload_{__version__}"

serve = {serve_directory: serve_path}
scripts = [f"{serve_directory}/trame_fespp_upload.umd.js"]
styles = [f"{serve_directory}/style.css"]
vue_use = ["trame_fespp_upload"]
