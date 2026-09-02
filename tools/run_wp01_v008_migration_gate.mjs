import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { Pool } from "pg";

import { startEmbeddedPostgresCluster } from "../tests/helpers/runtime_testkit.mjs";

const workspaceRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const migrationRoot = path.join(workspaceRoot, "backend", "teachbase-server", "src", "main", "resources", "db", "migration");
const reportPath = path.join(workspaceRoot, "docs", "reports", "wp01_v008_migration_gate_20260902.json");
const migrations = [
  "V001__foundation.sql",
  "V002__editor_and_export_foundation.sql",
  "V003__document_render_execution.sql",
  "V004__question_search_and_collection_snapshots.sql",
  "V005__question_governance_foundation.sql",
  "V006__release_seed_loader.sql",
  "V007__member_teaching_scope.sql",
  "V008__editor_working_draft_separation.sql",
];

function expect(condition, message) {
  if (!condition) throw new Error(message);
}

async function applyMigrations(pool, names) {
  for (const name of names) {
    const sql = await fs.readFile(path.join(migrationRoot, name), "utf8");
    await pool.query(sql);
  }
}

async function rowsAsText(pool, sql, values = []) {
  return (await pool.query(sql, values)).rows.map((row) => row.value);
}

async function seedV007History(pool) {
  const ids = {
    workspaceId: crypto.randomUUID(),
    userId: crypto.randomUUID(),
    documentId: crypto.randomUUID(),
    revisionId: crypto.randomUUID(),
    confirmationId: crypto.randomUUID(),
    snapshotId: crypto.randomUUID(),
  };
  const master = { type: "doc", content: [{ type: "paragraph", content: [{ type: "text", text: "V007 preserved" }] }] };
  const overrides = [null, null, null];
  const hash = crypto.createHash("sha256").update(JSON.stringify({ master, overrides })).digest("hex");
  await pool.query("insert into teachbase_app.workspace (workspace_id, slug, display_name) values ($1, 'v008-upgrade', 'V008 upgrade')", [ids.workspaceId]);
  await pool.query("insert into teachbase_app.app_user (user_id, email, display_name) values ($1, 'v008@example.invalid', 'V008')", [ids.userId]);
  await pool.query("insert into teachbase_app.workspace_member (workspace_id, user_id, member_role) values ($1, $2, 'owner')", [ids.workspaceId, ids.userId]);
  await pool.query(
    `insert into teachbase_app.editor_document
       (editor_document_id, workspace_id, document_kind, title, current_revision_no, created_by, updated_by)
     values ($1, $2, 'synchronized_handout', 'V007 history', 1, $3, $3)`,
    [ids.documentId, ids.workspaceId, ids.userId],
  );
  for (const [key, name, order] of [["basic", "基础版", 0], ["common", "常用版", 1], ["advanced", "进阶版", 2]]) {
    await pool.query(
      "insert into teachbase_app.editor_variant (editor_document_id, workspace_id, variant_key, display_name, sort_order) values ($1, $2, $3, $4, $5)",
      [ids.documentId, ids.workspaceId, key, name, order],
    );
  }
  await pool.query(
    `insert into teachbase_app.editor_revision
       (editor_revision_id, editor_document_id, workspace_id, revision_no, editor_model, schema_version,
        master_doc_json, version_overrides_json, content_hash, created_by)
     values ($1, $2, $3, 1, 'master-overrides-v1', 1, $4::jsonb, $5::jsonb, $6, $7)`,
    [ids.revisionId, ids.documentId, ids.workspaceId, JSON.stringify(master), JSON.stringify(overrides), hash, ids.userId],
  );
  await pool.query(
    "insert into teachbase_app.editor_draft (editor_document_id, workspace_id, editor_revision_id, revision_no, updated_by) values ($1, $2, $3, 1, $4)",
    [ids.documentId, ids.workspaceId, ids.revisionId, ids.userId],
  );
  await pool.query(
    `insert into teachbase_app.editor_preview_confirmation
       (editor_preview_confirmation_id, editor_document_id, workspace_id, editor_revision_id, variant_key, audience, confirmed_by)
     values ($1, $2, $3, $4, 'common', 'teacher', $5)`,
    [ids.confirmationId, ids.documentId, ids.workspaceId, ids.revisionId, ids.userId],
  );
  await pool.query(
    `insert into teachbase_app.editor_snapshot
       (editor_snapshot_id, editor_document_id, workspace_id, editor_revision_id, editor_preview_confirmation_id,
        variant_key, audience, schema_version, frozen_content_json, content_hash)
     values ($1, $2, $3, $4, $5, 'common', 'teacher', 1, $6::jsonb, $7)`,
    [ids.snapshotId, ids.documentId, ids.workspaceId, ids.revisionId, ids.confirmationId, JSON.stringify(master), hash],
  );
  return ids;
}

async function captureHistory(pool, documentId) {
  return {
    revisions: await rowsAsText(pool, "select row_to_json(x)::text value from (select * from teachbase_app.editor_revision where editor_document_id=$1 order by revision_no) x", [documentId]),
    drafts: await rowsAsText(pool, "select row_to_json(x)::text value from (select * from teachbase_app.editor_draft where editor_document_id=$1) x", [documentId]),
    confirmations: await rowsAsText(pool, "select row_to_json(x)::text value from (select * from teachbase_app.editor_preview_confirmation where editor_document_id=$1 order by editor_preview_confirmation_id) x", [documentId]),
    snapshots: await rowsAsText(pool, "select row_to_json(x)::text value from (select * from teachbase_app.editor_snapshot where editor_document_id=$1 order by editor_snapshot_id) x", [documentId]),
  };
}

async function expectFence(pool, sql, values, operation) {
  try {
    await pool.query(sql, values);
    throw new Error(`writer_fence_${operation}_was_not_rejected`);
  } catch (error) {
    expect(error.code === "TB001", `writer_fence_${operation}_wrong_sqlstate:${error.code}:${error.message}`);
  }
}

async function main() {
  const cluster = await startEmbeddedPostgresCluster("wp01_v008_migration_gate");
  let fresh;
  let upgrade;
  let report;
  try {
    const freshDb = await cluster.createDatabase("wp01_v008_fresh_test");
    fresh = new Pool({ connectionString: freshDb.connectionString });
    await applyMigrations(fresh, migrations);
    const postgresVersion = (await fresh.query("show server_version")).rows[0].server_version;
    const freshObjects = await fresh.query(
      `select table_name from information_schema.tables
        where table_schema='teachbase_app' and table_name in
          ('editor_working_draft','editor_autosave_mutation','editor_draft_checkpoint') order by table_name`,
    );
    expect(freshObjects.rowCount === 3, "fresh_v001_v008_missing_objects");

    const upgradeDb = await cluster.createDatabase("wp01_v008_upgrade_test");
    upgrade = new Pool({ connectionString: upgradeDb.connectionString });
    await applyMigrations(upgrade, migrations.slice(0, 7));
    const ids = await seedV007History(upgrade);
    const before = await captureHistory(upgrade, ids.documentId);
    await applyMigrations(upgrade, [migrations[7]]);
    const after = await captureHistory(upgrade, ids.documentId);
    expect(JSON.stringify(after) === JSON.stringify(before), "v008_changed_revision_snapshot_history");

    const mode = await upgrade.query("select writer_mode from teachbase_app.editor_document where editor_document_id=$1", [ids.documentId]);
    expect(mode.rows[0].writer_mode === "legacy", "v008_changed_existing_writer_mode");
    const newRows = await upgrade.query(
      `select
         (select count(*)::int from teachbase_app.editor_working_draft) working,
         (select count(*)::int from teachbase_app.editor_autosave_mutation) mutations,
         (select count(*)::int from teachbase_app.editor_draft_checkpoint) checkpoints`,
    );
    expect(Object.values(newRows.rows[0]).every((value) => value === 0), "v008_backfilled_new_tables");

    await upgrade.query("update teachbase_app.editor_draft set updated_at=now() where editor_document_id=$1", [ids.documentId]);
    await upgrade.query("update teachbase_app.editor_document set writer_mode='working_draft' where editor_document_id=$1", [ids.documentId]);
    await expectFence(upgrade, "update teachbase_app.editor_draft set updated_at=now() where editor_document_id=$1", [ids.documentId], "update");
    await expectFence(upgrade, "delete from teachbase_app.editor_draft where editor_document_id=$1", [ids.documentId], "delete");
    await expectFence(
      upgrade,
      "insert into teachbase_app.editor_draft (editor_document_id,workspace_id,editor_revision_id,revision_no,updated_by) values ($1,$2,$3,1,$4)",
      [ids.documentId, ids.workspaceId, ids.revisionId, ids.userId],
      "insert",
    );

    const forbidden = await upgrade.query(
      `select table_name from information_schema.tables where table_schema='teachbase_app' and
       (table_name like 'standard_module%' or table_name like 'knowledge_document%' or
        table_name like 'question_group%' or table_name like 'unified_search%')`,
    );
    expect(forbidden.rowCount === 0, "v008_created_forbidden_scope_tables");

    const checks = {
      freshV001ThroughV008: true,
      upgradeV007ToV008: true,
      revisionRowsUnchanged: true,
      previewConfirmationRowsUnchanged: true,
      snapshotRowsUnchanged: true,
      legacyDraftRowsUnchanged: true,
      noImplicitBackfill: true,
      legacyModeWriteAllowed: true,
      workingModeInsertFencedWithTB001: true,
      workingModeUpdateFencedWithTB001: true,
      workingModeDeleteFencedWithTB001: true,
      forbiddenScopeTablesAbsent: true,
    };
    report = {
      schemaVersion: 1,
      generatedAt: new Date().toISOString(),
      status: "passed",
      database: { engine: "PostgreSQL", version: postgresVersion },
      migrations: { fresh: "V001->V008", upgrade: "V007->V008" },
      acceptance: { passed: Object.keys(checks).length, total: Object.keys(checks).length, checks },
      writerFence: { sqlState: "TB001", operations: ["INSERT", "UPDATE", "DELETE"] },
      cleanup: "pending",
    };
  } finally {
    if (fresh) await fresh.end();
    if (upgrade) await upgrade.end();
    await cluster.stop();
  }
  report.cleanup = "passed";
  await fs.writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
  process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error.message}\n`);
  process.exitCode = 1;
});
