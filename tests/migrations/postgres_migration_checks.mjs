/**
 * 用途：
 * - 验证 schema 迁移能创建预期的 Postgres 结构。
 * - 凡是迁移改变表或索引预期，都要同步更新这个文件。
 */

import {
  expect,
} from "../helpers/runtime_testkit.mjs";

export function registerTests(register) {
  register({
    id: "B01",
    suite: "migrations",
    title: "Empty database migrates and exposes expected tables",
    required: true,
    async run({ harness }) {
      const server = await harness.startPostgresServer("migration_test");
      const result = await harness.queryDatabase(
        server.database.connectionString,
        `
          select table_name
          from information_schema.tables
          where table_schema = 'public'
          order by table_name
        `
      );
      const tables = new Set(result.rows.map((row) => row.table_name));
      for (const tableName of [
        "runtime_metadata",
        "runtime_state_snapshot",
        "document_source",
        "document_group",
        "document_group_member",
        "document_relation",
        "lesson",
        "lesson_revision",
        "task_projection",
        "lesson_import",
        "review_task",
        "publication",
        "question_bank_item",
        "question_bank_item_revision",
        "material_build",
        "material_item",
        "component",
        "component_link",
        "component_revision",
        "source_node",
        "source_node_revision",
        "task",
        "task_revision",
        "checkpoint_catalog",
        "checkpoint_catalog_version",
        "checkpoint_node",
        "source_node_checkpoint_link",
        "task_checkpoint_override",
        "task_subject_ext",
        "quality_evaluation",
        "run",
        "job",
        "job_attempt",
        "job_dependency",
        "outbox_event",
        "artifact",
        "artifact_dependency",
      ]) {
        expect(tables.has(tableName), `missing_table:${tableName}`);
      }
      return {
        tableCount: tables.size,
        database: server.database.maskedConnectionString,
      };
    },
  });

  register({
    id: "B05",
    suite: "migrations",
    title: "Unique constraint blocks duplicate lesson revision numbers",
    required: true,
    async run({ harness }) {
      const server = await harness.startPostgresServer("migration_unique_test");
      await harness.queryDatabase(
        server.database.connectionString,
        `
          insert into lesson (lesson_id, title, status, created_at, updated_at)
          values ('lesson_unique_test', 'unique test', 'draft', now(), now())
        `
      );
      await harness.queryDatabase(
        server.database.connectionString,
        `
          insert into lesson_revision (
            lesson_revision_id,
            lesson_id,
            revision_no,
            status,
            approval_status,
            bundle_jsonb,
            content_hash,
            created_by,
            created_at
          )
          values (
            'lesson_unique_test:rev:1',
            'lesson_unique_test',
            1,
            'reviewing',
            'pending',
            '{}'::jsonb,
            'hash_one',
            'migration_suite',
            now()
          )
        `
      );
      let duplicateError = null;
      try {
        await harness.queryDatabase(
          server.database.connectionString,
          `
            insert into lesson_revision (
              lesson_revision_id,
              lesson_id,
              revision_no,
              status,
              approval_status,
              bundle_jsonb,
              content_hash,
              created_by,
              created_at
            )
            values (
              'lesson_unique_test:rev:2',
              'lesson_unique_test',
              1,
              'reviewing',
              'pending',
              '{}'::jsonb,
              'hash_two',
              'migration_suite',
              now()
            )
          `
        );
      } catch (error) {
        duplicateError = error;
      }
      expect(duplicateError, "duplicate_lesson_revision_should_fail");
      expect(
        String(duplicateError.message || duplicateError).includes("uq_lesson_revision_lesson_revision_no"),
        "duplicate_lesson_revision_constraint_missing"
      );
      return {
        constraint: "uq_lesson_revision_lesson_revision_no",
      };
    },
  });

  register({
    id: "B06",
    suite: "migrations",
    title: "CHECK constraint blocks invalid review task status",
    required: true,
    async run({ harness }) {
      const server = await harness.startPostgresServer("migration_check_test");
      let statusError = null;
      try {
        await harness.queryDatabase(
          server.database.connectionString,
          `
            insert into review_task (
              review_task_id,
              target_type,
              target_revision_id,
              status,
              created_at,
              updated_at
            )
            values (
              'review_status_test',
              'lesson_revision',
              'lesson_unique_test:rev:1',
              'broken',
              now(),
              now()
            )
          `
        );
      } catch (error) {
        statusError = error;
      }
      expect(statusError, "invalid_review_status_should_fail");
      expect(
        String(statusError.message || statusError).includes("ck_review_task_status"),
        "review_status_check_constraint_missing"
      );
      return {
        constraint: "ck_review_task_status",
      };
    },
  });
}
