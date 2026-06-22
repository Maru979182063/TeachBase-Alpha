import fs from "fs";
import http from "http";
import path from "path";
import { spawnSync } from "child_process";
import { fileURLToPath } from "url";
import {
  ensureSeededState,
  getArtifactLineage,
  getLessonDetail,
  getRunDetail,
  getSummary as getRuntimeSummary,
  listLessons,
  loadState,
  registerExportRun,
  reseedState,
  rerunLesson,
  saveState,
  updateReviewTaskStatus,
} from "./runtime_backbone_store.mjs";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const workspaceRoot = path.resolve(__dirname, "..");
const pythonExe = "C:\\Users\\EDY\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\python\\python.exe";
const exportRoot = path.join(workspaceRoot, "outputs", "split_builder", "mock_workbench", "export_runs");
const historyPath = path.join(exportRoot, "export_history.json");
const tmpRoot = path.join(exportRoot, "_tmp");

fs.mkdirSync(exportRoot, { recursive: true });
fs.mkdirSync(tmpRoot, { recursive: true });
ensureSeededState();

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

function matchPath(pathname, pattern) {
  const actual = pathname.split("/").filter(Boolean);
  const expected = pattern.split("/").filter(Boolean);
  if (actual.length !== expected.length) return null;
  const params = {};
  for (let i = 0; i < expected.length; i += 1) {
    const exp = expected[i];
    const act = actual[i];
    if (exp.startsWith(":")) {
      params[exp.slice(1)] = decodeURIComponent(act);
      continue;
    }
    if (exp !== act) return null;
  }
  return params;
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

  const runtimeState = loadState();
  const runtime = registerExportRun(runtimeState, payload, historyItem);
  saveState(runtimeState);
  historyItem.runtime = runtime;
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

  const requestUrl = new URL(req.url || "/", "http://127.0.0.1");
  const pathname = requestUrl.pathname;

  if (pathname === "/health") {
    const runtimeState = loadState();
    sendJson(res, 200, {
      ok: true,
      historyCount: readHistory().length,
      exportRoot: toRelative(exportRoot),
      runtime: getRuntimeSummary(runtimeState),
    });
    return;
  }

  if (pathname === "/api/export/history" && req.method === "GET") {
    sendJson(res, 200, { items: readHistory() });
    return;
  }

  if (pathname === "/api/export/generate" && req.method === "POST") {
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

  if (pathname === "/api/runtime/bootstrap" && req.method === "POST") {
    const state = reseedState();
    sendJson(res, 200, { ok: true, summary: getRuntimeSummary(state) });
    return;
  }

  if (pathname === "/api/runtime/summary" && req.method === "GET") {
    sendJson(res, 200, { ok: true, summary: getRuntimeSummary(loadState()) });
    return;
  }

  if (pathname === "/api/runtime/lessons" && req.method === "GET") {
    sendJson(res, 200, { ok: true, items: listLessons(loadState()) });
    return;
  }

  const lessonParams = matchPath(pathname, "/api/runtime/lessons/:lessonId");
  if (lessonParams && req.method === "GET") {
    const detail = getLessonDetail(loadState(), lessonParams.lessonId);
    if (!detail) {
      sendJson(res, 404, { ok: false, error: "lesson_not_found" });
      return;
    }
    sendJson(res, 200, { ok: true, detail });
    return;
  }

  const rerunParams = matchPath(pathname, "/api/runtime/lessons/:lessonId/rerun");
  if (rerunParams && req.method === "POST") {
    try {
      const body = await parseBody(req);
      const state = loadState();
      const result = rerunLesson(state, rerunParams.lessonId, body.actor || "manual_rerun");
      saveState(state);
      sendJson(res, 200, { ok: true, result, lesson: getLessonDetail(state, rerunParams.lessonId) });
      return;
    } catch (error) {
      sendJson(res, 500, { ok: false, error: String(error?.message || error) });
      return;
    }
  }

  if (pathname === "/api/runtime/runs" && req.method === "GET") {
    const state = loadState();
    sendJson(res, 200, { ok: true, items: state.runs });
    return;
  }

  const runParams = matchPath(pathname, "/api/runtime/runs/:runId");
  if (runParams && req.method === "GET") {
    const detail = getRunDetail(loadState(), runParams.runId);
    if (!detail) {
      sendJson(res, 404, { ok: false, error: "run_not_found" });
      return;
    }
    sendJson(res, 200, { ok: true, detail });
    return;
  }

  if (pathname === "/api/runtime/review-tasks" && req.method === "GET") {
    const state = loadState();
    const status = requestUrl.searchParams.get("status");
    const items = status ? state.reviewTasks.filter((item) => item.status === status) : state.reviewTasks;
    sendJson(res, 200, { ok: true, items });
    return;
  }

  const approveParams = matchPath(pathname, "/api/runtime/review-tasks/:reviewTaskId/approve");
  if (approveParams && req.method === "POST") {
    try {
      const body = await parseBody(req);
      const state = loadState();
      const result = updateReviewTaskStatus(state, approveParams.reviewTaskId, "approve", body.actor || "reviewer");
      saveState(state);
      sendJson(res, 200, { ok: true, result });
      return;
    } catch (error) {
      sendJson(res, 500, { ok: false, error: String(error?.message || error) });
      return;
    }
  }

  const changesParams = matchPath(pathname, "/api/runtime/review-tasks/:reviewTaskId/request-changes");
  if (changesParams && req.method === "POST") {
    try {
      const body = await parseBody(req);
      const state = loadState();
      const result = updateReviewTaskStatus(
        state,
        changesParams.reviewTaskId,
        "request_changes",
        body.actor || "reviewer"
      );
      saveState(state);
      sendJson(res, 200, { ok: true, result });
      return;
    } catch (error) {
      sendJson(res, 500, { ok: false, error: String(error?.message || error) });
      return;
    }
  }

  const artifactParams = matchPath(pathname, "/api/runtime/artifacts/:artifactId/lineage");
  if (artifactParams && req.method === "GET") {
    const detail = getArtifactLineage(loadState(), artifactParams.artifactId);
    if (!detail) {
      sendJson(res, 404, { ok: false, error: "artifact_not_found" });
      return;
    }
    sendJson(res, 200, { ok: true, detail });
    return;
  }

  sendJson(res, 404, { ok: false, error: "not_found" });
});

const port = Number(process.env.MOCK_WORKBENCH_API_PORT || 8790);
server.listen(port, "127.0.0.1", () => {
  console.log(`mock_workbench_api listening on http://127.0.0.1:${port}`);
});
