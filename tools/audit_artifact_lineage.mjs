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
  if (Array.isArray(value.items)) {
    return value.items;
  }
  if (Array.isArray(value.decisions)) {
    return value.decisions;
  }
  if (Array.isArray(value.results)) {
    return value.results;
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

function questionIdOf(record = {}) {
  return firstText(record.question_id, record.questionId, record.local_task_id, record.localTaskId, record.id);
}

function readJson(filePath) {
  if (!filePath) {
    return null;
  }
  const absolutePath = path.isAbsolute(filePath) ? filePath : path.resolve(workspaceRoot, filePath);
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

function decisionItems(canonical = {}) {
  const root = canonical.canonical_release_decision || canonical;
  return asArray(root.decisions);
}

function allowItems(allowList = {}, canonical = {}) {
  const explicit = asArray(allowList.allow_items || allowList.allowItems);
  if (explicit.length > 0) {
    return explicit;
  }
  const decisionById = new Map(decisionItems(canonical).map((item) => [questionIdOf(item), item]));
  return [
    ...asArray(allowList.allow_question_ids || allowList.allowQuestionIds)
      .map((questionId) => decisionById.get(String(questionId).trim()) || { question_id: String(questionId).trim() }),
    ...decisionItems(allowList).filter((item) => String(item.decision || "").toLowerCase() === "allow"),
  ];
}

function runtimeLineageItems(runtimeImportResult = null) {
  const result =
    runtimeImportResult?.data?.result ||
    runtimeImportResult?.result ||
    runtimeImportResult ||
    {};
  const lineage = result.lineage || runtimeImportResult?.lineage || {};
  return asArray(lineage.items || lineage);
}

export function auditArtifactLineage({
  canonicalReleaseDecision = {},
  allowListManifest = {},
  runtimeImportResult = null,
} = {}) {
  const decisions = decisionItems(canonicalReleaseDecision);
  const decisionById = new Map(decisions.map((item) => [questionIdOf(item), item]));
  const runtimeByQuestionId = new Map(runtimeLineageItems(runtimeImportResult).map((item) => [questionIdOf(item), item]));
  const items = allowItems(allowListManifest, canonicalReleaseDecision);
  const missingFields = [];
  const records = items.map((item) => {
    const questionId = questionIdOf(item);
    const decision = decisionById.get(questionId);
    const lineage = item.lineage && typeof item.lineage === "object"
      ? item.lineage
      : decision?.lineage && typeof decision.lineage === "object"
        ? decision.lineage
        : {};
    const runtimeLineage = runtimeByQuestionId.get(questionId);
    const itemMissing = [];
    const requireField = (field, value, reason = "") => {
      const exists = Array.isArray(value) ? value.filter(Boolean).length > 0 : Boolean(firstText(value));
      if (!exists) {
        const failure = { question_id: questionId || "<missing>", field, reason };
        itemMissing.push(failure);
        missingFields.push(failure);
      }
    };

    requireField("question_id", questionId, "question_id_missing");
    requireField("release_decision", decision, "release_decision_missing");
    requireField("release_decision_id", lineage.release_decision_id || decision?.release_decision_id, "release_decision_id_missing");
    requireField("asset_ids", lineage.asset_ids || lineage.assetIds, "asset_id_missing");
    requireField("source_run_id", lineage.source_run_id || lineage.sourceRunId, "source_run_id_missing");
    if (runtimeImportResult) {
      requireField("runtime_lineage", runtimeLineage, "runtime_artifact_trace_missing");
      requireField("runtime_import_id", runtimeLineage?.runtime_import_id || runtimeLineage?.runtimeImportId, "runtime_import_id_missing");
    }

    return {
      question_id: questionId,
      status: itemMissing.length === 0 ? "pass" : "fail",
      missing_fields: itemMissing,
      lineage,
      runtime_lineage: runtimeLineage || null,
    };
  });
  const passed = records.filter((item) => item.status === "pass").length;
  return {
    schema_version: "artifact_lineage_audit.v0.1",
    total: records.length,
    passed,
    failed: records.length - passed,
    missing_fields: missingFields,
    records,
  };
}

export async function runArtifactLineageAuditCli(argv = process.argv.slice(2)) {
  const args = parseArgs(argv);
  const outDir = path.resolve(workspaceRoot, args.outDir || args["out-dir"] || "outputs/artifact_lineage_audit");
  const audit = auditArtifactLineage({
    canonicalReleaseDecision: readJson(args.canonical || args["canonical-release-decision"]),
    allowListManifest: readJson(args.allowList || args["allow-list"]),
    runtimeImportResult: readJson(args.runtimeImportResult || args["runtime-import-result"]),
  });
  fs.mkdirSync(outDir, { recursive: true });
  const outPath = path.join(outDir, "artifact_lineage_audit.json");
  fs.writeFileSync(outPath, `${JSON.stringify(audit, null, 2)}\n`, "utf8");
  return { outPath, total: audit.total, passed: audit.passed, failed: audit.failed };
}

if (process.argv[1] && path.resolve(process.argv[1]) === __filename) {
  runArtifactLineageAuditCli()
    .then((result) => {
      console.log(JSON.stringify(result, null, 2));
    })
    .catch((error) => {
      console.error(error);
      process.exitCode = 1;
    });
}
