/**
 * Purpose:
 * - prove GET search paths do not write to task_projection or question-bank tables
 * - keep rebuild behavior on an explicit write endpoint instead of a read side effect
 */

import {
  expect,
  readJsonFixture,
} from "../helpers/runtime_testkit.mjs";

async function importApprovePublish(server, bundle, actor) {
  const imported = await server.request("/api/runtime/imports/lesson-draft-bundles", {
    method: "POST",
    body: {
      actor,
      bundle,
    },
  });
  expect(imported.ok, `${actor}_import_failed:${JSON.stringify(imported.data)}`);

  const approved = await server.request(
    `/api/runtime/review-tasks/${imported.data.result.reviewTaskId}/approve`,
    {
      method: "POST",
      body: {
        actor: `${actor}_reviewer`,
      },
    }
  );
  expect(approved.ok, `${actor}_approve_failed:${JSON.stringify(approved.data)}`);

  const published = await server.request(`/api/runtime/lessons/${bundle.lesson_id}/publish`, {
    method: "POST",
    body: {
      actor: `${actor}_publisher`,
      lessonRevisionId: imported.data.result.lessonRevisionId,
    },
  });
  expect(published.ok, `${actor}_publish_failed:${JSON.stringify(published.data)}`);
  return published.data.result;
}

export function registerTests(register) {
  register({
    id: "READPATH-01",
    suite: "projection_read_path",
    title: "GET task-projection search reports degradation without writing rows back",
    required: true,
    async run({ harness }) {
      const bundle = await readJsonFixture("three_track", "math_senior_bundle.json");
      const server = await harness.startPostgresServer("projection_read_path_test");
      await importApprovePublish(server, bundle, "readpath");

      await harness.queryDatabase(
        server.database.connectionString,
        `delete from task_projection where lesson_id = $1`,
        [bundle.lesson_id]
      );
      const before = await harness.queryDatabase(
        server.database.connectionString,
        `select count(*)::int as row_count from task_projection where lesson_id = $1`,
        [bundle.lesson_id]
      );
      expect(before.rows[0].row_count === 0, "readpath_projection_rows_should_be_deleted");

      const search = await server.request(
        `/api/runtime/task-projections/search?subject=${encodeURIComponent("数学")}&stage=senior&trackCode=math_senior&publishedOnly=true`
      );
      expect(search.ok, `readpath_projection_search_failed:${JSON.stringify(search.data)}`);
      expect(search.data.projectionCoverage?.needsRebuild === true, "readpath_projection_should_need_rebuild");

      const after = await harness.queryDatabase(
        server.database.connectionString,
        `select count(*)::int as row_count from task_projection where lesson_id = $1`,
        [bundle.lesson_id]
      );
      expect(after.rows[0].row_count === 0, "readpath_projection_search_should_not_write_rows");
      return {
        rowCountAfterSearch: after.rows[0].row_count,
      };
    },
  });

  register({
    id: "READPATH-02",
    suite: "projection_read_path",
    title: "GET question-bank search does not mutate question-bank storage",
    required: true,
    async run({ harness }) {
      const bundle = await readJsonFixture("english", "minimal_bundle.json");
      const lessonId = `${bundle.lesson_id}_readpath`;
      const server = await harness.startPostgresServer("question_bank_read_path_test");
      await importApprovePublish(
        server,
        {
          ...bundle,
          lesson_id: lessonId,
          bundle_id: `${bundle.bundle_id}_readpath`,
        },
        "qb_readpath"
      );

      const search = await server.request(
        `/api/runtime/task-projections/search?subject=${encodeURIComponent(bundle.subject)}&trackCode=english_senior&publishedOnly=true`
      );
      expect(search.ok, "qb_readpath_projection_search_failed");
      const created = await server.request("/api/question-bank/items", {
        method: "POST",
        body: {
          actor: "qb_readpath",
          taskProjectionId: search.data.items.find((item) => item.lesson_id === lessonId).task_projection_id,
        },
      });
      expect(created.ok, `qb_readpath_create_failed:${JSON.stringify(created.data)}`);

      const before = await harness.queryDatabase(
        server.database.connectionString,
        `
          select
            (select count(*)::int from question_bank_item) as item_count,
            (select count(*)::int from question_bank_item_revision) as revision_count
        `
      );
      const response = await server.request(
        `/api/question-bank/search?subject=${encodeURIComponent(bundle.subject)}&trackCode=english_senior`
      );
      expect(response.ok, `qb_readpath_search_failed:${JSON.stringify(response.data)}`);
      const after = await harness.queryDatabase(
        server.database.connectionString,
        `
          select
            (select count(*)::int from question_bank_item) as item_count,
            (select count(*)::int from question_bank_item_revision) as revision_count
        `
      );
      expect(
        before.rows[0].item_count === after.rows[0].item_count &&
          before.rows[0].revision_count === after.rows[0].revision_count,
        "qb_readpath_search_should_not_change_counts"
      );
      return {
        itemCount: after.rows[0].item_count,
        revisionCount: after.rows[0].revision_count,
      };
    },
  });
}
