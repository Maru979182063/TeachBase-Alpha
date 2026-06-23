<#
Purpose:
- Stops the runtime backbone demo process started by the companion launcher script.
- Pair this with the start script when running iterative local backend demos.
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
