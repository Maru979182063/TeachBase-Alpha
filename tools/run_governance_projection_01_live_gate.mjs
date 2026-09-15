import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { Pool } from "pg";

import { fetchJson, reservePort, startEmbeddedPostgresCluster } from "../tests/helpers/runtime_testkit.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const serverRoot = path.join(root, "backend", "teachbase-server");
const jarPath = path.join(serverRoot, "target", "teachbase-server-0.1.0-SNAPSHOT.jar");
const reportPath = path.join(root, "docs", "reports", "governance_projection_01_live_gate.json");
const hash = (value) => crypto.createHash("sha256").update(value).digest("hex");
const uuid = () => crypto.randomUUID();

function expect(value, message) {
  if (!value) throw new Error(message);
}

async function waitForHealth(baseUrl, child, logs) {
  const deadline = Date.now() + 60_000;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) throw new Error(`java_server_exited:${child.exitCode}\n${logs.stderr.join("")}`);
    try {
      const response = await fetchJson(`${baseUrl}/actuator/health`);
      if (response.ok && response.data?.status === "UP") return;
    } catch {
      // Flyway 与 HTTP 端口仍在启动。
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`java_server_health_timeout\n${logs.stderr.join("")}`);
}

async function startServer(cluster, database, credentials, enabled) {
  const port = await reservePort();
  const baseUrl = `http://127.0.0.1:${port}`;
  const logs = { stdout: [], stderr: [] };
  const child = spawn("java", ["-jar", jarPath], {
    cwd: serverRoot,
    env: {
      ...process.env,
      TEACHBASE_DATABASE_URL: `jdbc:postgresql://127.0.0.1:${cluster.port}/${database}`,
      TEACHBASE_DATABASE_USER: credentials.username,
      TEACHBASE_DATABASE_PASSWORD: credentials.password,
      TEACHBASE_SERVER_PORT: String(port),
      TEACHBASE_RENDERING_ENABLED: "false",
      TEACHBASE_GOVERNANCE_PROJECTION_ENABLED: String(enabled),
      TEACHBASE_GOVERNANCE_PROJECTION_POLL_DELAY: "25ms",
      TEACHBASE_GOVERNANCE_PROJECTION_LEASE_DURATION: "1s",
      TEACHBASE_GOVERNANCE_PROJECTION_RETRY_DELAY: "2s",
      TEACHBASE_GOVERNANCE_PROJECTION_BATCH_SIZE: "100",
    },
    stdio: ["ignore", "pipe", "pipe"],
  });
  child.stdout.on("data", (chunk) => logs.stdout.push(String(chunk)));
  child.stderr.on("data", (chunk) => logs.stderr.push(String(chunk)));
  await waitForHealth(baseUrl, child, logs);
  return { child, baseUrl, logs };
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
  }
}

async function inTransaction(pool, work) {
  const client = await pool.connect();
  try {
    await client.query("begin");
    const result = await work(client);
    await client.query("commit");
    return result;
  } catch (error) {
    await client.query("rollback");
    throw error;
  } finally {
    client.release();
  }
}

async function seedWorkspace(client, slug, ownerId) {
  const workspaceId = uuid();
  await client.query("insert into teachbase_app.workspace(workspace_id,slug,display_name) values($1,$2,$2)", [workspaceId, slug]);
  await client.query("insert into teachbase_app.app_user(user_id,email,display_name) values($1,$2,$2)", [ownerId, `${slug}@example.invalid`]);
  await client.query("insert into teachbase_app.workspace_member(workspace_id,user_id,member_role) values($1,$2,'owner')", [workspaceId, ownerId]);
  return workspaceId;
}

async function seedQuestion(client, workspaceId, actorId, key) {
  const questionId = uuid();
  const revisionId = uuid();
  const contentHash = hash(`question:${workspaceId}:${key}`);
  await client.query(`insert into teachbase_app.question
    (question_id,workspace_id,external_key,source_system,source_key,current_revision_no,created_by,updated_by)
    values($1,$2,$3,'projection-gate',$3,1,$4,$4)`, [questionId, workspaceId, key, actorId]);
  await client.query(`insert into teachbase_app.question_revision
    (question_revision_id,question_id,workspace_id,revision_no,review_status,subject,stage,grade,
     question_type,primary_knowledge_tag,difficulty_stars,stem_markdown,content_json,content_hash,
     source_payload_hash,import_envelope_hash,created_by)
    values($1,$2,$3,1,'pending_review','数学','高中','高一','解答题','legacy-only',2,$4,'{}',$5,$5,$5,$6)`,
  [revisionId, questionId, workspaceId, `治理投影题目 ${key}`, contentHash, actorId]);
  return { questionId, revisionId, contentHash };
}

async function seedTaxonomy(client, workspaceId, actorId, suffix) {
  const versionId = uuid();
  await client.query(`insert into teachbase_app.taxonomy_version
    (taxonomy_version_id,workspace_id,taxonomy_key,version_key,subject,stage,status,schema_version,created_by)
    values($1,$2,'senior-math-knowledge',$3,'数学','高中','draft',1,$4)`,
  [versionId, workspaceId, `v1-${suffix}`, actorId]);
  const nodes = {};
  for (const [code, name] of [["A", "圆周角"], ["B", "切线"], ["C", "圆的性质"], ["D", "辅助线"]]) {
    nodes[code] = uuid();
    await client.query(`insert into teachbase_app.taxonomy_node
      (taxonomy_node_id,taxonomy_version_id,workspace_id,knowledge_code,display_name,sort_order)
      values($1,$2,$3,$4,$5,$6)`, [nodes[code], versionId, workspaceId, code, name, Object.keys(nodes).length]);
  }
  return { versionId, nodes };
}

async function seedRubric(client, workspaceId, actorId, suffix) {
  const rubricVersionId = uuid();
  await client.query(`insert into teachbase_app.difficulty_rubric_version
    (rubric_version_id,workspace_id,rubric_key,version_code,subject,stage,grade,
     definitions_json,rubric_hash,status,created_by)
    values($1,$2,'senior-math-five-star',$3,'数学','高中','高一',$4,$5,'active',$6)`,
  [rubricVersionId, workspaceId, `v1-${suffix}`,
    { "1": "容易", "2": "较易", "3": "中等", "4": "较难", "5": "困难" },
    hash(`rubric:${workspaceId}`), actorId]);
  return rubricVersionId;
}

async function createTagSnapshot(client, fixture, primary, secondary, suffix) {
  const snapshotId = uuid();
  const feedbackId = uuid();
  const labelSetHash = hash(`labels:${primary || ""}:${secondary.join(",")}`);
  await client.query(`insert into teachbase_app.question_tag_snapshot
    (snapshot_id,workspace_id,question_id,question_revision_id,taxonomy_key,taxonomy_version_id,
     snapshot_kind,label_set_hash,snapshot_hash,item_count,created_by)
    values($1,$2,$3,$4,'senior-math-knowledge',$5,'HUMAN_FINAL',$6,$7,$8,$9)`,
  [snapshotId, fixture.workspaceId, fixture.questionId, fixture.revisionId, fixture.taxonomyVersionId,
    labelSetHash, hash(`tag-snapshot:${suffix}`), (primary ? 1 : 0) + secondary.length, fixture.actorId]);
  let position = 0;
  if (primary) {
    await client.query(`insert into teachbase_app.question_tag_snapshot_item
      (snapshot_item_id,snapshot_id,workspace_id,taxonomy_version_id,taxonomy_node_id,relation_type,position_index)
      values($1,$2,$3,$4,$5,'primary',0)`,
    [uuid(), snapshotId, fixture.workspaceId, fixture.taxonomyVersionId, primary]);
  }
  for (const nodeId of secondary) {
    await client.query(`insert into teachbase_app.question_tag_snapshot_item
      (snapshot_item_id,snapshot_id,workspace_id,taxonomy_version_id,taxonomy_node_id,relation_type,position_index)
      values($1,$2,$3,$4,$5,'secondary',$6)`,
    [uuid(), snapshotId, fixture.workspaceId, fixture.taxonomyVersionId, nodeId, position++]);
  }
  await client.query(`insert into teachbase_app.question_tag_feedback
    (feedback_id,workspace_id,question_id,question_revision_id,taxonomy_key,taxonomy_version_id,
     before_snapshot_id,after_snapshot_id,outcome,reviewer_id,client_mutation_id,request_hash,
     expected_state_version,derived_operations_json)
    values($1,$2,$3,$4,'senior-math-knowledge',$5,$6,$6,$7,$8,$9,$10,$11,'[]')`,
  [feedbackId, fixture.workspaceId, fixture.questionId, fixture.revisionId, fixture.taxonomyVersionId,
    snapshotId, suffix.includes("initial") ? "confirmed" : "corrected", fixture.actorId,
    `tag-${suffix}`, hash(`tag-request:${suffix}`), fixture.stateVersion - 1]);
  return { snapshotId, feedbackId, labelSetHash };
}

async function createDifficultySnapshot(client, fixture, value, suffix) {
  const snapshotId = uuid();
  const feedbackId = uuid();
  await client.query(`insert into teachbase_app.question_difficulty_snapshot
    (snapshot_id,workspace_id,question_id,question_revision_id,rubric_key,rubric_version_id,
     context_key,context_json,context_hash,snapshot_kind,difficulty_value,snapshot_hash,created_by)
    values($1,$2,$3,$4,'senior-math-five-star',$5,'grade-10-default',$6,$7,
      'HUMAN_FINAL',$8,$9,$10)`,
  [snapshotId, fixture.workspaceId, fixture.questionId, fixture.revisionId, fixture.rubricVersionId,
    { subject: "数学", stage: "高中", grade: "高一" }, hash("grade-10-default"), value,
    hash(`difficulty-snapshot:${suffix}`), fixture.actorId]);
  await client.query(`insert into teachbase_app.question_difficulty_feedback
    (feedback_id,workspace_id,question_id,question_revision_id,rubric_key,rubric_version_id,
     context_key,before_snapshot_id,after_snapshot_id,outcome,reviewer_id,client_mutation_id,
     request_hash,expected_state_version,derived_operations_json)
    values($1,$2,$3,$4,'senior-math-five-star',$5,'grade-10-default',$6,$6,$7,$8,$9,$10,$11,'[]')`,
  [feedbackId, fixture.workspaceId, fixture.questionId, fixture.revisionId, fixture.rubricVersionId,
    snapshotId, suffix.includes("initial") ? "confirmed" : "corrected", fixture.actorId,
    `difficulty-${suffix}`, hash(`difficulty-request:${suffix}`), fixture.stateVersion - 1]);
  return { snapshotId, feedbackId };
}

async function createInitialAuthority(client, fixture, primary, secondary, difficulty) {
  const tag = await createTagSnapshot(client, { ...fixture, stateVersion: 5 }, primary, secondary, `${fixture.key}-initial`);
  const tagStateId = fixture.tagStateId || uuid();
  await client.query(`insert into teachbase_app.question_tag_state
    (state_id,workspace_id,question_id,question_revision_id,taxonomy_key,taxonomy_version_id,
     current_snapshot_id,current_feedback_id,state_version,status,updated_by)
    values($1,$2,$3,$4,'senior-math-knowledge',$5,$6,$7,5,'reviewed',$8)`,
  [tagStateId, fixture.workspaceId, fixture.questionId, fixture.revisionId,
    fixture.taxonomyVersionId, tag.snapshotId, tag.feedbackId, fixture.actorId]);
  const diff = await createDifficultySnapshot(client, { ...fixture, stateVersion: 2 }, difficulty, `${fixture.key}-initial`);
  const difficultyStateId = fixture.difficultyStateId || uuid();
  await client.query(`insert into teachbase_app.question_difficulty_state
    (state_id,workspace_id,question_id,question_revision_id,rubric_key,rubric_version_id,
     context_key,current_snapshot_id,current_feedback_id,state_version,status,updated_by)
    values($1,$2,$3,$4,'senior-math-five-star',$5,'grade-10-default',$6,$7,2,'reviewed',$8)`,
  [difficultyStateId, fixture.workspaceId, fixture.questionId, fixture.revisionId,
    fixture.rubricVersionId, diff.snapshotId, diff.feedbackId, fixture.actorId]);
  return { tagStateId, difficultyStateId, tagSnapshotId: tag.snapshotId, difficultySnapshotId: diff.snapshotId };
}

async function updateAuthority(client, fixture, stateIds, primary, secondary, difficulty) {
  const tag = await createTagSnapshot(client, { ...fixture, stateVersion: 6 }, primary, secondary, `${fixture.key}-updated`);
  await client.query(`update teachbase_app.question_tag_state set current_snapshot_id=$1,
    current_feedback_id=$2,state_version=6,status='reviewed',updated_by=$3,updated_at=now()
    where state_id=$4 and state_version=5`, [tag.snapshotId, tag.feedbackId, fixture.actorId, stateIds.tagStateId]);
  const diff = await createDifficultySnapshot(client, { ...fixture, stateVersion: 3 }, difficulty, `${fixture.key}-updated`);
  await client.query(`update teachbase_app.question_difficulty_state set current_snapshot_id=$1,
    current_feedback_id=$2,state_version=3,status='reviewed',updated_by=$3,updated_at=now()
    where state_id=$4 and state_version=2`,
  [diff.snapshotId, diff.feedbackId, fixture.actorId, stateIds.difficultyStateId]);
}

async function waitFor(pool, check, code, timeout = 20_000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    const value = await check();
    if (value) return value;
    await new Promise((resolve) => setTimeout(resolve, 25));
  }
  throw new Error(code);
}

async function waitForEvent(pool, eventId, minimumAttempts = 0) {
  return waitFor(pool, async () => {
    const row = (await pool.query(`select status,attempt_count from teachbase_app.governance_projection_outbox
      where event_id=$1`, [eventId])).rows[0];
    return row?.status === "processed" && row.attempt_count >= minimumAttempts ? row : null;
  }, `projection_event_not_processed:${eventId}`);
}

async function canonicalProjection(pool, workspaceId) {
  return (await pool.query(`select jsonb_build_object(
    'tags',(select coalesce(jsonb_agg(to_jsonb(x) order by x.question_revision_id,x.taxonomy_key),'[]')
      from (select p.projection_id,p.question_revision_id,p.taxonomy_key,p.taxonomy_version_id,
        p.current_snapshot_id,p.primary_node_id,p.decision_source,p.tag_status,
        p.authority_state_version,p.label_set_hash,p.projection_semantic_hash,
        coalesce((select jsonb_agg(s.taxonomy_node_id order by s.position_index)
          from teachbase_app.question_tag_current_projection_secondary s
          where s.projection_id=p.projection_id),'[]') secondary
        from teachbase_app.question_tag_current_projection p where p.workspace_id=$1) x),
    'difficulties',(select coalesce(jsonb_agg(to_jsonb(x) order by x.question_revision_id,x.rubric_key,x.context_key),'[]')
      from (select projection_id,question_revision_id,rubric_key,rubric_version_id,context_key,
        context_hash,current_snapshot_id,difficulty_value,decision_source,difficulty_status,
        authority_state_version,projection_semantic_hash
        from teachbase_app.question_difficulty_current_projection where workspace_id=$1) x)
  ) value`, [workspaceId])).rows[0].value;
}

async function main() {
  await fs.access(jarPath);
  const cluster = await startEmbeddedPostgresCluster("governance_projection_01_live_gate");
  let pool;
  let server;
  let report;
  try {
    const database = await cluster.createDatabase("governance_projection_01_test");
    const url = new URL(database.connectionString);
    const credentials = { username: decodeURIComponent(url.username), password: decodeURIComponent(url.password) };
    server = await startServer(cluster, database.database, credentials, false);
    pool = new Pool({ connectionString: database.connectionString });

    const actorA = uuid();
    const actorB = uuid();
    const seeded = await inTransaction(pool, async (client) => {
      const workspaceA = await seedWorkspace(client, "projection-a", actorA);
      const workspaceB = await seedWorkspace(client, "projection-b", actorB);
      const taxonomyA = await seedTaxonomy(client, workspaceA, actorA, "a");
      const taxonomyB = await seedTaxonomy(client, workspaceB, actorB, "b");
      const rubricA = await seedRubric(client, workspaceA, actorA, "a");
      const rubricB = await seedRubric(client, workspaceB, actorB, "b");
      const questionsA = [];
      for (const key of ["q1", "q2", "q3", "q4-recovery"]) {
        const question = await seedQuestion(client, workspaceA, actorA, key);
        questionsA.push({ ...question, key, workspaceId: workspaceA, actorId: actorA,
          taxonomyVersionId: taxonomyA.versionId, rubricVersionId: rubricA });
      }
      const questionB = await seedQuestion(client, workspaceB, actorB, "q-foreign");
      const fixtureB = { ...questionB, key: "q-foreign", workspaceId: workspaceB, actorId: actorB,
        taxonomyVersionId: taxonomyB.versionId, rubricVersionId: rubricB };
      const states = [];
      states.push(await createInitialAuthority(client, questionsA[0], taxonomyA.nodes.A, [taxonomyA.nodes.C], 3));
      states.push(await createInitialAuthority(client, questionsA[1], taxonomyA.nodes.A, [taxonomyA.nodes.D], 3));
      states.push(await createInitialAuthority(client, questionsA[2], taxonomyA.nodes.C, [], 4));
      const foreignStates = await createInitialAuthority(client, fixtureB, taxonomyB.nodes.A, [taxonomyB.nodes.D], 4);
      return { workspaceA, workspaceB, taxonomyA, taxonomyB, rubricA, rubricB,
        questionsA, fixtureB, states, foreignStates };
    });

    const staleEvent = (await pool.query(`select event_id from teachbase_app.governance_projection_outbox
      where authority_state_id=$1 and domain='TAG'`, [seeded.states[0].tagStateId])).rows[0].event_id;
    await pool.query(`update teachbase_app.governance_projection_outbox set status='processing',
      lease_owner='stopped-worker',lease_until=now()+interval '500 milliseconds'
      where event_id=$1`, [staleEvent]);
    await stopChild(server.child);
    server = null;
    await new Promise((resolve) => setTimeout(resolve, 650));
    server = await startServer(cluster, database.database, credentials, true);
    await waitFor(pool, async () => {
      const row = (await pool.query(`select
        (select count(*)::int from teachbase_app.question_tag_current_projection) tags,
        (select count(*)::int from teachbase_app.question_difficulty_current_projection) difficulties,
        (select count(*)::int from teachbase_app.governance_projection_outbox where status<>'processed') open_events`)).rows[0];
      return row.tags === 4 && row.difficulties === 4 && row.open_events === 0 ? row : null;
    }, "initial_projection_or_restart_recovery_failed");

    const q1 = seeded.questionsA[0];
    const initialProjection = await canonicalProjection(pool, seeded.workspaceA);
    const initialQ1Tag = initialProjection.tags.find((value) => value.question_revision_id === q1.revisionId);
    expect(initialQ1Tag.authority_state_version === 5, "initial_tag_version_invalid");
    await inTransaction(pool, (client) => updateAuthority(
      client, q1, seeded.states[0], seeded.taxonomyA.nodes.B,
      [seeded.taxonomyA.nodes.C, seeded.taxonomyA.nodes.D], 4));
    await waitFor(pool, async () => {
      const row = (await pool.query(`select
        (select authority_state_version from teachbase_app.question_tag_current_projection
          where workspace_id=$1 and question_revision_id=$2) tag_version,
        (select authority_state_version from teachbase_app.question_difficulty_current_projection
          where workspace_id=$1 and question_revision_id=$2) difficulty_version`,
      [seeded.workspaceA, q1.revisionId])).rows[0];
      return Number(row.tag_version) === 6 && Number(row.difficulty_version) === 3 ? row : null;
    }, "authority_update_not_projected");

    const oldEvent = (await pool.query(`select event_id,attempt_count from teachbase_app.governance_projection_outbox
      where authority_state_id=$1 and authority_state_version=5`, [seeded.states[0].tagStateId])).rows[0];
    const beforeReplay = (await pool.query(`select authority_state_version,projection_semantic_hash,projected_at
      from teachbase_app.question_tag_current_projection where workspace_id=$1 and question_revision_id=$2`,
    [seeded.workspaceA, q1.revisionId])).rows[0];
    let minimumAttempts = oldEvent.attempt_count;
    for (let index = 0; index < 100; index++) {
      minimumAttempts++;
      await pool.query(`update teachbase_app.governance_projection_outbox set status='pending',
        available_at=now(),processed_at=null,lease_owner=null,lease_until=null where event_id=$1`, [oldEvent.event_id]);
      await waitForEvent(pool, oldEvent.event_id, minimumAttempts);
    }
    const afterReplay = (await pool.query(`select authority_state_version,projection_semantic_hash,projected_at
      from teachbase_app.question_tag_current_projection where workspace_id=$1 and question_revision_id=$2`,
    [seeded.workspaceA, q1.revisionId])).rows[0];
    expect(JSON.stringify(beforeReplay) === JSON.stringify(afterReplay), "duplicate_or_old_event_changed_projection");

    const recoveryStateId = uuid();
    const recoveryEventId = uuid();
    const recoveryEventKey = hash(`recovery:${recoveryStateId}`);
    const q4 = seeded.questionsA[3];
    await pool.query(`insert into teachbase_app.governance_projection_outbox
      (event_id,workspace_id,question_revision_id,domain,authority_state_id,authority_state_version,event_key)
      values($1,$2,$3,'TAG',$4,5,$5)`,
    [recoveryEventId, seeded.workspaceA, q4.revisionId, recoveryStateId, recoveryEventKey]);
    await waitFor(pool, async () => {
      const row = (await pool.query(`select status,attempt_count from teachbase_app.governance_projection_outbox
        where event_id=$1`, [recoveryEventId])).rows[0];
      return row.status === "failed" && row.attempt_count >= 1 ? row : null;
    }, "projection_failure_not_retained");
    await inTransaction(pool, async (client) => {
      await createInitialAuthority(client, {
        ...q4, key: "q4-recovery", workspaceId: seeded.workspaceA, actorId: actorA,
        taxonomyVersionId: seeded.taxonomyA.versionId, rubricVersionId: seeded.rubricA,
        tagStateId: recoveryStateId,
      }, seeded.taxonomyA.nodes.B, [seeded.taxonomyA.nodes.D], 4);
    });
    await pool.query(`update teachbase_app.governance_projection_outbox set available_at=now()
      where event_id=$1 and status='failed'`, [recoveryEventId]);
    await waitForEvent(pool, recoveryEventId, 2);

    const factsBeforeRebuild = (await pool.query(`select jsonb_build_object(
      'revision',(select to_jsonb(x) from (select content_hash,primary_knowledge_tag,difficulty_stars
        from teachbase_app.question_revision where question_revision_id=$1) x),
      'tagSnapshots',(select count(*)::int from teachbase_app.question_tag_snapshot),
      'tagFeedback',(select count(*)::int from teachbase_app.question_tag_feedback),
      'difficultySnapshots',(select count(*)::int from teachbase_app.question_difficulty_snapshot),
      'difficultyFeedback',(select count(*)::int from teachbase_app.question_difficulty_feedback),
      'tagState',(select to_jsonb(x) from (select current_snapshot_id,state_version,status
        from teachbase_app.question_tag_state where state_id=$2) x),
      'difficultyState',(select to_jsonb(x) from (select current_snapshot_id,state_version,status
        from teachbase_app.question_difficulty_state where state_id=$3) x)
    ) value`, [q1.revisionId, seeded.states[0].tagStateId, seeded.states[0].difficultyStateId])).rows[0].value;

    const combined = await fetchJson(`${server.baseUrl}/api/v1/questions/governance-query?workspaceId=${seeded.workspaceA}&actorUserId=${actorA}&subject=${encodeURIComponent("数学")}&stage=${encodeURIComponent("高中")}&taxonomyKey=senior-math-knowledge&primaryTagId=${seeded.taxonomyA.nodes.B}&rubricKey=senior-math-five-star&difficultyContextKey=grade-10-default&difficultyValue=4`);
    expect(combined.status === 200 && combined.data.items.length === 2
      && combined.data.items.some((item) => item.questionRevisionId === q1.revisionId),
    `combined_query_invalid:${JSON.stringify(combined.data)}`);
    const secondary = await fetchJson(`${server.baseUrl}/api/v1/questions/governance-query?workspaceId=${seeded.workspaceA}&actorUserId=${actorA}&secondaryTagId=${seeded.taxonomyA.nodes.D}`);
    expect(secondary.status === 200 && secondary.data.items.length === 3, "secondary_query_invalid");
    const exactQ1 = combined.data.items.find((item) => item.questionRevisionId === q1.revisionId);
    expect(exactQ1.tags.some((tag) => tag.authorityStateVersion === 6
      && tag.primaryNodeId === seeded.taxonomyA.nodes.B
      && JSON.stringify(tag.secondaryNodeIds) === JSON.stringify([seeded.taxonomyA.nodes.C, seeded.taxonomyA.nodes.D])),
    "tag_projection_payload_invalid");
    expect(exactQ1.difficulties.some((difficulty) => difficulty.authorityStateVersion === 3
      && difficulty.difficultyValue === 4), "difficulty_projection_payload_invalid");

    const foreignRead = await fetchJson(`${server.baseUrl}/api/v1/questions/governance-query?workspaceId=${seeded.workspaceA}&actorUserId=${actorB}&difficultyValue=4`);
    const ownRead = await fetchJson(`${server.baseUrl}/api/v1/questions/governance-query?workspaceId=${seeded.workspaceB}&actorUserId=${actorB}&difficultyValue=4`);
    expect(foreignRead.status === 403 && ownRead.status === 200 && ownRead.data.items.length === 1,
      "workspace_isolation_invalid");

    let directWriteBlocked = false;
    try {
      await pool.query(`update teachbase_app.question_tag_current_projection set tag_status='pending'
        where workspace_id=$1`, [seeded.workspaceA]);
    } catch (error) {
      directWriteBlocked = String(error.message).includes("governance_projection_direct_write_forbidden");
    }
    expect(directWriteBlocked, "projection_direct_update_not_blocked");

    const incremental = await canonicalProjection(pool, seeded.workspaceA);
    const rebuild = await fetchJson(`${server.baseUrl}/api/v1/internal/governance-projections/rebuild`, {
      method: "POST", body: { actorUserId: actorA, workspaceId: seeded.workspaceA },
    });
    expect(rebuild.status === 200 && rebuild.data.workspaceCount === 1,
      `workspace_rebuild_failed:${JSON.stringify(rebuild.data)}`);
    const rebuilt = await canonicalProjection(pool, seeded.workspaceA);
    expect(JSON.stringify(incremental) === JSON.stringify(rebuilt), "incremental_full_rebuild_mismatch");

    const rebuildAll = await fetchJson(`${server.baseUrl}/api/v1/internal/governance-projections/rebuild`, {
      method: "POST", body: { actorUserId: actorA, workspaceId: null },
    });
    expect(rebuildAll.status === 200 && rebuildAll.data.workspaceCount === 1,
      "actor_scoped_rebuild_all_invalid");
    const rebuiltAll = await canonicalProjection(pool, seeded.workspaceA);
    expect(JSON.stringify(incremental) === JSON.stringify(rebuiltAll), "rebuild_all_semantics_changed");

    const factsAfterRebuild = (await pool.query(`select jsonb_build_object(
      'revision',(select to_jsonb(x) from (select content_hash,primary_knowledge_tag,difficulty_stars
        from teachbase_app.question_revision where question_revision_id=$1) x),
      'tagSnapshots',(select count(*)::int from teachbase_app.question_tag_snapshot),
      'tagFeedback',(select count(*)::int from teachbase_app.question_tag_feedback),
      'difficultySnapshots',(select count(*)::int from teachbase_app.question_difficulty_snapshot),
      'difficultyFeedback',(select count(*)::int from teachbase_app.question_difficulty_feedback),
      'tagState',(select to_jsonb(x) from (select current_snapshot_id,state_version,status
        from teachbase_app.question_tag_state where state_id=$2) x),
      'difficultyState',(select to_jsonb(x) from (select current_snapshot_id,state_version,status
        from teachbase_app.question_difficulty_state where state_id=$3) x)
    ) value`, [q1.revisionId, seeded.states[0].tagStateId, seeded.states[0].difficultyStateId])).rows[0].value;
    expect(JSON.stringify(factsBeforeRebuild) === JSON.stringify(factsAfterRebuild),
      "projection_mutated_authority_or_history");

    const health = await fetchJson(`${server.baseUrl}/api/v1/internal/governance-projections/health?workspaceId=${seeded.workspaceA}&actorUserId=${actorA}`);
    expect(health.status === 200 && health.data.tagLagCount === 0 && health.data.difficultyLagCount === 0
      && health.data.failedEventCount === 0, `projection_health_invalid:${JSON.stringify(health.data)}`);

    report = {
      schemaVersion: 1,
      generatedAt: new Date().toISOString(),
      status: "passed",
      database: { engine: "PostgreSQL", version: (await pool.query("show server_version")).rows[0].server_version },
      acceptance: {
        passed: 18,
        total: 18,
        checks: {
          tagProjectionImplemented: true,
          difficultyProjectionImplemented: true,
          authorityStateVersionPreserved: true,
          outOfOrderEventCannotDowngrade: true,
          duplicateEventReplay100Times: true,
          transactionalOutboxConsumed: true,
          failedProjectionRetainedAndRecovered: true,
          expiredLeaseRecoveredAfterWorkerRestart: true,
          workspaceFullRebuild: true,
          actorScopedFullRebuild: true,
          incrementalEqualsFullRebuild: true,
          minimalTagQuery: true,
          minimalDifficultyQuery: true,
          combinedQuery: true,
          secondaryTagQuery: true,
          workspaceIsolation: true,
          projectionDirectWriteBlocked: true,
          questionRevisionAndGovernanceHistoryUnchanged: true,
        },
      },
      projectionCounts: {
        workspaceA: { tags: incremental.tags.length, difficulties: incremental.difficulties.length },
        workspaceB: { tags: 1, difficulties: 1 },
      },
      legacyFallback: "question_revision legacy fields remain unchanged and are not projection authority",
      cleanup: "pending",
    };
  } finally {
    if (!report && server) {
      process.stderr.write(`\n--- governance projection server stdout tail ---\n${server.logs.stdout.join("").slice(-40_000)}`);
      process.stderr.write(`\n--- governance projection server stderr tail ---\n${server.logs.stderr.join("").slice(-10_000)}`);
    }
    if (pool) await pool.end();
    if (server) await stopChild(server.child);
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
