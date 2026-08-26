from pathlib import Path

TRAME_APP_TITLE = "FESPP on TRAME"

SOURCES_PATH = Path(__file__).parent
# Container layout copies the repo's public/ to /deploy/public; locally it lives
# at <repo>/public. Prefer the container path when present, else the repo dir, so
# the app boots on both Docker and a local checkout.
_DOCKER_PUBLIC = Path("/deploy/public")
PUBLIC_PATH = _DOCKER_PUBLIC if _DOCKER_PUBLIC.exists() else (SOURCES_PATH.parent / "public")
