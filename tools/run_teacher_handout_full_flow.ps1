param(
  [Parameter(Mandatory = $true)]
  [string]$Pdf,

  [string]$Profile = "auto",
  [string]$SplitOutName = "",
  [string]$TranscribeOutName = "",
  [string]$Model = "doubao-seed-2-0-lite-260428",
  [string]$ApiKey = "",
  [string]$Python = "",
  [double]$SleepSeconds = 0.3,
  [int]$Limit = 0,
  [int]$MaxPages = 0,
  [switch]$SplitOnly,
  [switch]$PrepareOnly
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptDir
# 允许调用方固定解释器；未指定时使用当前环境中的 Python。
if (-not $Python.Trim()) {
  $pythonCommand = Get-Command python -ErrorAction Stop
  $Python = $pythonCommand.Source
}
$py = (Resolve-Path -LiteralPath $Python).Path
$entry = Join-Path $scriptDir "run_teacher_handout_full_flow.py"

if (-not (Test-Path $py)) {
  throw "Python runtime not found: $py"
}
if (-not (Test-Path $entry)) {
  throw "Entry script not found: $entry"
}

$argsList = @(
  $entry,
  "--pdf", $Pdf,
  "--profile", $Profile,
  "--model", $Model,
  "--sleep-seconds", "$SleepSeconds"
)

if ($SplitOutName) {
  $argsList += @("--split-out-name", $SplitOutName)
}
if ($TranscribeOutName) {
  $argsList += @("--transcribe-out-name", $TranscribeOutName)
}
if ($ApiKey) {
  $argsList += @("--api-key", $ApiKey)
}
if ($Limit -gt 0) {
  $argsList += @("--limit", "$Limit")
}
if ($MaxPages -gt 0) {
  $argsList += @("--max-pages", "$MaxPages")
}
if ($SplitOnly) {
  $argsList += "--split-only"
}
if ($PrepareOnly) {
  $argsList += "--prepare-only"
}

Push-Location $repoRoot
try {
  & $py @argsList
} finally {
  Pop-Location
}
