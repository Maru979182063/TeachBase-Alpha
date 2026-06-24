/**
 * 用途：
 * - 强制制造局部失败场景，用来验证回滚行为和错误暴露。
 * - 当修复依赖失败顺序或清理保证时，应在这里补用例。
 */

import {
  expect,
  readJsonFixture,
} from "../helpers/runtime_testkit.mjs";

export function registerTests(register) {
  register({
    id: "P08",
    suite: "failure_injection",
    title: "Import failpoint rolls back the entire revision write",
    required: true,
    async run({ harness }) {
      const bundle = await readJsonFixture("math", "minimal_bundle.json");
      const server = await harness.startPostgresServer({
        prefix: "failure_import_test",
        env: {
          TEST_FAILPOINT: "import_after_hydrate_before_active_pointer",
        },
      });
      const targetLessonId = `${bundle.lesson_id}_fail`;
      const response = await server.request("/api/runtime/imports/lesson-draft-bundles", {
        method: "POST",
        body: {
          actor: "failure_suite",
          bundle: {
            ...bundle,
            bundle_id: `${bundle.bundle_id}_fail`,
            lesson_id: targetLessonId,
          },
        },
      });
      expect(response.status === 500, `import_failpoint_status_mismatch:${response.status}`);
      expect(
        response.data?.error === "failpoint:import_after_hydrate_before_active_pointer",
        "import_failpoint_error_mismatch"
      );
      const detail = await server.request(`/api/runtime/lessons/${targetLessonId}`);
      expect(detail.status === 404, "failed_import_should_not_leave_lesson_visible");
      return {
        status: response.status,
        requestId: response.headers["x-request-id"],
      };
    },
  });

  register({
    id: "P10",
    suite: "failure_injection",
    title: "Publish failpoint rolls back publication pointer changes",
    required: true,
    async run({ harness }) {
      const bundle = await readJsonFixture("english", "minimal_bundle.json");
      const server = await harness.startPostgresServer({
        prefix: "failure_publish_test",
        env: {
          TEST_FAILPOINT: "publish_after_publication_before_pointer",
        },
      });
      const targetLessonId = `${bundle.lesson_id}_publish_fail`;
      const imported = await server.request("/api/runtime/imports/lesson-draft-bundles", {
        method: "POST",
        body: {
          actor: "failure_suite",
          bundle: {
            ...bundle,
            bundle_id: `${bundle.bundle_id}_publish_fail`,
            lesson_id: targetLessonId,
          },
        },
      });
      expect(imported.ok, "publish_failpoint_import_failed");
      const approved = await server.request(
        `/api/runtime/review-tasks/${imported.data.result.reviewTaskId}/approve`,
        {
          method: "POST",
          body: {
            actor: "failure_reviewer",
          },
        }
      );
      expect(approved.ok, "publish_failpoint_approve_failed");
      const publish = await server.request(`/api/runtime/lessons/${targetLessonId}/publish`, {
        method: "POST",
        body: {
          actor: "failure_publisher",
          lessonRevisionId: imported.data.result.lessonRevisionId,
        },
      });
      expect(publish.status === 500, `publish_failpoint_status_mismatch:${publish.status}`);
      expect(
        publish.data?.error === "failpoint:publish_after_publication_before_pointer",
        "publish_failpoint_error_mismatch"
      );
      const detail = await server.request(`/api/runtime/lessons/${targetLessonId}`);
      expect(detail.ok, "publish_failpoint_detail_failed");
      expect(
        detail.data.detail.lesson.published_revision_id === null,
        "publish_failpoint_should_not_move_published_pointer"
      );
      const consistency = await server.request("/api/runtime/internal/consistency");
      expect(consistency.data.detail.ok === true, "publish_failpoint_should_keep_consistency");
      return {
        lessonId: targetLessonId,
        consistencyStatus: consistency.data.detail.status,
      };
    },
  });
}
