/**
 * 用途：
 * - 保留 8792 的兼容入口，但显式把它降级为 deprecated 代理层。
 * - 真实运行时 API 只认 8790；这个文件不再直接接触任何状态存储。
 */

import http from "node:http";

function parseBooleanFlag(value, fallback = true) {
  if (value === undefined || value === null || value === "") {
    return fallback;
  }
  return !["0", "false", "no", "off"].includes(String(value).trim().toLowerCase());
}

const compatPort = Number(process.env.RUNTIME_BACKBONE_API_PORT || 8792);
const targetPort = Number(process.env.MOCK_WORKBENCH_API_PORT || 8790);
const targetBaseUrl =
  process.env.RUNTIME_BACKBONE_COMPAT_TARGET || `http://127.0.0.1:${targetPort}`;
const compatEnabled = parseBooleanFlag(process.env.RUNTIME_BACKBONE_COMPAT_ENABLED, true);

function readRawBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on("data", (chunk) => chunks.push(chunk));
    req.on("end", () => resolve(chunks.length ? Buffer.concat(chunks) : null));
    req.on("error", reject);
  });
}

function sanitizeRequestHeaders(headers) {
  const nextHeaders = {};
  for (const [key, value] of Object.entries(headers || {})) {
    if (value === undefined || value === null) {
      continue;
    }
    if (["host", "content-length", "connection"].includes(String(key).toLowerCase())) {
      continue;
    }
    nextHeaders[key] = value;
  }
  nextHeaders["x-runtime-compat-proxy"] = "8792-to-8790";
  return nextHeaders;
}

function sanitizeResponseHeaders(headers) {
  const nextHeaders = {
    "X-Runtime-Deprecated": "true",
    "X-Runtime-Compat-Target": targetBaseUrl,
  };
  headers.forEach((value, key) => {
    if (["content-length", "connection", "transfer-encoding"].includes(String(key).toLowerCase())) {
      return;
    }
    nextHeaders[key] = value;
  });
  return nextHeaders;
}

const server = http.createServer(async (req, res) => {
  try {
    const requestUrl = new URL(req.url || "/", targetBaseUrl);
    const body =
      req.method === "GET" || req.method === "HEAD" || req.method === "OPTIONS"
        ? undefined
        : await readRawBody(req);
    const response = await fetch(requestUrl, {
      method: req.method || "GET",
      headers: sanitizeRequestHeaders(req.headers),
      body,
    });
    const payload = Buffer.from(await response.arrayBuffer());
    res.writeHead(response.status, sanitizeResponseHeaders(response.headers));
    res.end(payload);
  } catch (error) {
    res.writeHead(503, {
      "Content-Type": "application/json; charset=utf-8",
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type,X-Runtime-Admin-Token",
      "X-Runtime-Deprecated": "true",
      "X-Runtime-Compat-Target": targetBaseUrl,
    });
    res.end(
      JSON.stringify({
        ok: false,
        error: "runtime_backbone_compat_target_unavailable",
        target: targetBaseUrl,
        deprecated: true,
        detail: String(error?.message || error),
      })
    );
  }
});

server.on("error", (error) => {
  console.error(`runtime_backbone_api_compat_error:${error?.message || error}`);
  process.exitCode = 1;
});

if (!compatEnabled) {
  console.warn("runtime_backbone_api on 8792 is disabled by RUNTIME_BACKBONE_COMPAT_ENABLED=false");
} else {
  server.listen(compatPort, "127.0.0.1", () => {
    console.warn(
      `runtime_backbone_api on 8792 is deprecated; forwarding to ${targetBaseUrl} from http://127.0.0.1:${compatPort}`
    );
  });
}
