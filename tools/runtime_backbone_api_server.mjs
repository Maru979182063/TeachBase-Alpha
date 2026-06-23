/**
 * Purpose:
 * - Exposes runtime backbone store operations over a small local HTTP API.
 * - This is the bridge between automated checks, demos, and the runtime store implementations.
 */

import http from "http";
import { URL } from "url";
import {
  ensureSeededState,
  getArtifactLineage,
  getLessonDetail,
  getRunDetail,
  getSummary,
  listLessons,
  loadState,
  reseedState,
  rerunLesson,
  saveState,
  updateReviewTaskStatus,
} from "./runtime_backbone_store.mjs";

function sendJson(res, status, body) {
  res.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
  });
  res.end(JSON.stringify(body, null, 2));
}

function parseBody(req) {
  return new Promise((resolve, reject) => {
    let raw = "";
    req.on("data", (chunk) => {
      raw += chunk;
      if (raw.length > 2_000_000) {
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

ensureSeededState();

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

  const url = new URL(req.url || "/", "http://127.0.0.1");
  const { pathname } = url;

  try {
    if (pathname === "/health" && req.method === "GET") {
      const state = loadState();
      sendJson(res, 200, {
        ok: true,
        service: "runtime_backbone_api",
        summary: getSummary(state),
      });
      return;
    }

    if (pathname === "/api/runtime/bootstrap" && req.method === "POST") {
      const state = reseedState();
      sendJson(res, 200, {
        ok: true,
        summary: getSummary(state),
      });
      return;
    }

    if (pathname === "/api/runtime/summary" && req.method === "GET") {
      sendJson(res, 200, {
        ok: true,
        summary: getSummary(loadState()),
      });
      return;
    }

    if (pathname === "/api/runtime/lessons" && req.method === "GET") {
      const state = loadState();
      sendJson(res, 200, {
        ok: true,
        items: listLessons(state),
      });
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
      const body = await parseBody(req);
      const state = loadState();
      const result = rerunLesson(state, rerunParams.lessonId, body.actor || "manual_rerun");
      saveState(state);
      sendJson(res, 200, {
        ok: true,
        result,
        lesson: getLessonDetail(state, rerunParams.lessonId),
      });
      return;
    }

    if (pathname === "/api/runtime/runs" && req.method === "GET") {
      const state = loadState();
      sendJson(res, 200, {
        ok: true,
        items: state.runs,
      });
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
      const status = url.searchParams.get("status");
      const items = status
        ? state.reviewTasks.filter((item) => item.status === status)
        : state.reviewTasks;
      sendJson(res, 200, { ok: true, items });
      return;
    }

    const approveParams = matchPath(pathname, "/api/runtime/review-tasks/:reviewTaskId/approve");
    if (approveParams && req.method === "POST") {
      const body = await parseBody(req);
      const state = loadState();
      const result = updateReviewTaskStatus(state, approveParams.reviewTaskId, "approve", body.actor || "reviewer");
      saveState(state);
      sendJson(res, 200, { ok: true, result });
      return;
    }

    const changeParams = matchPath(pathname, "/api/runtime/review-tasks/:reviewTaskId/request-changes");
    if (changeParams && req.method === "POST") {
      const body = await parseBody(req);
      const state = loadState();
      const result = updateReviewTaskStatus(
        state,
        changeParams.reviewTaskId,
        "request_changes",
        body.actor || "reviewer"
      );
      saveState(state);
      sendJson(res, 200, { ok: true, result });
      return;
    }

    const lineageParams = matchPath(pathname, "/api/runtime/artifacts/:artifactId/lineage");
    if (lineageParams && req.method === "GET") {
      const detail = getArtifactLineage(loadState(), lineageParams.artifactId);
      if (!detail) {
        sendJson(res, 404, { ok: false, error: "artifact_not_found" });
        return;
      }
      sendJson(res, 200, { ok: true, detail });
      return;
    }

    if (pathname === "/api/runtime/debug/state" && req.method === "GET") {
      sendJson(res, 200, { ok: true, state: loadState() });
      return;
    }

    sendJson(res, 404, { ok: false, error: "not_found" });
  } catch (error) {
    sendJson(res, 500, {
      ok: false,
      error: String(error?.message || error),
    });
  }
});

const port = Number(process.env.RUNTIME_BACKBONE_API_PORT || 8792);
server.listen(port, "127.0.0.1", () => {
  console.log(`runtime_backbone_api listening on http://127.0.0.1:${port}`);
});
