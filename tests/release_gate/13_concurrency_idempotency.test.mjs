import {
  expect,
  readJsonFixture,
} from "../helpers/runtime_testkit.mjs";
import {
  buildQuestionVisualStructure,
  buildVisualAsset,
} from "./release_gate_shared.mjs";

export function registerTests(register) {
  register({
    id: "RG-CONC-01",
    suite: "release_gate_concurrency",
    title: "Five concurrent identical imports and publishes collapse to one effective import and one publication",
    required: true,
    async run({ harness }) {
      const bundle = await readJsonFixture("math", "minimal_bundle.json");
      const server = await harness.startPostgresServer(
        "release_gate_concurrency_test"
      );
      const targetBundle = {
        ...bundle,
        bundle_id: `${bundle.bundle_id}_release_gate_concurrency`,
        lesson_id: `${bundle.lesson_id}_release_gate_concurrency`,
      };

      const imports = await Promise.all(
        Array.from({ length: 5 }, () =>
          server.request("/api/runtime/imports/lesson-draft-bundles", {
            method: "POST",
            body: {
              actor: "release_gate_concurrency",
              bundle: targetBundle,
            },
          })
        )
      );
      for (const response of imports) {
        expect(response.ok, `release_gate_concurrent_import_failed:${JSON.stringify(response.data)}`);
      }

      const reviewTaskId = imports[0].data.result.reviewTaskId;
      const revisionId = imports[0].data.result.lessonRevisionId;
      const approved = await server.request(
        `/api/runtime/review-tasks/${reviewTaskId}/approve`,
        {
          method: "POST",
          body: {
            actor: "release_gate_concurrency_reviewer",
          },
        }
      );
      expect(approved.ok, `release_gate_concurrent_approve_failed:${JSON.stringify(approved.data)}`);

      const publishes = await Promise.all(
        Array.from({ length: 5 }, () =>
          server.request(
            `/api/runtime/lessons/${targetBundle.lesson_id}/publish`,
            {
              method: "POST",
              body: {
                actor: "release_gate_concurrency_publisher",
                lessonRevisionId: revisionId,
              },
            }
          )
        )
      );
      for (const response of publishes) {
        expect(response.ok, `release_gate_concurrent_publish_failed:${JSON.stringify(response.data)}`);
      }

      const state = await server.request("/api/runtime/debug/state");
      const importsInState = state.data.state.imports.filter(
        (item) => item.bundle_id === targetBundle.bundle_id
      );
      const publicationsInState = state.data.state.publications.filter(
        (item) =>
          item.lesson_id === targetBundle.lesson_id &&
          item.lesson_revision_id === revisionId
      );
      expect(importsInState.length === 1, `release_gate_duplicate_imports:${importsInState.length}`);
      expect(
        publicationsInState.length === 1,
        `release_gate_duplicate_publications:${publicationsInState.length}`
      );
      return {
        importIdempotentFlags: imports.map((response) => response.data.result.idempotent),
        publicationId: publicationsInState[0].publication_id,
      };
    },
  });

  register({
    id: "RG-CONC-02",
    suite: "release_gate_concurrency",
    title: "Repeated storage key generation for the same question requires a version segment so reruns do not collide",
    required: true,
    async run() {
      const oldAsset = buildVisualAsset({
        questionUid: "release_gate_storage_collision",
        runtimeRunId: "run_old",
        optionKey: "A",
      });
      const newAsset = buildVisualAsset({
        questionUid: "release_gate_storage_collision",
        runtimeRunId: "run_new",
        optionKey: "A",
      });
      const oldQvs = buildQuestionVisualStructure({
        question_uid: "release_gate_storage_collision",
        runtime_run_id: "run_old",
        visual_assets: [oldAsset],
        options: [
          {
            option_key: "A",
            asset_ids: [oldAsset.asset_id],
            bbox_space: "option_crop",
          },
        ],
        legacy_stem_md: `A. ![${oldAsset.asset_id}](${oldAsset.display_ref})`,
      });
      const newQvs = buildQuestionVisualStructure({
        question_uid: "release_gate_storage_collision",
        runtime_run_id: "run_new",
        visual_assets: [newAsset],
        options: [
          {
            option_key: "A",
            asset_ids: [newAsset.asset_id],
            bbox_space: "option_crop",
          },
        ],
        legacy_stem_md: `A. ![${newAsset.asset_id}](${newAsset.display_ref})`,
      });
      expect(
        oldQvs.visual_assets[0].storage_key !== newQvs.visual_assets[0].storage_key,
        "release_gate_storage_key_collision_detected"
      );
      return {
        oldStorageKey: oldQvs.visual_assets[0].storage_key,
        newStorageKey: newQvs.visual_assets[0].storage_key,
      };
    },
  });
}
