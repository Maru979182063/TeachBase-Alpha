param(
  [Parameter(Mandatory=$true)][string]$SourceJson,
  [Parameter(Mandatory=$true)][string]$OutDir,
  [string]$TranscriptionResults = "",
  [string]$Model = "doubao-seed-2-0-lite-260428",
  [int]$PlannerConcurrency = 4,
  [int]$FigureConcurrency = 4,
  [int]$TranscriptionConcurrency = 4,
  [int]$ModelTimeout = 120,
  [int]$ModelRetries = 1,
  [string]$Python = "",
  [switch]$SkipTranscriptionRetry,
  [switch]$DisableHeuristicFigureFallback
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$workspace = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
# 优先接受显式解释器，否则使用当前 PATH；不绑定开发机缓存目录。
if (-not $Python.Trim()) {
  $pythonCommand = Get-Command python -ErrorAction Stop
  $Python = $pythonCommand.Source
}
$python = (Resolve-Path -LiteralPath $Python).Path
$sourcePath = (Resolve-Path -LiteralPath $SourceJson).Path
$outPath = [System.IO.Path]::GetFullPath((Join-Path (Get-Location) $OutDir))
$transPath = ""
if ($TranscriptionResults.Trim()) {
  $transPath = (Resolve-Path -LiteralPath $TranscriptionResults).Path
}

if (-not $env:ARK_API_KEY) {
  Write-Host "Missing ARK_API_KEY. Model calls cannot run." -ForegroundColor Red
  Read-Host "Press Enter to close"
  exit 1
}

New-Item -ItemType Directory -Force -Path $outPath | Out-Null
$stdoutLog = Join-Path $outPath "visible_runtime_stdout.log"
$stderrLog = Join-Path $outPath "visible_runtime_stderr.log"
$statePath = Join-Path $outPath "state.json"

$argsList = @(
  "tools\run_question_ingest_skill.py",
  "--source-json", $sourcePath,
  "--out-dir", $outPath,
  "--model", $Model,
  "--planner-concurrency", "$PlannerConcurrency",
  "--figure-concurrency", "$FigureConcurrency",
  "--transcription-concurrency", "$TranscriptionConcurrency",
  "--model-timeout", "$ModelTimeout",
  "--model-retries", "$ModelRetries"
)
if ($transPath) {
  $argsList += @("--transcription-results", $transPath)
}
if ($SkipTranscriptionRetry) {
  $argsList += "--skip-transcription-retry"
}
if ($DisableHeuristicFigureFallback) {
  $argsList += "--disable-heuristic-figure-fallback"
}

Write-Host "Starting visual ingest runtime" -ForegroundColor Cyan
Write-Host "Source: $sourcePath"
Write-Host "OutDir: $outPath"
Write-Host "Model: $Model"
Write-Host "Concurrency: planner=$PlannerConcurrency, figure=$FigureConcurrency, transcription=$TranscriptionConcurrency"
Write-Host ""

$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $python
foreach ($arg in $argsList) { [void]$psi.ArgumentList.Add($arg) }
$psi.WorkingDirectory = $workspace
$psi.UseShellExecute = $false
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
$psi.Environment["PYTHONIOENCODING"] = "utf-8"
$proc = New-Object System.Diagnostics.Process
$proc.StartInfo = $psi
[void]$proc.Start()

$outWriter = [System.IO.StreamWriter]::new($stdoutLog, $false, [System.Text.Encoding]::UTF8)
$errWriter = [System.IO.StreamWriter]::new($stderrLog, $false, [System.Text.Encoding]::UTF8)
$outTask = $proc.StandardOutput.BaseStream.CopyToAsync($outWriter.BaseStream)
$errTask = $proc.StandardError.BaseStream.CopyToAsync($errWriter.BaseStream)

function Count-Files($path, $filter) {
  if (-not (Test-Path -LiteralPath $path)) { return 0 }
  return @(Get-ChildItem -LiteralPath $path -Filter $filter -File -ErrorAction SilentlyContinue).Count
}

function Count-Questions($jsonPath) {
  try {
    $json = Get-Content -LiteralPath $jsonPath -Raw -Encoding UTF8 | ConvertFrom-Json
    return @($json.questions).Count
  } catch { return 0 }
}

$total = Count-Questions $sourcePath
$lastLine = ""
while (-not $proc.HasExited) {
  $state = @{}
  if (Test-Path -LiteralPath $statePath) {
    try { $state = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json } catch {}
  }
  $gateDone = Count-Files (Join-Path $outPath "01_model_image_need_gate\gate") "*.gate.json"
  $preparedDone = Count-Files (Join-Path $outPath "04_figure_detection") "prepared_shard_*.json"
  $candidateSummary = Join-Path $outPath "02_candidate_source\candidate_source.summary.json"
  $candidateCount = "?"
  $noImageCount = "?"
  if (Test-Path -LiteralPath $candidateSummary) {
    try {
      $cs = Get-Content -LiteralPath $candidateSummary -Raw -Encoding UTF8 | ConvertFrom-Json
      $candidateCount = "$($cs.candidate_count)"
      $noImageCount = "$($cs.no_image_count)"
    } catch {}
  }
  $assetManifest = Join-Path $outPath "06_asset_bundle\question_asset_manifest_v0.1.json"
  $assetStatus = if (Test-Path -LiteralPath $assetManifest) { "generated" } else { "not_generated" }
  $statusText = ""
  if ($state -and $state.status) { $statusText = "$($state.status)" }
  $plannerText = ""
  if ($state -and $state.planner) { $plannerText = "$($state.planner)" }
  $line = "$(Get-Date -Format 'HH:mm:ss') | status=$statusText planner=$plannerText gate=$gateDone/$total candidate=$candidateCount no_image=$noImageCount figure_shards=$preparedDone asset=$assetStatus"
  if ($line -ne $lastLine) {
    Write-Host $line
    $lastLine = $line
  }
  Start-Sleep -Seconds 5
}

$proc.WaitForExit()
$outTask.Wait()
$errTask.Wait()
$outWriter.Dispose()
$errWriter.Dispose()

Write-Host ""
Write-Host "Runtime process finished. exit=$($proc.ExitCode)" -ForegroundColor Cyan
Write-Host "stdout: $stdoutLog"
Write-Host "stderr: $stderrLog"
if (Test-Path -LiteralPath (Join-Path $outPath "runtime_summary.json")) {
  Write-Host "summary: $(Join-Path $outPath 'runtime_summary.json')" -ForegroundColor Green
}
if (Test-Path -LiteralPath (Join-Path $outPath "06_asset_bundle\question_asset_review.html")) {
  Write-Host "review html: $(Join-Path $outPath '06_asset_bundle\question_asset_review.html')" -ForegroundColor Green
}
if ($proc.ExitCode -eq 0) {
  $packageDir = Join-Path $outPath "instance_package"
  $zipPath = Join-Path $outPath "instance_package.zip"
  if (Test-Path -LiteralPath $packageDir) { Remove-Item -LiteralPath $packageDir -Recurse -Force }
  if (Test-Path -LiteralPath $zipPath) { Remove-Item -LiteralPath $zipPath -Force }
  New-Item -ItemType Directory -Force -Path $packageDir | Out-Null
  $copyItems = @(
    "runtime_summary.json",
    "state.json",
    "source.abs.json",
    "visible_runtime_stdout.log",
    "visible_runtime_stderr.log",
    "logs",
    "01_model_image_need_gate",
    "02_candidate_source",
    "03_transcription",
    "05_prepared_merged",
    "06_asset_bundle"
  )
  foreach ($item in $copyItems) {
    $src = Join-Path $outPath $item
    if (-not (Test-Path -LiteralPath $src)) { continue }
    $dst = Join-Path $packageDir $item
    if ((Get-Item -LiteralPath $src).PSIsContainer) {
      Copy-Item -LiteralPath $src -Destination $dst -Recurse -Force
    } else {
      Copy-Item -LiteralPath $src -Destination $dst -Force
    }
  }
  Compress-Archive -LiteralPath (Join-Path $packageDir "*") -DestinationPath $zipPath -Force
  Write-Host "instance package dir: $packageDir" -ForegroundColor Green
  Write-Host "instance package zip: $zipPath" -ForegroundColor Green
}
if ($proc.ExitCode -ne 0) {
  Write-Host "Runtime failed. Last stderr lines:" -ForegroundColor Red
  if (Test-Path -LiteralPath $stderrLog) { Get-Content -LiteralPath $stderrLog -Tail 80 -Encoding UTF8 }
}
Read-Host "Press Enter to close"
