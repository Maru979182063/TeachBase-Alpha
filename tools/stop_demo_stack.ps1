<#
Purpose:
- Stops the local demo stack processes started by the companion launcher script.
- Cleanup rules live here so operators do not need to hunt for stray processes by hand.
#>

$ErrorActionPreference = "SilentlyContinue"

$targets = @(
  @{
    port = 4040
    label = "ngrok"
  },
  @{
    port = 8790
    label = "export_api"
  },
  @{
    port = 8787
    label = "mock_workbench"
  }
)

$stopped = @()

foreach ($target in $targets) {
  $conn = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $target.port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($conn) {
    Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
    $stopped += [ordered]@{
      service = $target.label
      port = $target.port
      pid = $conn.OwningProcess
      status = "stopped"
    }
  } else {
    $stopped += [ordered]@{
      service = $target.label
      port = $target.port
      pid = $null
      status = "not_running"
    }
  }
}

$stopped | ConvertTo-Json
