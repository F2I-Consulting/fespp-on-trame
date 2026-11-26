#!/usr/bin/env bash
# The container's run script with a choice: FESPP_POOL=1 starts the session
# pool (deploy/pool/run-pool.sh), anything else the wslink launcher as the
# image shipped it (run-wslink.sh: the original run.sh, kept at install).
if [ "$FESPP_POOL" = "1" ]; then
  exec /deploy/pool/run-pool.sh
fi
exec /opt/trame/run-wslink.sh
