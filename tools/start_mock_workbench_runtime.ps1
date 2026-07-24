<#
用途：
- 启动本地 8790 Runtime API，不再依赖写死的用户名目录。
- 优先使用显式环境变量，其次尝试当前用户缓存下的 bundled Node，再回退到 PATH 中的 `node`。
#>

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$preferredNode = if ($env:RUNTIME_BACKBONE_NODE) {
  $env:RUNTIME_BACKBONE_NODE
} elseif ($env:USERPROFILE) {
  Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe"
} else {
  ""
}
$node = if ($preferredNode -and (Test-Path $preferredNode)) {
  $preferredNode
} else {
  (Get-Command node -ErrorAction Stop).Source
}
$server = Join-Path $root "tools\mock_workbench_api_server.mjs"
$logDir = Join-Path $root "outputs\split_builder\mock_workbench\logs"
$outLog = Join-Path $logDir "mock_workbench_api.out.log"
$errLog = Join-Path $logDir "mock_workbench_api.err.log"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$existing = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 8790 -ErrorAction SilentlyContinue
if ($existing) {
  Write-Output "mock_workbench_api is already running on port 8790."
  exit 0
}

Start-Process -FilePath $node -ArgumentList $server -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput $outLog -RedirectStandardError $errLog

Write-Output "mock_workbench_api started."
