import fs from "fs";
import path from "path";
import vm from "vm";
import { randomUUID } from "crypto";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const workspaceRoot = path.resolve(__dirname, "..");
const runtimeRoot = path.join(workspaceRoot, "outputs", "runtime_backbone_demo");
const statePath = path.join(runtimeRoot, "state.json");
const workbenchDataPath = path.join(
  workspaceRoot,
  "outputs",
  "split_builder",
  "mock_workbench",
  "workbench_data.js"
);

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
    jobDependencies: [],
    outboxEvents: [],
    artifacts: [],
    artifactDependencies: [],
    lessons: [],
    lessonRevisions: [],
    pageAssets: [],
    components: [],
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
  const code = fs.readFileSync(workbenchDataPath, "utf8");
  const sandbox = { window: {} };
  vm.createContext(sandbox);
  vm.runInContext(code, sandbox);
  return sandbox.window.WORKBENCH_DATA;
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
  const lessonId = splitLesson.lesson_id;
  const documentSourceId = makeId("source");
  state.documentSources.push({
    source_id: documentSourceId,
    source_type: "mock_workbench_seed",
    subject: splitLesson.subject,
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
    subject: splitLesson.subject,
    stage: splitLesson.stage,
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
    subject: splitLesson.subject,
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
    subject: splitLesson.subject,
    stage: splitLesson.stage,
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

  const { catalog, version } = ensureCatalog(state, splitLesson);
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
      subject: splitLesson.subject,
      plugin_id: "subject.math.seed",
      plugin_version: "0.1",
      schema_version: "0.1",
      payload_json: {
        checkpoint: question.checkpoint,
        component_kind: question.componentKind,
        component_label: question.componentLabel,
        local_number: question.localNumber,
        source_page: question.sourcePage,
        text_storage_mode: question.textStorageMode,
        review_status: question.reviewStatus,
        visual_stats: question.visualStats || {},
      },
      risk_flags: question.riskIssues || [],
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    });

    const checkpointNode = state.checkpointNodes.find(
      (item) => item.catalog_version_id === version.catalog_version_id && item.name === checkpointName
    );
    if (checkpointNode) {
      state.taskCheckpointOverrides.push({
        override_id: makeId("task_checkpoint_override"),
        task_revision_id: taskRevisionId,
        checkpoint_node_id: checkpointNode.checkpoint_node_id,
        relation_type: "main",
        confidence: question.risk === "高风险" ? 0.74 : question.risk === "中风险" ? 0.88 : 0.96,
        mapping_source: "seed_question_checkpoint",
        reason: question.checkpoint,
        created_at: new Date().toISOString(),
      });
    }

    const queueItem = reviewQueue.find((item) => item.questionId === question.id);
    if (queueItem || question.risk !== "低风险") {
      state.reviewTasks.push({
        review_task_id: queueItem?.id || makeId("review_task"),
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

export function buildSeedState() {
  const data = loadWorkbenchData();
  const state = createEmptyState();
  state.meta.generatedAt = data.generatedAt || new Date().toISOString();
  state.meta.updatedAt = new Date().toISOString();
  state.meta.source = "workbench_data_seed";

  const splitLessons = Object.values(data.splitLessons || {});
  const reviewQueue = data.reviewQueue || [];
  for (const splitLesson of splitLessons) {
    buildLessonSeed(
      state,
      splitLesson,
      reviewQueue.filter((item) => item.lessonId === splitLesson.lesson_id)
    );
  }
  return state;
}

export function loadState() {
  return safeReadJson(statePath, createEmptyState());
}

export function saveState(state) {
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
    componentCount: state.components.length,
    pageAssetCount: state.pageAssets.length,
  };
}

export function listLessons(state) {
  return state.lessons.map((lesson) => {
    const activeRevision = state.lessonRevisions.find((item) => item.lesson_revision_id === lesson.active_revision_id);
    const publishedRevision = state.lessonRevisions.find((item) => item.lesson_revision_id === lesson.published_revision_id);
    const taskCount = state.tasks.filter((item) => item.lesson_id === lesson.lesson_id).length;
    const reviewTaskCount = state.reviewTasks.filter((item) => item.target_revision_id.startsWith(`${lesson.lesson_id}:task:`)).length;
    return {
      ...lesson,
      activeRevision,
      publishedRevision,
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
    checkpointLinks,
    taskCheckpointOverrides,
    reviewTasks,
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

function findLatestValidLessonArtifact(state, lessonId, artifactTypes) {
  const candidates = state.artifacts
    .filter(
      (item) =>
        item.summary_json?.lesson_id === lessonId &&
        item.lifecycle_status === "valid" &&
        artifactTypes.includes(item.artifact_type)
    )
    .sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)));
  return candidates[0] || null;
}

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
    ]) || null;

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
    export_history_id: historyItem.id,
    file_count: historyItem.fileCount,
    versions: historyItem.versions || [],
    audiences: historyItem.audiences || [],
    formats: historyItem.formats || [],
    include_compass: Boolean(historyItem.includeCompass),
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

  markArtifactChainStale(state, lessonId, ["source_tree_snapshot", "task_bundle", "reviewed_publishable_bundle"]);
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
        lessonRevision.status = "published";
        const lesson = state.lessons.find((item) => item.lesson_id === lessonRevision.lesson_id);
        if (lesson) {
          lesson.published_revision_id = lessonRevision.lesson_revision_id;
          lesson.status = "published";
          lesson.updated_at = new Date().toISOString();
        }
      }
      reviewTask.status = "published";
    }
  } else if (action === "request_changes") {
    reviewTask.status = "changes_requested";
    reviewTask.updated_at = new Date().toISOString();
  } else {
    throw new Error("unsupported_review_action");
  }

  return {
    reviewTask,
    actor,
  };
}
