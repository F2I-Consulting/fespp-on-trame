# Retrain the assistant's intent model (fespp_on_trame/assets/nlu_intents.npz)
# from the patterns, the lexicon and the corpus, inside a container of the
# image (nothing to install on the host). See scripts/train_nlu.py.
#
#   .\scripts\train-nlu.ps1                 -> train, score the open sets
#   .\scripts\train-nlu.ps1 -Heldout        -> ... and the sealed sets (score only)
#   .\scripts\train-nlu.ps1 -Confusions     -> ... and list what the model still misses
#   .\scripts\train-nlu.ps1 -Quiet          -> scores only, no per-sentence misses
#   .\scripts\train-nlu.ps1 -Image fespp_on_trame:<tag>   -> in another build of the app image
#
# Keep this file ASCII: PowerShell 5.1 reads a BOM-less script as ANSI, and
# an em dash there breaks the parse.
param(
    [string]$Image = "fespp_on_trame:local",
    [switch]$Heldout,
    [switch]$Confusions,
    [switch]$Quiet
)
$root = Split-Path -Parent $PSScriptRoot
$flags = @()
if ($Heldout) { $flags += "--heldout" }
if ($Confusions) { $flags += "--confusions" }
if ($Quiet) { $flags += "--quiet" }
docker run --rm -v "${root}:/repo" -w /repo --entrypoint /deploy/server/venv/bin/python $Image scripts/train_nlu.py @flags
if ($LASTEXITCODE -ne 0) { Write-Host "[train-nlu] l'entrainement a echoue" -ForegroundColor Red; exit 1 }
Write-Host "[train-nlu] modele ecrit : fespp_on_trame/assets/nlu_intents.npz - lancez .\test-unit.ps1 -Match nlu" -ForegroundColor Green
