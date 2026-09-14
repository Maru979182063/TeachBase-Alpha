import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { Pool } from "pg";

import { startEmbeddedPostgresCluster } from "../tests/helpers/runtime_testkit.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const migrationRoot = path.join(root, "backend", "teachbase-server", "src", "main", "resources", "db", "migration");
const reportPath = path.join(root, "docs", "reports", "tag_feedback_v011_migration_gate.json");

function expect(value, message) {
  if (!value) throw new Error(message);
}

async function migrationFiles() {
  return (await fs.readdir(migrationRoot))
    .filter((name) => /^V\d+__.+\.sql$/.test(name))
    .sort((a, b) => Number(a.slice(1, 4)) - Number(b.slice(1, 4)));
}

async function apply(pool, names) {
  for (const name of names) {
    await pool.query(await fs.readFile(path.join(migrationRoot, name), "utf8"));
  }
}

async function seedV010(pool) {
  const names = ["workspace", "actor", "question", "revision", "review", "document", "editorRevision", "module", "moduleRevision", "importRequest"];
  const ids = Object.fromEntries(names.map((name) => [name, crypto.randomUUID()]));
  const hash = crypto.createHash("sha256").update("tag-feedback-v010-preservation").digest("hex");
  await pool.query("insert into teachbase_app.workspace(workspace_id,slug,display_name) values($1,'tag-feedback-upgrade','Tag Feedback Upgrade')", [ids.workspace]);
  await pool.query("insert into teachbase_app.app_user(user_id,email,display_name) values($1,'tag-feedback-upgrade@example.invalid','Tag Feedback')", [ids.actor]);
  await pool.query("insert into teachbase_app.workspace_member(workspace_id,user_id,member_role) values($1,$2,'owner')", [ids.workspace, ids.actor]);
  await pool.query(`insert into teachbase_app.question
    (question_id,workspace_id,external_key,source_system,source_key,current_revision_no,created_by,updated_by)
    values($1,$2,'tag-feedback-q','migration-gate','tag-feedback-q',1,$3,$3)`, [ids.question, ids.workspace, ids.actor]);
  await pool.query(`insert into teachbase_app.question_revision
    (question_revision_id,question_id,workspace_id,revision_no,review_status,subject,stage,question_type,
     stem_markdown,content_json,content_hash,source_payload_hash,import_envelope_hash,created_by)
    values($1,$2,$3,1,'pending_review','数学','高中','解答题','迁移保留题目','{}',$4,$4,$4,$5)`,
  [ids.revision, ids.question, ids.workspace, hash, ids.actor]);
  await pool.query(`insert into teachbase_app.review_case
    (review_case_id,workspace_id,question_id,question_revision_id,expected_content_hash,opened_by)
    values($1,$2,$3,$4,$5,$6)`, [ids.review, ids.workspace, ids.question, ids.revision, hash, ids.actor]);
  await pool.query(`insert into teachbase_app.editor_document
    (editor_document_id,workspace_id,document_kind,title,current_revision_no,writer_mode,created_by,updated_by)
    values($1,$2,'synchronized_handout','迁移保留编辑器',1,'working_draft',$3,$3)`,
  [ids.document, ids.workspace, ids.actor]);
  await pool.query(`insert into teachbase_app.editor_revision
    (editor_revision_id,editor_document_id,workspace_id,revision_no,editor_model,schema_version,
     master_doc_json,version_overrides_json,content_hash,created_by)
    values($1,$2,$3,1,'master-overrides-v1',1,'{"type":"doc","content":[]}',
      '[null,null,null]',$4,$5)`, [ids.editorRevision, ids.document, ids.workspace, hash, ids.actor]);
  await pool.query(`insert into teachbase_app.standard_module
    (standard_module_id,workspace_id,module_key,module_type,current_revision_no,created_by,updated_by)
    values($1,$2,'migration-module','explanation',1,$3,$3)`, [ids.module, ids.workspace, ids.actor]);
  await pool.query(`insert into teachbase_app.standard_module_revision
    (standard_module_revision_id,standard_module_id,workspace_id,revision_no,title,subject,stage,
     content_json,content_hash,created_by)
    values($1,$2,$3,1,'迁移保留模块','数学','高中','{}',$4,$5)`,
  [ids.moduleRevision, ids.module, ids.workspace, hash, ids.actor]);
  await pool.query(`insert into teachbase_app.canonical_import_request
    (import_request_id,workspace_id,actor_user_id,producer,contract_version,package_key,package_hash,
     package_json,execution_plan_json,status,operation_count)
    values($1,$2,$3,'migration-gate','teachbase.canonical-content-import.v1','tag-feedback-package',$4,
      '{}','[]','validated',0)`, [ids.importRequest, ids.workspace, ids.actor, hash]);
  return { ...ids, hash };
}

async function preservedState(pool, ids) {
  return (await pool.query(`select jsonb_build_object(
    'question',(select to_jsonb(x) from (select * from teachbase_app.question where question_id=$1) x),
    'revision',(select to_jsonb(x) from (select * from teachbase_app.question_revision where question_revision_id=$2) x),
    'review',(select to_jsonb(x) from (select * from teachbase_app.review_case where review_case_id=$3) x),
    'editor',(select to_jsonb(x) from (select * from teachbase_app.editor_revision where editor_revision_id=$4) x),
    'module',(select to_jsonb(x) from (select * from teachbase_app.standard_module_revision where standard_module_revision_id=$5) x),
    'g5',(select to_jsonb(x) from (select * from teachbase_app.canonical_import_request where import_request_id=$6) x)
  ) value`, [ids.question, ids.revision, ids.review, ids.editorRevision, ids.moduleRevision, ids.importRequest])).rows[0].value;
}

async function main() {
  const discovered = await migrationFiles();
  const files = discovered.filter((name) => Number(name.slice(1, 4)) <= 11);
  expect(files.length === 11 && files.at(-1).startsWith("V011__"), `v011_migration_set_invalid:${discovered.join(",")}`);
  const cluster = await startEmbeddedPostgresCluster("tag_feedback_v011_migration_gate");
  let fresh;
  let upgrade;
  let report;
  try {
    const freshDb = await cluster.createDatabase("tag_feedback_v011_fresh_test");
    fresh = new Pool({ connectionString: freshDb.connectionString });
    await apply(fresh, files);
    const tables = await fresh.query(`select table_name from information_schema.tables
      where table_schema='teachbase_app' and table_name in
      ('tagging_run','question_tag_snapshot','question_tag_snapshot_item','question_tag_feedback','question_tag_state','taxonomy_gap_case')`);
    expect(tables.rowCount === 6, "v011_tables_missing");

    const upgradeDb = await cluster.createDatabase("tag_feedback_v011_upgrade_test");
    upgrade = new Pool({ connectionString: upgradeDb.connectionString });
    await apply(upgrade, files.slice(0, 10));
    const ids = await seedV010(upgrade);
    const before = await preservedState(upgrade, ids);
    await apply(upgrade, [files[10]]);
    const after = await preservedState(upgrade, ids);
    expect(JSON.stringify(before) === JSON.stringify(after), "v011_rewrote_existing_domain_data");

    const taxonomyVersion = crypto.randomUUID();
    const nodeA = crypto.randomUUID();
    const nodeB = crypto.randomUUID();
    await upgrade.query(`insert into teachbase_app.taxonomy_version
      (taxonomy_version_id,workspace_id,taxonomy_key,version_key,subject,stage,status,created_by,activated_at)
      values($1,$2,'senior-math','v1','数学','高中','active',$3,now())`,
    [taxonomyVersion, ids.workspace, ids.actor]);
    await upgrade.query(`insert into teachbase_app.taxonomy_node
      (taxonomy_node_id,taxonomy_version_id,workspace_id,knowledge_code,display_name,sort_order)
      values($1,$3,$4,'A','A',0),($2,$3,$4,'B','B',1)`,
    [nodeA, nodeB, taxonomyVersion, ids.workspace]);
    const runId = crypto.randomUUID();
    await upgrade.query(`insert into teachbase_app.tagging_run
      (tagging_run_id,workspace_id,external_run_key,taxonomy_version_id,model_provider,model_name,model_version,
       prompt_profile_version,candidate_package_key,candidate_package_version,candidate_package_hash,
       producer_version,runtime_version,parameters_hash,run_hash,status,started_at,completed_at,created_by)
      values($1,$2,'migration-run',$3,'fixture','model','v1','prompt-v1','candidate','v1',$4,
       'producer-v1','runtime-v1',$4,$4,'completed',now(),now(),$5)`,
    [runId, ids.workspace, taxonomyVersion, ids.hash, ids.actor]);
    const snapshotId = crypto.randomUUID();
    const transaction = await upgrade.connect();
    try {
      await transaction.query("begin");
      await transaction.query(`insert into teachbase_app.question_tag_snapshot
        (snapshot_id,workspace_id,question_id,question_revision_id,taxonomy_key,taxonomy_version_id,
         snapshot_kind,label_set_hash,snapshot_hash,item_count,tagging_run_id,created_by)
        values($1,$2,$3,$4,'senior-math',$5,'SYSTEM_SUGGESTION',$6,$6,1,$7,$8)`,
      [snapshotId, ids.workspace, ids.question, ids.revision, taxonomyVersion, ids.hash, runId, ids.actor]);
      await transaction.query(`insert into teachbase_app.question_tag_snapshot_item
        (snapshot_item_id,snapshot_id,workspace_id,taxonomy_version_id,taxonomy_node_id,relation_type,position_index)
        values($1,$2,$3,$4,$5,'primary',0)`,
      [crypto.randomUUID(), snapshotId, ids.workspace, taxonomyVersion, nodeA]);
      await transaction.query("commit");
    } finally {
      transaction.release();
    }
    const primaryIndex = await upgrade.query(`select indexdef from pg_indexes
      where schemaname='teachbase_app' and indexname='uq_question_tag_snapshot_one_primary'`);
    const primaryUnique = primaryIndex.rowCount === 1
      && primaryIndex.rows[0].indexdef.includes("WHERE")
      && primaryIndex.rows[0].indexdef.includes("relation_type")
      && primaryIndex.rows[0].indexdef.includes("primary");
    expect(primaryUnique, "v011_primary_partial_unique_missing");
    let appendRejected = false;
    try {
      await upgrade.query(`insert into teachbase_app.question_tag_snapshot_item
        (snapshot_item_id,snapshot_id,workspace_id,taxonomy_version_id,taxonomy_node_id,relation_type,position_index)
        values($1,$2,$3,$4,$5,'secondary',0)`,
      [crypto.randomUUID(), snapshotId, ids.workspace, taxonomyVersion, nodeB]);
    } catch (error) {
      appendRejected = error.code === "P0001" && error.message.includes("tag_feedback_snapshot_item_append_forbidden");
    }
    expect(appendRejected, "v011_snapshot_item_append_not_fenced");
    let immutable = false;
    try {
      await upgrade.query("update teachbase_app.question_tag_snapshot set label_set_hash=$1 where snapshot_id=$2", ["0".repeat(64), snapshotId]);
    } catch (error) {
      immutable = error.code === "P0001" && error.message.includes("tag_feedback_fact_immutable");
    }
    expect(immutable, "v011_snapshot_update_not_fenced");

    report = {
      schemaVersion: 1,
      generatedAt: new Date().toISOString(),
      status: "passed",
      database: { engine: "PostgreSQL", version: (await fresh.query("show server_version")).rows[0].server_version },
      migrations: { fresh: "V001->V011", upgrade: "V010->V011", existingFixture: "G5/V010 preservation fixture" },
      acceptance: {
        passed: 9,
        total: 9,
        checks: {
          cleanMigration: true,
          additiveUpgrade: true,
          sixTablesPresent: true,
          questionRevisionPreserved: true,
          reviewPreserved: true,
          editorG4G5Preserved: true,
          primaryPartialUnique: true,
          snapshotItemAppendFence: true,
          snapshotImmutableFence: true,
        },
      },
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
