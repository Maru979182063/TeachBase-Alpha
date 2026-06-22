$ErrorActionPreference = "Stop"

$port = 8792
$existing = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
if ($existing) {
  Stop-Process -Id $existing.OwningProcess -Force
  Write-Output "runtime_backbone_api stopped on port $port"
} else {
  Write-Output "runtime_backbone_api not running on port $port"
}
