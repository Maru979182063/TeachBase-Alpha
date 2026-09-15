import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { Pool } from "pg";

import { startEmbeddedPostgresCluster } from "../tests/helpers/runtime_testkit.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const migrationRoot = path.join(root, "backend", "teachbase-server", "src", "main", "resources", "db", "migration");
const reportPath = path.join(root, "docs", "reports", "governance_projection_v013_migration_gate.json");

function expect(value, message) {
  if (!value) throw new Error(message);
}

async function migrationFiles() {
  return (await fs.readdir(migrationRoot))
    .filter((name) => /^V\d+__.+\.sql$/.test(name))
    .filter((name) => Number(name.slice(1, 4)) <= 13)
    .sort((a, b) => Number(a.slice(1, 4)) - Number(b.slice(1, 4)));
}

async function apply(pool, names) {
  for (const name of names) await pool.query(await fs.readFile(path.join(migrationRoot, name), "utf8"));
}

async function seedAuthorities(pool) {
  const keys = ["workspace", "actor", "question", "revision", "taxonomy", "primary", "secondaryA",
    "secondaryB", "tagSnapshot", "tagFeedback", "tagState", "rubric", "difficultySnapshot",
    "difficultyFeedback", "difficultyState"];
  const ids = Object.fromEntries(keys.map((key) => [key, crypto.randomUUID()]));
  const hash = (value) => crypto.createHash("sha256").update(value).digest("hex");
  await pool.query("insert into teachbase_app.workspace(workspace_id,slug,display_name) values($1,'projection-upgrade','Projection Upgrade')", [ids.workspace]);
  await pool.query("insert into teachbase_app.app_user(user_id,email,display_name) values($1,'projection-upgrade@example.invalid','Projection Owner')", [ids.actor]);
  await pool.query("insert into teachbase_app.workspace_member(workspace_id,user_id,member_role) values($1,$2,'owner')", [ids.workspace, ids.actor]);
  await pool.query(`insert into teachbase_app.question
    (question_id,workspace_id,external_key,source_system,source_key,current_revision_no,created_by,updated_by)
    values($1,$2,'projection-q','migration-gate','projection-q',1,$3,$3)`, [ids.question, ids.workspace, ids.actor]);
  await pool.query(`insert into teachbase_app.question_revision
    (question_revision_id,question_id,workspace_id,revision_no,review_status,subject,stage,grade,question_type,
     primary_knowledge_tag,difficulty_stars,stem_markdown,content_json,content_hash,source_payload_hash,
     import_envelope_hash,created_by)
    values($1,$2,$3,1,'pending_review','数学','高中','高一','解答题','legacy-tag',2,
      '投影迁移保留题目','{}',$4,$4,$4,$5)`,
  [ids.revision, ids.question, ids.workspace, hash("revision"), ids.actor]);
  await pool.query(`insert into teachbase_app.taxonomy_version
    (taxonomy_version_id,workspace_id,taxonomy_key,version_key,subject,stage,status,schema_version,created_by)
    values($1,$2,'senior-math-knowledge','v1','数学','高中','draft',1,$3)`,
  [ids.taxonomy, ids.workspace, ids.actor]);
  for (const [id, code] of [[ids.primary, "A"], [ids.secondaryA, "B"], [ids.secondaryB, "C"]]) {
    await pool.query(`insert into teachbase_app.taxonomy_node
      (taxonomy_node_id,taxonomy_version_id,workspace_id,knowledge_code,display_name)
      values($1,$2,$3,$4,$4)`, [id, ids.taxonomy, ids.workspace, code]);
  }
  await pool.query(`insert into teachbase_app.question_tag_snapshot
    (snapshot_id,workspace_id,question_id,question_revision_id,taxonomy_key,taxonomy_version_id,
     snapshot_kind,label_set_hash,snapshot_hash,item_count,created_by)
    values($1,$2,$3,$4,'senior-math-knowledge',$5,'HUMAN_FINAL',$6,$7,3,$8)`,
  [ids.tagSnapshot, ids.workspace, ids.question, ids.revision, ids.taxonomy, hash("labels"), hash("tag-snapshot"), ids.actor]);
  for (const [id, node, relation, position] of [[crypto.randomUUID(), ids.primary, "primary", 0],
    [crypto.randomUUID(), ids.secondaryA, "secondary", 0], [crypto.randomUUID(), ids.secondaryB, "secondary", 1]]) {
    await pool.query(`insert into teachbase_app.question_tag_snapshot_item
      (snapshot_item_id,snapshot_id,workspace_id,taxonomy_version_id,taxonomy_node_id,relation_type,position_index)
      values($1,$2,$3,$4,$5,$6,$7)`, [id, ids.tagSnapshot, ids.workspace, ids.taxonomy, node, relation, position]);
  }
  await pool.query(`insert into teachbase_app.question_tag_feedback
    (feedback_id,workspace_id,question_id,question_revision_id,taxonomy_key,taxonomy_version_id,
     before_snapshot_id,after_snapshot_id,outcome,reviewer_id,client_mutation_id,request_hash,
     expected_state_version,derived_operations_json)
    values($1,$2,$3,$4,'senior-math-knowledge',$5,$6,$6,'confirmed',$7,
      'projection-upgrade-tag',$8,4,'[]')`,
  [ids.tagFeedback, ids.workspace, ids.question, ids.revision, ids.taxonomy, ids.tagSnapshot, ids.actor, hash("tag-request")]);
  await pool.query(`insert into teachbase_app.question_tag_state
    (state_id,workspace_id,question_id,question_revision_id,taxonomy_key,taxonomy_version_id,
     current_snapshot_id,current_feedback_id,state_version,status,updated_by)
    values($1,$2,$3,$4,'senior-math-knowledge',$5,$6,$7,5,'reviewed',$8)`,
  [ids.tagState, ids.workspace, ids.question, ids.revision, ids.taxonomy, ids.tagSnapshot, ids.tagFeedback, ids.actor]);

  await pool.query(`insert into teachbase_app.difficulty_rubric_version
    (rubric_version_id,workspace_id,rubric_key,version_code,subject,stage,grade,
     definitions_json,rubric_hash,status,created_by)
    values($1,$2,'senior-math-five-star','v1','数学','高中','高一',$3,$4,'active',$5)`,
  [ids.rubric, ids.workspace, { "1": "容易", "2": "较易", "3": "中等", "4": "较难", "5": "困难" }, hash("rubric"), ids.actor]);
  await pool.query(`insert into teachbase_app.question_difficulty_snapshot
    (snapshot_id,workspace_id,question_id,question_revision_id,rubric_key,rubric_version_id,
     context_key,context_json,context_hash,snapshot_kind,difficulty_value,snapshot_hash,created_by)
    values($1,$2,$3,$4,'senior-math-five-star',$5,'default',$6,$7,'HUMAN_FINAL',4,$8,$9)`,
  [ids.difficultySnapshot, ids.workspace, ids.question, ids.revision, ids.rubric,
    { subject: "数学", stage: "高中" }, hash("context"), hash("difficulty-snapshot"), ids.actor]);
  await pool.query(`insert into teachbase_app.question_difficulty_feedback
    (feedback_id,workspace_id,question_id,question_revision_id,rubric_key,rubric_version_id,
     context_key,before_snapshot_id,after_snapshot_id,outcome,reviewer_id,client_mutation_id,
     request_hash,expected_state_version,derived_operations_json)
    values($1,$2,$3,$4,'senior-math-five-star',$5,'default',$6,$6,'confirmed',$7,
      'projection-upgrade-difficulty',$8,1,'[]')`,
  [ids.difficultyFeedback, ids.workspace, ids.question, ids.revision, ids.rubric,
    ids.difficultySnapshot, ids.actor, hash("difficulty-request")]);
  await pool.query(`insert into teachbase_app.question_difficulty_state
    (state_id,workspace_id,question_id,question_revision_id,rubric_key,rubric_version_id,
     context_key,current_snapshot_id,current_feedback_id,state_version,status,updated_by)
    values($1,$2,$3,$4,'senior-math-five-star',$5,'default',$6,$7,2,'reviewed',$8)`,
  [ids.difficultyState, ids.workspace, ids.question, ids.revision, ids.rubric,
    ids.difficultySnapshot, ids.difficultyFeedback, ids.actor]);
  return { ...ids, revisionHash: hash("revision") };
}

async function expectRejected(pool, sql, params, code) {
  try {
    await pool.query(sql, params);
    return false;
  } catch (error) {
    return String(error.message).includes(code);
  }
}

async function main() {
  const files = await migrationFiles();
  expect(files.length === 13 && files.at(-1).startsWith("V013__"), "v013_migration_set_invalid");
  const cluster = await startEmbeddedPostgresCluster("governance_projection_v013_migration_gate");
  let freshPool;
  let upgradePool;
  let report;
  try {
    const fresh = await cluster.createDatabase("projection_v013_fresh_test");
    freshPool = new Pool({ connectionString: fresh.connectionString });
    await apply(freshPool, files);
    const newTables = (await freshPool.query(`select table_name from information_schema.tables
      where table_schema='teachbase_app' and table_name in
      ('question_tag_current_projection','question_tag_current_projection_secondary',
       'question_difficulty_current_projection','governance_projection_outbox')`)).rows.length;

    const upgrade = await cluster.createDatabase("projection_v013_upgrade_test");
    upgradePool = new Pool({ connectionString: upgrade.connectionString });
    await apply(upgradePool, files.slice(0, 12));
    await upgradePool.query("begin");
    const ids = await seedAuthorities(upgradePool);
    await upgradePool.query("commit");
    const before = (await upgradePool.query(`select jsonb_build_object(
      'revision',(select to_jsonb(x) from (select content_hash,primary_knowledge_tag,difficulty_stars
        from teachbase_app.question_revision where question_revision_id=$1) x),
      'tagState',(select to_jsonb(x) from (select current_snapshot_id,state_version,status
        from teachbase_app.question_tag_state where state_id=$2) x),
      'difficultyState',(select to_jsonb(x) from (select current_snapshot_id,state_version,status
        from teachbase_app.question_difficulty_state where state_id=$3) x),
      'tagFeedback',(select count(*)::int from teachbase_app.question_tag_feedback),
      'difficultyFeedback',(select count(*)::int from teachbase_app.question_difficulty_feedback)
    ) value`, [ids.revision, ids.tagState, ids.difficultyState])).rows[0].value;
    await apply(upgradePool, files.slice(12));
    const after = (await upgradePool.query(`select jsonb_build_object(
      'revision',(select to_jsonb(x) from (select content_hash,primary_knowledge_tag,difficulty_stars
        from teachbase_app.question_revision where question_revision_id=$1) x),
      'tagState',(select to_jsonb(x) from (select current_snapshot_id,state_version,status
        from teachbase_app.question_tag_state where state_id=$2) x),
      'difficultyState',(select to_jsonb(x) from (select current_snapshot_id,state_version,status
        from teachbase_app.question_difficulty_state where state_id=$3) x),
      'tagFeedback',(select count(*)::int from teachbase_app.question_tag_feedback),
      'difficultyFeedback',(select count(*)::int from teachbase_app.question_difficulty_feedback)
    ) value`, [ids.revision, ids.tagState, ids.difficultyState])).rows[0].value;
    const backfill = await upgradePool.query(`select domain,authority_state_version,count(*)::int
      from teachbase_app.governance_projection_outbox group by domain,authority_state_version order by domain`);

    await upgradePool.query("begin");
    await upgradePool.query("update teachbase_app.question_tag_state set state_version=6 where state_id=$1", [ids.tagState]);
    const eventInside = Number((await upgradePool.query(`select count(*) from teachbase_app.governance_projection_outbox
      where authority_state_id=$1 and authority_state_version=6`, [ids.tagState])).rows[0].count);
    await upgradePool.query("rollback");
    const eventAfterRollback = Number((await upgradePool.query(`select count(*) from teachbase_app.governance_projection_outbox
      where authority_state_id=$1 and authority_state_version=6`, [ids.tagState])).rows[0].count);
    const versionAfterRollback = Number((await upgradePool.query(
      "select state_version from teachbase_app.question_tag_state where state_id=$1", [ids.tagState])).rows[0].state_version);
    await upgradePool.query("update teachbase_app.question_tag_state set state_version=6 where state_id=$1", [ids.tagState]);
    const committedEvent = Number((await upgradePool.query(`select count(*) from teachbase_app.governance_projection_outbox
      where authority_state_id=$1 and authority_state_version=6`, [ids.tagState])).rows[0].count);

    const directWriteBlocked = await expectRejected(upgradePool, `insert into teachbase_app.question_tag_current_projection
      (projection_id,workspace_id,question_id,question_revision_id,taxonomy_key,taxonomy_version_id,
       current_snapshot_id,primary_node_id,decision_source,tag_status,authority_state_version,
       label_set_hash,projection_semantic_hash)
      values($1,$2,$3,$4,'senior-math-knowledge',$5,$6,$7,'HUMAN_FINAL','reviewed',6,$8,$9)`,
    [crypto.randomUUID(), ids.workspace, ids.question, ids.revision, ids.taxonomy, ids.tagSnapshot,
      ids.primary, crypto.createHash("sha256").update("labels").digest("hex"),
      crypto.createHash("sha256").update("projection").digest("hex")],
    "governance_projection_direct_write_forbidden");

    expect(newTables === 4, "fresh_v013_tables_missing");
    expect(JSON.stringify(before) === JSON.stringify(after), "v012_authority_or_legacy_changed");
    expect(backfill.rows.length === 2 && backfill.rows.every((row) => row.count === 1), "authority_backfill_invalid");
    expect(eventInside === 1 && eventAfterRollback === 0 && versionAfterRollback === 5,
      "transactional_outbox_rollback_invalid");
    expect(committedEvent === 1, "transactional_outbox_commit_missing");
    expect(directWriteBlocked, "projection_writer_guard_missing");

    report = {
      schemaVersion: 1,
      generatedAt: new Date().toISOString(),
      status: "passed",
      database: { engine: "PostgreSQL", version: (await upgradePool.query("show server_version")).rows[0].server_version },
      migrations: { fresh: "V001->V013", upgrade: "V012->V013" },
      acceptance: {
        passed: 8,
        total: 8,
        checks: {
          cleanMigration: true,
          additiveUpgrade: true,
          tagAuthorityPreserved: true,
          difficultyAuthorityPreserved: true,
          legacyQuestionFieldsPreserved: true,
          existingAuthorityBackfilledToOutbox: true,
          authorityAndOutboxShareTransaction: true,
          projectionDirectWriteRejected: true,
        },
      },
      cleanup: "pending",
    };
  } finally {
    if (freshPool) await freshPool.end();
    if (upgradePool) await upgradePool.end();
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
