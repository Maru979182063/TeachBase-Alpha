/**
 * 用途：
 * - 检查仅 Postgres 状态模式及相关迁移假设。
 * - 这个套件证明运行时可以在不回退到文件状态权威的情况下工作。
 */

import {
  expect,
  readJsonFixture,
} from "../helpers/runtime_testkit.mjs";

export function registerTests(register) {
  register({
    id: "PGSS-01",
    suite: "postgres-sole-source",
    title: "Postgres can start and serve lesson facts without any snapshot row",
    required: true,
    async run({ harness }) {
      const bundle = await readJsonFixture("math", "minimal_bundle.json");
      const database = await harness.createPostgresDatabase("pgss_startup_test");
      const server = await harness.startPostgresServer({
        database,
        env: {
          POSTGRES_SOLE_SOURCE: "true",
        },
      });

      const snapshotCount = await harness.queryDatabase(
        database.connectionString,
        "select count(*)::int as count from runtime_state_snapshot"
      );
      expect(Number(snapshotCount.rows[0].count) === 0, "snapshot_row_should_not_be_required_at_boot");

      const imported = await server.request("/api/runtime/imports/lesson-draft-bundles", {
        method: "POST",
        body: {
          actor: "pgss_suite",
          bundle: {
            ...bundle,
            lesson_id: `${bundle.lesson_id}_pgss`,
            bundle_id: `${bundle.bundle_id}_pgss`,
          },
        },
      });
      expect(imported.ok, `pgss_import_failed:${JSON.stringify(imported.data)}`);

      const detail = await server.request(`/api/runtime/lessons/${bundle.lesson_id}_pgss`);
      expect(detail.ok, `pgss_detail_failed:${JSON.stringify(detail.data)}`);
      expect(detail.data.detail.lesson.lesson_id === `${bundle.lesson_id}_pgss`, "pgss_detail_mismatch");

      return {
        lessonId: `${bundle.lesson_id}_pgss`,
        snapshotCount: Number(snapshotCount.rows[0].count),
      };
    },
  });

  register({
    id: "PGSS-02",
    suite: "postgres-sole-source",
    title: "Corrupt snapshot rows do not block published reads after restart",
    required: true,
    async run({ harness }) {
      const bundle = await readJsonFixture("chinese", "minimal_bundle.json");
      const lessonId = `${bundle.lesson_id}_pgss_restart`;
      const database = await harness.createPostgresDatabase("pgss_restart_test");
      const firstServer = await harness.startPostgresServer({
        database,
        env: {
          POSTGRES_SOLE_SOURCE: "true",
        },
      });

      const imported = await firstServer.request("/api/runtime/imports/lesson-draft-bundles", {
        method: "POST",
        body: {
          actor: "pgss_suite",
          bundle: {
            ...bundle,
            lesson_id: lessonId,
            bundle_id: `${bundle.bundle_id}_pgss_restart`,
          },
        },
      });
      expect(imported.ok, `pgss_restart_import_failed:${JSON.stringify(imported.data)}`);

      const approved = await firstServer.request(
        `/api/runtime/review-tasks/${imported.data.result.reviewTaskId}/approve`,
        {
          method: "POST",
          body: {
            actor: "pgss_reviewer",
          },
        }
      );
      expect(approved.ok, `pgss_restart_approve_failed:${JSON.stringify(approved.data)}`);

      const published = await firstServer.request(`/api/runtime/lessons/${lessonId}/publish`, {
        method: "POST",
        body: {
          actor: "pgss_publisher",
        },
      });
      expect(published.ok, `pgss_restart_publish_failed:${JSON.stringify(published.data)}`);

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
            '{"lessons":[{"lesson_id":"pgss_snapshot_fake"}]}'::jsonb,
            77,
            'pgss_fake_hash',
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

      const secondServer = await harness.startPostgresServer({
        database,
        env: {
          POSTGRES_SOLE_SOURCE: "true",
        },
      });
      const search = await secondServer.request(
        `/api/runtime/task-projections/search?subject=${encodeURIComponent(bundle.subject)}&publishedOnly=true`
      );
      expect(search.ok, `pgss_restart_search_failed:${JSON.stringify(search.data)}`);
      expect(
        search.data.items.some((item) => item.lesson_id === lessonId),
        "published_lesson_missing_after_restart"
      );

      const lessons = await secondServer.request("/api/runtime/lessons");
      expect(lessons.ok, "pgss_restart_lessons_failed");
      expect(
        !lessons.data.items.some((item) => item.lesson_id === "pgss_snapshot_fake"),
        "snapshot_row_should_not_rehydrate_fake_lessons"
      );

      const snapshotRow = await harness.queryDatabase(
        database.connectionString,
        "select snapshot_version from runtime_state_snapshot where snapshot_key = 'default'"
      );
      expect(Number(snapshotRow.rows[0].snapshot_version) === 77, "snapshot_row_should_remain_debug_only");

      return {
        lessonId,
        publishedSearchCount: search.data.items.filter((item) => item.lesson_id === lessonId).length,
      };
    },
  });
}
