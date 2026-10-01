from pathlib import Path

from trame_fespp_icon import __version__

serve_path = str(Path(__file__).with_name("serve").resolve())
serve_directory = f"__trame_fespp_icon_{__version__}"

serve = {serve_directory: serve_path}
scripts = [f"{serve_directory}/trame_fespp_icon.umd.js"]
styles = []
vue_use = ["trame_fespp_icon"]
