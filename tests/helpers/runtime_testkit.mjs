/**
 * 用途：
 * - 共享测试工具，提供断言、报告和临时工作区设置能力。
 * - 跨套件工具放在这里，让单个测试文件专注于测试意图。
 */

import assert from "node:assert/strict";
import fs from "node:fs";
import fsp from "node:fs/promises";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import { fileURLToPath, pathToFileURL } from "node:url";
import EmbeddedPostgres from "embedded-postgres";
import { Pool } from "pg";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

export const workspaceRoot = path.resolve(__dirname, "..", "..");
export const reportRoot = path.join(workspaceRoot, "outputs", "production_readiness");
const configuredTempRoot = String(process.env.RUNTIME_TEST_TEMP_ROOT || "").trim();
const asciiTempRoot = configuredTempRoot
  ? path.resolve(configuredTempRoot)
  : process.platform === "win32"
    ? path.win32.join("C:\\", "tmp", "jiaoyan-runtime-tests")
    : path.join(os.tmpdir(), "jiaoyan-runtime-tests");

export function expect(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

export function expectEqual(actual, expected, message) {
  assert.deepEqual(actual, expected, message);
}

export class SkipTestError extends Error {
  constructor(message) {
    super(message);
    this.name = "SkipTestError";
  }
}

export function skipTest(message) {
  throw new SkipTestError(message);
}

export async function ensureDir(targetPath) {
  await fsp.mkdir(targetPath, { recursive: true });
  return targetPath;
}

export function sanitizeFileName(value) {
  return String(value || "artifact")
    .replace(/[\\/:*?"<>|]+/g, "_")
    .replace(/\s+/g, "_");
}

export function makeRunId(prefix = "runtime") {
  return `${sanitizeFileName(prefix)}_${new Date().toISOString().replace(/[:.]/g, "-")}_${randomUUID().slice(0, 8)}`;
}

export async function reservePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      server.close((error) => {
        if (error) {
          reject(error);
          return;
        }
        resolve(address.port);
      });
    });
    server.on("error", reject);
  });
}

export function maskDatabaseUrl(connectionString) {
  const url = new URL(connectionString);
  const authPrefix = url.username ? `${url.username}:***@` : "";
  return `${url.protocol}//${authPrefix}${url.hostname}:${url.port}${url.pathname}`;
}

export function assertTestDatabaseName(databaseName) {
  if (!/(test|ci|integration|tmp|temp)/i.test(databaseName || "")) {
    throw new Error(`unsafe_test_database_name:${databaseName}`);
  }
}

function assertLoopbackDatabaseUrl(connectionString) {
  const url = new URL(connectionString);
  if (!["127.0.0.1", "localhost", "::1"].includes(url.hostname)) {
    throw new Error(`unsafe_test_database_host:${url.hostname}`);
  }
  return url;
}

export async function readJsonFixture(...segments) {
  const fixturePath = path.join(workspaceRoot, "tests", "fixtures", ...segments);
  return JSON.parse(await fsp.readFile(fixturePath, "utf8"));
}

export async function listFiles(rootDir, predicate) {
  const entries = await fsp.readdir(rootDir, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const absolutePath = path.join(rootDir, entry.name);
    if (entry.isDirectory()) {
      files.push(...(await listFiles(absolutePath, predicate)));
      continue;
    }
    if (!predicate || predicate(absolutePath)) {
      files.push(absolutePath);
    }
  }
  return files;
}

export async function runProcess(command, args = [], options = {}) {
  return new Promise((resolve) => {
    const needsShell = process.platform === "win32" && /\.(cmd|bat)$/i.test(String(command));
    const child = spawn(command, args, {
      cwd: options.cwd || workspaceRoot,
      env: {
        ...process.env,
        ...(options.env || {}),
      },
      shell: needsShell,
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => {
      stdout += String(chunk);
    });
    child.stderr.on("data", (chunk) => {
      stderr += String(chunk);
    });
    child.on("error", (error) => {
      resolve({
        code: 1,
        signal: null,
        stdout,
        stderr: `${stderr}${error.message}`,
      });
    });
    child.on("close", (code, signal) => {
      resolve({
        code,
        signal,
        stdout,
        stderr,
      });
    });
  });
}

async function forceTerminateChild(child) {
  if (!child?.pid || child.exitCode !== null) {
    return;
  }
  if (process.platform === "win32") {
    await runProcess("taskkill", ["/PID", String(child.pid), "/T", "/F"], {
      cwd: workspaceRoot,
    });
    return;
  }
  child.kill("SIGKILL");
}

async function stopChildProcess(child) {
  if (!child || child.exitCode !== null) {
    return;
  }
  child.kill("SIGTERM");
  await new Promise((resolve) => {
    let settled = false;
    const finish = () => {
      if (settled) {
        return;
      }
      settled = true;
      clearTimeout(forceTimer);
      clearTimeout(resolveTimer);
      resolve();
    };
    const forceTimer = setTimeout(() => {
      forceTerminateChild(child)
        .catch(() => undefined)
        .finally(() => {
          setTimeout(finish, 1000);
        });
    }, 5_000);
    const resolveTimer = setTimeout(finish, 15_000);
    child.once("close", finish);
    child.once("exit", finish);
  });
}

/**
 * 为需要真实数据库行为的套件启动隔离的一次性 Postgres 集群。
 * 下面的数据库名称断言刻意严格，避免误碰开发者数据。
 */
async function startManagedTestPostgresCluster(label, adminConnectionString) {
  const markerDir = path.join(asciiTempRoot, makeRunId(`${label}_managed_pg`));
  await ensureDir(markerDir);
  const adminUrl = assertLoopbackDatabaseUrl(adminConnectionString);
  const adminPool = new Pool({ connectionString: adminUrl.toString() });
  const createdDatabases = new Set();
  try {
    const versionResult = await adminPool.query("select version() as version");
    const version = versionResult.rows[0]?.version || "unknown";
    return {
      host: adminUrl.hostname,
      port: Number(adminUrl.port || 5432),
      user: decodeURIComponent(adminUrl.username),
      password: decodeURIComponent(adminUrl.password),
      version,
      databaseDir: markerDir,
      async createDatabase(prefix = "runtime_test") {
        const database = `${sanitizeFileName(prefix).toLowerCase()}_${randomUUID().slice(0, 8)}`;
        assertTestDatabaseName(database);
        await adminPool.query(`create database "${database}"`);
        createdDatabases.add(database);
        const databaseUrl = new URL(adminUrl.toString());
        databaseUrl.pathname = `/${database}`;
        return {
          database,
          connectionString: databaseUrl.toString(),
          maskedConnectionString: maskDatabaseUrl(databaseUrl.toString()),
        };
      },
      async adminQuery(sql, params = []) {
        return adminPool.query(sql, params);
      },
      async stop() {
        // 托管测试服务由 runner 维护；这里只回收本套件创建的数据库，绝不停止或修改服务本身。
        let cleanupError = null;
        try {
          for (const database of [...createdDatabases].reverse()) {
            assertTestDatabaseName(database);
            await adminPool.query(
              "select pg_terminate_backend(pid) from pg_stat_activity where datname = $1 and pid <> pg_backend_pid()",
              [database]
            );
            await adminPool.query(`drop database if exists "${database}"`);
          }
        } catch (error) {
          cleanupError = error;
        } finally {
          await adminPool.end().catch((error) => {
            cleanupError ||= error;
          });
          await fsp.rm(markerDir, { recursive: true, force: true }).catch((error) => {
            cleanupError ||= error;
          });
        }
        if (cleanupError) {
          throw cleanupError;
        }
      },
    };
  } catch (error) {
    await adminPool.end().catch(() => undefined);
    await fsp.rm(markerDir, { recursive: true, force: true }).catch(() => undefined);
    throw error;
  }
}

export async function startEmbeddedPostgresCluster(label = "runtime_test") {
  const managedAdminUrl = String(process.env.RUNTIME_TEST_POSTGRES_ADMIN_URL || "").trim();
  if (managedAdminUrl) {
    // Windows hosted runner 以管理员身份执行 job，PostgreSQL 服务则以专用普通账号安全运行。
    return startManagedTestPostgresCluster(label, managedAdminUrl);
  }
  await ensureDir(asciiTempRoot);
  const databaseDir = path.join(asciiTempRoot, makeRunId(`${label}_pg`));
  const port = await reservePort();
  const user = "postgres";
  const password = `pw_${randomUUID().slice(0, 10)}`;
  const diagnostics = [];
  const recordDiagnostic = (value) => {
    const message = value instanceof Error ? value.stack || value.message : String(value ?? "<undefined>");
    diagnostics.push(message);
  };
  const pg = new EmbeddedPostgres({
    databaseDir,
    port,
    user,
    password,
    persistent: false,
    initdbFlags: ["--locale=C"],
    onLog: recordDiagnostic,
    onError: recordDiagnostic,
  });
  try {
    await pg.initialise();
    await pg.start();
  } catch (error) {
    // CI 启动失败时必须保留 initdb/postgres 的真实诊断，不能再抛出无信息的 undefined。
    const reason = error instanceof Error ? error.stack || error.message : String(error ?? "<undefined>");
    throw new Error(`embedded_postgres_start_failed:${reason}\n${diagnostics.slice(-20).join("\n")}`);
  }

  const adminPool = new Pool({
    host: "127.0.0.1",
    port,
    user,
    password,
    database: "postgres",
  });
  const versionResult = await adminPool.query("select version() as version");
  const version = versionResult.rows[0]?.version || "unknown";

  return {
    host: "127.0.0.1",
    port,
    user,
    password,
    version,
    databaseDir,
    async createDatabase(prefix = "runtime_test") {
      const database = `${sanitizeFileName(prefix).toLowerCase()}_${randomUUID().slice(0, 8)}`;
      assertTestDatabaseName(database);
      await adminPool.query(`create database "${database}"`);
      const connectionString = `postgresql://${encodeURIComponent(user)}:${encodeURIComponent(password)}@127.0.0.1:${port}/${database}`;
      return {
        database,
        connectionString,
        maskedConnectionString: maskDatabaseUrl(connectionString),
      };
    },
    async adminQuery(sql, params = []) {
      return adminPool.query(sql, params);
    },
    async stop() {
      await adminPool.end();
      await pg.stop();
      // Windows may keep a just-stopped PostgreSQL data file handle alive for a few
      // scheduler ticks. Bounded fs.rm retries still fail the gate on a real leak,
      // while avoiding a false failure from that documented transient EBUSY state.
      await fsp.rm(databaseDir, {
        recursive: true,
        force: true,
        maxRetries: 10,
        retryDelay: 200,
      });
    },
  };
}

export async function fetchJson(url, options = {}) {
  const response = await fetch(url, {
    method: options.method || "GET",
    headers: {
      ...(options.json === false ? {} : { "Content-Type": "application/json" }),
      ...(options.headers || {}),
    },
    body:
      options.body === undefined || options.body === null
        ? undefined
        : options.json === false
          ? options.body
          : JSON.stringify(options.body),
  });
  const text = await response.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = { raw: text };
  }
  return {
    ok: response.ok,
    status: response.status,
    headers: Object.fromEntries(response.headers.entries()),
    data,
  };
}

export async function waitForHealth(baseUrl, timeoutMs = 20_000) {
  const startedAt = Date.now();
  let lastError = null;
  while (Date.now() - startedAt < timeoutMs) {
    try {
      const result = await fetchJson(`${baseUrl}/health`);
      if (result.ok && result.data?.ok) {
        return result.data;
      }
      lastError = new Error(`health_not_ready:${result.status}`);
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  throw lastError || new Error("health_timeout");
}

/**
 * 用测试控制的端口、环境和状态路径启动运行时 API 服务。
 * 测试套件应使用这个辅助函数，而不是手动启动服务进程。
 */
export async function startRuntimeServer(options = {}) {
  const port = options.port || (await reservePort());
  const adminToken = options.adminToken || `token_${randomUUID().slice(0, 10)}`;
  const env = {
    ...process.env,
    MOCK_WORKBENCH_API_PORT: String(port),
    RUNTIME_ADMIN_TOKEN: adminToken,
    ...options.env,
  };
  const child = spawn(
    process.execPath,
    [path.join(workspaceRoot, "tools", "mock_workbench_api_server.mjs")],
    {
      cwd: workspaceRoot,
      env,
      stdio: ["ignore", "pipe", "pipe"],
    }
  );
  const stdout = [];
  const stderr = [];
  child.stdout.on("data", (chunk) => stdout.push(String(chunk)));
  child.stderr.on("data", (chunk) => stderr.push(String(chunk)));
  const baseUrl = `http://127.0.0.1:${port}`;
  try {
    await waitForHealth(baseUrl, options.timeoutMs || 30_000);
  } catch (error) {
    if (child.exitCode === null) {
      child.kill("SIGTERM");
    }
    throw new Error(`${error.message}\n${stderr.join("") || stdout.join("")}`.trim());
  }
  return {
    baseUrl,
    adminToken,
    stdout,
    stderr,
    child,
    async request(pathname, requestOptions = {}) {
      const headers = { ...(requestOptions.headers || {}) };
      if (
        (requestOptions.method || "GET").toUpperCase() === "POST" &&
        !requestOptions.noAdminToken
      ) {
        headers["X-Runtime-Admin-Token"] =
          requestOptions.adminToken || headers["X-Runtime-Admin-Token"] || adminToken;
      }
      return fetchJson(`${baseUrl}${pathname}`, {
        ...requestOptions,
        headers,
      });
    },
    async stop() {
      await stopChildProcess(child);
    },
  };
}

export async function startCompatRuntimeServer(options = {}) {
  const port = options.port || (await reservePort());
  const targetPort = options.targetPort || 8790;
  const env = {
    ...process.env,
    RUNTIME_BACKBONE_API_PORT: String(port),
    MOCK_WORKBENCH_API_PORT: String(targetPort),
    ...(options.env || {}),
  };
  const child = spawn(
    process.execPath,
    [path.join(workspaceRoot, "tools", "runtime_backbone_api_server.mjs")],
    {
      cwd: workspaceRoot,
      env,
      stdio: ["ignore", "pipe", "pipe"],
    }
  );
  const stdout = [];
  const stderr = [];
  child.stdout.on("data", (chunk) => stdout.push(String(chunk)));
  child.stderr.on("data", (chunk) => stderr.push(String(chunk)));
  const baseUrl = `http://127.0.0.1:${port}`;

  const waitForCompatAvailability = async () => {
    const startedAt = Date.now();
    let lastError = null;
    while (Date.now() - startedAt < (options.timeoutMs || 30_000)) {
      try {
        const result = await fetchJson(`${baseUrl}/health`);
        if (result.ok && result.data?.ok) {
          return;
        }
        if (
          options.allowUnavailableHealth &&
          result.status === 503 &&
          result.data?.error === "runtime_backbone_compat_target_unavailable"
        ) {
          return;
        }
        lastError = new Error(`health_not_ready:${result.status}`);
      } catch (error) {
        lastError = error;
      }
      await new Promise((resolve) => setTimeout(resolve, 200));
    }
    throw lastError || new Error("health_timeout");
  };

  if ((options.env || {}).RUNTIME_BACKBONE_COMPAT_ENABLED === "false") {
    await new Promise((resolve) => setTimeout(resolve, 800));
    return {
      baseUrl,
      port,
      stdout,
      stderr,
      child,
      async request(pathname, requestOptions = {}) {
        return fetchJson(`${baseUrl}${pathname}`, requestOptions);
      },
      async stop() {
        await stopChildProcess(child);
      },
    };
  }

  try {
    await waitForCompatAvailability();
  } catch (error) {
    if (child.exitCode === null) {
      child.kill("SIGTERM");
    }
    throw new Error(`${error.message}\n${stderr.join("") || stdout.join("")}`.trim());
  }
  return {
    baseUrl,
    port,
    stdout,
    stderr,
    child,
    async request(pathname, requestOptions = {}) {
      return fetchJson(`${baseUrl}${pathname}`, requestOptions);
    },
    async stop() {
      await stopChildProcess(child);
    },
  };
}

/**
 * 负责临时服务、数据库集群和报告的生命周期清理。
 * 测试把资源登记到这里，即使失败也能保持工作区整洁。
 */
export class RuntimeHarness {
  constructor(options = {}) {
    this.runId = options.runId || makeRunId("production_readiness");
    // Keep the default report location stable for existing suites while
    // allowing release-gate style runners to isolate their artifacts.
    this.reportRoot = options.reportRoot || process.env.RUNTIME_TEST_REPORT_ROOT || reportRoot;
    this.outputDir = path.join(this.reportRoot, this.runId);
    this.cleanupTasks = [];
    this.postgresCluster = null;
    this.createdDatabases = [];
  }

  async init() {
    await ensureDir(this.outputDir);
    return this;
  }

  async ensurePostgresCluster() {
    if (!this.postgresCluster) {
      this.postgresCluster = await startEmbeddedPostgresCluster(this.runId);
      this.cleanupTasks.push(async () => this.postgresCluster.stop());
    }
    return this.postgresCluster;
  }

  async createPostgresDatabase(prefix = "runtime_test") {
    const cluster = await this.ensurePostgresCluster();
    const database = await cluster.createDatabase(prefix);
    this.createdDatabases.push(database.database);
    return database;
  }

  async queryDatabase(connectionString, sql, params = []) {
    const url = new URL(connectionString);
    assertTestDatabaseName(url.pathname.replace(/^\//, ""));
    const pool = new Pool({ connectionString });
    try {
      return await pool.query(sql, params);
    } finally {
      await pool.end();
    }
  }

  async startFileServer(options = {}) {
    const normalized =
      typeof options === "string"
        ? { label: options }
        : options;
    const stateDir = path.win32.join(asciiTempRoot, makeRunId(normalized.label || "file_server"));
    await ensureDir(stateDir);
    const server = await startRuntimeServer({
      env: {
        RUNTIME_STORE: "file",
        RUNTIME_BACKBONE_STATE_DIR: stateDir,
        RUNTIME_BACKBONE_STATE_PATH: path.win32.join(stateDir, "state.json"),
        ...(normalized.env || {}),
      },
    });
    this.cleanupTasks.push(async () => server.stop());
    return server;
  }

  async startPostgresServer(options = {}) {
    const normalized =
      typeof options === "string"
        ? { prefix: options }
        : options;
    const database = normalized.database || (await this.createPostgresDatabase(normalized.prefix || "runtime_test"));
    const server = await startRuntimeServer({
      env: {
        RUNTIME_STORE: "postgres",
        DATABASE_URL_TEST: database.connectionString,
        RUNTIME_BACKBONE_DATABASE_URL: database.connectionString,
        POSTGRES_SOLE_SOURCE: "true",
        ...(normalized.env || {}),
      },
    });
    this.cleanupTasks.push(async () => server.stop());
    return {
      ...server,
      database,
    };
  }

  async startCompatServer(options = {}) {
    const normalized =
      typeof options === "string"
        ? { targetPort: Number(options) }
        : options;
    const server = await startCompatRuntimeServer(normalized);
    this.cleanupTasks.push(async () => server.stop());
    return server;
  }

  async dispose() {
    while (this.cleanupTasks.length) {
      const cleanup = this.cleanupTasks.pop();
      try {
        await cleanup();
      } catch {
        // Best-effort cleanup keeps the report readable and does not hide test failures.
      }
    }
  }
}

export async function createHarness(options = {}) {
  const harness = new RuntimeHarness(options);
  return harness.init();
}

export function toFileUrl(absolutePath) {
  return pathToFileURL(absolutePath).href;
}
