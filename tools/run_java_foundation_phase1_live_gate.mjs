import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { Pool } from "pg";

import {
  fetchJson,
  reservePort,
  startEmbeddedPostgresCluster,
} from "../tests/helpers/runtime_testkit.mjs";

const __filename = fileURLToPath(import.meta.url);
const workspaceRoot = path.resolve(path.dirname(__filename), "..");
const serverRoot = path.join(workspaceRoot, "backend", "teachbase-server");
const jarPath = path.join(serverRoot, "target", "teachbase-server-0.1.0-SNAPSHOT.jar");
const reportPath = path.join(
  workspaceRoot,
  "docs",
  "reports",
  "java_foundation_phase1_live_gate_20260831.json",
);
const fixtureContractPath = "tests/fixtures/final_chain_samples/doc_math_sample.docx";
const fixturePath = path.join(workspaceRoot, ...fixtureContractPath.split("/"));
const concurrentFixtureContractPath = "tests/fixtures/final_chain_samples/doc_english_sample.docx";
const concurrentFixturePath = path.join(workspaceRoot, ...concurrentFixtureContractPath.split("/"));

function expect(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

async function waitForJavaHealth(baseUrl, child, logs, timeoutMs = 45_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) {
      throw new Error(`java_server_exited:${child.exitCode}\n${logs.stderr.join("")}`);
    }
    try {
      const response = await fetchJson(`${baseUrl}/actuator/health`);
      if (response.ok && response.data?.status === "UP") {
        return;
      }
    } catch {
      // Startup races are expected while Flyway and the web server initialize.
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`java_server_health_timeout\n${logs.stderr.join("")}`);
}

async function stopChild(child) {
  if (!child || child.exitCode !== null) {
    return;
  }
  child.kill("SIGTERM");
  await Promise.race([
    new Promise((resolve) => child.once("exit", resolve)),
    new Promise((resolve) => setTimeout(resolve, 8_000)),
  ]);
  if (child.exitCode === null) {
    if (process.platform === "win32") {
      const killer = spawn("taskkill", ["/PID", String(child.pid), "/T", "/F"], {
        stdio: "ignore",
      });
      await new Promise((resolve) => killer.once("exit", resolve));
    } else {
      child.kill("SIGKILL");
    }
  }
}

async function main() {
  await fs.access(jarPath);
  const fixture = await fs.readFile(fixturePath);
  const sha256 = crypto.createHash("sha256").update(fixture).digest("hex");
  const concurrentFixture = await fs.readFile(concurrentFixturePath);
  const concurrentSha = crypto.createHash("sha256").update(concurrentFixture).digest("hex");
  const cluster = await startEmbeddedPostgresCluster("java_foundation_phase1_test");
  let child;
  let pool;
  let report;

  try {
    const database = await cluster.createDatabase("java_foundation_phase1_test");
    const databaseUrl = new URL(database.connectionString);
    const serverPort = await reservePort();
    const baseUrl = `http://127.0.0.1:${serverPort}`;
    const logs = { stdout: [], stderr: [] };

    child = spawn("java", ["-jar", jarPath], {
      cwd: serverRoot,
      env: {
        ...process.env,
        TEACHBASE_DATABASE_URL: `jdbc:postgresql://127.0.0.1:${cluster.port}/${database.database}`,
        TEACHBASE_DATABASE_USER: decodeURIComponent(databaseUrl.username),
        TEACHBASE_DATABASE_PASSWORD: decodeURIComponent(databaseUrl.password),
        TEACHBASE_DATABASE_POOL_SIZE: "12",
        TEACHBASE_SERVER_PORT: String(serverPort),
      },
      stdio: ["ignore", "pipe", "pipe"],
    });
    child.stdout.on("data", (chunk) => logs.stdout.push(String(chunk)));
    child.stderr.on("data", (chunk) => logs.stderr.push(String(chunk)));
    await waitForJavaHealth(baseUrl, child, logs);

    pool = new Pool({ connectionString: database.connectionString });
    const workspaceId = crypto.randomUUID();
    const actorUserId = crypto.randomUUID();
    await pool.query(
      `insert into teachbase_app.workspace
         (workspace_id, slug, display_name)
       values ($1, $2, $3)`,
      [workspaceId, "phase1-live-gate", "Phase 1 Live Gate"],
    );
    await pool.query(
      `insert into teachbase_app.app_user
         (user_id, email, display_name)
       values ($1, $2, $3)`,
      [actorUserId, "phase1-live-gate@example.invalid", "Phase 1 Gate Actor"],
    );
    await pool.query(
      `insert into teachbase_app.workspace_member
         (workspace_id, user_id, member_role)
       values ($1, $2, 'owner')`,
      [workspaceId, actorUserId],
    );
    const teacherUserId = crypto.randomUUID();
    const viewerUserId = crypto.randomUUID();
    await pool.query(
      `insert into teachbase_app.app_user (user_id, email, display_name)
       values ($1, 'teacher@example.invalid', 'Teaching Scope Teacher'),
              ($2, 'viewer@example.invalid', 'Teaching Scope Viewer')`,
      [teacherUserId, viewerUserId],
    );
    await pool.query(
      `insert into teachbase_app.workspace_member (workspace_id, user_id, member_role)
       values ($1, $2, 'editor'), ($1, $3, 'viewer')`,
      [workspaceId, teacherUserId, viewerUserId],
    );

    const payload = {
      workspaceId,
      actorUserId,
      originalFilename: "doc_math_sample.docx",
      storageProvider: "local",
      storageKey: fixtureContractPath,
      mediaType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      sizeBytes: fixture.byteLength,
      sha256,
    };

    const first = await fetchJson(`${baseUrl}/api/v1/files`, {
      method: "POST",
      body: payload,
    });
    expect(first.status === 201, `first_registration_status:${first.status}`);
    expect(first.data?.created === true, "first_registration_not_created");

    const duplicate = await fetchJson(`${baseUrl}/api/v1/files`, {
      method: "POST",
      body: payload,
    });
    expect(duplicate.status === 200, `duplicate_registration_status:${duplicate.status}`);
    expect(duplicate.data?.created === false, "duplicate_registration_marked_created");
    expect(duplicate.data?.fileAssetId === first.data.fileAssetId, "duplicate_asset_id_changed");
    expect(duplicate.data?.fileVersionId === first.data.fileVersionId, "duplicate_version_id_changed");

    const concurrentPayload = {
      ...payload,
      originalFilename: "doc_english_sample.docx",
      storageKey: concurrentFixtureContractPath,
      sizeBytes: concurrentFixture.byteLength,
      sha256: concurrentSha,
    };
    const concurrent = await Promise.all(
      Array.from({ length: 8 }, () =>
        fetchJson(`${baseUrl}/api/v1/files`, { method: "POST", body: concurrentPayload }),
      ),
    );
    expect(concurrent.every((response) => [200, 201].includes(response.status)), "concurrent_status_failure");
    expect(concurrent.filter((response) => response.status === 201).length === 1, "concurrent_create_count_invalid");
    expect(new Set(concurrent.map((response) => response.data?.fileAssetId)).size === 1, "concurrent_asset_ids_diverged");
    expect(new Set(concurrent.map((response) => response.data?.fileVersionId)).size === 1, "concurrent_version_ids_diverged");

    const invalidPath = await fetchJson(`${baseUrl}/api/v1/files`, {
      method: "POST",
      body: { ...payload, sha256: "f".repeat(64), storageKey: "C:\\temp\\unsafe.docx" },
    });
    expect(invalidPath.status === 400, `absolute_path_status:${invalidPath.status}`);
    expect(
      invalidPath.data?.detail === "storage_key_must_be_portable_and_relative",
      `absolute_path_error_contract_changed:${invalidPath.data?.detail}`,
    );

    const nonMember = await fetchJson(`${baseUrl}/api/v1/files`, {
      method: "POST",
      body: { ...payload, actorUserId: crypto.randomUUID(), sha256: "d".repeat(64) },
    });
    expect(nonMember.status === 403, `non_member_status:${nonMember.status}`);
    expect(nonMember.data?.detail === "actor_not_active_workspace_member", "non_member_error_contract_changed");

    const teachingScopeUrl = `${baseUrl}/api/v1/workspaces/${workspaceId}/members/${teacherUserId}/teaching-scopes`;
    const assignedScopes = await fetchJson(teachingScopeUrl, {
      method: "PUT",
      body: {
        actorUserId,
        scopes: [
          { subject: " 数学 ", stage: "初中", primary: true },
          { subject: "数学", stage: "高中", primary: false },
        ],
      },
    });
    expect(assignedScopes.status === 200, `teaching_scope_assign_status:${assignedScopes.status}`);
    expect(assignedScopes.data?.length === 2, "teaching_scope_assign_count_invalid");
    expect(assignedScopes.data[0]?.subject === "数学", "teaching_scope_not_normalized");
    expect(assignedScopes.data[0]?.primary === true, "teaching_scope_primary_not_first");

    const loadedScopes = await fetchJson(`${teachingScopeUrl}?actorUserId=${actorUserId}`);
    expect(loadedScopes.status === 200, `teaching_scope_read_status:${loadedScopes.status}`);
    expect(loadedScopes.data?.length === 2, "teaching_scope_read_count_invalid");

    const duplicateScopes = await fetchJson(teachingScopeUrl, {
      method: "PUT",
      body: {
        actorUserId,
        scopes: [
          { subject: "数学", stage: "初中", primary: true },
          { subject: "数学", stage: "初中", primary: false },
        ],
      },
    });
    expect(duplicateScopes.status === 409, `teaching_scope_duplicate_status:${duplicateScopes.status}`);

    const forbiddenScopeUpdate = await fetchJson(teachingScopeUrl, {
      method: "PUT",
      body: {
        actorUserId: viewerUserId,
        scopes: [{ subject: "英语", stage: "高中", primary: true }],
      },
    });
    expect(forbiddenScopeUpdate.status === 403, `teaching_scope_forbidden_status:${forbiddenScopeUpdate.status}`);

    const selfUpdatedScopes = await fetchJson(teachingScopeUrl, {
      method: "PUT",
      body: {
        actorUserId: teacherUserId,
        scopes: [{ subject: "数学", stage: "初中", primary: true }],
      },
    });
    expect(selfUpdatedScopes.status === 200, `teaching_scope_self_update_status:${selfUpdatedScopes.status}`);
    expect(selfUpdatedScopes.data?.length === 1, "teaching_scope_self_update_count_invalid");

    const secondWorkspaceId = crypto.randomUUID();
    await pool.query(
      `insert into teachbase_app.workspace
         (workspace_id, slug, display_name)
       values ($1, $2, $3)`,
      [secondWorkspaceId, "phase1-isolation-gate", "Phase 1 Isolation Gate"],
    );
    let crossWorkspaceAssociationRejected = false;
    try {
      await pool.query(
        `insert into teachbase_app.file_version
           (file_version_id, file_asset_id, workspace_id, version_no, storage_provider,
            storage_key, media_type, size_bytes, sha256)
         values ($1, $2, $3, 2, 'local', $4, 'application/octet-stream', 1, $5)`,
        [
          crypto.randomUUID(),
          first.data.fileAssetId,
          secondWorkspaceId,
          "fixtures/isolation/forbidden.bin",
          "e".repeat(64),
        ],
      );
    } catch (error) {
      crossWorkspaceAssociationRejected = error.code === "23503";
    }
    expect(crossWorkspaceAssociationRejected, "cross_workspace_file_association_not_rejected");

    const tableResult = await pool.query(
      `select table_name
         from information_schema.tables
        where table_schema = 'teachbase_app'
          and table_type = 'BASE TABLE'
        order by table_name`,
    );
    const domainTableNames = tableResult.rows
      .map((row) => row.table_name)
      .filter((name) => name !== "flyway_schema_history");
    const foundationTables = [
      "app_user", "audit_event", "file_asset", "file_version", "legacy_id_map",
      "legacy_import_batch", "source_document", "source_region", "workspace", "workspace_member",
      "workspace_member_teaching_scope",
    ];
    expect(
      foundationTables.every((name) => domainTableNames.includes(name)),
      "foundation_tables_missing",
    );

    const counts = await pool.query(
      `select
         (select count(*)::int from teachbase_app.file_asset) as file_assets,
         (select count(*)::int from teachbase_app.file_version) as file_versions,
         (select count(*)::int from teachbase_app.audit_event) as audit_events,
         (select count(*)::int from teachbase_app.workspace_member_teaching_scope) as teaching_scopes,
         (select count(*)::int from teachbase_app.file_version where storage_key ~ '(^/|^[A-Za-z]:|\\\\)') as absolute_storage_keys`,
    );
    expect(counts.rows[0].file_assets === 2, `file_asset_count:${counts.rows[0].file_assets}`);
    expect(counts.rows[0].file_versions === 2, `file_version_count:${counts.rows[0].file_versions}`);
    expect(counts.rows[0].audit_events === 2, `audit_event_count:${counts.rows[0].audit_events}`);
    expect(counts.rows[0].teaching_scopes === 1, `teaching_scope_count:${counts.rows[0].teaching_scopes}`);
    expect(counts.rows[0].absolute_storage_keys === 0, "absolute_storage_key_persisted");

    const migration = await pool.query(
      `select version, success
         from teachbase_app.flyway_schema_history
        where type = 'SQL'
        order by installed_rank`,
    );
    const foundationMigration = migration.rows.find((row) => row.version === "001");
    expect(foundationMigration?.success, "migration_v001_not_successful");
    const teachingScopeMigration = migration.rows.find((row) => row.version === "007");
    expect(teachingScopeMigration?.success, "migration_v007_not_successful");

    const serverVersion = await pool.query("show server_version_num");
    const postgresMajor = Math.floor(Number.parseInt(serverVersion.rows[0].server_version_num, 10) / 10_000);
    expect(postgresMajor >= 16, `unsupported_postgres_major:${postgresMajor}`);

    report = {
      schemaVersion: 1,
      generatedAt: new Date().toISOString(),
      status: "passed",
      runtime: {
        java: 21,
        postgresMajor,
      },
      database: {
        schema: "teachbase_app",
        migration: "001",
        foundationTableCount: foundationTables.length,
        foundationTables,
        totalApplicationTableCount: domainTableNames.length,
      },
      fileRegistration: {
        fixture: fixtureContractPath,
        concurrentFixture: concurrentFixtureContractPath,
        sequentialIdempotency: "passed",
        concurrentRequests: concurrent.length,
        concurrentCreateResponses: concurrent.filter((response) => response.status === 201).length,
        persistedFileAssets: counts.rows[0].file_assets,
        persistedFileVersions: counts.rows[0].file_versions,
        persistedAuditEvents: counts.rows[0].audit_events,
      },
      memberTeachingScope: {
        migration: "007",
        administratorAssignment: "passed",
        selfServiceReplacement: "passed",
        duplicatePairRejected: duplicateScopes.status === 409,
        unauthorizedReplacementRejected: forbiddenScopeUpdate.status === 403,
        persistedScopeCount: counts.rows[0].teaching_scopes,
      },
      portability: {
        absolutePathRejected: true,
        persistedAbsoluteStorageKeys: counts.rows[0].absolute_storage_keys,
      },
      tenantIsolation: {
        crossWorkspaceFileAssociationRejected: crossWorkspaceAssociationRejected,
        nonMemberActorRejected: nonMember.status === 403,
      },
      cleanup: "pending",
    };
  } finally {
    if (pool) {
      await pool.end();
    }
    await stopChild(child);
    await cluster.stop();
  }

  try {
    await fs.access(cluster.databaseDir);
    throw new Error("embedded_postgres_directory_not_removed");
  } catch (error) {
    if (error.code !== "ENOENT") {
      throw error;
    }
  }
  report.cleanup = "passed";
  await fs.mkdir(path.dirname(reportPath), { recursive: true });
  await fs.writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
  process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error.message}\n`);
  process.exitCode = 1;
});
