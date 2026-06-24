/**
 * 用途：
 * - 把领导演示素材打包到可分发目录，并修补本地 URL。
 * - 演示需要脱离开发工作区结构运行时使用这个文件。
 */

import fs from "node:fs";
import fsp from "node:fs/promises";
import path from "node:path";
import vm from "node:vm";

const workspaceRoot = path.resolve("C:/Users/EDY/Documents/教研基建");
const sourceDir = path.join(workspaceRoot, "outputs", "split_builder", "mock_workbench");
const targetBaseDir = path.join(workspaceRoot, "outputs", "external_demos");
const stamp = new Date().toISOString().slice(0, 10).replace(/-/g, "");
const bundleName = `leader_workbench_demo_${stamp}`;
const targetDir = path.join(targetBaseDir, bundleName);
const assetsDir = path.join(targetDir, "assets");
const cropDir = path.join(assetsDir, "question_crops");
const exportDir = path.join(assetsDir, "export_runs");
const zipPath = path.join(targetBaseDir, `${bundleName}.zip`);

function ensureDir(dir) {
  fs.mkdirSync(dir, { recursive: true });
}

function safeName(text) {
  return String(text || "")
    .replace(/[\\/:*?"<>|]+/g, "_")
    .replace(/\s+/g, "_");
}

function writeText(filePath, text) {
  ensureDir(path.dirname(filePath));
  fs.writeFileSync(filePath, text, "utf8");
}

function copyFileSafe(fromPath, toPath) {
  if (!fromPath || !fs.existsSync(fromPath)) return false;
  ensureDir(path.dirname(toPath));
  fs.copyFileSync(fromPath, toPath);
  return true;
}

function loadWindowAssignment(jsPath, globalKey) {
  const code = fs.readFileSync(jsPath, "utf8");
  const sandbox = { window: {} };
  vm.runInNewContext(code, sandbox, { filename: jsPath });
  return sandbox.window[globalKey];
}

function readJsonFile(filePath) {
  const raw = fs.readFileSync(filePath, "utf8").replace(/^\uFEFF/, "");
  return JSON.parse(raw);
}

function toPosixRelative(fromDir, targetPath) {
  return path.relative(fromDir, targetPath).replace(/\\/g, "/");
}

function patchFileUrl(source) {
  const before = `  function fileUrl(windowsPath) {\n    if (!windowsPath) return \"\";\n    const raw = String(windowsPath);\n    if (raw.startsWith(workspaceRoot)) {\n      const relative = raw.slice(workspaceRoot.length).replace(/\\\\/g, \"/\");\n      return encodeURI(\`/\${relative}\`);\n    }\n    const normalized = raw.replace(/\\\\/g, \"/\");\n    return encodeURI(\`file:///\${normalized}\`);\n  }`;
  const after = `  function fileUrl(windowsPath) {\n    if (!windowsPath) return \"\";\n    const raw = String(windowsPath);\n    if (/^(?:\\.?\\/|assets\\/)/.test(raw)) {\n      return encodeURI(raw.replace(/\\\\/g, \"/\"));\n    }\n    if (raw.startsWith(workspaceRoot)) {\n      const relative = raw.slice(workspaceRoot.length).replace(/\\\\/g, \"/\");\n      return encodeURI(\`/\${relative}\`);\n    }\n    const normalized = raw.replace(/\\\\/g, \"/\");\n    return encodeURI(\`file:///\${normalized}\`);\n  }`;
  return source.replace(before, after);
}

function buildDemoShim() {
  return `window.LEADER_DEMO_MODE = true;
(function () {
  const apiPrefix = "http://127.0.0.1:8790";
  const historyPayload = window.DEMO_EXPORT_HISTORY || { items: [] };
  const responseHeaders = { "Content-Type": "application/json; charset=utf-8" };
  const originalFetch = window.fetch ? window.fetch.bind(window) : null;

  function jsonResponse(body, status) {
    return Promise.resolve(new Response(JSON.stringify(body), {
      status: status || 200,
      headers: responseHeaders,
    }));
  }

  function latestItem() {
    return (historyPayload.items || [])[0] || null;
  }

  window.fetch = function (input, init) {
    const url = typeof input === "string" ? input : (input && input.url) || "";

    if (url.indexOf(apiPrefix + "/health") === 0) {
      return jsonResponse({ ok: false, demo: true, mode: "leader_demo" }, 200);
    }

    if (url.indexOf(apiPrefix + "/api/export/history") === 0) {
      return jsonResponse(historyPayload, 200);
    }

    if (url.indexOf(apiPrefix + "/api/export/generate") === 0) {
      const item = latestItem();
      if (item) return jsonResponse({ ok: true, item: item, demo: true }, 200);
      return jsonResponse({ ok: false, error: "demo_history_empty" }, 503);
    }

    if (originalFetch) return originalFetch(input, init);
    return Promise.reject(new Error("fetch_unavailable_in_demo"));
  };
})();`;
}

function buildReadme(bundleFolderName) {
  return `题目工厂演示版（外化包）

这是一份独立的演示包，不依赖主项目运行。

使用方式：
1. 直接双击“打开演示版.bat”
2. 或双击“启动本地演示版.bat”
3. 或直接打开“index.html”

说明：
- 当前为演示模式，页面交互可用
- 题图、知识树、审核台、讲义工作台、导出记录均可查看
- “生成导出文件”会回放最近一次真实样例结果，用于演示流程，不会写入主项目

目录：
- index.html：演示首页
- assets/question_crops：题目切图
- assets/export_runs：样例导出文件
- demo_export_history.js：演示导出记录

打包目录：${bundleFolderName}
生成时间：${new Date().toLocaleString("zh-CN", { hour12: false })}
`;
}

function buildOpenBat() {
  return `@echo off
cd /d "%~dp0"
start "" "%~dp0index.html"
`;
}

function buildLocalServerBat() {
  return `@echo off
setlocal
cd /d "%~dp0"
PowerShell -ExecutionPolicy Bypass -File "%~dp0启动本地演示版.ps1"
`;
}

function buildLocalServerPs1() {
  return `$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$port = 8899
$prefix = "http://127.0.0.1:$port/"
$indexUrl = "${"$"}prefix" + "index.html"

Add-Type -AssemblyName System.Web

try {
  Start-Process $indexUrl | Out-Null
} catch {}

$listener = New-Object System.Net.HttpListener
$listener.Prefixes.Add($prefix)
$listener.Start()

Write-Host "Leader demo serving at $indexUrl"
Write-Host "Close this window to stop the local demo server."

function Get-ContentType([string]$path) {
  switch ([System.IO.Path]::GetExtension($path).ToLowerInvariant()) {
    ".html" { "text/html; charset=utf-8" }
    ".js" { "application/javascript; charset=utf-8" }
    ".css" { "text/css; charset=utf-8" }
    ".json" { "application/json; charset=utf-8" }
    ".png" { "image/png" }
    ".jpg" { "image/jpeg" }
    ".jpeg" { "image/jpeg" }
    ".gif" { "image/gif" }
    ".svg" { "image/svg+xml" }
    ".pdf" { "application/pdf" }
    ".docx" { "application/vnd.openxmlformats-officedocument.wordprocessingml.document" }
    ".pptx" { "application/vnd.openxmlformats-officedocument.presentationml.presentation" }
    ".txt" { "text/plain; charset=utf-8" }
    ".bat" { "text/plain; charset=utf-8" }
    ".ps1" { "text/plain; charset=utf-8" }
    default { "application/octet-stream" }
  }
}

while ($listener.IsListening) {
  try {
    $context = $listener.GetContext()
    $requestPath = [System.Web.HttpUtility]::UrlDecode($context.Request.Url.AbsolutePath.TrimStart('/'))
    if ([string]::IsNullOrWhiteSpace($requestPath)) { $requestPath = "index.html" }
    $filePath = Join-Path $root $requestPath
    $fullRoot = [System.IO.Path]::GetFullPath($root)
    $fullFile = [System.IO.Path]::GetFullPath($filePath)

    if (-not $fullFile.StartsWith($fullRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
      $context.Response.StatusCode = 403
      $context.Response.Close()
      continue
    }

    if (-not (Test-Path -LiteralPath $fullFile -PathType Leaf)) {
      $context.Response.StatusCode = 404
      $bytes = [System.Text.Encoding]::UTF8.GetBytes("Not Found")
      $context.Response.OutputStream.Write($bytes, 0, $bytes.Length)
      $context.Response.Close()
      continue
    }

    $bytes = [System.IO.File]::ReadAllBytes($fullFile)
    $context.Response.ContentType = Get-ContentType $fullFile
    $context.Response.ContentLength64 = $bytes.Length
    $context.Response.OutputStream.Write($bytes, 0, $bytes.Length)
    $context.Response.OutputStream.Close()
    $context.Response.Close()
  } catch {
    try { $context.Response.StatusCode = 500; $context.Response.Close() } catch {}
  }
}
`;
}

async function main() {
  ensureDir(targetBaseDir);
  fs.rmSync(targetDir, { recursive: true, force: true });
  ensureDir(targetDir);
  ensureDir(cropDir);
  ensureDir(exportDir);

  const indexPath = path.join(sourceDir, "index.html");
  const appPath = path.join(sourceDir, "workbench_app.js");
  const dataPath = path.join(sourceDir, "workbench_data.js");
  const exportHistoryPath = path.join(sourceDir, "export_runs", "export_history.json");

  const workbenchData = loadWindowAssignment(dataPath, "WORKBENCH_DATA");
  const cropCopies = new Map();

  for (const [lessonId, lesson] of Object.entries(workbenchData.splitLessons || {})) {
    for (const question of lesson.questions || []) {
      if (!question.cropPath) continue;
      const absPath = question.cropPath;
      if (!fs.existsSync(absPath)) continue;
      const fileName = `${lessonId}__${safeName(path.basename(absPath))}`;
      const destPath = path.join(cropDir, fileName);
      if (!cropCopies.has(absPath)) {
        copyFileSafe(absPath, destPath);
        cropCopies.set(absPath, destPath);
      }
      question.cropPath = `./${toPosixRelative(targetDir, destPath)}`;
    }
  }

  writeText(path.join(targetDir, "workbench_data.js"), `window.WORKBENCH_DATA = ${JSON.stringify(workbenchData, null, 2)};\n`);

  const historyItems = fs.existsSync(exportHistoryPath)
    ? readJsonFile(exportHistoryPath)
    : [];

  const demoHistory = historyItems.slice(0, 6).map((item) => {
    const runFolder = path.join(exportDir, item.id);
    ensureDir(runFolder);

    const files = (item.files || []).map((file) => {
      const sourceFile = file.path;
      const destFile = path.join(runFolder, safeName(path.basename(sourceFile)));
      copyFileSafe(sourceFile, destFile);
      const localRelative = `./${toPosixRelative(targetDir, destFile)}`;
      return {
        ...file,
        path: localRelative,
        relativePath: localRelative,
      };
    });

    return {
      ...item,
      outputDir: `./${toPosixRelative(targetDir, runFolder)}`,
      outputRelativeDir: `./${toPosixRelative(targetDir, runFolder)}`,
      files,
    };
  });

  writeText(path.join(targetDir, "demo_export_history.js"), `window.DEMO_EXPORT_HISTORY = ${JSON.stringify({ items: demoHistory }, null, 2)};\n`);

  let appSource = fs.readFileSync(appPath, "utf8");
  appSource = patchFileUrl(appSource);
  writeText(path.join(targetDir, "workbench_app.js"), appSource);

  let indexSource = fs.readFileSync(indexPath, "utf8");
  indexSource = indexSource.replace(
    `<script src="./workbench_data.js?v=20260618e"></script>\n  <script src="./workbench_app.js?v=20260618e"></script>`,
    `<script src="./workbench_data.js?v=leaderdemo"></script>\n  <script src="./demo_export_history.js?v=leaderdemo"></script>\n  <script>${buildDemoShim()}</script>\n  <script src="./workbench_app.js?v=leaderdemo"></script>`,
  );
  writeText(path.join(targetDir, "index.html"), indexSource);

  writeText(path.join(targetDir, "README_演示版.txt"), buildReadme(bundleName));
  writeText(path.join(targetDir, "打开演示版.bat"), buildOpenBat());
  writeText(path.join(targetDir, "启动本地演示版.bat"), buildLocalServerBat());
  writeText(path.join(targetDir, "启动本地演示版.ps1"), buildLocalServerPs1());

  const psCommand = `Compress-Archive -Path '${targetDir}' -DestinationPath '${zipPath}' -Force`;
  const { spawnSync } = await import("node:child_process");
  spawnSync("powershell", ["-NoProfile", "-Command", psCommand], { stdio: "inherit" });

  console.log(JSON.stringify({
    ok: true,
    bundleName,
    targetDir,
    zipPath,
    cropCount: cropCopies.size,
    exportRunCount: demoHistory.length,
  }, null, 2));
}

await main();
