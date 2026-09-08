/** 中文说明：真实候选库只读备份；迁移冲突、直接 SQL 与 HTTP 并发均在隔离副本验证。 */
import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { Pool } from 'pg';
import { reservePort, startEmbeddedPostgresCluster } from '../tests/helpers/runtime_testkit.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const args = process.argv.slice(2);
assert.equal(args.length, 4); assert.equal(args[0], '--source-data-root'); assert.equal(args[2], '--out-dir');
const output = path.resolve(args[3]); await fs.mkdir(output, { recursive: true });
const config = JSON.parse(await fs.readFile(path.join(path.resolve(args[1]), 'local.private.json'), 'utf8'));
assert.equal(config.database, 'teachbase_candidates');
const identity = { workspaceId: config.workspaceId, actorUserId: config.actorUserId };
const pgBin = process.env.TEACHBASE_PG_BIN || (process.platform === 'win32' ? 'C:/Program Files/PostgreSQL/18/bin' : '');
const ext = process.platform === 'win32' ? '.exe' : '';
const scanSql = await fs.readFile(path.join(root, 'tools/sql/scan_taxonomy_primary_conflicts.sql'), 'utf8');
const migration = await fs.readFile(path.join(root, 'backend/teachbase-server/src/main/resources/db/migration/V009__single_primary_per_taxonomy_version.sql'), 'utf8');
const source = new Pool({ host: '127.0.0.1', port: config.port, user: config.user,
  password: config.password, database: config.database, connectionTimeoutMillis: 3000 });
const report = { startedAt: new Date().toISOString(), scope: 'G1_per_revision_per_taxonomy_version',
  realQuestionsApproved: false, testsUseIsolatedClones: true, checks: [] };
async function check(name, body) {
  try { const evidence = await body(); report.checks.push({ name, status: 'passed', evidence }); }
  catch (e) { report.checks.push({ name, status: 'failed', error: e.message }); }
  console.log(JSON.stringify(report.checks.at(-1)));
}
async function run(command, commandArgs, env = process.env) {
  const child = spawn(command, commandArgs, { env, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
  const out = [], err = []; child.stdout.on('data', b => out.push(b)); child.stderr.on('data', b => err.push(b));
  const code = await new Promise((resolve, reject) => { child.once('exit', resolve); child.once('error', reject); });
  assert.equal(code, 0, Buffer.concat(err).toString('utf8').slice(-1800));
  return Buffer.concat(out);
}
async function fingerprint(pool) {
  return (await pool.query(`select md5(coalesce(string_agg(row_to_json(t)::text,'' order by kind,id),'')) as h from (
    select 'question' as kind,question_id::text as id,to_jsonb(q) as row from teachbase_app.question q
    union all select 'revision',question_revision_id::text,to_jsonb(r) from teachbase_app.question_revision r
    union all select 'review',review_case_id::text,to_jsonb(c) from teachbase_app.review_case c
    union all select 'tag',question_taxonomy_link_id::text,to_jsonb(t) from teachbase_app.question_taxonomy_link t) t`)).rows[0].h;
}
const before = await fingerprint(source);
let cluster, pool, probe, java;
const javaLogs = [];
try {
  await check('source_conflict_scan_read_only', async () => {
    const client = await source.connect();
    try {
      await client.query('begin read only');
      const conflicts = (await client.query(scanSql)).rows;
      const counts = (await client.query(`select count(*)::int as revisions,
        count(*) filter(where review_status='pending_review')::int as pending,
        count(*) filter(where review_status='approved')::int as approved from teachbase_app.question_revision`)).rows[0];
      await client.query('commit');
      assert.equal(conflicts.length, 0); assert.deepEqual(counts, { revisions: 52, pending: 52, approved: 0 });
      return { conflicts, counts };
    } finally { await client.query('rollback').catch(() => {}); client.release(); }
  });
  const dump = path.join(output, 'source.dump');
  await run(path.join(pgBin, `pg_dump${ext}`), ['-h', '127.0.0.1', '-p', String(config.port), '-U', config.user,
    '-d', config.database, '-Fc', '-f', dump], { ...process.env, PGPASSWORD: config.password });
  cluster = await startEmbeddedPostgresCluster('g1_primary_constraint');
  async function restored(name) {
    const db = await cluster.createDatabase(name); const url = new URL(db.connectionString);
    await run(path.join(pgBin, `pg_restore${ext}`), ['-h', '127.0.0.1', '-p', String(cluster.port),
      '-U', decodeURIComponent(url.username), '-d', db.database, '--no-owner', '--no-privileges', dump],
      { ...process.env, PGPASSWORD: decodeURIComponent(url.password) });
    return { ...db, pool: new Pool({ connectionString: db.connectionString }), url };
  }
  const bad = await restored('g1_migration_conflict_test'); probe = bad.pool;
  const question = (await probe.query('select question_id, question_revision_id from teachbase_app.question_revision order by question_revision_id limit 1')).rows[0];
  const versionId = crypto.randomUUID(), nodeIds = [crypto.randomUUID(), crypto.randomUUID()];
  await probe.query(`insert into teachbase_app.taxonomy_version(taxonomy_version_id,workspace_id,taxonomy_key,version_key,subject,created_by)
    values($1,$2,'g1-migration-fixture','fixture-v1','test-only',$3)`, [versionId, identity.workspaceId, identity.actorUserId]);
  for (const [n, nodeId] of nodeIds.entries()) {
    await probe.query(`insert into teachbase_app.taxonomy_node(taxonomy_node_id,taxonomy_version_id,workspace_id,knowledge_code,display_name)
      values($1,$2,$3,$4,'test-only node')`, [nodeId, versionId, identity.workspaceId, `NODE.${n}`]);
    await probe.query(`insert into teachbase_app.question_taxonomy_link(question_taxonomy_link_id,workspace_id,question_id,question_revision_id,
      taxonomy_node_id,taxonomy_version_id,relation_type,assignment_source,assigned_by)
      values($1,$2,$3,$4,$5,$6,'primary','import',$7)`, [crypto.randomUUID(), identity.workspaceId,
      question.question_id, question.question_revision_id, nodeId, versionId, identity.actorUserId]);
  }
  await check('migration_conflicts_abort_without_repair', async () => {
    const conflicts = (await probe.query(scanSql)).rows;
    assert.equal(conflicts.length, 1); assert.equal(conflicts[0].primary_count, 2);
    const snapshot = await fingerprint(probe);
    const client = await probe.connect(); let failure;
    try {
      await client.query('begin');
      try { await client.query(migration); } catch (e) { failure = e; }
      await client.query('rollback');
    } finally { client.release(); }
    assert.equal(failure?.code, '23505'); assert.equal(failure?.message, 'taxonomy_primary_conflicts_before_v009');
    assert.equal(JSON.parse(failure.detail)[0].primary_count, 2);
    assert.equal(await fingerprint(probe), snapshot);
    assert.equal((await probe.query("select to_regclass('teachbase_app.uq_question_primary_per_taxonomy_version') as idx")).rows[0].idx, null);
    return { conflicts, migrationSqlstate: failure.code, dataPreserved: true, partialIndexLeftBehind: false };
  });
  const clean = await restored('g1_clean_test'); pool = clean.pool;
  const port = await reservePort(), baseUrl = `http://127.0.0.1:${port}`;
  java = spawn('java', ['-jar', path.join(root, 'backend/teachbase-server/target/teachbase-server-0.1.0-SNAPSHOT.jar')], {
    cwd: root, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'], env: { ...process.env,
      TEACHBASE_DATABASE_URL: `jdbc:postgresql://127.0.0.1:${cluster.port}/${clean.database}`,
      TEACHBASE_DATABASE_USER: decodeURIComponent(clean.url.username), TEACHBASE_DATABASE_PASSWORD: decodeURIComponent(clean.url.password),
      TEACHBASE_SERVER_PORT: String(port), SERVER_ADDRESS: '127.0.0.1', TEACHBASE_RENDER_ENABLED: 'false',
      TEACHBASE_STORAGE_ROOT: path.join(output, 'storage') } });
  for (const stream of [java.stdout, java.stderr]) stream.on('data', b => javaLogs.push(b));
  let healthy = false;
  for (let n = 0; n < 160; n++) {
    assert.equal(java.exitCode, null, 'clone_java_exited');
    try { if ((await fetch(baseUrl + '/actuator/health', { signal: AbortSignal.timeout(1000) })).ok) { healthy = true; break; } } catch {}
    await new Promise(r => setTimeout(r, 300));
  }
  assert.ok(healthy, 'clone_health_timeout');
  async function api(route, body) {
    const r = await fetch(baseUrl + route, { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body), signal: AbortSignal.timeout(20000) });
    return { status: r.status, data: await r.json() };
  }
  function ok(r) { assert.equal(r.status, 200, JSON.stringify(r.data)); return r.data; }
  await check('flyway_v009_preserves_52_candidate_rows', async () => {
    assert.equal(await fingerprint(pool), before);
    const migrationRow = (await pool.query("select version,success from teachbase_app.flyway_schema_history where version='009'")).rows[0];
    assert.equal(migrationRow?.success, true);
    const index = (await pool.query("select indexdef from pg_indexes where schemaname='teachbase_app' and indexname='uq_question_primary_per_taxonomy_version'")).rows[0].indexdef;
    assert.ok(index.includes('UNIQUE')); return { migration: migrationRow, index, rowsUnchanged: true };
  });
  const rows = (await pool.query('select q.source_system,q.source_key,q.external_key,r.* from teachbase_app.question q join teachbase_app.question_revision r using(question_id) order by r.question_revision_id')).rows;
  const revision = rows[0].question_revision_id;
  async function taxonomy(versionKey) {
    const v = ok(await api('/api/v1/taxonomies/versions', { ...identity, taxonomyKey: 'g1-test-only', versionKey, subject: 'test-only', stage: '', schemaVersion: 1 }));
    const nodes = [];
    for (const code of ['NODE.A', 'NODE.B', 'NODE.C']) nodes.push(ok(await api(`/api/v1/taxonomies/versions/${v.taxonomyVersionId}/nodes`, {
      ...identity, knowledgeCode: code, displayName: code, parentNodeId: null, sortOrder: 0, metadata: { testOnly: true }, aliases: [] })));
    ok(await api(`/api/v1/taxonomies/versions/${v.taxonomyVersionId}/activate`, identity));
    return { ...v, nodes };
  }
  const v1 = await taxonomy('v1');
  const assign = (node, relationType = 'primary', questionRevisionId = revision) => api('/api/v1/taxonomies/assignments', {
    ...identity, questionRevisionId, taxonomyNodeId: node.taxonomyNodeId, relationType, assignmentSource: 'import', confidence: null });
  let winner, loser, winningId;
  await check('concurrent_primary_binding_one_success_one_409', async () => {
    const rs = await Promise.all(v1.nodes.slice(0, 2).map(n => assign(n)));
    assert.deepEqual(rs.map(r => r.status).sort(), [200, 409]);
    const win = rs.findIndex(r => r.status === 200); winner = v1.nodes[win]; loser = v1.nodes[1 - win];
    winningId = rs[win].data.questionTaxonomyLinkId;
    assert.equal(rs[1 - win].data.detail, 'taxonomy_primary_conflict');
    return { statuses: rs.map(r => r.status), conflictCode: rs[1 - win].data.detail };
  });
  await check('replay_primary_retains_original_link', async () => {
    assert.equal(ok(await assign(winner)).questionTaxonomyLinkId, winningId);
    const r = await assign(loser); assert.equal(r.status, 409); assert.equal(r.data.detail, 'taxonomy_primary_conflict');
    const links = (await pool.query("select * from teachbase_app.question_taxonomy_link where question_revision_id=$1 and relation_type='primary'", [revision])).rows;
    assert.equal(links.length, 1); assert.equal(links[0].question_taxonomy_link_id, winningId);
  });
  await check('secondary_bindings_remain_multiple_and_idempotent', async () => {
    const a = ok(await assign(loser, 'secondary')); ok(await assign(v1.nodes[2], 'secondary'));
    assert.equal(ok(await assign(loser, 'secondary')).questionTaxonomyLinkId, a.questionTaxonomyLinkId);
    assert.equal((await pool.query("select count(*)::int as n from teachbase_app.question_taxonomy_link where relation_type='secondary'")).rows[0].n, 2);
  });
  await check('direct_sql_insert_and_promotion_blocked_by_index', async () => {
    const commands = [
      { sql: `insert into teachbase_app.question_taxonomy_link(question_taxonomy_link_id,workspace_id,question_id,question_revision_id,
        taxonomy_node_id,taxonomy_version_id,relation_type,assignment_source,assigned_by)
        values($1,$2,$3,$4,$5,$6,'primary','import',$7)`, params: [crypto.randomUUID(), identity.workspaceId,
        rows[0].question_id, revision, loser.taxonomyNodeId, v1.taxonomyVersionId, identity.actorUserId] },
      { sql: "update teachbase_app.question_taxonomy_link set relation_type='primary' where taxonomy_node_id=$1 and relation_type='secondary'", params: [loser.taxonomyNodeId] }
    ];
    for (const command of commands) {
      let failure; try { await pool.query(command.sql, command.params); } catch (e) { failure = e; }
      assert.equal(failure?.code, '23505'); assert.equal(failure?.constraint, 'uq_question_primary_per_taxonomy_version');
    }
    return { sqlstate: '23505', constraint: 'uq_question_primary_per_taxonomy_version', operations: ['insert', 'update'] };
  });
  await check('same_question_new_revision_has_independent_primary', async () => {
    const r = rows[0];
    const item = { externalKey: r.external_key, sourceSystem: r.source_system, sourceKey: r.source_key,
      reviewStatus: 'pending_review', subject: r.subject, stage: r.stage, grade: r.grade, questionType: r.question_type,
      title: r.title, lesson: r.lesson, primaryKnowledgeTag: r.primary_knowledge_tag, secondaryKnowledgeTags: r.secondary_knowledge_tags_json,
      difficultyStars: r.difficulty_stars, materialMarkdown: r.material_markdown, stemMarkdown: r.stem_markdown + '\nG1 test-only revision',
      options: r.options_json, answerMarkdown: r.answer_markdown, analysisMarkdown: r.analysis_markdown,
      content: r.content_json, provenance: { testOnly: true, purpose: 'g1-revision-scope' } };
    const imported = ok(await api('/api/v1/questions/import-batch', { ...identity, questions: [item] })).results[0];
    assert.equal(imported.questionId, r.question_id); assert.equal(imported.revisionNo, 2);
    ok(await assign(loser, 'primary', imported.questionRevisionId));
    return { revisionNo: imported.revisionNo, originalPrimaryPreserved: true };
  });
  await check('cross_version_history_preserved_no_semantic_migration', async () => {
    const v2 = await taxonomy('v2'); ok(await assign(v2.nodes[0]));
    const links = (await pool.query("select taxonomy_version_id from teachbase_app.question_taxonomy_link where question_revision_id=$1 and relation_type='primary' order by taxonomy_version_id", [revision])).rows;
    assert.equal(links.length, 2); assert.ok(links.some(l => l.taxonomy_version_id === v1.taxonomyVersionId));
    assert.ok(links.some(l => l.taxonomy_version_id === v2.taxonomyVersionId));
    const old = await assign(loser); assert.equal(old.status, 409); assert.equal(old.data.detail, 'taxonomy_version_not_active');
    assert.equal((await pool.query(scanSql)).rows.length, 0);
    return { versionsWithHistoricalPrimary: 2, sameVersionConflicts: 0 };
  });
} catch (e) { report.fatal = e.message; }
finally {
  if (java && java.exitCode === null) { const stopped = new Promise(r => java.once('exit', r)); java.kill(); await stopped; }
  await fs.writeFile(path.join(output, 'java.log'), Buffer.concat(javaLogs));
  if (pool) await pool.end(); if (probe) await probe.end(); if (cluster) await cluster.stop();
  await check('original_question_review_and_tag_fingerprint_unchanged', async () => assert.equal(await fingerprint(source), before));
  await source.end();
  report.finishedAt = new Date().toISOString();
  report.status = report.fatal || report.checks.some(c => c.status === 'failed') ? 'failed' : 'passed';
  await fs.writeFile(path.join(output, 'report.json'), JSON.stringify(report, null, 2));
}
console.log(JSON.stringify({ status: report.status, fatal: report.fatal, checks: report.checks.length }));
if (report.status !== 'passed') process.exitCode = 1;
