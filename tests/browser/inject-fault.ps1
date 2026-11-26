# Break the application inside a running smoke container, on purpose, from a
# COPY of the code: the working tree is never touched. Then run the suite with
# -Reuse and watch it fail; -Restore puts the local code back.
#
#   .\tests\browser\inject-fault.ps1 -Fault tree-undefined
#   .\test-browser.ps1 -Reuse                          -> must FAIL
#   .\tests\browser\inject-fault.ps1 -Restore
#   .\test-browser.ps1 -Reuse                          -> must PASS
#
# The two faults are template and bundle failures that no Python-side test
# can see:
#
#   tree-undefined   a rename in the tree component (DataExplorerTree.vue) that
#                    leaves one reference to the old name: the computed throws
#                    on first render and the tree card is blank. The bundle is
#                    rebuilt with the widget's own toolchain, from a copy.
#   menu-attribute   the context-menu action list serialised into the tree's
#                    template attribute (data_tree.py): the quotes close the
#                    double-quoted attribute, the template fails to compile,
#                    the whole view panel, tree and menu with it, is blank.
#
# Both leave a trace in the browser console, which is exactly what the suite
# is required to hear: `test-browser.ps1 -Reuse` must go red with a message
# that names it, and green again after -Restore.

param(
    [ValidateSet("tree-undefined", "menu-attribute")]
    [string]$Fault,
    [switch]$Restore,
    [string]$Name = "fespp_smoke"
)

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$site = "/deploy/server/venv/lib/python3.12/site-packages"
$www = "/deploy/server/www"
$treeSrc = Join-Path $root "widgets\tree\vue-components"
$treePy = "fespp_on_trame/app/views/widgets/data_tree.py"
$work = Join-Path $env:TEMP "fespp-smoke-fault"

$running = docker inspect -f "{{.State.Running}}" $Name 2>$null
if ($running -ne "true") {
    Write-Host "[ERROR] container $Name is not running (start one with .\test-browser.ps1 -Keep)" -ForegroundColor Red
    exit 1
}

function Tree-Version {
    $m = Select-String -Path (Join-Path $root "widgets\tree\trame_fespp_tree\__init__.py") -Pattern '__version__\s*=\s*"([^"]+)"'
    return $m.Matches[0].Groups[1].Value
}
$treeWww = "$www/__trame_fespp_tree_$(Tree-Version)"

if ($Restore) {
    # The bundle AND its stylesheet: the scoped-CSS hash of a rebuilt bundle
    # differs, so a stylesheet left behind would leave the tree unstyled.
    docker cp (Join-Path $root "widgets\tree\trame_fespp_tree\module\serve\.") "${Name}:$treeWww/" | Out-Null
    docker cp (Join-Path $root ($treePy -replace '/', '\')) "${Name}:$site/$treePy" | Out-Null
    Write-Host "Restored: local tree bundle and data_tree.py in $Name" -ForegroundColor Green
    exit 0
}
if (-not $Fault) { Write-Host "Give -Fault tree-undefined | menu-attribute, or -Restore"; exit 1 }

if (Test-Path $work) { Remove-Item -Recurse -Force $work }
New-Item -ItemType Directory -Force $work | Out-Null

switch ($Fault) {
    "tree-undefined" {
        if (-not (Test-Path (Join-Path $treeSrc "node_modules"))) {
            Write-Host "[ERROR] $treeSrc has no node_modules: run npm install there first" -ForegroundColor Red
            exit 1
        }
        $copy = Join-Path $work "vue-components"
        # robocopy: node_modules is big and deep; /NFL /NDL /NJH /NJS keep it quiet.
        robocopy $treeSrc $copy /E /NFL /NDL /NJH /NJS /NP | Out-Null
        New-Item -ItemType Directory -Force (Join-Path $work "trame_fespp_tree\module\serve") | Out-Null
        $vue = Join-Path $copy "src\DataExplorerTree.vue"
        $src = Get-Content $vue -Raw -Encoding UTF8
        # The rename: `parsedRoots` becomes `parsedNodes` everywhere but in
        # one computed (the empty state, read on the very first render of an
        # empty tree), which still reads the old name. Each half must find
        # its line: a rename that leaves nothing behind is a working bundle,
        # and the suite would pass where it is expected to fail.
        $renamed = $src -replace 'parsedRoots', 'parsedNodes'
        if ($renamed -eq $src) { Write-Host "[ERROR] the rename found nothing to break" -ForegroundColor Red; exit 1 }
        $broken = $renamed -replace 'if \(!this\.parsedNodes\.length\) \{',
                                    'if (!this.parsedRoots.length) {'
        if ($broken -eq $renamed) { Write-Host "[ERROR] the empty-state computed no longer reads the root list: retarget the fault" -ForegroundColor Red; exit 1 }
        [IO.File]::WriteAllText($vue, $broken, (New-Object Text.UTF8Encoding $false))
        Push-Location $copy
        npx vite build --emptyOutDir 2>&1 | Out-Null
        $built = $LASTEXITCODE
        Pop-Location
        if ($built -ne 0) { Write-Host "[ERROR] vite build failed" -ForegroundColor Red; exit 1 }
        docker cp (Join-Path $work "trame_fespp_tree\module\serve\.") "${Name}:$treeWww/" | Out-Null
        Write-Host "Injected: tree bundle with an undefined reference (parsedRoots) into $Name" -ForegroundColor Yellow
    }
    "menu-attribute" {
        $py = Join-Path $work "data_tree.py"
        $src = Get-Content (Join-Path $root ($treePy -replace '/', '\')) -Raw -Encoding UTF8
        $broken = $src -replace 'context_actions=\(_CONTEXT_ACTIONS_VAR,\),',
                                'context_actions=(json.dumps(_CONTEXT_ACTIONS),),'
        $broken = $broken -replace '(?m)^from trame_fespp_tree\.widgets\.tree import DataExplorerTree',
                                   "import json`nfrom trame_fespp_tree.widgets.tree import DataExplorerTree"
        if ($broken -eq $src) { Write-Host "[ERROR] the attribute rewrite found nothing to break" -ForegroundColor Red; exit 1 }
        [IO.File]::WriteAllText($py, $broken, (New-Object Text.UTF8Encoding $false))
        docker cp $py "${Name}:$site/$treePy" | Out-Null
        Write-Host "Injected: data_tree.py serialising the menu into the template attribute, into $Name" -ForegroundColor Yellow
    }
}
Write-Host "Now: .\test-browser.ps1 -Reuse   (expected: BROWSER TESTS: FAIL)" -ForegroundColor Gray
exit 0
