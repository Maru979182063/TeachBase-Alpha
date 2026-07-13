import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const workspaceRoot = path.resolve(__dirname, "..");

function asArray(value) {
  if (!value) {
    return [];
  }
  if (Array.isArray(value)) {
    return value;
  }
  if (Array.isArray(value.records)) {
    return value.records;
  }
  if (Array.isArray(value.results)) {
    return value.results;
  }
  if (Array.isArray(value.questions)) {
    return value.questions;
  }
  if (Array.isArray(value.items)) {
    return value.items;
  }
  if (typeof value === "object") {
    return Object.values(value).filter((item) => item && typeof item === "object");
  }
  return [];
}

function firstText(...values) {
  for (const value of values) {
    if (value === undefined || value === null) {
      continue;
    }
    const text = String(value).trim();
    if (text) {
      return text;
    }
  }
  return "";
}

function normalizeStatus(value) {
  return String(value || "")
    .trim()
    .toLowerCase()
    .replace(/[\s-]+/g, "_");
}

function questionIdOf(record = {}) {
  return firstText(
    record.question_id,
    record.questionId,
    record.local_task_id,
    record.localTaskId,
    record.record_id,
    record.id,
    record.node_id,
    record.nodeId
  );
}

function indexByQuestionId(records) {
  const indexed = new Map();
  for (const record of asArray(records)) {
    const questionId = questionIdOf(record);
    if (questionId) {
      indexed.set(questionId, record);
    }
  }
  return indexed;
}

function transcriptionGateOf(record = null) {
  if (!record) {
    return { status: "missing", hardFail: false, review: true, reasons: ["transcription_gate_missing"] };
  }
  const status = normalizeStatus(
    firstText(
      record.quality_gate,
      record.qualityGate,
      record.ingest_decision,
      record.ingestDecision,
      record.decision,
      record.status
    )
  );
  if (status === "block" || status === "blocked" || status === "fail" || status === "failed") {
    return { status: "block", hardFail: true, review: false, reasons: ["transcription_quality_gate_block"] };
  }
  if (
    status === "allow_with_review" ||
    status === "needs_review" ||
    status === "review" ||
    record.needs_human_review === true ||
    record.needsHumanReview === true
  ) {
    return { status: status || "review", hardFail: false, review: true, reasons: ["transcription_needs_review"] };
  }
  if (status === "allow" || status === "ok" || status === "accepted" || status === "pass") {
    return { status: "allow", hardFail: false, review: false, reasons: [] };
  }
  return { status: status || "missing", hardFail: false, review: true, reasons: ["transcription_gate_unclear"] };
}

function assetAuditOf(record = null) {
  if (!record) {
    return { status: "missing", hardFail: false, review: true, reasons: ["asset_audit_missing"] };
  }
  const status = normalizeStatus(
    firstText(
      record.asset_audit,
      record.assetAudit,
      record.audit_status,
      record.auditStatus,
      record.status,
      record.decision
    )
  );
  if (status === "fail" || status === "failed" || status === "block" || status === "blocked") {
    return { status: "fail", hardFail: true, review: false, reasons: ["asset_audit_fail"] };
  }
  if (status === "needs_review" || status === "review" || status === "warning") {
    return { status: "needs_review", hardFail: false, review: true, reasons: ["asset_audit_needs_review"] };
  }
  if (status === "pass" || status === "allow" || status === "ok" || status === "accepted") {
    return { status: "pass", hardFail: false, review: false, reasons: [] };
  }
  return { status: status || "missing", hardFail: false, review: true, reasons: ["asset_audit_unclear"] };
}

function splitAuditOf(record = null) {
  if (!record) {
    return { status: "missing", hardFail: false, review: false, reasons: [] };
  }
  const status = normalizeStatus(
    firstText(record.split_v03, record.splitV03, record.review_status, record.reviewStatus, record.status, record.decision)
  );
  if (status === "quarantined" || status === "quarantined_orphan" || status === "block") {
    return { status: "QUARANTINED", hardFail: true, review: false, reasons: ["split_v03_quarantined"] };
  }
  if (status === "needs_review" || status === "review") {
    return { status: "NEEDS_REVIEW", hardFail: false, review: true, reasons: ["split_v03_needs_review"] };
  }
  if (status === "audited_ready" || status === "ready" || status === "allow" || status === "pass") {
    return { status: "AUDITED_READY", hardFail: false, review: false, reasons: [] };
  }
  return { status: status || "missing", hardFail: false, review: true, reasons: ["split_v03_unclear"] };
}

function uniqueSorted(values) {
  return [...new Set(values.filter(Boolean))].sort((a, b) => a.localeCompare(b));
}

function arrayTextValues(values = []) {
  return values
    .flatMap((value) => {
      if (!value) {
        return [];
      }
      if (Array.isArray(value)) {
        return value;
      }
      return [value];
    })
    .map((value) => String(value || "").trim())
    .filter(Boolean);
}

function nestedValue(record = {}, ...paths) {
  for (const pathParts of paths) {
    let cursor = record;
    let found = true;
    for (const part of pathParts) {
      if (!cursor || typeof cursor !== "object" || !(part in cursor)) {
        found = false;
        break;
      }
      cursor = cursor[part];
    }
    if (found && cursor !== undefined && cursor !== null && String(cursor).trim()) {
      return cursor;
    }
  }
  return "";
}

function assetIdsOf(record = {}) {
  const lineage = record.lineage && typeof record.lineage === "object" ? record.lineage : {};
  const qvs = record.question_visual_structure && typeof record.question_visual_structure === "object"
    ? record.question_visual_structure
    : {};
  const selectedScope = record.selected_scope_asset_ids && typeof record.selected_scope_asset_ids === "object"
    ? record.selected_scope_asset_ids
    : {};
  const selectedAssetValues = Object.values(selectedScope).flatMap((value) => {
    if (Array.isArray(value)) {
      return value;
    }
    if (value && typeof value === "object") {
      return Object.values(value).flatMap((nested) => (Array.isArray(nested) ? nested : [nested]));
    }
    return [value];
  });
  return uniqueSorted([
    ...arrayTextValues([lineage.asset_ids, lineage.assetIds]),
    ...asArray(record.assets).map((asset) => firstText(asset.asset_id, asset.assetId, asset.id)),
    ...asArray(qvs.visual_assets).map((asset) => firstText(asset.asset_id, asset.assetId, asset.id)),
    ...arrayTextValues(selectedAssetValues),
  ]);
}

function lineageOf({
  questionId = "",
  releaseDecisionId = "",
  runtimeImportId = "",
  generatedAt = "",
  runId = "",
  sourceRunId = "",
  records = [],
} = {}) {
  const sourceRecords = records.filter((record) => record && typeof record === "object");
  const firstRecord = (...paths) => {
    for (const record of sourceRecords) {
      const value = nestedValue(record, ...paths);
      if (String(value || "").trim()) {
        return String(value).trim();
      }
    }
    return "";
  };
  const semanticNodeId = firstRecord(
    ["lineage", "semantic_node_id"],
    ["lineage", "semanticNodeId"],
    ["semantic_node_id"],
    ["semanticNodeId"],
    ["question_visual_structure", "semantic_node_id"],
    ["question_visual_structure", "node_id"],
    ["split_node_id"],
    ["node_id"]
  );
  return {
    source_run_id: firstRecord(
      ["lineage", "source_run_id"],
      ["lineage", "sourceRunId"],
      ["source_run_id"],
      ["sourceRunId"],
      ["runtime_run_id"],
      ["runtimeRunId"],
      ["run_id"],
      ["runId"]
    ) || sourceRunId || runId || "",
    source_document_id: firstRecord(
      ["lineage", "source_document_id"],
      ["lineage", "sourceDocumentId"],
      ["source_document_id"],
      ["sourceDocumentId"],
      ["document_id"],
      ["documentId"]
    ),
    document_revision_id: firstRecord(
      ["lineage", "document_revision_id"],
      ["lineage", "documentRevisionId"],
      ["document_revision_id"],
      ["documentRevisionId"]
    ),
    semantic_node_id: semanticNodeId,
    question_id: questionId,
    asset_ids: uniqueSorted(sourceRecords.flatMap((record) => assetIdsOf(record))),
    release_decision_id: releaseDecisionId,
    runtime_import_id: runtimeImportId,
    created_at: generatedAt,
  };
}

export function buildReleaseDecisions({
  transcriptionResults = [],
  assetAuditResults = [],
  splitAuditResults = [],
  questionIds = [],
  generatedAt = new Date().toISOString(),
  runId = "",
  sourceRunId = "",
} = {}) {
  const transcriptionById = indexByQuestionId(transcriptionResults);
  const assetById = indexByQuestionId(assetAuditResults);
  const splitById = indexByQuestionId(splitAuditResults);
  const ids = uniqueSorted([
    ...questionIds.map(String),
    ...transcriptionById.keys(),
    ...assetById.keys(),
    ...splitById.keys(),
  ]);
  const decisions = ids.map((questionId) => {
    const transcriptionRecord = transcriptionById.get(questionId) || null;
    const assetRecord = assetById.get(questionId) || null;
    const splitRecord = splitById.get(questionId) || null;
    const transcription = transcriptionGateOf(transcriptionById.get(questionId));
    const asset = assetAuditOf(assetById.get(questionId));
    const split = splitAuditOf(splitById.get(questionId));
    const reasons = [...transcription.reasons, ...asset.reasons, ...split.reasons];
    const releaseDecisionId = `${runId || sourceRunId || "release_decision"}:${questionId}`;
    let decision = "allow";
    if (transcription.hardFail || asset.hardFail || split.hardFail) {
      decision = "block";
    } else if (transcription.review || asset.review || split.review) {
      decision = "review";
    }
    return {
      question_id: questionId,
      decision,
      reasons,
      transcription_gate: {
        status: transcription.status,
        source: transcriptionById.get(questionId) || null,
      },
      asset_audit: {
        status: asset.status,
        source: assetById.get(questionId) || null,
      },
      split_audit: {
        status: split.status,
        source: splitById.get(questionId) || null,
      },
      release_decision_id: releaseDecisionId,
      lineage: lineageOf({
        questionId,
        releaseDecisionId,
        generatedAt,
        runId,
        sourceRunId,
        records: [transcriptionRecord, assetRecord, splitRecord],
      }),
      generated_at: generatedAt,
      source_run_id: sourceRunId || runId || "",
    };
  });
  return decisions;
}

export function buildReleaseDecisionOutputs(options = {}) {
  const generatedAt = options.generatedAt || new Date().toISOString();
  const runId = options.runId || options.sourceRunId || `release_decision_${generatedAt.replace(/[:.]/g, "-")}`;
  const decisions = buildReleaseDecisions({
    ...options,
    generatedAt,
    runId,
    sourceRunId: options.sourceRunId || runId,
  });
  const allow = decisions.filter((item) => item.decision === "allow");
  const review = decisions.filter((item) => item.decision === "review");
  const block = decisions.filter((item) => item.decision === "block");
  const toManifestItems = (items) =>
    items.map((item) => ({
      question_id: item.question_id,
      decision: item.decision,
      release_decision_id: item.release_decision_id,
      lineage: item.lineage,
    }));
  return {
    canonical_release_decision: {
      schema_version: "canonical_release_decision.v0.1",
      generated_at: generatedAt,
      run_id: runId,
      decisions,
    },
    allow_list_manifest: {
      schema_version: "allow_list_manifest.v0.1",
      generated_at: generatedAt,
      run_id: runId,
      allow_question_ids: allow.map((item) => item.question_id),
      review_question_ids: review.map((item) => item.question_id),
      block_question_ids: block.map((item) => item.question_id),
      allow_items: toManifestItems(allow),
      review_items: toManifestItems(review),
      block_items: toManifestItems(block),
      decisions,
    },
    release_decision_summary: {
      total: decisions.length,
      allow: allow.length,
      review: review.length,
      block: block.length,
      generated_at: generatedAt,
      run_id: runId,
    },
  };
}

export function normalizeAllowListManifest(manifest = null) {
  if (!manifest || typeof manifest !== "object") {
    return null;
  }
  const decisions = asArray(manifest.decisions || manifest.canonical_release_decision);
  const allowQuestionIds = new Set(
    [
      ...(Array.isArray(manifest.allow_question_ids) ? manifest.allow_question_ids : []),
      ...(Array.isArray(manifest.allowQuestionIds) ? manifest.allowQuestionIds : []),
      ...decisions
        .filter((item) => normalizeStatus(item.decision) === "allow")
        .map((item) => item.question_id || item.questionId),
    ]
      .map((item) => String(item || "").trim())
      .filter(Boolean)
  );
  const reviewQuestionIds = new Set(
    [
      ...(Array.isArray(manifest.review_question_ids) ? manifest.review_question_ids : []),
      ...(Array.isArray(manifest.reviewQuestionIds) ? manifest.reviewQuestionIds : []),
      ...decisions
        .filter((item) => normalizeStatus(item.decision) === "review")
        .map((item) => item.question_id || item.questionId),
    ]
      .map((item) => String(item || "").trim())
      .filter(Boolean)
  );
  const blockQuestionIds = new Set(
    [
      ...(Array.isArray(manifest.block_question_ids) ? manifest.block_question_ids : []),
      ...(Array.isArray(manifest.blockQuestionIds) ? manifest.blockQuestionIds : []),
      ...decisions
        .filter((item) => normalizeStatus(item.decision) === "block")
        .map((item) => item.question_id || item.questionId),
    ]
      .map((item) => String(item || "").trim())
      .filter(Boolean)
  );
  return {
    schema_version: manifest.schema_version || manifest.schemaVersion || "allow_list_manifest.v0.1",
    generated_at: manifest.generated_at || manifest.generatedAt || "",
    run_id: manifest.run_id || manifest.runId || "",
    allow_question_ids: [...allowQuestionIds],
    review_question_ids: [...reviewQuestionIds],
    block_question_ids: [...blockQuestionIds],
    allow_items: asArray(manifest.allow_items || manifest.allowItems),
    review_items: asArray(manifest.review_items || manifest.reviewItems),
    block_items: asArray(manifest.block_items || manifest.blockItems),
    decisions,
  };
}

function localTaskIdOf(task = {}) {
  return firstText(task.local_task_id, task.localTaskId, task.question_id, task.questionId, task.id);
}

export function applyReleaseGateToLessonDraftBundle(bundle = {}, options = {}) {
  const manifest = normalizeAllowListManifest(options.allowListManifest || options.allow_list_manifest);
  if (!manifest) {
    if (options.requireReleaseDecision) {
      throw new Error("missing_allow_list_manifest");
    }
    return {
      bundle,
      gateApplied: false,
      releaseGate: {
        applied: false,
        reason: "allow_list_manifest_missing",
      },
    };
  }
  const allowSet = new Set(manifest.allow_question_ids);
  const reviewSet = new Set(manifest.review_question_ids);
  const blockSet = new Set(manifest.block_question_ids);
  const originalTasks = Array.isArray(bundle.tasks) ? bundle.tasks : [];
  const allowTasks = originalTasks.filter((task) => allowSet.has(localTaskIdOf(task)));
  const reviewTasks = originalTasks.filter((task) => reviewSet.has(localTaskIdOf(task)));
  const blockTasks = originalTasks.filter((task) => blockSet.has(localTaskIdOf(task)));
  const unknownTasks = originalTasks.filter((task) => {
    const id = localTaskIdOf(task);
    return !allowSet.has(id) && !reviewSet.has(id) && !blockSet.has(id);
  });
  if (allowTasks.length === 0) {
    throw new Error("release_gate_no_allow_tasks");
  }
  const manifestItems = [
    ...asArray(manifest.allow_items),
    ...asArray(manifest.review_items),
    ...asArray(manifest.block_items),
    ...asArray(manifest.decisions),
  ];
  const lineageByQuestionId = new Map();
  for (const item of manifestItems) {
    const questionId = questionIdOf(item);
    const lineage = item?.lineage && typeof item.lineage === "object" ? item.lineage : null;
    if (questionId && lineage) {
      lineageByQuestionId.set(questionId, lineage);
    }
  }
  const importedLineage = allowTasks.map((task) => {
    const questionId = localTaskIdOf(task);
    const sourceLineage = lineageByQuestionId.get(questionId) || {};
    return {
      ...lineageOf({
        questionId,
        releaseDecisionId: firstText(sourceLineage.release_decision_id),
        generatedAt: manifest.generated_at || new Date().toISOString(),
        runId: manifest.run_id || "",
        records: [task, { lineage: sourceLineage }],
      }),
      ...sourceLineage,
      question_id: questionId,
      runtime_import_id: "",
    };
  });
  return {
    bundle: {
      ...bundle,
      tasks: allowTasks,
      release_decision: {
        schema_version: "runtime_import_release_gate.v0.1",
        applied: true,
        allow_list_run_id: manifest.run_id || "",
        original_task_count: originalTasks.length,
        imported_task_count: allowTasks.length,
        review_task_count: reviewTasks.length,
        block_task_count: blockTasks.length,
        unknown_task_count: unknownTasks.length,
        lineage: importedLineage,
      },
    },
    gateApplied: true,
    releaseGate: {
      applied: true,
      manifest,
      original_task_count: originalTasks.length,
      imported_task_count: allowTasks.length,
      review_task_count: reviewTasks.length,
      block_task_count: blockTasks.length,
      unknown_task_count: unknownTasks.length,
      review_question_ids: reviewTasks.map(localTaskIdOf),
      block_question_ids: blockTasks.map(localTaskIdOf),
      unknown_question_ids: unknownTasks.map(localTaskIdOf),
      lineage: importedLineage,
    },
  };
}

export function buildRuntimeImportLineage({
  releaseGate = {},
  runtimeImportId = "",
  createdAt = new Date().toISOString(),
} = {}) {
  const sourceLineage = asArray(releaseGate.lineage);
  return {
    schema_version: "runtime_import_lineage.v0.1",
    runtime_import_id: runtimeImportId,
    created_at: createdAt,
    items: sourceLineage.map((item) => ({
      source_run_id: firstText(item.source_run_id),
      source_document_id: firstText(item.source_document_id),
      document_revision_id: firstText(item.document_revision_id),
      semantic_node_id: firstText(item.semantic_node_id),
      question_id: firstText(item.question_id),
      asset_ids: arrayTextValues([item.asset_ids, item.assetIds]),
      release_decision_id: firstText(item.release_decision_id),
      runtime_import_id: runtimeImportId,
      created_at: createdAt,
    })),
  };
}

function readJsonIfPresent(filePath) {
  if (!filePath) {
    return null;
  }
  const absolutePath = path.isAbsolute(filePath) ? filePath : path.resolve(workspaceRoot, filePath);
  if (!fs.existsSync(absolutePath)) {
    return null;
  }
  return JSON.parse(fs.readFileSync(absolutePath, "utf8").replace(/^\uFEFF/, ""));
}

function parseArgs(argv) {
  const args = {};
  for (let index = 0; index < argv.length; index += 1) {
    const item = argv[index];
    if (!item.startsWith("--")) {
      continue;
    }
    const key = item.slice(2);
    const next = argv[index + 1];
    if (!next || next.startsWith("--")) {
      args[key] = true;
      continue;
    }
    args[key] = next;
    index += 1;
  }
  return args;
}

function writeJson(filePath, value) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

export async function runReleaseDecisionCli(argv = process.argv.slice(2)) {
  const args = parseArgs(argv);
  const outDir = path.resolve(workspaceRoot, args.outDir || args["out-dir"] || "outputs/release_decision");
  const outputs = buildReleaseDecisionOutputs({
    transcriptionResults: readJsonIfPresent(args.transcription) || [],
    assetAuditResults: readJsonIfPresent(args.assetAudit || args["asset-audit"]) || [],
    splitAuditResults: readJsonIfPresent(args.splitAudit || args["split-audit"]) || [],
    runId: args.runId || args["run-id"] || "",
    sourceRunId: args.sourceRunId || args["source-run-id"] || "",
  });
  writeJson(path.join(outDir, "canonical_release_decision.json"), outputs.canonical_release_decision);
  writeJson(path.join(outDir, "allow_list_manifest.json"), outputs.allow_list_manifest);
  writeJson(path.join(outDir, "release_decision_summary.json"), outputs.release_decision_summary);
  return { outDir, ...outputs.release_decision_summary };
}

if (process.argv[1] && path.resolve(process.argv[1]) === __filename) {
  runReleaseDecisionCli()
    .then((result) => {
      console.log(JSON.stringify(result, null, 2));
    })
    .catch((error) => {
      console.error(error);
      process.exitCode = 1;
    });
}
