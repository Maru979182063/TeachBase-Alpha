<#
Purpose:
- Starts the lightweight mock workbench runtime with the pinned local Node binary.
- This launcher exists so the demo can run predictably on a shared workstation.
#>

$node = "C:\Users\EDY\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe"
$root = "C:\Users\EDY\Documents\教研基建"
$server = Join-Path $root "tools\mock_workbench_api_server.mjs"
$logDir = Join-Path $root "outputs\split_builder\mock_workbench\logs"
$outLog = Join-Path $logDir "mock_workbench_api.out.log"
$errLog = Join-Path $logDir "mock_workbench_api.err.log"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$existing = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 8790 -ErrorAction SilentlyContinue
if ($existing) {
  Write-Output "mock_workbench_api 已在 8790 端口运行。"
  exit 0
}

Start-Process -FilePath $node -ArgumentList $server -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput $outLog -RedirectStandardError $errLog

Write-Output "mock_workbench_api 已启动。"
