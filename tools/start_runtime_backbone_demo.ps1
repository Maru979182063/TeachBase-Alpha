<#
用途：
- 保留旧脚本名，但把默认启动目标切到唯一正式入口 8790。
- 8792 只保留兼容代理用途，不再由默认脚本拉起。
#>

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$startScript = Join-Path $root "tools\start_mock_workbench_runtime.ps1"

Write-Warning "8792 已降级为 deprecated compatibility 入口；默认只启动 8790 正式 Runtime API。"
& $startScript
Write-Output "official runtime api started: http://127.0.0.1:8790/health"
