/** 中文说明：从真实候选库只读备份，恢复到一次性副本，测试审核、标签、选题和导出；不批准原库数据。 */
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
assert.equal(args.length, 4, 'required: --source-data-root PATH --out-dir PATH');
assert.equal(args[0], '--source-data-root'); assert.equal(args[2], '--out-dir');
const sourceRoot = path.resolve(args[1]);
const output = path.resolve(args[3]);
await fs.mkdir(output, { recursive: true });
const config = JSON.parse(await fs.readFile(path.join(sourceRoot, 'local.private.json'), 'utf8'));
assert.equal(config.database, 'teachbase_candidates');
const { workspaceId, actorUserId } = config;
const identity = { workspaceId, actorUserId };
const checks = [];
const report = { startedAt: new Date().toISOString(), checks, sourceReadOnly: true,
  reviewDecisionsAreTestFixtures: true, missingCapabilities: ['automatic_semantic_tagging',
    'independent_source_crops', 'pipeline_to_ingestion_scheduler', 'formal_authentication'] };
async function run(command, commandArgs, env = process.env) {
  const child = spawn(command, commandArgs, { env, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
  const out = []; const err = [];
  child.stdout.on('data', b => out.push(b)); child.stderr.on('data', b => err.push(b));
  const code = await new Promise((resolve, reject) => { child.on('exit', resolve); child.on('error', reject); });
  assert.equal(code, 0, Buffer.concat(err).toString('utf8').slice(-1500));
  return Buffer.concat(out);
}
async function test(name, action) {
  try { const evidence = await action(); checks.push({ name, status: 'passed', evidence }); }
  catch (e) { checks.push({ name, status: 'failed', error: e.message.slice(0, 1700) }); }
  console.log(JSON.stringify(checks.at(-1)));
}
async function findFile(dir, name) {
  let entries;
  try { entries = await fs.readdir(dir, { withFileTypes: true }); }
  catch (e) { if (e.code === 'ENOENT') return null; throw e; }
  for (const entry of entries) {
    const file = path.join(dir, entry.name);
    if (entry.isDirectory()) { const found = await findFile(file, name); if (found) return found; }
    else if (entry.name === name) return file;
  }
}
const pgBin = process.env.TEACHBASE_PG_BIN || (process.platform === 'win32' ? 'C:/Program Files/PostgreSQL/18/bin' : '');
const ext = process.platform === 'win32' ? '.exe' : '';
const sourcePool = new Pool({ host: '127.0.0.1', port: config.port, user: config.user,
  password: config.password, database: config.database });
async function fingerprint(pool) {
  const result = await pool.query(`select md5(coalesce(string_agg(row_to_json(t)::text, '' order by id),'')) as hash from (
    select question_revision_id::text as id, to_jsonb(r) as row from teachbase_app.question_revision r
    union all select review_case_id::text, to_jsonb(c) from teachbase_app.review_case c
    union all select question_id::text, to_jsonb(q) from teachbase_app.question q) t`);
  return result.rows[0].hash;
}
const originalHash = await fingerprint(sourcePool);
let cluster, pool, java;
try {
  await run(path.join(pgBin, `pg_dump${ext}`), ['-h', '127.0.0.1', '-p', String(config.port), '-U', config.user,
    '-d', config.database, '-Fc', '-f', path.join(output, 'source.dump')], { ...process.env, PGPASSWORD: config.password });
  cluster = await startEmbeddedPostgresCluster('real_candidate_workflow_test');
  const database = await cluster.createDatabase('real_candidate_workflow_test');
  const url = new URL(database.connectionString);
  await run(path.join(pgBin, `pg_restore${ext}`), ['-h', '127.0.0.1', '-p', String(cluster.port),
    '-U', decodeURIComponent(url.username), '-d', database.database, '--no-owner', '--no-privileges', path.join(output, 'source.dump')],
    { ...process.env, PGPASSWORD: decodeURIComponent(url.password) });
  pool = new Pool({ connectionString: database.connectionString });
  const storage = path.join(output, 'storage');
  await fs.cp(path.join(sourceRoot, 'storage'), storage, { recursive: true });
  const vendor = path.join(root, 'tools/vendor/document-renderer');
  const pandoc = await findFile(vendor, `pandoc${ext}`);
  const typst = await findFile(vendor, `typst${ext}`);
  const rendererReady = Boolean(pandoc && typst);
  const port = await reservePort(); const baseUrl = `http://127.0.0.1:${port}`;
  const logs = [];
  java = spawn('java', ['-jar', path.join(root, 'backend/teachbase-server/target/teachbase-server-0.1.0-SNAPSHOT.jar')], {
    cwd: root, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'], env: { ...process.env,
      TEACHBASE_DATABASE_URL: `jdbc:postgresql://127.0.0.1:${cluster.port}/${database.database}`,
      TEACHBASE_DATABASE_USER: decodeURIComponent(url.username), TEACHBASE_DATABASE_PASSWORD: decodeURIComponent(url.password),
      TEACHBASE_SERVER_PORT: String(port), SERVER_ADDRESS: '127.0.0.1', TEACHBASE_STORAGE_ROOT: storage,
      TEACHBASE_RENDER_ENABLED: String(rendererReady), TEACHBASE_RENDER_PANDOC_PATH: pandoc || 'pandoc', TEACHBASE_RENDER_TYPST_PATH: typst || 'typst',
      TEACHBASE_RENDER_POLL_DELAY: '100ms', TEACHBASE_RENDER_PROCESS_TIMEOUT: '60s' } });
  for (const stream of [java.stdout, java.stderr]) stream.on('data', b => logs.push(b));
  let healthy = false;
  for (let n = 0; n < 160; n++) {
    assert.equal(java.exitCode, null, 'clone_java_exited');
    try { if ((await fetch(`${baseUrl}/actuator/health`)).ok) { healthy = true; break; } } catch {}
    await new Promise(r => setTimeout(r, 300));
  }
  assert.ok(healthy, 'clone_health_timeout');
  async function api(route, method = 'GET', body) {
    const response = await fetch(baseUrl + route, { method, headers: { 'Content-Type': 'application/json' },
      body: body ? JSON.stringify(body) : undefined, signal: AbortSignal.timeout(120000) });
    return { status: response.status, data: await response.json() };
  }
  function ok(response, status = 200) { assert.equal(response.status, status, JSON.stringify(response.data).slice(0, 1000)); return response.data; }
  const rows = (await pool.query(`select q.source_key, r.*, c.review_case_id from teachbase_app.question q
    join teachbase_app.question_revision r using(question_id) join teachbase_app.review_case c using(question_revision_id)
    where q.workspace_id=$1 order by q.source_key`, [workspaceId])).rows;
  const query = extra => new URLSearchParams({ ...identity, ...extra });
  const placements = rows.map(r => ({ questionRevisionId: r.question_revision_id,
    displayMode: 'full', showAnswer: true, showAnalysis: true }));
  await test('backup_restore_exact_candidates', async () => {
    assert.equal(await fingerprint(pool), originalHash); assert.equal(rows.length, 52); return { count: rows.length };
  });
  await test('pending_search_real_phrases', async () => {
    const counts = {};
    for (const word of ['集合', '足球', '交集']) {
      const result = ok(await api(`/api/v1/questions/search?${query({ reviewStatus: 'pending_review', query: word, limit: '100' })}`));
      assert.ok(result.items.length > 0); counts[word] = result.items.length;
    }
    assert.equal(ok(await api(`/api/v1/questions/search?${query({})}`)).items.length, 0); return counts;
  });
  await test('pending_cannot_be_placed', async () => {
    const response = await api(`/api/v1/editor/documents/${crypto.randomUUID()}/question-references`, 'POST', {
      ...identity, expectedDraftVersion: 1, insertionIndex: 0, targetLayers: ['common'], questions: placements.slice(0, 1) });
    assert.equal(response.status, 400); assert.equal(response.data.detail, 'question_revision_not_approved');
  });
  let taxonomy, node, secondNode;
  await test('taxonomy_version_alias_and_assignment', async () => {
    taxonomy = ok(await api('/api/v1/taxonomies/versions', 'POST', { ...identity, taxonomyKey: 'test-only-label-contract',
      versionKey: 'e2e-1', subject: '数学', stage: '', schemaVersion: 1 }));
    node = ok(await api(`/api/v1/taxonomies/versions/${taxonomy.taxonomyVersionId}/nodes`, 'POST', { ...identity,
      knowledgeCode: 'TEST.A', displayName: '测试节点A（非教学结论）', parentNodeId: null, sortOrder: 0,
      metadata: { testOnly: true }, aliases: ['测试别名A'] }));
    secondNode = ok(await api(`/api/v1/taxonomies/versions/${taxonomy.taxonomyVersionId}/nodes`, 'POST', { ...identity,
      knowledgeCode: 'TEST.B', displayName: '测试节点B（非教学结论）', parentNodeId: null, sortOrder: 1,
      metadata: { testOnly: true }, aliases: [] }));
    ok(await api(`/api/v1/taxonomies/versions/${taxonomy.taxonomyVersionId}/activate`, 'POST', identity));
    const resolved = ok(await api(`/api/v1/taxonomies/versions/${taxonomy.taxonomyVersionId}/resolve?${query({ codeOrAlias: '测试别名A' })}`));
    assert.equal(resolved.taxonomyNodeId, node.taxonomyNodeId);
    const body = { ...identity, questionRevisionId: rows[0].question_revision_id, taxonomyNodeId: node.taxonomyNodeId,
      relationType: 'primary', assignmentSource: 'import', confidence: null };
    ok(await api('/api/v1/taxonomies/assignments', 'POST', body));
    ok(await api('/api/v1/taxonomies/assignments', 'POST', body));
    assert.equal(Number((await pool.query('select count(*) as n from teachbase_app.question_taxonomy_link')).rows[0].n), 1);
    return { semanticClassificationTested: false };
  });
  await test('active_taxonomy_is_immutable', async () => {
    const r = await api(`/api/v1/taxonomies/versions/${taxonomy.taxonomyVersionId}/nodes`, 'POST', { ...identity,
      knowledgeCode: 'TEST.B', displayName: '测试B', sortOrder: 1, metadata: {}, aliases: [] });
    assert.equal(r.status, 409);
  });
  await test('taxonomy_single_primary_per_dimension', async () => {
    const response = await api('/api/v1/taxonomies/assignments', 'POST', { ...identity,
      questionRevisionId: rows[0].question_revision_id, taxonomyNodeId: secondNode.taxonomyNodeId,
      relationType: 'primary', assignmentSource: 'import', confidence: null });
    assert.ok([200, 409].includes(response.status));
    const primaryCount = (await pool.query(`select count(*)::int as n from teachbase_app.question_taxonomy_link
      where question_revision_id=$1 and taxonomy_version_id=$2 and relation_type='primary'`,
      [rows[0].question_revision_id, taxonomy.taxonomyVersionId])).rows[0].n;
    // 只检查单主标签不变量，不擅自决定旧主标签应降级、删除还是拒绝替换。
    assert.ok(primaryCount <= 1, `primary_count=${primaryCount}; BLOCKS_TAG_SCHEMA_AND_SEARCH remains open`);
  });
  await test('review_hash_guard', async () => {
    const r = await api(`/api/v1/review-cases/${rows[0].review_case_id}/decisions`, 'POST', { ...identity,
      expectedContentHash: '0'.repeat(64), decision: 'approved', note: 'isolated test only', policyVersion: 'test-only',
      decisionSource: 'api', evidence: { testOnly: true }, evidenceOccurredAt: new Date().toISOString() });
    assert.ok(r.status >= 400); assert.equal((await pool.query('select count(*)::int as n from teachbase_app.review_decision')).rows[0].n, 0);
  });
  await test('test_only_approval_in_clone', async () => {
    for (const row of rows) ok(await api(`/api/v1/review-cases/${row.review_case_id}/decisions`, 'POST', { ...identity,
      expectedContentHash: row.content_hash, decision: 'approved', note: '副本功能测试，不代表人工教学审核',
      policyVersion: 'isolated-e2e-test-only', decisionSource: 'api', evidence: { testOnly: true, source: 'cloned-database' },
      evidenceOccurredAt: new Date().toISOString() }));
    const result = ok(await api(`/api/v1/questions/search?${query({ limit: '100' })}`));
    assert.equal(result.items.length, rows.length);
  });
  let collection, frozen;
  await test('basket_concurrency_checkpoint_restore_snapshot', async () => {
    collection = ok(await api('/api/v1/question-collections', 'POST', { ...identity, name: '真实样本副本功能测试' }), 201);
    const base = `/api/v1/question-collections/${collection.questionCollectionId}`;
    const items = rows.map(r => ({ questionRevisionId: r.question_revision_id, settings: { showAnswer: true, showAnalysis: true } }));
    const body = { ...identity, expectedDraftVersion: 0, checkpointKind: 'manual', items };
    const concurrent = await Promise.all([api(base + '/draft', 'PUT', body), api(base + '/draft', 'PUT', body)]);
    assert.deepEqual(concurrent.map(r => r.status).sort(), [200, 409]);
    const points = ok(await api(base + `/checkpoints?${query({})}`));
    ok(await api(base + '/draft', 'PUT', { ...body, expectedDraftVersion: 1, items: items.slice(0, 1) }));
    const restored = ok(await api(base + `/checkpoints/${points[0].questionCollectionCheckpointId}/restore`, 'POST', { ...identity, expectedDraftVersion: 2 }));
    assert.equal(restored.items.length, rows.length);
    frozen = ok(await api(base + '/snapshots', 'POST', { ...identity, expectedDraftVersion: 3 }), 201);
    assert.equal(frozen.frozenContent.items.length, rows.length);
  });
  let document, placed, snapshots = {};
  await test('place_all_real_questions', async () => {
    document = ok(await api('/api/v1/editor/documents', 'POST', { ...identity, documentKind: 'synchronized_handout',
      title: '真实题包副本端到端测试', schemaVersion: 1, masterDoc: { type: 'doc', content: [{ type: 'paragraph', content: [] }] },
      versionOverrides: [null, null, null] }), 201);
    placed = ok(await api(`/api/v1/editor/documents/${document.editorDocumentId}/question-references`, 'POST', {
      ...identity, expectedDraftVersion: 1, clientMutationId: 'e2e-all-questions', insertionIndex: 1,
      targetLayers: ['common'], questions: placements }));
    assert.equal(placed.draftVersion, 2);
    await fs.writeFile(path.join(output, 'placed.json'), JSON.stringify(placed, null, 2));
  });
  const nodes = () => placed.masterDoc.content.filter(n => n.type === 'questionReference');
  function projectedText(text, row) {
    // 数据库存原始 URI，引用快照固定为哈希 URI；只允许这项显式表示转换。
    for (const [id, file] of Object.entries(row.provenance_json.assetFiles || {})) {
      text = text.replaceAll(`![${id}](asset://${id})`, `![](tbasset:${file.sha256})`);
      text = text.replaceAll(`(asset://${id})`, `(tbasset:${file.sha256})`);
    }
    return text;
  }
  await test('all_option_markdown_preserved', async () => {
    for (const r of rows) {
      const ref = nodes().find(n => n.attrs.questionRevisionId === r.question_revision_id);
      for (const option of r.options_json) for (const audience of ['teacherMarkdown', 'studentMarkdown']) {
        assert.ok(ref.attrs[audience].includes(projectedText(option.markdown, r)), `${r.source_key}:missing_option:${option.label}`);
      }
    }
  });
  await test('all_composite_subquestions_preserved', async () => {
    for (const r of rows) {
      const ref = nodes().find(n => n.attrs.questionRevisionId === r.question_revision_id);
      for (const q of r.content_json.subquestions || []) for (const audience of ['teacherMarkdown', 'studentMarkdown']) {
        assert.ok(ref.attrs[audience].includes(projectedText(q.markdown, r)), `${r.source_key}:missing_subquestion:${q.label}`);
      }
    }
  });
  await test('teacher_student_answer_separation', async () => {
    for (const r of rows) {
      const ref = nodes().find(n => n.attrs.questionRevisionId === r.question_revision_id);
      assert.ok(ref.attrs.teacherMarkdown.includes(projectedText(r.analysis_markdown, r)));
      if (r.analysis_markdown.length > 40) assert.ok(!ref.attrs.studentMarkdown.includes(projectedText(r.analysis_markdown, r)));
    }
  });
  await test('freeze_teacher_and_student_snapshots', async () => {
    for (const audience of ['teacher', 'student']) {
      snapshots[audience] = ok(await api(`/api/v1/editor/documents/${document.editorDocumentId}/snapshots`, 'POST', {
        ...identity, expectedDraftVersion: 2, variantKey: 'common', audience, schemaVersion: 1 }), 201);
      await fs.writeFile(path.join(output, `${audience}-snapshot.json`), JSON.stringify(snapshots[audience], null, 2));
    }
  });
  await test('reference_usage_visible_after_freeze', async () => {
    const result = ok(await api(`/api/v1/questions/search?${query({ limit: '100' })}`));
    assert.ok(result.items.every(i => i.referenced));
  });
  await test('pending_correction_preserves_approved_pointer_and_snapshots', async () => {
    const r = rows[0];
    const correctedStem = r.stem_markdown + '\n副本测试修订标记';
    const result = ok(await api('/api/v1/questions/import-batch', 'POST', { ...identity, questions: [{
      externalKey: 'isolated-correction-test', sourceSystem: 'doc_math', sourceKey: r.source_key,
      reviewStatus: 'pending_review', subject: r.subject, stage: r.stage, grade: r.grade,
      questionType: r.question_type, title: r.title, lesson: r.lesson, primaryKnowledgeTag: r.primary_knowledge_tag,
      secondaryKnowledgeTags: r.secondary_knowledge_tags_json, difficultyStars: r.difficulty_stars,
      materialMarkdown: r.material_markdown, stemMarkdown: correctedStem, options: r.options_json,
      answerMarkdown: r.answer_markdown, analysisMarkdown: r.analysis_markdown,
      content: { ...r.content_json, stem_md: correctedStem }, provenance: { ...r.provenance_json, testOnly: true },
    }] }));
    assert.equal(result.results[0].revisionNo, 2);
    const current = (await pool.query('select approved_revision_id from teachbase_app.question where question_id=$1', [r.question_id])).rows[0];
    assert.equal(current.approved_revision_id, r.question_revision_id);
    const approved = ok(await api(`/api/v1/questions/search?${query({ limit: '100' })}`));
    assert.ok(approved.items.some(i => i.questionRevisionId === r.question_revision_id));
    const basket = (await pool.query('select frozen_content_json from teachbase_app.question_collection_snapshot where question_collection_snapshot_id=$1',
      [frozen.questionCollectionSnapshotId])).rows[0];
    assert.deepEqual(basket.frozen_content_json, frozen.frozenContent);
    for (const snapshot of Object.values(snapshots)) {
      const stored = (await pool.query('select frozen_content_json from teachbase_app.editor_snapshot where editor_snapshot_id=$1', [snapshot.editorSnapshotId])).rows[0];
      assert.deepEqual(stored.frozen_content_json, snapshot.frozenContent);
    }
  });
  const exports = [];
  for (const audience of ['teacher', 'student']) for (const format of ['docx', 'pdf']) {
    if (!rendererReady) { checks.push({ name: `export_${audience}_${format}`, status: 'blocked', error: 'renderer_tools_missing' }); continue; }
    await test(`export_${audience}_${format}`, async () => {
      const body = { ...identity, editorSnapshotId: snapshots[audience].editorSnapshotId, format,
        idempotencyKey: `real-${audience}-${format}`, retryOfExportRequestId: null };
      const r = ok(await api('/api/v1/exports', 'POST', body), 201);
      assert.equal(ok(await api('/api/v1/exports', 'POST', body)).exportRequestId, r.exportRequestId);
      let state;
      for (let n = 0; n < 300; n++) {
        state = (await pool.query('select * from teachbase_app.export_request where export_request_id=$1', [r.exportRequestId])).rows[0];
        if (['completed', 'failed_final'].includes(state.status)) break;
        await new Promise(resolve => setTimeout(resolve, 300));
      }
      exports.push({ audience, format, ...state });
      assert.equal(state.status, 'completed', JSON.stringify(state.error_json));
      return { exportRequestId: r.exportRequestId };
    });
  }
  await fs.writeFile(path.join(output, 'exports.json'), JSON.stringify(exports, null, 2));
  await test('export_file_images_formulas_and_circled_numbers', async () => {
    const result = await run(process.env.TEACHBASE_QA_PYTHON || 'python', [path.join(root, 'tools/verify_real_candidate_exports.py'), '--run-dir', output]);
    return JSON.parse(result.toString('utf8'));
  });
  await fs.writeFile(path.join(output, 'java.log'), Buffer.concat(logs));
  report.databaseCounts = (await pool.query(`select (select count(*) from teachbase_app.question) as questions,
    (select count(*) from teachbase_app.question_taxonomy_link) as tags,
    (select count(*) from teachbase_app.editor_question_reference) as references,
    (select count(*) from teachbase_app.review_decision) as test_decisions`)).rows[0];
} catch (e) { report.fatal = e.message; }
finally {
  if (pool) await pool.end();
  if (java && java.exitCode === null) { const exited = new Promise(r => java.once('exit', r)); java.kill(); await exited; }
  if (cluster) await cluster.stop();
  await test('original_candidates_and_review_state_unchanged', async () => assert.equal(await fingerprint(sourcePool), originalHash));
  await sourcePool.end();
  report.status = report.fatal || checks.some(c => c.status === 'failed') ? 'failed'
    : checks.some(c => c.status === 'blocked') ? 'blocked' : 'passed';
  report.finishedAt = new Date().toISOString();
  await fs.writeFile(path.join(output, 'report.json'), JSON.stringify(report, null, 2));
}
console.log(JSON.stringify({ status: report.status, fatal: report.fatal, checks: checks.length, output }));
if (report.status !== 'passed') process.exitCode = 1;
