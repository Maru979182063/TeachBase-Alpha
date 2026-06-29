param(
    [Parameter(Mandatory = $true)]
    [string]$ApiKey,

    [string]$Model = "doubao-seed-1-8-251228",

    [string]$ManifestPath = "",

    [string]$OutDir = ""
)

$ErrorActionPreference = "Stop"

$workspaceRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$script = Join-Path $PSScriptRoot "teacher_handout_visual_transcribe_doubao.py"

if (-not $ManifestPath) {
    $ManifestPath = Join-Path $workspaceRoot "outputs\visual_transcription_v0.1\math_symbol_200q_clean_main_source_20260624\all_questions_manifest.json"
}

if (-not $OutDir) {
    $OutDir = Join-Path $workspaceRoot "outputs\visual_transcription_v0.1\math_symbol_200q_clean_main_doubao18_20260624"
}

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$env:ARK_API_KEY = $ApiKey
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

& $python $script `
    --manifest $ManifestPath `
    --model $Model `
    --out-dir $OutDir
