/** 中文说明：真实候选的数据库读回与 HTTP 门禁验证；只允许专属本地验证库，不批准任何题目。 */
import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import assert from 'node:assert/strict';
import { Pool } from 'pg';

const args = process.argv.slice(2);
if (args.length !== 4 || args[0] !== '--data-root' || args[2] !== '--receipt-dir') {
  throw new Error('required: --data-root PATH --receipt-dir PATH');
}
const dataRoot = path.resolve(args[1]);
const receiptDir = path.resolve(args[3]);
const config = JSON.parse(await fs.readFile(path.join(dataRoot, 'local.private.json'), 'utf8'));
assert.equal(config.database, 'teachbase_candidates');
const runtime = JSON.parse(await fs.readFile(path.join(dataRoot, 'runtime.json'), 'utf8'));
const request = JSON.parse(await fs.readFile(path.join(receiptDir, 'candidate_request.json'), 'utf8'));
const receipt = JSON.parse(await fs.readFile(path.join(receiptDir, 'candidate_receipt.json'), 'utf8'));
assert.equal(request.workspaceId, config.workspaceId);
const pool = new Pool({ host: '127.0.0.1', port: config.port, user: config.user,
  password: config.password, database: config.database });
const checks = [];
async function check(name, action) { await action(); checks.push({ name, passed: true }); }
async function post(body) {
  const response = await fetch(`${runtime.baseUrl}/api/v1/ingestion/candidate-batches`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    signal: AbortSignal.timeout(120000) });
  return { status: response.status, body: await response.json() };
}
const tables = ['question', 'question_revision', 'question_import_observation', 'source_document',
  'source_region', 'question_source_link', 'review_case'];
async function counts() {
  const result = {};
  for (const table of tables) result[table] = Number((await pool.query(
    `select count(*) as n from teachbase_app.${table}`)).rows[0].n);
  return result;
}
try {
  const expectedIds = receipt.results.map(r => r.question.questionRevisionId);
  await check('full_packet_and_latex_roundtrip', async () => {
    const rows = (await pool.query(`select q.source_key, r.* from teachbase_app.question q
      join teachbase_app.question_revision r using (question_id) where q.workspace_id=$1`,
      [request.workspaceId])).rows;
    assert.equal(rows.length, request.questions.length);
    for (const input of request.questions) {
      const row = rows.find(r => r.source_key === input.sourceKey);
      assert.ok(row);
      assert.deepEqual(row.content_json, input.content);
      assert.deepEqual(row.provenance_json, input.provenance);
      assert.deepEqual(row.options_json, input.options);
      assert.equal(row.stem_markdown, input.stemMarkdown.trim());
      assert.equal(row.answer_markdown, input.answerMarkdown.trim());
      assert.equal(row.analysis_markdown, input.analysisMarkdown.trim());
      assert.equal(row.source_payload_hash, input.sourcePayloadHash);
      assert.equal(row.review_status, 'pending_review');
      assert.equal(Number(row.revision_no), 1);
    }
  });
  await check('source_and_review_links_complete', async () => {
    const rows = (await pool.query(`select q.question_id, q.approved_revision_id, l.source_document_id,
      s.file_version_id, l.source_region_id, c.expected_content_hash, r.content_hash, c.status
      from teachbase_app.question q join teachbase_app.question_revision r using(question_id)
      join teachbase_app.question_source_link l using(question_revision_id)
      join teachbase_app.source_document s using(source_document_id)
      join teachbase_app.review_case c on c.question_revision_id=r.question_revision_id
      where q.workspace_id=$1`, [request.workspaceId])).rows;
    assert.equal(rows.length, request.questions.length);
    for (const row of rows) {
      assert.equal(row.approved_revision_id, null);
      assert.equal(row.source_document_id, receipt.sourceDocumentId);
      assert.equal(row.file_version_id, request.sourceFileVersionId);
      assert.ok(row.source_region_id);
      assert.equal(row.status, 'open');
      assert.equal(row.expected_content_hash, row.content_hash);
    }
  });
  await check('registered_file_bytes_and_hashes', async () => {
    const rows = (await pool.query('select storage_key, size_bytes, sha256 from teachbase_app.file_version where workspace_id=$1',
      [request.workspaceId])).rows;
    assert.ok(rows.length > 1);
    for (const row of rows) {
      const storage = path.resolve(dataRoot, 'storage');
      const file = path.resolve(storage, row.storage_key);
      assert.ok(file.startsWith(storage + path.sep));
      const bytes = await fs.readFile(file);
      assert.equal(bytes.length, Number(row.size_bytes));
      assert.equal(crypto.createHash('sha256').update(bytes).digest('hex'), row.sha256);
    }
  });
  const baseline = await counts();
  await check('identical_replay_and_concurrent_replay', async () => {
    for (const response of [await post(request), ...await Promise.all([post(request), post(request)])]) {
      assert.equal(response.status, 200, JSON.stringify(response.body));
      assert.deepEqual(response.body.results.map(r => r.question.questionRevisionId), expectedIds);
      assert.deepEqual(response.body.results.map(r => r.reviewCase.reviewCaseId), receipt.results.map(r => r.reviewCase.reviewCaseId));
      assert.ok(response.body.results.every(r => !r.question.createdQuestion && !r.question.createdRevision));
    }
    assert.deepEqual(await counts(), baseline);
  });
  const newRequest = () => {
    const body = structuredClone(request);
    body.questions = body.questions.slice(0, 2).map((q, i) => ({ ...q,
      sourceKey: `${request.sourceSha256}/verification-${crypto.randomUUID()}/${i}`,
      externalKey: `verification-${crypto.randomUUID()}` }));
    return body;
  };
  await check('invalid_second_item_rolls_back_first', async () => {
    const body = newRequest();
    body.questions[1].contentHash = '0'.repeat(64);
    const response = await post(body);
    assert.equal(response.status, 400);
    assert.equal(response.body.detail, 'question_content_hash_mismatch');
    assert.deepEqual(await counts(), baseline);
  });
  await check('missing_source_file_rolls_back_questions', async () => {
    const body = newRequest(); body.sourceFileVersionId = crypto.randomUUID();
    const response = await post(body);
    assert.equal(response.status, 400);
    assert.equal(response.body.detail, 'candidate_source_file_mismatch');
    assert.deepEqual(await counts(), baseline);
  });
  await check('source_hash_bound_to_file_version', async () => {
    const body = newRequest(); body.sourceSha256 = '0'.repeat(64);
    for (const q of body.questions) q.sourceKey = `${body.sourceSha256}/${crypto.randomUUID()}`;
    const response = await post(body);
    assert.equal(response.status, 400);
    assert.equal(response.body.detail, 'candidate_source_file_mismatch');
    assert.deepEqual(await counts(), baseline);
  });
  await check('approved_import_rejected', async () => {
    const body = newRequest(); body.questions[1].reviewStatus = 'approved';
    const response = await post(body);
    assert.equal(response.status, 400);
    assert.equal(response.body.detail, 'question_review_status_invalid');
    assert.deepEqual(await counts(), baseline);
  });
  await check('nonmember_import_rejected', async () => {
    const body = newRequest(); body.actorUserId = crypto.randomUUID();
    const response = await post(body);
    assert.equal(response.status, 403);
    assert.deepEqual(await counts(), baseline);
  });
  await check('duplicate_source_identity_rejected', async () => {
    const body = newRequest(); body.questions[1] = body.questions[0];
    const response = await post(body);
    assert.equal(response.status, 400);
    assert.equal(response.body.detail, 'candidate_source_identity_invalid');
    assert.deepEqual(await counts(), baseline);
  });
  await check('pending_search_pagination_and_approved_exclusion', async () => {
    const ids = []; let cursor = '';
    do {
      const params = new URLSearchParams({ workspaceId: request.workspaceId, actorUserId: request.actorUserId,
        reviewStatus: 'pending_review', limit: '17', cursor });
      const response = await fetch(`${runtime.baseUrl}/api/v1/questions/search?${params}`);
      assert.equal(response.status, 200);
      const page = await response.json();
      ids.push(...page.items.map(i => i.questionRevisionId));
      assert.ok(page.items.every(i => !i.humanReviewed));
      cursor = page.nextCursor || '';
    } while (cursor);
    assert.deepEqual([...ids].sort(), [...expectedIds].sort());
    const params = new URLSearchParams({ workspaceId: request.workspaceId, actorUserId: request.actorUserId });
    const response = await fetch(`${runtime.baseUrl}/api/v1/questions/search?${params}`);
    assert.equal(response.status, 200);
    assert.equal((await response.json()).items.length, 0);
  });
  const report = { status: 'passed', checkedAt: new Date().toISOString(), database: config.database,
    javaPid: runtime.javaPid, runtimeStartedAt: runtime.startedAt, counts: await counts(), checks,
    limitation: 'Local candidate persistence; no human approval, production publication or renderer acceptance.' };
  await fs.writeFile(path.join(receiptDir, `verification-${runtime.javaPid}.json`), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report));
} finally { await pool.end(); }
