/**
 * Purpose:
 * - cover the validation-baseline three-track lifecycle and isolation rules
 * - keep this suite focused on validation readiness instead of production readiness
 */

import {
  expect,
  expectEqual,
  readJsonFixture,
} from "../helpers/runtime_testkit.mjs";

const trackExpectations = {
  math_junior: {
    subject: "数学",
    stage: "junior",
    pluginId: "subject.math.junior.v1",
    difficultyScheme: "difficulty.math.junior.v1",
    lessonId: "three_track_math_junior_lesson",
    taskIds: ["MJ-001", "MJ-002"],
    expectedCheckpoints: {
      "MJ-001": ["一元一次方程"],
      "MJ-002": ["一元一次方程", "整式加减"],
    },
  },
  math_senior: {
    subject: "数学",
    stage: "senior",
    pluginId: "subject.math.senior.v1",
    difficultyScheme: "difficulty.math.senior.v1",
    lessonId: "three_track_math_senior_lesson",
    taskIds: ["MS-001", "MS-002"],
    expectedCheckpoints: {
      "MS-001": ["导数单调性"],
      "MS-002": ["数列递推"],
    },
  },
  english_senior: {
    subject: "英语",
    stage: "senior",
    pluginId: "subject.english.senior.v1",
    difficultyScheme: "difficulty.english.senior.v1",
    lessonId: "three_track_english_senior_lesson",
    taskIds: ["ES-001", "ES-002"],
    expectedCheckpoints: {
      "ES-001": ["阅读理解主旨大意", "阅读理解细节定位"],
      "ES-002": ["阅读理解主旨大意"],
    },
  },
};

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

  const detail = await server.request(`/api/runtime/lessons/${bundle.lesson_id}`);
  expect(detail.ok, `${actor}_detail_failed:${JSON.stringify(detail.data)}`);
  return {
    imported: imported.data.result,
    detail: detail.data.detail,
  };
}

export function registerTests(register) {
  register({
    id: "TT01-TT08",
    suite: "three_track",
    title: "Three tracks stay isolated across publish, search, question bank, material build, export, and component rerun",
    required: true,
    async run({ harness }) {
      const server = await harness.startPostgresServer("three_track_baseline_test");
      const bundles = {
        math_junior: await readJsonFixture("three_track", "math_junior_bundle.json"),
        math_senior: await readJsonFixture("three_track", "math_senior_bundle.json"),
        english_senior: await readJsonFixture("three_track", "english_senior_bundle.json"),
      };

      const published = {};
      const questionBankRevisionIdsByTrack = new Map();

      for (const [trackCode, bundle] of Object.entries(bundles)) {
        published[trackCode] = await importApprovePublish(server, bundle, `baseline_${trackCode}`);
        const expectation = trackExpectations[trackCode];
        const detail = published[trackCode].detail;

        expect(detail.lesson.track_code === trackCode, `${trackCode}_lesson_track_code_mismatch`);
        expect(detail.lesson.subject === expectation.subject, `${trackCode}_lesson_subject_mismatch`);
        expect(detail.lesson.stage === expectation.stage, `${trackCode}_lesson_stage_mismatch`);
        expect(
          detail.taskSubjectExt.every((item) => item.plugin_id === expectation.pluginId),
          `${trackCode}_plugin_id_mismatch`
        );
        if (trackCode === "english_senior") {
          expect(
            detail.taskSubjectExt.every((item) => !String(item.plugin_id).includes("subject.math")),
            "english_track_should_not_use_math_plugin"
          );
        }

        const search = await server.request(
          `/api/runtime/task-projections/search?subject=${encodeURIComponent(expectation.subject)}&stage=${encodeURIComponent(expectation.stage)}&trackCode=${encodeURIComponent(trackCode)}&publishedOnly=true`
        );
        expect(search.ok, `${trackCode}_projection_search_failed`);
        const lessonItems = search.data.items.filter((item) => item.lesson_id === bundle.lesson_id);
        expectEqual(
          lessonItems.map((item) => item.local_task_id).sort(),
          expectation.taskIds,
          `${trackCode}_projection_task_ids_mismatch`
        );
        for (const item of lessonItems) {
          expect(item.track_code === trackCode, `${trackCode}_projection_track_code_mismatch`);
          expect(item.stage === expectation.stage, `${trackCode}_projection_stage_mismatch`);
          expect(
            item.difficulty_scheme === expectation.difficultyScheme,
            `${trackCode}_difficulty_scheme_mismatch`
          );
          expect(
            item.difficulty_level >= 1 && item.difficulty_level <= 5,
            `${trackCode}_difficulty_level_out_of_range`
          );
          expectEqual(
            [...item.checkpoint_codes].sort(),
            [...expectation.expectedCheckpoints[item.local_task_id]].sort(),
            `${trackCode}_${item.local_task_id}_checkpoint_mismatch`
          );
        }

        const overridesByTask = new Map(
          detail.taskCheckpointOverrides.map((item) => [item.task_revision_id, item.relation_type])
        );
        const detailTaskById = new Map(detail.tasks.map((item) => [item.stable_question_no, item]));
        if (trackCode === "math_junior") {
          expect(
            !overridesByTask.has(detailTaskById.get("MJ-001").current_revision_id),
            "math_junior_regular_task_should_inherit"
          );
          expect(
            overridesByTask.get(detailTaskById.get("MJ-002").current_revision_id) === "add",
            "math_junior_override_should_be_add"
          );
        }
        if (trackCode === "math_senior") {
          expect(
            !overridesByTask.has(detailTaskById.get("MS-001").current_revision_id),
            "math_senior_regular_task_should_inherit"
          );
          expect(
            overridesByTask.get(detailTaskById.get("MS-002").current_revision_id) === "replace",
            "math_senior_override_should_be_replace"
          );
        }
        if (trackCode === "english_senior") {
          expect(
            !overridesByTask.has(detailTaskById.get("ES-001").current_revision_id),
            "english_regular_task_should_inherit"
          );
          expect(
            overridesByTask.get(detailTaskById.get("ES-002").current_revision_id) === "remove",
            "english_override_should_be_remove"
          );
        }

        const revisionIds = [];
        for (const item of lessonItems) {
          const created = await server.request("/api/question-bank/items", {
            method: "POST",
            body: {
              actor: `qb_${trackCode}`,
              taskProjectionId: item.task_projection_id,
            },
          });
          expect(created.ok, `${trackCode}_question_bank_create_failed:${JSON.stringify(created.data)}`);
          revisionIds.push(created.data.result.revision.question_bank_item_revision_id);
        }
        questionBankRevisionIdsByTrack.set(trackCode, revisionIds);

        const questionBankSearch = await server.request(
          `/api/question-bank/search?subject=${encodeURIComponent(expectation.subject)}&stage=${encodeURIComponent(expectation.stage)}&trackCode=${encodeURIComponent(trackCode)}`
        );
        expect(questionBankSearch.ok, `${trackCode}_question_bank_search_failed`);
        expectEqual(
          questionBankSearch.data.items.filter((item) => item.item?.track_code === trackCode).length,
          2,
          `${trackCode}_question_bank_count_mismatch`
        );

        const build = await server.request("/api/material-builds", {
          method: "POST",
          body: {
            actor: `material_${trackCode}`,
            lessonId: bundle.lesson_id,
            teacherName: "validation_teacher",
            buildName: `${trackCode}_build`,
          },
        });
        expect(build.ok, `${trackCode}_material_build_create_failed:${JSON.stringify(build.data)}`);
        const materialBuildId = build.data.result.material_build_id;

        const addItems = await server.request(`/api/material-builds/${materialBuildId}/items`, {
          method: "POST",
          body: {
            items: revisionIds.map((revisionId, index) => ({
              questionBankItemRevisionId: revisionId,
              sectionKey: "body",
              sortIndex: index + 1,
            })),
          },
        });
        expect(addItems.ok, `${trackCode}_material_add_items_failed:${JSON.stringify(addItems.data)}`);

        const exported = await server.request(`/api/material-builds/${materialBuildId}/export`, {
          method: "POST",
          body: {
            actor: `material_${trackCode}_exporter`,
          },
        });
        expect(exported.ok, `${trackCode}_material_export_failed:${JSON.stringify(exported.data)}`);

        const componentId = detail.componentRevisions[0]?.component_id;
        expect(componentId, `${trackCode}_component_missing`);
        const rerun = await server.request(`/api/runtime/components/${componentId}/rerun`, {
          method: "POST",
          body: {
            actor: `rerun_${trackCode}`,
            proposedText: `${trackCode} validation rerun text`,
            note: `${trackCode} validation rerun`,
          },
        });
        expect(rerun.ok, `${trackCode}_component_rerun_failed:${JSON.stringify(rerun.data)}`);
        const patchId = rerun.data.result.patch.component_patch_candidate_id;
        const accepted = await server.request(`/api/runtime/component-patches/${patchId}/accept`, {
          method: "POST",
          body: {
            actor: `rerun_${trackCode}_reviewer`,
          },
        });
        expect(accepted.ok, `${trackCode}_component_patch_accept_failed:${JSON.stringify(accepted.data)}`);

        if (trackCode === "english_senior") {
          const mismatch = await server.request(`/api/material-builds/${materialBuildId}/items`, {
            method: "POST",
            body: {
              items: [
                {
                  questionBankItemRevisionId: questionBankRevisionIdsByTrack.get("math_junior")[0],
                  sectionKey: "body",
                  sortIndex: 99,
                },
              ],
            },
          });
          expect(mismatch.status === 409, `english_material_mismatch_status:${mismatch.status}`);
          expect(
            mismatch.data?.error === "material_build_track_mismatch",
            "english_material_mismatch_error"
          );
        }
      }

      return {
        publishedLessons: Object.keys(published),
        englishRevisionIds: questionBankRevisionIdsByTrack.get("english_senior"),
      };
    },
  });

  register({
    id: "TT09",
    suite: "three_track",
    title: "Deleting task_projection rows requires an explicit rebuild before search returns the full projection set",
    required: true,
    async run({ harness }) {
      const server = await harness.startPostgresServer("three_track_projection_rebuild_test");
      const bundle = await readJsonFixture("three_track", "math_senior_bundle.json");
      await importApprovePublish(server, bundle, "projection_rebuild");

      const beforeDelete = await harness.queryDatabase(
        server.database.connectionString,
        `select count(*)::int as row_count from task_projection where lesson_id = $1`,
        [bundle.lesson_id]
      );
      expect(beforeDelete.rows[0].row_count === 2, "projection_rows_before_delete_mismatch");

      await harness.queryDatabase(
        server.database.connectionString,
        `delete from task_projection where lesson_id = $1`,
        [bundle.lesson_id]
      );
      const afterDelete = await harness.queryDatabase(
        server.database.connectionString,
        `select count(*)::int as row_count from task_projection where lesson_id = $1`,
        [bundle.lesson_id]
      );
      expect(afterDelete.rows[0].row_count === 0, "projection_rows_should_be_deleted");

      const degradedSearch = await server.request(
        `/api/runtime/task-projections/search?subject=${encodeURIComponent("数学")}&stage=senior&trackCode=math_senior&publishedOnly=true`
      );
      expect(
        degradedSearch.ok,
        `projection_rebuild_search_failed:${JSON.stringify(degradedSearch.data)}`
      );
      expect(
        degradedSearch.data.projectionCoverage?.needsRebuild === true,
        "projection_rebuild_should_report_degraded_before_repair"
      );
      expect(
        degradedSearch.data.items.filter((item) => item.lesson_id === bundle.lesson_id).length === 0,
        "projection_rows_should_not_be_rehydrated_by_get_search"
      );

      const rebuilt = await server.request("/api/runtime/internal/task-projections/rebuild", {
        method: "POST",
        body: {
          lessonId: bundle.lesson_id,
        },
      });
      expect(rebuilt.ok, `projection_rebuild_request_failed:${JSON.stringify(rebuilt.data)}`);

      const search = await server.request(
        `/api/runtime/task-projections/search?subject=${encodeURIComponent("数学")}&stage=senior&trackCode=math_senior&publishedOnly=true`
      );
      expect(
        search.ok,
        `projection_rebuild_search_after_fix_failed:${JSON.stringify(search.data)}`
      );
      expect(
        search.data.projectionCoverage?.needsRebuild === false,
        "projection_rebuild_should_report_healthy_after_repair"
      );
      expectEqual(
        search.data.items
          .filter((item) => item.lesson_id === bundle.lesson_id)
          .map((item) => item.local_task_id)
          .sort(),
        ["MS-001", "MS-002"],
        "projection_rebuild_search_results_mismatch"
      );

      const afterRepair = await harness.queryDatabase(
        server.database.connectionString,
        `select count(*)::int as row_count from task_projection where lesson_id = $1`,
        [bundle.lesson_id]
      );
      expect(afterRepair.rows[0].row_count === 2, "projection_rows_should_be_rebuilt");
      return {
        rowCountAfterRepair: afterRepair.rows[0].row_count,
      };
    },
  });
}
