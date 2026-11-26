# Build the RAG index of fespp_ia, AT INSTALL TIME, in two steps:
#   1. the corpus (chunks.jsonl) from the local source trees:
#      this repo (docs, wiki, docstrings), fesapi and FESPP headers (their
#      Doxygen blocks describe every RESQML object) and FESPP's plugin XML,
#      the ParaView docstrings and proxy documentation read in the app image,
#      the PWLS 4.0 property kinds, the ICS chart, the assistant's catalogue,
#      and the documents in ia\corpus (the glossary and the project documents,
#      plus what ia\get-docs.ps1 fetched: Energistics, AAPG Wiki, Wikipedia,
#      OSDU);
#   2. the index (vectors + chunks) with the embedding model of ia\models\embed,
#      written into ia\models\index, which the service mounts read-only.
#
#   .\ia\build-index.ps1 -Fesapi <fesapi source tree> -Fespp <FESPP src folder>
#   .\ia\build-index.ps1                    -> the same, the two folders taken from FESAPI_SRC and FESPP_SRC
#   .\ia\build-index.ps1 -PwlsEpc <eml23_pwls40.epc>   -> the PWLS 4.0 EPC from another place
#   .\ia\build-index.ps1 -SkipCorpus        -> only step 2 (the chunks are there)
#   .\ia\build-index.ps1 -Index index-new   -> build beside the index the service uses
#   .\ia\build-index.ps1 -Developer -Fetpapi <fetpapi source tree>
#                                           -> the developer's index, BESIDE the application's (ia\models\index-dev,
#                                              chunks-dev.jsonl): everything above, plus the SWIG interface files,
#                                              the examples and the READMEs of fesapi and fetpapi, fetpapi's headers,
#                                              and SWIG's manual when .\ia\get-docs.ps1 -Only swig fetched it.
#                                              -Fetpapi may come from FETPAPI_SRC; without it the index goes
#                                              without fetpapi. Serve it with FESPP_IA_INDEX=/models/index-dev.
#
# -Fesapi is the root of a fesapi source tree, the folder that holds src\ (the
# fesapi version the app image builds); -Fespp is FESPP's src folder, the one
# that holds Plugin\. -PwlsEpc is Energistics' PWLS 4.0 property-kind
# dictionary (eml23_pwls40.epc, a public download); without it, looked for in
# data\private by default, step 1 goes on and says what it left out.
# Step 1 runs in the fespp_ia image (it has pypdf, for the PDFs of ia\corpus),
# and in the app image (-AppImage) for what ParaView documents.
param(
    [string]$Fesapi = $env:FESAPI_SRC,
    [string]$Fespp = $env:FESPP_SRC,
    [string]$Fetpapi = $env:FETPAPI_SRC,
    [switch]$Developer,
    [string]$PwlsEpc = "",
    [string]$AppImage = "fespp_on_trame:local",
    [string]$Image = "fespp_ia:cpu",
    [string]$Index = "index",
    [string]$Chunks = "chunks.jsonl",
    [switch]$SkipCorpus
)
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
$cache = Join-Path $PSScriptRoot "corpus_cache"
$models = Join-Path $PSScriptRoot "models"
$pkg = Join-Path $PSScriptRoot "fespp_ia"
# the developer's index never takes the place of the application's: unless
# they are named, its chunks and its folder get their own names
if ($Developer) {
    if (-not $PSBoundParameters.ContainsKey("Index")) { $Index = "index-dev" }
    if (-not $PSBoundParameters.ContainsKey("Chunks")) { $Chunks = "chunks-dev.jsonl" }
}
# a PWLS EPC that was asked for must be there; the default one may be absent
$pwlsAsked = [bool]$PwlsEpc
if (-not $PwlsEpc) { $PwlsEpc = Join-Path $root "data\private\eml23_pwls40.epc" }

if (-not $SkipCorpus) {
    # every input checked before the first container: the steps before the
    # corpus take minutes, and a missing folder would only show at the end
    $bad = @()
    if (-not $Fesapi) {
        $bad += "no fesapi source tree: pass -Fesapi <folder> or set FESAPI_SRC"
    } elseif (-not (Test-Path -PathType Container (Join-Path $Fesapi "src"))) {
        $bad += "the fesapi source tree $Fesapi (-Fesapi or FESAPI_SRC) has no src folder"
    }
    if (-not $Fespp) {
        $bad += "no FESPP src folder: pass -Fespp <folder> or set FESPP_SRC"
    } elseif (-not (Test-Path -PathType Container (Join-Path $Fespp "Plugin"))) {
        $bad += "the FESPP src folder $Fespp (-Fespp or FESPP_SRC) has no Plugin folder"
    }
    if ($pwlsAsked -and -not (Test-Path -PathType Leaf $PwlsEpc)) { $bad += "no PWLS 4.0 EPC at $PwlsEpc (-PwlsEpc)" }
    if ($Developer -and $Fetpapi -and -not (Test-Path -PathType Container (Join-Path $Fetpapi "src"))) {
        $bad += "the fetpapi source tree $Fetpapi (-Fetpapi or FETPAPI_SRC) has no src folder"
    }
    if ($bad.Count) {
        foreach ($b in $bad) { Write-Host "[index] $b" -ForegroundColor Red }
        Write-Host "[index] -SkipCorpus builds the index from the chunks already in ia\corpus_cache" -ForegroundColor Yellow
        exit 1
    }
    # docker takes a relative host path for the name of a volume: mount absolute ones
    $Fesapi = (Resolve-Path $Fesapi).Path
    $Fespp = (Resolve-Path $Fespp).Path
}
New-Item -ItemType Directory -Force $cache, (Join-Path $PSScriptRoot "corpus") | Out-Null

if (-not $SkipCorpus) {
    if (-not (Test-Path (Join-Path $cache "paraview_simple.jsonl"))) {
        Write-Host "[index] ParaView docstrings from the app image" -ForegroundColor Cyan
        docker run --rm -v "${cache}:/out" --entrypoint /opt/paraview/bin/pvpython $AppImage -c @"
import inspect, json
from paraview import simple
out = open('/out/paraview_simple.jsonl', 'w', encoding='utf-8')
for name in sorted(dir(simple)):
    if name.startswith('_'): continue
    obj = getattr(simple, name); doc = inspect.getdoc(obj) or ''
    if len(doc) < 40: continue
    try: sig = str(inspect.signature(obj)) if inspect.isfunction(obj) else ''
    except (TypeError, ValueError): sig = ''
    out.write(json.dumps({'source': 'paraview', 'path': 'paraview.simple.' + name, 'title': 'paraview.simple.' + name + sig, 'text': 'paraview.simple.' + name + sig + '\n\n' + doc}, ensure_ascii=False) + '\n')
"@
    }
    # documents generated from local inputs, into ia\corpus (git-ignored):
    # the ParaView proxies' own documentation (filters, representations, views,
    # and FESPP's readers) read in the app image, the PWLS 4.0 property kinds
    # from the EPC the app derives its property hierarchy from, and the ICS
    # chart from the app's table
    $py = @("-v", "${root}:/repo", "-v", "${pkg}:/opt/fespp_ia/fespp_ia:ro", "-w", "/repo/ia", "--entrypoint", "python3", $Image)
    Write-Host "[index] ParaView proxy documentation from the app image" -ForegroundColor Cyan
    docker run --rm -v "${root}:/repo" --entrypoint /opt/paraview/bin/pvpython $AppImage `
        /repo/ia/fespp_ia/paraview_docs.py /repo/ia/corpus/paraview
    if ($LASTEXITCODE -ne 0) { Write-Host "[index] ParaView documentation failed" -ForegroundColor Red; exit 1 }
    if (Test-Path -PathType Leaf $PwlsEpc) {
        Write-Host "[index] PWLS 4.0 property kinds" -ForegroundColor Cyan
        $epc = (Resolve-Path $PwlsEpc).Path
        docker run --rm -v "$(Split-Path -Parent $epc):/pwls:ro" @py -m fespp_ia.pwls_docs "/pwls/$(Split-Path -Leaf $epc)" /repo/ia/corpus/pwls
        if ($LASTEXITCODE -ne 0) { Write-Host "[index] PWLS failed" -ForegroundColor Red; exit 1 }
    } elseif (Test-Path (Join-Path $PSScriptRoot "corpus\pwls")) {
        Write-Host "[index] no PWLS 4.0 EPC at ${PwlsEpc}: the property kinds already in ia\corpus\pwls are kept (-PwlsEpc <eml23_pwls40.epc> rewrites them)" -ForegroundColor Yellow
    } else {
        Write-Host "[index] no PWLS 4.0 EPC at ${PwlsEpc}: the corpus goes without the property kinds (-PwlsEpc <eml23_pwls40.epc> adds them)" -ForegroundColor Yellow
    }
    Write-Host "[index] ICS chronostratigraphic chart" -ForegroundColor Cyan
    docker run --rm @py -m fespp_ia.ics_docs /repo/ia/corpus/geologie/ics
    if ($LASTEXITCODE -ne 0) { Write-Host "[index] ICS chart failed" -ForegroundColor Red; exit 1 }
    $mounts = @("-v", "${root}:/repo", "-v", "${Fesapi}:/fesapi:ro", "-v", "${Fespp}:/fespp:ro")
    $catalogue = @()
    if (Test-Path (Join-Path $cache "catalogue-hints.json")) {
        $catalogue = @("--catalogue", "/repo/ia/corpus_cache/catalogue-hints.json")
    } else {
        Write-Host "[index] no ia\corpus_cache\catalogue-hints.json: the corpus goes without the assistant's catalogue" -ForegroundColor Yellow
    }
    # the developer's sources: fetpapi is read only for them
    $developer = @()
    if ($Developer) {
        $developer = @("--developer")
        if ($Fetpapi) {
            $mounts += @("-v", "$((Resolve-Path $Fetpapi).Path):/fetpapi:ro")
            $developer += @("--fetpapi", "/fetpapi")
        } else {
            Write-Host "[index] no fetpapi source tree (-Fetpapi or FETPAPI_SRC): the developer's corpus goes without fetpapi" -ForegroundColor Yellow
        }
        if (-not (Test-Path (Join-Path $PSScriptRoot "corpus\swig"))) {
            Write-Host "[index] no ia\corpus\swig: the developer's corpus goes without SWIG's manual (.\ia\get-docs.ps1 -Only swig fetches it)" -ForegroundColor Yellow
        }
    }
    Write-Host "[index] corpus" -ForegroundColor Cyan
    docker run --rm @mounts -v "${pkg}:/opt/fespp_ia/fespp_ia:ro" -w /repo/ia --entrypoint python3 $Image -m fespp_ia.corpus `
        --app /repo --fesapi /fesapi --fespp /fespp --paraview /repo/ia/corpus_cache/paraview_simple.jsonl @catalogue `
        @developer --dropped /repo/ia/corpus --out "/repo/ia/corpus_cache/$Chunks"
    if ($LASTEXITCODE -ne 0) { Write-Host "[index] corpus failed" -ForegroundColor Red; exit 1 }
}
Write-Host "[index] embeddings (a few minutes on a CPU)" -ForegroundColor Cyan
docker run --rm -v "${cache}:/cache:ro" -v "${models}:/models" -v "${pkg}:/opt/fespp_ia/fespp_ia:ro" `
    --entrypoint python3 $Image -m fespp_ia.rag --chunks "/cache/$Chunks" --index "/models/$Index" `
    --model /models/embed/bilingual-embedding-small
if ($LASTEXITCODE -ne 0) { Write-Host "[index] embeddings failed" -ForegroundColor Red; exit 1 }
Write-Host "[OK] index in $(Join-Path $models $Index) - restart the service (.\ia\run.ps1, or docker compose restart ia)" -ForegroundColor Green
