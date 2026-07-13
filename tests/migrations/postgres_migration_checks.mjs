/**
 * 用途：
 * - 验证 schema 迁移能创建预期的 Postgres 结构。
 * - 凡是迁移改变表或索引预期，都要同步更新这个文件。
 */

import fs from "node:fs/promises";
import path from "node:path";
import {
  expect,
  workspaceRoot,
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
        "subject_track",
        "runtime_migration_warning",
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

  register({
    id: "B08",
    suite: "migrations",
    title: "Three-track alignment migration adds track columns and normalizes difficulty types",
    required: true,
    async run({ harness }) {
      const server = await harness.startPostgresServer("migration_three_track_test");
      const result = await harness.queryDatabase(
        server.database.connectionString,
        `
          select table_name, column_name, data_type
          from information_schema.columns
          where table_schema = 'public'
            and (
              (table_name = 'lesson' and column_name = 'track_code')
              or (table_name = 'task_projection' and column_name in ('stage', 'track_code', 'difficulty_level'))
              or (table_name = 'question_bank_item' and column_name in ('stage', 'track_code'))
              or (table_name = 'question_bank_item_revision' and column_name in ('subject', 'stage', 'track_code', 'difficulty_level'))
              or (table_name = 'material_build' and column_name in ('subject', 'stage', 'track_code'))
              or (table_name = 'task_subject_ext' and column_name in ('stage', 'track_code'))
              or (table_name = 'subject_track' and column_name in ('track_code', 'subject', 'stage', 'plugin_id', 'difficulty_scheme'))
            )
          order by table_name, column_name
        `
      );
      const columns = new Map(
        result.rows.map((row) => [`${row.table_name}.${row.column_name}`, row.data_type])
      );
      for (const key of [
        "lesson.track_code",
        "task_projection.stage",
        "task_projection.track_code",
        "question_bank_item.stage",
        "question_bank_item.track_code",
        "question_bank_item_revision.subject",
        "question_bank_item_revision.stage",
        "question_bank_item_revision.track_code",
        "material_build.subject",
        "material_build.stage",
        "material_build.track_code",
        "task_subject_ext.stage",
        "task_subject_ext.track_code",
        "subject_track.track_code",
        "subject_track.subject",
        "subject_track.stage",
        "subject_track.plugin_id",
        "subject_track.difficulty_scheme",
      ]) {
        expect(columns.has(key), `missing_column:${key}`);
      }
      expect(columns.get("task_projection.difficulty_level") === "smallint", "task_projection_difficulty_level_should_be_smallint");
      expect(
        columns.get("question_bank_item_revision.difficulty_level") === "smallint",
        "question_bank_item_revision_difficulty_level_should_be_smallint"
      );
      return {
        checkedColumns: columns.size,
      };
    },
  });

  register({
    id: "B09",
    suite: "migrations",
    title: "Database constraints reject illegal track combinations and mismatched plugin or difficulty schemes",
    required: true,
    async run({ harness }) {
      const server = await harness.startPostgresServer("migration_track_constraint_test");
      let lessonError = null;
      let projectionError = null;
      let extError = null;

      try {
        await harness.queryDatabase(
          server.database.connectionString,
          `
            insert into lesson (
              lesson_id,
              subject,
              stage,
              track_code,
              grade,
              title,
              status,
              created_at,
              updated_at
            )
            values (
              'invalid_track_lesson',
              '英语',
              'senior',
              'math_senior',
              '高二',
              'invalid track lesson',
              'draft',
              now(),
              now()
            )
          `
        );
      } catch (error) {
        lessonError = error;
      }

      await harness.queryDatabase(
        server.database.connectionString,
        `
          insert into lesson (
            lesson_id,
            subject,
            stage,
            track_code,
            grade,
            title,
            status,
            created_at,
            updated_at
          )
          values (
            'valid_track_lesson',
            '英语',
            'senior',
            'english_senior',
            '高二',
            'valid track lesson',
            'draft',
            now(),
            now()
          )
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
            'valid_track_lesson:rev:1',
            'valid_track_lesson',
            1,
            'draft',
            'pending',
            '{}'::jsonb,
            'valid_track_hash',
            'migration_suite',
            now()
          )
        `
      );

      try {
        await harness.queryDatabase(
          server.database.connectionString,
          `
            insert into task_projection (
              task_projection_id,
              lesson_id,
              lesson_revision_id,
              local_task_id,
              subject,
              stage,
              track_code,
              grade,
              question_type,
              stem,
              answer,
              explanation,
              difficulty_level,
              difficulty_scheme,
              difficulty_source,
              difficulty_confidence,
              checkpoint_codes,
              subject_tags,
              source_refs_json,
              content_hash,
              search_text,
              created_at
            )
            values (
              'invalid_projection',
              'valid_track_lesson',
              'valid_track_lesson:rev:1',
              'ES-001',
              '英语',
              'senior',
              'english_senior',
              '高二',
              'question',
              'stem',
              'answer',
              'explanation',
              3,
              'difficulty.math.senior.v1',
              'manual',
              0.9,
              array['阅读理解主旨大意'],
              array['阅读'],
              '{}'::jsonb,
              'hash',
              'stem',
              now()
            )
          `
        );
      } catch (error) {
        projectionError = error;
      }

      await harness.queryDatabase(
        server.database.connectionString,
        `
          insert into task_revision (
            task_revision_id,
            task_id,
            lesson_revision_id,
            source_node_revision_id,
            student_stem,
            teacher_stem,
            answer,
            explanation,
            visibility,
            generated_data_ref,
            manual_patch_ref,
            merged_data_ref,
            status,
            created_at
          )
          values (
            'track_constraint_task_revision',
            'track_constraint_task',
            'valid_track_lesson:rev:1',
            null,
            'student',
            'teacher',
            'answer',
            'explanation',
            'visible',
            null,
            null,
            null,
            'ready',
            now()
          )
        `
      );

      try {
        await harness.queryDatabase(
          server.database.connectionString,
          `
            insert into task_subject_ext (
              task_revision_id,
              subject,
              stage,
              track_code,
              plugin_id,
              plugin_version,
              schema_version,
              payload_json,
              risk_flags,
              created_at,
              updated_at
            )
            values (
              'track_constraint_task_revision',
              '英语',
              'senior',
              'english_senior',
              'subject.math.seed',
              'v1',
              'v1',
              '{}'::jsonb,
              array[]::text[],
              now(),
              now()
            )
          `
        );
      } catch (error) {
        extError = error;
      }

      expect(lessonError, "invalid_lesson_track_combo_should_fail");
      expect(projectionError, "invalid_projection_difficulty_scheme_should_fail");
      expect(extError, "invalid_task_subject_ext_plugin_should_fail");
      return {
        lessonConstraint: String(lessonError.message || lessonError),
        projectionConstraint: String(projectionError.message || projectionError),
        pluginConstraint: String(extError.message || extError),
      };
    },
  });

  register({
    id: "B10",
    suite: "migrations",
    title: "Legacy data migration preserves unresolved rows as warnings and corrects determinable three-track mappings",
    required: true,
    async run({ harness, outputDir }) {
      const database = await harness.createPostgresDatabase("legacy_migration_test");
      const validationSql = await fs.readFile(
        path.join(workspaceRoot, "config", "migrations", "20260623_runtime_backbone_validation.sql"),
        "utf8"
      );
      const soleSourceSql = await fs.readFile(
        path.join(workspaceRoot, "config", "migrations", "20260623_postgres_sole_source.sql"),
        "utf8"
      );
      const alignmentSql = await fs.readFile(
        path.join(workspaceRoot, "config", "migrations", "20260624_three_track_validation_alignment.sql"),
        "utf8"
      );
      const hardeningSql = await fs.readFile(
        path.join(workspaceRoot, "config", "migrations", "20260624_three_track_final_review_hardening.sql"),
        "utf8"
      );

      await harness.queryDatabase(database.connectionString, validationSql);
      await harness.queryDatabase(database.connectionString, soleSourceSql);
      await harness.queryDatabase(
        database.connectionString,
        `
          insert into lesson (
            lesson_id, subject, stage, grade, season, title, active_revision_id, published_revision_id, status, created_at, updated_at
          )
          values
            ('legacy_english_lesson', '英语', '高中', '高二', '暑假', 'legacy english lesson', 'legacy_english_lesson:rev:1', 'legacy_english_lesson:rev:1', 'published', now(), now()),
            ('legacy_unresolved_lesson', '英语', 'junior', '初二', '暑假', 'legacy unresolved lesson', null, null, 'draft', now(), now());

          insert into lesson_revision (
            lesson_revision_id, lesson_id, revision_no, status, approval_status, bundle_jsonb, content_hash, created_by, created_at
          )
          values (
            'legacy_english_lesson:rev:1',
            'legacy_english_lesson',
            1,
            'published',
            'approved',
            '{"lesson_id":"legacy_english_lesson","lesson_title":"legacy english lesson","subject":"英语","stage":"高中","grade":"高二","season":"暑假","tasks":[]}'::jsonb,
            'legacy_bundle_hash',
            'migration_suite',
            now()
          );

          insert into publication (
            publication_id, lesson_id, lesson_revision_id, status, published_artifact_id, material_build_id, created_by, created_at, published_at, revoked_at, superseded_by_publication_id
          )
          values (
            'legacy_publication',
            'legacy_english_lesson',
            'legacy_english_lesson:rev:1',
            'published',
            null,
            null,
            'migration_suite',
            now(),
            now(),
            null,
            null
          );

          insert into task (
            task_id, lesson_id, stable_question_no, current_revision_id, created_at
          )
          values (
            'legacy_task',
            'legacy_english_lesson',
            'ES-LEGACY-001',
            'legacy_task_revision',
            now()
          );

          insert into task_revision (
            task_revision_id, task_id, lesson_revision_id, source_node_revision_id, student_stem, teacher_stem, answer, explanation, visibility, generated_data_ref, manual_patch_ref, merged_data_ref, status, created_at
          )
          values (
            'legacy_task_revision',
            'legacy_task',
            'legacy_english_lesson:rev:1',
            null,
            'student stem',
            'teacher stem',
            'answer',
            'explanation',
            'visible',
            null,
            null,
            null,
            'ready',
            now()
          );

          insert into task_subject_ext (
            task_revision_id, subject, plugin_id, plugin_version, schema_version, payload_json, risk_flags, created_at, updated_at
          )
          values (
            'legacy_task_revision',
            '英语',
            'subject.math.seed',
            'v0',
            'legacy',
            '{}'::jsonb,
            array[]::text[],
            now(),
            now()
          );

          insert into task_projection (
            task_projection_id, lesson_id, lesson_revision_id, local_task_id, source_node_local_id, subject, grade, question_type, stem, answer, explanation, difficulty_level, difficulty_scheme, difficulty_source, difficulty_confidence, checkpoint_codes, subject_tags, source_refs_json, content_hash, search_text, created_at
          )
          values (
            'legacy_projection',
            'legacy_english_lesson',
            'legacy_english_lesson:rev:1',
            'ES-LEGACY-001',
            'root',
            '英语',
            '高二',
            'question',
            'stem',
            'answer',
            'explanation',
            'unknown',
            'legacy_scheme',
            'legacy_unknown',
            0.4,
            array['阅读理解主旨大意'],
            array['阅读'],
            '{}'::jsonb,
            'legacy_projection_hash',
            'stem',
            now()
          );

          insert into question_bank_item (
            question_bank_item_id, subject, grade, current_revision_id, status, created_at, updated_at
          )
          values (
            'legacy_qb_item',
            null,
            '高二',
            'legacy_qb_revision',
            'active',
            now(),
            now()
          );

          insert into question_bank_item_revision (
            question_bank_item_revision_id, question_bank_item_id, stem, answer, explanation, question_type, difficulty_level, difficulty_scheme, difficulty_source, difficulty_confidence, checkpoint_codes, subject_tags, source_refs_json, content_hash, search_text, created_at, created_by
          )
          values (
            'legacy_qb_revision',
            'legacy_qb_item',
            'stem',
            'answer',
            'explanation',
            'question',
            'medium',
            'legacy_scheme',
            'legacy_scale',
            0.6,
            array['阅读理解主旨大意'],
            array['阅读'],
            '{}'::jsonb,
            'legacy_qb_hash',
            'stem',
            now(),
            'migration_suite'
          );

          insert into question_bank_source_link (
            question_bank_source_link_id, question_bank_item_revision_id, lesson_id, lesson_revision_id, local_task_id, source_node_local_id, source_refs_json, created_at
          )
          values (
            'legacy_qb_link',
            'legacy_qb_revision',
            'legacy_english_lesson',
            'legacy_english_lesson:rev:1',
            'ES-LEGACY-001',
            'root',
            '{}'::jsonb,
            now()
          );

          insert into material_build (
            material_build_id, lesson_id, teacher_name, build_name, section_schema, target_variant, status, created_by, created_at, updated_at
          )
          values (
            'legacy_material_build',
            'legacy_english_lesson',
            'legacy_teacher',
            'legacy build',
            '{}'::jsonb,
            'standard',
            'draft',
            'migration_suite',
            now(),
            now()
          );
        `
      );

      await harness.queryDatabase(database.connectionString, alignmentSql);
      await harness.queryDatabase(database.connectionString, hardeningSql);

      const result = await harness.queryDatabase(
        database.connectionString,
        `
          select
            lesson.track_code as lesson_track_code,
            lesson.stage as lesson_stage,
            ext.plugin_id as ext_plugin_id,
            projection.difficulty_level as projection_difficulty_level,
            projection.difficulty_scheme as projection_difficulty_scheme,
            revision.difficulty_level as revision_difficulty_level,
            revision.difficulty_scheme as revision_difficulty_scheme,
            material_build.track_code as material_track_code,
            publication.lesson_revision_id as publication_revision_id
          from lesson
          left join task_subject_ext ext
            on ext.task_revision_id = 'legacy_task_revision'
          left join task_projection projection
            on projection.task_projection_id = 'legacy_projection'
          left join question_bank_item_revision revision
            on revision.question_bank_item_revision_id = 'legacy_qb_revision'
          left join material_build
            on material_build.material_build_id = 'legacy_material_build'
          left join publication
            on publication.publication_id = 'legacy_publication'
          where lesson.lesson_id = 'legacy_english_lesson'
        `
      );
      const warnings = await harness.queryDatabase(
        database.connectionString,
        `
          select entity_table, entity_id, warning_code
          from runtime_migration_warning
          where entity_id = 'legacy_unresolved_lesson'
        `
      );
      const report = {
        legacyEnglish: result.rows[0],
        warningCount: warnings.rows.length,
        warnings: warnings.rows,
      };
      const migrationReportDir = path.join(workspaceRoot, "outputs", "migrations");
      await fs.mkdir(migrationReportDir, { recursive: true });
      await fs.writeFile(
        path.join(migrationReportDir, "three_track_alignment_migration_report.json"),
        JSON.stringify(report, null, 2),
        "utf8"
      );

      expect(result.rows.length === 1, "legacy_migration_target_missing");
      expect(result.rows[0].lesson_track_code === "english_senior", "legacy_english_track_not_corrected");
      expect(result.rows[0].lesson_stage === "senior", "legacy_english_stage_not_normalized");
      expect(result.rows[0].ext_plugin_id === "subject.english.senior.v1", "legacy_plugin_not_corrected");
      expect(result.rows[0].projection_difficulty_level === null, "unknown_projection_difficulty_should_be_null");
      expect(
        result.rows[0].projection_difficulty_scheme === "difficulty.english.senior.v1",
        "projection_difficulty_scheme_not_aligned"
      );
      expect(result.rows[0].revision_difficulty_level === 3, "medium_revision_difficulty_should_map_to_3");
      expect(
        result.rows[0].revision_difficulty_scheme === "difficulty.english.senior.v1",
        "revision_difficulty_scheme_not_aligned"
      );
      expect(result.rows[0].material_track_code === "english_senior", "material_track_not_aligned");
      expect(
        result.rows[0].publication_revision_id === "legacy_english_lesson:rev:1",
        "publication_revision_should_not_drift"
      );
      expect(warnings.rows.length === 1, "unresolved_legacy_lesson_should_emit_warning");
      return {
        reportPath: path.join("outputs", "migrations", "three_track_alignment_migration_report.json"),
        warningCount: warnings.rows.length,
      };
    },
  });
}
