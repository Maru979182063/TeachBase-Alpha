import fs from "node:fs/promises";
import path from "node:path";

import {
  expect,
  workspaceRoot,
} from "../helpers/runtime_testkit.mjs";
import { buildSchemaSnapshot } from "./release_gate_shared.mjs";

const requiredTables = [
  "lesson",
  "lesson_revision",
  "source_node",
  "source_node_revision",
  "task",
  "task_revision",
  "task_projection",
  "question_bank_item",
  "question_bank_item_revision",
  "question_bank_source_link",
  "review_task",
  "publication",
  "material_build",
  "material_item",
  "subject_track",
  "document",
  "document_group",
  "page_asset",
  "component",
  "component_revision",
  "component_link",
  "component_patch_candidate",
  "run",
  "job",
  "job_attempt",
  "job_dependency",
  "artifact",
  "artifact_dependency",
  "outbox_event",
  "lesson_import",
  "quality_evaluation",
  "runtime_metadata",
  "runtime_state_snapshot",
  "runtime_migration_warning",
];

const requiredColumns = [
  "task_projection.source_refs_json",
  "task_projection.difficulty_level",
  "task_projection.difficulty_scheme",
  "task_projection.difficulty_source",
  "task_projection.difficulty_confidence",
  "task_projection.search_vector",
  "question_bank_item_revision.stem",
  "question_bank_item_revision.answer",
  "question_bank_item_revision.explanation",
  "question_bank_item_revision.difficulty_level",
  "question_bank_item_revision.difficulty_scheme",
  "question_bank_item_revision.difficulty_source",
  "question_bank_item_revision.difficulty_confidence",
  "question_bank_item_revision.checkpoint_codes",
  "question_bank_item_revision.subject_tags",
  "question_bank_item_revision.source_refs_json",
  "question_bank_item_revision.search_vector",
  "question_bank_source_link.source_refs_json",
  "question_bank_source_link.lesson_revision_id",
  "question_bank_source_link.local_task_id",
  "component_revision.source_refs_json",
  "component_revision.bbox_json",
  "component_revision.extracted_text",
  "artifact.storage_uri",
  "artifact.content_hash",
  "artifact.integrity_status",
  "artifact.logical_status",
  "artifact.lifecycle_status",
  "publication.lesson_revision_id",
  "publication.published_artifact_id",
  "publication.superseded_by_publication_id",
  "material_item.question_bank_item_revision_id",
  "material_item.section_key",
  "material_item.placement_role",
  "material_item.sort_index",
  "material_item.difficulty_override",
  "material_item.include_answer",
  "material_item.include_explanation",
];

export function registerTests(register) {
  register({
    id: "RG-MIG-01",
    suite: "release_gate_migration",
    title: "Fresh Postgres migration matches the checked-in schema snapshot and keeps v1.1 write points off task_revision",
    required: true,
    async run({ harness, outputDir }) {
      const server = await harness.startPostgresServer("release_gate_migration_test");
      const currentSnapshot = await buildSchemaSnapshot(
        harness,
        server.database.connectionString
      );
      const baselinePath = path.join(
        workspaceRoot,
        "outputs",
        "db",
        "current_postgres_schema_snapshot.json"
      );
      const baselineSnapshot = JSON.parse(await fs.readFile(baselinePath, "utf8"));
      await fs.writeFile(
        path.join(outputDir, "current_postgres_schema_snapshot.runtime.json"),
        JSON.stringify(currentSnapshot, null, 2),
        "utf8"
      );

      const tables = new Map(
        currentSnapshot.tables.map((table) => [table.table, table])
      );
      const columnSet = new Set(
        currentSnapshot.tables.flatMap((table) =>
          table.columns.map((column) => `${table.table}.${column.name}`)
        )
      );

      for (const tableName of requiredTables) {
        expect(tables.has(tableName), `missing_required_table:${tableName}`);
      }
      for (const columnName of requiredColumns) {
        expect(columnSet.has(columnName), `missing_required_column:${columnName}`);
      }
      expect(
        !columnSet.has("task_revision.source_refs_json"),
        "task_revision_source_refs_json_must_not_exist"
      );
      expect(
        tables.has("runtime_state_snapshot"),
        "runtime_state_snapshot_table_missing"
      );
      expect(
        JSON.stringify(currentSnapshot) === JSON.stringify(baselineSnapshot),
        `schema_snapshot_mismatch:runtime=${currentSnapshot.tableCount}:baseline=${baselineSnapshot.tableCount}`
      );
      return {
        tableCount: currentSnapshot.tableCount,
        snapshotPath: path.relative(workspaceRoot, baselinePath),
      };
    },
  });
}
