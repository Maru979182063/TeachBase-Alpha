import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { createEmptyState, recoverJobs } from "./runtime_backbone_store.mjs";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const workspaceRoot = path.resolve(__dirname, "..");
const baseUrl = process.env.RUNTIME_BACKBONE_BASE_URL || "http://127.0.0.1:8790";
const exportPayloadPath = path.join(
  workspaceRoot,
  "outputs",
  "split_builder",
  "mock_workbench",
  "export_runs",
  "_tmp",
  "2026-06-22T05-23-43-413Z_junior_g7_12_003.json"
);

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

async function fetchJson(url, options) {
  const response = await fetch(url, {
    headers: {
      "Content-Type": "application/json",
      ...(options?.headers || {}),
    },
    ...options,
  });
  const data = await response.json();
  if (!response.ok || data.ok === false) {
    throw new Error(`${response.status} ${url} ${data.error || "request_failed"}`);
  }
  return data;
}

async function main() {
  const results = [];
  const record = (name, detail) => {
    results.push({ name, detail });
  };

  const health = await fetchJson(`${baseUrl}/health`);
  assert(health.runtimeMode === "file", "health should expose file mode during local validation");
  record("health", {
    runtimeMode: health.runtimeMode,
    taskProjectionCount: health.runtime.taskProjectionCount,
  });

  const lessons = await fetchJson(`${baseUrl}/api/runtime/lessons`);
  const lesson = lessons.items.find((item) => item.lesson_id === "junior_g7_12_003");
  assert(lesson, "seed lesson junior_g7_12_003 should exist");
  record("lesson_list", {
    lessonId: lesson.lesson_id,
    publishedRevisionId: lesson.published_revision_id,
  });

  const initialDetail = await fetchJson(`${baseUrl}/api/runtime/lessons/${lesson.lesson_id}`);
  const baseBundle = structuredClone(
    initialDetail.detail.lessonRevisions.find(
      (item) => item.lesson_revision_id === initialDetail.detail.lesson.active_revision_id
    ).bundle_jsonb
  );
  const oldPublishedRevisionId = initialDetail.detail.lesson.published_revision_id;

  const projectionSearch = await fetchJson(
    `${baseUrl}/api/runtime/task-projections/search?subject=${encodeURIComponent("数学")}&publishedOnly=true&q=${encodeURIComponent("方程")}`
  );
  assert(projectionSearch.items.length > 0, "task projection search should return published items");
  record("task_projection_search", {
    hitCount: projectionSearch.items.length,
    firstProjectionId: projectionSearch.items[0].task_projection_id,
  });

  const importBundle = structuredClone(baseBundle);
  importBundle.bundle_id = `validation_bundle_${Date.now()}`;
  importBundle.tasks[0].stem = `${importBundle.tasks[0].stem} [验证导入A]`;

  const importResult = await fetchJson(`${baseUrl}/api/runtime/imports/lesson-draft-bundles`, {
    method: "POST",
    body: JSON.stringify({
      actor: "validation_suite",
      bundle: importBundle,
    }),
  });
  assert(importResult.result.idempotent === false, "first import should create a new revision");
  record("import_bundle", importResult.result);

  const approveResult = await fetchJson(
    `${baseUrl}/api/runtime/review-tasks/${importResult.result.reviewTaskId}/approve`,
    {
      method: "POST",
      body: JSON.stringify({
        actor: "validation_suite",
      }),
    }
  );
  assert(approveResult.result.reviewTask.status === "approved", "review task should become approved");

  const afterApprove = await fetchJson(`${baseUrl}/api/runtime/lessons/${lesson.lesson_id}`);
  assert(
    afterApprove.detail.lesson.published_revision_id === oldPublishedRevisionId,
    "approve should not change published revision"
  );
  record("approve_without_publish", {
    publishedRevisionId: afterApprove.detail.lesson.published_revision_id,
    approvedRevisionId: importResult.result.lessonRevisionId,
  });

  const publishResult = await fetchJson(
    `${baseUrl}/api/runtime/lessons/${lesson.lesson_id}/publish`,
    {
      method: "POST",
      body: JSON.stringify({
        actor: "validation_suite",
        lessonRevisionId: importResult.result.lessonRevisionId,
      }),
    }
  );
  assert(
    publishResult.result.lesson.published_revision_id === importResult.result.lessonRevisionId,
    "publish should switch published revision"
  );
  record("publish_revision", {
    publicationId: publishResult.result.publication.publication_id,
    publishedRevisionId: publishResult.result.lesson.published_revision_id,
  });

  const idempotentImport = await fetchJson(`${baseUrl}/api/runtime/imports/lesson-draft-bundles`, {
    method: "POST",
    body: JSON.stringify({
      actor: "validation_suite",
      bundle: importBundle,
    }),
  });
  assert(idempotentImport.result.idempotent === true, "same bundle and hash should be idempotent");
  record("import_idempotent", idempotentImport.result);

  const modifiedBundle = structuredClone(importBundle);
  modifiedBundle.tasks[0].stem = `${modifiedBundle.tasks[0].stem} [验证改动B]`;
  const changedImport = await fetchJson(`${baseUrl}/api/runtime/imports/lesson-draft-bundles`, {
    method: "POST",
    body: JSON.stringify({
      actor: "validation_suite",
      bundle: modifiedBundle,
    }),
  });
  assert(
    changedImport.result.lessonRevisionId !== importResult.result.lessonRevisionId,
    "changed bundle content should create a new revision"
  );
  record("import_changed_bundle", changedImport.result);

  const questionBankCreate = await fetchJson(`${baseUrl}/api/question-bank/items`, {
    method: "POST",
    body: JSON.stringify({
      actor: "validation_suite",
      taskProjectionId: projectionSearch.items[0].task_projection_id,
    }),
  });
  record("question_bank_create", {
    itemId: questionBankCreate.result.item.question_bank_item_id,
    revisionId: questionBankCreate.result.revision.question_bank_item_revision_id,
  });

  const questionBankSearch = await fetchJson(
    `${baseUrl}/api/question-bank/search?q=${encodeURIComponent("方程")}`
  );
  assert(questionBankSearch.items.length > 0, "question bank search should return inserted item");
  record("question_bank_search", {
    hitCount: questionBankSearch.items.length,
  });

  const materialBuildCreate = await fetchJson(`${baseUrl}/api/material-builds`, {
    method: "POST",
    body: JSON.stringify({
      actor: "validation_suite",
      lessonId: lesson.lesson_id,
      teacherName: "验证老师",
      buildName: "验证落版讲义",
      targetVariant: "standard",
    }),
  });
  const materialBuildId = materialBuildCreate.result.material_build_id;
  const materialItems = await fetchJson(`${baseUrl}/api/material-builds/${materialBuildId}/items`, {
    method: "POST",
    body: JSON.stringify({
      items: [
        {
          questionBankItemRevisionId:
            questionBankCreate.result.revision.question_bank_item_revision_id,
          sectionKey: "warmup",
          placementRole: "question",
          sortIndex: 1,
          includeAnswer: true,
          includeExplanation: true,
        },
      ],
    }),
  });
  const materialExport = await fetchJson(`${baseUrl}/api/material-builds/${materialBuildId}/export`, {
    method: "POST",
    body: JSON.stringify({
      actor: "validation_suite",
      publicationId: publishResult.result.publication.publication_id,
    }),
  });
  record("material_build", {
    materialBuildId,
    materialItemCount: materialItems.result.items.length,
    exportArtifactId: materialExport.result.artifact.artifact_id,
  });

  const detailForComponent = await fetchJson(`${baseUrl}/api/runtime/lessons/${lesson.lesson_id}`);
  const componentId = detailForComponent.detail.componentRevisions[0]?.component_id;
  assert(componentId, "component revision should exist for rerun validation");

  const componentRerun = await fetchJson(`${baseUrl}/api/runtime/components/${componentId}/rerun`, {
    method: "POST",
    body: JSON.stringify({
      actor: "validation_suite",
      proposedText: "验证局部重跑文本",
      note: "validation patch",
    }),
  });
  const patchId = componentRerun.result.patch.component_patch_candidate_id;
  const patchDetail = await fetchJson(`${baseUrl}/api/runtime/component-patches/${patchId}`);
  assert(patchDetail.detail.patch.status === "pending", "component patch should start pending");
  const patchAccept = await fetchJson(`${baseUrl}/api/runtime/component-patches/${patchId}/accept`, {
    method: "POST",
    body: JSON.stringify({
      actor: "validation_suite",
    }),
  });
  assert(
    patchAccept.result.patch.status === "accepted",
    "accepted component patch should update patch status"
  );
  record("component_rerun_accept", {
    patchId,
    rerunRevisionId: patchAccept.result.rerunResult.activeRevisionId,
  });

  const exportPayload = JSON.parse(fs.readFileSync(exportPayloadPath, "utf8"));
  const exportResult = await fetchJson(`${baseUrl}/api/export/generate`, {
    method: "POST",
    body: JSON.stringify(exportPayload),
  });
  const lineage = await fetchJson(
    `${baseUrl}/api/runtime/artifacts/${exportResult.item.runtime.exportArtifactId}/lineage`
  );
  assert(lineage.detail.nodes.length >= 1, "export artifact lineage should exist");
  record("export_and_lineage", {
    exportRunId: exportResult.item.runtime.runId,
    lineageNodeCount: lineage.detail.nodes.length,
  });

  const recoveryState = createEmptyState();
  recoveryState.jobs.push({
    job_id: "job_validation_recover",
    run_id: "run_validation_recover",
    job_type: "validation_job",
    status: "running",
    heartbeat_at: new Date(Date.now() - 10 * 60 * 1000).toISOString(),
    timeout_at: new Date(Date.now() - 60 * 1000).toISOString(),
    updated_at: new Date().toISOString(),
  });
  recoveryState.jobAttempts.push({
    job_attempt_id: "attempt_validation_recover",
    job_id: "job_validation_recover",
    attempt_no: 1,
    started_at: new Date(Date.now() - 10 * 60 * 1000).toISOString(),
    heartbeat_at: new Date(Date.now() - 10 * 60 * 1000).toISOString(),
    finished_at: null,
    status: "running",
    error_detail_json: null,
    worker_ref: "validation_suite",
  });
  const recovered = recoverJobs(recoveryState, "validation_suite");
  assert(recovered.length === 1, "recoverJobs should move stalled running jobs to retry_wait");
  record("recover_jobs_unit", {
    recoveredJobId: recovered[0].job_id,
    recoveredStatus: recovered[0].status,
  });

  console.log(JSON.stringify({ ok: true, checks: results }, null, 2));
}

main().catch((error) => {
  console.error(JSON.stringify({ ok: false, error: String(error?.message || error) }, null, 2));
  process.exitCode = 1;
});
