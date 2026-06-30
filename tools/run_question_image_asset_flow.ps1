param(
  [Parameter(Mandatory = $true)]
  [string]$SourceJson,

  [string]$OutDir = "",
  [string]$VisualResults = "",
  [string]$Model = "doubao-seed-2-0-lite-260428",
  [string]$Python = "",
  [switch]$OpenReport
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

function Resolve-Python {
  param([string]$Requested)
  if ($Requested -and (Test-Path $Requested)) {
    return (Resolve-Path $Requested).Path
  }
  if ($env:PYTHON -and (Test-Path $env:PYTHON)) {
    return (Resolve-Path $env:PYTHON).Path
  }
  $bundled = Join-Path $HOME ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
  if (Test-Path $bundled) {
    return (Resolve-Path $bundled).Path
  }
  return "python"
}

if (-not $env:ARK_API_KEY) {
  throw "Missing ARK_API_KEY. Please run: `$env:ARK_API_KEY='your_ark_key'"
}

$sourcePath = Resolve-Path $SourceJson
$pythonExe = Resolve-Python $Python

if (-not $OutDir) {
  $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
  $OutDir = Join-Path "outputs\visual_transcription_v0.1" "question_image_asset_flow_$stamp"
}
$outPath = New-Item -ItemType Directory -Force -Path $OutDir
$resolvedSourcePath = Join-Path $outPath.FullName "source.resolved.json"
$preparedPath = Join-Path $outPath.FullName "prepared.json"
$assetBundlePath = Join-Path $outPath.FullName "asset_bundle"

$sourcePayload = Get-Content -LiteralPath $sourcePath -Raw -Encoding UTF8 | ConvertFrom-Json
$sourceParent = Split-Path -Parent $sourcePath
foreach ($question in $sourcePayload.questions) {
  foreach ($field in @("question_image", "stem_image", "analysis_image")) {
    $rawValue = [string]$question.$field
    if (-not $rawValue) {
      continue
    }
    if ([System.IO.Path]::IsPathRooted($rawValue)) {
      continue
    }
    $repoCandidate = Join-Path $repoRoot $rawValue
    $sourceCandidate = Join-Path $sourceParent $rawValue
    if (Test-Path $repoCandidate) {
      $question.$field = (Resolve-Path $repoCandidate).Path
    } elseif (Test-Path $sourceCandidate) {
      $question.$field = (Resolve-Path $sourceCandidate).Path
    } else {
      $question.$field = $repoCandidate
    }
  }
}
$sourcePayload | ConvertTo-Json -Depth 50 | Set-Content -LiteralPath $resolvedSourcePath -Encoding UTF8

Write-Host "Project root: $repoRoot"
Write-Host "Source JSON:  $sourcePath"
Write-Host "Resolved JSON: $resolvedSourcePath"
Write-Host "Output dir:   $($outPath.FullName)"
Write-Host "Model:        $Model"

& $pythonExe "tools\prepare_option_visual_source.py" `
  --source-json $resolvedSourcePath `
  --out-json $preparedPath `
  --model $Model `
  --require-vision-figure-model `
  --disable-heuristic-figure-fallback

$assetArgs = @(
  "tools\assetize_question_images.py",
  "--source-json", $preparedPath,
  "--out-dir", $assetBundlePath,
  "--include-debug-paths"
)
if ($VisualResults) {
  $visualResultsPath = Resolve-Path $VisualResults
  $assetArgs += @("--visual-results", $visualResultsPath)
}
& $pythonExe @assetArgs

$htmlPath = Join-Path $assetBundlePath "question_asset_review.html"
$manifestPath = Join-Path $assetBundlePath "question_asset_manifest_v0.1.json"

Write-Host ""
Write-Host "Done."
Write-Host "Review HTML: $htmlPath"
Write-Host "Manifest:    $manifestPath"

if ($OpenReport) {
  Start-Process $htmlPath
}
