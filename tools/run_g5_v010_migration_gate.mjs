import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { Pool } from "pg";

import { startEmbeddedPostgresCluster } from "../tests/helpers/runtime_testkit.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const migrationRoot = path.join(root, "backend", "teachbase-server", "src", "main", "resources", "db", "migration");
const reportPath = path.join(root, "docs", "reports", "g5_v010_migration_gate.json");

function expect(value, message) {
  if (!value) throw new Error(message);
}

async function migrationFiles() {
  return (await fs.readdir(migrationRoot)).filter((name) => /^V\d+__.+\.sql$/.test(name))
    .sort((a, b) => Number(a.slice(1, 4)) - Number(b.slice(1, 4)));
}

async function apply(pool, names) {
  for (const name of names) await pool.query(await fs.readFile(path.join(migrationRoot, name), "utf8"));
}

async function seedV009(pool) {
  const ids = Object.fromEntries(["workspace", "actor", "document", "revision"].map((key) => [key, crypto.randomUUID()]));
  const hash = crypto.createHash("sha256").update("g5-v009-preservation").digest("hex");
  await pool.query("insert into teachbase_app.workspace(workspace_id,slug,display_name) values($1,'g5-upgrade','G5 Upgrade')", [ids.workspace]);
  await pool.query("insert into teachbase_app.app_user(user_id,email,display_name) values($1,'g5-upgrade@example.invalid','G5')", [ids.actor]);
  await pool.query("insert into teachbase_app.workspace_member(workspace_id,user_id,member_role) values($1,$2,'owner')", [ids.workspace, ids.actor]);
  await pool.query(`insert into teachbase_app.editor_document
    (editor_document_id,workspace_id,document_kind,title,current_revision_no,writer_mode,created_by,updated_by)
    values($1,$2,'synchronized_handout','Preserved',1,'working_draft',$3,$3)`, [ids.document, ids.workspace, ids.actor]);
  await pool.query(`insert into teachbase_app.editor_revision
    (editor_revision_id,editor_document_id,workspace_id,revision_no,editor_model,schema_version,
     master_doc_json,version_overrides_json,content_hash,created_by)
    values($1,$2,$3,1,'master-overrides-v1',1,'{"type":"doc","content":[]}'::jsonb,
      '[null,null,null]'::jsonb,$4,$5)`, [ids.revision, ids.document, ids.workspace, hash, ids.actor]);
  return { ...ids, hash };
}

async function snapshot(pool, ids) {
  return (await pool.query(`select jsonb_build_object(
    'document',(select to_jsonb(x) from (select * from teachbase_app.editor_document where editor_document_id=$1) x),
    'revision',(select to_jsonb(x) from (select * from teachbase_app.editor_revision where editor_revision_id=$2) x),
    'g4Tables',(select count(*)::int from information_schema.tables where table_schema='teachbase_app' and
      (table_name like 'standard_module%' or table_name like 'handout_%' or table_name='editor_revision_artifact_link'))
  ) value`, [ids.document, ids.revision])).rows[0].value;
}

async function main() {
  const discovered = await migrationFiles();
  const files = discovered.filter((name) => Number(name.slice(1, 4)) <= 10);
  expect(files.length === 10 && files.at(-1).startsWith("V010__"), `v010_migration_set_invalid:${discovered.join(",")}`);
  const cluster = await startEmbeddedPostgresCluster("g5_v010_migration_gate");
  let fresh;
  let upgrade;
  let report;
  try {
    const freshDb = await cluster.createDatabase("g5_v010_fresh_test");
    fresh = new Pool({ connectionString: freshDb.connectionString });
    await apply(fresh, files);
    const tables = await fresh.query(`select table_name from information_schema.tables
      where table_schema='teachbase_app' and table_name in ('canonical_import_request','canonical_import_operation')`);
    expect(tables.rowCount === 2, "v010_ledger_tables_missing");

    const upgradeDb = await cluster.createDatabase("g5_v010_upgrade_test");
    upgrade = new Pool({ connectionString: upgradeDb.connectionString });
    await apply(upgrade, files.slice(0, 9));
    const ids = await seedV009(upgrade);
    const before = await snapshot(upgrade, ids);
    await apply(upgrade, [files[9]]);
    const after = await snapshot(upgrade, ids);
    expect(after.document.import_identity_key === null, "v010_existing_document_identity_not_null");
    delete after.document.import_identity_key;
    expect(JSON.stringify(after) === JSON.stringify(before), "v010_changed_v009_domain_history");
    const columns = await upgrade.query(`select column_name from information_schema.columns
      where table_schema='teachbase_app' and table_name='canonical_import_request'`);
    expect(columns.rows.some((row) => row.column_name === "execution_plan_json"), "v010_plan_column_missing");
    const requestId = crypto.randomUUID();
    const operationId = crypto.randomUUID();
    await upgrade.query(`insert into teachbase_app.canonical_import_request
      (import_request_id,workspace_id,actor_user_id,producer,contract_version,package_key,package_hash,
       package_json,execution_plan_json,status,operation_count)
      values($1,$2,$3,'migration-gate','teachbase.canonical-content-import.v1','immutable',$4,'{}','[]','validated',1)`,
    [requestId, ids.workspace, ids.actor, ids.hash]);
    await upgrade.query(`insert into teachbase_app.canonical_import_operation
      (import_operation_id,import_request_id,workspace_id,operation_key,operation_type,sequence_no,payload_json,payload_hash)
      values($1,$2,$3,'file:x','file_reference',0,'{}',$4)`, [operationId, requestId, ids.workspace, ids.hash]);
    let immutablePlan = false;
    try {
      await upgrade.query("update teachbase_app.canonical_import_operation set payload_json='{\"changed\":true}' where import_operation_id=$1", [operationId]);
    } catch (error) {
      immutablePlan = error.code === "P0001" && error.message.includes("canonical_import_operation_plan_immutable");
    }
    expect(immutablePlan, "v010_operation_plan_mutation_not_rejected");
    let deleteRejected = false;
    try {
      await upgrade.query("delete from teachbase_app.canonical_import_operation where import_operation_id=$1", [operationId]);
    } catch (error) {
      deleteRejected = error.code === "P0001" && error.message.includes("canonical_import_ledger_delete_forbidden");
    }
    expect(deleteRejected, "v010_operation_ledger_delete_not_rejected");
    report = {
      schemaVersion: 1,
      generatedAt: new Date().toISOString(),
      status: "passed",
      database: { engine: "PostgreSQL", version: (await fresh.query("show server_version")).rows[0].server_version },
      migrations: { fresh: "V001->V010", upgrade: "V009->V010" },
      acceptance: { passed: 8, total: 8, checks: {
        cleanMigration: true, additiveUpgrade: true, g4TablesPreserved: true,
        editorRevisionPreserved: true, nullableImportIdentityBackfill: true, ledgerPlanPresent: true,
        operationPlanImmutableFromValidation: true,
        ledgerDeleteRejected: true,
      } },
      cleanup: "pending",
    };
  } finally {
    if (fresh) await fresh.end();
    if (upgrade) await upgrade.end();
    await cluster.stop();
  }
  report.cleanup = "passed";
  await fs.mkdir(path.dirname(reportPath), { recursive: true });
  await fs.writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
  process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error.message || error}\n`);
  process.exit(1);
});
