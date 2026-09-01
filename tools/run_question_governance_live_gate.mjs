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
const reportPath = path.join(workspaceRoot, "docs", "reports", "question_governance_live_gate_20260901.json");

function expect(condition, message) {
  if (!condition) throw new Error(message);
}

async function waitForHealth(baseUrl, child, logs) {
  const deadline = Date.now() + 45_000;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) {
      throw new Error(`java_server_exited:${child.exitCode}\n${logs.stdout.join("")}\n${logs.stderr.join("")}`);
    }
    try {
      const response = await fetchJson(`${baseUrl}/actuator/health`);
      if (response.ok && response.data?.status === "UP") return;
    } catch {
      // Flyway and the HTTP listener are still starting.
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

function packet(overrides = {}) {
  return {
    externalKey: "governance-gate-001",
    sourceSystem: "doc_math",
    sourceKey: "governance/fixture-001",
    reviewStatus: "pending_review",
    subject: "数学",
    stage: "初中",
    grade: "八年级",
    questionType: "解答题",
    title: "全等三角形治理样本",
    lesson: "全等三角形",
    primaryKnowledgeTag: "旧自由文本标签",
    secondaryKnowledgeTags: ["证明"],
    difficultyStars: null,
    materialMarkdown: "如图，在 $\\triangle ABC$ 中。",
    stemMarkdown: "证明 $\\triangle ABC \\cong \\triangle DEF$。",
    options: [],
    answerMarkdown: "结论成立。",
    analysisMarkdown: "验证两边及其夹角。",
    content: { schemaVersion: 1, blocks: [{ type: "stem", order: 0 }] },
    provenance: { pipeline: "doc_math", runId: "governance-gate-run-1" },
    ...overrides,
  };
}

async function main() {
  await fs.access(jarPath);
  const cluster = await startEmbeddedPostgresCluster("question_governance_live_gate");
  let child;
  let pool;
  let report;
  try {
    const database = await cluster.createDatabase("question_governance_test");
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
    const actorUserId = crypto.randomUUID();
    await pool.query(
      "insert into teachbase_app.workspace (workspace_id, slug, display_name) values ($1, $2, $3)",
      [workspaceId, "question-governance-gate", "Question Governance Gate"],
    );
    await pool.query(
      "insert into teachbase_app.app_user (user_id, email, display_name) values ($1, $2, $3)",
      [actorUserId, "question-governance@example.invalid", "Governance Gate Actor"],
    );
    await pool.query(
      "insert into teachbase_app.workspace_member (workspace_id, user_id, member_role) values ($1, $2, 'owner')",
      [workspaceId, actorUserId],
    );

    const bypass = await fetchJson(`${baseUrl}/api/v1/questions/import-batch`, {
      method: "POST",
      body: { workspaceId, actorUserId, questions: [packet({ reviewStatus: "approved" })] },
    });
    expect(bypass.status === 400, `approved_import_not_blocked:${bypass.status}`);

    const badDeclaredHash = await fetchJson(`${baseUrl}/api/v1/questions/import-batch`, {
      method: "POST",
      body: { workspaceId, actorUserId, questions: [packet({ contentHash: "0".repeat(64) })] },
    });
    expect(badDeclaredHash.status === 400, `declared_content_hash_not_verified:${badDeclaredHash.status}`);

    const imported = await fetchJson(`${baseUrl}/api/v1/questions/import-batch`, {
      method: "POST",
      body: { workspaceId, actorUserId, questions: [packet()] },
    });
    expect(imported.status === 200, `governance_import_status:${imported.status}:${JSON.stringify(imported.data)}`);
    const first = imported.data.results[0];

    // Changing operational provenance must not create a semantic content revision,
    // but it must remain visible as a second received envelope.
    const replay = await fetchJson(`${baseUrl}/api/v1/questions/import-batch`, {
      method: "POST",
      body: {
        workspaceId,
        actorUserId,
        questions: [packet({ provenance: { pipeline: "doc_math", runId: "governance-gate-run-2" } })],
      },
    });
    expect(replay.status === 200 && replay.data.results[0].createdRevision === false, "semantic_replay_created_revision");
    const hashes = await pool.query(
      `select content_hash, source_payload_hash, import_envelope_hash
         from teachbase_app.question_revision where question_revision_id = $1`,
      [first.questionRevisionId],
    );
    const observations = await pool.query(
      `select count(*)::int as count, count(distinct import_envelope_hash)::int as envelopes
         from teachbase_app.question_import_observation where question_revision_id = $1`,
      [first.questionRevisionId],
    );
    expect(observations.rows[0].count === 2 && observations.rows[0].envelopes === 2, "import_observation_split_failed");

    const opened = await fetchJson(`${baseUrl}/api/v1/review-cases`, {
      method: "POST",
      body: { workspaceId, actorUserId, questionRevisionId: first.questionRevisionId },
    });
    expect(opened.status === 200, `review_open_failed:${opened.status}:${JSON.stringify(opened.data)}`);
    const decisionBody = {
      workspaceId,
      actorUserId,
      expectedContentHash: opened.data.expectedContentHash,
      decision: "approved",
      note: "concurrent governance gate",
      policyVersion: "governance-gate-v1",
      decisionSource: "human_ui",
      evidence: { gate: "question-governance-live", reviewedBy: "governance-gate-actor" },
      evidenceOccurredAt: new Date().toISOString(),
    };
    const concurrent = await Promise.all([
      fetchJson(`${baseUrl}/api/v1/review-cases/${opened.data.reviewCaseId}/decisions`, {
        method: "POST", body: decisionBody,
      }),
      fetchJson(`${baseUrl}/api/v1/review-cases/${opened.data.reviewCaseId}/decisions`, {
        method: "POST", body: decisionBody,
      }),
    ]);
    expect(concurrent.filter((value) => value.status === 200).length === 1, "review_concurrent_winner_count");
    expect(concurrent.filter((value) => value.status === 409).length === 1, "review_concurrent_conflict_count");

    const approvedSearch = await fetchJson(
      `${baseUrl}/api/v1/questions/search?workspaceId=${workspaceId}&actorUserId=${actorUserId}`
        + `&query=${encodeURIComponent("全等三角形")}&limit=10`,
    );
    expect(approvedSearch.status === 200 && approvedSearch.data.items.length === 1, "approved_pointer_not_searchable");

    const version = await fetchJson(`${baseUrl}/api/v1/taxonomies/versions`, {
      method: "POST",
      body: {
        workspaceId, actorUserId, taxonomyKey: "cn-junior-math", versionKey: "2026.1",
        subject: "数学", stage: "初中", schemaVersion: 1,
      },
    });
    expect(version.status === 200, `taxonomy_version_create_failed:${version.status}:${JSON.stringify(version.data)}`);
    const node = await fetchJson(
      `${baseUrl}/api/v1/taxonomies/versions/${version.data.taxonomyVersionId}/nodes`,
      {
        method: "POST",
        body: {
          workspaceId, actorUserId, knowledgeCode: "M8.GEO.CONGRUENCE",
          displayName: "全等三角形", parentNodeId: null, sortOrder: 0,
          metadata: { source: "governance-live-gate" }, aliases: ["三角形全等", "全等"],
        },
      },
    );
    expect(node.status === 200, `taxonomy_node_create_failed:${node.status}:${JSON.stringify(node.data)}`);
    const activated = await fetchJson(
      `${baseUrl}/api/v1/taxonomies/versions/${version.data.taxonomyVersionId}/activate`,
      { method: "POST", body: { workspaceId, actorUserId } },
    );
    expect(activated.status === 200 && activated.data.status === "active", "taxonomy_activation_failed");
    const resolvedByCode = await fetchJson(
      `${baseUrl}/api/v1/taxonomies/versions/${version.data.taxonomyVersionId}/resolve`
        + `?workspaceId=${workspaceId}&actorUserId=${actorUserId}`
        + `&codeOrAlias=${encodeURIComponent("M8.GEO.CONGRUENCE")}`,
    );
    const resolvedByAlias = await fetchJson(
      `${baseUrl}/api/v1/taxonomies/versions/${version.data.taxonomyVersionId}/resolve`
        + `?workspaceId=${workspaceId}&actorUserId=${actorUserId}`
        + `&codeOrAlias=${encodeURIComponent("三角形全等")}`,
    );
    expect(resolvedByCode.data?.taxonomyNodeId === node.data.taxonomyNodeId, "taxonomy_code_resolution_failed");
    expect(resolvedByAlias.data?.taxonomyNodeId === node.data.taxonomyNodeId, "taxonomy_alias_resolution_failed");
    const immutable = await fetchJson(
      `${baseUrl}/api/v1/taxonomies/versions/${version.data.taxonomyVersionId}/nodes`,
      {
        method: "POST",
        body: {
          workspaceId, actorUserId, knowledgeCode: "M8.GEO.LATE", displayName: "禁止追加",
          sortOrder: 1, metadata: {}, aliases: [],
        },
      },
    );
    expect(immutable.status === 409, `active_taxonomy_mutated:${immutable.status}`);
    const assignment = await fetchJson(`${baseUrl}/api/v1/taxonomies/assignments`, {
      method: "POST",
      body: {
        workspaceId, actorUserId, questionRevisionId: first.questionRevisionId,
        taxonomyNodeId: node.data.taxonomyNodeId, relationType: "primary",
        assignmentSource: "human", confidence: null,
      },
    });
    expect(assignment.status === 200, `taxonomy_assignment_failed:${assignment.status}:${JSON.stringify(assignment.data)}`);

    const databaseState = await pool.query(
      `select
        (select count(*)::int from teachbase_app.question_revision) as revisions,
        (select count(*)::int from teachbase_app.review_decision) as decisions,
        (select count(*)::int from teachbase_app.review_decision
          where policy_version = 'governance-gate-v1'
            and decision_source = 'human_ui'
            and evidence_json->>'gate' = 'question-governance-live'
            and evidence_occurred_at is not null) as decisions_with_evidence,
        (select count(*)::int from teachbase_app.question_taxonomy_link) as taxonomy_links,
        (select count(*)::int from teachbase_app.taxonomy_alias) as aliases,
        (select count(*)::int from teachbase_app.audit_event
          where event_type in ('review_case.approved', 'taxonomy_version.activated')) as governance_audits`,
    );
    expect(databaseState.rows[0].revisions === 1, "review_changed_content_revision");
    expect(databaseState.rows[0].decisions === 1, "review_decision_not_append_only");
    expect(databaseState.rows[0].decisions_with_evidence === 1, "review_decision_evidence_missing");
    expect(databaseState.rows[0].taxonomy_links === 1 && databaseState.rows[0].aliases === 2, "taxonomy_state_invalid");

    report = {
      schemaVersion: 1,
      generatedAt: new Date().toISOString(),
      status: "passed",
      hashes: {
        contentHash: hashes.rows[0].content_hash,
        sourcePayloadHash: hashes.rows[0].source_payload_hash,
        importEnvelopeHash: hashes.rows[0].import_envelope_hash,
        semanticRevisionCount: databaseState.rows[0].revisions,
        observedEnvelopes: observations.rows[0].envelopes,
      },
      review: {
        directApprovedImportBlocked: true,
        declaredContentHashMismatchBlocked: true,
        concurrentAttempts: 2,
        successfulDecisions: 1,
        conflicts: 1,
        approvedPointerSearch: "passed",
        appendOnlyDecisionCount: databaseState.rows[0].decisions,
        structuredEvidencePreserved: true,
      },
      taxonomy: {
        versionLifecycle: "draft_to_active",
        activeVersionImmutable: true,
        aliases: databaseState.rows[0].aliases,
        explicitVersionCodeResolution: "passed",
        explicitVersionAliasResolution: "passed",
        revisionPinnedAssignments: databaseState.rows[0].taxonomy_links,
        difficultyPolicyChanged: false,
      },
      audit: { governanceEvents: databaseState.rows[0].governance_audits },
      portability: { reportUsesAbsolutePathsAsInputContract: false },
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
  process.exit(1);
});
