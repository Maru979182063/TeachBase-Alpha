/**
 * Purpose:
 * - Selects and constructs the active runtime store implementation.
 * - Callers should depend on this interface layer so backend swaps stay localized.
 */

import {
  addMaterialBuildItems,
  applyComponentPatchDecision,
  createMaterialBuild,
  createQuestionBankItem,
  ensureSeededState,
  exportMaterialBuild,
  getArtifactLineage,
  getComponentPatch,
  getComponentRevisions,
  getLessonDetail,
  getRunDetail,
  getSummary,
  importLessonDraftBundle,
  listLessons,
  loadState,
  publishLessonRevision,
  recoverJobs,
  registerExportRun,
  reseedState,
  rerunComponent,
  rerunLesson,
  saveState,
  searchQuestionBank,
  searchTaskProjections,
  updateReviewTaskStatus,
} from "./runtime_backbone_store.mjs";

class FileRuntimeBackboneStore {
  constructor() {
    this.mode = "file";
    this.migrationVersion = "file-store";
  }

  readState() {
    const state = loadState();
    recoverJobs(state);
    return state;
  }

  writeState(mutator) {
    const state = this.readState();
    const result = mutator(state);
    saveState(state);
    return result;
  }

  bootstrap() {
    const state = reseedState();
    return {
      ok: true,
      summary: getSummary(state),
    };
  }

  getSummary() {
    return getSummary(this.readState());
  }

  listLessons() {
    return listLessons(this.readState());
  }

  getLessonDetail(lessonId) {
    return getLessonDetail(this.readState(), lessonId);
  }

  rerunLesson(lessonId, actor) {
    return this.writeState((state) => ({
      result: rerunLesson(state, lessonId, actor),
      lesson: getLessonDetail(state, lessonId),
    }));
  }

  publishLesson(lessonId, actor, options) {
    return this.writeState((state) => publishLessonRevision(state, lessonId, actor, options));
  }

  importLessonDraftBundle(payload) {
    return this.writeState((state) => importLessonDraftBundle(state, payload));
  }

  listRuns() {
    return this.readState().runs;
  }

  getRunDetail(runId) {
    return getRunDetail(this.readState(), runId);
  }

  listReviewTasks(status) {
    const state = this.readState();
    return status ? state.reviewTasks.filter((item) => item.status === status) : state.reviewTasks;
  }

  approveReviewTask(reviewTaskId, actor) {
    return this.writeState((state) => updateReviewTaskStatus(state, reviewTaskId, "approve", actor));
  }

  requestReviewChanges(reviewTaskId, actor) {
    return this.writeState((state) =>
      updateReviewTaskStatus(state, reviewTaskId, "request_changes", actor)
    );
  }

  getArtifactLineage(artifactId) {
    return getArtifactLineage(this.readState(), artifactId);
  }

  searchTaskProjections(filters) {
    return searchTaskProjections(this.readState(), filters);
  }

  searchQuestionBank(filters) {
    return searchQuestionBank(this.readState(), filters);
  }

  createQuestionBankItem(payload) {
    return this.writeState((state) => createQuestionBankItem(state, payload));
  }

  createMaterialBuild(payload) {
    return this.writeState((state) => createMaterialBuild(state, payload));
  }

  addMaterialBuildItems(materialBuildId, payload) {
    return this.writeState((state) => addMaterialBuildItems(state, materialBuildId, payload));
  }

  exportMaterialBuild(materialBuildId, payload) {
    return this.writeState((state) => exportMaterialBuild(state, materialBuildId, payload));
  }

  rerunComponent(componentId, payload) {
    return this.writeState((state) => rerunComponent(state, componentId, payload));
  }

  listComponentRevisions(componentId) {
    return getComponentRevisions(this.readState(), componentId);
  }

  getComponentPatch(patchId) {
    return getComponentPatch(this.readState(), patchId);
  }

  acceptComponentPatch(patchId, actor) {
    return this.writeState((state) => applyComponentPatchDecision(state, patchId, "accept", actor));
  }

  rejectComponentPatch(patchId, actor) {
    return this.writeState((state) => applyComponentPatchDecision(state, patchId, "reject", actor));
  }

  registerExportRun(payload, historyItem) {
    return this.writeState((state) => registerExportRun(state, payload, historyItem));
  }

  recoverJobs(actor) {
    return this.writeState((state) => recoverJobs(state, actor));
  }

  getDebugState() {
    return this.readState();
  }

  getHealth() {
    return {
      runtimeMode: this.mode,
      database: {
        status: "not_applicable",
        engine: "json_file",
      },
      migrationVersion: this.migrationVersion,
    };
  }

  getConsistencyReport() {
    const state = this.readState();
    return {
      ok: true,
      status: "ok",
      checkedAt: new Date().toISOString(),
      snapshotKey: "file-store",
      snapshotVersion: null,
      snapshotContentHash: null,
      computedSnapshotHash: null,
      snapshotHashMatches: true,
      mismatches: [],
      tables: {
        lesson: { count: state.lessons.length, actualCount: state.lessons.length },
        lesson_revision: {
          count: state.lessonRevisions.length,
          actualCount: state.lessonRevisions.length,
        },
        task_projection: {
          count: state.taskProjections.length,
          actualCount: state.taskProjections.length,
        },
        publication: {
          count: state.publications.length,
          actualCount: state.publications.length,
        },
        question_bank_item_revision: {
          count: state.questionBankItemRevisions.length,
          actualCount: state.questionBankItemRevisions.length,
        },
        material_item: {
          count: state.materialItems.length,
          actualCount: state.materialItems.length,
        },
        component_revision: {
          count: state.componentRevisions.length,
          actualCount: state.componentRevisions.length,
        },
        run: { count: state.runs.length, actualCount: state.runs.length },
        job: { count: state.jobs.length, actualCount: state.jobs.length },
        artifact: { count: state.artifacts.length, actualCount: state.artifacts.length },
      },
    };
  }

  async close() {
    return undefined;
  }
}

export async function createRuntimeBackboneStore(options = {}) {
  const mode =
    options.mode ||
    process.env.RUNTIME_BACKBONE_STORE ||
    process.env.RUNTIME_STORE ||
    "file";
  if (mode === "postgres") {
    const { PostgresRuntimeBackboneStore } = await import("./runtime_backbone_postgres_store.mjs");
    const store = new PostgresRuntimeBackboneStore(options);
    await store.init();
    return store;
  }
  if (mode !== "file") {
    throw new Error(`unsupported_runtime_store:${mode}`);
  }

  ensureSeededState();
  return new FileRuntimeBackboneStore();
}
