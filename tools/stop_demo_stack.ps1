<#
用途：
- 停止配套启动脚本拉起的本地演示栈进程。
- 清理规则集中在这里，操作者不用手动寻找残留进程。
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
