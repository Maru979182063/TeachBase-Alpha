import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { Pool } from "pg";

import {
  fetchJson,
  reservePort,
  startEmbeddedPostgresCluster,
} from "../tests/helpers/runtime_testkit.mjs";

const __filename = fileURLToPath(import.meta.url);
const workspaceRoot = path.resolve(path.dirname(__filename), "..");
const serverRoot = path.join(workspaceRoot, "backend", "teachbase-server");
const jarPath = path.join(serverRoot, "target", "teachbase-server-0.1.0-SNAPSHOT.jar");
const reportPath = path.join(
  workspaceRoot,
  "docs",
  "reports",
  "question_collection_live_gate_20260831.json",
);

function expect(condition, message) {
  if (!condition) throw new Error(message);
}

async function waitForHealth(baseUrl, child, logs, timeoutMs = 45_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) {
      throw new Error(`java_server_exited:${child.exitCode}\n${logs.stderr.join("")}`);
    }
    try {
      const response = await fetchJson(`${baseUrl}/actuator/health`);
      if (response.ok && response.data?.status === "UP") return;
    } catch {
      // Flyway and the web server may still be starting.
    }
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  throw new Error(`java_server_health_timeout\n${logs.stderr.join("")}`);
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

function questionPacket(index, overrides = {}) {
  const chains = ["doc_math", "doc_english", "pdf_math", "pdf_english"];
  const chain = chains[index % chains.length];
  const math = chain.endsWith("math");
  return {
    externalKey: `gate-question-${index}`,
    sourceSystem: chain,
    sourceKey: `${chain}/fixture-${index}`,
    reviewStatus: "pending_review",
    subject: math ? "数学" : "英语",
    stage: "初中",
    grade: `${7 + (index % 3)}年级`,
    questionType: math ? "解答题" : "阅读理解",
    title: math ? `三角形全等训练 ${index}` : `Reading comprehension ${index}`,
    lesson: math ? "全等三角形" : "Reading",
    primaryKnowledgeTag: math ? "三角形全等" : "信息定位",
    secondaryKnowledgeTags: math ? ["角平分线", "证明"] : ["上下文", "推断"],
    difficultyStars: 1 + (index % 5),
    materialMarkdown: math ? "如图，在 $\\triangle ABC$ 中。" : "Read the passage and answer the question.",
    stemMarkdown: math
      ? `证明第 ${index} 题中的两个三角形全等。`
      : `What can be inferred from paragraph ${1 + (index % 3)}?`,
    options: math ? [] : ["A. First", "B. Second", "C. Third", "D. Fourth"],
    answerMarkdown: math ? "由 SAS 可证。" : "B",
    analysisMarkdown: math ? "先找公共边，再验证对应角相等。" : "Locate the supporting sentence.",
    content: { schemaVersion: 1, chain, blocks: [{ type: "stem", order: 0 }] },
    provenance: { sourceLabel: `${chain} gate fixture`, pipeline: chain, inputContract: "generated-live-gate" },
    ...overrides,
  };
}

function editorDoc() {
  return {
    type: "doc",
    content: [{ type: "heading", attrs: { level: 2 }, content: [{ type: "text", text: "课前练习" }] }],
  };
}

async function approveImportedQuestions(baseUrl, workspaceId, actorUserId, results) {
  // Use bounded parallelism so this large search fixture exercises the real review
  // contract without turning the gate into an HTTP connection-pool benchmark.
  for (let offset = 0; offset < results.length; offset += 20) {
    const batch = results.slice(offset, offset + 20);
    await Promise.all(batch.map(async (item) => {
      const opened = await fetchJson(`${baseUrl}/api/v1/review-cases`, {
        method: "POST",
        body: { workspaceId, actorUserId, questionRevisionId: item.questionRevisionId },
      });
      expect(opened.status === 200, `review_open_status:${opened.status}:${JSON.stringify(opened.data)}`);
      const decided = await fetchJson(
        `${baseUrl}/api/v1/review-cases/${opened.data.reviewCaseId}/decisions`,
        {
          method: "POST",
          body: {
            workspaceId,
            actorUserId,
            expectedContentHash: opened.data.expectedContentHash,
            decision: "approved",
            note: "question collection live gate",
            policyVersion: "question-collection-gate-v1",
            decisionSource: "api",
            evidence: { gate: "question-collection-live" },
            evidenceOccurredAt: new Date().toISOString(),
          },
        },
      );
      expect(decided.status === 200, `review_decide_status:${decided.status}:${JSON.stringify(decided.data)}`);
    }));
  }
}

async function main() {
  await fs.access(jarPath);
  const cluster = await startEmbeddedPostgresCluster("question_collection_live_gate");
  let child;
  let pool;
  let report;
  try {
    const database = await cluster.createDatabase("question_collection_test");
    const databaseUrl = new URL(database.connectionString);
    const port = await reservePort();
    const baseUrl = `http://127.0.0.1:${port}`;
    const logs = { stdout: [], stderr: [] };
    child = spawn("java", ["-jar", jarPath], {
      cwd: serverRoot,
      env: {
        ...process.env,
        TEACHBASE_DATABASE_URL: `jdbc:postgresql://127.0.0.1:${cluster.port}/${database.database}`,
        TEACHBASE_DATABASE_USER: decodeURIComponent(databaseUrl.username),
        TEACHBASE_DATABASE_PASSWORD: decodeURIComponent(databaseUrl.password),
        TEACHBASE_DATABASE_POOL_SIZE: "16",
        TEACHBASE_SERVER_PORT: String(port),
        TEACHBASE_RENDERING_ENABLED: "false",
      },
      stdio: ["ignore", "pipe", "pipe"],
    });
    child.stdout.on("data", (chunk) => logs.stdout.push(String(chunk)));
    child.stderr.on("data", (chunk) => logs.stderr.push(String(chunk)));
    await waitForHealth(baseUrl, child, logs);

    pool = new Pool({ connectionString: database.connectionString });
    const workspaceId = crypto.randomUUID();
    const actorUserId = crypto.randomUUID();
    await pool.query(
      `insert into teachbase_app.workspace (workspace_id, slug, display_name) values ($1, $2, $3)`,
      [workspaceId, "question-live-gate", "Question Live Gate"],
    );
    await pool.query(
      `insert into teachbase_app.app_user (user_id, email, display_name) values ($1, $2, $3)`,
      [actorUserId, "question-live-gate@example.invalid", "Question Gate Actor"],
    );
    await pool.query(
      `insert into teachbase_app.workspace_member (workspace_id, user_id, member_role) values ($1, $2, 'owner')`,
      [workspaceId, actorUserId],
    );

    const packets = Array.from({ length: 240 }, (_, index) => questionPacket(index));
    const imported = await fetchJson(`${baseUrl}/api/v1/questions/import-batch`, {
      method: "POST",
      body: { workspaceId, actorUserId, questions: packets },
    });
    expect(imported.status === 200, `question_import_status:${imported.status}:${JSON.stringify(imported.data)}`);
    expect(imported.data?.results?.length === packets.length, "question_import_result_count");
    expect(imported.data.results.every((item) => item.createdQuestion && item.createdRevision), "initial_import_not_created");
    await approveImportedQuestions(baseUrl, workspaceId, actorUserId, imported.data.results);

    const repeated = await fetchJson(`${baseUrl}/api/v1/questions/import-batch`, {
      method: "POST",
      body: { workspaceId, actorUserId, questions: [packets[0]] },
    });
    expect(repeated.status === 200, `question_reimport_status:${repeated.status}`);
    expect(repeated.data.results[0].createdRevision === false, "question_reimport_not_idempotent");
    const firstRevisionId = imported.data.results[0].questionRevisionId;

    const searchStarted = performance.now();
    const search = await fetchJson(
      `${baseUrl}/api/v1/questions/search?workspaceId=${workspaceId}&actorUserId=${actorUserId}`
        + `&query=${encodeURIComponent("三角形全等")}&subject=${encodeURIComponent("数学")}&limit=40`,
    );
    const searchMs = Math.round((performance.now() - searchStarted) * 100) / 100;
    expect(search.status === 200, `question_search_status:${search.status}:${JSON.stringify(search.data)}`);
    expect(search.data.items.length > 0, "question_search_empty");
    expect(search.data.items.every((item) => item.subject === "数学" && item.humanReviewed), "question_search_filter_failed");
    expect(search.data.nextCursor, "question_search_next_cursor_missing");
    const secondPage = await fetchJson(
      `${baseUrl}/api/v1/questions/search?workspaceId=${workspaceId}&actorUserId=${actorUserId}`
        + `&query=${encodeURIComponent("三角形全等")}&subject=${encodeURIComponent("数学")}`
        + `&limit=40&cursor=${encodeURIComponent(search.data.nextCursor)}`,
    );
    expect(secondPage.status === 200 && secondPage.data.items.length > 0, "question_search_second_page_missing");
    const firstPageIds = new Set(search.data.items.map((item) => item.questionId));
    expect(secondPage.data.items.every((item) => !firstPageIds.has(item.questionId)), "question_search_page_overlap");

    await pool.query("set enable_seqscan = off");
    const explain = await pool.query(
      `explain (format json)
       select question_revision_id
         from teachbase_app.question_revision
        where lower(
          coalesce(title, '') || ' ' || coalesce(subject, '') || ' ' || coalesce(stage, '') || ' '
          || coalesce(grade, '') || ' ' || coalesce(question_type, '') || ' ' || coalesce(lesson, '') || ' '
          || coalesce(primary_knowledge_tag, '') || ' ' || coalesce(material_markdown, '') || ' '
          || coalesce(stem_markdown, '') || ' ' || coalesce(answer_markdown, '') || ' ' || coalesce(analysis_markdown, '')
        ) like '%三角形全等%'`,
    );
    const explainText = JSON.stringify(explain.rows[0]["QUERY PLAN"]);
    expect(explainText.includes("idx_question_revision_search_trgm"), "trigram_index_not_used");

    const collectionCreated = await fetchJson(`${baseUrl}/api/v1/question-collections`, {
      method: "POST",
      body: { workspaceId, actorUserId, name: "并发与快照验收题篮" },
    });
    expect(collectionCreated.status === 201, `collection_create_status:${collectionCreated.status}`);
    const collectionId = collectionCreated.data.questionCollectionId;
    const draftPayload = {
      workspaceId,
      actorUserId,
      expectedDraftVersion: 0,
      checkpointKind: "autosave",
      items: imported.data.results.slice(0, 4).map((item) => ({
        questionRevisionId: item.questionRevisionId,
        settings: { displayMode: "full", showAnswer: true, showAnalysis: true },
      })),
    };
    const concurrentSaves = await Promise.all([
      fetchJson(`${baseUrl}/api/v1/question-collections/${collectionId}/draft`, { method: "PUT", body: draftPayload }),
      fetchJson(`${baseUrl}/api/v1/question-collections/${collectionId}/draft`, { method: "PUT", body: draftPayload }),
    ]);
    expect(concurrentSaves.filter((item) => item.status === 200).length === 1, "collection_concurrent_winner_count");
    expect(concurrentSaves.filter((item) => item.status === 409).length === 1, "collection_concurrent_conflict_count");
    const savedDraft = concurrentSaves.find((item) => item.status === 200).data;
    expect(savedDraft.draftVersion === 1 && savedDraft.items.length === 4, "collection_draft_invalid");

    const snapshot = await fetchJson(`${baseUrl}/api/v1/question-collections/${collectionId}/snapshots`, {
      method: "POST",
      body: { workspaceId, actorUserId, expectedDraftVersion: 1 },
    });
    expect(snapshot.status === 201, `collection_snapshot_status:${snapshot.status}:${JSON.stringify(snapshot.data)}`);
    expect(snapshot.data.frozenContent.items.length === 4, "collection_snapshot_item_count");
    const frozenStem = snapshot.data.frozenContent.items[0].question.stemMarkdown;

    const checkpoints = await fetchJson(
      `${baseUrl}/api/v1/question-collections/${collectionId}/checkpoints`
        + `?workspaceId=${workspaceId}&actorUserId=${actorUserId}`,
    );
    expect(checkpoints.status === 200 && checkpoints.data.length === 1, "collection_checkpoint_list_invalid");
    const checkpointId = checkpoints.data[0].questionCollectionCheckpointId;
    const manualSave = await fetchJson(`${baseUrl}/api/v1/question-collections/${collectionId}/draft`, {
      method: "PUT",
      body: {
        ...draftPayload,
        expectedDraftVersion: 1,
        checkpointKind: "manual",
        items: draftPayload.items.slice(0, 2),
      },
    });
    expect(manualSave.status === 200 && manualSave.data.draftVersion === 2, "collection_manual_checkpoint_failed");
    const restored = await fetchJson(
      `${baseUrl}/api/v1/question-collections/${collectionId}/checkpoints/${checkpointId}/restore`,
      {
        method: "POST",
        body: { workspaceId, actorUserId, expectedDraftVersion: 2 },
      },
    );
    expect(restored.status === 200 && restored.data.draftVersion === 3, "collection_checkpoint_restore_failed");
    expect(restored.data.items.length === 4, "collection_checkpoint_restore_content_changed");

    const corrected = questionPacket(0, {
      reviewStatus: "pending_review",
      stemMarkdown: "这是尚未人工批准的新修订，不得改变既有快照。",
    });
    const correctionImport = await fetchJson(`${baseUrl}/api/v1/questions/import-batch`, {
      method: "POST",
      body: { workspaceId, actorUserId, questions: [corrected] },
    });
    expect(correctionImport.status === 200 && correctionImport.data.results[0].revisionNo === 2, "correction_revision_missing");
    const reviewQueue = await fetchJson(
      `${baseUrl}/api/v1/questions/search?workspaceId=${workspaceId}&actorUserId=${actorUserId}`
        + `&reviewStatus=pending_review&query=${encodeURIComponent("尚未人工批准")}&limit=10`,
    );
    expect(reviewQueue.status === 200 && reviewQueue.data.items.length === 1, "pending_review_queue_missing");
    expect(reviewQueue.data.items[0].humanReviewed === false, "pending_review_marker_incorrect");
    const persistedSnapshot = await pool.query(
      `select frozen_content_json from teachbase_app.question_collection_snapshot where question_collection_snapshot_id = $1`,
      [snapshot.data.questionCollectionSnapshotId],
    );
    expect(persistedSnapshot.rows[0].frozen_content_json.items[0].question.stemMarkdown === frozenStem,
      "collection_snapshot_mutated_after_question_revision");

    const overrides = [null, null, null];
    const editorCreated = await fetchJson(`${baseUrl}/api/v1/editor/documents`, {
      method: "POST",
      body: {
        workspaceId,
        actorUserId,
        documentKind: "synchronized_handout",
        title: "题目落位验收",
        schemaVersion: 1,
        masterDoc: editorDoc(),
        versionOverrides: overrides,
      },
    });
    expect(editorCreated.status === 201, `editor_create_status:${editorCreated.status}`);
    const documentId = editorCreated.data.editorDocumentId;
    const placed = await fetchJson(`${baseUrl}/api/v1/editor/documents/${documentId}/question-references`, {
      method: "POST",
      body: {
        workspaceId,
        actorUserId,
        expectedRevisionNo: 1,
        insertionIndex: 1,
        targetLayers: ["basic", "advanced", "common"],
        questions: [
          { questionRevisionId: firstRevisionId, displayMode: "full", showAnswer: true, showAnalysis: true },
          { questionRevisionId: imported.data.results[1].questionRevisionId, displayMode: "full", showAnswer: true, showAnalysis: true },
        ],
      },
    });
    expect(placed.status === 200 && placed.data.revisionNo === 2, `editor_placement_status:${placed.status}`);
    const placedNodes = placed.data.masterDoc.content.filter((node) => node.type === "questionReference");
    expect(placedNodes.length === 2, "editor_placement_node_count");
    expect(placedNodes.every((node) => node.attrs.teacherMarkdown && node.attrs.studentMarkdown), "editor_reference_not_hydrated");

    const editorSnapshot = await fetchJson(`${baseUrl}/api/v1/editor/documents/${documentId}/snapshots`, {
      method: "POST",
      body: { workspaceId, actorUserId, expectedRevisionNo: 2, variantKey: "common", audience: "teacher", schemaVersion: 1 },
    });
    expect(editorSnapshot.status === 201, `editor_snapshot_after_placement:${editorSnapshot.status}`);
    expect(JSON.stringify(editorSnapshot.data.frozenContent).includes("三角形"), "editor_snapshot_missing_question_content");

    // External keys are identity metadata, not searchable teaching content. Retrieve
    // by the stable stem phrase and verify the usage projection instead.
    const usageSearch = await fetchJson(
      `${baseUrl}/api/v1/questions/search?workspaceId=${workspaceId}&actorUserId=${actorUserId}`
        + `&query=${encodeURIComponent("证明第 0 题")}&limit=10`,
    );
    expect(usageSearch.status === 200 && usageSearch.data.items[0]?.referenced === true, "question_usage_marker_missing");

    const counts = await pool.query(
      `select
        (select count(*)::int from teachbase_app.question) as questions,
        (select count(*)::int from teachbase_app.question_revision) as revisions,
        (select count(*)::int from teachbase_app.question_collection_checkpoint) as checkpoints,
        (select count(*)::int from teachbase_app.question_collection_snapshot) as snapshots,
        (select count(*)::int from teachbase_app.editor_question_reference) as editor_references`,
    );
    expect(counts.rows[0].questions === 240, `question_count:${counts.rows[0].questions}`);
    expect(counts.rows[0].revisions === 241, `revision_count:${counts.rows[0].revisions}`);
    expect(counts.rows[0].checkpoints === 3, `checkpoint_count:${counts.rows[0].checkpoints}`);

    report = {
      schemaVersion: 1,
      generatedAt: new Date().toISOString(),
      status: "passed",
      import: {
        sourceSystems: ["doc_math", "doc_english", "pdf_math", "pdf_english"],
        questions: counts.rows[0].questions,
        revisions: counts.rows[0].revisions,
        exactReplayCreatedRevision: repeated.data.results[0].createdRevision,
        correctionRevisionNo: correctionImport.data.results[0].revisionNo,
      },
      search: {
        chinesePhraseResults: search.data.items.length,
        elapsedMs: searchMs,
        trigramIndex: "idx_question_revision_search_trgm",
        keysetPagination: "passed",
        humanReviewProjection: "passed",
        pendingReviewQueue: "passed",
        usageProjection: "passed",
      },
      collection: {
        concurrentSaves: 2,
        successfulSaves: 1,
        conflicts: 1,
        checkpointKind: "autosave",
        checkpointList: "passed",
        restoreCreatesNewVersion: "passed",
        immutableSnapshot: "passed",
        snapshotItems: snapshot.data.frozenContent.items.length,
      },
      editorPlacement: {
        batchQuestions: 2,
        editorRevisionsCreated: 1,
        hydratedTeacherAndStudentContent: "passed",
        frozenSnapshotContainsQuestionContent: "passed",
      },
      portability: {
        reportUsesAbsolutePathsAsInputContract: false,
      },
      cleanup: "pending",
    };
  } finally {
    if (pool) await pool.end();
    await stopChild(child);
    await cluster.stop();
  }

  report.cleanup = "passed";
  await fs.mkdir(path.dirname(reportPath), { recursive: true });
  await fs.writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
  process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error.message}\n`);
  // Explicit exit prevents a leaked third-party handle from masking a failed gate.
  process.exit(1);
});
