from pathlib import Path

from trame_welllog import __version__

# Local folder holding the built bundle (vite's outDir). The version is part
# of the served URL, so a new release is not masked by a cached bundle.
serve_path = str(Path(__file__).with_name("serve").resolve())
serve_directory = f"__trame_welllog_{__version__}"

# Serve directory for JS/CSS files
serve = {serve_directory: serve_path}

# List of JS files to load (the built UMD bundle)
scripts = [f"{serve_directory}/trame_welllog.umd.js"]

# List of CSS files to load (only if the build emitted any)
if (Path(serve_path) / "style.css").exists():
    styles = [f"{serve_directory}/style.css"]

# List of Vue plugins to install/load (must match vite lib.name / UMD global)
vue_use = ["trame_welllog"]
