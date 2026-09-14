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
const fixturePath = path.join(root, "tests", "fixtures", "tag_feedback", "real_math_case054_model_excerpt.json");
const reportPath = path.join(root, "docs", "reports", "tag_feedback_01a_live_gate.json");

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
      // Flyway 与 HTTP 监听仍在启动。
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

function questionPacket(index) {
  return {
    externalKey: `tag-feedback-live-q-${index}`,
    sourceSystem: "tag-feedback-live-gate",
    sourceKey: `fixture/question-${index}`,
    reviewStatus: "pending_review",
    subject: "数学",
    stage: "高中",
    grade: "高一",
    questionType: "解答题",
    title: `标签反馈验收题 ${index}`,
    lesson: "函数",
    primaryKnowledgeTag: "legacy/import/evidence",
    secondaryKnowledgeTags: ["legacy-secondary"],
    difficultyStars: 2,
    materialMarkdown: "用于标签反馈事务验收的固定材料。",
    stemMarkdown: `第 ${index} 题：判断对应关系是否构成函数。`,
    options: [],
    answerMarkdown: "按函数定义判断。",
    analysisMarkdown: "检查定义域中每个元素是否具有唯一像。",
    content: { schemaVersion: 1, blocks: [{ type: "stem", order: 0 }] },
    provenance: { fixture: "tag-feedback-01a-live", sourceIndex: index },
  };
}

async function registerRun(baseUrl, fixture, workspaceId, actorUserId, taxonomyVersionId, overrides = {}) {
  const run = fixture.run;
  return fetchJson(`${baseUrl}/api/v1/tagging-runs`, {
    method: "POST",
    body: {
      workspaceId,
      actorUserId,
      taxonomyVersionId,
      externalRunKey: run.externalRunKey,
      modelProvider: run.modelProvider,
      modelName: run.modelName,
      modelVersion: run.modelVersion,
      promptProfileVersion: run.promptProfileVersion,
      candidatePackageKey: run.candidatePackageKey,
      candidatePackageVersion: run.candidatePackageVersion,
      candidatePackageHash: run.candidatePackageHash,
      producerVersion: run.producerVersion,
      runtimeVersion: run.runtimeVersion,
      parameters: run.parameters,
      status: run.status,
      startedAt: run.startedAt,
      completedAt: run.completedAt,
      canonicalImportRequestId: null,
      ...overrides,
    },
  });
}

async function registerSuggestion(baseUrl, runId, workspaceId, actorUserId, revisionId, taxonomyKey, primary, secondary, context) {
  return fetchJson(`${baseUrl}/api/v1/tagging-runs/${runId}/question-suggestions`, {
    method: "POST",
    body: {
      workspaceId,
      actorUserId,
      questionRevisionId: revisionId,
      taxonomyKey,
      primary,
      secondary,
      modelOutputContext: context,
    },
  });
}

function feedbackBody({ workspaceId, actorUserId, taxonomyKey, taxonomyVersionId, beforeSnapshotId,
  expectedStateVersion, clientMutationId, primary, secondary, reasonCodes = [], note = "", taxonomyGap = null }) {
  return {
    workspaceId,
    actorUserId,
    taxonomyKey,
    taxonomyVersionId,
    beforeSnapshotId,
    expectedStateVersion,
    clientMutationId,
    finalPrimaryNodeId: primary,
    finalSecondaryNodeIds: secondary,
    reasonCodes,
    note,
    taxonomyGap,
  };
}

async function submit(baseUrl, revisionId, body) {
  return fetchJson(`${baseUrl}/api/v1/question-revisions/${revisionId}/tag-feedback`, { method: "POST", body });
}

async function main() {
  await fs.access(jarPath);
  const fixture = JSON.parse(await fs.readFile(fixturePath, "utf8"));
  expect(fixture.fixtureKind === "REAL_MODEL_RESULT_EXCERPT", "real_model_fixture_missing");
  const cluster = await startEmbeddedPostgresCluster("tag_feedback_01a_live_gate");
  let child;
  let pool;
  let report;
  try {
    const database = await cluster.createDatabase("tag_feedback_01a_test");
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
    const actorA = crypto.randomUUID();
    const actorB = crypto.randomUUID();
    await pool.query("insert into teachbase_app.workspace(workspace_id,slug,display_name) values($1,'tag-feedback-live','Tag Feedback Live')", [workspaceId]);
    for (const [actor, email] of [[actorA, "teacher-a@example.invalid"], [actorB, "teacher-b@example.invalid"]]) {
      await pool.query("insert into teachbase_app.app_user(user_id,email,display_name) values($1,$2,$3)", [actor, email, email]);
      await pool.query("insert into teachbase_app.workspace_member(workspace_id,user_id,member_role) values($1,$2,'reviewer')", [workspaceId, actor]);
      await pool.query(`insert into teachbase_app.workspace_member_teaching_scope
        (workspace_id,user_id,subject,stage,is_primary,assigned_by) values($1,$2,'数学','高中',true,$2)`, [workspaceId, actor]);
    }

    const imported = await fetchJson(`${baseUrl}/api/v1/questions/import-batch`, {
      method: "POST",
      body: { workspaceId, actorUserId: actorA, questions: [1, 2, 3, 4].map(questionPacket) },
    });
    expect(imported.status === 200 && imported.data.results.length === 4, `question_import_failed:${JSON.stringify(imported.data)}`);
    const revisions = imported.data.results.map((value) => value.questionRevisionId);

    const review = await fetchJson(`${baseUrl}/api/v1/review-cases`, {
      method: "POST", body: { workspaceId, actorUserId: actorA, questionRevisionId: revisions[0] },
    });
    expect(review.status === 200, `review_open_failed:${JSON.stringify(review.data)}`);
    const reviewed = await fetchJson(`${baseUrl}/api/v1/review-cases/${review.data.reviewCaseId}/decisions`, {
      method: "POST",
      body: {
        workspaceId, actorUserId: actorA, expectedContentHash: review.data.expectedContentHash,
        decision: "approved", note: "标签反馈前冻结 Review", policyVersion: "tag-feedback-live-v1",
        decisionSource: "human_ui", evidence: { gate: "tag-feedback-01a" }, evidenceOccurredAt: new Date().toISOString(),
      },
    });
    expect(reviewed.status === 200, `review_decision_failed:${JSON.stringify(reviewed.data)}`);

    const taxonomy = await fetchJson(`${baseUrl}/api/v1/taxonomies/versions`, {
      method: "POST",
      body: { workspaceId, actorUserId: actorA, taxonomyKey: "senior-math-knowledge", versionKey: "2026.09", subject: "数学", stage: "高中", schemaVersion: 1 },
    });
    expect(taxonomy.status === 200, "taxonomy_create_failed");
    const nodes = {};
    for (const [code, displayName] of [["A", "函数概念"], ["B", "函数定义"], ["C", "映射关系"], ["D", "唯一对应"]]) {
      const response = await fetchJson(`${baseUrl}/api/v1/taxonomies/versions/${taxonomy.data.taxonomyVersionId}/nodes`, {
        method: "POST",
        body: { workspaceId, actorUserId: actorA, knowledgeCode: code, displayName, parentNodeId: null, sortOrder: Object.keys(nodes).length, metadata: {}, aliases: [] },
      });
      expect(response.status === 200, `taxonomy_node_failed:${code}`);
      nodes[code] = response.data.taxonomyNodeId;
    }
    const activation = await fetchJson(`${baseUrl}/api/v1/taxonomies/versions/${taxonomy.data.taxonomyVersionId}/activate`, {
      method: "POST", body: { workspaceId, actorUserId: actorA },
    });
    expect(activation.status === 200, "taxonomy_activation_failed");
    const taxonomyVersionId = taxonomy.data.taxonomyVersionId;

    const beforeDomain = (await pool.query(`select jsonb_build_object(
      'revisionCount',(select count(*)::int from teachbase_app.question_revision),
      'q1Revision',(select to_jsonb(x) from (select question_revision_id,review_status,approved_at,content_hash from teachbase_app.question_revision where question_revision_id=$1) x),
      'q1Root',(select to_jsonb(x) from (select approved_revision_id,current_revision_no from teachbase_app.question where question_id=$2) x),
      'reviewCase',(select to_jsonb(x) from (select status,decided_at from teachbase_app.review_case where review_case_id=$3) x),
      'reviewDecision',(select to_jsonb(x) from (select decision,policy_version,expected_content_hash from teachbase_app.review_decision where review_case_id=$3) x),
      'legacyLinks',(select count(*)::int from teachbase_app.question_taxonomy_link)
    ) value`, [revisions[0], imported.data.results[0].questionId, review.data.reviewCaseId])).rows[0].value;

    const runA = await registerRun(baseUrl, fixture, workspaceId, actorA, taxonomyVersionId);
    expect(runA.status === 200 && runA.data.replayed === false, `real_run_register_failed:${JSON.stringify(runA.data)}`);
    const runReplay = await registerRun(baseUrl, fixture, workspaceId, actorA, taxonomyVersionId);
    expect(runReplay.status === 200 && runReplay.data.replayed === true && runReplay.data.taggingRunId === runA.data.taggingRunId, "run_replay_failed");
    const runConflict = await registerRun(baseUrl, fixture, workspaceId, actorA, taxonomyVersionId, { runtimeVersion: "conflicting-runtime" });
    expect(runConflict.status === 409 && runConflict.data?.code === "TAG_FEEDBACK_RUN_PAYLOAD_CONFLICT", "run_payload_conflict_not_closed");

    const primaryA = { taxonomyNodeId: nodes.A, confidence: fixture.suggestion.primary.confidence, candidateRank: fixture.suggestion.primary.candidateRank };
    // 中文维护说明：外部知识点键只是来源证据，入库引用仍使用当前 workspace 内的精确 taxonomy node UUID。
    const realModelContext = {
      ...fixture.suggestion.modelOutputContext,
      sourceExternalNodeKey: fixture.suggestion.primary.externalNodeKey,
      sourceTaxonomyPath: fixture.suggestion.primary.path,
    };
    const secondaryBC = [
      { taxonomyNodeId: nodes.B, confidence: 0.71, candidateRank: 2 },
      { taxonomyNodeId: nodes.C, confidence: 0.63, candidateRank: 3 },
    ];
    const suggestions = [];
    for (let index = 0; index < 3; index++) {
      const response = await registerSuggestion(baseUrl, runA.data.taggingRunId, workspaceId, actorA, revisions[index], fixture.suggestion.taxonomyKey, primaryA, secondaryBC, realModelContext);
      expect(response.status === 200, `suggestion_failed:${index}:${JSON.stringify(response.data)}`);
      suggestions.push(response.data);
    }
    const realSuggestion = await registerSuggestion(baseUrl, runA.data.taggingRunId, workspaceId, actorA, revisions[3], fixture.suggestion.taxonomyKey, primaryA, [], realModelContext);
    expect(realSuggestion.status === 200, "real_fixture_suggestion_failed");

    const runB = await registerRun(baseUrl, fixture, workspaceId, actorA, taxonomyVersionId, {
      externalRunKey: `${fixture.run.externalRunKey}:run-b`,
      parameters: { ...fixture.run.parameters, rerun: "confidence-variant" },
    });
    expect(runB.status === 200, "second_run_register_failed");
    const confidenceVariant = await registerSuggestion(baseUrl, runB.data.taggingRunId, workspaceId, actorA, revisions[3], fixture.suggestion.taxonomyKey,
      { taxonomyNodeId: nodes.A, confidence: 0.91, candidateRank: 9 }, [], { ...realModelContext, overallScore: 0.91 });
    expect(confidenceVariant.status === 200, "confidence_variant_suggestion_failed");
    expect(realSuggestion.data.labelSetHash === confidenceVariant.data.labelSetHash, "label_set_hash_changed_with_confidence");
    expect(realSuggestion.data.snapshotHash !== confidenceVariant.data.snapshotHash, "snapshot_hash_ignored_run_or_confidence");

    const correction = await submit(baseUrl, revisions[0], feedbackBody({
      workspaceId, actorUserId: actorA, taxonomyKey: fixture.suggestion.taxonomyKey, taxonomyVersionId,
      beforeSnapshotId: suggestions[0].snapshotId, expectedStateVersion: 0, clientMutationId: "golden-correction",
      primary: nodes.B, secondary: [nodes.C, nodes.D], reasonCodes: ["PRIMARY_MISSELECTED"], note: "主标签应为函数定义",
    }));
    expect(correction.status === 200 && correction.data.tagStatus === "reviewed", `correction_failed:${JSON.stringify(correction.data)}`);
    expect(JSON.stringify(correction.data.derivedOperations.map((value) => value.code)) === JSON.stringify(["PRIMARY_CHANGED", "PRIMARY_SECONDARY_SWAP", "SECONDARY_ADDED"]), "golden_diff_invalid");

    const unchanged = await submit(baseUrl, revisions[0], feedbackBody({
      workspaceId, actorUserId: actorA, taxonomyKey: fixture.suggestion.taxonomyKey, taxonomyVersionId,
      beforeSnapshotId: correction.data.currentSnapshotId, expectedStateVersion: 1, clientMutationId: "unchanged-confirmation",
      primary: nodes.B, secondary: [nodes.C, nodes.D], reasonCodes: [], note: "确认当前标签",
    }));
    expect(unchanged.status === 200 && unchanged.data.derivedOperations[0].code === "UNCHANGED_CONFIRMED", "unchanged_confirmation_missing");

    const repeatedBody = feedbackBody({
      workspaceId, actorUserId: actorA, taxonomyKey: fixture.suggestion.taxonomyKey, taxonomyVersionId,
      beforeSnapshotId: unchanged.data.currentSnapshotId, expectedStateVersion: 2, clientMutationId: "repeat-100",
      primary: nodes.B, secondary: [nodes.D, nodes.C], reasonCodes: ["CONFIRMED"], note: "一百次网络重试",
    });
    const repeated = await Promise.all(Array.from({ length: 100 }, () => submit(baseUrl, revisions[0], repeatedBody)));
    expect(repeated.every((value) => value.status === 200), "idempotent_replay_http_failure");
    expect(repeated.filter((value) => value.data.replayed === false).length === 1, "idempotent_first_result_count");
    expect(new Set(repeated.map((value) => value.data.feedbackId)).size === 1, "idempotent_feedback_duplicated");
    const mutationConflict = await submit(baseUrl, revisions[0], { ...repeatedBody, note: "不同载荷" });
    expect(mutationConflict.status === 409 && mutationConflict.data?.code === "TAG_FEEDBACK_IDEMPOTENCY_PAYLOAD_CONFLICT", "mutation_payload_conflict_not_closed");

    const gap = await submit(baseUrl, revisions[1], feedbackBody({
      workspaceId, actorUserId: actorA, taxonomyKey: fixture.suggestion.taxonomyKey, taxonomyVersionId,
      beforeSnapshotId: suggestions[1].snapshotId, expectedStateVersion: 0, clientMutationId: "taxonomy-gap",
      primary: null, secondary: [], reasonCodes: ["NO_SUITABLE_NODE"], note: "树中缺少需要的节点",
      taxonomyGap: { expectedLabelText: "集合间的单值对应判定", explanation: "现有节点粒度无法表达该考查目标" },
    }));
    if (gap.status !== 200) process.stderr.write(logs.stderr.join("") + logs.stdout.join(""));
    expect(gap.status === 200 && gap.data.tagStatus === "taxonomy_gap" && gap.data.taxonomyGapCaseId,
      `taxonomy_gap_failed:${gap.status}:${JSON.stringify(gap.data)}`);
    const gapHistory = await fetchJson(`${baseUrl}/api/v1/question-revisions/${revisions[1]}/tag-feedback-history?workspaceId=${workspaceId}&actorUserId=${actorA}&taxonomyKey=${fixture.suggestion.taxonomyKey}`);
    expect(gapHistory.status === 200 && gapHistory.data.taxonomyGaps.length === 1 && gapHistory.data.snapshots.some((value) => value.snapshotKind === "SYSTEM_SUGGESTION"), "gap_history_incomplete");

    let q3Snapshot = suggestions[2].snapshotId;
    for (let version = 0; version < 7; version++) {
      const response = await submit(baseUrl, revisions[2], feedbackBody({
        workspaceId, actorUserId: actorA, taxonomyKey: fixture.suggestion.taxonomyKey, taxonomyVersionId,
        beforeSnapshotId: q3Snapshot, expectedStateVersion: version, clientMutationId: `q3-prime-${version}`,
        primary: nodes.A, secondary: [nodes.B, nodes.C], note: `推进到版本 ${version + 1}`,
      }));
      expect(response.status === 200, `q3_prime_failed:${version}`);
      q3Snapshot = response.data.currentSnapshotId;
    }
    const concurrent = await Promise.all([
      submit(baseUrl, revisions[2], feedbackBody({
        workspaceId, actorUserId: actorA, taxonomyKey: fixture.suggestion.taxonomyKey, taxonomyVersionId,
        beforeSnapshotId: q3Snapshot, expectedStateVersion: 7, clientMutationId: "q3-concurrent-a",
        primary: nodes.B, secondary: [nodes.C], note: "并发 A",
      })),
      submit(baseUrl, revisions[2], feedbackBody({
        workspaceId, actorUserId: actorB, taxonomyKey: fixture.suggestion.taxonomyKey, taxonomyVersionId,
        beforeSnapshotId: q3Snapshot, expectedStateVersion: 7, clientMutationId: "q3-concurrent-b",
        primary: nodes.C, secondary: [nodes.B], note: "并发 B",
      })),
    ]);
    expect(concurrent.filter((value) => value.status === 200).length === 1, "cas_winner_count_invalid");
    expect(concurrent.filter((value) => value.status === 409).length === 1, "cas_conflict_count_invalid");
    expect(concurrent.find((value) => value.status === 409).data?.currentStateVersion === 8, "cas_conflict_latest_state_missing");

    const foreignWorkspace = crypto.randomUUID();
    const foreignActor = crypto.randomUUID();
    await pool.query("insert into teachbase_app.workspace(workspace_id,slug,display_name) values($1,'tag-feedback-foreign','Foreign')", [foreignWorkspace]);
    await pool.query("insert into teachbase_app.app_user(user_id,email,display_name) values($1,'foreign@example.invalid','Foreign')", [foreignActor]);
    await pool.query("insert into teachbase_app.workspace_member(workspace_id,user_id,member_role) values($1,$2,'reviewer')", [foreignWorkspace, foreignActor]);
    await pool.query(`insert into teachbase_app.workspace_member_teaching_scope
      (workspace_id,user_id,subject,stage,is_primary,assigned_by) values($1,$2,'数学','高中',true,$2)`, [foreignWorkspace, foreignActor]);
    const foreignKnown = await fetchJson(`${baseUrl}/api/v1/question-revisions/${revisions[0]}/tag-review-context?workspaceId=${foreignWorkspace}&actorUserId=${foreignActor}&taxonomyKey=${fixture.suggestion.taxonomyKey}`);
    const foreignRandom = await fetchJson(`${baseUrl}/api/v1/question-revisions/${crypto.randomUUID()}/tag-review-context?workspaceId=${foreignWorkspace}&actorUserId=${foreignActor}&taxonomyKey=${fixture.suggestion.taxonomyKey}`);
    expect(foreignKnown.status === 404 && foreignRandom.status === 404 && foreignKnown.data?.code === foreignRandom.data?.code, "cross_workspace_entity_leak");

    const context = await fetchJson(`${baseUrl}/api/v1/question-revisions/${revisions[0]}/tag-review-context?workspaceId=${workspaceId}&actorUserId=${actorA}&taxonomyKey=${fixture.suggestion.taxonomyKey}`);
    expect(context.status === 200 && context.data.systemSuggestion && context.data.currentSnapshot && context.data.runContext && context.data.questionSourceSummary, "review_context_incomplete");
    const history = await fetchJson(`${baseUrl}/api/v1/question-revisions/${revisions[0]}/tag-feedback-history?workspaceId=${workspaceId}&actorUserId=${actorA}&taxonomyKey=${fixture.suggestion.taxonomyKey}`);
    expect(history.status === 200 && history.data.feedback.length === 3 && history.data.snapshots.some((value) => value.snapshotKind === "HUMAN_FINAL"), "single_question_history_incomplete");

    const afterDomain = (await pool.query(`select jsonb_build_object(
      'revisionCount',(select count(*)::int from teachbase_app.question_revision),
      'q1Revision',(select to_jsonb(x) from (select question_revision_id,review_status,approved_at,content_hash from teachbase_app.question_revision where question_revision_id=$1) x),
      'q1Root',(select to_jsonb(x) from (select approved_revision_id,current_revision_no from teachbase_app.question where question_id=$2) x),
      'reviewCase',(select to_jsonb(x) from (select status,decided_at from teachbase_app.review_case where review_case_id=$3) x),
      'reviewDecision',(select to_jsonb(x) from (select decision,policy_version,expected_content_hash from teachbase_app.review_decision where review_case_id=$3) x),
      'legacyLinks',(select count(*)::int from teachbase_app.question_taxonomy_link)
    ) value`, [revisions[0], imported.data.results[0].questionId, review.data.reviewCaseId])).rows[0].value;
    expect(JSON.stringify(beforeDomain) === JSON.stringify(afterDomain), "question_or_review_semantics_changed");

    const databaseChecks = (await pool.query(`select
      (select count(*)::int from teachbase_app.question_tag_feedback where client_mutation_id='repeat-100') repeat_feedback,
      (select state_version from teachbase_app.question_tag_state where question_revision_id=$1) q1_version,
      (select count(*)::int from teachbase_app.question_tag_snapshot s where snapshot_kind='HUMAN_FINAL'
        and not exists(select 1 from teachbase_app.question_tag_feedback f where f.after_snapshot_id=s.snapshot_id)) orphan_human_snapshots,
      (select count(*)::int from teachbase_app.taxonomy_gap_case where feedback_id=$2) gap_count,
      (select confidence from teachbase_app.question_tag_snapshot_item where snapshot_id=$3 and relation_type='primary') real_confidence,
      (select candidate_rank from teachbase_app.question_tag_snapshot_item where snapshot_id=$3 and relation_type='primary') real_rank,
      (select model_output_context_json->>'sourceExternalNodeKey' from teachbase_app.question_tag_snapshot where snapshot_id=$3) real_external_node_key,
      (select state_version from teachbase_app.question_tag_state where question_revision_id=$4) q3_version`,
    [revisions[0], gap.data.feedbackId, realSuggestion.data.snapshotId, revisions[2]])).rows[0];
    expect(databaseChecks.repeat_feedback === 1 && Number(databaseChecks.q1_version) === 3, "idempotency_database_state_invalid");
    expect(databaseChecks.orphan_human_snapshots === 0, "failed_transaction_left_orphan_snapshot");
    expect(databaseChecks.gap_count === 1, "taxonomy_gap_duplicate_or_missing");
    expect(Number(databaseChecks.real_confidence) === 0.82 && databaseChecks.real_rank === 9, "real_fixture_confidence_or_rank_lost");
    expect(databaseChecks.real_external_node_key === fixture.suggestion.primary.externalNodeKey, "real_fixture_external_node_key_lost");
    expect(Number(databaseChecks.q3_version) === 8, "cas_state_version_invalid");

    report = {
      schemaVersion: 1,
      generatedAt: new Date().toISOString(),
      status: "passed",
      database: { engine: "PostgreSQL", version: (await pool.query("show server_version")).rows[0].server_version },
      fixture: {
        kind: fixture.fixtureKind,
        logicalArtifact: fixture.sourceEvidence.logicalArtifact,
        sourceArtifactSha256: fixture.sourceEvidence.sourceArtifactSha256,
        model: fixture.run.modelName,
        promptProfileVersion: fixture.run.promptProfileVersion,
        externalNodeKey: databaseChecks.real_external_node_key,
        confidence: Number(databaseChecks.real_confidence),
        candidateRank: databaseChecks.real_rank,
      },
      acceptance: {
        passed: 20,
        total: 20,
        checks: {
          runRegistrationAndReplay: true,
          runPayloadConflict: true,
          realSystemSuggestionRegistered: true,
          labelSetHashOrderIndependent: true,
          snapshotHashFreezesRunAndConfidence: true,
          standardCorrection: true,
          unchangedConfirmation: true,
          deterministicDiff: true,
          taxonomyGapSeparated: true,
          oneHundredMutationRetries: true,
          mutationPayloadConflict: true,
          casOneSuccessOneConflictAtVersionSeven: true,
          failedCasLeavesNoOrphan: true,
          reviewContext: true,
          singleQuestionHistory: true,
          currentStateAuthority: true,
          noQuestionRevisionCreated: true,
          questionReviewUnchanged: true,
          legacyTaxonomyLinksUnchanged: true,
          crossWorkspaceNonDisclosure: true,
        },
      },
      identityBoundary: "business actor authorization and teaching-scope validation only; production authentication remains open",
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
  process.stderr.write(`${error.stack || error.message || error}\n`);
  process.exit(1);
});
