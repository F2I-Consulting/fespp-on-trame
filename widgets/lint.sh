#!/bin/sh
# Lint every widget's client source with the toolchain installed in widgets/tree.
cd "$(dirname "$0")" || exit 1
# every function a template calls must exist in its script: eslint does not
# check it (see check-template-calls.mjs)
node ./check-template-calls.mjs || exit 1
./tree/vue-components/node_modules/.bin/eslint --no-eslintrc -c ./.eslintrc.widgets.json --resolve-plugins-relative-to ./tree/vue-components --ext .js,.vue \
  --ignore-pattern "**/node_modules/**" --ignore-pattern "**/serve/**" --ignore-pattern "**/dist/**" \
  $(ls -d */vue-components/src */src _shared 2>/dev/null) "$@"
