# What an image must pass before it is put on the public server: it carries
# the working tree's code, the lint gate and the unit suite pass on that
# code (test-unit.ps1), a short list of scenarios pass on the image AS IT
# IS, nothing injected (test-visual.ps1), and its page comes up in a
# browser (tests\browser\probes\page_up.mjs, on the trial container when it
# runs that image). About a quarter of an hour; -Quick stops after the unit
# suite.
#
#   .\test-before-deploy.ps1                 the image the trial container runs
#   .\test-before-deploy.ps1 -Image <tag>    that image
#   .\test-before-deploy.ps1 -Quick          code, lint and unit tests only
#
# The verdict is kept under _local\checked\<image id>.txt, its output next
# to it (.log): deploy\caddy\crhome.ps1 reads the verdict, runs this script
# when the image has none, and refuses an image that failed.
#
# ASCII only: PowerShell 5.1 reads a file without BOM in the ANSI code page.
param(
    [string]$Image = "",
    [string]$From = "fespp_new",
    [int]$FromPort = 8082,
    [switch]$Quick
)

$root = $PSScriptRoot
$site = "/deploy/server/venv/lib/python3.12/site-packages"

# The short list: one scenario per thing a swap must not break -- a first
# load, a grid's properties and colours, a threshold, a cut of the scene,
# wells and markers, the Values view, a session put back, the Statistics
# view, a second 3D view, the memory given back over cycles of ticks. Each must pass on a sound image: a scenario that
# fails for a reason of its own has no place here.
$scenarios = @("first_load", "two_properties", "colormap", "threshold_eye", "scene_slicer",
               "markers_md", "values_filter", "session_roundtrip", "stats_pin_all", "second_view",
               "memory_cycles")

if (-not $Image) { $Image = (docker inspect -f "{{.Config.Image}}" $From 2>$null | Out-String).Trim() }
if (-not $Image) { Write-Host "[ERREUR] pas de conteneur $From : donner l'image par -Image." -ForegroundColor Red; exit 2 }
$id = (docker image inspect -f "{{.Id}}" $Image 2>$null | Out-String).Trim()
if (-not $id) { Write-Host "[ERREUR] l'image $Image n'existe pas sur ce poste." -ForegroundColor Red; exit 2 }
$short = ($id -replace "^sha256:", "").Substring(0, 12)
$dir = Join-Path $root "_local\checked"
New-Item -ItemType Directory -Force $dir | Out-Null
$verdict = Join-Path $dir "$short.txt"
$log = Join-Path $dir "$short.log"
Set-Content -Path $log -Value "check of $Image ($short), $(Get-Date -Format s)" -Encoding ascii
$failed = @()
$ran = @()

function Step([string]$what, [bool]$ok, [string]$more) {
    $dots = "." * [Math]::Max(3, 44 - $what.Length)
    $word = "ok"
    $color = "Green"
    if (-not $ok) { $word = "ECHEC"; $color = "Red" }
    Write-Host ("  {0} {1} {2} {3}" -f $what, $dots, $word, $more) -ForegroundColor $color
    $script:ran += $what
    if (-not $ok) { $script:failed += $what }
}

Write-Host ""
Write-Host "Verification de $Image ($short)" -ForegroundColor Cyan

# 1. the image carries the working tree's code: the unit suite below reads
#    the tree, and what it says is true of the image only then
$inner = @'
cd /repo && find fespp_on_trame -name '*.py' | xargs md5sum > /tmp/list
for d in widgets/*/trame_*; do (cd $(dirname $d) && find $(basename $d) -type f \( -name '*.py' -o -name '*.js' -o -name '*.css' \) | xargs md5sum) >> /tmp/list; done
cd SITE && md5sum -c /tmp/list 2>/dev/null | grep -v ': OK$' | head -5
'@
$inner = ($inner -replace "`r", "") -replace "SITE", $site
$drift = (docker run --rm --entrypoint sh -v "${root}:/repo:ro" $Image -c $inner | Out-String).Trim()
Add-Content -Path $log -Value "--- code: $drift" -Encoding ascii
Step "code de l'arbre dans l'image" (-not $drift) ""
if ($drift) {
    Write-Host "    l'image ne porte pas le code de l'arbre de travail : redeployer l'essai (run.ps1), puis verifier." -ForegroundColor Yellow
    Write-Host ("    " + ($drift -split "`n")[0]) -ForegroundColor DarkGray
}

# 2. the lint gate and the unit suite, on the tree's code with the image's Python
$out = (& (Join-Path $root "test-unit.ps1") -Image $Image *>&1 | Out-String)
$unitOk = ($LASTEXITCODE -eq 0)
Add-Content -Path $log -Value "--- unit`n$out" -Encoding ascii
$last = (($out -split "`n") | Where-Object { $_ -match "passed|failed|error" } | Select-Object -Last 1)
Step "lint et tests unitaires" $unitOk ("" + $last).Trim(" =`r")

if (-not $Quick) {
    # 3. the short list of scenarios, on the image itself
    foreach ($s in $scenarios) {
        $out = (& (Join-Path $root "test-visual.ps1") -Scenario $s -Image $Image *>&1 | Out-String)
        $ok = ($LASTEXITCODE -eq 0)
        Add-Content -Path $log -Value "--- scenario $s`n$out" -Encoding ascii
        Step "scenario $s" $ok ""
    }
    # 4. the page in a browser, on the trial container when it runs this image
    $trial = (docker inspect -f "{{.Config.Image}}" $From 2>$null | Out-String).Trim()
    if ($trial -eq $Image -and (Get-Command node -ErrorAction SilentlyContinue)) {
        Push-Location (Join-Path $root "tests\browser")
        $out = (node probes\page_up.mjs "http://127.0.0.1:${FromPort}/fespp/" *>&1 | Out-String)
        $ok = ($LASTEXITCODE -eq 0)
        Pop-Location
        Add-Content -Path $log -Value "--- page`n$out" -Encoding ascii
        Step "page dans le navigateur" $ok ""
    } else {
        Write-Host "  page dans le navigateur : non verifiee ($From ne tourne pas sur cette image, ou node manque)." -ForegroundColor Yellow
    }
}

$word = "PASS"
if ($failed.Count) { $word = "FAIL" }
$lines = @($word, (Get-Date -Format s), $Image, $id, ("ran: " + ($ran -join "; ")))
if ($Quick) { $lines += "quick: code, lint and unit tests only" }
if ($failed.Count) { $lines += ("failed: " + ($failed -join "; ")) }
Set-Content -Path $verdict -Value $lines -Encoding ascii
Write-Host ""
if ($failed.Count) {
    Write-Host "VERDICT : ECHEC ($($failed -join ', '))" -ForegroundColor Red
    Write-Host "Journal : $log" -ForegroundColor DarkGray
    exit 1
}
Write-Host "VERDICT : bon pour la bascule." -ForegroundColor Green
Write-Host "Journal : $log" -ForegroundColor DarkGray
exit 0
