from pathlib import Path

from trame_fespp_newview import __version__

serve_path = str(Path(__file__).with_name("serve").resolve())
serve_directory = f"__trame_fespp_newview_{__version__}"

serve = {serve_directory: serve_path}
scripts = [f"{serve_directory}/trame_fespp_newview.umd.js"]
styles = [f"{serve_directory}/style.css"]
vue_use = ["trame_fespp_newview"]
