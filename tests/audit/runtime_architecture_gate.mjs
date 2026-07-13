/**
 * 用途：
 * - 守住架构规则，确保运行时栈保持预期边界。
 * - 这里失败通常意味着模块职责发生了越界。
 */

import fs from "node:fs/promises";
import path from "node:path";
import {
  expect,
  readJsonFixture,
  workspaceRoot,
} from "../helpers/runtime_testkit.mjs";

export function registerTests(register) {
  register({
    id: "ARCH-001",
    suite: "audit",
    title: "Postgres normalized tables must be the sole business source of truth",
    required: true,
    async run({ harness }) {
      const filePath = path.join(workspaceRoot, "tools", "runtime_backbone_postgres_store.mjs");
      const source = await fs.readFile(filePath, "utf8");

      expect(!source.includes("loadStateFromClient("), "legacy_snapshot_loader_still_present");
      expect(!source.includes("saveStateWithClient("), "legacy_snapshot_writer_still_present");
      expect(!source.includes("writeState("), "legacy_snapshot_write_wrapper_still_present");
      expect(!source.includes("select snapshot_json, snapshot_version, snapshot_content_hash"), "snapshot_select_still_present");

      const database = await harness.createPostgresDatabase("arch001_test_pg");
      const bundle = await readJsonFixture("math", "minimal_bundle.json");
      const lessonId = `${bundle.lesson_id}_arch001`;
      const server = await harness.startPostgresServer({
        database,
        env: {
          POSTGRES_SOLE_SOURCE: "true",
        },
      });

      const imported = await server.request("/api/runtime/imports/lesson-draft-bundles", {
        method: "POST",
        body: {
          actor: "arch001_suite",
          bundle: {
            ...bundle,
            lesson_id: lessonId,
            bundle_id: `${bundle.bundle_id}_arch001`,
          },
        },
      });
      expect(imported.ok, `arch001_import_failed:${JSON.stringify(imported.data)}`);

      const health = await server.request("/health");
      expect(health.ok, "arch001_health_failed");
      expect(
        health.data.storeHealth?.sourceOfTruth?.mode === "normalized_tables",
        "health_source_of_truth_not_tables"
      );
      expect(
        health.data.storeHealth?.sourceOfTruth?.soleSourceEnabled === true,
        "health_sole_source_flag_missing"
      );

      await harness.queryDatabase(
        database.connectionString,
        `
          insert into runtime_state_snapshot (
            snapshot_key,
            snapshot_json,
            snapshot_version,
            snapshot_content_hash,
            updated_at
          )
          values (
            'default',
            '{"meta":{"generatedAt":"2000-01-01T00:00:00.000Z","updatedAt":"2000-01-01T00:00:00.000Z"},"lessons":[{"lesson_id":"bogus_snapshot_lesson","title":"bogus"}]}'::jsonb,
            999,
            'bogus_hash',
            now()
          )
          on conflict (snapshot_key)
          do update
          set snapshot_json = excluded.snapshot_json,
              snapshot_version = excluded.snapshot_version,
              snapshot_content_hash = excluded.snapshot_content_hash,
              updated_at = excluded.updated_at
        `
      );

      const approved = await server.request(
        `/api/runtime/review-tasks/${imported.data.result.reviewTaskId}/approve`,
        {
          method: "POST",
          body: {
            actor: "arch001_reviewer",
          },
        }
      );
      expect(approved.ok, `arch001_approve_failed:${JSON.stringify(approved.data)}`);

      const published = await server.request(`/api/runtime/lessons/${lessonId}/publish`, {
        method: "POST",
        body: {
          actor: "arch001_publisher",
        },
      });
      expect(published.ok, `arch001_publish_failed:${JSON.stringify(published.data)}`);

      const detail = await server.request(`/api/runtime/lessons/${lessonId}`);
      expect(detail.ok, `arch001_detail_failed:${JSON.stringify(detail.data)}`);
      expect(detail.data.detail.lesson.lesson_id === lessonId, "table_backed_detail_missing");

      const lessons = await server.request("/api/runtime/lessons");
      expect(lessons.ok, "arch001_lessons_failed");
      expect(
        lessons.data.items.some((item) => item.lesson_id === lessonId),
        "imported_lesson_missing_from_table_query"
      );
      expect(
        !lessons.data.items.some((item) => item.lesson_id === "bogus_snapshot_lesson"),
        "snapshot_json_is_still_polluting_lesson_queries"
      );

      const restarted = await harness.startPostgresServer({
        database,
        env: {
          POSTGRES_SOLE_SOURCE: "true",
        },
      });
      const restartedDetail = await restarted.request(`/api/runtime/lessons/${lessonId}`);
      expect(restartedDetail.ok, `arch001_restart_detail_failed:${JSON.stringify(restartedDetail.data)}`);
      expect(
        restartedDetail.data.detail.lesson.lesson_id === lessonId,
        "restart_should_read_normalized_tables"
      );
      expect(
        restartedDetail.data.detail.lesson.published_revision_id,
        "published_revision_missing_after_restart"
      );

      const snapshotRow = await harness.queryDatabase(
        database.connectionString,
        `
          select snapshot_version, snapshot_content_hash
          from runtime_state_snapshot
          where snapshot_key = 'default'
        `
      );
      expect(snapshotRow.rows.length === 1, "corrupt_snapshot_row_missing");
      expect(Number(snapshotRow.rows[0].snapshot_version) === 999, "business_write_should_not_refresh_snapshot");
      expect(
        snapshotRow.rows[0].snapshot_content_hash === "bogus_hash",
        "business_write_should_ignore_debug_snapshot"
      );

      return {
        lessonId,
        snapshotVersion: Number(snapshotRow.rows[0].snapshot_version),
        snapshotContentHash: snapshotRow.rows[0].snapshot_content_hash,
        sourceOfTruth: health.data.storeHealth.sourceOfTruth,
      };
    },
  });

  register({
    id: "POLICY-001",
    suite: "policy",
    title: "Validation baseline keeps the branch non-production while the core Postgres write path is no longer a full state replay bridge",
    required: true,
    async run({ harness }) {
      const filePath = path.join(workspaceRoot, "tools", "runtime_backbone_postgres_store.mjs");
      const source = await fs.readFile(filePath, "utf8");
      const requiredCorePaths = [
        "importLessonDraftBundle",
        "approveReviewTask",
        "requestReviewChanges",
        "publishLesson",
        "createQuestionBankItem",
        "createMaterialBuild",
        "addMaterialBuildItems",
        "exportMaterialBuild",
        "registerExportRun",
      ];
      const extractMethodBlock = (methodName) => {
        const start = source.indexOf(`async ${methodName}(`);
        if (start < 0) {
          return "";
        }
        const nextAsync = source.indexOf("\n  async ", start + 1);
        const nextClose = source.indexOf("\n}", start + 1);
        const endCandidates = [nextAsync, nextClose].filter((value) => value >= 0);
        const end = endCandidates.length ? Math.min(...endCandidates) : source.length;
        return source.slice(start, end);
      };
      for (const methodName of requiredCorePaths) {
        const methodBlock = extractMethodBlock(methodName);
        expect(methodBlock, `policy_core_write_method_missing:${methodName}`);
        expect(
          methodBlock.includes("return this.mutateScopedState("),
          `policy_core_write_not_scoped:${methodName}`
        );
        expect(
          !methodBlock.includes("return this.mutateState("),
          `policy_core_write_still_full_bridge:${methodName}`
        );
      }

      const server = await harness.startPostgresServer("arch002_test");
      const health = await server.request("/health");
      expect(health.ok, "arch002_health_failed");
      expect(
        health.data.storeHealth?.architectureMode === "scoped_table_write",
        "arch002_expected_scoped_table_write_marker_missing"
      );
      expect(
        health.data.storeHealth?.releaseChannel === "validation_baseline",
        "arch002_expected_validation_baseline_channel_missing"
      );
      const directCorePaths =
        health.data.storeHealth?.writePathAudit?.directCorePaths || [];
      const remainingMainBridgePaths =
        health.data.storeHealth?.writePathAudit?.remainingStateBridgePaths
          ?.mainBusiness || [];
      for (const methodName of requiredCorePaths) {
        expect(
          directCorePaths.includes(methodName),
          `arch002_core_write_audit_missing:${methodName}`
        );
        expect(
          !remainingMainBridgePaths.includes(methodName),
          `arch002_core_write_still_listed_as_bridge:${methodName}`
        );
      }
      return {
        releaseChannel: health.data.storeHealth.releaseChannel,
        architectureMode: health.data.storeHealth.architectureMode,
        directCorePaths,
        remainingMainBridgePaths,
      };
    },
  });
}
