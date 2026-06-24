<#
用途：
- 启动工作台预览所需的本地演示栈和配套辅助进程。
- 启动顺序、端口设置和进程记录有意集中在一个地方。
#>

param(
  [switch]$OpenBrowser,
  [string]$NgrokAuthtoken = ""
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$python = "C:\Users\EDY\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$node = "C:\Users\EDY\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe"
$apiScript = Join-Path $root "tools\mock_workbench_api_server.mjs"
$buildScript = Join-Path $root "tools\build_mock_workbench_data.mjs"
$runtimeYaml = Join-Path $root "config\runtime_observability.yaml"
$localSecretsPath = Join-Path $root "config\runtime_secrets.local.json"
$ngrokConfig = Join-Path $root "config\ngrok.demo.yml"
$logDir = Join-Path $root "outputs\split_builder\mock_workbench\logs"
$frontLog = Join-Path $logDir "mock_workbench_frontend.out.log"
$frontErr = Join-Path $logDir "mock_workbench_frontend.err.log"
$apiLog = Join-Path $logDir "mock_workbench_api.out.log"
$apiErr = Join-Path $logDir "mock_workbench_api.err.log"
$ngrokLog = Join-Path $logDir "ngrok.out.log"
$ngrokErr = Join-Path $logDir "ngrok.err.log"
$workbenchUrl = "http://127.0.0.1:8787/outputs/split_builder/mock_workbench/index.html"
$exportApiUrl = "http://127.0.0.1:8790"
$ngrokApiUrl = "http://127.0.0.1:4040/api/tunnels"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Get-PortProcess {
  param([int]$Port)
  Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
    Select-Object -First 1
}

function Test-PortOpen {
  param([int]$Port)
  try {
    $result = Test-NetConnection -ComputerName 127.0.0.1 -Port $Port -WarningAction SilentlyContinue
    return [bool]$result.TcpTestSucceeded
  } catch {
    return $false
  }
}

function Start-BackgroundProcess {
  param(
    [string]$FilePath,
    [string[]]$ArgumentList,
    [string]$WorkingDirectory,
    [string]$StdOutPath,
    [string]$StdErrPath
  )

  $argString = [string]::Join(" ", ($ArgumentList | ForEach-Object {
    if ($_ -match '\s') {
      '"' + ($_.Replace('"', '\"')) + '"'
    } else {
      $_
    }
  }))
  $cmdArgs = "/c start `"`" /b `"$FilePath`" $argString"
  Start-Process -FilePath "cmd.exe" -ArgumentList $cmdArgs -WorkingDirectory $WorkingDirectory | Out-Null
}

function Ensure-FrontendServer {
  if (Test-PortOpen -Port 8787) {
    $existing = Get-PortProcess -Port 8787
    return @{
      status = "running"
      process = "python_http_server"
      pid = if ($existing) { $existing.OwningProcess } else { "" }
    }
  }

  Start-BackgroundProcess `
    -FilePath $python `
    -ArgumentList @("-m", "http.server", "8787", "--bind", "127.0.0.1", "--directory", $root) `
    -WorkingDirectory $root `
    -StdOutPath $frontLog `
    -StdErrPath $frontErr | Out-Null

  Start-Sleep -Seconds 2
  if (-not (Test-PortOpen -Port 8787)) {
    throw "Frontend server failed to start."
  }
  $started = Get-PortProcess -Port 8787

  return @{
    status = "running"
    process = "python_http_server"
    pid = if ($started) { $started.OwningProcess } else { "" }
  }
}

function Ensure-ExportApi {
  if (Test-PortOpen -Port 8790) {
    $existing = Get-PortProcess -Port 8790
    return @{
      status = "running"
      process = "node_api_server"
      pid = if ($existing) { $existing.OwningProcess } else { "" }
    }
  }

  Start-BackgroundProcess `
    -FilePath $node `
    -ArgumentList @($apiScript) `
    -WorkingDirectory $root `
    -StdOutPath $apiLog `
    -StdErrPath $apiErr | Out-Null

  Start-Sleep -Seconds 2
  if (-not (Test-PortOpen -Port 8790)) {
    throw "Export API failed to start."
  }
  $started = Get-PortProcess -Port 8790

  return @{
    status = "running"
    process = "node_api_server"
    pid = if ($started) { $started.OwningProcess } else { "" }
  }
}

function Find-NgrokExe {
  $cmd = Get-Command ngrok -ErrorAction SilentlyContinue
  if ($cmd) {
    return $cmd.Source
  }

  $candidates = @(
    (Join-Path $root "tools\vendor\ngrok.exe"),
    "C:\Users\EDY\AppData\Local\Microsoft\WinGet\Packages\Ngrok.Ngrok_Microsoft.Winget.Source_8wekyb3d8bbwe\ngrok.exe",
    "C:\Users\EDY\ngrok.exe",
    "C:\Users\EDY\Downloads\ngrok.exe",
    "C:\Users\EDY\Desktop\ngrok.exe",
    "C:\Program Files\ngrok\ngrok.exe",
    "C:\Program Files (x86)\ngrok\ngrok.exe"
  )

  foreach ($candidate in $candidates) {
    if (Test-Path $candidate) {
      return $candidate
    }
  }

  return ""
}

function Get-NgrokToken {
  param([string]$ManualToken)

  if ($ManualToken) {
    return $ManualToken
  }

  if ($env:NGROK_AUTHTOKEN) {
    return $env:NGROK_AUTHTOKEN
  }

  if (Test-Path $localSecretsPath) {
    try {
      $secret = Get-Content -Path $localSecretsPath -Raw | ConvertFrom-Json
      if ($secret.ngrok_authtoken) {
        return [string]$secret.ngrok_authtoken
      }
    } catch {
    }
  }

  return ""
}

function Start-NgrokIfReady {
  param(
    [string]$NgrokExe,
    [string]$Token
  )

  $state = @{
    enabled = $false
    status = "disabled"
    publicUrl = ""
    exportProxyUrl = ""
  }

  if (-not $NgrokExe) {
    $state.status = "binary_missing"
    return $state
  }

  if ([string]::IsNullOrWhiteSpace($Token)) {
    $state.status = "waiting_for_authtoken"
    return $state
  }

  $existingApi = Get-PortProcess -Port 4040
  if (-not $existingApi) {
    $args = @(
      "start",
      "--all",
      "--config", $ngrokConfig,
      "--log", $ngrokLog,
      "--log-format", "json",
      "--authtoken", $Token
    )

    Start-BackgroundProcess `
      -FilePath $NgrokExe `
      -ArgumentList $args `
      -WorkingDirectory $root `
      -StdOutPath $ngrokLog `
      -StdErrPath $ngrokErr | Out-Null
  }

  $tunnels = $null
  for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Milliseconds 800
    try {
      $response = Invoke-RestMethod -Uri $ngrokApiUrl -TimeoutSec 3
      if ($response.tunnels) {
        $tunnels = $response.tunnels
        break
      }
    } catch {
    }
  }

  if (-not $tunnels) {
    $state.status = "failed_to_start"
    return $state
  }

  $workbenchTunnel = $tunnels | Where-Object {
    $_.config.addr -eq "http://localhost:8787" -or
    $_.config.addr -eq "8787" -or
    $_.config.addr -eq "http://127.0.0.1:8787"
  } | Select-Object -First 1

  $exportTunnel = $tunnels | Where-Object {
    $_.config.addr -eq "http://localhost:8790" -or
    $_.config.addr -eq "8790" -or
    $_.config.addr -eq "http://127.0.0.1:8790"
  } | Select-Object -First 1

  $state.enabled = $true
  $state.status = "running"
  $state.publicUrl = if ($workbenchTunnel) { $workbenchTunnel.public_url } else { "" }
  $state.exportProxyUrl = if ($exportTunnel) { $exportTunnel.public_url } else { "" }
  return $state
}

function Write-RuntimeYaml {
  param(
    [string]$NgrokExe,
    [hashtable]$FrontendInfo,
    [hashtable]$ExportInfo,
    [hashtable]$NgrokState
  )

  $binaryPath = ($NgrokExe -replace "\\", "/")
  $configPath = "config/ngrok.demo.yml"
  $secretPath = "config/runtime_secrets.local.json"
  $ngrokEnabled = if ($NgrokState.enabled) { "true" } else { "false" }
  $ngrokStatus = $NgrokState.status
  $ngrokPublicUrl = $NgrokState.publicUrl
  $exportPublicUrl = $NgrokState.exportProxyUrl
  $exportProxyEnabled = if ($exportPublicUrl) { "true" } else { "false" }
  $exportProxyStatus = if ($exportPublicUrl) { "running" } else { "disabled" }

  $yaml = @"
meta:
  owner: "题目工厂 Demo"
  environment: "local-demo"
  season_scope: "暑假标准讲义"
  notes: "模型、服务、隧道与启动脚本统一在这里观测。"

paths:
  workspace_root: "C:/Users/EDY/Documents/教研基建"
  knowledge_map_junior: "outputs/junior_math_knowledge_map"
  knowledge_map_senior: "outputs/senior_math_knowledge_map"
  split_outputs: "outputs/ingress_splitter_v0.1"
  placement_outputs: "outputs/placement_trials"
  export_runs: "outputs/split_builder/mock_workbench/export_runs"

services:
  mock_workbench:
    label: "讲义工作台前端"
    local_url: "$workbenchUrl"
    port: 8787
    status: "$($FrontendInfo.status)"
    process: "$($FrontendInfo.process)"
  export_api:
    label: "导出服务"
    local_url: "$exportApiUrl"
    health_path: "/health"
    port: 8790
    status: "$($ExportInfo.status)"
    process: "$($ExportInfo.process)"
  stack_launcher:
    label: "一键启动"
    script_path: "tools/start_demo_stack.ps1"
    stop_script_path: "tools/stop_demo_stack.ps1"
    mode: "one_click"

models:
  placement:
    provider: "volcengine_ark"
    endpoint: "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
    primary_model: "doubao-seed-2-0-pro-260215"
    api_key_env: "ARK_API_KEY"
    fallback_mode: "visual_split_then_text_only_placement"
    current_result_dir: "outputs/placement_trials/junior_g7_12_003_final_node"

tunnels:
  ngrok:
    enabled: $ngrokEnabled
    binary_path: "$binaryPath"
    config_path: "$configPath"
    auth_token_source: "$secretPath"
    auth_token_env: "NGROK_AUTHTOKEN"
    status: "$ngrokStatus"
    public_url: "$ngrokPublicUrl"
    local_target: "$workbenchUrl"
    api_url: "$ngrokApiUrl"
    notes: "本地 secrets 文件或环境变量就绪后可一键拉起对外入口。"
  export_api_proxy:
    enabled: $exportProxyEnabled
    status: "$exportProxyStatus"
    public_url: "$exportPublicUrl"
    local_target: "$exportApiUrl"

startup:
  launcher_script: "tools/start_demo_stack.ps1"
  stop_script: "tools/stop_demo_stack.ps1"
  rebuild_data_script: "tools/build_mock_workbench_data.mjs"
  browser_entry: "$workbenchUrl"

ops:
  visual_split_mode: "model_reading_first"
  placement_mode: "doubao_layered_lesson_routing"
  export_bundle: "docx_pdf_pptx"
  review_flow: "visual_gate_then_teacher_review"
"@

  Set-Content -Path $runtimeYaml -Value $yaml -Encoding UTF8
}

$frontendInfo = Ensure-FrontendServer
$exportInfo = Ensure-ExportApi
$ngrokExe = Find-NgrokExe
$token = Get-NgrokToken -ManualToken $NgrokAuthtoken
$ngrokState = Start-NgrokIfReady -NgrokExe $ngrokExe -Token $token

Write-RuntimeYaml -NgrokExe $ngrokExe -FrontendInfo $frontendInfo -ExportInfo $exportInfo -NgrokState $ngrokState

& $node $buildScript | Out-Null

$summary = [ordered]@{
  local_workbench = $workbenchUrl
  local_export_api = $exportApiUrl
  ngrok_status = $ngrokState.status
  ngrok_workbench = $ngrokState.publicUrl
  ngrok_export_api = $ngrokState.exportProxyUrl
  runtime_yaml = $runtimeYaml
  launcher = (Join-Path $root "tools\start_demo_stack.ps1")
}

if ($OpenBrowser) {
  Start-Process $workbenchUrl | Out-Null
}

$summary | ConvertTo-Json
