/**
 * 用途：
 * - 提供本地 mock 工作台演示服务，并持久化轻量历史或操作状态。
 * - 路由处理集中在这里，让前端演示保持静态资源包形态。
 */

import fs from "fs";
import http from "http";
import path from "path";
import { spawnSync } from "child_process";
import { randomUUID } from "crypto";
import { fileURLToPath } from "url";
import { createRuntimeBackboneStore } from "./runtime_backbone_store_interface.mjs";
import { resolveBundledPythonPath } from "./runtime_dependency_paths.mjs";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const workspaceRoot = path.resolve(__dirname, "..");
const pythonExe = resolveBundledPythonPath() || process.env.PYTHON || "python";
const exportRoot = path.join(workspaceRoot, "outputs", "split_builder", "mock_workbench", "export_runs");
const historyPath = path.join(exportRoot, "export_history.json");
const tmpRoot = path.join(exportRoot, "_tmp");

fs.mkdirSync(exportRoot, { recursive: true });
fs.mkdirSync(tmpRoot, { recursive: true });
const runtimeStore = await createRuntimeBackboneStore();
const adminToken = process.env.RUNTIME_ADMIN_TOKEN || "";
const rateLimitWindowMs = Number(process.env.RUNTIME_RATE_LIMIT_WINDOW_MS || 2000);
const rateLimitMaxRequests = Number(process.env.RUNTIME_RATE_LIMIT_MAX_REQUESTS || 8);
const rateLimitBuckets = new Map();

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

function sendJson(res, status, body, headers = {}) {
  res.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type,X-Runtime-Admin-Token",
    ...headers,
  });
  res.end(JSON.stringify(body));
}

function toSafeError(error) {
  const message = String(error?.message || error);
  const exactStatus = new Map([
    ["body_too_large", 413],
    ["invalid_json", 400],
    ["invalid_content_type", 415],
    ["missing_admin_token", 401],
    ["invalid_admin_token", 403],
    ["insufficient_actor_role", 403],
    ["rate_limited", 429],
    ["revision_not_approved_for_publish", 409],
    ["publication_artifact_not_found", 409],
    ["task_projection_not_published", 409],
    ["duplicate_local_task_id", 409],
    ["task_source_node_not_found", 400],
    ["invalid_bundle_payload", 400],
    ["invalid_bundle_tasks", 400],
    ["invalid_bundle_task_entry", 400],
    ["invalid_bundle_task_checkpoint_override_mode", 400],
    ["missing_local_task_id", 400],
    ["material_build_track_mismatch", 409],
    ["component_patch_not_pending", 409],
    ["component_patch_conflict", 409],
  ]);
  if (exactStatus.has(message)) {
    return {
      status: exactStatus.get(message),
      error: message,
    };
  }
  if (message.startsWith("unsupported_runtime_store:")) {
    return { status: 400, error: message };
  }
  if (message.startsWith("track_profile_") || message.startsWith("track_subject_") || message.startsWith("track_stage_")) {
    return { status: 400, error: message };
  }
  if (message.startsWith("failpoint:")) {
    return { status: 500, error: message };
  }
  if (message.endsWith("_not_found")) {
    return { status: 404, error: message };
  }
  if (
    message.endsWith("_conflict") ||
    message.includes("not_approved") ||
    message.includes("stale")
  ) {
    return { status: 409, error: message };
  }
  if (message.startsWith("invalid_") || message.startsWith("unsupported_")) {
    return { status: 400, error: message };
  }
  return {
    status: 500,
    error: message,
  };
}

function handleRouteError(res, error, requestId) {
  const safeError = toSafeError(error);
  sendJson(
    res,
    safeError.status,
    {
      ok: false,
      error: safeError.error,
      requestId,
    },
    { "X-Request-Id": requestId }
  );
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
        reject(new Error("invalid_json"));
      }
    });
    req.on("error", reject);
  });
}

/**
 * 变更类 JSON 接口的请求守卫。
 * 保持这里短小，让路由处理器读起来像工作流，而不是协议检查。
 */
function assertJsonRequest(req) {
  if (req.method !== "POST") return;
  const contentType = req.headers["content-type"] || "";
  if (!String(contentType).toLowerCase().includes("application/json")) {
    throw new Error("invalid_content_type");
  }
}

function assertAdminAccess(req) {
  if (!adminToken || req.method !== "POST") return;
  const candidate = req.headers["x-runtime-admin-token"];
  if (!candidate) {
    throw new Error("missing_admin_token");
  }
  if (candidate !== adminToken) {
    throw new Error("invalid_admin_token");
  }
}

/**
 * 本地演示限流有意采用进程内内存实现。
 * 它用于防止误重复点击，不假装是生产级限流。
 */
function assertRateLimit(req, pathname) {
  if (req.method !== "POST") return;
  const now = Date.now();
  const bucketKey = `${req.socket.remoteAddress || "local"}:${pathname}`;
  const recent = (rateLimitBuckets.get(bucketKey) || []).filter(
    (timestamp) => now - timestamp < rateLimitWindowMs
  );
  if (recent.length >= rateLimitMaxRequests) {
    rateLimitBuckets.set(bucketKey, recent);
    throw new Error("rate_limited");
  }
  recent.push(now);
  rateLimitBuckets.set(bucketKey, recent);
}

function assertActorRole(actor, allowedPatterns) {
  const normalized = String(actor || "").toLowerCase();
  if (!allowedPatterns.some((pattern) => pattern.test(normalized))) {
    throw new Error("insufficient_actor_role");
  }
}

/**
 * 在进入文档生成脚本前归一化导出 payload。
 * API 接受灵活的演示输入，但导出器依赖这个稳定形态。
 */
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

/**
 * 以子进程执行 Python 导出器，并返回生成的产物映射。
 * 把进程边界放在这里，可以隔离 Office/PDF 依赖和 HTTP 服务。
 */
async function runExport(payload) {
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
    throw new Error(pythonRun.stderr || pythonRun.stdout || pythonRun.error?.message || "python_export_failed");
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

  const runtime = await runtimeStore.registerExportRun(payload, historyItem);
  historyItem.runtime = runtime;
  return historyItem;
}

// 本地工作台 API 路由表；每个分支有意写得明确，方便演示调试。
const server = http.createServer(async (req, res) => {
  if (req.method === "OPTIONS") {
    res.writeHead(204, {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type,X-Runtime-Admin-Token",
    });
    res.end();
    return;
  }

  const requestId = randomUUID();
  const requestUrl = new URL(req.url || "/", "http://127.0.0.1");
  const pathname = requestUrl.pathname;

  try {
    assertJsonRequest(req);
    assertAdminAccess(req);
    assertRateLimit(req, pathname);
  } catch (error) {
    handleRouteError(res, error, requestId);
    return;
  }

  if (pathname === "/health") {
    const storeHealth = runtimeStore.getHealth ? await runtimeStore.getHealth() : {};
    sendJson(res, 200, {
      ok: true,
      requestId,
      historyCount: readHistory().length,
      exportRoot: toRelative(exportRoot),
      runtime: await runtimeStore.getSummary(),
      runtimeMode: runtimeStore.mode,
      storeHealth,
    }, { "X-Request-Id": requestId });
    return;
  }

  if (pathname === "/api/export/history" && req.method === "GET") {
    sendJson(res, 200, { ok: true, requestId, items: readHistory() }, { "X-Request-Id": requestId });
    return;
  }

  if (pathname === "/api/export/generate" && req.method === "POST") {
    try {
      const body = await parseBody(req);
      const payload = buildPayload(body);
      if (!payload.lesson || !payload.splitLesson) {
        sendJson(res, 400, { ok: false, error: "missing_lesson_payload", requestId }, { "X-Request-Id": requestId });
        return;
      }
      const item = await runExport(payload);
      sendJson(res, 200, { ok: true, requestId, item }, { "X-Request-Id": requestId });
      return;
    } catch (error) {
      handleRouteError(res, error, requestId);
      return;
    }
  }

  if (pathname === "/api/runtime/bootstrap" && req.method === "POST") {
    sendJson(res, 200, { ...(await runtimeStore.bootstrap()), requestId }, { "X-Request-Id": requestId });
    return;
  }

  if (pathname === "/api/runtime/summary" && req.method === "GET") {
    sendJson(res, 200, { ok: true, requestId, summary: await runtimeStore.getSummary() }, { "X-Request-Id": requestId });
    return;
  }

  if (pathname === "/api/runtime/internal/consistency" && req.method === "GET") {
    const detail = runtimeStore.getConsistencyReport
      ? await runtimeStore.getConsistencyReport()
      : {
          ok: false,
          status: "unsupported",
          checkedAt: new Date().toISOString(),
          mismatches: [{ table: "runtime", reason: "consistency_report_not_supported" }],
        };
    sendJson(res, 200, { ok: true, requestId, detail }, { "X-Request-Id": requestId });
    return;
  }

  if (pathname === "/api/runtime/lessons" && req.method === "GET") {
    sendJson(res, 200, { ok: true, requestId, items: await runtimeStore.listLessons() }, { "X-Request-Id": requestId });
    return;
  }

  const lessonParams = matchPath(pathname, "/api/runtime/lessons/:lessonId");
  if (lessonParams && req.method === "GET") {
    const detail = await runtimeStore.getLessonDetail(lessonParams.lessonId);
    if (!detail) {
      sendJson(res, 404, { ok: false, error: "lesson_not_found", requestId }, { "X-Request-Id": requestId });
      return;
    }
    sendJson(res, 200, { ok: true, requestId, detail }, { "X-Request-Id": requestId });
    return;
  }

  const rerunParams = matchPath(pathname, "/api/runtime/lessons/:lessonId/rerun");
  if (rerunParams && req.method === "POST") {
    try {
      const body = await parseBody(req);
      const result = await runtimeStore.rerunLesson(
        rerunParams.lessonId,
        body.actor || "manual_rerun"
      );
      sendJson(res, 200, { ok: true, requestId, ...result }, { "X-Request-Id": requestId });
      return;
    } catch (error) {
      handleRouteError(res, error, requestId);
      return;
    }
  }

  const publishParams = matchPath(pathname, "/api/runtime/lessons/:lessonId/publish");
  if (publishParams && req.method === "POST") {
    try {
      const body = await parseBody(req);
      assertActorRole(body.actor || "publisher", [/(publisher|admin)/]);
      const result = await runtimeStore.publishLesson(
        publishParams.lessonId,
        body.actor || "publisher",
        {
          lessonRevisionId: body.lessonRevisionId,
          materialBuildId: body.materialBuildId,
        }
      );
      sendJson(res, 200, { ok: true, requestId, result }, { "X-Request-Id": requestId });
      return;
    } catch (error) {
      handleRouteError(res, error, requestId);
      return;
    }
  }

  if (pathname === "/api/runtime/imports/lesson-draft-bundles" && req.method === "POST") {
    try {
      const body = await parseBody(req);
      const result = await runtimeStore.importLessonDraftBundle(body);
      sendJson(res, 200, { ok: true, requestId, result }, { "X-Request-Id": requestId });
      return;
    } catch (error) {
      handleRouteError(res, error, requestId);
      return;
    }
  }

  if (pathname === "/api/runtime/task-projections/search" && req.method === "GET") {
    const searchResult = await runtimeStore.searchTaskProjections({
      q: requestUrl.searchParams.get("q") || "",
      subject: requestUrl.searchParams.get("subject") || "",
      stage: requestUrl.searchParams.get("stage") || "",
      trackCode: requestUrl.searchParams.get("trackCode") || "",
      grade: requestUrl.searchParams.get("grade") || "",
      questionType: requestUrl.searchParams.get("questionType") || "",
      difficultyLevel: requestUrl.searchParams.get("difficultyLevel") || "",
      difficultyScheme: requestUrl.searchParams.get("difficultyScheme") || "",
      checkpointCode: requestUrl.searchParams.get("checkpointCode") || "",
      publishedOnly: requestUrl.searchParams.get("publishedOnly") === "true",
    });
    sendJson(
      res,
      200,
      {
        ok: true,
        requestId,
        items: searchResult.items || [],
        projectionCoverage: searchResult.projectionCoverage || { status: "unknown", needsRebuild: false },
      },
      { "X-Request-Id": requestId }
    );
    return;
  }

  if (pathname === "/api/runtime/internal/task-projections/rebuild" && req.method === "POST") {
    try {
      const body = await parseBody(req);
      const result = await runtimeStore.rebuildTaskProjections({
        lessonId: body.lessonId,
        lessonRevisionId: body.lessonRevisionId,
      });
      sendJson(res, 200, { ok: true, requestId, result }, { "X-Request-Id": requestId });
      return;
    } catch (error) {
      handleRouteError(res, error, requestId);
      return;
    }
  }

  if (pathname === "/api/runtime/runs" && req.method === "GET") {
    sendJson(res, 200, { ok: true, requestId, items: await runtimeStore.listRuns() }, { "X-Request-Id": requestId });
    return;
  }

  const runParams = matchPath(pathname, "/api/runtime/runs/:runId");
  if (runParams && req.method === "GET") {
    const detail = await runtimeStore.getRunDetail(runParams.runId);
    if (!detail) {
      sendJson(res, 404, { ok: false, error: "run_not_found", requestId }, { "X-Request-Id": requestId });
      return;
    }
    sendJson(res, 200, { ok: true, requestId, detail }, { "X-Request-Id": requestId });
    return;
  }

  if (pathname === "/api/runtime/review-tasks" && req.method === "GET") {
    const status = requestUrl.searchParams.get("status");
    const items = await runtimeStore.listReviewTasks(status);
    sendJson(res, 200, { ok: true, requestId, items }, { "X-Request-Id": requestId });
    return;
  }

  const approveParams = matchPath(pathname, "/api/runtime/review-tasks/:reviewTaskId/approve");
  if (approveParams && req.method === "POST") {
    try {
      const body = await parseBody(req);
      assertActorRole(body.actor || "reviewer", [/(reviewer|admin)/]);
      const result = await runtimeStore.approveReviewTask(
        approveParams.reviewTaskId,
        body.actor || "reviewer"
      );
      sendJson(res, 200, { ok: true, requestId, result }, { "X-Request-Id": requestId });
      return;
    } catch (error) {
      handleRouteError(res, error, requestId);
      return;
    }
  }

  const changesParams = matchPath(pathname, "/api/runtime/review-tasks/:reviewTaskId/request-changes");
  if (changesParams && req.method === "POST") {
    try {
      const body = await parseBody(req);
      assertActorRole(body.actor || "reviewer", [/(reviewer|admin)/]);
      const result = await runtimeStore.requestReviewChanges(
        changesParams.reviewTaskId,
        body.actor || "reviewer"
      );
      sendJson(res, 200, { ok: true, requestId, result }, { "X-Request-Id": requestId });
      return;
    } catch (error) {
      handleRouteError(res, error, requestId);
      return;
    }
  }

  const artifactParams = matchPath(pathname, "/api/runtime/artifacts/:artifactId/lineage");
  if (artifactParams && req.method === "GET") {
    const detail = await runtimeStore.getArtifactLineage(artifactParams.artifactId);
    if (!detail) {
      sendJson(res, 404, { ok: false, error: "artifact_not_found", requestId }, { "X-Request-Id": requestId });
      return;
    }
    sendJson(res, 200, { ok: true, requestId, detail }, { "X-Request-Id": requestId });
    return;
  }

  const componentRerunParams = matchPath(pathname, "/api/runtime/components/:componentId/rerun");
  if (componentRerunParams && req.method === "POST") {
    try {
      const body = await parseBody(req);
      const result = await runtimeStore.rerunComponent(componentRerunParams.componentId, body);
      sendJson(res, 200, { ok: true, requestId, result }, { "X-Request-Id": requestId });
      return;
    } catch (error) {
      handleRouteError(res, error, requestId);
      return;
    }
  }

  const componentRevisionsParams = matchPath(pathname, "/api/runtime/components/:componentId/revisions");
  if (componentRevisionsParams && req.method === "GET") {
    const items = await runtimeStore.listComponentRevisions(componentRevisionsParams.componentId);
    sendJson(res, 200, { ok: true, requestId, items }, { "X-Request-Id": requestId });
    return;
  }

  const componentPatchParams = matchPath(pathname, "/api/runtime/component-patches/:patchId");
  if (componentPatchParams && req.method === "GET") {
    const detail = await runtimeStore.getComponentPatch(componentPatchParams.patchId);
    if (!detail) {
      sendJson(res, 404, { ok: false, error: "component_patch_not_found", requestId }, { "X-Request-Id": requestId });
      return;
    }
    sendJson(res, 200, { ok: true, requestId, detail }, { "X-Request-Id": requestId });
    return;
  }

  const acceptPatchParams = matchPath(pathname, "/api/runtime/component-patches/:patchId/accept");
  if (acceptPatchParams && req.method === "POST") {
    try {
      const body = await parseBody(req);
      assertActorRole(body.actor || "component_reviewer", [/(reviewer|admin)/]);
      const result = await runtimeStore.acceptComponentPatch(
        acceptPatchParams.patchId,
        body.actor || "component_reviewer"
      );
      sendJson(res, 200, { ok: true, requestId, result }, { "X-Request-Id": requestId });
      return;
    } catch (error) {
      handleRouteError(res, error, requestId);
      return;
    }
  }

  const rejectPatchParams = matchPath(pathname, "/api/runtime/component-patches/:patchId/reject");
  if (rejectPatchParams && req.method === "POST") {
    try {
      const body = await parseBody(req);
      assertActorRole(body.actor || "component_reviewer", [/(reviewer|admin)/]);
      const result = await runtimeStore.rejectComponentPatch(
        rejectPatchParams.patchId,
        body.actor || "component_reviewer"
      );
      sendJson(res, 200, { ok: true, requestId, result }, { "X-Request-Id": requestId });
      return;
    } catch (error) {
      handleRouteError(res, error, requestId);
      return;
    }
  }

  if (pathname === "/api/question-bank/search" && req.method === "GET") {
    const items = await runtimeStore.searchQuestionBank({
      q: requestUrl.searchParams.get("q") || "",
      subject: requestUrl.searchParams.get("subject") || "",
      stage: requestUrl.searchParams.get("stage") || "",
      trackCode: requestUrl.searchParams.get("trackCode") || "",
      grade: requestUrl.searchParams.get("grade") || "",
      questionType: requestUrl.searchParams.get("questionType") || "",
      difficultyLevel: requestUrl.searchParams.get("difficultyLevel") || "",
      difficultyScheme: requestUrl.searchParams.get("difficultyScheme") || "",
      checkpointCode: requestUrl.searchParams.get("checkpointCode") || "",
      latestOnly: requestUrl.searchParams.get("latestOnly") !== "false",
    });
    sendJson(res, 200, { ok: true, requestId, items }, { "X-Request-Id": requestId });
    return;
  }

  if (pathname === "/api/question-bank/items" && req.method === "POST") {
    try {
      const body = await parseBody(req);
      const result = await runtimeStore.createQuestionBankItem(body);
      sendJson(res, 200, { ok: true, requestId, result }, { "X-Request-Id": requestId });
      return;
    } catch (error) {
      handleRouteError(res, error, requestId);
      return;
    }
  }

  if (pathname === "/api/material-builds" && req.method === "POST") {
    try {
      const body = await parseBody(req);
      const result = await runtimeStore.createMaterialBuild(body);
      sendJson(res, 200, { ok: true, requestId, result }, { "X-Request-Id": requestId });
      return;
    } catch (error) {
      handleRouteError(res, error, requestId);
      return;
    }
  }

  const materialBuildItemsParams = matchPath(pathname, "/api/material-builds/:materialBuildId/items");
  if (materialBuildItemsParams && req.method === "POST") {
    try {
      const body = await parseBody(req);
      const result = await runtimeStore.addMaterialBuildItems(
        materialBuildItemsParams.materialBuildId,
        body
      );
      sendJson(res, 200, { ok: true, requestId, result }, { "X-Request-Id": requestId });
      return;
    } catch (error) {
      handleRouteError(res, error, requestId);
      return;
    }
  }

  const materialBuildExportParams = matchPath(pathname, "/api/material-builds/:materialBuildId/export");
  if (materialBuildExportParams && req.method === "POST") {
    try {
      const body = await parseBody(req);
      const result = await runtimeStore.exportMaterialBuild(
        materialBuildExportParams.materialBuildId,
        body
      );
      sendJson(res, 200, { ok: true, requestId, result }, { "X-Request-Id": requestId });
      return;
    } catch (error) {
      handleRouteError(res, error, requestId);
      return;
    }
  }

  if (pathname === "/api/runtime/jobs/recover" && req.method === "POST") {
    try {
      const body = await parseBody(req);
      const items = await runtimeStore.recoverJobs(body.actor || "runtime_recovery");
      sendJson(res, 200, { ok: true, requestId, items }, { "X-Request-Id": requestId });
      return;
    } catch (error) {
      handleRouteError(res, error, requestId);
      return;
    }
  }

  if (pathname === "/api/runtime/debug/state" && req.method === "GET") {
    sendJson(res, 200, { ok: true, requestId, state: await runtimeStore.getDebugState() }, { "X-Request-Id": requestId });
    return;
  }

  sendJson(res, 404, { ok: false, error: "not_found", requestId }, { "X-Request-Id": requestId });
});

const port = Number(process.env.MOCK_WORKBENCH_API_PORT || 8790);
server.on("error", (error) => {
  console.error(`mock_workbench_api_server_error:${error?.message || error}`);
  process.exitCode = 1;
});

server.listen(port, "127.0.0.1", () => {
  console.log(`mock_workbench_api listening on http://127.0.0.1:${port}`);
});

async function shutdown(signal) {
  console.log(`mock_workbench_api shutting down on ${signal}`);
  await new Promise((resolve) => server.close(() => resolve()));
  if (runtimeStore.close) {
    await runtimeStore.close();
  }
}

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => {
    shutdown(signal)
      .then(() => process.exit(0))
      .catch((error) => {
        console.error(`mock_workbench_api_shutdown_error:${error?.message || error}`);
        process.exit(1);
      });
  });
}
