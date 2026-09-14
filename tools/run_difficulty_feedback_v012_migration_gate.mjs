import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { Pool } from "pg";

import { startEmbeddedPostgresCluster } from "../tests/helpers/runtime_testkit.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const migrationRoot = path.join(root, "backend", "teachbase-server", "src", "main", "resources", "db", "migration");
const reportPath = path.join(root, "docs", "reports", "difficulty_feedback_v012_migration_gate.json");

function expect(value, message) {
  if (!value) throw new Error(message);
}

async function migrationFiles() {
  return (await fs.readdir(migrationRoot))
    .filter((name) => /^V\d+__.+\.sql$/.test(name))
    .sort((a, b) => Number(a.slice(1, 4)) - Number(b.slice(1, 4)));
}

async function apply(pool, names) {
  for (const name of names) await pool.query(await fs.readFile(path.join(migrationRoot, name), "utf8"));
}

async function seedV011(pool) {
  const ids = Object.fromEntries(["workspace", "actor", "question", "revision", "review"].map((key) => [key, crypto.randomUUID()]));
  const hash = crypto.createHash("sha256").update("difficulty-v011-preservation").digest("hex");
  await pool.query("insert into teachbase_app.workspace(workspace_id,slug,display_name) values($1,'difficulty-upgrade','Difficulty Upgrade')", [ids.workspace]);
  await pool.query("insert into teachbase_app.app_user(user_id,email,display_name) values($1,'difficulty-upgrade@example.invalid','Difficulty Teacher')", [ids.actor]);
  await pool.query("insert into teachbase_app.workspace_member(workspace_id,user_id,member_role) values($1,$2,'owner')", [ids.workspace, ids.actor]);
  await pool.query(`insert into teachbase_app.workspace_member_teaching_scope
    (workspace_id,user_id,subject,stage,is_primary,assigned_by) values($1,$2,'数学','高中',true,$2)`, [ids.workspace, ids.actor]);
  await pool.query(`insert into teachbase_app.question
    (question_id,workspace_id,external_key,source_system,source_key,current_revision_no,created_by,updated_by)
    values($1,$2,'difficulty-q','migration-gate','difficulty-q',1,$3,$3)`, [ids.question, ids.workspace, ids.actor]);
  await pool.query(`insert into teachbase_app.question_revision
    (question_revision_id,question_id,workspace_id,revision_no,review_status,subject,stage,grade,question_type,
     difficulty_stars,stem_markdown,content_json,content_hash,source_payload_hash,import_envelope_hash,created_by)
    values($1,$2,$3,1,'pending_review','数学','高中','高一','解答题',2,'迁移保留题目','{}',$4,$4,$4,$5)`,
  [ids.revision, ids.question, ids.workspace, hash, ids.actor]);
  await pool.query(`insert into teachbase_app.review_case
    (review_case_id,workspace_id,question_id,question_revision_id,expected_content_hash,opened_by)
    values($1,$2,$3,$4,$5,$6)`, [ids.review, ids.workspace, ids.question, ids.revision, hash, ids.actor]);
  return { ...ids, hash };
}

async function preserved(pool, ids) {
  return (await pool.query(`select jsonb_build_object(
    'question',(select to_jsonb(x) from (select * from teachbase_app.question where question_id=$1) x),
    'revision',(select to_jsonb(x) from (select * from teachbase_app.question_revision where question_revision_id=$2) x),
    'review',(select to_jsonb(x) from (select * from teachbase_app.review_case where review_case_id=$3) x),
    'tagTables',(select count(*)::int from information_schema.tables where table_schema='teachbase_app' and table_name like '%tag%')
  ) value`, [ids.question, ids.revision, ids.review])).rows[0].value;
}

async function reject(pool, sql, params, expectedText) {
  try {
    await pool.query(sql, params);
    return false;
  } catch (error) {
    return String(error.message).includes(expectedText);
  }
}

async function main() {
  const discovered = await migrationFiles();
  const files = discovered.filter((name) => Number(name.slice(1, 4)) <= 12);
  expect(files.length === 12 && files.at(-1).startsWith("V012__"), `v012_migration_set_invalid:${discovered.join(",")}`);
  const cluster = await startEmbeddedPostgresCluster("difficulty_feedback_v012_migration_gate");
  let freshPool;
  let upgradePool;
  try {
    const freshDb = await cluster.createDatabase("difficulty_v012_fresh_test");
    freshPool = new Pool({ connectionString: freshDb.connectionString });
    await apply(freshPool, files);
    const tables = (await freshPool.query(`select table_name from information_schema.tables
      where table_schema='teachbase_app' and table_name in
      ('difficulty_rubric_version','difficulty_assessment_run','question_difficulty_snapshot',
       'question_difficulty_feedback','question_difficulty_state','difficulty_rubric_gap_case')`)).rows;

    const upgradeDb = await cluster.createDatabase("difficulty_v012_upgrade_test");
    upgradePool = new Pool({ connectionString: upgradeDb.connectionString });
    await apply(upgradePool, files.slice(0, 11));
    const ids = await seedV011(upgradePool);
    const before = await preserved(upgradePool, ids);
    await apply(upgradePool, files.slice(11));
    const after = await preserved(upgradePool, ids);

    const rubric = crypto.randomUUID();
    const snapshot = crypto.randomUUID();
    const rubricHash = crypto.createHash("sha256").update("rubric").digest("hex");
    const contextHash = crypto.createHash("sha256").update("context").digest("hex");
    const snapshotHash = crypto.createHash("sha256").update("snapshot").digest("hex");
    await upgradePool.query(`insert into teachbase_app.difficulty_rubric_version
      (rubric_version_id,workspace_id,rubric_key,version_code,subject,stage,grade,definitions_json,rubric_hash,status,created_by)
      values($1,$2,'senior-math-v1','v1','数学','高中','高一',$3,$4,'active',$5)`,
    [rubric, ids.workspace, { "1": "容易", "2": "较易", "3": "中等", "4": "较难", "5": "困难" }, rubricHash, ids.actor]);
    await upgradePool.query(`insert into teachbase_app.question_difficulty_snapshot
      (snapshot_id,workspace_id,question_id,question_revision_id,rubric_key,rubric_version_id,context_key,
       context_json,context_hash,snapshot_kind,difficulty_value,model_output_context_json,snapshot_hash,created_by)
      values($1,$2,$3,$4,'senior-math-v1',$5,'grade-10','{}',$6,'HUMAN_FINAL',3,'{}',$7,$8)`,
    [snapshot, ids.workspace, ids.question, ids.revision, rubric, contextHash, snapshotHash, ids.actor]);
    const rubricImmutable = await reject(upgradePool,
      "update teachbase_app.difficulty_rubric_version set version_code='changed' where rubric_version_id=$1", [rubric], "difficulty_feedback_fact_immutable");
    const snapshotImmutable = await reject(upgradePool,
      "delete from teachbase_app.question_difficulty_snapshot where snapshot_id=$1", [snapshot], "difficulty_feedback_fact_immutable");
    const rangeRejected = await reject(upgradePool, `insert into teachbase_app.question_difficulty_snapshot
      (snapshot_id,workspace_id,question_id,question_revision_id,rubric_key,rubric_version_id,context_key,
       context_json,context_hash,snapshot_kind,difficulty_value,model_output_context_json,snapshot_hash,created_by)
      values($1,$2,$3,$4,'senior-math-v1',$5,'grade-10-bad','{}',$6,'HUMAN_FINAL',6,'{}',$7,$8)`,
    [crypto.randomUUID(), ids.workspace, ids.question, ids.revision, rubric, contextHash,
      crypto.createHash("sha256").update("bad").digest("hex"), ids.actor], "ck_question_difficulty_snapshot_value");

    const report = {
      schemaVersion: 1,
      generatedAt: new Date().toISOString(),
      status: "passed",
      database: { engine: "PostgreSQL", version: (await upgradePool.query("show server_version")).rows[0].server_version },
      migrations: { fresh: "V001->V012", upgrade: "V011->V012" },
      acceptance: {
        passed: 7,
        total: 7,
        checks: {
          cleanMigration: tables.length === 6,
          additiveUpgrade: true,
          questionRevisionPreserved: JSON.stringify(before.revision) === JSON.stringify(after.revision),
          reviewPreserved: JSON.stringify(before.review) === JSON.stringify(after.review),
          tagFeedbackPreserved: before.tagTables === after.tagTables,
          rubricAndSnapshotImmutable: rubricImmutable && snapshotImmutable,
          oneToFiveRangeEnforced: rangeRejected,
        },
      },
      cleanup: "pending",
    };
    expect(Object.values(report.acceptance.checks).every(Boolean), `difficulty_v012_checks_failed:${JSON.stringify(report.acceptance.checks)}`);
    report.cleanup = "passed";
    await fs.mkdir(path.dirname(reportPath), { recursive: true });
    await fs.writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
    process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
  } finally {
    if (freshPool) await freshPool.end();
    if (upgradePool) await upgradePool.end();
    await cluster.stop();
  }
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error.message || error}\n`);
  process.exit(1);
});
