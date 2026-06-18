import fs from "fs";
import http from "http";
import path from "path";
import { spawnSync } from "child_process";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const workspaceRoot = path.resolve(__dirname, "..");
const pythonExe = "C:\\Users\\EDY\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\python\\python.exe";
const exportRoot = path.join(workspaceRoot, "outputs", "split_builder", "mock_workbench", "export_runs");
const historyPath = path.join(exportRoot, "export_history.json");
const tmpRoot = path.join(exportRoot, "_tmp");

fs.mkdirSync(exportRoot, { recursive: true });
fs.mkdirSync(tmpRoot, { recursive: true });

function readHistory() {
  if (!fs.existsSync(historyPath)) return [];
  try {
    const raw = fs.readFileSync(historyPath, "utf8").replace(/^\uFEFF/, "");
    return JSON.parse(raw);
  } catch {
    return [];
  }
}

function writeHistory(history) {
  fs.writeFileSync(historyPath, JSON.stringify(history.slice(0, 30), null, 2), "utf8");
}

function slug(text) {
  return String(text || "")
    .trim()
    .replace(/[\\/:*?"<>|]+/g, "_")
    .replace(/\s+/g, "_");
}

function toRelative(filePath) {
  return path.relative(workspaceRoot, filePath).replace(/\\/g, "/");
}

function sendJson(res, status, body) {
  res.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
  });
  res.end(JSON.stringify(body));
}

function parseBody(req) {
  return new Promise((resolve, reject) => {
    let raw = "";
    req.on("data", (chunk) => {
      raw += chunk;
      if (raw.length > 10_000_000) {
        reject(new Error("body_too_large"));
      }
    });
    req.on("end", () => {
      try {
        resolve(raw ? JSON.parse(raw) : {});
      } catch (error) {
        reject(error);
      }
    });
    req.on("error", reject);
  });
}

function buildPayload(input) {
  const questionVersionOverrides = input.questionVersions || {};
  const splitQuestions = (input.splitLesson?.questions || []).map((question) => ({
    ...question,
    effectiveVersionTags: questionVersionOverrides[question.id] || question.versionTags || [],
  }));

  const reviewItems = (input.reviewQueue || [])
    .filter((item) => item.lessonId === input.lesson.lesson_id)
    .map((item) => {
      const q = splitQuestions.find((question) => question.id === item.questionId);
      return q ? { ...q, queueNo: item.queueNo, title: item.title, tags: item.tags || [] } : item;
    });

  return {
    lesson: input.lesson,
    splitLesson: {
      ...input.splitLesson,
      questions: splitQuestions,
    },
    reviewItems,
    selectedVersions: input.selectedVersions || [],
    selectedAudiences: input.selectedAudiences || [],
    selectedFormats: input.selectedFormats || [],
    includeCompass: Boolean(input.includeCompass),
  };
}

function runExport(payload) {
  const now = new Date();
  const stamp = now.toISOString().replace(/[:.]/g, "-");
  const runId = `${stamp}_${slug(payload.lesson.lesson_id)}`;
  const runDir = path.join(exportRoot, runId);
  fs.mkdirSync(runDir, { recursive: true });

  const runtimePayload = {
    ...payload,
    outputDir: runDir,
    createdAtDisplay: now.toLocaleString("zh-CN", { hour12: false }),
  };

  const payloadPath = path.join(tmpRoot, `${runId}.json`);
  const manifestPath = path.join(tmpRoot, `${runId}.manifest.json`);
  fs.writeFileSync(payloadPath, JSON.stringify(runtimePayload, null, 2), "utf8");

  const pythonRun = spawnSync(
    pythonExe,
    [path.join(workspaceRoot, "tools", "mock_workbench_export_bundle.py"), "--payload", payloadPath, "--manifest", manifestPath],
    { cwd: workspaceRoot, encoding: "utf8" }
  );
  if (pythonRun.status !== 0) {
    throw new Error(pythonRun.stderr || pythonRun.stdout || "python_export_failed");
  }

  const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
  const files = [...(manifest.files || [])];

  const normalizedFiles = files
    .filter((file) => fs.existsSync(file.path))
    .map((file) => ({
      ...file,
      relativePath: toRelative(file.path),
      size: fs.statSync(file.path).size,
    }));

  const historyItem = {
    id: runId,
    createdAt: now.toISOString(),
    createdAtDisplay: now.toLocaleString("zh-CN", { hour12: false }),
    lessonId: payload.lesson.lesson_id,
    lessonTitle: payload.lesson.lesson_title,
    stage: payload.lesson.stage,
    grade: payload.lesson.grade,
    season: payload.lesson.season,
    outputDir: runDir,
    outputRelativeDir: toRelative(runDir),
    versions: payload.selectedVersions,
    audiences: payload.selectedAudiences,
    formats: payload.selectedFormats,
    includeCompass: payload.includeCompass,
    fileCount: normalizedFiles.length,
    files: normalizedFiles,
  };

  const history = readHistory();
  history.unshift(historyItem);
  writeHistory(history);
  return historyItem;
}

const server = http.createServer(async (req, res) => {
  if (req.method === "OPTIONS") {
    res.writeHead(204, {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type",
    });
    res.end();
    return;
  }

  if (req.url === "/health") {
    sendJson(res, 200, { ok: true, historyCount: readHistory().length, exportRoot: toRelative(exportRoot) });
    return;
  }

  if (req.url === "/api/export/history" && req.method === "GET") {
    sendJson(res, 200, { items: readHistory() });
    return;
  }

  if (req.url === "/api/export/generate" && req.method === "POST") {
    try {
      const body = await parseBody(req);
      const payload = buildPayload(body);
      if (!payload.lesson || !payload.splitLesson) {
        sendJson(res, 400, { ok: false, error: "missing_lesson_payload" });
        return;
      }
      const item = runExport(payload);
      sendJson(res, 200, { ok: true, item });
      return;
    } catch (error) {
      sendJson(res, 500, {
        ok: false,
        error: String(error?.message || error),
      });
      return;
    }
  }

  sendJson(res, 404, { ok: false, error: "not_found" });
});

const port = Number(process.env.MOCK_WORKBENCH_API_PORT || 8790);
server.listen(port, "127.0.0.1", () => {
  console.log(`mock_workbench_api listening on http://127.0.0.1:${port}`);
});
