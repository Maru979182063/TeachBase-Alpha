/**
 * 用途：
 * - 实现 Postgres 支撑的运行时存储，包括迁移、仓库接线和生命周期辅助。
 * - 后端特定持久化规则放在这里，共享语义放在存储接口和契约测试中。
 */

import fs from "fs";
import path from "path";
import { Pool } from "pg";
import { fileURLToPath } from "url";
import {
  addMaterialBuildItems,
  applyComponentPatchDecision,
  computeContentHash,
  createMaterialBuild,
  createQuestionBankItem,
  exportMaterialBuild,
  getArtifactLineage,
  getComponentPatch,
  getComponentRevisions,
  getLessonDetail,
  getRunDetail,
  getSummary,
  importLessonDraftBundle,
  listLessons,
  publishLessonRevision,
  recoverJobs,
  registerExportRun,
  rerunComponent,
  rerunLesson,
  searchQuestionBank,
  searchTaskProjections,
  updateReviewTaskStatus,
} from "./runtime_backbone_store.mjs";
import {
  buildActualTableReport,
  buildExpectedTableReport,
  cloneRuntimeState,
  ensureSeedRuntimeState,
  loadRuntimeState,
  persistRuntimeState,
  reseedRuntimeState,
} from "../runtime/postgres/state_repository.mjs";
import {
  readSnapshotInfo,
  writeSnapshotBestEffort,
} from "../runtime/postgres/snapshot_repository.mjs";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const workspaceRoot = path.resolve(__dirname, "..");
const migrationPaths = [
  path.join(
    workspaceRoot,
    "config",
    "migrations",
    "20260623_runtime_backbone_validation.sql"
  ),
  path.join(
    workspaceRoot,
    "config",
    "migrations",
    "20260623_postgres_sole_source.sql"
  ),
];

function parseBooleanFlag(value, fallback) {
  if (value === undefined || value === null || value === "") {
    return fallback;
  }
  return !["0", "false", "no", "off"].includes(String(value).trim().toLowerCase());
}

/**
 * 应用定义 Postgres 运行时状态的 SQL 迁移。
 * 迁移在仓库调用前执行，让存储构造过程自包含。
 */
async function runMigrations(pool) {
  for (const migrationPath of migrationPaths) {
    const migrationSql = fs.readFileSync(migrationPath, "utf8");
    await pool.query(migrationSql);
  }
}

/**
 * 用 Postgres 表镜像文件存储运行时契约的存储实现。
 * 方法大多委托给仓库辅助函数，让事务处理更容易审计。
 */
export class PostgresRuntimeBackboneStore {
  constructor(options = {}) {
    this.mode = "postgres";
    this.connectionString =
      options.connectionString ||
      process.env.DATABASE_URL_TEST ||
      process.env.RUNTIME_BACKBONE_DATABASE_URL ||
      process.env.DATABASE_URL ||
      null;
    this.snapshotKey = options.snapshotKey || "default";
    this.soleSourceEnabled = parseBooleanFlag(
      options.soleSourceEnabled ?? process.env.POSTGRES_SOLE_SOURCE,
      true
    );
    this.debugSnapshotEnabled = parseBooleanFlag(
      options.debugSnapshotEnabled ?? process.env.RUNTIME_POSTGRES_EMIT_DEBUG_SNAPSHOT,
      false
    );
    this.pool = null;
    this.migrationVersion = "20260623_postgres_sole_source.sql";
    this.lastConsistencyReport = null;
    this.lastSnapshotStatus = {
      status: this.debugSnapshotEnabled ? "idle" : "disabled",
    };
    this.lastMutationStats = [];
  }

  async init() {
    if (!this.connectionString) {
      throw new Error("postgres_store_requires_DATABASE_URL");
    }
    if (!this.soleSourceEnabled) {
      throw new Error("postgres_sole_source_required");
    }

    this.pool = new Pool({
      connectionString: this.connectionString,
    });
    await runMigrations(this.pool);

    const client = await this.pool.connect();
    try {
      await client.query("begin");
      await ensureSeedRuntimeState(client, this.snapshotKey);
      await client.query("commit");
    } catch (error) {
      await client.query("rollback");
      throw error;
    } finally {
      client.release();
    }

    this.lastConsistencyReport = await this.getConsistencyReport();
  }

  async refreshDebugSnapshot(state) {
    // Snapshot is intentionally best-effort: normalized tables are the business
    // source of truth, so debug snapshot failure must never poison the write path.
    this.lastSnapshotStatus = await writeSnapshotBestEffort(
      this.pool,
      this.snapshotKey,
      state,
      this.debugSnapshotEnabled
    );
    return this.lastSnapshotStatus;
  }

  async readState() {
    const state = await loadRuntimeState(this.pool, this.snapshotKey);
    recoverJobs(state);
    return state;
  }

  async mutateState(mutator) {
    const client = await this.pool.connect();
    let nextState = null;
    try {
      await client.query("begin");
      // Validation-stage writes still reuse the pure state mutators, so we keep
      // one advisory lock to avoid lost updates until hot paths are fully split.
      await client.query("select pg_advisory_xact_lock(hashtext($1))", [this.snapshotKey]);
      const previousState = await loadRuntimeState(client, this.snapshotKey);
      nextState = cloneRuntimeState(previousState);
      recoverJobs(nextState);
      const result = await mutator(nextState);
      nextState.meta.generatedAt =
        nextState.meta.generatedAt || previousState.meta.generatedAt || new Date().toISOString();
      nextState.meta.updatedAt = new Date().toISOString();
      nextState.meta.source = nextState.meta.source || previousState.meta.source || "postgres_normalized_tables";
      const persistence = await persistRuntimeState(client, previousState, nextState, this.snapshotKey);
      await client.query("commit");
      this.lastConsistencyReport = null;
      this.lastMutationStats = persistence.tableStats;
      await this.refreshDebugSnapshot(nextState);
      return result;
    } catch (error) {
      await client.query("rollback");
      throw error;
    } finally {
      client.release();
    }
  }

  async bootstrap() {
    const client = await this.pool.connect();
    try {
      await client.query("begin");
      await client.query("select pg_advisory_xact_lock(hashtext($1))", [this.snapshotKey]);
      const reseeded = await reseedRuntimeState(client, this.snapshotKey);
      await client.query("commit");
      this.lastConsistencyReport = null;
      this.lastMutationStats = reseeded.persistence.tableStats;
      await this.refreshDebugSnapshot(reseeded.state);
      return {
        ok: true,
        summary: getSummary(reseeded.state),
      };
    } catch (error) {
      await client.query("rollback");
      throw error;
    } finally {
      client.release();
    }
  }

  async getSummary() {
    return getSummary(await this.readState());
  }

  async listLessons() {
    return listLessons(await this.readState());
  }

  async getLessonDetail(lessonId) {
    return getLessonDetail(await this.readState(), lessonId);
  }

  async rerunLesson(lessonId, actor) {
    return this.mutateState(async (state) => ({
      result: rerunLesson(state, lessonId, actor),
      lesson: getLessonDetail(state, lessonId),
    }));
  }

  async publishLesson(lessonId, actor, options) {
    return this.mutateState(async (state) => publishLessonRevision(state, lessonId, actor, options));
  }

  async importLessonDraftBundle(payload) {
    return this.mutateState(async (state) => importLessonDraftBundle(state, payload));
  }

  async listRuns() {
    return (await this.readState()).runs;
  }

  async getRunDetail(runId) {
    return getRunDetail(await this.readState(), runId);
  }

  async listReviewTasks(status) {
    const state = await this.readState();
    return status ? state.reviewTasks.filter((item) => item.status === status) : state.reviewTasks;
  }

  async approveReviewTask(reviewTaskId, actor) {
    return this.mutateState(async (state) =>
      updateReviewTaskStatus(state, reviewTaskId, "approve", actor)
    );
  }

  async requestReviewChanges(reviewTaskId, actor) {
    return this.mutateState(async (state) =>
      updateReviewTaskStatus(state, reviewTaskId, "request_changes", actor)
    );
  }

  async getArtifactLineage(artifactId) {
    return getArtifactLineage(await this.readState(), artifactId);
  }

  async searchTaskProjections(filters) {
    return searchTaskProjections(await this.readState(), filters);
  }

  async searchQuestionBank(filters) {
    return searchQuestionBank(await this.readState(), filters);
  }

  async createQuestionBankItem(payload) {
    return this.mutateState(async (state) => createQuestionBankItem(state, payload));
  }

  async createMaterialBuild(payload) {
    return this.mutateState(async (state) => createMaterialBuild(state, payload));
  }

  async addMaterialBuildItems(materialBuildId, payload) {
    return this.mutateState(async (state) => addMaterialBuildItems(state, materialBuildId, payload));
  }

  async exportMaterialBuild(materialBuildId, payload) {
    return this.mutateState(async (state) => exportMaterialBuild(state, materialBuildId, payload));
  }

  async rerunComponent(componentId, payload) {
    return this.mutateState(async (state) => rerunComponent(state, componentId, payload));
  }

  async listComponentRevisions(componentId) {
    return getComponentRevisions(await this.readState(), componentId);
  }

  async getComponentPatch(patchId) {
    return getComponentPatch(await this.readState(), patchId);
  }

  async acceptComponentPatch(patchId, actor) {
    return this.mutateState(async (state) => applyComponentPatchDecision(state, patchId, "accept", actor));
  }

  async rejectComponentPatch(patchId, actor) {
    return this.mutateState(async (state) => applyComponentPatchDecision(state, patchId, "reject", actor));
  }

  async registerExportRun(payload, historyItem) {
    return this.mutateState(async (state) => registerExportRun(state, payload, historyItem));
  }

  async recoverJobs(actor) {
    return this.mutateState(async (state) => recoverJobs(state, actor));
  }

  async getDebugState() {
    return this.readState();
  }

  async getConsistencyReport() {
    const client = await this.pool.connect();
    try {
      const state = await loadRuntimeState(client, this.snapshotKey);
      const expectedTables = buildExpectedTableReport(state);
      const actualTables = await buildActualTableReport(client);
      const mismatches = [];

      for (const [table, expected] of Object.entries(expectedTables)) {
        const actual = actualTables[table];
        if (!actual || expected.count !== actual.count || expected.hash !== actual.hash) {
          mismatches.push({
            table,
            expectedCount: expected.count,
            actualCount: actual?.count ?? null,
            expectedHash: expected.hash,
            actualHash: actual?.hash ?? null,
          });
        }
      }

      const snapshotInfo = await readSnapshotInfo(client, this.snapshotKey);
      const computedSnapshotHash = computeContentHash(state);
      const snapshotStatus = !snapshotInfo.present
        ? "missing"
        : !snapshotInfo.snapshotContentHash
          ? "present_without_hash"
          : snapshotInfo.snapshotContentHash === computedSnapshotHash
            ? "matching"
            : "stale";

      const report = {
        ok: mismatches.length === 0,
        status: mismatches.length === 0 ? "ok" : "degraded",
        checkedAt: new Date().toISOString(),
        snapshotKey: this.snapshotKey,
        sourceOfTruth: {
          mode: "normalized_tables",
          snapshotRole: "debug_only",
          soleSourceEnabled: this.soleSourceEnabled,
        },
        snapshotVersion: snapshotInfo.snapshotVersion,
        snapshotContentHash: snapshotInfo.snapshotContentHash,
        computedSnapshotHash,
        snapshotHashMatches: snapshotStatus !== "stale",
        snapshotStatus,
        snapshotUpdatedAt: snapshotInfo.updatedAt,
        debugSnapshotMirror: this.lastSnapshotStatus,
        mismatches,
        tables: Object.fromEntries(
          Object.keys(expectedTables).map((table) => [
            table,
            {
              ...expectedTables[table],
              actualCount: actualTables[table]?.count ?? null,
              actualHash: actualTables[table]?.hash ?? null,
            },
          ])
        ),
      };
      this.lastConsistencyReport = report;
      return report;
    } finally {
      client.release();
    }
  }

  async getHealth() {
    const status = {
      runtimeMode: this.mode,
      database: {
        status: "connected",
        engine: "postgres",
      },
      migrationVersion: this.migrationVersion,
      sourceOfTruth: {
        mode: "normalized_tables",
        soleSourceEnabled: this.soleSourceEnabled,
        snapshotRole: "debug_only",
      },
      debugSnapshotMirror: this.lastSnapshotStatus,
      lastMutationStats: this.lastMutationStats,
      consistency: this.lastConsistencyReport
        ? {
            status: this.lastConsistencyReport.status,
            checkedAt: this.lastConsistencyReport.checkedAt,
            mismatchCount: this.lastConsistencyReport.mismatches.length,
          }
        : {
            status: "unknown",
            checkedAt: null,
            mismatchCount: null,
          },
    };
    try {
      const result = await this.pool.query("select current_database() as database_name");
      status.database.databaseName = result.rows[0]?.database_name || null;
    } catch {
      status.database.status = "degraded";
    }
    if (status.consistency.status === "degraded") {
      status.database.status = "degraded";
    }
    return status;
  }

  async close() {
    if (this.pool) {
      await this.pool.end();
    }
  }
}
