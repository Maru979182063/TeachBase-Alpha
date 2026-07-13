/**
 * 用途：
 * - 实现基于文件的运行时权威状态，包括归一化、检查点和变更流程。
 * - 派生状态重建和可靠写入规则集中在这里，避免调用方重复实现。
 */

import fs from "fs";
import path from "path";
import vm from "vm";
import { createHash, randomUUID } from "crypto";
import { fileURLToPath } from "url";
import {
  normalizeDifficultyPayload,
  resolveTrackProfile,
  validateTrackProfile,
} from "./runtime_subject_tracks.mjs";
import {
  adaptQuestionAssetManifestToLessonDraftBundle,
  looksLikeVisualQuestionManifest,
  normalizeLessonDraftBundle,
} from "./runtime_visual_split_adapter.mjs";
import {
  adaptRuntimeManifestToLessonDraftBundle,
  looksLikeRuntimeManifest,
} from "./runtime_manifest_to_lesson_bundle_adapter.mjs";
import {
  applyReleaseGateToLessonDraftBundle,
  buildRuntimeImportLineage,
} from "./build_release_decision.mjs";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const workspaceRoot = path.resolve(__dirname, "..");
const runtimeRoot =
  process.env.RUNTIME_BACKBONE_STATE_DIR ||
  path.join(workspaceRoot, "outputs", "runtime_backbone_demo");
const statePath =
  process.env.RUNTIME_BACKBONE_STATE_PATH || path.join(runtimeRoot, "state.json");
const workbenchDataPath = path.join(
  workspaceRoot,
  "outputs",
  "split_builder",
  "mock_workbench",
  "workbench_data.js"
);
const threeTrackSeedFixturePaths = [
  path.join(workspaceRoot, "tests", "fixtures", "three_track", "math_junior_bundle.json"),
  path.join(workspaceRoot, "tests", "fixtures", "three_track", "math_senior_bundle.json"),
  path.join(workspaceRoot, "tests", "fixtures", "three_track", "english_senior_bundle.json"),
];
const stateCollectionKeys = [
  "documentSources",
  "documents",
  "documentGroups",
  "documentGroupMembers",
  "documentRelations",
  "runs",
  "jobs",
  "jobAttempts",
  "jobDependencies",
  "outboxEvents",
  "imports",
  "artifacts",
  "artifactDependencies",
  "lessons",
  "lessonRevisions",
  "taskProjections",
  "questionBankItems",
  "questionBankItemRevisions",
  "questionBankSourceLinks",
  "publications",
  "materialBuilds",
  "materialItems",
  "pageAssets",
  "components",
  "componentRevisions",
  "componentPatchCandidates",
  "componentLinks",
  "sourceNodes",
  "sourceNodeRevisions",
  "tasks",
  "taskRevisions",
  "checkpointCatalogs",
  "checkpointCatalogVersions",
  "checkpointNodes",
  "sourceNodeCheckpointLinks",
  "taskCheckpointOverrides",
  "taskSubjectExt",
  "reviewTasks",
  "qualityEvaluations",
];

function makeId(prefix) {
  return `${prefix}_${randomUUID().replace(/-/g, "").slice(0, 12)}`;
}

function slug(text) {
  return String(text || "")
    .trim()
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, "_")
    .replace(/^_+|_+$/g, "") || "unknown";
}

function parseCheckpointName(text) {
  return String(text || "")
    .replace(/^考点\s*\d+\s*/u, "")
    .replace(/\s+/g, " ")
    .trim();
}

function normalizeCheckpointCodes(values) {
  return [...new Set((values || []).map((value) => parseCheckpointName(value)).filter(Boolean))];
}

function normalizeTrackScope(input = {}) {
  const trackProfile = validateTrackProfile(input);
  return {
    trackProfile,
    subject: trackProfile.subject,
    stage: trackProfile.stage,
    track_code: trackProfile.track_code,
  };
}

function safeTrackScope(input = {}) {
  try {
    return normalizeTrackScope(input);
  } catch {
    return null;
  }
}

function buildDifficultyPayload(input, trackProfile, options = {}) {
  return normalizeDifficultyPayload(input, {
    defaultLevel: options.defaultLevel ?? 3,
    defaultScheme: options.defaultScheme || trackProfile?.difficulty_scheme,
    defaultSource: options.defaultSource || "manual",
    defaultConfidence: options.defaultConfidence ?? 0.8,
  });
}

function normalizeBundleImportPayload(payload = {}) {
  const runtimeManifestCandidate =
    payload?.runtime_manifest ||
    payload?.runtimeManifest ||
    (looksLikeRuntimeManifest(payload?.manifest) ? payload.manifest : null) ||
    (looksLikeRuntimeManifest(payload?.bundle) ? payload.bundle : null) ||
    (looksLikeRuntimeManifest(payload) ? payload : null);
  if (
    payload?.payload_type === "runtime_manifest" ||
    payload?.payloadType === "runtime_manifest" ||
    runtimeManifestCandidate
  ) {
    return adaptRuntimeManifestToLessonDraftBundle(runtimeManifestCandidate || payload, {
      bundle_id: payload.bundle_id || payload.bundleId,
      lesson_id: payload.lesson_id || payload.lessonId || payload.lesson?.lesson_id,
      title: payload.title || payload.lesson?.title || payload.lesson?.lesson_title,
      subject: payload.subject || payload.lesson?.subject,
      stage: payload.stage || payload.lesson?.stage,
      track_code: payload.track_code || payload.trackCode || payload.lesson?.track_code,
      grade: payload.grade || payload.lesson?.grade,
      season: payload.season || payload.lesson?.season,
      runtime_run_id: payload.runtime_run_id || payload.runtimeRunId || payload.run_name,
      base_dir: payload.base_dir || payload.baseDir,
      manifest_path: payload.manifest_path || payload.manifestPath,
      document_metadata: payload.document_metadata || payload.documentMetadata,
      source_document_refs: payload.source_document_refs || payload.sourceDocumentRefs,
    });
  }
  if (looksLikeVisualQuestionManifest(payload?.bundle)) {
    return adaptQuestionAssetManifestToLessonDraftBundle(payload.bundle, {
      bundle_id: payload.bundle_id || payload.bundleId,
      lesson_id: payload.lesson_id || payload.lessonId || payload.lesson?.lesson_id,
      title: payload.title || payload.lesson?.title || payload.lesson?.lesson_title,
      subject: payload.subject || payload.lesson?.subject,
      stage: payload.stage || payload.lesson?.stage,
      track_code: payload.track_code || payload.trackCode || payload.lesson?.track_code,
      grade: payload.grade || payload.lesson?.grade,
      season: payload.season || payload.lesson?.season,
      source_tree: payload.source_tree || payload.sourceTree,
      runtime_run_id: payload.runtime_run_id || payload.runtimeRunId,
    });
  }
  if (payload?.bundle) {
    return deepClone(payload.bundle);
  }
  if (looksLikeVisualQuestionManifest(payload?.visualManifest)) {
    return adaptQuestionAssetManifestToLessonDraftBundle(payload.visualManifest, {
      bundle_id: payload.bundle_id || payload.bundleId,
      lesson_id: payload.lesson_id || payload.lessonId || payload.lesson?.lesson_id,
      title: payload.title || payload.lesson?.title || payload.lesson?.lesson_title,
      subject: payload.subject || payload.lesson?.subject,
      stage: payload.stage || payload.lesson?.stage,
      track_code: payload.track_code || payload.trackCode || payload.lesson?.track_code,
      grade: payload.grade || payload.lesson?.grade,
      season: payload.season || payload.lesson?.season,
      source_tree: payload.source_tree || payload.sourceTree,
      runtime_run_id: payload.runtime_run_id || payload.runtimeRunId,
    });
  }
  if (looksLikeVisualQuestionManifest(payload)) {
    return adaptQuestionAssetManifestToLessonDraftBundle(payload, {
      bundle_id: payload.bundle_id || payload.bundleId,
      lesson_id: payload.lesson_id || payload.lessonId || payload.lesson?.lesson_id,
      title: payload.title || payload.lesson?.title || payload.lesson?.lesson_title,
      subject: payload.subject || payload.lesson?.subject,
      stage: payload.stage || payload.lesson?.stage,
      track_code: payload.track_code || payload.trackCode || payload.lesson?.track_code,
      grade: payload.grade || payload.lesson?.grade,
      season: payload.season || payload.lesson?.season,
      source_tree: payload.source_tree || payload.sourceTree,
      runtime_run_id: payload.runtime_run_id || payload.runtimeRunId,
    });
  }
  return deepClone(payload);
}

function mergeTaskRuntimeSourceRefs(sourceRefsJson = {}, component = null, pageAsset = null) {
  const merged = deepClone(sourceRefsJson || {});
  // Keep the richer visual contract intact while refreshing the runtime linkage fields.
  merged.component_id = component?.component_id || merged.component_id || null;
  merged.page_no = pageAsset?.page_no || merged.page_no || null;
  merged.crop_artifact_id = component?.crop_artifact_id || merged.crop_artifact_id || null;
  return merged;
}

function readPersistedTaskSourceRefs(taskSubjectExt = null, componentRevision = null) {
  const storedInSubjectExt = deepClone(taskSubjectExt?.payload_json?.source_refs_json || {});
  if (Object.keys(storedInSubjectExt).length > 0) {
    return storedInSubjectExt;
  }
  return deepClone(componentRevision?.source_refs_json || {});
}

function parseDifficultyFilter(value) {
  if (value === null || value === undefined || value === "") {
    return null;
  }
  return buildDifficultyPayload({ difficulty_level: value }, null, { defaultLevel: 3 }).difficulty_level;
}

function findSourceNodeRevision(state, sourceNodeRevisionId) {
  return state.sourceNodeRevisions.find((item) => item.source_node_revision_id === sourceNodeRevisionId) || null;
}

function getDefaultCheckpointCodesForSourceNodeRevision(state, sourceNodeRevisionId) {
  return normalizeCheckpointCodes(
    state.sourceNodeCheckpointLinks
      .filter(
        (item) =>
          item.source_node_revision_id === sourceNodeRevisionId &&
          (item.relation_type || "default") === "default"
      )
      .map((item) => state.checkpointNodes.find((node) => node.checkpoint_node_id === item.checkpoint_node_id)?.code)
  );
}

function buildTaskCheckpointPlan(defaultCheckpointCodes, task = {}) {
  const explicitOverride =
    task.checkpoint_override ||
    task.checkpointOverride ||
    (task.checkpoint_override_mode || task.checkpointOverrideMode
      ? {
          mode: task.checkpoint_override_mode || task.checkpointOverrideMode,
          checkpoint_codes:
            task.checkpoint_override_codes || task.checkpointOverrideCodes || task.checkpoint_codes || [],
        }
      : null);

  if (explicitOverride) {
    return {
      mode: String(explicitOverride.mode || "replace").toLowerCase(),
      checkpoint_codes: normalizeCheckpointCodes(explicitOverride.checkpoint_codes || []),
    };
  }

  const legacyCheckpointCodes = normalizeCheckpointCodes(task.checkpoint_codes || []);
  if (legacyCheckpointCodes.length === 0) {
    return null;
  }
  if (JSON.stringify(legacyCheckpointCodes) === JSON.stringify(defaultCheckpointCodes)) {
    return null;
  }
  return {
    mode: "replace",
    checkpoint_codes: legacyCheckpointCodes,
  };
}

function writeTaskCheckpointOverrides(
  state,
  catalogVersionId,
  taskRevisionId,
  defaultCheckpointCodes,
  task
) {
  const plan = buildTaskCheckpointPlan(defaultCheckpointCodes, task);
  if (!plan) {
    return;
  }

  const relationType = new Set(["add", "remove", "replace"]).has(plan.mode)
    ? plan.mode
    : "replace";
  const checkpointCodes =
    relationType === "remove" && plan.checkpoint_codes.length === 0
      ? defaultCheckpointCodes
      : plan.checkpoint_codes;

  for (const checkpointCode of checkpointCodes) {
    const checkpointNode = ensureCheckpointNode(state, catalogVersionId, checkpointCode, 0);
    state.taskCheckpointOverrides.push({
      override_id: makeId("task_checkpoint_override"),
      task_revision_id: taskRevisionId,
      checkpoint_node_id: checkpointNode.checkpoint_node_id,
      relation_type: relationType,
      confidence: relationType === "remove" ? 0.92 : 0.9,
      mapping_source: task.checkpoint_override || task.checkpointOverride
        ? "bundle_task_checkpoint_override"
        : "bundle_task_checkpoint_legacy",
      reason: checkpointCode,
      created_at: new Date().toISOString(),
    });
  }
}

function toRelativePath(filePath) {
  if (!filePath) return "";
  return path.relative(workspaceRoot, filePath).replace(/\\/g, "/");
}

function safeReadJson(filePath, fallback) {
  if (!fs.existsSync(filePath)) return fallback;
  try {
    const raw = fs.readFileSync(filePath, "utf8").replace(/^\uFEFF/, "");
    return JSON.parse(raw);
  } catch {
    return fallback;
  }
}

function writeJsonAtomic(filePath, payload) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  const tmpPath = `${filePath}.tmp`;
  fs.writeFileSync(tmpPath, JSON.stringify(payload, null, 2), "utf8");
  fs.renameSync(tmpPath, filePath);
}

function deepClone(value) {
  return JSON.parse(JSON.stringify(value));
}

function stableStringify(value) {
  if (value === null) return "null";
  if (typeof value === "number" || typeof value === "boolean") {
    return JSON.stringify(value);
  }
  if (typeof value === "string") {
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map((item) => stableStringify(item)).join(",")}]`;
  }
  if (typeof value === "object") {
    return `{${Object.keys(value)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${stableStringify(value[key])}`)
      .join(",")}}`;
  }
  return JSON.stringify(String(value));
}

export function computeContentHash(value) {
  return createHash("sha256").update(stableStringify(value)).digest("hex");
}

function computeHash(value) {
  return computeContentHash(value);
}

function maybeFailpoint(name) {
  if (process.env.TEST_FAILPOINT === name) {
    throw new Error(`failpoint:${name}`);
  }
}

/**
 * 在调用方读取或修改前，对所有持久化集合做归一化。
 * 这里要兼容旧快照，让本地演示数据能跨 schema 演进保留下来。
 */
export function normalizeState(state) {
  const normalized = state && typeof state === "object" ? state : createEmptyState();
  const fallback = createEmptyState();
  normalized.meta = {
    ...fallback.meta,
    ...(normalized.meta || {}),
  };

  for (const key of stateCollectionKeys) {
    if (!Array.isArray(normalized[key])) {
      normalized[key] = [];
    }
  }

  for (const artifact of normalized.artifacts) {
    // `integrity_status` controls storage integrity; rerun no longer invalidates history.
    artifact.integrity_status =
      artifact.integrity_status ||
      (artifact.lifecycle_status === "corrupt" || artifact.lifecycle_status === "deleted"
        ? artifact.lifecycle_status
        : "valid");
    artifact.logical_status =
      artifact.logical_status ||
      (artifact.lifecycle_status === "stale" ? "outdated" : "current");
    if (!artifact.lifecycle_status) {
      artifact.lifecycle_status = artifact.integrity_status;
    }
  }

  for (const lesson of normalized.lessons) {
    const lessonTrackScope = safeTrackScope(lesson);
    if (lessonTrackScope) {
      lesson.subject = lessonTrackScope.subject;
      lesson.stage = lessonTrackScope.stage;
      lesson.track_code = lessonTrackScope.track_code;
    }
    if (!lesson.published_revision_id) {
      const publishedPublication = normalized.publications.find(
        (item) => item.lesson_id === lesson.lesson_id && item.status === "published"
      );
      lesson.published_revision_id =
        publishedPublication?.lesson_revision_id ||
        (lesson.status === "published" ? lesson.active_revision_id || null : null);
    }
  }

  for (const lessonRevision of normalized.lessonRevisions) {
    lessonRevision.approval_status = lessonRevision.approval_status || "pending";
    if (!Object.prototype.hasOwnProperty.call(lessonRevision, "bundle_jsonb")) {
      lessonRevision.bundle_jsonb = null;
    }
  }

  const lessonById = new Map(normalized.lessons.map((item) => [item.lesson_id, item]));

  for (const taskSubjectExt of normalized.taskSubjectExt) {
    const taskRevision = normalized.taskRevisions.find(
      (item) => item.task_revision_id === taskSubjectExt.task_revision_id
    );
    const lessonRevision = normalized.lessonRevisions.find(
      (item) => item.lesson_revision_id === taskRevision?.lesson_revision_id
    );
    const lesson = lessonRevision ? lessonById.get(lessonRevision.lesson_id) : null;
    const trackScope = safeTrackScope({
      track_code: taskSubjectExt.track_code || taskSubjectExt.payload_json?.track_code || lesson?.track_code,
      subject: taskSubjectExt.subject || lesson?.subject,
      stage: taskSubjectExt.stage || lesson?.stage,
      grade: lesson?.grade,
    });
    const difficulty = buildDifficultyPayload(
      taskSubjectExt.payload_json || {},
      trackScope?.trackProfile,
      {
        defaultSource: "state_normalizer",
      }
    );
    taskSubjectExt.subject = trackScope?.subject || taskSubjectExt.subject || lesson?.subject || null;
    taskSubjectExt.stage = trackScope?.stage || taskSubjectExt.stage || lesson?.stage || null;
    taskSubjectExt.track_code = trackScope?.track_code || taskSubjectExt.track_code || lesson?.track_code || null;
    taskSubjectExt.plugin_id =
      taskSubjectExt.plugin_id || trackScope?.trackProfile?.plugin_id || "subject.validation.generic.v1";
    taskSubjectExt.payload_json = {
      ...(taskSubjectExt.payload_json || {}),
      track_code: taskSubjectExt.track_code,
      ...difficulty,
    };
  }

  for (const projection of normalized.taskProjections) {
    const lesson = lessonById.get(projection.lesson_id);
    const trackScope = safeTrackScope({
      track_code: projection.track_code || lesson?.track_code,
      subject: projection.subject || lesson?.subject,
      stage: projection.stage || lesson?.stage,
      grade: projection.grade || lesson?.grade,
    });
    const difficulty = buildDifficultyPayload(projection, trackScope?.trackProfile, {
      defaultSource: "state_normalizer",
    });
    projection.subject = trackScope?.subject || projection.subject || lesson?.subject || null;
    projection.stage = trackScope?.stage || projection.stage || lesson?.stage || null;
    projection.track_code = trackScope?.track_code || projection.track_code || lesson?.track_code || null;
    Object.assign(projection, difficulty);
  }

  for (const component of normalized.components) {
    if (!Object.prototype.hasOwnProperty.call(component, "current_revision_id")) {
      component.current_revision_id = null;
    }
  }

  return normalized;
}

export function createEmptyState() {
  const now = new Date().toISOString();
  return {
    meta: {
      generatedAt: now,
      updatedAt: now,
      source: "runtime_backbone_seed",
      version: "0.1",
    },
    documentSources: [],
    documents: [],
    documentGroups: [],
    documentGroupMembers: [],
    documentRelations: [],
    runs: [],
    jobs: [],
    jobAttempts: [],
    jobDependencies: [],
    outboxEvents: [],
    imports: [],
    artifacts: [],
    artifactDependencies: [],
    lessons: [],
    lessonRevisions: [],
    taskProjections: [],
    questionBankItems: [],
    questionBankItemRevisions: [],
    questionBankSourceLinks: [],
    publications: [],
    materialBuilds: [],
    materialItems: [],
    pageAssets: [],
    components: [],
    componentRevisions: [],
    componentPatchCandidates: [],
    componentLinks: [],
    sourceNodes: [],
    sourceNodeRevisions: [],
    tasks: [],
    taskRevisions: [],
    checkpointCatalogs: [],
    checkpointCatalogVersions: [],
    checkpointNodes: [],
    sourceNodeCheckpointLinks: [],
    taskCheckpointOverrides: [],
    taskSubjectExt: [],
    reviewTasks: [],
    qualityEvaluations: [],
  };
}

function loadWorkbenchData() {
  if (!fs.existsSync(workbenchDataPath)) {
    return null;
  }
  const code = fs.readFileSync(workbenchDataPath, "utf8");
  const sandbox = { window: {} };
  vm.createContext(sandbox);
  vm.runInContext(code, sandbox);
  return sandbox.window.WORKBENCH_DATA;
}

function loadThreeTrackSeedBundles() {
  return threeTrackSeedFixturePaths.map((fixturePath) => {
    const bundle = safeReadJson(fixturePath, null);
    if (!bundle) {
      throw new Error(`seed_fixture_missing:${path.relative(workspaceRoot, fixturePath).replace(/\\/g, "/")}`);
    }
    return {
      ...deepClone(bundle),
      bundle_id: `seed_${bundle.track_code}_bundle`,
      lesson_id: `seed_${bundle.track_code}_lesson`,
      title: `${bundle.title || bundle.lesson_id} [seed]`,
    };
  });
}

function buildFixtureSeedState(state) {
  // Clean clones do not carry local outputs/, so the runtime must be able to
  // bootstrap from committed validation fixtures instead of demo-only artifacts.
  for (const bundle of loadThreeTrackSeedBundles()) {
    const imported = importLessonDraftBundle(state, {
      actor: "seed_loader",
      bundle,
    });
    updateReviewTaskStatus(state, imported.reviewTaskId, "approve", "seed_reviewer");
    publishLessonRevision(state, imported.lessonId, "seed_publisher", {
      lessonRevisionId: imported.lessonRevisionId,
    });
  }
  return state;
}

function buildCatalogNodeIndex(state) {
  const index = new Map();
  for (const node of state.checkpointNodes) {
    index.set(`${node.catalog_version_id}|${node.name}`, node);
  }
  return index;
}

function ensureCatalog(state, splitLesson) {
  const key = `${splitLesson.subject}|${splitLesson.stage}|${splitLesson.grade}`;
  let catalog = state.checkpointCatalogs.find((item) => item.key === key);
  if (!catalog) {
    catalog = {
      catalog_id: makeId("catalog"),
      key,
      subject: splitLesson.subject,
      scope_type: `${splitLesson.stage}_${splitLesson.grade}`,
      status: "active",
      created_at: new Date().toISOString(),
    };
    state.checkpointCatalogs.push(catalog);
    state.checkpointCatalogVersions.push({
      catalog_version_id: makeId("catalog_version"),
      catalog_id: catalog.catalog_id,
      version_no: 1,
      status: "published",
      base_version_id: null,
      overlay_ref: null,
      published_at: new Date().toISOString(),
      created_at: new Date().toISOString(),
    });
  }
  return {
    catalog,
    version: state.checkpointCatalogVersions.find((item) => item.catalog_id === catalog.catalog_id && item.version_no === 1),
  };
}

function ensureCheckpointNode(state, catalogVersionId, name, orderIndex = 0) {
  const existing = state.checkpointNodes.find(
    (item) => item.catalog_version_id === catalogVersionId && item.name === name
  );
  if (existing) return existing;
  const node = {
    checkpoint_node_id: makeId("checkpoint_node"),
    catalog_version_id: catalogVersionId,
    parent_id: null,
    code: slug(name),
    name,
    node_kind: "knowledge_point",
    order_index: orderIndex,
    created_at: new Date().toISOString(),
  };
  state.checkpointNodes.push(node);
  return node;
}

function createImportRun(state, lesson, lessonRevisionId) {
  const runId = makeId("run");
  const jobIds = {
    ingest: makeId("job"),
    component: makeId("job"),
    tree: makeId("job"),
    task: makeId("job"),
    subject: makeId("job"),
    checkpoint: makeId("job"),
    gate: makeId("job"),
  };

  state.runs.push({
    run_id: runId,
    run_type: "import_lesson",
    root_target_type: "lesson",
    root_target_id: lesson.lesson_id,
    subject: lesson.subject,
    lane: "night-batch",
    status: "published",
    triggered_by: "seed_loader",
    started_at: new Date().toISOString(),
    finished_at: new Date().toISOString(),
  });

  const jobSpecs = [
    [jobIds.ingest, "page_ingest", "vision", "L", 20],
    [jobIds.component, "component_split", "vision", "L", 30],
    [jobIds.tree, "source_tree_build", "structure", "M", 40],
    [jobIds.task, "task_extract", "task-extraction", "M", 50],
    [jobIds.subject, "subject_enrich", `subject.${slug(lesson.subject)}`, "M", 60],
    [jobIds.checkpoint, "checkpoint_suggest", "checkpoint", "M", 70],
    [jobIds.gate, "quality_gate", "export", "S", 80],
  ];

  for (const [jobId, jobType, capability, resourceClass, priority] of jobSpecs) {
    state.jobs.push({
      job_id: jobId,
      run_id: runId,
      job_type: jobType,
      lane: "night-batch",
      capability,
      resource_class: resourceClass,
      priority,
      idempotency_key: `${lesson.lesson_id}:${lessonRevisionId}:${jobType}`,
      status: "succeeded",
      attempt_count: 1,
      max_attempts: 3,
      lease_expires_at: null,
      heartbeat_at: null,
      timeout_at: null,
      cancel_requested_at: null,
      next_retry_at: null,
      error_code: null,
      error_detail_ref: null,
      payload_ref: `${lesson.lesson_id}/${jobType}.json`,
      result_artifact_id: null,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    });
  }

  const dependencies = [
    [jobIds.ingest, jobIds.component, "finishes_before"],
    [jobIds.component, jobIds.tree, "finishes_before"],
    [jobIds.component, jobIds.task, "finishes_before"],
    [jobIds.tree, jobIds.task, "requires_structure"],
    [jobIds.task, jobIds.subject, "requires_tasks"],
    [jobIds.subject, jobIds.checkpoint, "requires_subject_enrichment"],
    [jobIds.tree, jobIds.checkpoint, "requires_structure"],
    [jobIds.subject, jobIds.gate, "quality_input"],
    [jobIds.checkpoint, jobIds.gate, "quality_input"],
  ];

  for (const [upstream, downstream, dependencyType] of dependencies) {
    state.jobDependencies.push({
      job_dependency_id: makeId("job_dep"),
      upstream_job_id: upstream,
      downstream_job_id: downstream,
      dependency_type: dependencyType,
      created_at: new Date().toISOString(),
    });
  }

  state.outboxEvents.push({
    outbox_event_id: makeId("outbox"),
    aggregate_type: "run",
    aggregate_id: runId,
    event_type: "run_seeded",
    payload_json: {
      lesson_id: lesson.lesson_id,
      lesson_revision_id: lessonRevisionId,
    },
    status: "dispatched",
    created_at: new Date().toISOString(),
    dispatched_at: new Date().toISOString(),
  });

  return { runId, jobIds };
}

function createArtifact(state, lesson, runId, jobId, artifactType, summaryJson, dependencies = []) {
  const artifact = {
    artifact_id: makeId("artifact"),
    run_id: runId,
    job_id: jobId,
    artifact_type: artifactType,
    schema_version: "0.1",
    producer_name: "runtime_backbone_seed",
    producer_version: "0.1",
    model_version: null,
    prompt_hash: null,
    plugin_version: null,
    storage_uri: `runtime_backbone/${lesson.lesson_id}/${artifactType}.json`,
    content_hash: null,
    summary_json: summaryJson,
    supersedes_artifact_id: null,
    integrity_status: "valid",
    logical_status: "current",
    lifecycle_status: "valid",
    created_at: new Date().toISOString(),
  };
  state.artifacts.push(artifact);

  for (const parentArtifactId of dependencies) {
    state.artifactDependencies.push({
      artifact_dependency_id: makeId("artifact_dep"),
      parent_artifact_id: parentArtifactId,
      child_artifact_id: artifact.artifact_id,
      dependency_type: "derived_from",
      created_at: new Date().toISOString(),
    });
  }

  const job = state.jobs.find((item) => item.job_id === jobId);
  if (job) job.result_artifact_id = artifact.artifact_id;
  return artifact;
}

function createQuestionComponent(state, pageAsset, question) {
  const width = Number(question.visualStats?.width || 0);
  const height = Number(question.visualStats?.height || 0);
  const cropArtifact = {
    artifact_id: makeId("artifact"),
    run_id: null,
    job_id: null,
    artifact_type: "question_crop",
    schema_version: "0.1",
    producer_name: "visual_split_seed",
    producer_version: "0.1",
    model_version: null,
    prompt_hash: null,
    plugin_version: null,
    storage_uri: toRelativePath(question.cropPath),
    content_hash: null,
    summary_json: {
      question_id: question.id,
      source_page: question.sourcePage,
    },
    supersedes_artifact_id: null,
    lifecycle_status: "valid",
    created_at: new Date().toISOString(),
  };
  state.artifacts.push(cropArtifact);

  const component = {
    component_id: makeId("component"),
    page_asset_id: pageAsset.page_asset_id,
    parent_component_id: null,
    component_type: question.componentKind || "question_crop",
    bbox_json: {
      x: 0,
      y: 0,
      width,
      height,
    },
    reading_order: question.order || 0,
    crop_artifact_id: cropArtifact.artifact_id,
    content_hash: null,
    schema_version: "0.1",
    extraction_confidence: question.risk === "高风险" ? 0.65 : question.risk === "中风险" ? 0.82 : 0.95,
    status: question.auditStatus === "PASS_BY_VISUAL_GATE" ? "ready" : "needs_review",
    created_at: new Date().toISOString(),
  };
  state.components.push(component);
  return component;
}

function createPageAsset(state, documentId, pageNo) {
  const existing = state.pageAssets.find(
    (item) => item.document_id === documentId && item.page_no === pageNo
  );
  if (existing) return existing;
  const artifactBase = `${documentId}/page_${String(pageNo).padStart(3, "0")}`;
  const imageArtifact = {
    artifact_id: makeId("artifact"),
    run_id: null,
    job_id: null,
    artifact_type: "page_image",
    schema_version: "0.1",
    producer_name: "visual_split_seed",
    producer_version: "0.1",
    model_version: null,
    prompt_hash: null,
    plugin_version: null,
    storage_uri: `${artifactBase}.png`,
    content_hash: null,
    summary_json: { page_no: pageNo },
    supersedes_artifact_id: null,
    lifecycle_status: "valid",
    created_at: new Date().toISOString(),
  };
  const ocrArtifact = {
    artifact_id: makeId("artifact"),
    run_id: null,
    job_id: null,
    artifact_type: "page_ocr",
    schema_version: "0.1",
    producer_name: "visual_split_seed",
    producer_version: "0.1",
    model_version: null,
    prompt_hash: null,
    plugin_version: null,
    storage_uri: `${artifactBase}.ocr.json`,
    content_hash: null,
    summary_json: { page_no: pageNo },
    supersedes_artifact_id: null,
    lifecycle_status: "valid",
    created_at: new Date().toISOString(),
  };
  const layoutArtifact = {
    artifact_id: makeId("artifact"),
    run_id: null,
    job_id: null,
    artifact_type: "page_layout",
    schema_version: "0.1",
    producer_name: "visual_split_seed",
    producer_version: "0.1",
    model_version: null,
    prompt_hash: null,
    plugin_version: null,
    storage_uri: `${artifactBase}.layout.json`,
    content_hash: null,
    summary_json: { page_no: pageNo },
    supersedes_artifact_id: null,
    lifecycle_status: "valid",
    created_at: new Date().toISOString(),
  };
  state.artifacts.push(imageArtifact, ocrArtifact, layoutArtifact);

  const pageAsset = {
    page_asset_id: makeId("page"),
    document_id: documentId,
    page_no: pageNo,
    width: null,
    height: null,
    image_artifact_id: imageArtifact.artifact_id,
    ocr_artifact_id: ocrArtifact.artifact_id,
    layout_artifact_id: layoutArtifact.artifact_id,
    status: "ready",
    created_at: new Date().toISOString(),
  };
  state.pageAssets.push(pageAsset);
  return pageAsset;
}

/**
 * 根据拆分输出构建初始课时图：课时版本、任务、组件和审阅队列链接。
 * 这是后续变更流程默认已存在的播种路径。
 */
function buildLessonSeed(state, splitLesson, reviewQueue) {
  const trackScope = normalizeTrackScope(splitLesson);
  const { trackProfile } = trackScope;
  const lessonId = splitLesson.lesson_id;
  const documentSourceId = makeId("source");
  state.documentSources.push({
    source_id: documentSourceId,
    source_type: "mock_workbench_seed",
    subject: trackScope.subject,
    owner_id: "codex",
    import_batch_id: "runtime_backbone_seed",
    metadata_json: {
      lesson_id: lessonId,
    },
    created_at: new Date().toISOString(),
  });

  const documentId = makeId("document");
  const documentGroupId = makeId("docgroup");
  state.documents.push({
    document_id: documentId,
    source_id: documentSourceId,
    subject: trackScope.subject,
    stage: trackScope.stage,
    grade: splitLesson.grade,
    season: splitLesson.season,
    doc_role: "teacher_handout",
    title: splitLesson.source_pdf_name || splitLesson.lesson_title,
    storage_uri: toRelativePath(splitLesson.source_pdf_path),
    checksum: null,
    page_count: splitLesson.page_count || null,
    status: "ready",
    metadata_json: {
      lesson_id: lessonId,
      parse_status: splitLesson.parse_status,
    },
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  });
  state.documentGroups.push({
    document_group_id: documentGroupId,
    subject: trackScope.subject,
    group_type: "lesson_source_set",
    label: splitLesson.lesson_title,
    status: "active",
    metadata_json: {
      lesson_id: lessonId,
    },
    created_at: new Date().toISOString(),
  });
  state.documentGroupMembers.push({
    document_group_member_id: makeId("docgroup_member"),
    document_group_id: documentGroupId,
    document_id: documentId,
    member_role: "teacher_handout",
    sort_index: 1,
    created_at: new Date().toISOString(),
  });

  const lessonRevisionId = `${lessonId}:rev:1`;
  const lesson = {
    lesson_id: lessonId,
    document_group_id: documentGroupId,
    subject: trackScope.subject,
    stage: trackScope.stage,
    track_code: trackScope.track_code,
    grade: splitLesson.grade,
    season: splitLesson.season,
    title: splitLesson.lesson_title,
    active_revision_id: lessonRevisionId,
    published_revision_id: lessonRevisionId,
    status: "published",
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };
  state.lessons.push(lesson);
  state.lessonRevisions.push({
    lesson_revision_id: lessonRevisionId,
    lesson_id: lessonId,
    base_artifact_id: null,
    generated_snapshot_ref: `${lessonId}/generated_snapshot.json`,
    manual_patch_ref: null,
    merged_snapshot_ref: `${lessonId}/merged_snapshot.json`,
    revision_no: 1,
    status: "published",
    created_by: "seed_loader",
    created_at: new Date().toISOString(),
  });

  const { version } = ensureCatalog(state, {
    subject: trackScope.subject,
    stage: trackScope.stage,
    grade: splitLesson.grade,
  });
  const rootCatalogNode = ensureCheckpointNode(
    state,
    version.catalog_version_id,
    splitLesson.lesson_title,
    0
  );
  rootCatalogNode.node_kind = "lesson_topic";

  const { runId, jobIds } = createImportRun(state, lesson, lessonRevisionId);

  const ingestArtifact = createArtifact(state, lesson, runId, jobIds.ingest, "page_ocr_artifact", {
    lesson_id: lessonId,
    page_count: splitLesson.page_count,
  });
  const componentArtifact = createArtifact(
    state,
    lesson,
    runId,
    jobIds.component,
    "component_bundle",
    {
      lesson_id: lessonId,
      segment_count: splitLesson.segment_count || 0,
    },
    [ingestArtifact.artifact_id]
  );

  const rootSourceNodeId = `${lessonId}:node:root`;
  const rootSourceNodeRevisionId = `${rootSourceNodeId}:rev:1`;
  state.sourceNodes.push({
    source_node_id: rootSourceNodeId,
    lesson_id: lessonId,
    stable_code: "root",
    current_revision_id: rootSourceNodeRevisionId,
    created_at: new Date().toISOString(),
  });
  state.sourceNodeRevisions.push({
    source_node_revision_id: rootSourceNodeRevisionId,
    source_node_id: rootSourceNodeId,
    lesson_revision_id: lessonRevisionId,
    parent_node_revision_id: null,
    node_type: "lesson",
    phase: "knowledge_main",
    title: splitLesson.lesson_title,
    order_index: 0,
    page_span: null,
    component_bundle_ref: componentArtifact.artifact_id,
    generated_data_ref: `${lessonId}/source_tree/root.json`,
    manual_patch_ref: null,
    merged_data_ref: `${lessonId}/source_tree/root_merged.json`,
    status: "published",
    created_at: new Date().toISOString(),
  });

  const sourceNodeByCheckpoint = new Map();
  let nodeOrder = 1;
  for (const module of splitLesson.tree || []) {
    const moduleNodeId = `${lessonId}:node:module:${slug(module.module)}`;
    const moduleNodeRevisionId = `${moduleNodeId}:rev:1`;
    state.sourceNodes.push({
      source_node_id: moduleNodeId,
      lesson_id: lessonId,
      stable_code: `module:${slug(module.module)}`,
      current_revision_id: moduleNodeRevisionId,
      created_at: new Date().toISOString(),
    });
    state.sourceNodeRevisions.push({
      source_node_revision_id: moduleNodeRevisionId,
      source_node_id: moduleNodeId,
      lesson_revision_id: lessonRevisionId,
      parent_node_revision_id: rootSourceNodeRevisionId,
      node_type: "knowledge_block",
      phase: "knowledge_main",
      title: module.module,
      order_index: nodeOrder++,
      page_span: null,
      component_bundle_ref: componentArtifact.artifact_id,
      generated_data_ref: `${lessonId}/source_tree/${slug(module.module)}.json`,
      manual_patch_ref: null,
      merged_data_ref: `${lessonId}/source_tree/${slug(module.module)}_merged.json`,
      status: "published",
      created_at: new Date().toISOString(),
    });

    for (const item of module.items || []) {
      const checkpointName = String(item || "").trim();
      const checkpointNodeId = `${lessonId}:node:checkpoint:${slug(checkpointName)}`;
      const checkpointNodeRevisionId = `${checkpointNodeId}:rev:1`;
      if (!state.sourceNodes.some((node) => node.source_node_id === checkpointNodeId)) {
        state.sourceNodes.push({
          source_node_id: checkpointNodeId,
          lesson_id: lessonId,
          stable_code: `checkpoint:${slug(checkpointName)}`,
          current_revision_id: checkpointNodeRevisionId,
          created_at: new Date().toISOString(),
        });
        state.sourceNodeRevisions.push({
          source_node_revision_id: checkpointNodeRevisionId,
          source_node_id: checkpointNodeId,
          lesson_revision_id: lessonRevisionId,
          parent_node_revision_id: moduleNodeRevisionId,
          node_type: "exam_point",
          phase: "knowledge_main",
          title: checkpointName,
          order_index: nodeOrder++,
          page_span: null,
          component_bundle_ref: componentArtifact.artifact_id,
          generated_data_ref: `${lessonId}/source_tree/${slug(checkpointName)}.json`,
          manual_patch_ref: null,
          merged_data_ref: `${lessonId}/source_tree/${slug(checkpointName)}_merged.json`,
          status: "published",
          created_at: new Date().toISOString(),
        });
      }
      sourceNodeByCheckpoint.set(checkpointName, checkpointNodeRevisionId);
      const checkpointNode = ensureCheckpointNode(
        state,
        version.catalog_version_id,
        checkpointName,
        nodeOrder
      );
      state.sourceNodeCheckpointLinks.push({
        link_id: makeId("checkpoint_link"),
        source_node_revision_id: checkpointNodeRevisionId,
        checkpoint_node_id: checkpointNode.checkpoint_node_id,
        relation_type: "default",
        confidence: 0.95,
        mapping_source: "seed_tree",
        created_at: new Date().toISOString(),
      });
    }
  }

  const sourceTreeArtifact = createArtifact(
    state,
    lesson,
    runId,
    jobIds.tree,
    "source_tree_snapshot",
    {
      lesson_id: lessonId,
      node_count: state.sourceNodeRevisions.filter((item) => item.lesson_revision_id === lessonRevisionId).length,
    },
    [componentArtifact.artifact_id]
  );
  state.lessonRevisions.find((item) => item.lesson_revision_id === lessonRevisionId).base_artifact_id =
    sourceTreeArtifact.artifact_id;

  const uniquePages = new Set();
  for (const question of splitLesson.questions || []) {
    for (const pageNo of question.visualPages || [question.sourcePage]) {
      if (pageNo) uniquePages.add(pageNo);
    }
  }
  const pageAssetByPage = new Map();
  for (const pageNo of [...uniquePages].sort((a, b) => a - b)) {
    pageAssetByPage.set(pageNo, createPageAsset(state, documentId, pageNo));
  }

  let taskCount = 0;
  for (const question of splitLesson.questions || []) {
    const checkpointName = parseCheckpointName(question.checkpoint);
    const sourceNodeRevisionId = sourceNodeByCheckpoint.get(checkpointName) || rootSourceNodeRevisionId;
    const difficulty = buildDifficultyPayload(
      {
        difficulty_level: question.risk,
        difficulty_source: "visual_seed",
        difficulty_confidence:
          question.risk === "低风险" ? 0.9 : question.risk === "中风险" ? 0.75 : 0.6,
      },
      trackProfile,
      {
        defaultSource: "visual_seed",
      }
    );
    const taskId = `${lessonId}:task:${question.id}`;
    const taskRevisionId = `${taskId}:rev:1`;
    state.tasks.push({
      task_id: taskId,
      lesson_id: lessonId,
      stable_question_no: question.id,
      current_revision_id: taskRevisionId,
      created_at: new Date().toISOString(),
    });
    state.taskRevisions.push({
      task_revision_id: taskRevisionId,
      task_id: taskId,
      lesson_revision_id: lessonRevisionId,
      source_node_revision_id: sourceNodeRevisionId,
      student_stem: question.trustedText || question.previewShort,
      teacher_stem: question.ocrTextRaw || question.previewText,
      answer: question.ocrTextRaw?.includes("【答案】") ? question.ocrTextRaw.split("【答案】")[1].split("【分析】")[0].trim() : null,
      explanation: question.reviewNote || null,
      visibility: question.versionTags?.includes("基础版") ? "student_basic" : "student_standard",
      generated_data_ref: `${lessonId}/tasks/${question.id}.generated.json`,
      manual_patch_ref: null,
      merged_data_ref: `${lessonId}/tasks/${question.id}.merged.json`,
      status: question.auditStatus === "PASS_BY_VISUAL_GATE" ? "published" : "reviewing",
      created_at: new Date().toISOString(),
    });

    const pageAsset = pageAssetByPage.get(question.sourcePage) || pageAssetByPage.values().next().value;
    const component = createQuestionComponent(state, pageAsset, question);
    state.componentLinks.push({
      component_link_id: makeId("component_link"),
      component_id: component.component_id,
      target_type: "task_revision",
      target_revision_id: taskRevisionId,
      relation_type: "primary_visual_crop",
      created_at: new Date().toISOString(),
    });

    state.taskSubjectExt.push({
      task_revision_id: taskRevisionId,
      subject: trackScope.subject,
      stage: trackScope.stage,
      track_code: trackScope.track_code,
      plugin_id: trackProfile.plugin_id,
      plugin_version: "0.1",
      schema_version: "0.1",
      payload_json: {
        track_code: trackScope.track_code,
        checkpoint: question.checkpoint,
        component_kind: question.componentKind,
        component_label: question.componentLabel,
        local_number: question.localNumber,
        source_page: question.sourcePage,
        text_storage_mode: question.textStorageMode,
        review_status: question.reviewStatus,
        risk: question.risk,
        tags: question.versionTags || [],
        // Task subject ext is the per-revision fact row that survives reruns, so
        // we persist the source refs contract here instead of reconstructing it later.
        source_refs_json: {
          component_id: component.component_id,
          page_no: pageAsset?.page_no || question.sourcePage || null,
          crop_artifact_id: component.crop_artifact_id || null,
          bbox: deepClone(component.bbox_json || null),
        },
        ...difficulty,
        visual_stats: question.visualStats || {},
      },
      risk_flags: question.riskIssues || [],
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    });

    const queueItem = reviewQueue.find((item) => item.questionId === question.id);
    if (queueItem || question.risk !== "低风险") {
      state.reviewTasks.push({
        // Seed review queue ids repeat across lessons, so we scope them by lesson.
        review_task_id: queueItem ? `${lessonId}:${queueItem.id}` : makeId("review_task"),
        target_type: "task_revision",
        target_revision_id: taskRevisionId,
        run_id: runId,
        status: queueItem?.status === "复核中" ? "in_review" : "pending",
        assigned_to: null,
        requested_by: "visual_gate",
        changes_summary: queueItem?.title || question.reviewNote || question.storageNote,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      });
    }
    taskCount += 1;
  }

  const taskBundleArtifact = createArtifact(
    state,
    lesson,
    runId,
    jobIds.task,
    "task_bundle",
    {
      lesson_id: lessonId,
      task_count: taskCount,
    },
    [sourceTreeArtifact.artifact_id, componentArtifact.artifact_id]
  );
  const subjectArtifact = createArtifact(
    state,
    lesson,
    runId,
    jobIds.subject,
    "subject_enrichment_artifact",
    {
      lesson_id: lessonId,
      subject_ext_count: taskCount,
    },
    [taskBundleArtifact.artifact_id]
  );
  const checkpointArtifact = createArtifact(
    state,
    lesson,
    runId,
    jobIds.checkpoint,
    "checkpoint_candidate_artifact",
    {
      lesson_id: lessonId,
      checkpoint_count: state.taskCheckpointOverrides.filter((item) => item.task_revision_id.startsWith(`${lessonId}:task:`)).length,
    },
    [sourceTreeArtifact.artifact_id, subjectArtifact.artifact_id]
  );
  createArtifact(
    state,
    lesson,
    runId,
    jobIds.gate,
    "reviewed_publishable_bundle",
    {
      lesson_id: lessonId,
      review_task_count: state.reviewTasks.filter((item) => item.target_revision_id.startsWith(`${lessonId}:task:`)).length,
    },
    [subjectArtifact.artifact_id, checkpointArtifact.artifact_id]
  );

  const reviewTaskCount = state.reviewTasks.filter((item) => item.target_revision_id.startsWith(`${lessonId}:task:`)).length;
  const qualityRows = [
    ["Q0_pairing", "info", true, 100],
    ["Q1_structure", "info", true, 96],
    ["Q2_visual_gate", reviewTaskCount ? "warning" : "info", reviewTaskCount === 0, reviewTaskCount ? 78 : 94],
    ["Q3_task_binding", "info", true, 92],
  ];
  for (const [checkCode, severity, passed, score] of qualityRows) {
    state.qualityEvaluations.push({
      quality_evaluation_id: makeId("quality"),
      target_type: "lesson_revision",
      target_revision_id: lessonRevisionId,
      rule_set_version: "runtime_backbone_seed_v0.1",
      check_code: checkCode,
      severity,
      score,
      passed,
      evidence_ref: `${lessonId}/quality/${checkCode}.json`,
      evaluated_at: new Date().toISOString(),
    });
  }
}

function getCheckpointCodesForTaskRevision(state, taskRevisionId) {
  const taskRevision = state.taskRevisions.find((item) => item.task_revision_id === taskRevisionId);
  const inherited = new Set(
    taskRevision
      ? getDefaultCheckpointCodesForSourceNodeRevision(state, taskRevision.source_node_revision_id)
      : []
  );
  const overrides = state.taskCheckpointOverrides.filter((item) => item.task_revision_id === taskRevisionId);

  const replaceCodes = normalizeCheckpointCodes(
    overrides
      .filter((item) => ["replace", "main"].includes(item.relation_type || "replace"))
      .map((item) => state.checkpointNodes.find((node) => node.checkpoint_node_id === item.checkpoint_node_id)?.code)
  );
  if (replaceCodes.length > 0) {
    return replaceCodes;
  }

  const addCodes = normalizeCheckpointCodes(
    overrides
      .filter((item) => (item.relation_type || "replace") === "add")
      .map((item) => state.checkpointNodes.find((node) => node.checkpoint_node_id === item.checkpoint_node_id)?.code)
  );
  for (const code of addCodes) {
    inherited.add(code);
  }

  const removeCodes = normalizeCheckpointCodes(
    overrides
      .filter((item) => (item.relation_type || "replace") === "remove")
      .map((item) => state.checkpointNodes.find((node) => node.checkpoint_node_id === item.checkpoint_node_id)?.code)
  );
  for (const code of removeCodes) {
    inherited.delete(code);
  }

  return [...inherited];
}

function buildCheckpointOverridePayloadForTaskRevision(state, taskRevisionId) {
  const overrides = state.taskCheckpointOverrides.filter((item) => item.task_revision_id === taskRevisionId);
  if (!overrides.length) {
    return null;
  }

  const replaceCodes = normalizeCheckpointCodes(
    overrides
      .filter((item) => ["replace", "main"].includes(item.relation_type || "replace"))
      .map((item) => state.checkpointNodes.find((node) => node.checkpoint_node_id === item.checkpoint_node_id)?.code)
  );
  if (replaceCodes.length > 0) {
    return {
      mode: "replace",
      checkpoint_codes: replaceCodes,
    };
  }

  const addCodes = normalizeCheckpointCodes(
    overrides
      .filter((item) => (item.relation_type || "replace") === "add")
      .map((item) => state.checkpointNodes.find((node) => node.checkpoint_node_id === item.checkpoint_node_id)?.code)
  );
  if (addCodes.length > 0) {
    return {
      mode: "add",
      checkpoint_codes: addCodes,
    };
  }

  const removeCodes = normalizeCheckpointCodes(
    overrides
      .filter((item) => (item.relation_type || "replace") === "remove")
      .map((item) => state.checkpointNodes.find((node) => node.checkpoint_node_id === item.checkpoint_node_id)?.code)
  );
  if (removeCodes.length > 0) {
    return {
      mode: "remove",
      checkpoint_codes: removeCodes,
    };
  }
  return null;
}

function buildLessonDraftBundle(state, lessonRevisionId) {
  const lessonRevision = state.lessonRevisions.find((item) => item.lesson_revision_id === lessonRevisionId);
  if (!lessonRevision) return null;
  const lesson = state.lessons.find((item) => item.lesson_id === lessonRevision.lesson_id);
  if (!lesson) return null;

  const sourceNodeRevisions = state.sourceNodeRevisions.filter(
    (item) => item.lesson_revision_id === lessonRevisionId
  );
  const taskRevisions = state.taskRevisions.filter((item) => item.lesson_revision_id === lessonRevisionId);
  const taskRevisionIdSet = new Set(taskRevisions.map((item) => item.task_revision_id));
  const taskIds = new Set(taskRevisions.map((item) => item.task_id));
  const taskById = new Map(
    state.tasks.filter((item) => taskIds.has(item.task_id)).map((item) => [item.task_id, item])
  );
  const sourceNodeById = new Map(state.sourceNodes.map((item) => [item.source_node_id, item]));
  const sourceNodeRevisionById = new Map(
    sourceNodeRevisions.map((item) => [item.source_node_revision_id, item])
  );
  const pageAssetById = new Map(state.pageAssets.map((item) => [item.page_asset_id, item]));
  const componentById = new Map(state.components.map((item) => [item.component_id, item]));
  const componentRevisionById = new Map(
    state.componentRevisions.map((item) => [item.component_revision_id, item])
  );

  const tasks = taskRevisions.map((taskRevision) => {
    const task = taskById.get(taskRevision.task_id);
    const taskSubjectExt = state.taskSubjectExt.find(
      (item) => item.task_revision_id === taskRevision.task_revision_id
    );
    const componentLink = state.componentLinks.find(
      (item) =>
        item.target_type === "task_revision" &&
        item.target_revision_id === taskRevision.task_revision_id &&
        item.relation_type === "primary_visual_crop"
    );
    const component = componentLink ? componentById.get(componentLink.component_id) : null;
    const pageAsset = component ? pageAssetById.get(component.page_asset_id) : null;
    const componentRevision = component?.current_revision_id
      ? componentRevisionById.get(component.current_revision_id) ||
        state.componentRevisions.find(
          (item) =>
            item.component_id === component.component_id &&
            item.source_task_revision_id === taskRevision.task_revision_id
        ) ||
        null
      : null;
    const difficulty = buildDifficultyPayload(
      taskSubjectExt?.payload_json || {},
      safeTrackScope(lesson)?.trackProfile || null,
      {
        defaultSource: "bundle_export",
      }
    );
    return {
      local_task_id: task?.stable_question_no || taskRevision.task_id,
      task_revision_id: taskRevision.task_revision_id,
      source_node_local_id:
        sourceNodeById.get(sourceNodeRevisionById.get(taskRevision.source_node_revision_id)?.source_node_id)?.stable_code ||
        taskRevision.source_node_revision_id,
      question_type: taskSubjectExt?.payload_json?.component_kind || "question",
      stem: taskRevision.student_stem || taskRevision.teacher_stem || "",
      answer: taskRevision.answer || "",
      explanation: taskRevision.explanation || "",
      ...difficulty,
      checkpoint_codes: getCheckpointCodesForTaskRevision(state, taskRevision.task_revision_id),
      checkpoint_override: buildCheckpointOverridePayloadForTaskRevision(
        state,
        taskRevision.task_revision_id
      ),
      subject_tags: taskSubjectExt?.payload_json?.tags || [],
      source_refs_json: mergeTaskRuntimeSourceRefs(
        readPersistedTaskSourceRefs(taskSubjectExt, componentRevision),
        component,
        pageAsset
      ),
    };
  });

  const components = state.componentLinks
    .filter(
      (item) =>
        item.target_type === "task_revision" &&
        taskRevisionIdSet.has(item.target_revision_id)
    )
    .map((item) => {
      const component = componentById.get(item.component_id);
      const pageAsset = component ? pageAssetById.get(component.page_asset_id) : null;
      return {
        component_id: component?.component_id || item.component_id,
        current_revision_id: component?.current_revision_id || null,
        target_revision_id: item.target_revision_id,
        relation_type: item.relation_type,
        page_no: pageAsset?.page_no || null,
        bbox: component?.bbox_json || null,
        crop_artifact_id: component?.crop_artifact_id || null,
      };
    });

  return {
    bundle_id: `${lessonRevision.lesson_id}:${lessonRevision.revision_no}`,
    lesson_id: lesson.lesson_id,
    lesson_revision_id: lessonRevisionId,
    subject: lesson.subject,
    stage: lesson.stage,
    track_code: lesson.track_code || null,
    grade: lesson.grade,
    season: lesson.season,
    title: lesson.title,
    source_tree: sourceNodeRevisions.map((item) => ({
      source_node_revision_id: item.source_node_revision_id,
      source_node_local_id: sourceNodeById.get(item.source_node_id)?.stable_code || item.source_node_id,
      parent_source_node_revision_id: item.parent_node_revision_id,
      node_type: item.node_type,
      phase: item.phase,
      title: item.title,
      order_index: item.order_index,
      checkpoint_codes: getDefaultCheckpointCodesForSourceNodeRevision(
        state,
        item.source_node_revision_id
      ),
    })),
    tasks,
    components,
    checkpoint_candidates: sourceNodeRevisions
      .filter((item) => item.node_type === "exam_point")
      .map((item) => ({
        source_node_revision_id: item.source_node_revision_id,
        title: item.title,
      })),
    subject_extensions: state.taskSubjectExt
      .filter((item) => taskRevisionIdSet.has(item.task_revision_id))
      .map((item) => ({
        task_revision_id: item.task_revision_id,
        payload_json: item.payload_json,
      })),
    quality_issues: state.qualityEvaluations
      .filter(
        (item) =>
          item.target_type === "lesson_revision" && item.target_revision_id === lessonRevisionId
      )
      .map((item) => ({
        check_code: item.check_code,
        severity: item.severity,
        passed: item.passed,
        score: item.score,
        evidence_ref: item.evidence_ref,
      })),
  };
}

function syncLessonRevisionBundle(state, lessonRevisionId) {
  const lessonRevision = state.lessonRevisions.find((item) => item.lesson_revision_id === lessonRevisionId);
  if (!lessonRevision) return null;
  const bundle = buildLessonDraftBundle(state, lessonRevisionId);
  lessonRevision.bundle_jsonb = {
    ...(lessonRevision.bundle_jsonb || {}),
    ...(bundle || {}),
  };
  lessonRevision.content_hash = lessonRevision.bundle_jsonb
    ? computeHash(lessonRevision.bundle_jsonb)
    : null;
  return lessonRevision.bundle_jsonb;
}

function syncTaskProjectionForRevision(state, lessonRevisionId) {
  const lessonRevision = state.lessonRevisions.find((item) => item.lesson_revision_id === lessonRevisionId);
  const lesson = lessonRevision
    ? state.lessons.find((item) => item.lesson_id === lessonRevision.lesson_id)
    : null;
  if (!lessonRevision || !lesson) return;

  const bundle = lessonRevision.bundle_jsonb || syncLessonRevisionBundle(state, lessonRevisionId);
  state.taskProjections = state.taskProjections.filter(
    (item) => item.lesson_revision_id !== lessonRevisionId
  );

  for (const task of bundle?.tasks || []) {
    const difficulty = buildDifficultyPayload(task, safeTrackScope(lesson)?.trackProfile || null, {
      defaultSource: "task_projection_sync",
    });
    const searchText = [
      task.stem,
      task.answer,
      task.explanation,
      ...(task.checkpoint_codes || []),
      ...(task.subject_tags || []),
    ]
      .filter(Boolean)
      .join(" ");
    state.taskProjections.push({
      task_projection_id: `${lessonRevisionId}:${task.local_task_id}`,
      lesson_id: lesson.lesson_id,
      lesson_revision_id: lessonRevisionId,
      local_task_id: task.local_task_id,
      source_node_local_id: task.source_node_local_id,
      subject: lesson.subject,
      stage: lesson.stage,
      track_code: lesson.track_code || null,
      grade: lesson.grade,
      question_type: task.question_type,
      stem: task.stem,
      answer: task.answer,
      explanation: task.explanation,
      ...difficulty,
      checkpoint_codes: task.checkpoint_codes || [],
      subject_tags: task.subject_tags || [],
      source_refs_json: task.source_refs_json || {},
      content_hash: computeHash(task),
      search_text: searchText,
      search_vector: searchText,
      created_at: lessonRevision.created_at,
    });
  }
}

function syncSeedPublication(state, lesson) {
  if (!lesson?.published_revision_id) return;
  if (state.publications.some((item) => item.lesson_revision_id === lesson.published_revision_id)) {
    return;
  }
  state.publications.push({
    publication_id: makeId("publication"),
    lesson_id: lesson.lesson_id,
    lesson_revision_id: lesson.published_revision_id,
    status: "published",
    published_artifact_id:
      state.artifacts.find(
        (item) =>
          item.summary_json?.lesson_revision_id === lesson.published_revision_id &&
          item.artifact_type === "reviewed_publishable_bundle"
      )?.artifact_id || null,
    created_by: "seed_loader",
    created_at: lesson.updated_at || new Date().toISOString(),
    published_at: lesson.updated_at || new Date().toISOString(),
    revoked_at: null,
    superseded_by_publication_id: null,
  });
}

function syncComponentRevisionSeeds(state) {
  for (const component of state.components) {
    let currentRevision = state.componentRevisions.find(
      (item) => item.component_revision_id === component.current_revision_id
    );
    if (currentRevision) continue;

    const componentLink = state.componentLinks.find(
      (item) =>
        item.component_id === component.component_id &&
        item.target_type === "task_revision" &&
        item.relation_type === "primary_visual_crop"
    );
    const taskSubjectExt = state.taskSubjectExt.find(
      (item) => item.task_revision_id === componentLink?.target_revision_id
    );
    const pageNo =
      state.pageAssets.find((item) => item.page_asset_id === component.page_asset_id)?.page_no || null;
    currentRevision = {
      component_revision_id: makeId("component_revision"),
      component_id: component.component_id,
      source_task_revision_id: componentLink?.target_revision_id || null,
      page_no: pageNo,
      bbox_json: component.bbox_json,
      extracted_text:
        state.taskRevisions.find((item) => item.task_revision_id === componentLink?.target_revision_id)
          ?.student_stem || "",
      // Seeded component revisions should reuse any richer source refs already
      // persisted on the task fact row so rebuilds do not drop visual structure.
      source_refs_json: mergeTaskRuntimeSourceRefs(
        readPersistedTaskSourceRefs(taskSubjectExt, null),
        component,
        pageNo ? { page_no: pageNo } : null
      ),
      created_by: "seed_loader",
      created_at: component.created_at || new Date().toISOString(),
    };
    state.componentRevisions.push(currentRevision);
    component.current_revision_id = currentRevision.component_revision_id;
  }
}

// 这些派生表都从 lesson_revision 回放生成，避免 FileStore 和 PostgresStore 出现两套事实源。
/**
 * 重算所有从源集合派生出来的投影。
 * 变更后调用这里，不要在单个工作流里手动更新投影表。
 */
export function rebuildDerivedState(state) {
  normalizeState(state);
  syncComponentRevisionSeeds(state);
  for (const lessonRevision of state.lessonRevisions) {
    syncLessonRevisionBundle(state, lessonRevision.lesson_revision_id);
    syncTaskProjectionForRevision(state, lessonRevision.lesson_revision_id);
  }
  for (const lesson of state.lessons) {
    syncSeedPublication(state, lesson);
  }
  return state;
}

export function buildSeedState() {
  const state = createEmptyState();
  const data = loadWorkbenchData();
  state.meta.generatedAt = data?.generatedAt || new Date().toISOString();
  state.meta.updatedAt = new Date().toISOString();
  state.meta.source = data ? "workbench_data_seed" : "three_track_fixture_seed";

  if (data) {
    const splitLessons = Object.values(data.splitLessons || {});
    const reviewQueue = data.reviewQueue || [];
    for (const splitLesson of splitLessons) {
      buildLessonSeed(
        state,
        splitLesson,
        reviewQueue.filter((item) => item.lessonId === splitLesson.lesson_id)
      );
    }
  } else {
    buildFixtureSeedState(state);
  }
  return rebuildDerivedState(state);
}

export function loadState() {
  return rebuildDerivedState(safeReadJson(statePath, createEmptyState()));
}

export function saveState(state) {
  rebuildDerivedState(state);
  state.meta.updatedAt = new Date().toISOString();
  writeJsonAtomic(statePath, state);
  return state;
}

export function ensureSeededState() {
  fs.mkdirSync(runtimeRoot, { recursive: true });
  if (!fs.existsSync(statePath)) {
    return saveState(buildSeedState());
  }
  return loadState();
}

export function reseedState() {
  fs.mkdirSync(runtimeRoot, { recursive: true });
  return saveState(buildSeedState());
}

export function getSummary(state) {
  const pendingReviewCount = state.reviewTasks.filter((item) =>
    ["pending", "in_review", "changes_requested", "rerun_requested"].includes(item.status)
  ).length;
  return {
    generatedAt: state.meta.generatedAt,
    updatedAt: state.meta.updatedAt,
    lessonCount: state.lessons.length,
    lessonRevisionCount: state.lessonRevisions.length,
    runCount: state.runs.length,
    jobCount: state.jobs.length,
    artifactCount: state.artifacts.length,
    reviewTaskCount: state.reviewTasks.length,
    pendingReviewCount,
    publicationCount: state.publications.length,
    taskProjectionCount: state.taskProjections.length,
    questionBankItemCount: state.questionBankItems.length,
    materialBuildCount: state.materialBuilds.length,
    componentCount: state.components.length,
    pageAssetCount: state.pageAssets.length,
  };
}

export function listLessons(state) {
  return state.lessons.map((lesson) => {
    const activeRevision = state.lessonRevisions.find((item) => item.lesson_revision_id === lesson.active_revision_id);
    const publishedRevision = state.lessonRevisions.find((item) => item.lesson_revision_id === lesson.published_revision_id);
    const latestPublication = state.publications
      .filter((item) => item.lesson_id === lesson.lesson_id)
      .sort((a, b) => String(b.published_at || b.created_at).localeCompare(String(a.published_at || a.created_at)))[0] || null;
    const taskCount = state.tasks.filter((item) => item.lesson_id === lesson.lesson_id).length;
    const reviewTaskCount = state.reviewTasks.filter((item) => item.target_revision_id.startsWith(`${lesson.lesson_id}:task:`)).length;
    return {
      ...lesson,
      activeRevision,
      publishedRevision,
      latestPublication,
      taskCount,
      reviewTaskCount,
    };
  });
}

export function getLessonDetail(state, lessonId) {
  const lesson = state.lessons.find((item) => item.lesson_id === lessonId);
  if (!lesson) return null;
  const lessonRevisions = state.lessonRevisions.filter((item) => item.lesson_id === lessonId);
  const sourceNodes = state.sourceNodes.filter((item) => item.lesson_id === lessonId);
  const sourceNodeIdSet = new Set(sourceNodes.map((item) => item.source_node_id));
  const sourceNodeRevisions = state.sourceNodeRevisions.filter((item) => sourceNodeIdSet.has(item.source_node_id));
  const tasks = state.tasks.filter((item) => item.lesson_id === lessonId);
  const taskIdSet = new Set(tasks.map((item) => item.task_id));
  const taskRevisions = state.taskRevisions.filter((item) => taskIdSet.has(item.task_id));
  const taskRevisionIdSet = new Set(taskRevisions.map((item) => item.task_revision_id));
  const reviewTasks = state.reviewTasks.filter((item) => taskRevisionIdSet.has(item.target_revision_id) || item.target_revision_id === lesson.active_revision_id);
  const taskSubjectExt = state.taskSubjectExt.filter((item) => taskRevisionIdSet.has(item.task_revision_id));
  const taskProjections = state.taskProjections.filter((item) => item.lesson_id === lessonId);
  const publications = state.publications.filter((item) => item.lesson_id === lessonId);
  const componentLinks = state.componentLinks.filter((item) => taskRevisionIdSet.has(item.target_revision_id));
  const componentIdSet = new Set(componentLinks.map((item) => item.component_id));
  const componentRevisions = state.componentRevisions.filter((item) => componentIdSet.has(item.component_id));
  const componentRevisionIdSet = new Set(componentRevisions.map((item) => item.component_revision_id));
  const componentPatchCandidates = state.componentPatchCandidates.filter((item) =>
    componentIdSet.has(item.component_id) || componentRevisionIdSet.has(item.proposed_component_revision_id)
  );
  const checkpointLinks = state.sourceNodeCheckpointLinks.filter((item) =>
    sourceNodeRevisions.some((rev) => rev.source_node_revision_id === item.source_node_revision_id)
  );
  const taskCheckpointOverrides = state.taskCheckpointOverrides.filter((item) =>
    taskRevisionIdSet.has(item.task_revision_id)
  );
  const runs = state.runs.filter((item) => item.root_target_id === lessonId);
  const runIdSet = new Set(runs.map((item) => item.run_id));
  const jobs = state.jobs.filter((item) => runIdSet.has(item.run_id));
  const artifacts = state.artifacts.filter(
    (item) =>
      runIdSet.has(item.run_id) ||
      taskSubjectExt.some((ext) => ext.task_revision_id === item.summary_json?.task_revision_id)
  );
  const qualityEvaluations = state.qualityEvaluations.filter(
    (item) => item.target_type === "lesson_revision" && lessonRevisions.some((rev) => rev.lesson_revision_id === item.target_revision_id)
  );

  return {
    lesson,
    lessonRevisions,
    sourceNodes,
    sourceNodeRevisions,
    tasks,
    taskRevisions,
    taskSubjectExt,
    taskProjections,
    checkpointLinks,
    taskCheckpointOverrides,
    reviewTasks,
    publications,
    componentLinks,
    componentRevisions,
    componentPatchCandidates,
    runs,
    jobs,
    artifacts,
    qualityEvaluations,
  };
}

export function getRunDetail(state, runId) {
  const run = state.runs.find((item) => item.run_id === runId);
  if (!run) return null;
  const jobs = state.jobs.filter((item) => item.run_id === runId);
  const jobIdSet = new Set(jobs.map((item) => item.job_id));
  const jobAttempts = state.jobAttempts.filter((item) => jobIdSet.has(item.job_id));
  const jobDependencies = state.jobDependencies.filter(
    (item) => jobIdSet.has(item.upstream_job_id) || jobIdSet.has(item.downstream_job_id)
  );
  const artifacts = state.artifacts.filter((item) => item.run_id === runId || jobIdSet.has(item.job_id));
  const artifactIdSet = new Set(artifacts.map((item) => item.artifact_id));
  const artifactDependencies = state.artifactDependencies.filter(
    (item) => artifactIdSet.has(item.parent_artifact_id) || artifactIdSet.has(item.child_artifact_id)
  );
  const reviewTasks = state.reviewTasks.filter((item) => item.run_id === runId);
  return {
    run,
    jobs,
    jobAttempts,
    jobDependencies,
    artifacts,
    artifactDependencies,
    reviewTasks,
  };
}

export function getArtifactLineage(state, artifactId) {
  const artifact = state.artifacts.find((item) => item.artifact_id === artifactId);
  if (!artifact) return null;
  const nodes = new Map();
  const edges = [];

  function visit(currentId) {
    if (nodes.has(currentId)) return;
    const current = state.artifacts.find((item) => item.artifact_id === currentId);
    if (!current) return;
    nodes.set(currentId, current);
    const parents = state.artifactDependencies.filter((item) => item.child_artifact_id === currentId);
    for (const dependency of parents) {
      edges.push(dependency);
      visit(dependency.parent_artifact_id);
    }
  }

  visit(artifactId);
  return {
    rootArtifact: artifact,
    nodes: [...nodes.values()],
    edges,
  };
}

function findLatestValidLessonArtifact(state, lessonId, artifactTypes, lessonRevisionId = null) {
  const candidates = state.artifacts
    .filter(
      (item) =>
        item.summary_json?.lesson_id === lessonId &&
        (!lessonRevisionId || item.summary_json?.lesson_revision_id === lessonRevisionId) &&
        item.integrity_status === "valid" &&
        artifactTypes.includes(item.artifact_type)
    )
    .sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)));
  return candidates[0] || null;
}

/**
 * 把一次导出同时记录成操作者可见的运行记录和血缘产物。
 * 下游看板用它说明某个 bundle 版本来自哪个课时版本。
 */
export function registerExportRun(state, payload, historyItem) {
  const lessonId = payload?.lesson?.lesson_id;
  const lesson = state.lessons.find((item) => item.lesson_id === lessonId);
  if (!lesson) {
    throw new Error("lesson_not_found_for_export");
  }

  const revisionId = lesson.published_revision_id || lesson.active_revision_id;
  const parentArtifact =
    findLatestValidLessonArtifact(state, lessonId, [
      "reviewed_publishable_bundle",
      "task_bundle",
      "source_tree_snapshot",
    ], revisionId) || null;
  const publication = state.publications.find(
    (item) => item.lesson_id === lessonId && item.lesson_revision_id === revisionId && item.status === "published"
  );

  const runId = `export_${historyItem.id}`;
  const jobId = `export_job_${slug(historyItem.id)}`;
  const outboxEventId = `export_outbox_${slug(historyItem.id)}`;

  if (!state.runs.some((item) => item.run_id === runId)) {
    state.runs.push({
      run_id: runId,
      run_type: "export_bundle",
      root_target_type: "lesson_revision",
      root_target_id: revisionId,
      subject: lesson.subject,
      lane: "interactive",
      status: "succeeded",
      triggered_by: "mock_workbench_export",
      started_at: historyItem.createdAt,
      finished_at: historyItem.createdAt,
    });
  }

  if (!state.jobs.some((item) => item.job_id === jobId)) {
    state.jobs.push({
      job_id: jobId,
      run_id: runId,
      job_type: "export_bundle",
      lane: "interactive",
      capability: "export",
      resource_class: "S",
      priority: 10,
      idempotency_key: `${lessonId}:${historyItem.id}:export_bundle`,
      status: "succeeded",
      attempt_count: 1,
      max_attempts: 3,
      lease_expires_at: null,
      heartbeat_at: null,
      timeout_at: null,
      cancel_requested_at: null,
      next_retry_at: null,
      error_code: null,
      error_detail_ref: null,
      payload_ref: `${lessonId}/exports/${historyItem.id}.payload.json`,
      result_artifact_id: null,
      created_at: historyItem.createdAt,
      updated_at: historyItem.createdAt,
    });
  }

  if (!state.outboxEvents.some((item) => item.outbox_event_id === outboxEventId)) {
    state.outboxEvents.push({
      outbox_event_id: outboxEventId,
      aggregate_type: "run",
      aggregate_id: runId,
      event_type: "export_bundle_generated",
      payload_json: {
        lesson_id: lessonId,
        lesson_revision_id: revisionId,
        export_history_id: historyItem.id,
      },
      status: "dispatched",
      created_at: historyItem.createdAt,
      dispatched_at: historyItem.createdAt,
    });
  }

  const summary = {
    lesson_id: lessonId,
    lesson_revision_id: revisionId,
    publication_id: publication?.publication_id || null,
    export_history_id: historyItem.id,
    file_count: historyItem.fileCount,
    versions: historyItem.versions || [],
    audiences: historyItem.audiences || [],
    formats: historyItem.formats || [],
    include_compass: Boolean(historyItem.includeCompass),
    preflight_checked_question_count:
      historyItem.preflight?.checkedQuestionCount || 0,
    preflight_warning_count: historyItem.preflight?.warningCount || 0,
  };

  let bundleArtifact = state.artifacts.find(
    (item) => item.run_id === runId && item.artifact_type === "export_bundle_manifest"
  );
  if (!bundleArtifact) {
    bundleArtifact = createArtifact(
      state,
      lesson,
      runId,
      jobId,
      "export_bundle_manifest",
      summary,
      parentArtifact ? [parentArtifact.artifact_id] : []
    );
  }

  for (const file of historyItem.files || []) {
    const storageUri = file.relativePath || toRelativePath(file.path);
    const existing = state.artifacts.find(
      (item) =>
        item.run_id === runId &&
        item.artifact_type === "export_file" &&
        item.storage_uri === storageUri
    );
    if (existing) continue;
    createArtifact(
      state,
      lesson,
      runId,
      jobId,
      "export_file",
      {
        lesson_id: lessonId,
        lesson_revision_id: revisionId,
        export_history_id: historyItem.id,
        format: file.format || null,
        audience: file.audience || null,
        version: file.version || null,
        relative_path: storageUri,
        size: file.size || null,
      },
      [bundleArtifact.artifact_id]
    );
  }

  return {
    runId,
    jobId,
    lessonRevisionId: revisionId,
    exportArtifactId: bundleArtifact.artifact_id,
    parentArtifactId: parentArtifact?.artifact_id || null,
  };
}

function markArtifactChainStale(state, lessonId, artifactTypes) {
  for (const artifact of state.artifacts) {
    if (
      artifact.lifecycle_status === "valid" &&
      artifact.summary_json?.lesson_id === lessonId &&
      artifactTypes.includes(artifact.artifact_type)
    ) {
      artifact.lifecycle_status = "stale";
    }
  }
}

/**
 * 模拟课时级重跑，同时保留已有审阅和发布历史。
 * 过期标记让旧派生产物仍可见，但不再被信任。
 */
export function rerunLesson(state, lessonId, actor = "manual_rerun") {
  const lesson = state.lessons.find((item) => item.lesson_id === lessonId);
  if (!lesson) {
    throw new Error("lesson_not_found");
  }
  const activeRevision = state.lessonRevisions.find((item) => item.lesson_revision_id === lesson.active_revision_id);
  if (!activeRevision) {
    throw new Error("active_revision_not_found");
  }

  const nextRevisionNo =
    Math.max(
      0,
      ...state.lessonRevisions.filter((item) => item.lesson_id === lessonId).map((item) => item.revision_no)
    ) + 1;
  const newLessonRevisionId = `${lessonId}:rev:${nextRevisionNo}`;
  state.lessonRevisions.push({
    lesson_revision_id: newLessonRevisionId,
    lesson_id: lessonId,
    base_artifact_id: activeRevision.base_artifact_id,
    generated_snapshot_ref: `${lessonId}/reruns/rev_${nextRevisionNo}/generated_snapshot.json`,
    manual_patch_ref: null,
    merged_snapshot_ref: `${lessonId}/reruns/rev_${nextRevisionNo}/merged_snapshot.json`,
    revision_no: nextRevisionNo,
    status: "reviewing",
    approval_status: "pending",
    bundle_jsonb: null,
    content_hash: null,
    created_by: actor,
    created_at: new Date().toISOString(),
  });

  const sourceNodeMap = new Map();
  for (const oldRevision of state.sourceNodeRevisions.filter((item) => item.lesson_revision_id === activeRevision.lesson_revision_id)) {
    const sourceNode = state.sourceNodes.find((item) => item.source_node_id === oldRevision.source_node_id);
    const newRevisionId = `${sourceNode.source_node_id}:rev:${nextRevisionNo}`;
    sourceNodeMap.set(oldRevision.source_node_revision_id, newRevisionId);
    state.sourceNodeRevisions.push({
      ...oldRevision,
      source_node_revision_id: newRevisionId,
      lesson_revision_id: newLessonRevisionId,
      parent_node_revision_id: oldRevision.parent_node_revision_id
        ? null
        : null,
      generated_data_ref: `${lessonId}/reruns/rev_${nextRevisionNo}/source_nodes/${slug(oldRevision.title)}.json`,
      manual_patch_ref: null,
      merged_data_ref: `${lessonId}/reruns/rev_${nextRevisionNo}/source_nodes/${slug(oldRevision.title)}_merged.json`,
      status: "reviewing",
      created_at: new Date().toISOString(),
    });
    sourceNode.current_revision_id = newRevisionId;
  }
  for (const nodeRevision of state.sourceNodeRevisions.filter((item) => item.lesson_revision_id === newLessonRevisionId)) {
    const oldParent = state.sourceNodeRevisions.find(
      (item) =>
        item.lesson_revision_id === activeRevision.lesson_revision_id &&
        `${item.source_node_id}:rev:${nextRevisionNo}` === nodeRevision.source_node_revision_id
    )?.parent_node_revision_id;
    nodeRevision.parent_node_revision_id = oldParent ? sourceNodeMap.get(oldParent) || null : null;
  }

  for (const oldTaskRevision of state.taskRevisions.filter((item) => item.lesson_revision_id === activeRevision.lesson_revision_id)) {
    const task = state.tasks.find((item) => item.task_id === oldTaskRevision.task_id);
    const newTaskRevisionId = `${task.task_id}:rev:${nextRevisionNo}`;
    state.taskRevisions.push({
      ...oldTaskRevision,
      task_revision_id: newTaskRevisionId,
      lesson_revision_id: newLessonRevisionId,
      source_node_revision_id:
        sourceNodeMap.get(oldTaskRevision.source_node_revision_id) || oldTaskRevision.source_node_revision_id,
      generated_data_ref: `${lessonId}/reruns/rev_${nextRevisionNo}/tasks/${slug(task.task_id)}.generated.json`,
      manual_patch_ref: null,
      merged_data_ref: `${lessonId}/reruns/rev_${nextRevisionNo}/tasks/${slug(task.task_id)}.merged.json`,
      status: "reviewing",
      created_at: new Date().toISOString(),
    });
    task.current_revision_id = newTaskRevisionId;

    const oldOverrides = state.taskCheckpointOverrides.filter(
      (item) => item.task_revision_id === oldTaskRevision.task_revision_id
    );
    for (const override of oldOverrides) {
      state.taskCheckpointOverrides.push({
        ...override,
        override_id: makeId("task_checkpoint_override"),
        task_revision_id: newTaskRevisionId,
        created_at: new Date().toISOString(),
      });
    }

    const oldSubjectExt = state.taskSubjectExt.filter(
      (item) => item.task_revision_id === oldTaskRevision.task_revision_id
    );
    for (const ext of oldSubjectExt) {
      state.taskSubjectExt.push({
        ...ext,
        task_revision_id: newTaskRevisionId,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      });
    }

    for (const componentLink of state.componentLinks.filter(
      (item) =>
        item.target_type === "task_revision" &&
        item.target_revision_id === oldTaskRevision.task_revision_id
    )) {
      // Keep the task-to-component bridge on rerun so the rebuilt bundle can
      // still resolve visual lineage without waiting for a fresh crop job.
      state.componentLinks.push({
        ...componentLink,
        component_link_id: makeId("component_link"),
        target_revision_id: newTaskRevisionId,
        created_at: new Date().toISOString(),
      });
    }
  }

  const runId = makeId("run");
  const rerunJobs = [
    ["source_tree_rerun", "structure", "M", 20],
    ["task_extract_rerun", "task-extraction", "M", 30],
    ["quality_gate_rerun", "checkpoint", "S", 40],
  ].map(([jobType, capability, resourceClass, priority]) => ({
    job_id: makeId("job"),
    run_id: runId,
    job_type: jobType,
    lane: "async-short",
    capability,
    resource_class: resourceClass,
    priority,
    idempotency_key: `${lessonId}:${newLessonRevisionId}:${jobType}`,
    status: "succeeded",
    attempt_count: 1,
    max_attempts: 3,
    lease_expires_at: null,
    heartbeat_at: null,
    timeout_at: null,
    cancel_requested_at: null,
    next_retry_at: null,
    error_code: null,
    error_detail_ref: null,
    payload_ref: `${lessonId}/reruns/rev_${nextRevisionNo}/${jobType}.json`,
    result_artifact_id: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  }));
  state.runs.push({
    run_id: runId,
    run_type: "lesson_rerun",
    root_target_type: "lesson",
    root_target_id: lessonId,
    subject: lesson.subject,
    lane: "async-short",
    status: "waiting_review",
    triggered_by: actor,
    started_at: new Date().toISOString(),
    finished_at: new Date().toISOString(),
  });
  state.jobs.push(...rerunJobs);
  state.jobAttempts.push(
    ...rerunJobs.map((job, index) => ({
      job_attempt_id: makeId("job_attempt"),
      job_id: job.job_id,
      attempt_no: 1,
      started_at: job.created_at,
      heartbeat_at: job.updated_at,
      finished_at: job.updated_at,
      status: "succeeded",
      error_detail_json: null,
      worker_ref: `file_store_rerun_${index + 1}`,
    }))
  );
  state.jobDependencies.push({
    job_dependency_id: makeId("job_dep"),
    upstream_job_id: rerunJobs[0].job_id,
    downstream_job_id: rerunJobs[1].job_id,
    dependency_type: "finishes_before",
    created_at: new Date().toISOString(),
  });
  state.jobDependencies.push({
    job_dependency_id: makeId("job_dep"),
    upstream_job_id: rerunJobs[1].job_id,
    downstream_job_id: rerunJobs[2].job_id,
    dependency_type: "finishes_before",
    created_at: new Date().toISOString(),
  });
  state.outboxEvents.push({
    outbox_event_id: makeId("outbox"),
    aggregate_type: "run",
    aggregate_id: runId,
    event_type: "lesson_rerun_requested",
    payload_json: {
      lesson_id: lessonId,
      lesson_revision_id: newLessonRevisionId,
    },
    status: "dispatched",
    created_at: new Date().toISOString(),
    dispatched_at: new Date().toISOString(),
  });

  const sourceTreeArtifact = createArtifact(
    state,
    lesson,
    runId,
    rerunJobs[0].job_id,
    "source_tree_snapshot",
    {
      lesson_id: lessonId,
      lesson_revision_id: newLessonRevisionId,
      rerun_note: "active_revision_updated_pending_review",
    }
  );
  const taskBundleArtifact = createArtifact(
    state,
    lesson,
    runId,
    rerunJobs[1].job_id,
    "task_bundle",
    {
      lesson_id: lessonId,
      lesson_revision_id: newLessonRevisionId,
      rerun_note: "task_revisions_cloned",
    },
    [sourceTreeArtifact.artifact_id]
  );
  const publishableArtifact = createArtifact(
    state,
    lesson,
    runId,
    rerunJobs[2].job_id,
    "reviewed_publishable_bundle",
    {
      lesson_id: lessonId,
      lesson_revision_id: newLessonRevisionId,
      rerun_note: "awaiting_manual_review",
    },
    [taskBundleArtifact.artifact_id]
  );
  state.lessonRevisions.find((item) => item.lesson_revision_id === newLessonRevisionId).base_artifact_id =
    sourceTreeArtifact.artifact_id;

  lesson.active_revision_id = newLessonRevisionId;
  lesson.status = "reviewing";
  lesson.updated_at = new Date().toISOString();

  state.reviewTasks.push({
    review_task_id: makeId("review_task"),
    target_type: "lesson_revision",
    target_revision_id: newLessonRevisionId,
    run_id: runId,
    status: "pending",
    assigned_to: null,
    requested_by: actor,
    changes_summary: `重跑生成了新修订 ${newLessonRevisionId}，待人工确认后再发布。`,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  });
  state.qualityEvaluations.push({
    quality_evaluation_id: makeId("quality"),
    target_type: "lesson_revision",
    target_revision_id: newLessonRevisionId,
    rule_set_version: "runtime_backbone_seed_v0.1",
    check_code: "Q4_manual_review_required",
    severity: "warning",
    score: 70,
    passed: false,
    evidence_ref: publishableArtifact.artifact_id,
    evaluated_at: new Date().toISOString(),
  });
  syncLessonRevisionBundle(state, newLessonRevisionId);
  syncTaskProjectionForRevision(state, newLessonRevisionId);

  return {
    lessonId,
    activeRevisionId: newLessonRevisionId,
    runId,
  };
}

export function updateReviewTaskStatus(state, reviewTaskId, action, actor = "reviewer") {
  const reviewTask = state.reviewTasks.find((item) => item.review_task_id === reviewTaskId);
  if (!reviewTask) {
    throw new Error("review_task_not_found");
  }

  if (action === "approve") {
    reviewTask.status = "approved";
    reviewTask.updated_at = new Date().toISOString();
    if (reviewTask.target_type === "lesson_revision") {
      const lessonRevision = state.lessonRevisions.find(
        (item) => item.lesson_revision_id === reviewTask.target_revision_id
      );
      if (lessonRevision) {
        lessonRevision.status = "approved";
        lessonRevision.approval_status = "approved";
      }
    }
  } else if (action === "request_changes") {
    reviewTask.status = "changes_requested";
    reviewTask.updated_at = new Date().toISOString();
    if (reviewTask.target_type === "lesson_revision") {
      const lessonRevision = state.lessonRevisions.find(
        (item) => item.lesson_revision_id === reviewTask.target_revision_id
      );
      if (lessonRevision) {
        lessonRevision.status = "changes_requested";
        lessonRevision.approval_status = "changes_requested";
      }
    }
  } else {
    throw new Error("unsupported_review_action");
  }

  return {
    reviewTask,
    actor,
  };
}

function getPublishedRevisionIdSet(state) {
  const published = new Set(
    state.publications
      .filter((item) => item.status === "published")
      .map((item) => item.lesson_revision_id)
  );
  for (const lesson of state.lessons) {
    if (lesson.published_revision_id) {
      published.add(lesson.published_revision_id);
    }
  }
  return published;
}

function validateLessonDraftBundle(bundle) {
  if (!bundle || typeof bundle !== "object") {
    throw new Error("invalid_bundle_payload");
  }
  if (!Array.isArray(bundle.tasks)) {
    throw new Error("invalid_bundle_tasks");
  }
  validateTrackProfile(bundle);
  const localTaskIds = new Set();
  const sourceNodeIds = new Set(
    Array.isArray(bundle.source_tree)
      ? bundle.source_tree.map((item) => item.source_node_local_id).filter(Boolean)
      : ["root"]
  );

  for (const task of bundle.tasks) {
    if (!task || typeof task !== "object") {
      throw new Error("invalid_bundle_task_entry");
    }
    if (!task.local_task_id) {
      throw new Error("missing_local_task_id");
    }
    if (localTaskIds.has(task.local_task_id)) {
      throw new Error("duplicate_local_task_id");
    }
    localTaskIds.add(task.local_task_id);
    if (
      task.checkpoint_override?.mode &&
      !["add", "remove", "replace"].includes(String(task.checkpoint_override.mode).toLowerCase())
    ) {
      throw new Error("invalid_bundle_task_checkpoint_override_mode");
    }
    if (task.source_node_local_id && !sourceNodeIds.has(task.source_node_local_id)) {
      throw new Error("task_source_node_not_found");
    }
  }
}

/**
 * 校验 bundle 形态后，将课时草稿推进到已发布通道。
 * 发布会有意更新多个投影，因为它是面向操作者的权威视图。
 */
export function publishLessonRevision(state, lessonId, actor = "publisher", options = {}) {
  const lesson = state.lessons.find((item) => item.lesson_id === lessonId);
  if (!lesson) {
    throw new Error("lesson_not_found");
  }

  const lessonRevisionId = options.lessonRevisionId || lesson.active_revision_id;
  const lessonRevision = state.lessonRevisions.find(
    (item) => item.lesson_revision_id === lessonRevisionId && item.lesson_id === lessonId
  );
  if (!lessonRevision) {
    throw new Error("lesson_revision_not_found");
  }

  if (
    lesson.published_revision_id === lessonRevisionId &&
    state.publications.some(
      (item) =>
        item.lesson_id === lessonId &&
        item.lesson_revision_id === lessonRevisionId &&
        item.status === "published"
    )
  ) {
    return {
      lesson,
      lessonRevision,
      publication: state.publications.find(
        (item) =>
          item.lesson_id === lessonId &&
          item.lesson_revision_id === lessonRevisionId &&
          item.status === "published"
      ),
    };
  }

  if (lessonRevision.approval_status !== "approved") {
    throw new Error("revision_not_approved_for_publish");
  }

  const currentPublished = state.publications.filter(
    (item) => item.lesson_id === lessonId && item.status === "published"
  );

  const publishedArtifact =
    state.artifacts
      .filter(
        (item) =>
          item.integrity_status === "valid" &&
          item.summary_json?.lesson_id === lessonId &&
          item.summary_json?.lesson_revision_id === lessonRevisionId &&
          ["reviewed_publishable_bundle", "task_bundle", "source_tree_snapshot"].includes(
            item.artifact_type
          )
      )
      .sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)))[0] || null;
  if (!publishedArtifact) {
    throw new Error("publication_artifact_not_found");
  }

  const publication = {
    publication_id: makeId("publication"),
    lesson_id: lessonId,
    lesson_revision_id: lessonRevisionId,
    status: "published",
    published_artifact_id: publishedArtifact?.artifact_id || null,
    material_build_id: options.materialBuildId || null,
    created_by: actor,
    created_at: new Date().toISOString(),
    published_at: new Date().toISOString(),
    revoked_at: null,
    superseded_by_publication_id: null,
  };
  state.publications.push(publication);
  for (const previousPublication of currentPublished) {
    previousPublication.status = "superseded";
    previousPublication.superseded_by_publication_id = publication.publication_id;
  }
  maybeFailpoint("publish_after_publication_before_pointer");

  lesson.published_revision_id = lessonRevisionId;
  lesson.status = "published";
  lesson.updated_at = publication.published_at;
  lessonRevision.status = "published";
  lessonRevision.approval_status = "approved";
  syncLessonRevisionBundle(state, lessonRevisionId);
  syncTaskProjectionForRevision(state, lessonRevisionId);

  return {
    lesson,
    lessonRevision,
    publication,
  };
}

export function searchTaskProjections(state, filters = {}) {
  return {
    items: filterTaskProjectionItems(state, state.taskProjections || [], filters),
    projectionCoverage: inspectTaskProjectionCoverage(state, filters),
  };
}

function filterTaskProjectionItems(state, projections, filters = {}) {
  const publishedRevisionIds = getPublishedRevisionIdSet(state);
  const keyword = String(filters.q || "").trim().toLowerCase();
  const difficultyLevel = parseDifficultyFilter(filters.difficultyLevel);
  const trackCode = filters.trackCode || filters.track_code || "";

  return projections.filter((item) => {
    if (filters.publishedOnly && !publishedRevisionIds.has(item.lesson_revision_id)) {
      return false;
    }
    if (filters.subject && item.subject !== filters.subject) {
      return false;
    }
    if (filters.stage && item.stage !== filters.stage) {
      return false;
    }
    if (trackCode && item.track_code !== trackCode) {
      return false;
    }
    if (filters.grade && item.grade !== filters.grade) {
      return false;
    }
    if (filters.questionType && item.question_type !== filters.questionType) {
      return false;
    }
    if (difficultyLevel !== null && item.difficulty_level !== difficultyLevel) {
      return false;
    }
    if (filters.difficultyScheme && item.difficulty_scheme !== filters.difficultyScheme) {
      return false;
    }
    if (filters.checkpointCode && !(item.checkpoint_codes || []).includes(filters.checkpointCode)) {
      return false;
    }
    if (
      keyword &&
      !String(item.search_text || "")
        .toLowerCase()
        .includes(keyword)
    ) {
      return false;
    }
    return true;
  });
}

function inspectTaskProjectionCoverage(state, filters = {}) {
  const expectedState = JSON.parse(JSON.stringify(state || createEmptyState()));
  rebuildDerivedState(expectedState);

  const actualItems = filterTaskProjectionItems(state, state.taskProjections || [], filters);
  const expectedItems = filterTaskProjectionItems(
    expectedState,
    expectedState.taskProjections || [],
    filters
  );
  const actualMap = new Map(
    actualItems.map((item) => [item.task_projection_id, item.content_hash || computeHash(item)])
  );
  const expectedMap = new Map(
    expectedItems.map((item) => [item.task_projection_id, item.content_hash || computeHash(item)])
  );
  const missingProjectionIds = [];
  const staleProjectionIds = [];
  const extraProjectionIds = [];

  for (const [projectionId, expectedHash] of expectedMap.entries()) {
    if (!actualMap.has(projectionId)) {
      missingProjectionIds.push(projectionId);
      continue;
    }
    if (actualMap.get(projectionId) !== expectedHash) {
      staleProjectionIds.push(projectionId);
    }
  }
  for (const projectionId of actualMap.keys()) {
    if (!expectedMap.has(projectionId)) {
      extraProjectionIds.push(projectionId);
    }
  }

  return {
    status:
      missingProjectionIds.length || staleProjectionIds.length || extraProjectionIds.length
        ? "degraded"
        : "ok",
    needsRebuild:
      missingProjectionIds.length > 0 ||
      staleProjectionIds.length > 0 ||
      extraProjectionIds.length > 0,
    actualCount: actualItems.length,
    expectedCount: expectedItems.length,
    missingProjectionIds,
    staleProjectionIds,
    extraProjectionIds,
  };
}

function collectScopedLessonRevisionIds(state, scope = {}) {
  const lessonId = scope.lessonId || scope.lesson_id || null;
  const lessonRevisionId = scope.lessonRevisionId || scope.lesson_revision_id || null;

  if (lessonRevisionId) {
    return state.lessonRevisions
      .filter((item) => item.lesson_revision_id === lessonRevisionId)
      .map((item) => item.lesson_revision_id);
  }
  if (lessonId) {
    return state.lessonRevisions
      .filter((item) => item.lesson_id === lessonId)
      .map((item) => item.lesson_revision_id);
  }
  return state.lessonRevisions.map((item) => item.lesson_revision_id);
}

export function rebuildTaskProjections(state, scope = {}) {
  normalizeState(state);
  const lessonRevisionIds = collectScopedLessonRevisionIds(state, scope);
  const beforeCount = state.taskProjections.length;

  for (const currentLessonRevisionId of lessonRevisionIds) {
    syncLessonRevisionBundle(state, currentLessonRevisionId);
    syncTaskProjectionForRevision(state, currentLessonRevisionId);
  }

  const afterCount = state.taskProjections.length;
  return {
    rebuiltLessonRevisionIds: lessonRevisionIds,
    rebuiltLessonRevisionCount: lessonRevisionIds.length,
    beforeCount,
    afterCount,
    deltaCount: afterCount - beforeCount,
  };
}

function buildQuestionBankRevisionPayload(source, existingItemId = null) {
  const itemId = existingItemId || makeId("qb_item");
  const revisionId = makeId("qb_rev");
  const trackScope = normalizeTrackScope(source);
  const difficulty = buildDifficultyPayload(source, trackScope.trackProfile, {
    defaultSource: source.created_by === "question_bank_ingest" ? "question_bank_projection" : "question_bank_manual",
  });
  const searchText = [
    source.stem,
    source.answer,
    source.explanation,
    ...(source.checkpoint_codes || []),
    ...(source.subject_tags || []),
  ]
    .filter(Boolean)
    .join(" ");
  return {
    item: {
      question_bank_item_id: itemId,
      subject: trackScope.subject,
      stage: trackScope.stage,
      track_code: trackScope.track_code,
      grade: source.grade || null,
      current_revision_id: revisionId,
      status: "active",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    },
    revision: {
      question_bank_item_revision_id: revisionId,
      question_bank_item_id: itemId,
      subject: trackScope.subject,
      stage: trackScope.stage,
      track_code: trackScope.track_code,
      stem: source.stem || "",
      answer: source.answer || "",
      explanation: source.explanation || "",
      question_type: source.question_type || "question",
      ...difficulty,
      checkpoint_codes: source.checkpoint_codes || [],
      subject_tags: source.subject_tags || [],
      source_refs_json: source.source_refs_json || {},
      content_hash: computeHash(source),
      search_text: searchText,
      search_vector: searchText,
      created_at: new Date().toISOString(),
      created_by: source.created_by || "manual",
    },
  };
}

export function createQuestionBankItem(state, payload = {}) {
  let source = null;
  let projection = null;

  if (payload.taskProjectionId) {
    projection = state.taskProjections.find((item) => item.task_projection_id === payload.taskProjectionId);
    if (!projection) {
      throw new Error("task_projection_not_found");
    }
    if (!getPublishedRevisionIdSet(state).has(projection.lesson_revision_id)) {
      throw new Error("task_projection_not_published");
    }
    source = {
      ...projection,
      created_by: payload.actor || "question_bank_ingest",
    };
  } else {
    source = {
      ...payload,
      created_by: payload.actor || "question_bank_manual",
    };
  }

  const existingItem = payload.questionBankItemId
    ? state.questionBankItems.find((item) => item.question_bank_item_id === payload.questionBankItemId)
    : null;
  const built = buildQuestionBankRevisionPayload(source, existingItem?.question_bank_item_id || null);

  if (!existingItem) {
    state.questionBankItems.push(built.item);
  } else {
    existingItem.subject = built.item.subject;
    existingItem.stage = built.item.stage;
    existingItem.track_code = built.item.track_code;
    existingItem.grade = built.item.grade;
    existingItem.current_revision_id = built.revision.question_bank_item_revision_id;
    existingItem.updated_at = built.item.updated_at;
  }
  state.questionBankItemRevisions.push(built.revision);

  if (projection) {
    state.questionBankSourceLinks.push({
      question_bank_source_link_id: makeId("qb_link"),
      question_bank_item_revision_id: built.revision.question_bank_item_revision_id,
      lesson_id: projection.lesson_id,
      lesson_revision_id: projection.lesson_revision_id,
      local_task_id: projection.local_task_id,
      source_node_local_id: projection.source_node_local_id,
      source_refs_json: projection.source_refs_json,
      created_at: new Date().toISOString(),
    });
  }

  return {
    item: existingItem || built.item,
    revision: built.revision,
  };
}

export function searchQuestionBank(state, filters = {}) {
  const keyword = String(filters.q || "").trim().toLowerCase();
  const difficultyLevel = parseDifficultyFilter(filters.difficultyLevel);
  const trackCode = filters.trackCode || filters.track_code || "";
  const latestRevisionIds = new Set(
    state.questionBankItems.map((item) => item.current_revision_id).filter(Boolean)
  );
  return state.questionBankItemRevisions
    .filter((item) => {
      if (filters.latestOnly !== false && !latestRevisionIds.has(item.question_bank_item_revision_id)) {
        return false;
      }
      const owner = state.questionBankItems.find(
        (row) => row.question_bank_item_id === item.question_bank_item_id
      );
      if (filters.subject && owner?.subject !== filters.subject) {
        return false;
      }
      if (filters.stage && owner?.stage !== filters.stage) {
        return false;
      }
      if (trackCode && owner?.track_code !== trackCode) {
        return false;
      }
      if (filters.grade && owner?.grade !== filters.grade) {
        return false;
      }
      if (filters.questionType && item.question_type !== filters.questionType) {
        return false;
      }
      if (difficultyLevel !== null && item.difficulty_level !== difficultyLevel) {
        return false;
      }
      if (filters.difficultyScheme && item.difficulty_scheme !== filters.difficultyScheme) {
        return false;
      }
      if (
        filters.checkpointCode &&
        !(item.checkpoint_codes || []).includes(filters.checkpointCode)
      ) {
        return false;
      }
      if (
        keyword &&
        !String(item.search_text || "")
          .toLowerCase()
          .includes(keyword)
      ) {
        return false;
      }
      return true;
    })
    .map((item) => ({
      ...item,
      item: state.questionBankItems.find(
        (row) => row.question_bank_item_id === item.question_bank_item_id
      ),
      sourceLinks: state.questionBankSourceLinks.filter(
        (row) => row.question_bank_item_revision_id === item.question_bank_item_revision_id
      ),
    }));
}

function createRunJobPair(state, options) {
  const createdAt = options.createdAt || new Date().toISOString();
  const run = {
    run_id: options.runId || makeId("run"),
    run_type: options.runType,
    root_target_type: options.rootTargetType,
    root_target_id: options.rootTargetId,
    subject: options.subject || null,
    lane: options.lane || "interactive",
    status: options.status || "succeeded",
    triggered_by: options.actor || "system",
    started_at: createdAt,
    finished_at: createdAt,
  };
  const job = {
    job_id: options.jobId || makeId("job"),
    run_id: run.run_id,
    job_type: options.jobType,
    lane: run.lane,
    capability: options.capability || options.jobType,
    resource_class: options.resourceClass || "S",
    priority: options.priority || 20,
    idempotency_key: options.idempotencyKey,
    status: options.jobStatus || "succeeded",
    attempt_count: 1,
    max_attempts: options.maxAttempts || 3,
    lease_expires_at: null,
    heartbeat_at: createdAt,
    timeout_at: options.timeoutAt || null,
    cancel_requested_at: null,
    next_retry_at: null,
    error_code: null,
    error_detail_ref: null,
    payload_ref: options.payloadRef || null,
    result_artifact_id: null,
    created_at: createdAt,
    updated_at: createdAt,
  };
  state.runs.push(run);
  state.jobs.push(job);
  state.jobAttempts.push({
    job_attempt_id: makeId("job_attempt"),
    job_id: job.job_id,
    attempt_no: 1,
    started_at: createdAt,
    heartbeat_at: createdAt,
    finished_at: options.jobStatus === "running" ? null : createdAt,
    status: options.jobStatus || "succeeded",
    error_detail_json: null,
    worker_ref: options.workerRef || "file_store_worker",
  });
  return { run, job };
}

function ensureLessonContainers(state, bundle, actor = "import_api") {
  const lessonId = bundle.lesson_id || bundle.lesson?.lesson_id || makeId("lesson");
  let lesson = state.lessons.find((item) => item.lesson_id === lessonId);
  if (lesson) {
    lesson.subject = bundle.subject || lesson.subject || null;
    lesson.stage = bundle.stage || lesson.stage || null;
    lesson.track_code = bundle.track_code || bundle.trackCode || lesson.track_code || null;
    lesson.grade = bundle.grade || lesson.grade || null;
    lesson.season = bundle.season || lesson.season || null;
    lesson.title = bundle.title || lesson.title || lessonId;
    lesson.updated_at = new Date().toISOString();
    const documentId = state.documentGroupMembers.find(
      (item) => item.document_group_id === lesson.document_group_id
    )?.document_id;
    return { lesson, documentId };
  }

  const sourceId = makeId("source");
  const documentId = makeId("document");
  const documentGroupId = makeId("docgroup");
  state.documentSources.push({
    source_id: sourceId,
    source_type: "lesson_draft_bundle",
    subject: bundle.subject || bundle.lesson?.subject || null,
    owner_id: actor,
    import_batch_id: bundle.bundle_id || lessonId,
    metadata_json: {
      bundle_id: bundle.bundle_id || null,
    },
    created_at: new Date().toISOString(),
  });
  state.documents.push({
    document_id: documentId,
    source_id: sourceId,
    subject: bundle.subject || bundle.lesson?.subject || null,
    stage: bundle.stage || bundle.lesson?.stage || null,
    grade: bundle.grade || bundle.lesson?.grade || null,
    season: bundle.season || bundle.lesson?.season || null,
    doc_role: "lesson_draft_bundle",
    title: bundle.title || bundle.lesson?.title || lessonId,
    storage_uri: bundle.storage_uri || "",
    checksum: bundle.content_hash || null,
    page_count: bundle.page_count || null,
    status: "ready",
    metadata_json: {},
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  });
  state.documentGroups.push({
    document_group_id: documentGroupId,
    subject: bundle.subject || bundle.lesson?.subject || null,
    group_type: "lesson_source_set",
    label: bundle.title || bundle.lesson?.title || lessonId,
    status: "active",
    metadata_json: {
      lesson_id: lessonId,
    },
    created_at: new Date().toISOString(),
  });
  state.documentGroupMembers.push({
    document_group_member_id: makeId("docgroup_member"),
    document_group_id: documentGroupId,
    document_id: documentId,
    member_role: "lesson_draft_bundle",
    sort_index: 1,
    created_at: new Date().toISOString(),
  });
  lesson = {
    lesson_id: lessonId,
    document_group_id: documentGroupId,
    subject: bundle.subject || bundle.lesson?.subject || null,
    stage: bundle.stage || bundle.lesson?.stage || null,
    track_code: bundle.track_code || bundle.trackCode || null,
    grade: bundle.grade || bundle.lesson?.grade || null,
    season: bundle.season || bundle.lesson?.season || null,
    title: bundle.title || bundle.lesson?.title || lessonId,
    active_revision_id: null,
    published_revision_id: null,
    status: "draft",
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };
  state.lessons.push(lesson);
  return { lesson, documentId };
}

function inferSourceNodeCheckpointDefaults(sourceTree, tasks = []) {
  const taskBuckets = new Map();
  for (const task of tasks) {
    const localId = task.source_node_local_id || "root";
    if (!taskBuckets.has(localId)) {
      taskBuckets.set(localId, []);
    }
    taskBuckets.get(localId).push(task);
  }

  const defaults = new Map();
  for (const node of sourceTree) {
    const localId = node.source_node_local_id || slug(node.title || "node");
    const explicitCodes = normalizeCheckpointCodes(node.checkpoint_codes || []);
    if (explicitCodes.length > 0) {
      defaults.set(localId, explicitCodes);
      continue;
    }

    const seen = new Map();
    for (const task of taskBuckets.get(localId) || []) {
      if (task.checkpoint_override || task.checkpointOverride) {
        continue;
      }
      const taskCodes = normalizeCheckpointCodes(task.checkpoint_codes || []);
      if (taskCodes.length === 0) {
        continue;
      }
      const key = JSON.stringify(taskCodes);
      seen.set(key, (seen.get(key) || 0) + 1);
    }

    const best = [...seen.entries()].sort((left, right) => right[1] - left[1])[0];
    defaults.set(localId, best ? JSON.parse(best[0]) : []);
  }
  return defaults;
}

function hydrateRevisionFromBundle(state, lesson, documentId, lessonRevisionId, bundle, actor = "import_api") {
  const catalogScope = {
    subject: lesson.subject,
    stage: lesson.stage,
    grade: lesson.grade,
  };
  const { version } = ensureCatalog(state, catalogScope);
  const sourceNodeIdByLocalId = new Map();
  const sourceNodeRevisionIdByLocalId = new Map();
  const sourceTree = bundle.source_tree?.length
    ? bundle.source_tree
    : [
        {
          source_node_local_id: "root",
          parent_source_node_revision_id: null,
          node_type: "lesson",
          phase: "knowledge_main",
          title: bundle.title || lesson.title,
          order_index: 0,
        },
      ];
  const defaultCheckpointCodesByLocalId = inferSourceNodeCheckpointDefaults(sourceTree, bundle.tasks || []);

  for (const node of sourceTree) {
    const localId = node.source_node_local_id || slug(node.title || "node");
    const sourceNodeId = `${lesson.lesson_id}:node:${localId}`;
    const sourceNodeRevisionId = `${sourceNodeId}:rev:${state.lessonRevisions.find((item) => item.lesson_revision_id === lessonRevisionId)?.revision_no || 1}`;
    if (!state.sourceNodes.some((item) => item.source_node_id === sourceNodeId)) {
      state.sourceNodes.push({
        source_node_id: sourceNodeId,
        lesson_id: lesson.lesson_id,
        stable_code: localId,
        current_revision_id: sourceNodeRevisionId,
        created_at: new Date().toISOString(),
      });
    }
    state.sourceNodeRevisions.push({
      source_node_revision_id: sourceNodeRevisionId,
      source_node_id: sourceNodeId,
      lesson_revision_id: lessonRevisionId,
      parent_node_revision_id: null,
      node_type: node.node_type || "knowledge_block",
      phase: node.phase || "knowledge_main",
      title: node.title || localId,
      order_index: node.order_index || 0,
      page_span: null,
      component_bundle_ref: null,
      generated_data_ref: `${lesson.lesson_id}/imports/${slug(localId)}.generated.json`,
      manual_patch_ref: null,
      merged_data_ref: `${lesson.lesson_id}/imports/${slug(localId)}.merged.json`,
      status: "reviewing",
      created_at: new Date().toISOString(),
    });
    sourceNodeIdByLocalId.set(localId, sourceNodeId);
    sourceNodeRevisionIdByLocalId.set(localId, sourceNodeRevisionId);
  }

  for (const node of sourceTree) {
    const localId = node.source_node_local_id || slug(node.title || "node");
    const currentRevision = state.sourceNodeRevisions.find(
      (item) => item.source_node_revision_id === sourceNodeRevisionIdByLocalId.get(localId)
    );
    const parentLocalId = node.parent_source_node_local_id || node.parent_source_node_revision_id;
    currentRevision.parent_node_revision_id = parentLocalId
      ? sourceNodeRevisionIdByLocalId.get(parentLocalId) || null
      : null;
    for (const checkpointCode of defaultCheckpointCodesByLocalId.get(localId) || []) {
      const checkpointNode = ensureCheckpointNode(state, version.catalog_version_id, checkpointCode, 0);
      state.sourceNodeCheckpointLinks.push({
        link_id: makeId("checkpoint_link"),
        source_node_revision_id: currentRevision.source_node_revision_id,
        checkpoint_node_id: checkpointNode.checkpoint_node_id,
        relation_type: "default",
        confidence: 0.95,
        mapping_source: "lesson_draft_bundle_node_default",
        created_at: new Date().toISOString(),
      });
    }
  }

  const pageAssetByPageNo = new Map();
  const trackProfile = safeTrackScope(lesson)?.trackProfile || resolveTrackProfile(bundle);
  for (const task of bundle.tasks || []) {
    const taskId = `${lesson.lesson_id}:task:${task.local_task_id}`;
    const taskRevisionId = `${taskId}:rev:${state.lessonRevisions.find((item) => item.lesson_revision_id === lessonRevisionId)?.revision_no || 1}`;
    const sourceNodeLocalId =
      task.source_node_local_id ||
      sourceTree[0]?.source_node_local_id ||
      "root";
    const sourceNodeRevisionId =
      sourceNodeRevisionIdByLocalId.get(sourceNodeLocalId) ||
      [...sourceNodeRevisionIdByLocalId.values()][0] ||
      null;
    const defaultCheckpointCodes = getDefaultCheckpointCodesForSourceNodeRevision(
      state,
      sourceNodeRevisionId
    );
    const difficulty = buildDifficultyPayload(task, trackProfile, {
      defaultSource: "lesson_draft_bundle",
    });
    if (!state.tasks.some((item) => item.task_id === taskId)) {
      state.tasks.push({
        task_id: taskId,
        lesson_id: lesson.lesson_id,
        stable_question_no: task.local_task_id,
        current_revision_id: taskRevisionId,
        created_at: new Date().toISOString(),
      });
    } else {
      state.tasks.find((item) => item.task_id === taskId).current_revision_id = taskRevisionId;
    }
    state.taskRevisions.push({
      task_revision_id: taskRevisionId,
      task_id: taskId,
      lesson_revision_id: lessonRevisionId,
      source_node_revision_id: sourceNodeRevisionId,
      student_stem: task.stem || "",
      teacher_stem: task.stem || "",
      answer: task.answer || "",
      explanation: task.explanation || "",
      visibility: "student_standard",
      generated_data_ref: `${lesson.lesson_id}/imports/${task.local_task_id}.generated.json`,
      manual_patch_ref: null,
      merged_data_ref: `${lesson.lesson_id}/imports/${task.local_task_id}.merged.json`,
      status: "reviewing",
      created_at: new Date().toISOString(),
    });
    state.taskSubjectExt.push({
      task_revision_id: taskRevisionId,
      subject: lesson.subject,
      stage: lesson.stage,
      track_code: lesson.track_code || trackProfile.track_code,
      plugin_id: trackProfile.plugin_id,
      plugin_version: "0.1",
      schema_version: "0.1",
      payload_json: {
        track_code: lesson.track_code || trackProfile.track_code,
        component_kind: task.question_type || "question",
        tags: task.subject_tags || [],
        // Persist the merged source refs on the task fact row so reruns can
        // rebuild projections even when no new visual crop is generated.
        source_refs_json: deepClone(task.source_refs_json || {}),
        ...difficulty,
      },
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    });

    writeTaskCheckpointOverrides(
      state,
      version.catalog_version_id,
      taskRevisionId,
      defaultCheckpointCodes,
      task
    );

    const pageNo = task.source_refs_json?.page_no || 1;
    if (!pageAssetByPageNo.has(pageNo)) {
      pageAssetByPageNo.set(pageNo, createPageAsset(state, documentId, pageNo));
    }
    const pageAsset = pageAssetByPageNo.get(pageNo);
    const component = {
      component_id: makeId("component"),
      page_asset_id: pageAsset.page_asset_id,
      parent_component_id: null,
      component_type: task.question_type || "question_crop",
      bbox_json: task.source_refs_json?.bbox || {
        x: 0,
        y: 0,
        width: 100,
        height: 100,
      },
      reading_order: Number(task.local_task_id) || 0,
      crop_artifact_id: task.source_refs_json?.crop_artifact_id || null,
      content_hash: computeHash({
        lesson_revision_id: lessonRevisionId,
        local_task_id: task.local_task_id,
      }),
      schema_version: "0.1",
      extraction_confidence: 0.85,
      status: "ready",
      current_revision_id: null,
      created_at: new Date().toISOString(),
    };
    state.components.push(component);
    state.componentLinks.push({
      component_link_id: makeId("component_link"),
      component_id: component.component_id,
      target_type: "task_revision",
      target_revision_id: taskRevisionId,
      relation_type: "primary_visual_crop",
      created_at: new Date().toISOString(),
    });
    const componentRevision = {
      component_revision_id: makeId("component_revision"),
      component_id: component.component_id,
      source_task_revision_id: taskRevisionId,
      page_no: pageNo,
      bbox_json: component.bbox_json,
      extracted_text: task.stem || "",
      source_refs_json: task.source_refs_json || {},
      created_by: actor,
      created_at: new Date().toISOString(),
    };
    state.componentRevisions.push(componentRevision);
    component.current_revision_id = componentRevision.component_revision_id;
  }
}

// Import keeps the raw bundle on lesson_revision and rebuilds projections from it.
/**
 * 把外部准备好的课时 bundle 导入运行时模型。
 * 容器创建和版本灌入分开，便于迁移复用同一组内部步骤。
 */
export function importLessonDraftBundle(state, payload = {}) {
  let bundle = normalizeLessonDraftBundle(normalizeBundleImportPayload(payload), {
    runtimeRunId: payload.runtime_run_id || payload.runtimeRunId || "",
  });
  const releaseGateResult = applyReleaseGateToLessonDraftBundle(bundle, {
    allowListManifest:
      payload.allow_list_manifest ||
      payload.allowListManifest ||
      payload.release_decision_manifest ||
      payload.releaseDecisionManifest,
    requireReleaseDecision:
      payload.require_release_decision === true ||
      payload.requireReleaseDecision === true ||
      process.env.RUNTIME_REQUIRE_RELEASE_ALLOW_LIST === "1",
  });
  bundle = releaseGateResult.bundle;
  bundle.bundle_id = bundle.bundle_id || bundle.bundleId || `${bundle.lesson_id || bundle.lesson?.lesson_id || "lesson"}:bundle`;
  bundle.lesson_id = bundle.lesson_id || bundle.lesson?.lesson_id || makeId("lesson");
  bundle.title = bundle.title || bundle.lesson?.title || bundle.lesson?.lesson_title || bundle.lesson_id;
  bundle.subject = bundle.subject || bundle.lesson?.subject || null;
  bundle.stage = bundle.stage || bundle.lesson?.stage || null;
  bundle.grade = bundle.grade || bundle.lesson?.grade || null;
  bundle.season = bundle.season || bundle.lesson?.season || null;
  const trackScope = normalizeTrackScope(bundle);
  bundle.subject = trackScope.subject;
  bundle.stage = trackScope.stage;
  bundle.track_code = trackScope.track_code;
  validateLessonDraftBundle(bundle);
  const contentHash = computeHash(bundle);

  const sameImport = state.imports.find(
    (item) => item.bundle_id === bundle.bundle_id && item.content_hash === contentHash
  );
  if (sameImport) {
    const lineage = buildRuntimeImportLineage({
      releaseGate: releaseGateResult.releaseGate,
      runtimeImportId: sameImport.import_id || sameImport.artifact_id || "",
      createdAt: new Date().toISOString(),
    });
    return {
      importId: sameImport.import_id,
      runId: sameImport.run_id,
      lessonId: sameImport.lesson_id,
      lessonRevisionId: sameImport.lesson_revision_id,
      reviewTaskId: sameImport.review_task_id,
      idempotent: true,
      releaseGate: releaseGateResult.releaseGate,
      lineage,
    };
  }

  const { lesson, documentId } = ensureLessonContainers(state, bundle, payload.actor || "import_api");
  const nextRevisionNo =
    Math.max(
      0,
      ...state.lessonRevisions.filter((item) => item.lesson_id === lesson.lesson_id).map((item) => item.revision_no)
    ) + 1;
  const lessonRevisionId = `${lesson.lesson_id}:rev:${nextRevisionNo}`;
  const importId = makeId("import");
  const { run, job } = createRunJobPair(state, {
    runType: "import_lesson_draft_bundle",
    rootTargetType: "lesson",
    rootTargetId: lesson.lesson_id,
    subject: lesson.subject,
    jobType: "import_bundle",
    capability: "import",
    idempotencyKey: `${bundle.bundle_id}:${contentHash}`,
    actor: payload.actor || "import_api",
    payloadRef: `${lesson.lesson_id}/imports/${bundle.bundle_id}.json`,
  });
  const importArtifact = createArtifact(
    state,
    lesson,
    run.run_id,
    job.job_id,
    "lesson_draft_bundle",
    {
      lesson_id: lesson.lesson_id,
      bundle_id: bundle.bundle_id,
      content_hash: contentHash,
    }
  );
  state.lessonRevisions.push({
    lesson_revision_id: lessonRevisionId,
    lesson_id: lesson.lesson_id,
    base_artifact_id: importArtifact.artifact_id,
    generated_snapshot_ref: `${lesson.lesson_id}/imports/rev_${nextRevisionNo}.generated.json`,
    manual_patch_ref: null,
    merged_snapshot_ref: `${lesson.lesson_id}/imports/rev_${nextRevisionNo}.merged.json`,
    revision_no: nextRevisionNo,
    status: "reviewing",
    approval_status: "pending",
    bundle_jsonb: bundle,
    content_hash: contentHash,
    created_by: payload.actor || "import_api",
    created_at: new Date().toISOString(),
  });
  maybeFailpoint("import_after_lesson_revision_before_hydrate");

  hydrateRevisionFromBundle(
    state,
    lesson,
    documentId,
    lessonRevisionId,
    bundle,
    payload.actor || "import_api"
  );
  syncLessonRevisionBundle(state, lessonRevisionId);
  syncTaskProjectionForRevision(state, lessonRevisionId);
  // Import creates the first publishable revision artifacts so approve and publish stay decoupled.
  createArtifact(
    state,
    lesson,
    run.run_id,
    job.job_id,
    "source_tree_snapshot",
    {
      lesson_id: lesson.lesson_id,
      lesson_revision_id: lessonRevisionId,
      bundle_id: bundle.bundle_id,
      source_node_count: (bundle.source_tree || []).length || 1,
    },
    [importArtifact.artifact_id]
  );
  createArtifact(
    state,
    lesson,
    run.run_id,
    job.job_id,
    "task_bundle",
    {
      lesson_id: lesson.lesson_id,
      lesson_revision_id: lessonRevisionId,
      bundle_id: bundle.bundle_id,
      task_count: (bundle.tasks || []).length,
    },
    [importArtifact.artifact_id]
  );

  const reviewTask = {
    review_task_id: makeId("review_task"),
    target_type: "lesson_revision",
    target_revision_id: lessonRevisionId,
    run_id: run.run_id,
    status: "pending",
    assigned_to: null,
    requested_by: payload.actor || "import_api",
    changes_summary: `导入 ${bundle.bundle_id} 后生成新修订，待审核后发布。`,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };
  state.reviewTasks.push(reviewTask);
  state.imports.push({
    import_id: importId,
    bundle_id: bundle.bundle_id,
    content_hash: contentHash,
    lesson_id: lesson.lesson_id,
    lesson_revision_id: lessonRevisionId,
    run_id: run.run_id,
    review_task_id: reviewTask.review_task_id,
    artifact_id: importArtifact.artifact_id,
    created_at: new Date().toISOString(),
  });

  lesson.active_revision_id = lessonRevisionId;
  lesson.updated_at = new Date().toISOString();
  lesson.status = "reviewing";
  maybeFailpoint("import_after_hydrate_before_active_pointer");

  if (payload.writeQuestionBankCandidates) {
    for (const projection of state.taskProjections.filter(
      (item) => item.lesson_revision_id === lessonRevisionId
    )) {
      createQuestionBankItem(state, {
        taskProjectionId: projection.task_projection_id,
        actor: payload.actor || "import_api",
      });
    }
  }

  const lineage = buildRuntimeImportLineage({
    releaseGate: releaseGateResult.releaseGate,
    runtimeImportId: importId,
    createdAt: new Date().toISOString(),
  });

  return {
    importId,
    runId: run.run_id,
    lessonId: lesson.lesson_id,
    lessonRevisionId,
    reviewTaskId: reviewTask.review_task_id,
    artifactId: importArtifact.artifact_id,
    idempotent: false,
    releaseGate: releaseGateResult.releaseGate,
    lineage,
  };
}

export function createMaterialBuild(state, payload = {}) {
  const lesson = payload.lessonId
    ? state.lessons.find((item) => item.lesson_id === payload.lessonId)
    : null;
  const trackScope = normalizeTrackScope({
    track_code: payload.trackCode || payload.track_code || lesson?.track_code,
    subject: payload.subject || lesson?.subject,
    stage: payload.stage || lesson?.stage,
    grade: payload.grade || lesson?.grade,
  });
  const materialBuild = {
    material_build_id: makeId("material_build"),
    lesson_id: payload.lessonId || null,
    subject: trackScope.subject,
    stage: trackScope.stage,
    track_code: trackScope.track_code,
    teacher_name: payload.teacherName || null,
    build_name: payload.buildName || "未命名讲义",
    section_schema: payload.sectionSchema || [],
    target_variant: payload.targetVariant || "standard",
    status: "draft",
    created_by: payload.actor || "material_builder",
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };
  state.materialBuilds.push(materialBuild);
  return materialBuild;
}

export function addMaterialBuildItems(state, materialBuildId, payload = {}) {
  const materialBuild = state.materialBuilds.find((item) => item.material_build_id === materialBuildId);
  if (!materialBuild) {
    throw new Error("material_build_not_found");
  }

  const created = [];
  for (const item of payload.items || []) {
    const revision = state.questionBankItemRevisions.find(
      (row) => row.question_bank_item_revision_id === item.questionBankItemRevisionId
    );
    if (!revision) {
      throw new Error("question_bank_item_revision_not_found");
    }
    const owner = state.questionBankItems.find(
      (row) => row.question_bank_item_id === revision.question_bank_item_id
    );
    if (
      materialBuild.track_code &&
      owner?.track_code &&
      materialBuild.track_code !== owner.track_code
    ) {
      throw new Error("material_build_track_mismatch");
    }
    const materialItem = {
      material_item_id: makeId("material_item"),
      material_build_id: materialBuildId,
      question_bank_item_revision_id: revision.question_bank_item_revision_id,
      section_key: item.sectionKey || "body",
      placement_role: item.placementRole || "question",
      target_variant: item.targetVariant || materialBuild.target_variant,
      sort_index: item.sortIndex || created.length + 1,
      difficulty_override: item.difficultyOverride || null,
      include_answer: item.includeAnswer !== false,
      include_explanation: Boolean(item.includeExplanation),
      layout_hint_json: item.layoutHintJson || {},
      created_at: new Date().toISOString(),
    };
    state.materialItems.push(materialItem);
    created.push(materialItem);
  }

  materialBuild.updated_at = new Date().toISOString();
  return {
    materialBuild,
    items: created,
  };
}

export function exportMaterialBuild(state, materialBuildId, payload = {}) {
  const materialBuild = state.materialBuilds.find((item) => item.material_build_id === materialBuildId);
  if (!materialBuild) {
    throw new Error("material_build_not_found");
  }
  const lesson = materialBuild.lesson_id
    ? state.lessons.find((item) => item.lesson_id === materialBuild.lesson_id)
    : null;
  const { run, job } = createRunJobPair(state, {
    runType: "material_build_export",
    rootTargetType: "material_build",
    rootTargetId: materialBuildId,
    subject: lesson?.subject || materialBuild.subject || null,
    jobType: "material_build_export",
    capability: "export",
    idempotencyKey: `${materialBuildId}:export:${payload.actor || "material_builder"}`,
    actor: payload.actor || "material_builder",
    payloadRef: `${materialBuildId}/export_manifest.json`,
  });
  const artifact = createArtifact(
    state,
    lesson || {
      lesson_id: materialBuild.lesson_id || materialBuildId,
    },
    run.run_id,
    job.job_id,
    "material_build_export_manifest",
    {
      material_build_id: materialBuildId,
      material_item_count: state.materialItems.filter(
        (item) => item.material_build_id === materialBuildId
      ).length,
      publication_id: payload.publicationId || null,
    }
  );
  materialBuild.status = "exported";
  materialBuild.updated_at = new Date().toISOString();
  return {
    materialBuild,
    run,
    job,
    artifact,
  };
}

export function getComponentRevisions(state, componentId) {
  return state.componentRevisions
    .filter((item) => item.component_id === componentId)
    .sort((a, b) => String(a.created_at).localeCompare(String(b.created_at)));
}

export function getComponentPatch(state, patchId) {
  const patch = state.componentPatchCandidates.find((item) => item.component_patch_candidate_id === patchId);
  if (!patch) return null;
  return {
    patch,
    baseRevision: state.componentRevisions.find(
      (item) => item.component_revision_id === patch.base_component_revision_id
    ),
    proposedRevision: state.componentRevisions.find(
      (item) => item.component_revision_id === patch.proposed_component_revision_id
    ),
  };
}

export function rerunComponent(state, componentId, payload = {}) {
  const component = state.components.find((item) => item.component_id === componentId);
  if (!component) {
    throw new Error("component_not_found");
  }
  const baseRevision = state.componentRevisions.find(
    (item) => item.component_revision_id === component.current_revision_id
  );
  if (!baseRevision) {
    throw new Error("component_revision_not_found");
  }
  const componentLink = state.componentLinks.find(
    (item) =>
      item.component_id === componentId &&
      item.target_type === "task_revision" &&
      item.relation_type === "primary_visual_crop"
  );
  const sourceTaskRevision = state.taskRevisions.find(
    (item) => item.task_revision_id === componentLink?.target_revision_id
  );
  const lesson = sourceTaskRevision
    ? state.lessons.find(
        (item) =>
          item.lesson_id === state.tasks.find((task) => task.task_id === sourceTaskRevision.task_id)?.lesson_id
      )
    : null;
  const { run, job } = createRunJobPair(state, {
    runType: "component_rerun",
    rootTargetType: "component",
    rootTargetId: componentId,
    subject: lesson?.subject || null,
    jobType: "component_reextract",
    capability: "component_rerun",
    idempotencyKey: `${componentId}:${baseRevision.component_revision_id}:rerun`,
    actor: payload.actor || "component_reviewer",
    payloadRef: `${componentId}/rerun.json`,
  });
  const proposedRevision = {
    component_revision_id: makeId("component_revision"),
    component_id: componentId,
    source_task_revision_id: componentLink?.target_revision_id || null,
    page_no: baseRevision.page_no,
    bbox_json: baseRevision.bbox_json,
    extracted_text:
      payload.proposedText || `${baseRevision.extracted_text || ""}（局部重跑候选）`,
    source_refs_json: {
      ...baseRevision.source_refs_json,
      rerun_context: {
        actor: payload.actor || "component_reviewer",
        note: payload.note || null,
      },
    },
    created_by: payload.actor || "component_reviewer",
    created_at: new Date().toISOString(),
  };
  state.componentRevisions.push(proposedRevision);
  const patch = {
    component_patch_candidate_id: makeId("component_patch"),
    component_id: componentId,
    base_component_revision_id: baseRevision.component_revision_id,
    proposed_component_revision_id: proposedRevision.component_revision_id,
    target_task_revision_id: componentLink?.target_revision_id || null,
    run_id: run.run_id,
    status: "pending",
    diff_json: {
      before: baseRevision.extracted_text || "",
      after: proposedRevision.extracted_text || "",
    },
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    reviewed_by: null,
    accepted_lesson_revision_id: null,
  };
  state.componentPatchCandidates.push(patch);
  createArtifact(
    state,
    lesson || {
      lesson_id: componentId,
    },
    run.run_id,
    job.job_id,
    "component_patch_preview",
    {
      component_id: componentId,
      patch_id: patch.component_patch_candidate_id,
    }
  );
  return {
    run,
    job,
    patch,
    proposedRevision,
  };
}

export function applyComponentPatchDecision(state, patchId, action, actor = "component_reviewer") {
  const patch = state.componentPatchCandidates.find((item) => item.component_patch_candidate_id === patchId);
  if (!patch) {
    throw new Error("component_patch_not_found");
  }

  if (patch.status !== "pending") {
    throw new Error("component_patch_not_pending");
  }

  if (action === "reject") {
    patch.status = "rejected";
    patch.updated_at = new Date().toISOString();
    patch.reviewed_by = actor;
    return {
      patch,
    };
  }

  if (action !== "accept") {
    throw new Error("unsupported_component_patch_action");
  }

  const component = state.components.find((item) => item.component_id === patch.component_id);
  const proposedRevision = state.componentRevisions.find(
    (item) => item.component_revision_id === patch.proposed_component_revision_id
  );
  const baseTaskRevision = state.taskRevisions.find(
    (item) => item.task_revision_id === patch.target_task_revision_id
  );
  const task = state.tasks.find((item) => item.task_id === baseTaskRevision?.task_id);
  const lesson = state.lessons.find((item) => item.lesson_id === task?.lesson_id);
  if (!component || !proposedRevision || !baseTaskRevision || !task || !lesson) {
    throw new Error("component_patch_context_not_found");
  }
  if (component.current_revision_id !== patch.base_component_revision_id) {
    throw new Error("component_patch_conflict");
  }
  if (task.current_revision_id !== patch.target_task_revision_id) {
    throw new Error("component_patch_conflict");
  }

  maybeFailpoint("component_patch_accept_before_rerun");
  const rerunResult = rerunLesson(state, lesson.lesson_id, actor);
  const nextTaskRevision = state.taskRevisions.find(
    (item) =>
      item.task_id === task.task_id && item.lesson_revision_id === rerunResult.activeRevisionId
  );
  if (!nextTaskRevision) {
    throw new Error("rerun_task_revision_not_found");
  }

  nextTaskRevision.student_stem = proposedRevision.extracted_text;
  nextTaskRevision.teacher_stem = proposedRevision.extracted_text;
  component.current_revision_id = proposedRevision.component_revision_id;
  state.componentLinks.push({
    component_link_id: makeId("component_link"),
    component_id: component.component_id,
    target_type: "task_revision",
    target_revision_id: nextTaskRevision.task_revision_id,
    relation_type: "primary_visual_crop",
    created_at: new Date().toISOString(),
  });
  patch.status = "accepted";
  patch.updated_at = new Date().toISOString();
  patch.reviewed_by = actor;
  patch.accepted_lesson_revision_id = rerunResult.activeRevisionId;
  maybeFailpoint("component_patch_accept_after_rerun_before_projection");
  syncLessonRevisionBundle(state, rerunResult.activeRevisionId);
  syncTaskProjectionForRevision(state, rerunResult.activeRevisionId);
  return {
    patch,
    rerunResult,
    lessonRevision: state.lessonRevisions.find(
      (item) => item.lesson_revision_id === rerunResult.activeRevisionId
    ),
  };
}

/**
 * 把被遗弃的运行中任务标记为已恢复，方便操作者理解中断运行。
 * 恢复逻辑应保持保守：记录历史，但不凭空生成成功产物。
 */
export function recoverJobs(state, actor = "runtime_recovery", now = new Date().toISOString()) {
  const nowMs = Date.parse(now);
  const recovered = [];
  for (const job of state.jobs) {
    if (job.status !== "running") continue;
    const heartbeatExpired =
      job.heartbeat_at && nowMs - Date.parse(job.heartbeat_at) > 5 * 60 * 1000;
    const timeoutExpired = job.timeout_at && nowMs > Date.parse(job.timeout_at);
    if (!heartbeatExpired && !timeoutExpired) continue;
    job.status = "retry_wait";
    job.next_retry_at = now;
    job.updated_at = now;
    const latestAttempt = state.jobAttempts
      .filter((item) => item.job_id === job.job_id)
      .sort((a, b) => Number(b.attempt_no) - Number(a.attempt_no))[0];
    if (latestAttempt) {
      latestAttempt.finished_at = latestAttempt.finished_at || now;
      latestAttempt.status = "retry_wait";
      latestAttempt.error_detail_json = {
        recovered_by: actor,
        reason: heartbeatExpired ? "heartbeat_timeout" : "job_timeout",
      };
    }
    recovered.push(job);
  }
  return recovered;
}
