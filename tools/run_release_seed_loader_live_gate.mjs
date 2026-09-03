import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { Pool } from "pg";

import { startEmbeddedPostgresCluster } from "../tests/helpers/runtime_testkit.mjs";

const __filename = fileURLToPath(import.meta.url);
const workspaceRoot = path.resolve(path.dirname(__filename), "..");
const serverRoot = path.join(workspaceRoot, "backend", "teachbase-server");
const jarPath = path.join(serverRoot, "target", "teachbase-server-0.1.0-SNAPSHOT.jar");
const finalReportPath = path.join(
  workspaceRoot, "docs", "reports", "release_seed_loader_live_gate_20260901.json",
);

function expect(condition, message) {
  if (!condition) throw new Error(message);
}

function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.keys(value).sort().map((key) => [key, canonical(value[key])]));
  }
  return value;
}

function sha256Bytes(bytes) {
  return crypto.createHash("sha256").update(bytes).digest("hex");
}

function sha256Json(value) {
  return sha256Bytes(Buffer.from(JSON.stringify(canonical(value)), "utf8"));
}

function contentHash(row, defaults) {
  const original = row.original;
  return sha256Json({
    subject: defaults.subject,
    stage: defaults.stage,
    grade: defaults.grade,
    questionType: defaults.questionType,
    title: row.externalKey,
    lesson: "",
    primaryKnowledgeTag: row.primaryKnowledgeTag,
    secondaryKnowledgeTags: row.secondaryKnowledgeTags,
    difficultyStars: row.difficultyStars,
    materialMarkdown: original.material ?? "",
    stemMarkdown: original.prompt,
    options: original.options,
    answerMarkdown: original.answer,
    analysisMarkdown: original.explanation ?? "",
    content: { schemaVersion: 1, original, sourceLocator: row.sourceLocator },
  });
}

async function writeJson(file, value) {
  await fs.writeFile(file, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

async function writeJsonl(file, values) {
  await fs.writeFile(file, values.map((value) => JSON.stringify(value)).join("\n") + (values.length ? "\n" : ""), "utf8");
}

async function computePackageHash(root) {
  const payloadPaths = [
    "questions.jsonl", "question_relations.jsonl", "source_documents.jsonl",
    "source_regions.jsonl", "rejected_questions.jsonl", "assets/manual-source.json",
  ];
  const digest = crypto.createHash("sha256");
  for (const relative of payloadPaths) {
    digest.update(Buffer.from(relative, "utf8"));
    digest.update(Buffer.from([0]));
    digest.update(await fs.readFile(path.join(root, ...relative.split("/"))));
    digest.update(Buffer.from([0]));
  }
  return digest.digest("hex");
}

async function buildPackage(root) {
  await fs.mkdir(path.join(root, "assets"), { recursive: true });
  const sourceBytes = Buffer.from('{"fixture":"release-seed-loader-live"}\n', "utf8");
  const sourceSha = sha256Bytes(sourceBytes);
  await fs.writeFile(path.join(root, "assets", "manual-source.json"), sourceBytes);
  const defaults = { subject: "数学", stage: "初中", grade: "七年级", questionType: "选择题" };
  const base = (index, primary, secondary) => ({
    externalKey: `release-seed-live-q-${index}`,
    sourceSystem: "manual_seed",
    sourceKey: `release-seed-live:${sourceSha}:q-${index}`,
    taggerInputHash: "0".repeat(64),
    originalFileSha256: sourceSha,
    sourceLocator: { kind: "businessId", value: `q-${index}` },
    sourceDocumentKey: "release-seed-live-document",
    sourceRegionKey: `release-seed-live-region-${index}`,
    original: {
      prompt: index === 1 ? "1 + 1 = ?" : "2 + 1 = ?",
      material: null,
      options: [
        { key: "A", text: "1" }, { key: "B", text: index === 1 ? "2" : "3" },
      ],
      answer: "B",
      explanation: "使用初等加法计算。",
      formulaRefs: [],
      imageRefs: [],
    },
    difficultyStars: 1,
    primaryKnowledgeTag: primary,
    secondaryKnowledgeTags: [secondary],
    tagging: {
      confidence: 1,
      taggerName: "release-seed-loader-live-tagger",
      taggerVersion: "1.0.0",
      taggerInputHash: "0".repeat(64),
      needsHumanReview: false,
    },
    review: {
      reviewStatus: "approved",
      reviewerId: "release-seed-live-reviewer",
      reviewedAt: "2026-09-01T00:00:00Z",
      reviewPolicyVersion: "release-seed-live-policy-v1",
    },
  });
  const questions = [
    base(1, "fixture/math/arithmetic", "fixture/math/counting"),
    base(2, "fixture/math/arithmetic", "fixture/math/counting"),
  ];
  for (const question of questions) {
    question.contentHash = contentHash(question, defaults);
    question.taggerInputHash = question.contentHash;
    question.tagging.taggerInputHash = question.contentHash;
  }
  const relations = [{
    fromExternalKey: questions[0].externalKey,
    toExternalKey: questions[1].externalKey,
    relationType: "related",
    ordinal: 0,
  }];
  const sourceDocuments = [{
    sourceDocumentKey: "release-seed-live-document",
    sourceSystem: "manual_seed",
    originalFileSha256: sourceSha,
    assetPath: "assets/manual-source.json",
    assetSha256: sourceSha,
    mediaType: "application/json",
  }];
  const sourceRegions = [1, 2].map((index) => ({
    sourceRegionKey: `release-seed-live-region-${index}`,
    sourceDocumentKey: "release-seed-live-document",
    locator: { kind: "businessId", value: `q-${index}` },
  }));
  const rejected = [];
  await writeJsonl(path.join(root, "questions.jsonl"), questions);
  await writeJsonl(path.join(root, "question_relations.jsonl"), relations);
  await writeJsonl(path.join(root, "source_documents.jsonl"), sourceDocuments);
  await writeJsonl(path.join(root, "source_regions.jsonl"), sourceRegions);
  await writeJsonl(path.join(root, "rejected_questions.jsonl"), rejected);

  const packageHash = await computePackageHash(root);
  const manifest = {
    schemaVersion: "teachbase.release-seed.v1",
    batchId: "release-seed-loader-live-001",
    releaseVersion: "live-gate-v1",
    generatedAt: "2026-09-01T00:00:00Z",
    questionCount: questions.length,
    approvedQuestionCount: questions.length,
    rejectedQuestionCount: 0,
    pendingReviewQuestionCount: 0,
    sourceSystems: ["manual_seed"],
    contentSha256: packageHash,
    assetCount: 1,
    taggerName: "release-seed-loader-live-tagger",
    taggerVersion: "1.0.0",
    taggerInputHash: questions[0].taggerInputHash,
    reviewedBy: "release-seed-live-reviewer",
    reviewedAt: "2026-09-01T00:00:00Z",
    reviewPolicyVersion: "release-seed-live-policy-v1",
  };
  await writeJson(path.join(root, "manifest.json"), manifest);
  await writeJson(path.join(root, "validation_report.json"), {
    batchId: manifest.batchId,
    releaseVersion: manifest.releaseVersion,
    packageContentSha256: packageHash,
    validatorName: "release-seed-loader-live-validator",
    validatorVersion: "1.0.0",
    validatedAt: "2026-09-01T00:00:00Z",
    passed: true,
    errorCount: 0,
  });
  await writeJson(path.join(root, "review_report.json"), {
    batchId: manifest.batchId,
    releaseVersion: manifest.releaseVersion,
    packageContentSha256: packageHash,
    reviewerId: manifest.reviewedBy,
    reviewedAt: manifest.reviewedAt,
    reviewPolicyVersion: manifest.reviewPolicyVersion,
    reviewMode: "full",
    sampleSize: questions.length,
    approvedQuestionCount: questions.length,
    rejectedQuestionCount: 0,
    issueCounts: {},
  });
  return { packageHash, defaults, questionCount: questions.length };
}

async function buildCrossBatchReplay(sourceRoot, targetRoot) {
  await fs.cp(sourceRoot, targetRoot, { recursive: true });
  const questions = (await fs.readFile(path.join(targetRoot, "questions.jsonl"), "utf8"))
    .trim().split(/\r?\n/).filter(Boolean).map((line) => JSON.parse(line));
  for (const question of questions) question.tagging.taggerVersion = "1.0.1";
  await writeJsonl(path.join(targetRoot, "questions.jsonl"), questions);
  const packageHash = await computePackageHash(targetRoot);
  const manifest = JSON.parse(await fs.readFile(path.join(targetRoot, "manifest.json"), "utf8"));
  manifest.batchId = "release-seed-loader-live-002";
  manifest.releaseVersion = "live-gate-v2";
  manifest.taggerVersion = "1.0.1";
  manifest.contentSha256 = packageHash;
  await writeJson(path.join(targetRoot, "manifest.json"), manifest);
  const validation = JSON.parse(await fs.readFile(path.join(targetRoot, "validation_report.json"), "utf8"));
  validation.batchId = manifest.batchId;
  validation.releaseVersion = manifest.releaseVersion;
  validation.packageContentSha256 = packageHash;
  await writeJson(path.join(targetRoot, "validation_report.json"), validation);
  const review = JSON.parse(await fs.readFile(path.join(targetRoot, "review_report.json"), "utf8"));
  review.batchId = manifest.batchId;
  review.releaseVersion = manifest.releaseVersion;
  review.packageContentSha256 = packageHash;
  await writeJson(path.join(targetRoot, "review_report.json"), review);
  return packageHash;
}

async function runCommand({ database, cluster, mode, packageRoot, reportPath, storageRoot, ids, defaults, failAfter = 0 }) {
  const databaseUrl = new URL(database.connectionString);
  const env = {
    ...process.env,
    TEACHBASE_DATABASE_URL: `jdbc:postgresql://127.0.0.1:${cluster.port}/${database.database}`,
    TEACHBASE_DATABASE_USER: decodeURIComponent(databaseUrl.username),
    TEACHBASE_DATABASE_PASSWORD: decodeURIComponent(databaseUrl.password),
    TEACHBASE_RENDER_ENABLED: "false",
    TEACHBASE_RELEASE_SEED_MODE: mode,
    TEACHBASE_RELEASE_SEED_PACKAGE_ROOT: packageRoot,
    TEACHBASE_RELEASE_SEED_REPORT_PATH: reportPath,
    TEACHBASE_RELEASE_SEED_STORAGE_ROOT: storageRoot,
    TEACHBASE_RELEASE_SEED_LEASE_DURATION: "1s",
    TEACHBASE_RELEASE_SEED_FAIL_AFTER_ITEMS: String(failAfter),
  };
  if (ids) {
    env.TEACHBASE_RELEASE_SEED_WORKSPACE_ID = ids.workspaceId;
    env.TEACHBASE_RELEASE_SEED_ACTOR_USER_ID = ids.actorUserId;
    env.TEACHBASE_RELEASE_SEED_TAXONOMY_VERSION_ID = ids.taxonomyVersionId;
    env.TEACHBASE_RELEASE_SEED_DEFAULT_SUBJECT = defaults.subject;
    env.TEACHBASE_RELEASE_SEED_DEFAULT_STAGE = defaults.stage;
    env.TEACHBASE_RELEASE_SEED_DEFAULT_GRADE = defaults.grade;
    env.TEACHBASE_RELEASE_SEED_DEFAULT_QUESTION_TYPE = defaults.questionType;
  }
  const logs = { stdout: [], stderr: [] };
  const child = spawn("java", ["-jar", jarPath, "--spring.main.web-application-type=none"], {
    cwd: serverRoot,
    env,
    stdio: ["ignore", "pipe", "pipe"],
  });
  child.stdout.on("data", (chunk) => logs.stdout.push(String(chunk)));
  child.stderr.on("data", (chunk) => logs.stderr.push(String(chunk)));
  const exitCode = await new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      child.kill();
      reject(new Error(`release_seed_command_timeout:${mode}`));
    }, 60_000);
    // close 在进程退出且 stdout/stderr 管道关闭后触发，避免 Windows 清理竞态。
    child.once("close", (code) => {
      clearTimeout(timer);
      resolve(code);
    });
  });
  let report = null;
  try {
    report = JSON.parse(await fs.readFile(reportPath, "utf8"));
  } catch {
    // A startup failure may occur before the command runner can create a report.
  }
  return { exitCode, report, logs };
}

async function main() {
  await fs.access(jarPath);
  const runRoot = path.join(workspaceRoot, "test-results", `release-seed-loader-${crypto.randomUUID()}`);
  const packageRoot = path.join(runRoot, "package");
  const replayPackageRoot = path.join(runRoot, "package-replay");
  const storageRoot = path.join(runRoot, "storage");
  const reportsRoot = path.join(runRoot, "reports");
  await fs.mkdir(packageRoot, { recursive: true });
  await fs.mkdir(reportsRoot, { recursive: true });
  const fixture = await buildPackage(packageRoot);
  const cluster = await startEmbeddedPostgresCluster("release_seed_loader_live_gate");
  let pool;
  let finalReport;
  try {
    const database = await cluster.createDatabase("release_seed_loader_test");
    const validate = await runCommand({
      database, cluster, mode: "validate", packageRoot,
      reportPath: path.join(reportsRoot, "validate.json"), storageRoot,
    });
    expect(validate.exitCode === 0 && validate.report?.status === "passed", `validate_failed:${validate.exitCode}`);

    pool = new Pool({ connectionString: database.connectionString });
    const ids = {
      workspaceId: crypto.randomUUID(),
      actorUserId: crypto.randomUUID(),
      taxonomyVersionId: crypto.randomUUID(),
    };
    const primaryNodeId = crypto.randomUUID();
    const secondaryNodeId = crypto.randomUUID();
    await pool.query(
      `insert into teachbase_app.workspace (workspace_id, slug, display_name) values ($1, 'release-seed-loader-live', 'Release Seed Loader Live')`,
      [ids.workspaceId],
    );
    await pool.query(
      `insert into teachbase_app.app_user (user_id, email, display_name) values ($1, 'release-seed-loader@example.invalid', 'Release Seed Loader')`,
      [ids.actorUserId],
    );
    await pool.query(
      `insert into teachbase_app.workspace_member (workspace_id, user_id, member_role) values ($1, $2, 'owner')`,
      [ids.workspaceId, ids.actorUserId],
    );
    await pool.query(
      `insert into teachbase_app.taxonomy_version
       (taxonomy_version_id, workspace_id, taxonomy_key, version_key, subject, stage, status, schema_version, created_by, activated_at)
       values ($1, $2, 'release-seed-live-taxonomy', 'v1', '数学', '初中', 'active', 1, $3, now())`,
      [ids.taxonomyVersionId, ids.workspaceId, ids.actorUserId],
    );
    await pool.query(
      `insert into teachbase_app.taxonomy_node
       (taxonomy_node_id, taxonomy_version_id, workspace_id, knowledge_code, display_name, sort_order, metadata_json)
       values ($1, $3, $4, 'MATH.ARITHMETIC', '算术', 0, '{}'),
              ($2, $3, $4, 'MATH.COUNTING', '计数', 1, '{}')`,
      [primaryNodeId, secondaryNodeId, ids.taxonomyVersionId, ids.workspaceId],
    );
    await pool.query(
      `insert into teachbase_app.taxonomy_alias
       (taxonomy_alias_id, taxonomy_node_id, taxonomy_version_id, workspace_id, display_alias, normalized_alias)
       values ($1, $2, $4, $5, 'fixture/math/arithmetic', 'fixture/math/arithmetic'),
              ($3, $6, $4, $5, 'fixture/math/counting', 'fixture/math/counting')`,
      [crypto.randomUUID(), primaryNodeId, crypto.randomUUID(), ids.taxonomyVersionId, ids.workspaceId, secondaryNodeId],
    );

    const dryRun = await runCommand({
      database, cluster, mode: "dry-run", packageRoot,
      reportPath: path.join(reportsRoot, "dry-run.json"), storageRoot, ids, defaults: fixture.defaults,
    });
    expect(dryRun.exitCode === 0 && dryRun.report?.databaseWrites === 0, `dry_run_failed:${dryRun.exitCode}`);
    const beforeImport = await pool.query("select count(*)::int as count from teachbase_app.release_seed_batch");
    expect(beforeImport.rows[0].count === 0, "dry_run_wrote_batch");

    const interrupted = await runCommand({
      database, cluster, mode: "import", packageRoot,
      reportPath: path.join(reportsRoot, "interrupted.json"), storageRoot, ids,
      defaults: fixture.defaults, failAfter: 1,
    });
    expect(interrupted.exitCode !== 0 && interrupted.report?.errorCode === "release_seed_injected_interruption",
      `interruption_not_observed:${interrupted.exitCode}:${JSON.stringify(interrupted.report)}`);
    const checkpoint = await pool.query(
      `select status, next_question_index, approved_count, attempt_no
         from teachbase_app.release_seed_batch where package_content_hash = $1`,
      [fixture.packageHash],
    );
    expect(checkpoint.rows[0].status === "importing", "interrupted_batch_not_leased");
    expect(checkpoint.rows[0].next_question_index === 1 && checkpoint.rows[0].approved_count === 1,
      "interrupted_checkpoint_not_durable");
    await new Promise((resolve) => setTimeout(resolve, 1_300));

    const resumed = await runCommand({
      database, cluster, mode: "import", packageRoot,
      reportPath: path.join(reportsRoot, "resumed.json"), storageRoot, ids, defaults: fixture.defaults,
    });
    expect(resumed.exitCode === 0 && resumed.report?.status === "passed",
      `resume_failed:${resumed.exitCode}:${JSON.stringify(resumed.report)}:${resumed.logs.stdout.join("")}`);
    expect(resumed.report.resumedFromQuestionIndex === 1 && resumed.report.attemptNo === 2,
      "resume_cursor_or_attempt_invalid");

    const replay = await runCommand({
      database, cluster, mode: "import", packageRoot,
      reportPath: path.join(reportsRoot, "replay.json"), storageRoot, ids, defaults: fixture.defaults,
    });
    expect(replay.exitCode === 0 && replay.report?.attemptNo === 2, "completed_replay_not_idempotent");
    const verify = await runCommand({
      database, cluster, mode: "verify", packageRoot,
      reportPath: path.join(reportsRoot, "verify.json"), storageRoot, ids, defaults: fixture.defaults,
    });
    expect(verify.exitCode === 0 && verify.report?.verification?.approvedItemCount === 2,
      `verify_failed:${verify.exitCode}:${JSON.stringify(verify.report)}`);

    const replayPackageHash = await buildCrossBatchReplay(packageRoot, replayPackageRoot);
    expect(replayPackageHash !== fixture.packageHash, "cross_batch_package_hash_not_changed");
    const crossBatch = await runCommand({
      database, cluster, mode: "import", packageRoot: replayPackageRoot,
      reportPath: path.join(reportsRoot, "cross-batch.json"), storageRoot, ids, defaults: fixture.defaults,
    });
    expect(crossBatch.exitCode === 0 && crossBatch.report?.reusedCount === 2
      && crossBatch.report?.importedCount === 0,
    `cross_batch_replay_failed:${crossBatch.exitCode}:${JSON.stringify(crossBatch.report)}`);

    const state = await pool.query(
      `select
        (select count(*)::int from teachbase_app.question) as questions,
        (select count(*)::int from teachbase_app.question_revision) as revisions,
        (select count(*)::int from teachbase_app.review_decision) as decisions,
        (select count(*)::int from teachbase_app.question_source_link) as source_links,
        (select count(*)::int from teachbase_app.question_relation) as relations,
        (select count(*)::int from teachbase_app.question_taxonomy_link) as taxonomy_links,
        (select count(*)::int from teachbase_app.file_version) as files,
        (select count(*)::int from teachbase_app.question_import_observation) as observations`,
    );
    expect(state.rows[0].questions === 2 && state.rows[0].revisions === 2, "question_counts_invalid");
    expect(state.rows[0].decisions === 2 && state.rows[0].source_links === 2, "review_or_source_counts_invalid");
    expect(state.rows[0].relations === 1 && state.rows[0].taxonomy_links === 4, "relation_or_taxonomy_counts_invalid");
    expect(state.rows[0].files === 1 && state.rows[0].observations === 4, "file_or_observation_counts_invalid");
    const tempFiles = (await fs.readdir(path.join(storageRoot, "release-seed", fixture.packageHash)))
      .filter((name) => name.endsWith(".tmp"));
    expect(tempFiles.length === 0, "release_seed_temp_files_remaining");

    finalReport = {
      schemaVersion: 1,
      generatedAt: new Date().toISOString(),
      status: "passed",
      commands: { validate: "passed", dryRun: "passed", import: "passed", verify: "passed" },
      package: { questions: 2, sourceDocuments: 1, sourceRegions: 2, relations: 1 },
      recovery: {
        injectedAfterItems: 1,
        durableNextQuestionIndex: 1,
        resumedFromQuestionIndex: resumed.report.resumedFromQuestionIndex,
        attempts: resumed.report.attemptNo,
      },
      idempotency: {
        replayStatus: replay.report.status,
        questions: state.rows[0].questions,
        revisions: state.rows[0].revisions,
        importObservations: state.rows[0].observations,
        crossBatchSemanticReplay: "passed",
        crossBatchImportedRevisions: crossBatch.report.importedCount,
        crossBatchReusedRevisions: crossBatch.report.reusedCount,
      },
      verification: verify.report.verification,
      evidence: { reviewDecisions: state.rows[0].decisions, sourceLinks: state.rows[0].source_links },
      storage: { registeredFiles: state.rows[0].files, temporaryFilesRemaining: tempFiles.length },
      portability: { reportUsesAbsolutePathsAsInputContract: false },
      cleanup: "pending",
    };
  } finally {
    if (pool) await pool.end();
    await cluster.stop();
    // 杀毒软件或刚关闭的子进程可能短暂占用目录；有界重试后仍失败则保留红灯。
    await fs.rm(runRoot, { recursive: true, force: true, maxRetries: 30, retryDelay: 200 });
  }
  finalReport.cleanup = "passed";
  await fs.mkdir(path.dirname(finalReportPath), { recursive: true });
  await fs.writeFile(finalReportPath, `${JSON.stringify(finalReport, null, 2)}\n`, "utf8");
  process.stdout.write(`${JSON.stringify(finalReport, null, 2)}\n`);
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error.message}\n`);
  process.exit(1);
});
