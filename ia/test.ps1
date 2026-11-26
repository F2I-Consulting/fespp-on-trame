# Run the fespp_ia tests inside the image they ship in (fastapi, httpx and
# pytest are installed there). The package and the tests are mounted
# read-only over the image's copies, so the working tree is tested without
# a rebuild.
#   .\ia\test.ps1            -> fespp_ia:cpu
param([string]$Image = "fespp_ia:cpu")
$ErrorActionPreference = "Continue"
$pkg = Join-Path $PSScriptRoot "fespp_ia"
$tests = Join-Path $PSScriptRoot "tests"
docker run --rm --entrypoint python3 -v "${pkg}:/opt/fespp_ia/fespp_ia:ro" `
    -v "${tests}:/opt/fespp_ia/tests:ro" $Image -m pytest -q -p no:cacheprovider tests
exit $LASTEXITCODE
