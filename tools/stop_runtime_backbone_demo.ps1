<#
用途：
- 停止配套启动脚本拉起的运行时主干演示进程。
- 迭代运行本地后端演示时，应和启动脚本配套使用。
#>

$ErrorActionPreference = "Stop"

$port = 8792
$existing = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
if ($existing) {
  Stop-Process -Id $existing.OwningProcess -Force
  Write-Output "runtime_backbone_api stopped on port $port"
} else {
  Write-Output "runtime_backbone_api not running on port $port"
}
