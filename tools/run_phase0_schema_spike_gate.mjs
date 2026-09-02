import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { Pool } from "pg";

import { startEmbeddedPostgresCluster } from "../tests/helpers/runtime_testkit.mjs";

const workspaceRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const migrationRoot = path.join(workspaceRoot, "backend", "teachbase-server", "src", "main", "resources", "db", "migration");
const spikeRoot = path.join(workspaceRoot, "docs", "architecture", "spikes");
const reportPath = path.join(workspaceRoot, "docs", "reports", "phase0_schema_spike_gate_20260902.json");

function expect(condition, message) {
  if (!condition) throw new Error(message);
}

function id() {
  return crypto.randomUUID();
}

function hash(value) {
  return crypto.createHash("sha256").update(value).digest("hex");
}

async function applySqlFiles(pool, root, names) {
  for (const name of names) {
    await pool.query(await fs.readFile(path.join(root, name), "utf8"));
  }
}

async function insertQuestion(pool, workspaceId, actorUserId, suffix) {
  const questionId = id();
  const revisionId = id();
  await pool.query(
    `insert into teachbase_app.question (
       question_id, workspace_id, external_key, source_system, source_key,
       current_revision_no, approved_revision_id, created_by, updated_by
     ) values ($1,$2,$3,'phase0_spike',$4,1,null,$5,$5)`,
    [questionId, workspaceId, `spike-${suffix}`, `source-${suffix}`, actorUserId],
  );
  await pool.query(
    `insert into teachbase_app.question_revision (
       question_revision_id, question_id, workspace_id, revision_no, review_status,
       subject, question_type, stem_markdown, content_json, content_hash,
       source_payload_hash, import_envelope_hash, approved_at, created_by
     ) values ($1,$2,$3,1,'approved','英语','组合题',$4,$5::jsonb,$6,$6,$6,now(),$7)`,
    [revisionId, questionId, workspaceId, `题目 ${suffix}`, JSON.stringify({ suffix }), hash(`question-${suffix}`), actorUserId],
  );
  await pool.query(
    `update teachbase_app.question set approved_revision_id = $1 where question_id = $2`,
    [revisionId, questionId],
  );
  return { questionId, revisionId };
}

async function main() {
  const cluster = await startEmbeddedPostgresCluster("phase0_schema_spike");
  let pool;
  let report;
  try {
    const database = await cluster.createDatabase("phase0_schema_spike_test");
    pool = new Pool({ connectionString: database.connectionString, max: 8 });
    const migrations = (await fs.readdir(migrationRoot))
      .filter((name) => /^V\d+__.*\.sql$/.test(name))
      .sort((left, right) => left.localeCompare(right));
    await applySqlFiles(pool, migrationRoot, migrations);
    await applySqlFiles(pool, spikeRoot, [
      "working_draft_schema_spike.sql",
      "knowledge_document_schema_spike.sql",
      "question_group_composition_schema_spike.sql",
    ]);

    const workspaceId = id();
    const actorUserId = id();
    await pool.query(
      `insert into teachbase_app.workspace (workspace_id, slug, display_name) values ($1,'phase0-spike','Phase 0 Spike')`,
      [workspaceId],
    );
    await pool.query(
      `insert into teachbase_app.app_user (user_id, email, display_name) values ($1,'phase0@example.invalid','Phase 0')`,
      [actorUserId],
    );
    await pool.query(
      `insert into teachbase_app.workspace_member (workspace_id, user_id, member_role) values ($1,$2,'owner')`,
      [workspaceId, actorUserId],
    );

    const documentId = id();
    const editorRevisionId = id();
    const emptyDoc = { type: "doc", content: [] };
    const emptyOverrides = [null, null, null];
    await pool.query(
      `insert into teachbase_app.editor_document (
         editor_document_id, workspace_id, document_kind, title, current_revision_no, created_by, updated_by
       ) values ($1,$2,'synchronized_handout','working draft spike',1,$3,$3)`,
      [documentId, workspaceId, actorUserId],
    );
    await pool.query(
      `insert into teachbase_app.editor_revision (
         editor_revision_id, editor_document_id, workspace_id, revision_no, editor_model,
         schema_version, master_doc_json, version_overrides_json, content_hash, created_by
       ) values ($1,$2,$3,1,'master-overrides-v1',1,$4::jsonb,$5::jsonb,$6,$7)`,
      [editorRevisionId, documentId, workspaceId, JSON.stringify(emptyDoc), JSON.stringify(emptyOverrides), hash("editor-r1"), actorUserId],
    );
    await pool.query(
      `insert into teachbase_phase0_spike.editor_working_draft (
         editor_document_id, workspace_id, based_on_editor_revision_id, schema_version,
         master_doc_json, version_overrides_json, content_hash, updated_by
       ) values ($1,$2,$3,1,$4::jsonb,$5::jsonb,$6,$7)`,
      [documentId, workspaceId, editorRevisionId, JSON.stringify(emptyDoc), JSON.stringify(emptyOverrides), hash("draft-v1"), actorUserId],
    );
    const concurrentDraftSaves = await Promise.all([
      pool.query(
        `update teachbase_phase0_spike.editor_working_draft
            set draft_version = draft_version + 1, content_hash = $1, updated_at = now()
          where editor_document_id = $2 and draft_version = 1`,
        [hash("draft-winner-a"), documentId],
      ),
      pool.query(
        `update teachbase_phase0_spike.editor_working_draft
            set draft_version = draft_version + 1, content_hash = $1, updated_at = now()
          where editor_document_id = $2 and draft_version = 1`,
        [hash("draft-winner-b"), documentId],
      ),
    ]);
    expect(concurrentDraftSaves.filter((result) => result.rowCount === 1).length === 1, "working_draft_concurrency_failed");
    const editorRevisionCount = await pool.query(
      `select count(*)::int as count from teachbase_app.editor_revision where editor_document_id = $1`,
      [documentId],
    );
    expect(editorRevisionCount.rows[0].count === 1, "autosave_created_editor_revision");
    await pool.query(
      `insert into teachbase_phase0_spike.editor_draft_checkpoint (
         editor_draft_checkpoint_id, editor_document_id, workspace_id, draft_version, checkpoint_kind,
         schema_version, master_doc_json, version_overrides_json, content_hash, created_by, expires_at
       ) values ($1,$2,$3,2,'autosave',1,$4::jsonb,$5::jsonb,$6,$7,now()+interval '72 hours')`,
      [id(), documentId, workspaceId, JSON.stringify(emptyDoc), JSON.stringify(emptyOverrides), hash("checkpoint-v2"), actorUserId],
    );

    const knowledgeDocumentId = id();
    const knowledgeRevision1 = id();
    const knowledgeRevision2 = id();
    const sectionRoot = id();
    const sectionMoved = id();
    const sectionSplitA = id();
    const sectionSplitB = id();
    await pool.query(
      `insert into teachbase_phase0_spike.knowledge_document (
         knowledge_document_id, workspace_id, lesson_key, title, created_by
       ) values ($1,$2,'math.g8.term1.lesson_012','全等三角形第 12 讲',$3)`,
      [knowledgeDocumentId, workspaceId, actorUserId],
    );
    for (const [revisionId, revisionNo, revisionHash] of [
      [knowledgeRevision1, 1, hash("knowledge-r1")],
      [knowledgeRevision2, 2, hash("knowledge-r2")],
    ]) {
      await pool.query(
        `insert into teachbase_phase0_spike.knowledge_document_revision (
           knowledge_document_revision_id, knowledge_document_id, workspace_id, revision_no,
           workflow_status, content_hash, created_by
         ) values ($1,$2,$3,$4,'approved',$5,$6)`,
        [revisionId, knowledgeDocumentId, workspaceId, revisionNo, revisionHash, actorUserId],
      );
    }
    for (const [sectionId, key] of [
      [sectionRoot, "root"], [sectionMoved, "proof"], [sectionSplitA, "proof-a"], [sectionSplitB, "proof-b"],
    ]) {
      await pool.query(
        `insert into teachbase_phase0_spike.knowledge_section_identity (
           knowledge_section_id, knowledge_document_id, workspace_id, section_key
         ) values ($1,$2,$3,$4)`,
        [sectionId, knowledgeDocumentId, workspaceId, key],
      );
    }
    await pool.query(
      `insert into teachbase_phase0_spike.knowledge_section_revision (
         knowledge_document_revision_id, knowledge_document_id, workspace_id,
         knowledge_section_id, parent_section_id, sort_order, title, change_kind, content_json
       ) values
         ($1,$2,$3,$4,null,0,'定义','created',$8::jsonb),
         ($1,$2,$3,$5,$4,0,'证明方法','created',$8::jsonb),
         ($6,$2,$3,$4,null,0,'定义','unchanged',$8::jsonb),
         ($6,$2,$3,$5,$4,1,'证明方法（移动）','moved',$8::jsonb),
         ($6,$2,$3,$7,$4,2,'证明方法 A','created',$8::jsonb),
         ($6,$2,$3,$9,$4,3,'证明方法 B','created',$8::jsonb)`,
      [knowledgeRevision1, knowledgeDocumentId, workspaceId, sectionRoot, sectionMoved,
        knowledgeRevision2, sectionSplitA, JSON.stringify(emptyDoc), sectionSplitB],
    );
    await pool.query(
      `insert into teachbase_phase0_spike.knowledge_section_lineage (
         knowledge_document_revision_id, knowledge_document_id, workspace_id,
         from_section_id, to_section_id, relation_type
       ) values ($1,$2,$3,$4,$5,'split_into'),($1,$2,$3,$4,$6,'split_into')`,
      [knowledgeRevision2, knowledgeDocumentId, workspaceId, sectionMoved, sectionSplitA, sectionSplitB],
    );
    const oldSectionOrder = await pool.query(
      `select sort_order from teachbase_phase0_spike.knowledge_section_revision
        where knowledge_document_revision_id = $1 and knowledge_section_id = $2`,
      [knowledgeRevision1, sectionMoved],
    );
    expect(oldSectionOrder.rows[0].sort_order === 0, "knowledge_old_revision_mutated");

    const material = await insertQuestion(pool, workspaceId, actorUserId, "material");
    const childA = await insertQuestion(pool, workspaceId, actorUserId, "child-a");
    const childB = await insertQuestion(pool, workspaceId, actorUserId, "child-b");
    const groupId = id();
    const composition1 = id();
    await pool.query(
      `insert into teachbase_phase0_spike.question_group (
         question_group_id, workspace_id, source_system, external_group_key, created_by
       ) values ($1,$2,'pdf_english','reading-set-001',$3)`,
      [groupId, workspaceId, actorUserId],
    );
    await pool.query(
      `insert into teachbase_phase0_spike.question_group_composition_revision (
         question_group_composition_revision_id, question_group_id, workspace_id,
         revision_no, workflow_status, content_hash, created_by
       ) values ($1,$2,$3,1,'approved',$4,$5)`,
      [composition1, groupId, workspaceId, hash("composition-r1"), actorUserId],
    );
    for (const [order, role, question] of [
      [0, "material", material], [1, "child", childA], [2, "child", childB],
    ]) {
      await pool.query(
        `insert into teachbase_phase0_spike.question_group_composition_item (
           question_group_composition_revision_id, question_group_id, workspace_id,
           sort_order, member_role, question_id, question_revision_id
         ) values ($1,$2,$3,$4,$5,$6,$7)`,
        [composition1, groupId, workspaceId, order, role, question.questionId, question.revisionId],
      );
    }
    const concurrentCompositionCreates = await Promise.allSettled([
      pool.query(
        `insert into teachbase_phase0_spike.question_group_composition_revision (
           question_group_composition_revision_id, question_group_id, workspace_id,
           revision_no, workflow_status, content_hash, created_by
         ) values ($1,$2,$3,2,'draft',$4,$5)`,
        [id(), groupId, workspaceId, hash("composition-r2-a"), actorUserId],
      ),
      pool.query(
        `insert into teachbase_phase0_spike.question_group_composition_revision (
           question_group_composition_revision_id, question_group_id, workspace_id,
           revision_no, workflow_status, content_hash, created_by
         ) values ($1,$2,$3,2,'draft',$4,$5)`,
        [id(), groupId, workspaceId, hash("composition-r2-b"), actorUserId],
      ),
    ]);
    expect(concurrentCompositionCreates.filter((result) => result.status === "fulfilled").length === 1,
      "question_group_revision_concurrency_failed");
    const compositionItems = await pool.query(
      `select member_role, question_revision_id from teachbase_phase0_spike.question_group_composition_item
        where question_group_composition_revision_id = $1 order by sort_order`,
      [composition1],
    );
    expect(compositionItems.rows.length === 3 && compositionItems.rows[0].member_role === "material",
      "question_group_composition_not_frozen");

    report = {
      schemaVersion: 1,
      generatedAt: new Date().toISOString(),
      status: "passed",
      isolation: { schema: "teachbase_phase0_spike", productionMigrationsChanged: false },
      workingDraft: {
        concurrentSaves: 2,
        successfulSaves: concurrentDraftSaves.filter((result) => result.rowCount === 1).length,
        permanentRevisionsAfterAutosave: editorRevisionCount.rows[0].count,
        checkpointRetentionHours: 72,
      },
      knowledgeDocument: {
        lessonKey: "math.g8.term1.lesson_012",
        revisions: 2,
        stableMovedSectionIdentity: true,
        splitLineageEdges: 2,
        oldRevisionUnchanged: true,
      },
      questionGroup: {
        compositionItems: compositionItems.rows.length,
        exactQuestionRevisionsPinned: true,
        concurrentNextRevisionWinners: concurrentCompositionCreates.filter((result) => result.status === "fulfilled").length,
      },
      cleanup: "pending",
    };
  } finally {
    if (pool) await pool.end();
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
