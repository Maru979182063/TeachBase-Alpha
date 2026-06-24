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
    title: "Three-track validation fixtures remain isolated and searchable with stable task ids after publish",
    required: true,
    async run({ harness }) {
      const juniorMathBundle = await readJsonFixture("three_track", "math_junior_bundle.json");
      const seniorMathBundle = await readJsonFixture("three_track", "math_senior_bundle.json");
      const seniorEnglishBundle = await readJsonFixture("three_track", "english_senior_bundle.json");
      const server = await harness.startPostgresServer("business_golden_test");
      await importAndPublish(
        server,
        {
          ...juniorMathBundle,
          bundle_id: `${juniorMathBundle.bundle_id}_golden`,
          lesson_id: `${juniorMathBundle.lesson_id}_golden`,
        },
        "golden_math_junior"
      );
      await importAndPublish(
        server,
        {
          ...seniorMathBundle,
          bundle_id: `${seniorMathBundle.bundle_id}_golden`,
          lesson_id: `${seniorMathBundle.lesson_id}_golden`,
        },
        "golden_math_senior"
      );
      await importAndPublish(
        server,
        {
          ...seniorEnglishBundle,
          bundle_id: `${seniorEnglishBundle.bundle_id}_golden`,
          lesson_id: `${seniorEnglishBundle.lesson_id}_golden`,
        },
        "golden_english_senior"
      );
      const mathSearch = await server.request(
        `/api/runtime/task-projections/search?subject=${encodeURIComponent("数学")}&trackCode=math_junior&publishedOnly=true`
      );
      const seniorMathSearch = await server.request(
        `/api/runtime/task-projections/search?subject=${encodeURIComponent("数学")}&trackCode=math_senior&publishedOnly=true`
      );
      const englishSearch = await server.request(
        `/api/runtime/task-projections/search?subject=${encodeURIComponent("英语")}&trackCode=english_senior&publishedOnly=true`
      );
      const mathLocalTaskIds = mathSearch.data.items
        .filter((item) => item.lesson_id === `${juniorMathBundle.lesson_id}_golden`)
        .map((item) => item.local_task_id)
        .sort();
      const seniorMathLocalTaskIds = seniorMathSearch.data.items
        .filter((item) => item.lesson_id === `${seniorMathBundle.lesson_id}_golden`)
        .map((item) => item.local_task_id)
        .sort();
      const englishLocalTaskIds = englishSearch.data.items
        .filter((item) => item.lesson_id === `${seniorEnglishBundle.lesson_id}_golden`)
        .map((item) => item.local_task_id)
        .sort();
      expectEqual(mathLocalTaskIds, ["MJ-001", "MJ-002"], "math_junior_golden_task_ids_changed");
      expectEqual(seniorMathLocalTaskIds, ["MS-001", "MS-002"], "math_senior_golden_task_ids_changed");
      expectEqual(englishLocalTaskIds, ["ES-001", "ES-002"], "english_senior_golden_task_ids_changed");
      return {
        mathLocalTaskIds,
        seniorMathLocalTaskIds,
        englishLocalTaskIds,
      };
    },
  });
}
