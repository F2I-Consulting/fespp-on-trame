# Fetch the public documentation the RAG reads, AT INSTALL TIME, into
# ia\corpus (git-ignored); the raw pages are kept in ia\corpus_cache, so a
# re-run reads them and does not fetch them again. The service itself never
# downloads anything.
#   - Energistics Online (fespp_ia.energistics_docs): RESQML v2.0.1,
#     Energistics common v2.0, EPC v1.0, the Common Technical Architecture,
#     plus the ETP v1.2 and Unit of Measure Usage Guide PDFs -> corpus\energistics
#   - the AAPG Wiki, every article (fespp_ia.wiki_docs, CC BY-SA 3.0)
#     -> corpus\geologie\aapg
#   - Wikipedia FR + EN, a curated list of reservoir geology and stratigraphy
#     articles (fespp_ia.wikipedia_docs, CC BY-SA 4.0) -> corpus\geologie\wikipedia
#   - the OSDU Data Definitions usage guide, glossary and worked examples
#     (fespp_ia.osdu_docs, Apache-2.0) -> corpus\osdu
#   - SWIG's manual (fespp_ia.swig_docs, SWIG's licence: GPL-3.0-or-later), the
#     chapters a C++ library wrapped for Python, Java and C# needs -> corpus\swig.
#     Only the developer's index reads it (.\ia\build-index.ps1 -Developer), so
#     it is not fetched unless asked for: -Only swig
#   .\ia\get-docs.ps1                           -> the first four, then rebuild the index
#   .\ia\get-docs.ps1 -Only energistics -Families RESQML,EPC
#   .\ia\get-docs.ps1 -NoPdf                    -> Energistics without the PDFs
#   .\ia\get-docs.ps1 -Only swig                -> SWIG's manual, then .\ia\build-index.ps1 -Developer
#   .\ia\get-docs.ps1 -Only swig -SwigVersion 4.3   -> the manual of another SWIG release
# An official package behind an Open Group account (RESQML v2.2, ETP XSD):
# drop its zip in ia\corpus, the corpus builder reads the XSD inside.
param([string]$Only = "energistics,aapg,wikipedia,osdu", [string]$Families = "RESQML,ECOM2,EPC,CTA",
      [string]$Image = "fespp_ia:cpu", [switch]$NoPdf, [string]$SwigVersion = "4.4")
$ErrorActionPreference = "Continue"
$corpus = Join-Path $PSScriptRoot "corpus"
$cache = Join-Path $PSScriptRoot "corpus_cache"
$pkg = Join-Path $PSScriptRoot "fespp_ia"
$run = @("run", "--rm", "--entrypoint", "python3", "-v", "${pkg}:/opt/fespp_ia/fespp_ia:ro",
         "-v", "${corpus}:/corpus", "-v", "${cache}:/cache", $Image)
$wanted = $Only.ToLower().Split(",") | ForEach-Object { $_.Trim() }
New-Item -ItemType Directory -Force $corpus, $cache | Out-Null

if ($wanted -contains "energistics") {
    Write-Host "[docs] Energistics Online" -ForegroundColor Cyan
    $a = @("-m", "fespp_ia.energistics_docs", "--out", "/corpus/energistics", "--cache", "/cache/eo_html", "--families", $Families)
    if ($NoPdf) { $a += "--no-pdf" }
    & docker @run @a
    if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] Energistics documentation fetch failed" -ForegroundColor Red; exit 1 }
}
if ($wanted -contains "aapg") {
    Write-Host "[docs] AAPG Wiki" -ForegroundColor Cyan
    & docker @run -m fespp_ia.wiki_docs --api https://wiki.aapg.org/api.php --label "AAPG Wiki" `
        --license "CC BY-SA 3.0" --out /corpus/geologie/aapg --cache /cache/aapg
    if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] AAPG Wiki fetch failed" -ForegroundColor Red; exit 1 }
}
if ($wanted -contains "wikipedia") {
    Write-Host "[docs] Wikipedia FR + EN" -ForegroundColor Cyan
    & docker @run -m fespp_ia.wikipedia_docs --out /corpus/geologie/wikipedia --cache /cache/wikipedia_raw
    if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] Wikipedia fetch failed" -ForegroundColor Red; exit 1 }
}
if ($wanted -contains "osdu") {
    Write-Host "[docs] OSDU Data Definitions" -ForegroundColor Cyan
    & docker @run -m fespp_ia.osdu_docs --out /corpus/osdu --cache /cache/osdu_raw
    if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] OSDU documentation fetch failed" -ForegroundColor Red; exit 1 }
}
if ($wanted -contains "swig") {
    Write-Host "[docs] SWIG manual $SwigVersion" -ForegroundColor Cyan
    & docker @run -m fespp_ia.swig_docs --out /corpus/swig --cache /cache/swig_raw --version $SwigVersion
    if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] SWIG manual fetch failed" -ForegroundColor Red; exit 1 }
}
Write-Host "[OK] documentation in $corpus -- now rebuild the index: .\ia\build-index.ps1" -ForegroundColor Green
