param(
    [Parameter(Mandatory = $true)]
    [string]$OutDir,

    [Parameter(Mandatory = $true)]
    [string]$AuthToken,

    [string]$Model = "doubao-seed-2-0-lite-260428",
    [string]$Endpoint = "https://ark.cn-beijing.volces.com/api/v3/chat/completions",
    [string]$Prompt = "Reply with OK only."
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Mask-Token {
    param([string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) {
        return ""
    }
    if ($Value.Length -le 12) {
        return ("*" * $Value.Length)
    }
    return "{0}...{1}" -f $Value.Substring(0, 6), $Value.Substring($Value.Length - 4)
}

function Read-ErrorBody {
    param($Exception)
    try {
        if ($null -ne $Exception.Response) {
            $stream = $Exception.Response.GetResponseStream()
            if ($null -ne $stream) {
                $reader = New-Object System.IO.StreamReader($stream)
                return $reader.ReadToEnd()
            }
        }
    } catch {
    }
    return $Exception.Message
}

function Escape-Html {
    param([string]$Text)
    if ($null -eq $Text) {
        return ""
    }
    return [System.Net.WebUtility]::HtmlEncode($Text)
}

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$requestBody = @{
    model = $Model
    messages = @(
        @{
            role = "user"
            content = $Prompt
        }
    )
    temperature = 0
    max_tokens = 8
} | ConvertTo-Json -Depth 6

$headers = @{
    "Authorization" = "Bearer $AuthToken"
    "Content-Type" = "application/json"
}

$result = [ordered]@{
    probe_time = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
    endpoint = $Endpoint
    model = $Model
    auth_token_masked = Mask-Token $AuthToken
    request_body = ($requestBody | ConvertFrom-Json)
    http_status = $null
    success = $false
    duration_ms = $null
    response_headers = @{}
    response_body_text = ""
    response_body_json = $null
    error_message = $null
}

$sw = [System.Diagnostics.Stopwatch]::StartNew()
try {
    $response = Invoke-WebRequest -Method Post -Uri $Endpoint -Headers $headers -Body $requestBody -TimeoutSec 60
    $sw.Stop()
    $result.http_status = [int]$response.StatusCode
    $result.success = $true
    $result.duration_ms = [int]$sw.ElapsedMilliseconds
    foreach ($key in $response.Headers.Keys) {
        $result.response_headers[$key] = [string]$response.Headers[$key]
    }
    $result.response_body_text = [string]$response.Content
    try {
        $result.response_body_json = $response.Content | ConvertFrom-Json -Depth 20
    } catch {
        $result.response_body_json = $null
    }
} catch {
    $sw.Stop()
    $body = Read-ErrorBody $_.Exception
    $statusCode = $null
    try {
        if ($null -ne $_.Exception.Response -and $null -ne $_.Exception.Response.StatusCode) {
            $statusCode = [int]$_.Exception.Response.StatusCode
        }
    } catch {
    }
    $result.http_status = $statusCode
    $result.success = $false
    $result.duration_ms = [int]$sw.ElapsedMilliseconds
    $result.response_body_text = $body
    $result.error_message = $_.Exception.Message
    try {
        $result.response_body_json = $body | ConvertFrom-Json -Depth 20
    } catch {
        $result.response_body_json = $null
    }
}

$jsonPath = Join-Path $OutDir "ark_auth_probe.json"
$htmlPath = Join-Path $OutDir "ark_auth_probe.html"

$result | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $jsonPath -Encoding UTF8

$prettyBody = if ($result.response_body_json) {
    ($result.response_body_json | ConvertTo-Json -Depth 20)
} else {
    [string]$result.response_body_text
}

$prettyRequest = $result.request_body | ConvertTo-Json -Depth 10
$html = @"
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>Ark Auth Probe</title>
  <style>
    body { font-family: "Microsoft YaHei", sans-serif; margin: 24px; color: #222; }
    h1 { margin: 0 0 16px; }
    .ok { color: #137333; font-weight: 700; }
    .bad { color: #c5221f; font-weight: 700; }
    .card { border: 1px solid #ddd; border-radius: 12px; padding: 16px; margin: 16px 0; }
    .grid { display: grid; grid-template-columns: 220px 1fr; gap: 10px 14px; }
    .k { color: #666; }
    pre { white-space: pre-wrap; word-break: break-word; background: #fafafa; border: 1px solid #eee; border-radius: 8px; padding: 12px; }
  </style>
</head>
<body>
  <h1>Ark 最小原始请求探针</h1>
  <div class="card">
    <div class="grid">
      <div class="k">探针时间</div><div>$(Escape-Html $result.probe_time)</div>
      <div class="k">请求地址</div><div>$(Escape-Html $result.endpoint)</div>
      <div class="k">模型</div><div>$(Escape-Html $result.model)</div>
      <div class="k">认证串（脱敏）</div><div>$(Escape-Html $result.auth_token_masked)</div>
      <div class="k">HTTP 状态</div><div>$(Escape-Html ([string]$result.http_status))</div>
      <div class="k">是否成功</div><div class="$(if ($result.success) { "ok" } else { "bad" })">$(if ($result.success) { "成功" } else { "失败" })</div>
      <div class="k">耗时</div><div>$(Escape-Html ([string]$result.duration_ms)) ms</div>
      <div class="k">错误信息</div><div>$(Escape-Html ([string]$result.error_message))</div>
    </div>
  </div>
  <div class="card">
    <h2>请求体</h2>
    <pre>$(Escape-Html $prettyRequest)</pre>
  </div>
  <div class="card">
    <h2>返回体</h2>
    <pre>$(Escape-Html $prettyBody)</pre>
  </div>
</body>
</html>
"@

Set-Content -LiteralPath $htmlPath -Value $html -Encoding UTF8

Write-Output "JSON=$jsonPath"
Write-Output "HTML=$htmlPath"
