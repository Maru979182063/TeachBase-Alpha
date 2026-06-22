import fs from "node:fs";
import path from "node:path";

const root = path.resolve("outputs/external_demos/leader_workbench_demo_20260618");
const indexPath = path.join(root, "index.html");
const dataPath = path.join(root, "workbench_data.js");
const historyPath = path.join(root, "demo_export_history.js");
const appPath = path.join(root, "workbench_app.js");
const outputPath = path.join(root, "题目工厂_领导汇报单文件版.html");
const asciiOutputPath = path.join(root, "leader_workbench_single_file.html");
const openBatPath = path.join(root, "open_leader_single_file.bat");
const openBatCnPath = path.join(root, "打开领导单文件版.bat");

function readUtf8(filePath) {
  return fs.readFileSync(filePath, "utf8");
}

function escapeScriptEnd(source) {
  return source.replaceAll("</script", "<\\/script");
}

function walkFiles(dir) {
  const out = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...walkFiles(full));
    if (entry.isFile()) out.push(full);
  }
  return out;
}

function mimeFor(filePath) {
  const ext = path.extname(filePath).toLowerCase();
  if (ext === ".png") return "image/png";
  if (ext === ".jpg" || ext === ".jpeg") return "image/jpeg";
  if (ext === ".webp") return "image/webp";
  if (ext === ".gif") return "image/gif";
  return "application/octet-stream";
}

function toPosix(value) {
  return value.split(path.sep).join("/");
}

function buildAssetMap() {
  const assetsRoot = path.join(root, "assets");
  const map = {};
  for (const filePath of walkFiles(assetsRoot)) {
    if (!/\.(png|jpe?g|webp|gif)$/i.test(filePath)) continue;
    const rel = toPosix(path.relative(root, filePath));
    const dataUrl = `data:${mimeFor(filePath)};base64,${fs.readFileSync(filePath).toString("base64")}`;
    map[`./${rel}`] = dataUrl;
    map[rel] = dataUrl;
  }
  return map;
}

function patchAppForSingleFile(appSource) {
  const needle = "    const raw = String(windowsPath);\n";
  const patch = `    const raw = String(windowsPath);\n    if (/^(?:data:|blob:|https?:)/.test(raw)) return raw;\n    if (window.LEADER_DEMO_ASSETS && window.LEADER_DEMO_ASSETS[raw]) return window.LEADER_DEMO_ASSETS[raw];\n    const normalizedRawForDemo = raw.replace(/\\\\/g, "/");\n    if (window.LEADER_DEMO_SINGLE_FILE && normalizedRawForDemo.includes("assets/export_runs/") && /\\.(?:docx|pdf|pptx)$/i.test(normalizedRawForDemo)) {\n      const message = "这是领导汇报单文件版：页面交互和题图资源已内嵌，真实 DOCX/PDF/PPTX 导出文件未塞入 HTML，以免文件过大。请在完整演示包的 assets/export_runs 目录查看原文件。";\n      return "data:text/plain;charset=utf-8," + encodeURIComponent(message);\n    }\n`;
  if (!appSource.includes(needle)) {
    throw new Error("Could not patch fileUrl in workbench_app.js");
  }
  return appSource.replace(needle, patch);
}

const index = readUtf8(indexPath);
const dataSource = readUtf8(dataPath);
const historySource = readUtf8(historyPath);
const appSource = patchAppForSingleFile(readUtf8(appPath));
const assetMap = buildAssetMap();

let html = index
  .replace(/\s*<script src="\.\/workbench_data\.js\?v=leaderdemo"><\/script>/, `\n  <script>\n${escapeScriptEnd(dataSource)}\n  </script>`)
  .replace(/\s*<script src="\.\/demo_export_history\.js\?v=leaderdemo"><\/script>/, `\n  <script>\n${escapeScriptEnd(historySource)}\n  </script>`)
  .replace(/\s*<script src="\.\/workbench_app\.js\?v=leaderdemo"><\/script>/, `\n  <script>\n${escapeScriptEnd(appSource)}\n  </script>`);

const assetScript = `\n  <script>\nwindow.LEADER_DEMO_SINGLE_FILE = true;\nwindow.LEADER_DEMO_ASSETS = ${JSON.stringify(assetMap)};\n  </script>`;
html = html.replace(/\n  <script>window\.LEADER_DEMO_MODE = true;/, `${assetScript}\n  <script>window.LEADER_DEMO_MODE = true;`);

fs.writeFileSync(outputPath, html, "utf8");
fs.writeFileSync(asciiOutputPath, html, "utf8");
fs.writeFileSync(
  openBatPath,
  ['@echo off', 'cd /d "%~dp0"', 'start "" "%~dp0leader_workbench_single_file.html"', ""].join("\r\n"),
  "utf8",
);
fs.writeFileSync(
  openBatCnPath,
  ['@echo off', 'cd /d "%~dp0"', 'call "%~dp0open_leader_single_file.bat"', ""].join("\r\n"),
  "utf8",
);

const mb = fs.statSync(outputPath).size / 1024 / 1024;
console.log(JSON.stringify({
  outputPath,
  asciiOutputPath,
  openBatPath,
  openBatCnPath,
  embeddedAssets: Object.keys(assetMap).length / 2,
  sizeMB: Math.round(mb * 100) / 100,
}, null, 2));
