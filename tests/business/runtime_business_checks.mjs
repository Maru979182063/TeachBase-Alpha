/**
 * 用途：
 * - 从操作者视角覆盖导入、审批、发布等业务流程。
 * - 场景描述应贴近人实际执行的工作流。
 */

import {
  expect,
  expectEqual,
  readJsonFixture,
} from "../helpers/runtime_testkit.mjs";

async function importAndPublish(server, bundle, actor) {
  const reviewerActor = `${actor}_reviewer`;
  const publisherActor = `${actor}_publisher`;
  const imported = await server.request("/api/runtime/imports/lesson-draft-bundles", {
    method: "POST",
    body: {
      actor,
      bundle,
    },
  });
  expect(imported.ok, `${actor}_import_failed`);
  await server.request(`/api/runtime/review-tasks/${imported.data.result.reviewTaskId}/approve`, {
    method: "POST",
    body: {
      actor: reviewerActor,
    },
  });
  await server.request(`/api/runtime/lessons/${bundle.lesson_id}/publish`, {
    method: "POST",
    body: {
      actor: publisherActor,
      lessonRevisionId: imported.data.result.lessonRevisionId,
    },
  });
}

export function registerTests(register) {
  register({
    id: "D18",
    suite: "business",
    title: "Duplicate local_task_id bundles are rejected",
    required: true,
    async run({ harness }) {
      const invalidBundle = await readJsonFixture("invalid", "duplicate_local_task_id.json");
      const server = await harness.startPostgresServer("business_invalid_bundle_test");
      const response = await server.request("/api/runtime/imports/lesson-draft-bundles", {
        method: "POST",
        body: {
          actor: "business_suite",
          bundle: invalidBundle,
        },
      });
      expect(response.status === 409, `duplicate_local_task_status_mismatch:${response.status}`);
      expect(response.data?.error === "duplicate_local_task_id", "duplicate_local_task_error_mismatch");
      return {
        status: response.status,
      };
    },
  });

  register({
    id: "GOLDEN-01",
    suite: "business",
    title: "Math and Chinese validation fixtures remain searchable with stable task ids after publish",
    required: true,
    async run({ harness }) {
      const mathBundle = await readJsonFixture("math", "minimal_bundle.json");
      const chineseBundle = await readJsonFixture("chinese", "minimal_bundle.json");
      const server = await harness.startPostgresServer("business_golden_test");
      await importAndPublish(
        server,
        {
          ...mathBundle,
          bundle_id: `${mathBundle.bundle_id}_golden`,
          lesson_id: `${mathBundle.lesson_id}_golden`,
        },
        "golden_math"
      );
      await importAndPublish(
        server,
        {
          ...chineseBundle,
          bundle_id: `${chineseBundle.bundle_id}_golden`,
          lesson_id: `${chineseBundle.lesson_id}_golden`,
        },
        "golden_chinese"
      );
      const mathSearch = await server.request(
        `/api/runtime/task-projections/search?subject=${encodeURIComponent("数学")}&publishedOnly=true`
      );
      const chineseSearch = await server.request(
        `/api/runtime/task-projections/search?subject=${encodeURIComponent("语文")}&publishedOnly=true`
      );
      const mathLocalTaskIds = mathSearch.data.items
        .filter((item) => item.lesson_id === `${mathBundle.lesson_id}_golden`)
        .map((item) => item.local_task_id)
        .sort();
      const chineseLocalTaskIds = chineseSearch.data.items
        .filter((item) => item.lesson_id === `${chineseBundle.lesson_id}_golden`)
        .map((item) => item.local_task_id)
        .sort();
      expectEqual(mathLocalTaskIds, ["M-001", "M-002"], "math_golden_task_ids_changed");
      expectEqual(chineseLocalTaskIds, ["C-001", "C-002"], "chinese_golden_task_ids_changed");
      return {
        mathLocalTaskIds,
        chineseLocalTaskIds,
      };
    },
  });
}
