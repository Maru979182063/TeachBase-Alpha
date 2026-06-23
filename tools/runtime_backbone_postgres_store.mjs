import fs from "fs";
import path from "path";
import { Pool } from "pg";
import { fileURLToPath } from "url";
import {
  addMaterialBuildItems,
  applyComponentPatchDecision,
  buildSeedState,
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
  normalizeState,
  publishLessonRevision,
  recoverJobs,
  registerExportRun,
  rerunComponent,
  rerunLesson,
  searchQuestionBank,
  searchTaskProjections,
  updateReviewTaskStatus,
} from "./runtime_backbone_store.mjs";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const workspaceRoot = path.resolve(__dirname, "..");
const migrationPath = path.join(
  workspaceRoot,
  "config",
  "migrations",
  "20260623_runtime_backbone_validation.sql"
);

const mirrorTableConfigs = [
  {
    table: "document",
    rows: (state) => state.documents,
    columns: [
      "document_id",
      "source_id",
      "subject",
      "stage",
      "grade",
      "season",
      "doc_role",
      "title",
      "storage_uri",
      "checksum",
      "page_count",
      "status",
      "metadata_json",
      "created_at",
      "updated_at",
    ],
  },
  {
    table: "lesson",
    rows: (state) => state.lessons,
    columns: [
      "lesson_id",
      "document_group_id",
      "subject",
      "stage",
      "grade",
      "season",
      "title",
      "active_revision_id",
      "published_revision_id",
      "status",
      "created_at",
      "updated_at",
    ],
  },
  {
    table: "lesson_revision",
    rows: (state) => state.lessonRevisions,
    columns: [
      "lesson_revision_id",
      "lesson_id",
      "base_artifact_id",
      "generated_snapshot_ref",
      "manual_patch_ref",
      "merged_snapshot_ref",
      "revision_no",
      "status",
      "approval_status",
      "bundle_jsonb",
      "content_hash",
      "created_by",
      "created_at",
    ],
  },
  {
    table: "task_projection",
    rows: (state) => state.taskProjections,
    columns: [
      "task_projection_id",
      "lesson_id",
      "lesson_revision_id",
      "local_task_id",
      "source_node_local_id",
      "subject",
      "grade",
      "question_type",
      "stem",
      "answer",
      "explanation",
      "difficulty_level",
      "difficulty_scheme",
      "difficulty_source",
      "difficulty_confidence",
      "checkpoint_codes",
      "subject_tags",
      "source_refs_json",
      "content_hash",
      "search_text",
      "created_at",
    ],
  },
  {
    table: "question_bank_item",
    rows: (state) => state.questionBankItems,
    columns: [
      "question_bank_item_id",
      "subject",
      "grade",
      "current_revision_id",
      "status",
      "created_at",
      "updated_at",
    ],
  },
  {
    table: "question_bank_item_revision",
    rows: (state) => state.questionBankItemRevisions,
    columns: [
      "question_bank_item_revision_id",
      "question_bank_item_id",
      "stem",
      "answer",
      "explanation",
      "question_type",
      "difficulty_level",
      "difficulty_scheme",
      "difficulty_source",
      "difficulty_confidence",
      "checkpoint_codes",
      "subject_tags",
      "source_refs_json",
      "content_hash",
      "search_text",
      "created_at",
      "created_by",
    ],
  },
  {
    table: "question_bank_source_link",
    rows: (state) => state.questionBankSourceLinks,
    columns: [
      "question_bank_source_link_id",
      "question_bank_item_revision_id",
      "lesson_id",
      "lesson_revision_id",
      "local_task_id",
      "source_node_local_id",
      "source_refs_json",
      "created_at",
    ],
  },
  {
    table: "review_task",
    rows: (state) => state.reviewTasks,
    columns: [
      "review_task_id",
      "target_type",
      "target_revision_id",
      "run_id",
      "status",
      "assigned_to",
      "requested_by",
      "changes_summary",
      "created_at",
      "updated_at",
    ],
  },
  {
    table: "publication",
    rows: (state) => state.publications,
    columns: [
      "publication_id",
      "lesson_id",
      "lesson_revision_id",
      "status",
      "published_artifact_id",
      "material_build_id",
      "created_by",
      "created_at",
      "published_at",
      "revoked_at",
      "superseded_by_publication_id",
    ],
  },
  {
    table: "material_build",
    rows: (state) => state.materialBuilds,
    columns: [
      "material_build_id",
      "lesson_id",
      "teacher_name",
      "build_name",
      "section_schema",
      "target_variant",
      "status",
      "created_by",
      "created_at",
      "updated_at",
    ],
  },
  {
    table: "material_item",
    rows: (state) => state.materialItems,
    columns: [
      "material_item_id",
      "material_build_id",
      "question_bank_item_revision_id",
      "section_key",
      "placement_role",
      "target_variant",
      "sort_index",
      "difficulty_override",
      "include_answer",
      "include_explanation",
      "layout_hint_json",
      "created_at",
    ],
  },
  {
    table: "page_asset",
    rows: (state) => state.pageAssets,
    columns: [
      "page_asset_id",
      "document_id",
      "page_no",
      "width",
      "height",
      "image_artifact_id",
      "ocr_artifact_id",
      "layout_artifact_id",
      "status",
      "created_at",
    ],
  },
  {
    table: "component",
    rows: (state) => state.components,
    columns: [
      "component_id",
      "page_asset_id",
      "parent_component_id",
      "component_type",
      "bbox_json",
      "reading_order",
      "crop_artifact_id",
      "content_hash",
      "schema_version",
      "extraction_confidence",
      "status",
      "current_revision_id",
      "created_at",
    ],
  },
  {
    table: "component_revision",
    rows: (state) => state.componentRevisions,
    columns: [
      "component_revision_id",
      "component_id",
      "source_task_revision_id",
      "page_no",
      "bbox_json",
      "extracted_text",
      "source_refs_json",
      "created_by",
      "created_at",
    ],
  },
  {
    table: "component_patch_candidate",
    rows: (state) => state.componentPatchCandidates,
    columns: [
      "component_patch_candidate_id",
      "component_id",
      "base_component_revision_id",
      "proposed_component_revision_id",
      "target_task_revision_id",
      "run_id",
      "status",
      "diff_json",
      "created_at",
      "updated_at",
      "reviewed_by",
      "accepted_lesson_revision_id",
    ],
  },
  {
    table: "run",
    rows: (state) => state.runs,
    columns: [
      "run_id",
      "run_type",
      "root_target_type",
      "root_target_id",
      "subject",
      "lane",
      "status",
      "triggered_by",
      "started_at",
      "finished_at",
    ],
  },
  {
    table: "job",
    rows: (state) => state.jobs,
    columns: [
      "job_id",
      "run_id",
      "job_type",
      "lane",
      "capability",
      "resource_class",
      "priority",
      "idempotency_key",
      "status",
      "attempt_count",
      "max_attempts",
      "lease_expires_at",
      "heartbeat_at",
      "timeout_at",
      "cancel_requested_at",
      "next_retry_at",
      "error_code",
      "error_detail_ref",
      "payload_ref",
      "result_artifact_id",
      "created_at",
      "updated_at",
    ],
  },
  {
    table: "job_attempt",
    rows: (state) => state.jobAttempts,
    columns: [
      "job_attempt_id",
      "job_id",
      "attempt_no",
      "started_at",
      "heartbeat_at",
      "finished_at",
      "status",
      "error_detail_json",
      "worker_ref",
    ],
  },
  {
    table: "artifact",
    rows: (state) => state.artifacts,
    columns: [
      "artifact_id",
      "run_id",
      "job_id",
      "artifact_type",
      "schema_version",
      "producer_name",
      "producer_version",
      "model_version",
      "prompt_hash",
      "plugin_version",
      "storage_uri",
      "content_hash",
      "summary_json",
      "supersedes_artifact_id",
      "integrity_status",
      "logical_status",
      "lifecycle_status",
      "created_at",
    ],
  },
  {
    table: "artifact_dependency",
    rows: (state) => state.artifactDependencies,
    columns: [
      "artifact_dependency_id",
      "parent_artifact_id",
      "child_artifact_id",
      "dependency_type",
      "created_at",
    ],
  },
];

function quoteIdent(identifier) {
  return `"${String(identifier).replace(/"/g, "\"\"")}"`;
}

function buildMirrorRows(rows, columns) {
  return rows.map((row) => {
    const normalized = {};
    for (const column of columns) {
      normalized[column] = row[column] ?? null;
    }
    return normalized;
  });
}

function sortMirrorRows(rows, primaryColumn) {
  return [...rows].sort((left, right) =>
    String(left[primaryColumn] ?? "").localeCompare(String(right[primaryColumn] ?? ""))
  );
}

function buildMirrorSelectExpression(column) {
  const quotedColumn = quoteIdent(column);
  if (column.endsWith("_at")) {
    return `case when ${quotedColumn} is null then null else to_char(${quotedColumn} at time zone 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.MS\"Z\"') end as ${quotedColumn}`;
  }
  return quotedColumn;
}

function buildExpectedMirrorReport(state) {
  const report = {};
  for (const config of mirrorTableConfigs) {
    const rows = sortMirrorRows(
      buildMirrorRows(config.rows(state), config.columns),
      config.columns[0]
    );
    report[config.table] = {
      count: rows.length,
      hash: computeContentHash(rows),
    };
  }
  return report;
}

async function buildActualMirrorReport(client) {
  const report = {};
  for (const config of mirrorTableConfigs) {
    const orderBy = quoteIdent(config.columns[0]);
    const result = await client.query(
      `
        select to_jsonb(source_row) as row_json
        from (
          select ${config.columns.map(buildMirrorSelectExpression).join(", ")}
          from ${quoteIdent(config.table)}
          order by ${orderBy}
        ) as source_row
      `
    );
    const rows = result.rows.map((row) => row.row_json);
    report[config.table] = {
      count: rows.length,
      hash: computeContentHash(rows),
    };
  }
  return report;
}

async function replaceTable(client, table, columns, rows) {
  if (!rows.length) {
    return;
  }

  const columnSql = columns.map(quoteIdent).join(", ");
  const values = [];
  const valueSql = rows
    .map((row, rowIndex) => {
      const placeholders = columns.map((column, columnIndex) => {
        values.push(row[column] ?? null);
        return `$${rowIndex * columns.length + columnIndex + 1}`;
      });
      return `(${placeholders.join(", ")})`;
    })
    .join(", ");

  await client.query(
    `insert into ${quoteIdent(table)} (${columnSql}) values ${valueSql}`,
    values
  );
}

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
    this.pool = null;
    this.migrationVersion = "20260623_runtime_backbone_validation.sql";
    this.lastConsistencyReport = null;
  }

  async init() {
    if (!this.connectionString) {
      throw new Error("postgres_store_requires_DATABASE_URL");
    }
    this.pool = new Pool({
      connectionString: this.connectionString,
    });
    const migrationSql = fs.readFileSync(migrationPath, "utf8");
    await this.pool.query(migrationSql);
    const state = await this.loadState();
    await this.saveState(state);
    this.lastConsistencyReport = await this.getConsistencyReport();
  }

  async loadStateFromClient(client) {
    const result = await client.query(
      `
        select snapshot_json, snapshot_version, snapshot_content_hash
        from runtime_state_snapshot
        where snapshot_key = $1
      `,
      [this.snapshotKey]
    );
    if (!result.rows.length) {
      return {
        snapshotVersion: 0,
        snapshotContentHash: null,
        state: normalizeState(buildSeedState()),
      };
    }
    return {
      snapshotVersion: Number(result.rows[0].snapshot_version || 0),
      snapshotContentHash: result.rows[0].snapshot_content_hash || null,
      state: normalizeState(result.rows[0].snapshot_json),
    };
  }

  async loadState() {
    return (await this.loadStateFromClient(this.pool)).state;
  }

  async saveStateWithClient(client, state, currentSnapshotVersion = 0) {
    normalizeState(state);
    const snapshotContentHash = computeContentHash(state);
    const nextSnapshotVersion = Number(currentSnapshotVersion || 0) + 1;
    await client.query(
      `
        insert into runtime_state_snapshot (
          snapshot_key,
          snapshot_json,
          snapshot_version,
          snapshot_content_hash,
          updated_at
        )
        values ($1, $2::jsonb, $3, $4, now())
        on conflict (snapshot_key)
        do update
        set snapshot_json = excluded.snapshot_json,
            snapshot_version = excluded.snapshot_version,
            snapshot_content_hash = excluded.snapshot_content_hash,
            updated_at = excluded.updated_at
      `,
      [this.snapshotKey, JSON.stringify(state), nextSnapshotVersion, snapshotContentHash]
    );

    for (const config of [...mirrorTableConfigs].reverse()) {
      await client.query(`delete from ${quoteIdent(config.table)}`);
    }
    for (const config of mirrorTableConfigs) {
      await replaceTable(client, config.table, config.columns, config.rows(state));
    }
    return {
      snapshotContentHash,
      snapshotVersion: nextSnapshotVersion,
    };
  }

  async saveState(state) {
    const client = await this.pool.connect();
    try {
      await client.query("begin");
      await this.saveStateWithClient(client, state);
      await client.query("commit");
    } catch (error) {
      await client.query("rollback");
      throw error;
    } finally {
      client.release();
    }
    return state;
  }

  async readState() {
    const state = await this.loadState();
    recoverJobs(state);
    return state;
  }

  async writeState(mutator) {
    const client = await this.pool.connect();
    try {
      await client.query("begin");
      // Advisory locking serializes snapshot-based writes and prevents lost updates.
      await client.query("select pg_advisory_xact_lock(hashtext($1))", [this.snapshotKey]);
      const { state, snapshotVersion } = await this.loadStateFromClient(client);
      recoverJobs(state);
      const result = await mutator(state);
      await this.saveStateWithClient(client, state, snapshotVersion);
      await client.query("commit");
      this.lastConsistencyReport = null;
      return result;
    } catch (error) {
      await client.query("rollback");
      throw error;
    } finally {
      client.release();
    }
  }

  async bootstrap() {
    const state = buildSeedState();
    await this.saveState(state);
    return {
      ok: true,
      summary: getSummary(state),
    };
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
    return this.writeState(async (state) => ({
      result: rerunLesson(state, lessonId, actor),
      lesson: getLessonDetail(state, lessonId),
    }));
  }

  async publishLesson(lessonId, actor, options) {
    return this.writeState(async (state) => publishLessonRevision(state, lessonId, actor, options));
  }

  async importLessonDraftBundle(payload) {
    return this.writeState(async (state) => importLessonDraftBundle(state, payload));
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
    return this.writeState(async (state) =>
      updateReviewTaskStatus(state, reviewTaskId, "approve", actor)
    );
  }

  async requestReviewChanges(reviewTaskId, actor) {
    return this.writeState(async (state) =>
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
    return this.writeState(async (state) => createQuestionBankItem(state, payload));
  }

  async createMaterialBuild(payload) {
    return this.writeState(async (state) => createMaterialBuild(state, payload));
  }

  async addMaterialBuildItems(materialBuildId, payload) {
    return this.writeState(async (state) => addMaterialBuildItems(state, materialBuildId, payload));
  }

  async exportMaterialBuild(materialBuildId, payload) {
    return this.writeState(async (state) => exportMaterialBuild(state, materialBuildId, payload));
  }

  async rerunComponent(componentId, payload) {
    return this.writeState(async (state) => rerunComponent(state, componentId, payload));
  }

  async listComponentRevisions(componentId) {
    return getComponentRevisions(await this.readState(), componentId);
  }

  async getComponentPatch(patchId) {
    return getComponentPatch(await this.readState(), patchId);
  }

  async acceptComponentPatch(patchId, actor) {
    return this.writeState(async (state) => applyComponentPatchDecision(state, patchId, "accept", actor));
  }

  async rejectComponentPatch(patchId, actor) {
    return this.writeState(async (state) => applyComponentPatchDecision(state, patchId, "reject", actor));
  }

  async registerExportRun(payload, historyItem) {
    return this.writeState(async (state) => registerExportRun(state, payload, historyItem));
  }

  async recoverJobs(actor) {
    return this.writeState(async (state) => recoverJobs(state, actor));
  }

  async getDebugState() {
    return this.readState();
  }

  async getConsistencyReport() {
    const client = await this.pool.connect();
    try {
      const snapshotResult = await this.loadStateFromClient(client);
      const expectedTables = buildExpectedMirrorReport(snapshotResult.state);
      const actualTables = await buildActualMirrorReport(client);
      const mismatches = [];
      for (const config of mirrorTableConfigs) {
        const expected = expectedTables[config.table];
        const actual = actualTables[config.table];
        if (expected.count !== actual.count || expected.hash !== actual.hash) {
          mismatches.push({
            table: config.table,
            expectedCount: expected.count,
            actualCount: actual.count,
            expectedHash: expected.hash,
            actualHash: actual.hash,
          });
        }
      }
      const computedSnapshotHash = computeContentHash(snapshotResult.state);
      const snapshotHashMatches =
        !snapshotResult.snapshotContentHash ||
        snapshotResult.snapshotContentHash === computedSnapshotHash;
      const report = {
        ok: mismatches.length === 0 && snapshotHashMatches,
        status: mismatches.length === 0 && snapshotHashMatches ? "ok" : "degraded",
        checkedAt: new Date().toISOString(),
        snapshotKey: this.snapshotKey,
        snapshotVersion: snapshotResult.snapshotVersion,
        snapshotContentHash: snapshotResult.snapshotContentHash,
        computedSnapshotHash,
        snapshotHashMatches,
        mismatches,
        tables: Object.fromEntries(
          mirrorTableConfigs.map((config) => [
            config.table,
            {
              ...expectedTables[config.table],
              actualCount: actualTables[config.table].count,
              actualHash: actualTables[config.table].hash,
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
