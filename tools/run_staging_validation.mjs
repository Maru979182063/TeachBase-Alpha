/**
 * Purpose:
 * - run a repeatable validation/staging pass against a persistent local Postgres cluster
 * - prove the current backend chain on a dedicated validation database, not on shared or production infra
 *
 * Safety boundaries:
 * - only localhost databases are allowed
 * - database names must contain staging or validation
 * - production-like names are rejected before any write happens
 */

import fs from "node:fs";
import fsp from "node:fs/promises";
import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { Client, Pool } from "pg";

import {
  ensureDir,
  makeRunId,
  runProcess,
  startRuntimeServer,
  workspaceRoot,
} from "../tests/helpers/runtime_testkit.mjs";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const stagingRoot = path.join(workspaceRoot, "outputs", "staging_validation");
const persistentClusterDir = path.join(stagingRoot, "local_pg_cluster");
const persistentClusterLog = path.join(stagingRoot, "local_pg_cluster.log");
const defaultPort = Number(process.env.STAGING_VALIDATION_PGPORT || 55432);
const defaultHost = process.env.STAGING_VALIDATION_PGHOST || "127.0.0.1";
const defaultUser = process.env.STAGING_VALIDATION_PGUSER || "postgres";
const stagingDatabaseName =
  process.env.STAGING_VALIDATION_DB || "teachbase_validation_staging";
const restoreDatabaseName =
  process.env.STAGING_VALIDATION_RESTORE_DB || "teachbase_validation_restore";

const defaultVisualManifestPath = path.join(
  workspaceRoot,
  "outputs",
  "visual_transcription_v0.1",
  "case007_numberline_focus_20260702",
  "runtime_out",
  "06_6_asset_reconcile_refine",
  "reconciled_refined_manifest.json"
);
const defaultVisualAssetBaseDir = path.join(
  workspaceRoot,
  "outputs",
  "visual_transcription_v0.1",
  "case007_numberline_focus_20260702",
  "runtime_out",
  "06_asset_bundle"
);
const defaultRuntimeManifestPath = path.join(
  workspaceRoot,
  "outputs",
  "ingress_runtime_v0.1",
  "english_narrative_teacher_runtime_v01",
  "runtime_manifest.json"
);

function expect(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

function toRelative(targetPath) {
  return path.relative(workspaceRoot, path.resolve(targetPath)).replace(/\\/g, "/");
}

function maskDatabaseUrl(connectionString) {
  const parsed = new URL(connectionString);
  const authPrefix = parsed.username ? `${parsed.username}:***@` : "";
  return `${parsed.protocol}//${authPrefix}${parsed.hostname}:${parsed.port}${parsed.pathname}`;
}

function assertSafeDatabaseName(databaseName) {
  const normalized = String(databaseName || "").trim().toLowerCase();
  expect(normalized.length > 0, "staging_database_name_missing");
  expect(
    /(staging|validation)/i.test(normalized),
    `staging_database_name_missing_validation_marker:${databaseName}`
  );
  expect(
    !/(prod|production|live|main|shared|team)/i.test(normalized),
    `staging_database_name_looks_unsafe:${databaseName}`
  );
}

function assertSafeConnectionString(connectionString) {
  const parsed = new URL(connectionString);
  const databaseName = parsed.pathname.replace(/^\//, "");
  expect(
    ["127.0.0.1", "localhost"].includes(String(parsed.hostname || "").toLowerCase()),
    `staging_database_host_not_local:${parsed.hostname}`
  );
  assertSafeDatabaseName(databaseName);
}

function assertSafeAdminConnectionString(connectionString) {
  const parsed = new URL(connectionString);
  const databaseName = parsed.pathname.replace(/^\//, "");
  expect(
    ["127.0.0.1", "localhost"].includes(String(parsed.hostname || "").toLowerCase()),
    `admin_database_host_not_local:${parsed.hostname}`
  );
  expect(databaseName === "postgres", `admin_database_name_mismatch:${databaseName}`);
}

async function readJsonFile(filePath) {
  return JSON.parse(await fsp.readFile(path.resolve(filePath), "utf8"));
}

async function writeJsonFile(filePath, value) {
  await ensureDir(path.dirname(filePath));
  await fsp.writeFile(filePath, JSON.stringify(value, null, 2), "utf8");
}

async function writeTextFile(filePath, value) {
  await ensureDir(path.dirname(filePath));
  await fsp.writeFile(filePath, value, "utf8");
}

async function appendProgress(logPath, message) {
  const line = `[${new Date().toISOString()}] ${message}\n`;
  await ensureDir(path.dirname(logPath));
  await fsp.appendFile(logPath, line, "utf8");
}

async function withTimeout(promise, timeoutMs, label) {
  let timer = null;
  try {
    return await Promise.race([
      promise,
      new Promise((_, reject) => {
        timer = setTimeout(() => {
          reject(new Error(`${label}_timeout_after_${timeoutMs}ms`));
        }, timeoutMs);
      }),
    ]);
  } finally {
    if (timer) {
      clearTimeout(timer);
    }
  }
}

async function runQuietCommand(command, args = [], options = {}) {
  return new Promise((resolve) => {
    const child = spawn(command, args, {
      cwd: options.cwd || workspaceRoot,
      env: {
        ...process.env,
        ...(options.env || {}),
      },
      shell: false,
      stdio: ["ignore", "ignore", "pipe"],
      windowsHide: true,
    });
    let stderr = "";
    child.stderr.on("data", (chunk) => {
      stderr += String(chunk);
    });
    child.on("error", (error) => {
      resolve({
        code: 1,
        signal: null,
        stderr: `${stderr}${error.message}`,
      });
    });
    child.on("close", (code, signal) => {
      resolve({
        code,
        signal,
        stderr,
      });
    });
  });
}

async function launchPgCtlStart(pgCtlPath, dataDir, logPath, port) {
  return new Promise((resolve, reject) => {
    const child = spawn(
      pgCtlPath,
      ["start", "-D", dataDir, "-l", logPath, "-o", `-p ${port}`],
      {
        cwd: workspaceRoot,
        env: process.env,
        shell: false,
        stdio: "ignore",
        windowsHide: true,
        detached: false,
      }
    );
    child.on("error", reject);
    setTimeout(resolve, 1_000);
  });
}

async function resolvePgTool(toolName) {
  const directHit = process.platform === "win32"
    ? await runProcess("where", [toolName])
    : await runProcess("which", [toolName]);
  if (directHit.code === 0) {
    const first = String(directHit.stdout || "")
      .split(/\r?\n/)
      .map((line) => line.trim())
      .find(Boolean);
    if (first) {
      return first;
    }
  }
  const candidates = [];
  if (process.env.POSTGRES_BIN_DIR) {
    candidates.push(path.join(process.env.POSTGRES_BIN_DIR, `${toolName}.exe`));
  }
  for (const version of ["18", "17", "16", "15"]) {
    candidates.push(
      path.join("C:\\", "Program Files", "PostgreSQL", version, "bin", `${toolName}.exe`)
    );
  }
  for (const candidate of candidates) {
    try {
      await fsp.access(candidate);
      return candidate;
    } catch {
      // Keep scanning local candidates.
    }
  }
  return null;
}

function postgresInstallRoots() {
  const roots = [];
  if (process.env.POSTGRES_BIN_DIR) {
    roots.push(path.resolve(process.env.POSTGRES_BIN_DIR, ".."));
  }
  for (const version of ["18", "17", "16", "15"]) {
    roots.push(path.join("C:\\", "Program Files", "PostgreSQL", version));
  }
  return [...new Set(roots)];
}

async function resolveLocalPostgresInstallation() {
  for (const root of postgresInstallRoots()) {
    const initdb = path.join(root, "bin", "initdb.exe");
    const shareFile = path.join(root, "share", "postgres.bki");
    try {
      await fsp.access(initdb);
      await fsp.access(shareFile);
      return {
        root,
        binDir: path.join(root, "bin"),
        shareFile,
      };
    } catch {
      // Keep scanning for a full local installation with initdb metadata.
    }
  }
  return null;
}

function buildConnectionString(databaseName) {
  assertSafeDatabaseName(databaseName);
  return `postgresql://${encodeURIComponent(defaultUser)}@${defaultHost}:${defaultPort}/${databaseName}`;
}

function buildAdminConnectionString() {
  return `postgresql://${encodeURIComponent(defaultUser)}@${defaultHost}:${defaultPort}/postgres`;
}

async function withPool(connectionString, callback, options = {}) {
  if (options.allowAdminDatabase) {
    assertSafeAdminConnectionString(connectionString);
  } else {
    assertSafeConnectionString(connectionString);
  }
  const pool = new Pool({ connectionString });
  try {
    return await callback(pool);
  } finally {
    await pool.end();
  }
}

async function queryRows(connectionString, sql, params = []) {
  return withPool(connectionString, (pool) => pool.query(sql, params));
}

async function pgCtlStatus(pgCtlPath, dataDir) {
  return runQuietCommand(pgCtlPath, ["status", "-D", dataDir], {
    cwd: workspaceRoot,
  });
}

async function waitForAdminReady(connectionString, timeoutMs = 30_000) {
  const startedAt = Date.now();
  let lastError = null;
  while (Date.now() - startedAt < timeoutMs) {
    const client = new Client({
      connectionString,
      connectionTimeoutMillis: 3_000,
    });
    try {
      await client.connect();
      const result = await client.query("select version() as version");
      return result.rows[0]?.version || "unknown";
    } catch (error) {
      lastError = error;
    } finally {
      await client.end().catch(() => undefined);
    }
    try {
      await new Promise((resolve) => setTimeout(resolve, 500));
    } catch {
      // no-op
    }
  }
  throw new Error(`admin_database_not_ready:${lastError?.message || "timeout"}`);
}

async function ensurePersistentCluster(tools) {
  await ensureDir(stagingRoot);
  await ensureDir(persistentClusterDir);
  const pgVersionFile = path.join(persistentClusterDir, "PG_VERSION");
  const cluster = {
    dataDir: persistentClusterDir,
    logPath: persistentClusterLog,
    host: defaultHost,
    port: defaultPort,
    user: defaultUser,
    initializedNow: false,
    startedNow: false,
    stoppedAtEnd: false,
  };

  if (!fs.existsSync(pgVersionFile)) {
    const initdb = await runProcess(
      tools.initdb,
      [
        "-D",
        persistentClusterDir,
        "-A",
        "trust",
        "-U",
        defaultUser,
        "-E",
        "UTF8",
        "--locale=C",
      ],
      {
        cwd: workspaceRoot,
      }
    );
    expect(initdb.code === 0, `initdb_failed:${initdb.stderr || initdb.stdout}`);
    cluster.initializedNow = true;
  }

  const status = await pgCtlStatus(tools.pgCtl, persistentClusterDir);
  cluster.wasRunningBefore = status.code === 0;
  if (status.code !== 0) {
    await launchPgCtlStart(
      tools.pgCtl,
      persistentClusterDir,
      persistentClusterLog,
      defaultPort
    );
    cluster.startedNow = true;
  }

  const adminConnectionString = buildAdminConnectionString();
  cluster.version = await waitForAdminReady(adminConnectionString);

  cluster.adminConnectionString = adminConnectionString;
  cluster.adminConnectionStringMasked = maskDatabaseUrl(adminConnectionString);
  return cluster;
}

async function stopPersistentClusterIfNeeded(tools, cluster) {
  if (!cluster?.startedNow) {
    return false;
  }
  const stop = await runQuietCommand(
    tools.pgCtl,
    ["stop", "-w", "-D", cluster.dataDir, "-m", "fast"],
    {
      cwd: workspaceRoot,
    }
  );
  expect(stop.code === 0, `pg_ctl_stop_failed:${stop.stderr || stop.stdout}`);
  cluster.stoppedAtEnd = true;
  return true;
}

async function resetDatabase(adminConnectionString, databaseName) {
  assertSafeDatabaseName(databaseName);
  await withPool(adminConnectionString, async (pool) => {
    await pool.query(
      `
        select pg_terminate_backend(pid)
        from pg_stat_activity
        where datname = $1
          and pid <> pg_backend_pid()
      `,
      [databaseName]
    );
    await pool.query(`drop database if exists "${databaseName}"`);
    await pool.query(`create database "${databaseName}"`);
  }, { allowAdminDatabase: true });
  const connectionString = buildConnectionString(databaseName);
  return {
    databaseName,
    connectionString,
    maskedConnectionString: maskDatabaseUrl(connectionString),
  };
}

async function collectMigrationList() {
  const names = await fsp.readdir(path.join(workspaceRoot, "config", "migrations"));
  return names.filter((name) => name.endsWith(".sql")).sort();
}

async function collectPublicTables(connectionString) {
  const result = await queryRows(
    connectionString,
    `
      select tablename
      from pg_tables
      where schemaname = 'public'
      order by tablename
    `
  );
  return result.rows.map((row) => row.tablename);
}

async function collectCoreCounts(connectionString) {
  const result = await queryRows(
    connectionString,
    `
      select
        (select count(*)::int from lesson) as lesson_count,
        (select count(*)::int from lesson_revision) as lesson_revision_count,
        (select count(*)::int from task_projection) as task_projection_count,
        (select count(*)::int from question_bank_item) as question_bank_item_count,
        (select count(*)::int from question_bank_item_revision) as question_bank_item_revision_count,
        (select count(*)::int from publication) as publication_count,
        (select count(*)::int from material_build) as material_build_count,
        (select count(*)::int from material_item) as material_item_count,
        (select count(*)::int from artifact) as artifact_count,
        (select count(*)::int from component_patch_candidate) as component_patch_candidate_count,
        (select count(*)::int from runtime_state_snapshot) as runtime_state_snapshot_count
    `
  );
  return result.rows[0];
}

function findLessonRevisionBundle(detail, lessonRevisionId) {
  return (
    detail?.lessonRevisions?.find((item) => item.lesson_revision_id === lessonRevisionId)?.bundle_jsonb ||
    null
  );
}

function firstCheckpoint(task) {
  return (
    task?.checkpoint_codes?.[0] ||
    task?.subject_tags?.[0] ||
    task?.source_refs_json?.runtime_manifest?.label ||
    "checkpoint"
  );
}

function firstSourcePage(task) {
  const refs = task?.source_refs_json || {};
  return (
    refs.page_no ||
    refs.runtime_manifest?.start_page ||
    refs.question_visual_structure?.source_page ||
    1
  );
}

function buildExportPayloadFromBundle(bundle, options = {}) {
  const selectedLocalTaskIds =
    Array.isArray(options.selectedLocalTaskIds) && options.selectedLocalTaskIds.length
      ? new Set(options.selectedLocalTaskIds)
      : null;
  const tasks = (bundle.tasks || []).filter((task) =>
    selectedLocalTaskIds ? selectedLocalTaskIds.has(task.local_task_id) : true
  );
  return {
    lesson: {
      lesson_id: bundle.lesson_id,
      lesson_title: bundle.title,
      subject: bundle.subject,
      track_code: bundle.track_code,
      stage: bundle.stage,
      grade: bundle.grade,
      season: bundle.season,
      lesson_no: 1,
      source_pdf_name: `${bundle.lesson_id}.pdf`,
      knowledge_point_count: Array.isArray(bundle.source_tree) ? bundle.source_tree.length : 1,
      objectives: options.objectives || "staging validation export",
    },
    splitLesson: {
      lesson_id: bundle.lesson_id,
      assetBaseDir: options.assetBaseDir || null,
      question_count: tasks.length,
      tree: [
        {
          module: bundle.title || bundle.lesson_id,
          items: (bundle.source_tree || []).map(
            (item) => item.title || item.source_node_local_id || "root"
          ),
        },
      ],
      auditSummary: {
        reviewedCount: tasks.length,
        pendingCount: 0,
      },
      questions: tasks.map((task, index) => ({
        id: `${bundle.lesson_id}_export_${index + 1}`,
        localTaskId: task.local_task_id,
        localNumber: task.local_task_id,
        checkpoint: firstCheckpoint(task),
        componentLabel: task.question_type || "question",
        sourcePage: firstSourcePage(task),
        stem: task.stem || "",
        answer: task.answer || "",
        explanation: task.explanation || "",
        versionTags: ["base"],
        effectiveVersionTags: ["base"],
        question_visual_structure:
          task.question_visual_structure ||
          task.source_refs_json?.question_visual_structure ||
          null,
      })),
    },
    reviewQueue: [],
    selectedVersions: ["base"],
    selectedAudiences: ["teacher"],
    selectedFormats: ["DOCX"],
    includeCompass: false,
  };
}

function collectStorageKeySamples(bundle) {
  const samples = [];
  for (const task of bundle.tasks || []) {
    const qvs =
      task.question_visual_structure ||
      task.source_refs_json?.question_visual_structure ||
      null;
    for (const asset of qvs?.visual_assets || []) {
      if (asset?.storage_key) {
        samples.push({
          localTaskId: task.local_task_id,
          assetId: asset.asset_id,
          storageKey: asset.storage_key,
        });
      }
      if (samples.length >= 5) {
        return samples;
      }
    }
  }
  return samples;
}

async function verifyOutputFiles(fileItems = []) {
  const verified = [];
  for (const item of fileItems) {
    const absolutePath = path.isAbsolute(item.path)
      ? item.path
      : path.join(workspaceRoot, item.relativePath || "");
    const stats = await fsp.stat(absolutePath);
    expect(stats.size > 0, `export_file_empty:${absolutePath}`);
    verified.push({
      ...item,
      absolutePath,
      relativePath: item.relativePath || toRelative(absolutePath),
      size: Number(item.size || stats.size),
    });
  }
  return verified;
}

async function fetchLineageNodeCount(server, artifactId) {
  const lineage = await server.request(`/api/runtime/artifacts/${artifactId}/lineage`);
  expect(lineage.ok, `artifact_lineage_failed:${JSON.stringify(lineage.data)}`);
  return (lineage.data?.detail?.nodes || []).length;
}

async function approveAndPublish(server, lessonId, reviewTaskId, lessonRevisionId, actorPrefix) {
  const approved = await server.request(`/api/runtime/review-tasks/${reviewTaskId}/approve`, {
    method: "POST",
    body: {
      actor: `${actorPrefix}_reviewer`,
    },
  });
  expect(approved.ok, `${actorPrefix}_approve_failed:${JSON.stringify(approved.data)}`);

  const published = await server.request(`/api/runtime/lessons/${lessonId}/publish`, {
    method: "POST",
    body: {
      actor: `${actorPrefix}_publisher`,
      lessonRevisionId,
    },
  });
  expect(published.ok, `${actorPrefix}_publish_failed:${JSON.stringify(published.data)}`);
  return {
    approved: approved.data.result,
    published: published.data.result,
  };
}

async function createQuestionBankItems(server, projectionItems, actorPrefix, limit = projectionItems.length) {
  const revisionIds = [];
  const selectedItems = projectionItems.slice(0, limit);
  for (const item of selectedItems) {
    const created = await server.request("/api/question-bank/items", {
      method: "POST",
      body: {
        actor: `${actorPrefix}_qb`,
        taskProjectionId: item.task_projection_id,
      },
    });
    expect(created.ok, `${actorPrefix}_question_bank_create_failed:${JSON.stringify(created.data)}`);
    revisionIds.push(created.data.result.revision.question_bank_item_revision_id);
  }
  return revisionIds;
}

async function createMaterialBuild(server, lessonId, revisionIds, actorPrefix) {
  const build = await server.request("/api/material-builds", {
    method: "POST",
    body: {
      actor: `${actorPrefix}_material`,
      lessonId,
      teacherName: "validation_teacher",
      buildName: `${actorPrefix}_build`,
    },
  });
  expect(build.ok, `${actorPrefix}_material_build_failed:${JSON.stringify(build.data)}`);
  const materialBuildId = build.data.result.material_build_id;

  const addItems = await server.request(`/api/material-builds/${materialBuildId}/items`, {
    method: "POST",
    body: {
      items: revisionIds.map((revisionId, index) => ({
        questionBankItemRevisionId: revisionId,
        sectionKey: "body",
        sortIndex: index + 1,
        includeAnswer: true,
        includeExplanation: true,
      })),
    },
  });
  expect(addItems.ok, `${actorPrefix}_material_items_failed:${JSON.stringify(addItems.data)}`);

  const exported = await server.request(`/api/material-builds/${materialBuildId}/export`, {
    method: "POST",
    body: {
      actor: `${actorPrefix}_material_exporter`,
    },
  });
  expect(exported.ok, `${actorPrefix}_material_export_failed:${JSON.stringify(exported.data)}`);
  return {
    materialBuildId,
    materialItemCount: revisionIds.length,
    materialExportArtifactId: exported.data.result.artifact.artifact_id,
  };
}

async function rerunFirstComponent(server, lessonDetail, actorPrefix) {
  const componentId = lessonDetail?.componentRevisions?.[0]?.component_id;
  expect(componentId, `${actorPrefix}_component_missing`);
  const rerun = await server.request(`/api/runtime/components/${componentId}/rerun`, {
    method: "POST",
    body: {
      actor: `${actorPrefix}_rerun`,
      proposedText: `${actorPrefix} validation rerun text`,
      note: `${actorPrefix} validation rerun`,
    },
  });
  expect(rerun.ok, `${actorPrefix}_component_rerun_failed:${JSON.stringify(rerun.data)}`);
  const patchId = rerun.data.result.patch.component_patch_candidate_id;
  const accepted = await server.request(`/api/runtime/component-patches/${patchId}/accept`, {
    method: "POST",
    body: {
      actor: `${actorPrefix}_rerun_reviewer`,
    },
  });
  expect(accepted.ok, `${actorPrefix}_component_patch_accept_failed:${JSON.stringify(accepted.data)}`);
  return {
    componentId,
    patchId,
    rerunRevisionId: accepted.data.result.rerunResult.activeRevisionId,
  };
}

async function loadLessonDetail(server, lessonId, actorPrefix) {
  const detail = await server.request(`/api/runtime/lessons/${lessonId}`);
  expect(detail.ok, `${actorPrefix}_lesson_detail_failed:${JSON.stringify(detail.data)}`);
  return detail.data.detail;
}

async function searchLessonProjections(server, searchPath, lessonId, actorPrefix) {
  const response = await server.request(searchPath);
  expect(response.ok, `${actorPrefix}_projection_search_failed:${JSON.stringify(response.data)}`);
  return (response.data.items || []).filter((item) => item.lesson_id === lessonId);
}

async function searchQuestionBank(server, searchPath, actorPrefix) {
  const response = await server.request(searchPath);
  expect(response.ok, `${actorPrefix}_question_bank_search_failed:${JSON.stringify(response.data)}`);
  return response.data.items || [];
}

async function runVisualBatchValidation(server, report) {
  const manifestPath = process.env.STAGING_VALIDATION_VISUAL_MANIFEST || defaultVisualManifestPath;
  const assetBaseDir =
    process.env.STAGING_VALIDATION_VISUAL_ASSET_BASE || defaultVisualAssetBaseDir;
  const manifest = await readJsonFile(manifestPath);

  const lessonId = "staging_case007_visual";
  const bundleId = "staging_case007_visual_bundle";
  const importResponse = await server.request("/api/runtime/imports/lesson-draft-bundles", {
    method: "POST",
    body: {
      actor: "staging_visual",
      ...manifest,
      bundle_id: bundleId,
      lesson_id: lessonId,
      title: "Case007 Visual Validation",
      subject: "数学",
      stage: "junior",
      track_code: "math_junior",
      grade: "g7",
      season: "summer",
      runtime_run_id: "staging_case007_visual",
      source_tree: [
        {
          source_node_local_id: "root",
          node_type: "lesson",
          phase: "knowledge_main",
          title: "Case007 Visual Validation",
          checkpoint_codes: ["数轴上的点与平移"],
        },
      ],
    },
  });
  expect(importResponse.ok, `staging_visual_import_failed:${JSON.stringify(importResponse.data)}`);

  const published = await approveAndPublish(
    server,
    lessonId,
    importResponse.data.result.reviewTaskId,
    importResponse.data.result.lessonRevisionId,
    "staging_visual"
  );
  let detail = await loadLessonDetail(server, lessonId, "staging_visual");
  let bundle = findLessonRevisionBundle(detail, importResponse.data.result.lessonRevisionId);
  expect(bundle, "staging_visual_bundle_missing");

  const projectionItems = await searchLessonProjections(
    server,
    `/api/runtime/task-projections/search?subject=${encodeURIComponent("数学")}&stage=junior&trackCode=math_junior&publishedOnly=true`,
    lessonId,
    "staging_visual"
  );
  expect(projectionItems.length >= 1, "staging_visual_projection_missing");

  const questionBankRevisionIds = await createQuestionBankItems(
    server,
    projectionItems,
    "staging_visual",
    1
  );
  const questionBankItems = await searchQuestionBank(
    server,
    `/api/question-bank/search?subject=${encodeURIComponent("数学")}&stage=junior&trackCode=math_junior`,
    "staging_visual"
  );
  const material = await createMaterialBuild(
    server,
    lessonId,
    questionBankRevisionIds,
    "staging_visual"
  );
  const rerun = await rerunFirstComponent(server, detail, "staging_visual");

  detail = await loadLessonDetail(server, lessonId, "staging_visual_after_rerun");
  bundle = findLessonRevisionBundle(detail, rerun.rerunRevisionId) || bundle;

  const exportPayload = buildExportPayloadFromBundle(bundle, {
    assetBaseDir,
    objectives: "staging validation visual export",
  });
  const exportResponse = await server.request("/api/export/generate", {
    method: "POST",
    body: exportPayload,
  });
  expect(exportResponse.ok, `staging_visual_export_failed:${JSON.stringify(exportResponse.data)}`);
  const files = await verifyOutputFiles(exportResponse.data.item.files || []);
  const exportArtifactId = exportResponse.data.item.runtime.exportArtifactId;
  const lineageNodeCount = await fetchLineageNodeCount(server, exportArtifactId);

  return {
    status: "passed",
    assumption:
      "track metadata is inferred as math_junior because the visual manifest itself does not carry authoritative subject/stage/track fields",
    manifestPath: toRelative(manifestPath),
    assetBaseDir: toRelative(assetBaseDir),
    lessonId,
    bundleId,
    reviewTaskId: importResponse.data.result.reviewTaskId,
    lessonRevisionId: importResponse.data.result.lessonRevisionId,
    publicationId: published.published.publication.publication_id,
    importedQuestionCount: Array.isArray(bundle.tasks) ? bundle.tasks.length : 0,
    validationIssueCount: Array.isArray(bundle.validation_issues) ? bundle.validation_issues.length : 0,
    projectionSearchCount: projectionItems.length,
    questionBankCreated: questionBankRevisionIds.length,
    questionBankSearchCount: questionBankItems.filter((item) => item.item?.track_code === "math_junior").length,
    materialBuildId: material.materialBuildId,
    materialItemCount: material.materialItemCount,
    materialExportArtifactId: material.materialExportArtifactId,
    componentId: rerun.componentId,
    patchId: rerun.patchId,
    rerunRevisionId: rerun.rerunRevisionId,
    exportRunId: exportResponse.data.item.runtime.exportRunId,
    exportArtifactId,
    exportPreflight: exportResponse.data.item.preflight,
    exportFiles: files.map((file) => ({
      name: file.name,
      relativePath: file.relativePath,
      format: file.format,
      version: file.version,
      audience: file.audience,
      questionCount: file.questionCount,
      size: file.size,
    })),
    lineageNodeCount,
    storageKeySamples: collectStorageKeySamples(bundle),
  };
}

async function runEnglishRuntimeValidation(server, report) {
  const manifestPath = process.env.STAGING_VALIDATION_RUNTIME_MANIFEST || defaultRuntimeManifestPath;
  const manifest = await readJsonFile(manifestPath);
  const baseDir =
    process.env.STAGING_VALIDATION_RUNTIME_BASE_DIR || path.dirname(path.resolve(manifestPath));

  const lessonId = "staging_english_runtime_manifest";
  const requestBody = {
    actor: "staging_english",
    lesson_id: lessonId,
    title: "English Runtime Manifest Validation",
    subject: "英语",
    stage: "senior",
    track_code: "english_senior",
    grade: "g11",
    season: "summer",
    base_dir: baseDir,
    manifest_path: manifestPath,
    document_metadata: {
      lesson_title: "English Runtime Manifest Validation",
      source_pdf_name: path.basename(manifest.source_pdf || "english_runtime_manifest.pdf"),
    },
    runtime_manifest: manifest,
  };

  const importResponse = await server.request("/api/runtime/imports/runtime-manifest", {
    method: "POST",
    body: requestBody,
  });
  expect(importResponse.ok, `staging_english_import_failed:${JSON.stringify(importResponse.data)}`);

  const published = await approveAndPublish(
    server,
    lessonId,
    importResponse.data.result.reviewTaskId,
    importResponse.data.result.lessonRevisionId,
    "staging_english"
  );

  let detail = await loadLessonDetail(server, lessonId, "staging_english");
  let bundle = findLessonRevisionBundle(detail, importResponse.data.result.lessonRevisionId);
  expect(bundle, "staging_english_bundle_missing");

  const projectionItems = await searchLessonProjections(
    server,
    `/api/runtime/task-projections/search?subject=${encodeURIComponent("英语")}&stage=senior&trackCode=english_senior&publishedOnly=true`,
    lessonId,
    "staging_english"
  );
  expect(projectionItems.length >= 8, "staging_english_projection_count_too_small");

  const questionBankRevisionIds = await createQuestionBankItems(
    server,
    projectionItems,
    "staging_english",
    8
  );
  const questionBankItems = await searchQuestionBank(
    server,
    `/api/question-bank/search?subject=${encodeURIComponent("英语")}&stage=senior&trackCode=english_senior`,
    "staging_english"
  );
  const material = await createMaterialBuild(
    server,
    lessonId,
    questionBankRevisionIds,
    "staging_english"
  );
  const rerun = await rerunFirstComponent(server, detail, "staging_english");

  detail = await loadLessonDetail(server, lessonId, "staging_english_after_rerun");
  bundle = findLessonRevisionBundle(detail, rerun.rerunRevisionId) || bundle;

  const selectedLocalTaskIds = projectionItems
    .slice(0, 8)
    .map((item) => item.local_task_id)
    .filter(Boolean);
  const exportPayload = buildExportPayloadFromBundle(bundle, {
    selectedLocalTaskIds,
    objectives: "staging validation english export",
  });
  const exportResponse = await server.request("/api/export/generate", {
    method: "POST",
    body: exportPayload,
  });
  expect(exportResponse.ok, `staging_english_export_failed:${JSON.stringify(exportResponse.data)}`);
  const files = await verifyOutputFiles(exportResponse.data.item.files || []);
  const exportArtifactId = exportResponse.data.item.runtime.exportArtifactId;
  const lineageNodeCount = await fetchLineageNodeCount(server, exportArtifactId);

  return {
    status: "passed",
    manifestPath: toRelative(manifestPath),
    baseDir: toRelative(baseDir),
    lessonId,
    bundleId: bundle.bundle_id,
    reviewTaskId: importResponse.data.result.reviewTaskId,
    lessonRevisionId: importResponse.data.result.lessonRevisionId,
    publicationId: published.published.publication.publication_id,
    importedQuestionCount: Array.isArray(bundle.tasks) ? bundle.tasks.length : 0,
    validationIssueCount: Array.isArray(bundle.validation_issues) ? bundle.validation_issues.length : 0,
    projectionSearchCount: projectionItems.length,
    questionBankCreated: questionBankRevisionIds.length,
    questionBankSearchCount: questionBankItems.filter((item) => item.item?.track_code === "english_senior").length,
    materialBuildId: material.materialBuildId,
    materialItemCount: material.materialItemCount,
    materialExportArtifactId: material.materialExportArtifactId,
    componentId: rerun.componentId,
    patchId: rerun.patchId,
    rerunRevisionId: rerun.rerunRevisionId,
    exportRunId: exportResponse.data.item.runtime.exportRunId,
    exportArtifactId,
    exportPreflight: exportResponse.data.item.preflight,
    exportFiles: files.map((file) => ({
      name: file.name,
      relativePath: file.relativePath,
      format: file.format,
      version: file.version,
      audience: file.audience,
      questionCount: file.questionCount,
      size: file.size,
    })),
    lineageNodeCount,
  };
}

async function runBackupRestore(tools, stagingDatabase, restoreDatabase, reportOutputDir) {
  const backupDir = path.join(reportOutputDir, "backups");
  await ensureDir(backupDir);
  const backupFile = path.join(backupDir, `${new Date().toISOString().replace(/[:.]/g, "-")}.dump`);
  const dump = await runProcess(
    tools.pgDump,
    [
      `--dbname=${stagingDatabase.connectionString}`,
      "--format=custom",
      `--file=${backupFile}`,
    ],
    {
      cwd: workspaceRoot,
    }
  );
  expect(dump.code === 0, `staging_pg_dump_failed:${dump.stderr || dump.stdout}`);

  const restore = await runProcess(
    tools.pgRestore,
    [
      `--dbname=${restoreDatabase.connectionString}`,
      "--clean",
      "--if-exists",
      "--no-owner",
      backupFile,
    ],
    {
      cwd: workspaceRoot,
    }
  );
  expect(restore.code === 0, `staging_pg_restore_failed:${restore.stderr || restore.stdout}`);

  const [beforeCounts, afterCounts] = await Promise.all([
    collectCoreCounts(stagingDatabase.connectionString),
    collectCoreCounts(restoreDatabase.connectionString),
  ]);

  expect(
    JSON.stringify(beforeCounts) === JSON.stringify(afterCounts),
    `staging_backup_restore_count_mismatch:${JSON.stringify({ beforeCounts, afterCounts })}`
  );

  return {
    backupFile: toRelative(backupFile),
    beforeCounts,
    afterCounts,
  };
}

async function runRestartChecks(server, visualResult, englishResult, stagingConnectionString) {
  const visualSearch = await searchLessonProjections(
    server,
    `/api/runtime/task-projections/search?subject=${encodeURIComponent("数学")}&stage=junior&trackCode=math_junior&publishedOnly=true`,
    visualResult.lessonId,
    "restart_visual"
  );
  const englishSearch = await searchLessonProjections(
    server,
    `/api/runtime/task-projections/search?subject=${encodeURIComponent("英语")}&stage=senior&trackCode=english_senior&publishedOnly=true`,
    englishResult.lessonId,
    "restart_english"
  );
  const questionBankItems = await searchQuestionBank(
    server,
    `/api/question-bank/search?subject=${encodeURIComponent("英语")}&stage=senior&trackCode=english_senior`,
    "restart_english"
  );
  const detail = await loadLessonDetail(server, visualResult.lessonId, "restart_visual");
  const materialRows = await queryRows(
    stagingConnectionString,
    `
      select lesson_id, material_build_id
      from material_build
      where lesson_id in ($1, $2)
      order by created_at asc
    `,
    [visualResult.lessonId, englishResult.lessonId]
  );
  return {
    visualProjectionCount: visualSearch.length,
    englishProjectionCount: englishSearch.length,
    englishQuestionBankCount: questionBankItems.filter(
      (item) => item.item?.track_code === "english_senior"
    ).length,
    materialBuildRows: materialRows.rows,
    publicationIdsStillReadable: [
      visualResult.publicationId,
      englishResult.publicationId,
    ],
    visualLessonLoaded: detail.lesson.lesson_id === visualResult.lessonId,
  };
}

function buildMarkdownReport(report) {
  const visualFiles = (report.visualBatch?.exportFiles || [])
    .map((file) => `- ${file.relativePath} (${file.size} bytes)`)
    .join("\n");
  const englishFiles = (report.englishRuntime?.exportFiles || [])
    .map((file) => `- ${file.relativePath} (${file.size} bytes)`)
    .join("\n");
  const maskedDb = report.database?.maskedConnectionString || "not-available";
  const publicTableCount = report.tableSummary?.publicTableCount ?? "not-available";
  const runtimeSnapshotRows =
    report.tableSummary?.runtimeStateSnapshotRowCount ?? "not-available";
  return [
    "# Staging Runtime Validation",
    "",
    `- Run ID: ${report.runId}`,
    `- Generated At: ${report.generatedAt}`,
    `- Git Branch: ${report.gitBranch}`,
    `- Git Commit: ${report.gitCommit}`,
    `- Masked DB: ${maskedDb}`,
    `- Public Tables: ${publicTableCount}`,
    `- Runtime Snapshot Rows: ${runtimeSnapshotRows}`,
    `- Recommendation: ${report.recommendation}`,
    `- Production Position: ${report.productionPosition}`,
    "",
    "## Visual Batch",
    `- Manifest: ${report.visualBatch?.manifestPath || "not-run"}`,
    `- Lesson ID: ${report.visualBatch?.lessonId || "not-run"}`,
    `- Publication ID: ${report.visualBatch?.publicationId || "not-run"}`,
    `- Export Artifact ID: ${report.visualBatch?.exportArtifactId || "not-run"}`,
    `- Export Run ID: ${report.visualBatch?.exportRunId || "not-run"}`,
    `- Preflight Checked: ${report.visualBatch?.exportPreflight?.checkedQuestionCount ?? "not-run"}`,
    visualFiles || "- no visual export files recorded",
    "",
    "## English Runtime Manifest",
    `- Manifest: ${report.englishRuntime?.manifestPath || "not-run"}`,
    `- Lesson ID: ${report.englishRuntime?.lessonId || "not-run"}`,
    `- Publication ID: ${report.englishRuntime?.publicationId || "not-run"}`,
    `- Export Artifact ID: ${report.englishRuntime?.exportArtifactId || "not-run"}`,
    `- Export Run ID: ${report.englishRuntime?.exportRunId || "not-run"}`,
    `- Imported Questions: ${report.englishRuntime?.importedQuestionCount ?? "not-run"}`,
    `- Question Bank Created: ${report.englishRuntime?.questionBankCreated ?? "not-run"}`,
    englishFiles || "- no english export files recorded",
    "",
    "## Backup Restore",
    `- Backup File: ${report.backupRestore?.backupFile || "not-run"}`,
    "",
    "## Restart Checks",
    `- Visual projection count after restart: ${report.restartChecks?.visualProjectionCount ?? "not-run"}`,
    `- English projection count after restart: ${report.restartChecks?.englishProjectionCount ?? "not-run"}`,
    `- English question bank count after restart: ${report.restartChecks?.englishQuestionBankCount ?? "not-run"}`,
    "",
    "## Warnings",
    ...(report.p1Warnings.length ? report.p1Warnings.map((item) => `- ${item}`) : ["- none"]),
    "",
    "## Blockers",
    ...(report.p0Blockers.length ? report.p0Blockers.map((item) => `- ${item}`) : ["- none"]),
  ].join("\n");
}

async function main() {
  const runId = makeRunId("staging_validation");
  const outputDir = path.join(stagingRoot, runId);
  await ensureDir(outputDir);
  const progressLogPath = path.join(outputDir, "progress.log");

  const report = {
    runId,
    generatedAt: new Date().toISOString(),
    outputDir: toRelative(outputDir),
    p0Blockers: [],
    p1Warnings: [],
    productionPosition: "NOT_READY_FOR_PRODUCTION",
    backgroundProcesses: {
      runtimeServerRunningAtEnd: false,
      postgresClusterRunningAtEnd: false,
    },
    progressLog: toRelative(progressLogPath),
  };

  let runtimeServer = null;
  let restartedServer = null;
  let cluster = null;

  const installation = await resolveLocalPostgresInstallation();
  const tools = installation
    ? {
        initdb: path.join(installation.binDir, "initdb.exe"),
        pgCtl: path.join(installation.binDir, "pg_ctl.exe"),
        psql: path.join(installation.binDir, "psql.exe"),
        pgDump: path.join(installation.binDir, "pg_dump.exe"),
        pgRestore: path.join(installation.binDir, "pg_restore.exe"),
      }
    : {
        initdb: await resolvePgTool("initdb"),
        pgCtl: await resolvePgTool("pg_ctl"),
        psql: await resolvePgTool("psql"),
        pgDump: await resolvePgTool("pg_dump"),
        pgRestore: await resolvePgTool("pg_restore"),
      };

  try {
    await appendProgress(progressLogPath, "resolving local postgres toolset");
    expect(tools.initdb, "initdb_not_available");
    expect(tools.pgCtl, "pg_ctl_not_available");
    expect(tools.psql, "psql_not_available");
    expect(tools.pgDump, "pg_dump_not_available");
    expect(tools.pgRestore, "pg_restore_not_available");

    const [gitCommit, gitBranch, migrations] = await Promise.all([
      runProcess("git", ["rev-parse", "HEAD"]),
      runProcess("git", ["branch", "--show-current"]),
      collectMigrationList(),
    ]);
    report.gitCommit = gitCommit.code === 0 ? gitCommit.stdout.trim() : "unknown";
    report.gitBranch = gitBranch.code === 0 ? gitBranch.stdout.trim() : "unknown";
    report.migrations = migrations;

    await appendProgress(progressLogPath, "starting or reusing persistent local postgres cluster");
    cluster = await withTimeout(
      ensurePersistentCluster(tools),
      120_000,
      "ensure_persistent_cluster"
    );
    report.cluster = {
      dataDir: toRelative(cluster.dataDir),
      logPath: toRelative(cluster.logPath),
      host: cluster.host,
      port: cluster.port,
      user: cluster.user,
      version: cluster.version,
      installationRoot: installation ? installation.root : "path-resolved-tools",
      initializedNow: cluster.initializedNow,
      startedNow: cluster.startedNow,
    };

    await appendProgress(progressLogPath, `resetting staging database ${stagingDatabaseName}`);
    const stagingDatabase = await withTimeout(
      resetDatabase(cluster.adminConnectionString, stagingDatabaseName),
      60_000,
      "reset_staging_database"
    );
    await appendProgress(progressLogPath, `resetting restore database ${restoreDatabaseName}`);
    const restoreDatabase = await withTimeout(
      resetDatabase(cluster.adminConnectionString, restoreDatabaseName),
      60_000,
      "reset_restore_database"
    );
    report.database = {
      databaseName: stagingDatabase.databaseName,
      maskedConnectionString: stagingDatabase.maskedConnectionString,
      restoreDatabaseName: restoreDatabase.databaseName,
    };

    await appendProgress(progressLogPath, "starting runtime api on 8790-compatible server");
    runtimeServer = await withTimeout(
      startRuntimeServer({
        env: {
          RUNTIME_STORE: "postgres",
          DATABASE_URL_TEST: stagingDatabase.connectionString,
          RUNTIME_BACKBONE_DATABASE_URL: stagingDatabase.connectionString,
          POSTGRES_SOLE_SOURCE: "true",
          RUNTIME_RATE_LIMIT_WINDOW_MS: process.env.RUNTIME_RATE_LIMIT_WINDOW_MS || "2000",
          RUNTIME_RATE_LIMIT_MAX_REQUESTS: process.env.RUNTIME_RATE_LIMIT_MAX_REQUESTS || "500",
        },
        timeoutMs: 60_000,
      }),
      90_000,
      "start_runtime_server"
    );
    report.runtimeApi = {
      baseUrl: runtimeServer.baseUrl,
    };

    await appendProgress(progressLogPath, "collecting migrated table summary");
    const publicTables = await collectPublicTables(stagingDatabase.connectionString);
    expect(publicTables.length === 43, `public_table_count_mismatch:${publicTables.length}`);
    const countsAfterMigrate = await collectCoreCounts(stagingDatabase.connectionString);
    report.tableSummary = {
      publicTableCount: publicTables.length,
      publicTables,
      afterMigrate: countsAfterMigrate,
      runtimeStateSnapshotRowCount: Number(
        countsAfterMigrate.runtime_state_snapshot_count || 0
      ),
    };

    try {
      await appendProgress(progressLogPath, "running visual batch validation");
      report.visualBatch = await withTimeout(
        runVisualBatchValidation(runtimeServer, report),
        300_000,
        "visual_batch_validation"
      );
      await appendProgress(progressLogPath, "visual batch validation passed");
    } catch (error) {
      report.visualBatch = {
        status: "failed",
        error: error.message,
      };
      report.p0Blockers.push(`visual_batch:${error.message}`);
      await appendProgress(progressLogPath, `visual batch validation failed: ${error.message}`);
    }

    try {
      await appendProgress(progressLogPath, "running english runtime manifest validation");
      report.englishRuntime = await withTimeout(
        runEnglishRuntimeValidation(runtimeServer, report),
        300_000,
        "english_runtime_validation"
      );
      await appendProgress(progressLogPath, "english runtime manifest validation passed");
    } catch (error) {
      report.englishRuntime = {
        status: "failed",
        error: error.message,
      };
      report.p0Blockers.push(`english_runtime:${error.message}`);
      await appendProgress(progressLogPath, `english runtime manifest validation failed: ${error.message}`);
    }

    const countsBeforeBackup = await collectCoreCounts(stagingDatabase.connectionString);
    report.tableSummary.beforeBackup = countsBeforeBackup;
    report.tableSummary.runtimeStateSnapshotRowCount = Number(
      countsBeforeBackup.runtime_state_snapshot_count || 0
    );
    if (report.tableSummary.runtimeStateSnapshotRowCount !== 0) {
      report.p1Warnings.push(
        `runtime_state_snapshot_rows_present:${report.tableSummary.runtimeStateSnapshotRowCount}`
      );
    }

    try {
      await appendProgress(progressLogPath, "running backup restore smoke");
      report.backupRestore = await withTimeout(
        runBackupRestore(tools, stagingDatabase, restoreDatabase, outputDir),
        300_000,
        "backup_restore_validation"
      );
      await appendProgress(progressLogPath, "backup restore smoke passed");
    } catch (error) {
      report.backupRestore = {
        status: "failed",
        error: error.message,
      };
      report.p0Blockers.push(`backup_restore:${error.message}`);
      await appendProgress(progressLogPath, `backup restore smoke failed: ${error.message}`);
    }

    if (runtimeServer) {
      await appendProgress(progressLogPath, "stopping runtime api before restart check");
      await runtimeServer.stop();
      runtimeServer = null;
    }

    await appendProgress(progressLogPath, "restarting runtime api for persistence checks");
    restartedServer = await withTimeout(
      startRuntimeServer({
        env: {
          RUNTIME_STORE: "postgres",
          DATABASE_URL_TEST: stagingDatabase.connectionString,
          RUNTIME_BACKBONE_DATABASE_URL: stagingDatabase.connectionString,
          POSTGRES_SOLE_SOURCE: "true",
          RUNTIME_RATE_LIMIT_WINDOW_MS: process.env.RUNTIME_RATE_LIMIT_WINDOW_MS || "2000",
          RUNTIME_RATE_LIMIT_MAX_REQUESTS: process.env.RUNTIME_RATE_LIMIT_MAX_REQUESTS || "500",
        },
        timeoutMs: 60_000,
      }),
      90_000,
      "restart_runtime_server"
    );

    if (report.visualBatch?.status === "passed" && report.englishRuntime?.status === "passed") {
      try {
        await appendProgress(progressLogPath, "running restart checks");
        report.restartChecks = await withTimeout(
          runRestartChecks(
            restartedServer,
            report.visualBatch,
            report.englishRuntime,
            stagingDatabase.connectionString
          ),
          180_000,
          "restart_checks_validation"
        );
        await appendProgress(progressLogPath, "restart checks passed");
      } catch (error) {
        report.restartChecks = {
          status: "failed",
          error: error.message,
        };
        report.p0Blockers.push(`restart_checks:${error.message}`);
        await appendProgress(progressLogPath, `restart checks failed: ${error.message}`);
      }
    } else {
      report.restartChecks = {
        status: "skipped",
        reason: "upstream_validation_failed",
      };
      await appendProgress(progressLogPath, "restart checks skipped because an upstream validation step failed");
    }

    const finalCounts = await collectCoreCounts(stagingDatabase.connectionString);
    report.tableSummary.final = finalCounts;
    report.tableSummary.runtimeStateSnapshotRowCount = Number(
      finalCounts.runtime_state_snapshot_count || 0
    );

    report.recommendation =
      report.p0Blockers.length === 0 ? "GO_FOR_VALIDATION" : "HOLD_FOR_FIXES";
  } catch (error) {
    report.fatalError = error.message;
    report.recommendation = "HOLD_FOR_FIXES";
    report.p0Blockers.push(`fatal:${error.message}`);
    await appendProgress(progressLogPath, `fatal error: ${error.message}`);
  } finally {
    if (restartedServer) {
      await restartedServer.stop().catch(() => undefined);
      restartedServer = null;
    }
    if (runtimeServer) {
      await runtimeServer.stop().catch(() => undefined);
      runtimeServer = null;
    }
    if (cluster) {
      await stopPersistentClusterIfNeeded(tools, cluster).catch((error) => {
        report.p1Warnings.push(`cluster_stop_warning:${error.message}`);
      });
      report.cluster = {
        ...(report.cluster || {}),
        stoppedAtEnd: Boolean(cluster.stoppedAtEnd),
      };
      report.backgroundProcesses.postgresClusterRunningAtEnd =
        Boolean(cluster.wasRunningBefore) || Boolean(!cluster.stoppedAtEnd && cluster.startedNow);
    }
    report.backgroundProcesses.runtimeServerRunningAtEnd = false;
  }

  const reportJsonPath = path.join(outputDir, "staging_report.json");
  const reportMdPath = path.join(outputDir, "staging_report.md");
  report.artifacts = {
    reportJson: toRelative(reportJsonPath),
    reportMd: toRelative(reportMdPath),
  };
  await writeJsonFile(reportJsonPath, report);
  await writeTextFile(reportMdPath, buildMarkdownReport(report));

  process.stdout.write(`${reportJsonPath}\n${reportMdPath}\n`);
  process.exit(report.p0Blockers.length > 0 ? 1 : 0);
}

await main();
