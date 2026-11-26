#!/usr/bin/env bash
# The container's run script with the session pool (deploy/pool/fespp_pool.py)
# in place of wslink's launcher: the same config.json, generated the same way
# (TRAME_USE_HOST / TRAME_URL_PREFIX), then the template in the background and
# the HTTP front in the foreground. The original stays as run-wslink.sh.

if [ ! -d /deploy/server ]; then
  echo "ERROR: The the server directory must be in the container at '/deploy/server'"
  exit 1
fi

. /opt/trame/activate_venv.sh

LAUNCHER_TEMPLATE_PATH=/deploy/server/launcher.json
LAUNCHER_PATH=/opt/trame/config.json

OUTPUT=$(<"${LAUNCHER_TEMPLATE_PATH}")

if [[ -n $TRAME_USE_HOST ]]; then
  REPLACEMENT_STRING="USE_HOST"
  if [[ $TRAME_USE_HOST == *"://"* ]]; then
    REPLACEMENT_STRING="ws://$REPLACEMENT_STRING"
  fi
  OUTPUT="${OUTPUT//$REPLACEMENT_STRING/$TRAME_USE_HOST}"
elif [[ -n "$TRAME_URL_PREFIX" ]]; then
  REPLACEMENT_STRING="ws://USE_HOST/proxy"
  OUTPUT_STRING="ws://USE_HOST$TRAME_URL_PREFIX/proxy"
  OUTPUT="${OUTPUT//$REPLACEMENT_STRING/$OUTPUT_STRING}"
fi

echo -e "$OUTPUT" > "${LAUNCHER_PATH}"

echo "Starting the FesTrame session pool (template + launcher), size ${FESPP_POOL_SIZE:-2}"
/opt/paraview/bin/pvpython /deploy/pool/fespp_pool.py template "${LAUNCHER_PATH}" &
exec python /deploy/pool/fespp_pool.py launcher "${LAUNCHER_PATH}"
