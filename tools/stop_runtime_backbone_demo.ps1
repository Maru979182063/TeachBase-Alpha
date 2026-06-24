<#
用途：
- 保留旧脚本名，但停止唯一正式入口 8790。
- deprecated 的 8792 不再由默认工作流管理。
#>

$ErrorActionPreference = "Stop"

$port = 8790
$existing = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
if ($existing) {
  Stop-Process -Id $existing.OwningProcess -Force
  Write-Output "official runtime api stopped on port $port"
} else {
  Write-Output "official runtime api not running on port $port"
}
