# Runs the unit suite AND a bug-only lint gate, INSIDE the application image.
#
# Not on the host: the app needs Python 3.10+ (it uses `dict | None`), and
# the image's venv holds a known interpreter (3.12) with the app's
# dependencies. The image ships neither pytest nor flake8: each run installs
# them (ensurepip + pip install, a few seconds).
#
#   .\test-unit.ps1              suite + lint gate
#   .\test-unit.ps1 -Match tree  only tests whose name matches
#   .\test-unit.ps1 -SkipLint    tests only
#
# Why the lint gate: most of the app's exception handlers catch everything
# and report nothing, mostly legitimate guards around ParaView calls that may
# fail harmlessly. The cost is that a PROGRAMMING error looks exactly like an
# expected quirk: a NameError inside such a guard is swallowed on every call,
# the guarded block silently never runs, and nothing says so. The gate
# refuses exactly that class of mistake (undefined names, redefinitions, `is`
# on a literal, bare `except:`) and stays silent about style, so it cannot be
# dismissed as noise.
param(
    [string]$Image = "fespp_on_trame:local",
    [string]$Match = "",
    [switch]$SkipLint
)

$repo = $PSScriptRoot
$k = if ($Match) { "-k `"$Match`"" } else { "" }

# E999 syntax error             F821 undefined name      F811 redefinition
# F823 used before assignment   F632 `is` on a literal   E722 bare except
# F502/F522 bad % / .format     F601/F602 dict key repeated with different values
$bugCodes = "E999,F821,F811,F823,F632,E722,F502,F522,F601,F602"

$lint = if ($SkipLint) { "" } else { @"
/deploy/server/venv/bin/python -m pip install -q flake8 >/dev/null 2>&1
echo '--- lint gate (bugs only, no style) ---'
/deploy/server/venv/bin/python -m flake8 fespp_on_trame tests --select=$bugCodes || exit 1
echo 'lint gate: clean'
"@ }

# -p no:cacheprovider: the repo is mounted read-only, and pytest's cache
# writes would otherwise warn on every run.
# The image carries no `vtk` wheel: pvpython uses ParaView's own VTK, and the
# wheel (with the matplotlib it pulls in) is large and imported by nothing at
# run time. Three tests build VTK objects from the venv's Python, so the
# wheel is installed for the run, without its dependencies, from a pip cache
# kept on the host (_local\pip-cache): only the first run downloads it.
$inner = @"
/deploy/server/venv/bin/python -m ensurepip >/dev/null 2>&1
/deploy/server/venv/bin/python -m pip install -q pytest >/dev/null 2>&1
/deploy/server/venv/bin/python -c 'import vtkmodules.vtkCommonCore' 2>/dev/null || /deploy/server/venv/bin/python -m pip install -q --no-deps vtk >/dev/null 2>&1 || echo '[test-unit] could not install the vtk wheel: the three VTK tests will fail'
cd /repo || exit 1
$lint
/deploy/server/venv/bin/python -m pytest tests/unit -q -p no:cacheprovider $k
"@
# A Windows checkout gives this file CRLF line endings (`* text=auto`), and
# the here-strings above would carry the `r into the container's sh, which
# reads `2>/dev/null`r` as a redirection to fd "null\r" ("Bad fd number") and
# runs no test at all. Stripping `r keeps the script LF inside the container,
# whatever git did.
$inner = $inner -replace "`r", ""

$pipCache = Join-Path $repo "_local\pip-cache"
New-Item -ItemType Directory -Force $pipCache | Out-Null
docker run --rm --entrypoint sh -v "${repo}:/repo:ro" `
    -v "${pipCache}:/pipcache" -e PIP_CACHE_DIR=/pipcache $Image -c $inner
exit $LASTEXITCODE
