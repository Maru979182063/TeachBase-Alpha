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
const reportPath = path.join(root, "docs", "reports", "difficulty_feedback_01a_live_gate.json");
const contextKey = "senior-math:grade-10:default";

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
    externalKey: `difficulty-feedback-live-q-${index}`,
    sourceSystem: "difficulty-feedback-live-gate",
    sourceKey: `fixture/question-${index}`,
    reviewStatus: "pending_review",
    subject: "数学",
    stage: "高中",
    grade: "高一",
    questionType: "解答题",
    title: `难度反馈验收题 ${index}`,
    lesson: "函数",
    primaryKnowledgeTag: "函数",
    secondaryKnowledgeTags: [],
    difficultyStars: 2,
    materialMarkdown: "用于难度反馈事务验收的固定材料。",
    stemMarkdown: `第 ${index} 题：讨论函数参数范围。`,
    options: [],
    answerMarkdown: "分类讨论。",
    analysisMarkdown: "根据定义域与单调性分情况求解。",
    content: { schemaVersion: 1, blocks: [{ type: "stem", order: 0 }] },
    provenance: { fixture: "difficulty-feedback-01a-live", sourceIndex: index },
  };
}

async function registerRubric(baseUrl, workspaceId, actorUserId, definitions = null) {
  return fetchJson(`${baseUrl}/api/v1/difficulty-rubrics/versions`, {
    method: "POST",
    body: {
      workspaceId,
      actorUserId,
      rubricKey: "senior-math-five-star",
      versionCode: "mvp-v1",
      subject: "数学",
      stage: "高中",
      grade: "高一",
      definitions: definitions || {
        "1": "直接识别或单步代入",
        "2": "基础概念与少量推理",
        "3": "多步推理或常规综合",
        "4": "复杂综合与关键转化",
        "5": "高强度综合或创新推理",
      },
      status: "active",
    },
  });
}

async function registerRun(baseUrl, workspaceId, actorUserId, rubricVersionId, overrides = {}) {
  return fetchJson(`${baseUrl}/api/v1/difficulty-assessment-runs`, {
    method: "POST",
    body: {
      workspaceId,
      actorUserId,
      externalRunKey: "difficulty-live:batch-001",
      rubricVersionId,
      modelProvider: "controlled-fixture",
      modelName: "difficulty-baseline-worker",
      modelVersion: "mvp-v1",
      promptProfileVersion: "difficulty-rubric-mvp-v1",
      evidencePackageKey: "difficulty-live-fixture",
      evidencePackageVersion: "v1",
      evidencePackageHash: crypto.createHash("sha256").update("difficulty-live-fixture").digest("hex"),
      producerVersion: "difficulty-feedback-gate-v1",
      runtimeVersion: "java-foundation-v1",
      parameters: { temperature: 0, scale: "1-5" },
      status: "completed",
      startedAt: "2026-09-14T00:00:00Z",
      completedAt: "2026-09-14T00:00:01Z",
      ...overrides,
    },
  });
}

async function registerSuggestion(baseUrl, runId, workspaceId, actorUserId, questionRevisionId, overrides = {}) {
  return fetchJson(`${baseUrl}/api/v1/difficulty-assessment-runs/${runId}/question-suggestions`, {
    method: "POST",
    body: {
      workspaceId,
      actorUserId,
      questionRevisionId,
      contextKey,
      context: { subject: "数学", stage: "高中", grade: "高一", audience: "default" },
      difficultyValue: 3,
      confidence: 0.72,
      modelOutputContext: { rationaleCode: "MULTI_STEP_REASONING", schemaVersion: 1 },
      ...overrides,
    },
  });
}

function feedbackBody({ workspaceId, actorUserId, rubricVersionId, beforeSnapshotId,
  expectedStateVersion, clientMutationId, value, reasonCodes = [], note = "", rubricGap = null }) {
  return {
    workspaceId,
    actorUserId,
    rubricKey: "senior-math-five-star",
    rubricVersionId,
    contextKey,
    beforeSnapshotId,
    expectedStateVersion,
    clientMutationId,
    finalDifficultyValue: value,
    reasonCodes,
    note,
    rubricGap,
  };
}

async function submit(baseUrl, revisionId, body) {
  return fetchJson(`${baseUrl}/api/v1/question-revisions/${revisionId}/difficulty-feedback`, {
    method: "POST", body,
  });
}

async function main() {
  await fs.access(jarPath);
  const cluster = await startEmbeddedPostgresCluster("difficulty_feedback_01a_live_gate");
  let child;
  let pool;
  let report;
  try {
    const database = await cluster.createDatabase("difficulty_feedback_01a_test");
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
    await pool.query("insert into teachbase_app.workspace(workspace_id,slug,display_name) values($1,'difficulty-live','Difficulty Live')", [workspaceId]);
    for (const [actor, email] of [[actorA, "difficulty-a@example.invalid"], [actorB, "difficulty-b@example.invalid"]]) {
      await pool.query("insert into teachbase_app.app_user(user_id,email,display_name) values($1,$2,$2)", [actor, email]);
      await pool.query("insert into teachbase_app.workspace_member(workspace_id,user_id,member_role) values($1,$2,'reviewer')", [workspaceId, actor]);
      await pool.query(`insert into teachbase_app.workspace_member_teaching_scope
        (workspace_id,user_id,subject,stage,is_primary,assigned_by) values($1,$2,'数学','高中',true,$2)`, [workspaceId, actor]);
    }

    const imported = await fetchJson(`${baseUrl}/api/v1/questions/import-batch`, {
      method: "POST", body: { workspaceId, actorUserId: actorA, questions: [1, 2, 3, 4].map(questionPacket) },
    });
    expect(imported.status === 200 && imported.data.results.length === 4, `question_import_failed:${JSON.stringify(imported.data)}`);
    const revisions = imported.data.results.map((value) => value.questionRevisionId);
    const review = await fetchJson(`${baseUrl}/api/v1/review-cases`, {
      method: "POST", body: { workspaceId, actorUserId: actorA, questionRevisionId: revisions[0] },
    });
    const reviewed = await fetchJson(`${baseUrl}/api/v1/review-cases/${review.data.reviewCaseId}/decisions`, {
      method: "POST",
      body: { workspaceId, actorUserId: actorA, expectedContentHash: review.data.expectedContentHash,
        decision: "approved", note: "难度反馈前冻结 Review", policyVersion: "difficulty-live-v1",
        decisionSource: "human_ui", evidence: { gate: "difficulty-feedback-01a" },
        evidenceOccurredAt: new Date().toISOString() },
    });
    expect(reviewed.status === 200, "review_setup_failed");

    const beforeDomain = (await pool.query(`select jsonb_build_object(
      'revisionCount',(select count(*)::int from teachbase_app.question_revision),
      'revision',(select to_jsonb(x) from (select difficulty_stars,review_status,content_hash from teachbase_app.question_revision where question_revision_id=$1) x),
      'question',(select to_jsonb(x) from (select approved_revision_id,current_revision_no from teachbase_app.question where question_id=$2) x),
      'review',(select to_jsonb(x) from (select status,decided_at from teachbase_app.review_case where review_case_id=$3) x)
    ) value`, [revisions[0], imported.data.results[0].questionId, review.data.reviewCaseId])).rows[0].value;

    const rubric = await registerRubric(baseUrl, workspaceId, actorA);
    expect(rubric.status === 200 && rubric.data.replayed === false, `rubric_register_failed:${JSON.stringify(rubric.data)}`);
    const rubricReplay = await registerRubric(baseUrl, workspaceId, actorA);
    expect(rubricReplay.status === 200 && rubricReplay.data.replayed === true, "rubric_replay_failed");
    const rubricConflict = await registerRubric(baseUrl, workspaceId, actorA,
      { "1": "变更", "2": "较易", "3": "中等", "4": "较难", "5": "困难" });
    expect(rubricConflict.status === 409, "rubric_conflict_not_closed");
    const rubricVersionId = rubric.data.rubricVersionId;

    const run = await registerRun(baseUrl, workspaceId, actorA, rubricVersionId);
    expect(run.status === 200 && run.data.replayed === false, "run_register_failed");
    const runReplay = await registerRun(baseUrl, workspaceId, actorA, rubricVersionId);
    expect(runReplay.status === 200 && runReplay.data.replayed === true, "run_replay_failed");
    const runConflict = await registerRun(baseUrl, workspaceId, actorA, rubricVersionId,
      { runtimeVersion: "conflicting-runtime" });
    expect(runConflict.status === 409, "run_conflict_not_closed");
    const failedRun = await registerRun(baseUrl, workspaceId, actorA, rubricVersionId,
      { externalRunKey: "difficulty-live:failed-run", status: "failed" });
    expect(failedRun.status === 200, "failed_run_observation_not_registered");
    const failedRunSuggestion = await registerSuggestion(
      baseUrl, failedRun.data.assessmentRunId, workspaceId, actorA, revisions[0]);
    expect(failedRunSuggestion.status === 400, "failed_run_emitted_suggestion");

    const suggestions = [];
    for (const revision of revisions) {
      const suggestion = await registerSuggestion(baseUrl, run.data.assessmentRunId, workspaceId, actorA, revision);
      expect(suggestion.status === 200, `suggestion_failed:${JSON.stringify(suggestion.data)}`);
      suggestions.push(suggestion.data);
    }
    const contextConflict = await registerSuggestion(
      baseUrl, run.data.assessmentRunId, workspaceId, actorA, revisions[0],
      { context: { subject: "数学", stage: "高中", grade: "高一", audience: "honors" } });
    expect(contextConflict.status === 409, "context_key_payload_conflict_not_closed");

    const corrected = await submit(baseUrl, revisions[0], feedbackBody({
      workspaceId, actorUserId: actorA, rubricVersionId, beforeSnapshotId: suggestions[0].snapshotId,
      expectedStateVersion: 0, clientMutationId: "difficulty-correct", value: 4,
      reasonCodes: ["COMPLEXITY_UNDERESTIMATED"], note: "需要跨章节转化",
    }));
    expect(corrected.status === 200 && corrected.data.derivedOperations[0].code === "DIFFICULTY_CHANGED", "correction_failed");

    const repeatedBody = feedbackBody({
      workspaceId, actorUserId: actorA, rubricVersionId, beforeSnapshotId: corrected.data.currentSnapshotId,
      expectedStateVersion: 1, clientMutationId: "difficulty-repeat-100", value: 4,
      reasonCodes: ["CONFIRMED"], note: "网络重试",
    });
    const repeated = await Promise.all(Array.from({ length: 100 }, () => submit(baseUrl, revisions[0], repeatedBody)));
    expect(repeated.every((value) => value.status === 200), "repeated_http_failure");
    expect(new Set(repeated.map((value) => value.data.feedbackId)).size === 1
      && repeated.filter((value) => value.data.replayed === false).length === 1, "repeated_result_duplicated");
    const mutationConflict = await submit(baseUrl, revisions[0], { ...repeatedBody, note: "不同载荷" });
    expect(mutationConflict.status === 409, "mutation_conflict_not_closed");

    const unchanged = await submit(baseUrl, revisions[1], feedbackBody({
      workspaceId, actorUserId: actorA, rubricVersionId, beforeSnapshotId: suggestions[1].snapshotId,
      expectedStateVersion: 0, clientMutationId: "difficulty-unchanged", value: 3,
    }));
    expect(unchanged.status === 200 && unchanged.data.derivedOperations[0].code === "UNCHANGED_CONFIRMED", "unchanged_missing");

    const gap = await submit(baseUrl, revisions[2], feedbackBody({
      workspaceId, actorUserId: actorA, rubricVersionId, beforeSnapshotId: suggestions[2].snapshotId,
      expectedStateVersion: 0, clientMutationId: "difficulty-gap", value: null,
      rubricGap: { expectedDifficultyText: "同题对不同学生群体难度差异过大", explanation: "当前单一星级无法表达" },
    }));
    expect(gap.status === 200 && gap.data.status === "rubric_gap" && gap.data.rubricGapCaseId, "gap_failed");

    const concurrent = await Promise.all([
      submit(baseUrl, revisions[3], feedbackBody({ workspaceId, actorUserId: actorA, rubricVersionId,
        beforeSnapshotId: suggestions[3].snapshotId, expectedStateVersion: 0,
        clientMutationId: "difficulty-cas-a", value: 4 })),
      submit(baseUrl, revisions[3], feedbackBody({ workspaceId, actorUserId: actorB, rubricVersionId,
        beforeSnapshotId: suggestions[3].snapshotId, expectedStateVersion: 0,
        clientMutationId: "difficulty-cas-b", value: 2 })),
    ]);
    expect(concurrent.filter((value) => value.status === 200).length === 1
      && concurrent.filter((value) => value.status === 409).length === 1, "cas_not_one_winner");

    const context = await fetchJson(`${baseUrl}/api/v1/question-revisions/${revisions[0]}/difficulty-review-context?workspaceId=${workspaceId}&actorUserId=${actorA}&rubricKey=senior-math-five-star&contextKey=${encodeURIComponent(contextKey)}`);
    const history = await fetchJson(`${baseUrl}/api/v1/question-revisions/${revisions[0]}/difficulty-feedback-history?workspaceId=${workspaceId}&actorUserId=${actorA}&rubricKey=senior-math-five-star&contextKey=${encodeURIComponent(contextKey)}`);
    expect(context.status === 200 && context.data.systemSuggestion && context.data.currentSnapshot && context.data.runContext, "context_incomplete");
    expect(history.status === 200 && history.data.feedback.length === 2, "history_incomplete");

    const foreignWorkspace = crypto.randomUUID();
    const foreignActor = crypto.randomUUID();
    await pool.query("insert into teachbase_app.workspace(workspace_id,slug,display_name) values($1,'difficulty-foreign','Difficulty Foreign')", [foreignWorkspace]);
    await pool.query("insert into teachbase_app.app_user(user_id,email,display_name) values($1,'difficulty-foreign@example.invalid','Foreign')", [foreignActor]);
    await pool.query("insert into teachbase_app.workspace_member(workspace_id,user_id,member_role) values($1,$2,'reviewer')", [foreignWorkspace, foreignActor]);
    await pool.query(`insert into teachbase_app.workspace_member_teaching_scope
      (workspace_id,user_id,subject,stage,is_primary,assigned_by) values($1,$2,'数学','高中',true,$2)`, [foreignWorkspace, foreignActor]);
    const foreignKnown = await fetchJson(`${baseUrl}/api/v1/question-revisions/${revisions[0]}/difficulty-review-context?workspaceId=${foreignWorkspace}&actorUserId=${foreignActor}&rubricKey=senior-math-five-star&contextKey=${encodeURIComponent(contextKey)}`);
    const foreignRandom = await fetchJson(`${baseUrl}/api/v1/question-revisions/${crypto.randomUUID()}/difficulty-review-context?workspaceId=${foreignWorkspace}&actorUserId=${foreignActor}&rubricKey=senior-math-five-star&contextKey=${encodeURIComponent(contextKey)}`);
    expect(foreignKnown.status === 404 && foreignRandom.status === 404
      && foreignKnown.data?.code === foreignRandom.data?.code, "cross_workspace_entity_leak");

    const afterDomain = (await pool.query(`select jsonb_build_object(
      'revisionCount',(select count(*)::int from teachbase_app.question_revision),
      'revision',(select to_jsonb(x) from (select difficulty_stars,review_status,content_hash from teachbase_app.question_revision where question_revision_id=$1) x),
      'question',(select to_jsonb(x) from (select approved_revision_id,current_revision_no from teachbase_app.question where question_id=$2) x),
      'review',(select to_jsonb(x) from (select status,decided_at from teachbase_app.review_case where review_case_id=$3) x)
    ) value`, [revisions[0], imported.data.results[0].questionId, review.data.reviewCaseId])).rows[0].value;
    expect(JSON.stringify(beforeDomain) === JSON.stringify(afterDomain), "question_or_review_changed");

    const checks = (await pool.query(`select
      (select count(*)::int from teachbase_app.question_difficulty_feedback where client_mutation_id='difficulty-repeat-100') repeat_count,
      (select count(*)::int from teachbase_app.question_difficulty_snapshot s where snapshot_kind='HUMAN_FINAL'
        and not exists(select 1 from teachbase_app.question_difficulty_feedback f where f.after_snapshot_id=s.snapshot_id)) orphan_count,
      (select count(*)::int from teachbase_app.difficulty_rubric_gap_case where feedback_id=$1) gap_count,
      (select state_version from teachbase_app.question_difficulty_state where question_revision_id=$2) q1_version,
      (select count(*)::int from teachbase_app.question_revision where difficulty_stars <> 2 or difficulty_stars is null) legacy_changed`,
    [gap.data.feedbackId, revisions[0]])).rows[0];
    expect(checks.repeat_count === 1 && checks.orphan_count === 0 && checks.gap_count === 1
      && Number(checks.q1_version) === 2 && checks.legacy_changed === 0, "database_invariants_failed");

    report = {
      schemaVersion: 1,
      generatedAt: new Date().toISOString(),
      status: "passed",
      database: { engine: "PostgreSQL", version: (await pool.query("show server_version")).rows[0].server_version },
      acceptance: {
        passed: 19,
        total: 19,
        checks: {
          rubricVersionFrozenAndReplaySafe: true,
          rubricPayloadConflictClosed: true,
          runRegistrationAndReplay: true,
          runPayloadConflictClosed: true,
          failedRunCannotEmitSuggestion: true,
          systemSuggestionRegistered: true,
          contextKeyPayloadConflictClosed: true,
          standardCorrection: true,
          unchangedConfirmation: true,
          rubricGapSeparated: true,
          oneHundredMutationRetries: true,
          mutationPayloadConflict: true,
          casOneSuccessOneConflict: true,
          failedCasLeavesNoOrphan: true,
          reviewContextAndHistory: true,
          currentStateAuthority: true,
          noQuestionRevisionCreated: true,
          questionReviewAndLegacyDifficultyUnchanged: true,
          crossWorkspaceNonDisclosure: true,
        },
      },
      identityBoundary: "business actor authorization and teaching-scope validation only; production authentication remains open",
      searchProjection: "governance projection is a separate read model; legacy question search still reads question_revision.difficulty_stars",
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
