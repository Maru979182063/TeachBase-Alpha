/**
 * 用途：
 * - 压力检查并发写入和锁行为。
 * - 这些检查用于在生产工作流暴露前捕获竞态问题。
 */

import {
  expect,
  readJsonFixture,
} from "../helpers/runtime_testkit.mjs";

export function registerTests(register) {
  register({
    id: "D12-E10",
    suite: "concurrency",
    title: "Concurrent identical imports and publishes do not create duplicate effective state",
    required: true,
    async run({ harness }) {
      const bundle = await readJsonFixture("math", "minimal_bundle.json");
      const targetBundle = {
        ...bundle,
        bundle_id: `${bundle.bundle_id}_concurrency`,
        lesson_id: `${bundle.lesson_id}_concurrency`,
      };
      const server = await harness.startPostgresServer("concurrency_test");
      const importRequests = await Promise.all([
        server.request("/api/runtime/imports/lesson-draft-bundles", {
          method: "POST",
          body: {
            actor: "concurrency_suite",
            bundle: targetBundle,
          },
        }),
        server.request("/api/runtime/imports/lesson-draft-bundles", {
          method: "POST",
          body: {
            actor: "concurrency_suite",
            bundle: targetBundle,
          },
        }),
      ]);
      for (const response of importRequests) {
        expect(response.ok, `concurrent_import_failed:${JSON.stringify(response.data)}`);
      }
      const reviewTaskId = importRequests[0].data.result.reviewTaskId;
      const revisionId = importRequests[0].data.result.lessonRevisionId;
      const approved = await server.request(`/api/runtime/review-tasks/${reviewTaskId}/approve`, {
        method: "POST",
        body: {
          actor: "concurrency_reviewer",
        },
      });
      expect(approved.ok, "concurrent_publish_approve_failed");
      const publishRequests = await Promise.all([
        server.request(`/api/runtime/lessons/${targetBundle.lesson_id}/publish`, {
          method: "POST",
          body: {
            actor: "concurrency_publisher",
            lessonRevisionId: revisionId,
          },
        }),
        server.request(`/api/runtime/lessons/${targetBundle.lesson_id}/publish`, {
          method: "POST",
          body: {
            actor: "concurrency_publisher",
            lessonRevisionId: revisionId,
          },
        }),
      ]);
      for (const response of publishRequests) {
        expect(response.ok, `concurrent_publish_failed:${JSON.stringify(response.data)}`);
      }
      const state = await server.request("/api/runtime/debug/state");
      const imports = state.data.state.imports.filter((item) => item.bundle_id === targetBundle.bundle_id);
      const publications = state.data.state.publications.filter(
        (item) =>
          item.lesson_id === targetBundle.lesson_id &&
          item.lesson_revision_id === revisionId
      );
      expect(imports.length === 1, `duplicate_imports_detected:${imports.length}`);
      expect(publications.length === 1, `duplicate_publications_detected:${publications.length}`);
      return {
        importResponses: importRequests.map((item) => item.data.result.idempotent),
        publicationId: publications[0].publication_id,
      };
    },
  });
}
