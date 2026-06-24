<#
用途：
- 在受控本地 shell 中启动运行时主干 API 或演示进程。
- 使用配套停止脚本清理这个启动器拉起的进程。
#>

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $root "outputs\runtime_backbone_demo\logs"
$outLog = Join-Path $logDir "runtime_backbone_api.out.log"
$errLog = Join-Path $logDir "runtime_backbone_api.err.log"
$port = 8792

New-Item -ItemType Directory -Force $logDir | Out-Null

$existing = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
if ($existing) {
  Stop-Process -Id $existing.OwningProcess -Force
  Start-Sleep -Milliseconds 300
}

Start-Process node `
  -ArgumentList "tools/runtime_backbone_api_server.mjs" `
  -WorkingDirectory $root `
  -WindowStyle Hidden `
  -RedirectStandardOutput $outLog `
  -RedirectStandardError $errLog

Start-Sleep -Seconds 2
Write-Output "runtime_backbone_api started: http://127.0.0.1:$port/health"
