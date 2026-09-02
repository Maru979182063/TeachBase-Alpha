import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { Pool } from "pg";

import { fetchJson, reservePort, startEmbeddedPostgresCluster } from "../tests/helpers/runtime_testkit.mjs";
import { runMaintenance } from "./editor_working_draft_maintenance.mjs";

const workspaceRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const serverRoot = path.join(workspaceRoot, "backend", "teachbase-server");
const jarPath = path.join(serverRoot, "target", "teachbase-server-0.1.0-SNAPSHOT.jar");
const reportPath = path.join(workspaceRoot, "docs", "reports", "wp01_editor_working_draft_gate_20260902.json");

function expect(condition, message) {
  if (!condition) throw new Error(message);
}

function documentContent(label) {
  return {
    type: "doc",
    content: [{ type: "paragraph", content: [{ type: "text", text: label }] }],
  };
}

async function waitForHealth(baseUrl, child, logs) {
  const deadline = Date.now() + 45_000;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) throw new Error(`java_server_exited:${child.exitCode}\n${logs.stderr.join("")}`);
    try {
      const response = await fetchJson(`${baseUrl}/actuator/health`);
      if (response.ok && response.data?.status === "UP") return;
    } catch {
      // Flyway 与 HTTP 监听器此时可能仍在启动。
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`java_server_health_timeout\n${logs.stderr.join("")}`);
}

async function stopChild(child) {
  if (!child || child.exitCode !== null) return;
  child.kill("SIGTERM");
  await Promise.race([
    new Promise((resolve) => child.once("exit", resolve)),
    new Promise((resolve) => setTimeout(resolve, 8_000)),
  ]);
  if (child.exitCode === null && process.platform === "win32") {
    const killer = spawn("taskkill", ["/PID", String(child.pid), "/T", "/F"], { stdio: "ignore" });
    await new Promise((resolve) => killer.once("exit", resolve));
  } else if (child.exitCode === null) {
    child.kill("SIGKILL");
  }
}

async function seedWorkspace(pool, slug) {
  const workspaceId = crypto.randomUUID();
  const actorUserId = crypto.randomUUID();
  await pool.query(
    `insert into teachbase_app.workspace (workspace_id, slug, display_name) values ($1, $2, $3)`,
    [workspaceId, slug, slug],
  );
  await pool.query(
    `insert into teachbase_app.app_user (user_id, email, display_name) values ($1, $2, $3)`,
    [actorUserId, `${slug}@example.invalid`, slug],
  );
  await pool.query(
    `insert into teachbase_app.workspace_member (workspace_id, user_id, member_role) values ($1, $2, 'editor')`,
    [workspaceId, actorUserId],
  );
  return { workspaceId, actorUserId };
}

async function seedLegacyDocument(pool, workspaceId, actorUserId, label) {
  const documentId = crypto.randomUUID();
  const revisionId = crypto.randomUUID();
  const master = documentContent(label);
  const contentHash = crypto.createHash("sha256").update(JSON.stringify({ master, overrides: [null, null, null] })).digest("hex");
  await pool.query(
    `insert into teachbase_app.editor_document (
       editor_document_id, workspace_id, document_kind, title, status, current_revision_no,
       writer_mode, created_by, updated_by
     ) values ($1, $2, 'synchronized_handout', $3, 'draft', 1, 'legacy', $4, $4)`,
    [documentId, workspaceId, label, actorUserId],
  );
  await pool.query(
    `insert into teachbase_app.editor_revision (
       editor_revision_id, editor_document_id, workspace_id, revision_no, editor_model,
       schema_version, master_doc_json, version_overrides_json, content_hash, created_by
     ) values ($1, $2, $3, 1, 'master-overrides-v1', 1, $4::jsonb, '[null,null,null]'::jsonb, $5, $6)`,
    [revisionId, documentId, workspaceId, JSON.stringify(master), contentHash, actorUserId],
  );
  await pool.query(
    `insert into teachbase_app.editor_draft (
       editor_document_id, workspace_id, editor_revision_id, revision_no, updated_by
     ) values ($1, $2, $3, 1, $4)`,
    [documentId, workspaceId, revisionId, actorUserId],
  );
  return { documentId, revisionId, contentHash };
}

async function main() {
  await fs.access(jarPath);
  const cluster = await startEmbeddedPostgresCluster("wp01_working_draft_gate");
  let child;
  let pool;
  let report;
  try {
    const database = await cluster.createDatabase("wp01_working_draft_test");
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
        TEACHBASE_DATABASE_POOL_SIZE: "16",
        TEACHBASE_SERVER_PORT: String(serverPort),
        TEACHBASE_RENDER_ENABLED: "false",
        TEACHBASE_EDITOR_WORKING_DRAFT_ENABLED: "true",
        TEACHBASE_EDITOR_LAZY_MIGRATION_ENABLED: "true",
        TEACHBASE_EDITOR_CLEANUP_DELAY: "200ms",
      },
      stdio: ["ignore", "pipe", "pipe"],
    });
    child.stdout.on("data", (chunk) => logs.stdout.push(String(chunk)));
    child.stderr.on("data", (chunk) => logs.stderr.push(String(chunk)));
    await waitForHealth(baseUrl, child, logs);
    pool = new Pool({ connectionString: database.connectionString, max: 8 });
    const postgresVersion = (await pool.query("show server_version")).rows[0].server_version;
    const primary = await seedWorkspace(pool, "wp01-primary");
    const foreign = await seedWorkspace(pool, "wp01-foreign");

    const created = await fetchJson(`${baseUrl}/api/v1/editor/documents`, {
      method: "POST",
      body: {
        ...primary,
        documentKind: "synchronized_handout",
        title: "WP-01 autosave acceptance",
        schemaVersion: 1,
        masterDoc: documentContent("initial"),
        versionOverrides: [null, null, null],
      },
    });
    expect(created.status === 201 && created.data.draftVersion === 1, `create_failed:${created.status}`);
    const documentId = created.data.editorDocumentId;

    let draftVersion = 1;
    let lastBody;
    for (let index = 0; index < 100; index += 1) {
      lastBody = {
        ...primary,
        expectedDraftVersion: draftVersion,
        clientMutationId: `autosave-${index}`,
        schemaVersion: 1,
        masterDoc: documentContent(`autosave-${index}`),
        versionOverrides: [null, null, null],
      };
      const saved = await fetchJson(`${baseUrl}/api/v1/editor/documents/${documentId}/draft`, {
        method: "PUT",
        body: lastBody,
      });
      expect(saved.status === 200, `autosave_failed:${index}:${saved.status}`);
      draftVersion = saved.data.draftVersion;
    }
    const afterHundred = await pool.query(
      `select
         (select count(*)::int from teachbase_app.editor_revision where editor_document_id = $1) as revisions,
         (select count(*)::int from teachbase_app.editor_draft_checkpoint where editor_document_id = $1) as checkpoints,
         (select draft_version from teachbase_app.editor_working_draft where editor_document_id = $1) as draft_version`,
      [documentId],
    );
    expect(afterHundred.rows[0].revisions === 0, "autosave_created_revision");
    expect(Number(afterHundred.rows[0].draft_version) === 101, "draft_version_after_100_invalid");
    expect(afterHundred.rows[0].checkpoints === 1, "checkpoint_created_for_every_autosave");

    const replay = await fetchJson(`${baseUrl}/api/v1/editor/documents/${documentId}/draft`, {
      method: "PUT",
      body: lastBody,
    });
    expect(replay.status === 200 && replay.data.draftVersion === 101, "idempotent_retry_changed_version");
    expect(replay.data.idempotentReplay === true, "idempotent_retry_not_marked");

    const oldClientSave = await fetchJson(`${baseUrl}/api/v1/editor/documents/${documentId}/draft`, {
      method: "PUT",
      body: {
        ...primary,
        expectedRevisionNo: 1,
        schemaVersion: 1,
        masterDoc: documentContent("legacy-client-must-upgrade"),
        versionOverrides: [null, null, null],
      },
    });
    expect(oldClientSave.status === 426, `old_client_save_not_explicitly_rejected:${oldClientSave.status}`);
    expect(oldClientSave.data?.detail === "editor_client_contract_upgrade_required", "old_client_upgrade_problem_invalid");

    const concurrentBodies = ["winner-a", "winner-b"].map((label) => ({
      ...primary,
      expectedDraftVersion: 101,
      clientMutationId: `concurrent-${label}`,
      schemaVersion: 1,
      masterDoc: documentContent(label),
      versionOverrides: [null, null, null],
    }));
    const concurrent = await Promise.all(concurrentBodies.map((body) =>
      fetchJson(`${baseUrl}/api/v1/editor/documents/${documentId}/draft`, { method: "PUT", body })));
    expect(concurrent.filter((item) => item.status === 200).length === 1, "concurrent_winner_count_invalid");
    expect(concurrent.filter((item) => item.status === 409).length === 1, "concurrent_conflict_count_invalid");
    const winningLabel = concurrentBodies[concurrent.findIndex((item) => item.status === 200)].masterDoc.content[0].content[0].text;
    const loaded = await fetchJson(
      `${baseUrl}/api/v1/editor/documents/${documentId}/draft?workspaceId=${primary.workspaceId}&actorUserId=${primary.actorUserId}`,
    );
    expect(loaded.data.masterDoc.content[0].content[0].text === winningLabel, "conflict_overwrote_winner");
    expect(loaded.data.draftVersion === 102, "concurrent_draft_version_invalid");

    const foreignRead = await fetchJson(
      `${baseUrl}/api/v1/editor/documents/${documentId}/draft?workspaceId=${foreign.workspaceId}&actorUserId=${foreign.actorUserId}`,
    );
    expect(foreignRead.status === 404, `cross_workspace_read_not_rejected:${foreignRead.status}`);

    const oldClientSnapshot = await fetchJson(`${baseUrl}/api/v1/editor/documents/${documentId}/snapshots`, {
      method: "POST",
      body: { ...primary, expectedRevisionNo: 1, variantKey: "common", audience: "teacher", schemaVersion: 1 },
    });
    expect(oldClientSnapshot.status === 426, `old_client_snapshot_not_explicitly_rejected:${oldClientSnapshot.status}`);

    // 两个真实并发确认必须共用文档行锁串行化，并只冻结一个内容 revision。
    const [firstSnapshot, secondSnapshot] = await Promise.all([
      fetchJson(`${baseUrl}/api/v1/editor/documents/${documentId}/snapshots`, {
        method: "POST",
        body: { ...primary, expectedDraftVersion: 102, variantKey: "common", audience: "teacher", schemaVersion: 1 },
      }),
      fetchJson(`${baseUrl}/api/v1/editor/documents/${documentId}/snapshots`, {
        method: "POST",
        body: { ...primary, expectedDraftVersion: 102, variantKey: "common", audience: "student", schemaVersion: 1 },
      }),
    ]);
    expect(firstSnapshot.status === 201, `first_snapshot_failed:${firstSnapshot.status}`);
    expect(secondSnapshot.status === 201, `second_snapshot_failed:${secondSnapshot.status}`);
    expect(firstSnapshot.data.editorRevisionId === secondSnapshot.data.editorRevisionId, "same_content_revision_not_reused");
    const frozenRevisionCount = await pool.query(
      `select count(*)::int as count from teachbase_app.editor_revision where editor_document_id = $1`,
      [documentId],
    );
    expect(frozenRevisionCount.rows[0].count === 1, "preview_confirmation_created_duplicate_revision");

    const postSnapshotSave = await fetchJson(`${baseUrl}/api/v1/editor/documents/${documentId}/draft`, {
      method: "PUT",
      body: {
        ...primary,
        expectedDraftVersion: 102,
        clientMutationId: "post-snapshot-dirty",
        schemaVersion: 1,
        masterDoc: documentContent("content-after-snapshot"),
        versionOverrides: [null, null, null],
      },
    });
    expect(postSnapshotSave.status === 200 && postSnapshotSave.data.draftVersion === 103, "post_snapshot_autosave_failed");
    const snapshotStillFrozen = await pool.query(
      `select editor_revision_id, content_hash from teachbase_app.editor_snapshot where editor_snapshot_id = $1`,
      [firstSnapshot.data.editorSnapshotId],
    );
    expect(snapshotStillFrozen.rows[0].editor_revision_id === firstSnapshot.data.editorRevisionId,
      "snapshot_revision_pointer_changed");
    expect(snapshotStillFrozen.rows[0].content_hash === firstSnapshot.data.contentHash, "snapshot_hash_changed");

    const legacy = await seedLegacyDocument(pool, primary.workspaceId, primary.actorUserId, "legacy-first-open");
    const migrateRead = fetchJson(
      `${baseUrl}/api/v1/editor/documents/${legacy.documentId}/draft?workspaceId=${primary.workspaceId}&actorUserId=${primary.actorUserId}`,
    );
    const migrateSave = fetchJson(`${baseUrl}/api/v1/editor/documents/${legacy.documentId}/draft`, {
      method: "PUT",
      body: {
        ...primary,
        expectedDraftVersion: 1,
        clientMutationId: "legacy-concurrent-save",
        schemaVersion: 1,
        masterDoc: documentContent("legacy-save-winner"),
        versionOverrides: [null, null, null],
      },
    });
    const migrationRace = await Promise.all([migrateRead, migrateSave]);
    expect(migrationRace.every((item) => item.status === 200), "migration_save_race_failed");
    const migratedAgain = await fetchJson(
      `${baseUrl}/api/v1/editor/documents/${legacy.documentId}/draft?workspaceId=${primary.workspaceId}&actorUserId=${primary.actorUserId}`,
    );
    expect(migratedAgain.data.draftVersion === 2, "repeat_backfill_changed_draft_version");
    expect(migratedAgain.data.masterDoc.content[0].content[0].text === "legacy-save-winner",
      "backfill_save_race_lost_content");
    let oldWriterFenced = false;
    try {
      await pool.query(
        `update teachbase_app.editor_draft set updated_at = now() where editor_document_id = $1`,
        [legacy.documentId],
      );
    } catch (error) {
      oldWriterFenced = String(error.message).includes("legacy_editor_writer_fenced");
    }
    expect(oldWriterFenced, "legacy_writer_not_fenced_after_migration");

    const beforeCleanup = await pool.query(
      `select content_hash from teachbase_app.editor_working_draft where editor_document_id = $1`,
      [documentId],
    );
    await pool.query(
      `update teachbase_app.editor_draft_checkpoint
          set expires_at = now() - interval '1 second'
        where editor_document_id = $1`,
      [documentId],
    );
    await pool.query(
      `insert into teachbase_app.editor_draft_checkpoint (
         editor_draft_checkpoint_id, editor_document_id, workspace_id, draft_version,
         checkpoint_kind, content_json, content_hash, content_bytes, created_by, created_at, expires_at
       ) select $2, editor_document_id, workspace_id, draft_version, 'autosave', content_json,
                content_hash, content_bytes, updated_by, now() + interval '1 second', now() + interval '72 hours'
           from teachbase_app.editor_working_draft where editor_document_id = $1`,
      [documentId, crypto.randomUUID()],
    );
    await new Promise((resolve) => setTimeout(resolve, 900));
    const afterCleanup = await pool.query(
      `select
         (select content_hash from teachbase_app.editor_working_draft where editor_document_id = $1) as draft_hash,
         (select count(*)::int from teachbase_app.editor_draft_checkpoint where editor_document_id = $1) as checkpoints`,
      [documentId],
    );
    expect(afterCleanup.rows[0].draft_hash === beforeCleanup.rows[0].content_hash, "cleanup_deleted_or_changed_working_draft");
    expect(afterCleanup.rows[0].checkpoints === 1, "cleanup_did_not_preserve_latest_recovery_point");

    const rollbackHash = afterCleanup.rows[0].draft_hash;
    let maintenanceFenceRejected = false;
    try {
      await runMaintenance({ connectionString: database.connectionString, mode: "rollback-materialize", documentIds: [documentId] });
    } catch (error) {
      maintenanceFenceRejected = error.message === "editor_write_drain_confirmation_required";
    }
    expect(maintenanceFenceRejected, "maintenance_missing_write_drain_fence");
    const rollback = await runMaintenance({
      connectionString: database.connectionString,
      mode: "rollback-materialize",
      documentIds: [documentId],
      writesDrained: true,
    });
    expect(rollback.results[0].outcome === "materialized_for_rollback", "rollback_materialization_failed");
    const rollbackState = await pool.query(
      `select d.writer_mode, r.content_hash
         from teachbase_app.editor_document d
         join teachbase_app.editor_draft p on p.editor_document_id = d.editor_document_id
         join teachbase_app.editor_revision r on r.editor_revision_id = p.editor_revision_id
        where d.editor_document_id = $1`,
      [documentId],
    );
    expect(rollbackState.rows[0].writer_mode === "legacy", "rollback_writer_mode_not_legacy");
    expect(rollbackState.rows[0].content_hash === rollbackHash, "rollback_lost_working_draft_content");
    const reenabled = await runMaintenance({
      connectionString: database.connectionString,
      mode: "backfill",
      documentIds: [documentId],
      writesDrained: true,
    });
    expect(reenabled.results[0].outcome === "migrated", "backfill_after_rollback_failed");
    const reenabledHash = await pool.query(
      `select d.writer_mode, w.content_hash
         from teachbase_app.editor_document d
         join teachbase_app.editor_working_draft w on w.editor_document_id = d.editor_document_id
        where d.editor_document_id = $1`,
      [documentId],
    );
    expect(reenabledHash.rows[0].writer_mode === "working_draft", "writer_not_reenabled");
    expect(reenabledHash.rows[0].content_hash === rollbackHash, "reenable_lost_rollback_content");

    const forbiddenTables = await pool.query(
      `select table_name from information_schema.tables
        where table_schema = 'teachbase_app'
          and (table_name like 'standard_module%' or table_name like 'knowledge_document%'
            or table_name like 'question_group%' or table_name like 'unified_search%')`,
    );
    expect(forbiddenTables.rowCount === 0, `forbidden_production_tables:${JSON.stringify(forbiddenTables.rows)}`);

    // 灰度切换关闭新 writer 时，旧读合同仍可用，但任何新写入口必须 fail closed。
    await stopChild(child);
    const fencedPort = await reservePort();
    const fencedBaseUrl = `http://127.0.0.1:${fencedPort}`;
    const fencedLogs = { stdout: [], stderr: [] };
    child = spawn("java", ["-jar", jarPath], {
      cwd: serverRoot,
      env: {
        ...process.env,
        TEACHBASE_DATABASE_URL: `jdbc:postgresql://127.0.0.1:${cluster.port}/${database.database}`,
        TEACHBASE_DATABASE_USER: decodeURIComponent(databaseUrl.username),
        TEACHBASE_DATABASE_PASSWORD: decodeURIComponent(databaseUrl.password),
        TEACHBASE_DATABASE_POOL_SIZE: "8",
        TEACHBASE_SERVER_PORT: String(fencedPort),
        TEACHBASE_RENDER_ENABLED: "false",
        TEACHBASE_EDITOR_WORKING_DRAFT_ENABLED: "false",
        TEACHBASE_EDITOR_LAZY_MIGRATION_ENABLED: "false",
      },
      stdio: ["ignore", "pipe", "pipe"],
    });
    child.stdout.on("data", (chunk) => fencedLogs.stdout.push(String(chunk)));
    child.stderr.on("data", (chunk) => fencedLogs.stderr.push(String(chunk)));
    await waitForHealth(fencedBaseUrl, child, fencedLogs);
    const fencedWrite = await fetchJson(`${fencedBaseUrl}/api/v1/editor/documents`, {
      method: "POST",
      body: {
        ...primary,
        documentKind: "synchronized_handout",
        title: "must remain fenced",
        schemaVersion: 1,
        masterDoc: documentContent("fenced"),
        versionOverrides: [null, null, null],
      },
    });
    expect(fencedWrite.status === 503 && fencedWrite.data?.detail === "editor_writer_fenced",
      `feature_flag_writer_not_fenced:${fencedWrite.status}`);

    const checks = {
      autosave100CreatesZeroRevisions: true,
      sameMutationDoesNotAdvanceVersion: true,
      sameExpectedVersionHasOneWinner: true,
      conflictDoesNotOverwriteWinner: true,
      checkpointsAreThrottled: true,
      cleanupPreservesWorkingDraftAndLatestCheckpoint: true,
      legacyFirstOpenMigratesSafely: true,
      repeatedBackfillIsIdempotent: true,
      backfillAndSaveRacePreservesLastSuccess: true,
      dirtyPreviewCreatesExactlyOneRevision: true,
      concurrentPreviewCreatesExactlyOneRevision: true,
      unchangedPreviewReusesRevision: true,
      snapshotPinsExactRevisionId: true,
      oldSnapshotHashRemainsFrozen: true,
      rollbackPreservesNewDraftContent: true,
      crossWorkspaceReadFails: true,
      forbiddenProductionTablesAbsent: true,
      legacyWriterIsDatabaseFenced: true,
      oldClientReceivesExplicitUpgradeResponse: true,
      disabledFeatureFlagFencesWriter: true,
      maintenanceRequiresWriteDrainConfirmation: true,
    };
    report = {
      schemaVersion: 1,
      generatedAt: new Date().toISOString(),
      status: "passed",
      database: { engine: "PostgreSQL", version: postgresVersion, schema: "teachbase_app", flywayThrough: "V008" },
      policy: {
        checkpointInterval: "2m",
        checkpointTtl: "72h",
        checkpointMaxPerDocument: 100,
        mutationTtl: "7d",
      },
      acceptance: { passed: Object.values(checks).filter(Boolean).length, total: Object.keys(checks).length, checks },
      counters: {
        autosaves: 100,
        draftVersionAfterAutosaves: Number(afterHundred.rows[0].draft_version),
        revisionsAfterAutosaves: afterHundred.rows[0].revisions,
        checkpointsAfterAutosaves: afterHundred.rows[0].checkpoints,
        concurrentRequests: 2,
        concurrentSuccesses: 1,
        concurrentConflicts: 1,
      },
      maintenance: {
        writerFence: "passed",
        lazyMigration: "passed",
        repeatedBackfill: "passed",
        rollbackMaterialization: rollback.results[0].outcome,
        reenableBackfill: reenabled.results[0].outcome,
      },
      cleanup: "pending",
    };
  } finally {
    if (pool) await pool.end();
    await stopChild(child);
    await cluster.stop();
  }
  try {
    await fs.access(cluster.databaseDir);
    throw new Error("embedded_postgres_directory_not_removed");
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
  }
  report.cleanup = "passed";
  await fs.writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
  process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
}

main().catch((error) => {
  const detail = error instanceof Error ? error.stack || error.message : `non_error_rejection:${String(error)}`;
  process.stderr.write(`${detail}\n`);
  process.exitCode = 1;
});
