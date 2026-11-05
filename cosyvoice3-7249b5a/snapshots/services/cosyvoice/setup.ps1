param(
    [string]$Config = "configs/cosyvoice.yaml"
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$Python = Join-Path $Root ".venv/Scripts/python.exe"
$RepoCommit = "074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Project virtual environment not found: $Python"
}

$ConfigPath = $Config
if (-not [System.IO.Path]::IsPathRooted($ConfigPath)) {
    $ConfigPath = Join-Path $Root $ConfigPath
}
$cfgJson = & $Python -X utf8 -B -c "import json, sys, yaml; raw = yaml.safe_load(open(sys.argv[1], encoding='utf-8'))['cosyvoice']; print(json.dumps({k: raw[k] for k in ('repo_dir', 'model_id', 'model_revision', 'model_dir')}))" $ConfigPath
if ($LASTEXITCODE -ne 0) { throw "Failed to read config: $ConfigPath" }
$cfg = $cfgJson | ConvertFrom-Json

Push-Location $Root
try {
    uv sync --locked --python $Python
    if ($LASTEXITCODE -ne 0) { throw "uv sync failed" }

    $repoDir = Join-Path $Root $cfg.repo_dir
    if (-not (Test-Path -LiteralPath $repoDir)) {
        New-Item -ItemType Directory -Force -Path (Split-Path $repoDir) | Out-Null
        git clone --recursive https://github.com/QwenAudio/CosyVoice.git $repoDir
        if ($LASTEXITCODE -ne 0) { throw "git clone failed" }
    }
    git -C $repoDir checkout $RepoCommit
    if ($LASTEXITCODE -ne 0) { throw "git checkout failed" }
    git -C $repoDir submodule update --init --recursive
    if ($LASTEXITCODE -ne 0) { throw "git submodule update failed" }

    $modelDir = Join-Path $Root $cfg.model_dir
    $coreFiles = @("llm.pt", "flow.pt", "hift.pt", "speech_tokenizer_v3.onnx", "cosyvoice3.yaml")
    $missing = $coreFiles | Where-Object { -not (Test-Path -LiteralPath (Join-Path $modelDir $_)) }
    if ($missing) {
        & $Python -X utf8 -B -c "from huggingface_hub import snapshot_download; import sys; snapshot_download(repo_id=sys.argv[1], revision=sys.argv[2], local_dir=sys.argv[3])" $cfg.model_id $cfg.model_revision $modelDir
        if ($LASTEXITCODE -ne 0) { throw "model download failed" }
    } else {
        Write-Host "Model core files already present at $modelDir; reusing local weights."
    }
}
finally {
    Pop-Location
}
