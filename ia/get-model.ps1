# Bring a model into ia\models, AT INSTALL TIME: the service itself never
# downloads anything (it runs without outbound network).
# Chat models: Mistral AI only (a French publisher, by project policy), and
# only those under Apache 2.0 -- confirm on the model card before shipping
# one: some Mistral models are under a research licence (Ministral-8B-2410).
#   .\ia\get-model.ps1                    -> Ministral-3-3B-Instruct-2512 (Apache 2.0, official GGUF), Q4_K_M, ~2 GB:
#                                             the default chat model (compose.yaml, ia\run.ps1), the one for a CPU
#   .\ia\get-model.ps1 -Name ministral-8b -> Ministral-3-8B-Instruct-2512 (official GGUF), Q4_K_M, ~5 GB:
#                                             the larger one, meant for a GPU (see compose.gpu.yaml)
#   .\ia\get-model.ps1 -Name embed        -> bilingual-embedding-small (La Javaness, Paris, Apache 2.0):
#                                             the RAG's embedding model, ~470 MB, into ia\models\embed\
# A download goes to <file>.part and is renamed only once complete, so an
# interrupted download is never taken for a model.
param([ValidateSet("ministral-3b", "ministral-8b", "embed")][string]$Name = "ministral-3b")

$dir = Join-Path $PSScriptRoot "models"
New-Item -ItemType Directory -Force $dir | Out-Null

function Get-File($url, $out) {
    if (Test-Path $out) { Write-Host "[OK] already there: $out" -ForegroundColor Green; return $true }
    New-Item -ItemType Directory -Force (Split-Path -Parent $out) | Out-Null
    Write-Host "Downloading $url" -ForegroundColor Yellow
    # the curl program: in Windows PowerShell a bare "curl" is an alias of
    # Invoke-WebRequest, so it is named curl.exe there and curl elsewhere
    $curl = if ($env:OS -eq "Windows_NT") { "curl.exe" } else { "curl" }
    & $curl -L --fail -sS -o "$out.part" $url
    if ($LASTEXITCODE -ne 0) { Remove-Item -ErrorAction SilentlyContinue "$out.part"; Write-Host "[ERROR] download failed: $url" -ForegroundColor Red; return $false }
    Move-Item "$out.part" $out
    Write-Host "[OK] $out" -ForegroundColor Green
    return $true
}

if ($Name -eq "embed") {
    $repo = "https://huggingface.co/Lajavaness/bilingual-embedding-small/resolve/main"
    $files = @("config.json", "config.py", "modeling.py", "model.safetensors", "modules.json",
               "sentence_bert_config.json", "config_sentence_transformers.json", "sentencepiece.bpe.model",
               "special_tokens_map.json", "tokenizer.json", "tokenizer_config.json", "1_Pooling/config.json")
    $target = Join-Path $dir "embed\bilingual-embedding-small"
    foreach ($f in $files) {
        if (-not (Get-File "$repo/$f" (Join-Path $target $f))) { exit 1 }
    }
    Write-Host "[OK] embedding model in $target" -ForegroundColor Green
    exit 0
}

$models = @{
    "ministral-3b" = "https://huggingface.co/mistralai/Ministral-3-3B-Instruct-2512-GGUF/resolve/main/Ministral-3-3B-Instruct-2512-Q4_K_M.gguf"
    "ministral-8b" = "https://huggingface.co/mistralai/Ministral-3-8B-Instruct-2512-GGUF/resolve/main/Ministral-3-8B-Instruct-2512-Q4_K_M.gguf"
}
$url = $models[$Name]
if (-not (Get-File $url (Join-Path $dir ($url.Split("/")[-1])))) { exit 1 }
