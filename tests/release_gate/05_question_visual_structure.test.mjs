import {
  expect,
} from "../helpers/runtime_testkit.mjs";
import {
  resolveQuestionVisualAsset,
  validateQuestionVisualSourceRefs,
} from "../../tools/runtime_visual_split_adapter.mjs";
import {
  buildLegacySourceRefs,
  buildQuestionVisualStructure,
  buildVisualAsset,
} from "./release_gate_shared.mjs";

function makeOption(key, assetIds = []) {
  return {
    option_key: key,
    label_md: `${key}.`,
    asset_ids: assetIds,
    bbox_space: "option_crop",
    bbox_json: { x: 10, y: 10, w: 120, h: 48 },
  };
}

function assertBaseContract(sourceRefsJson, fixtureName) {
  const qvs = sourceRefsJson.question_visual_structure;
  expect(
    qvs.schema_version === "question_visual_structure.v1.1",
    `${fixtureName}:schema_version_mismatch`
  );
  expect(qvs.question_uid, `${fixtureName}:question_uid_missing`);
  expect(qvs.runtime_run_id, `${fixtureName}:runtime_run_id_missing`);
  for (const asset of qvs.visual_assets || []) {
    expect(
      asset.display_ref === `asset://${asset.asset_id}`,
      `${fixtureName}:display_ref_noncanonical:${asset.asset_id}`
    );
  }
}

export function registerTests(register) {
  register({
    id: "RG-QVS-01",
    suite: "release_gate_qvs",
    title: "question_visual_structure v1.1 fixture matrix covers happy paths, degradations, and hard failures",
    required: true,
    async run() {
      const fourOptionAssets = ["A", "B", "C", "D"].map((key) =>
        buildVisualAsset({
          optionKey: key,
          assetId: `qa_release_gate_fixture_${key}_001`,
        })
      );
      const fixtures = [
        {
          name: "fixture_01_no_visual_assets",
          sourceRefsJson: buildLegacySourceRefs(
            buildQuestionVisualStructure({
              question_uid: "fixture_01_no_visual_assets",
              visual_assets: [],
              options: ["A", "B", "C", "D"].map((key) => makeOption(key)),
              content_blocks: [
                {
                  block_id: "blk_stem_1",
                  block_order: 1,
                  scope: "stem",
                  block_type: "markdown",
                  text_md: "Choose the correct answer.",
                },
              ],
              legacy_stem_md: "Choose the correct answer.",
            })
          ),
          expectOk: true,
        },
        {
          name: "fixture_02_public_stem_image",
          sourceRefsJson: buildLegacySourceRefs(
            buildQuestionVisualStructure({
              question_uid: "fixture_02_public_stem_image",
              visual_assets: [
                buildVisualAsset({
                  questionUid: "fixture_02_public_stem_image",
                  placementScope: "after_stem",
                  assetRole: "stem",
                  optionKey: null,
                  assetId: "qa_fixture_02_stem_001",
                }),
              ],
              options: ["A", "B", "C", "D"].map((key) => makeOption(key)),
              content_blocks: [
                {
                  block_id: "blk_stem_1",
                  block_order: 1,
                  scope: "stem",
                  block_type: "markdown",
                  text_md: "Observe the image.",
                },
                {
                  block_id: "blk_stem_2",
                  block_order: 2,
                  scope: "stem",
                  block_type: "image",
                  asset_id: "qa_fixture_02_stem_001",
                  display_ref: "asset://qa_fixture_02_stem_001",
                },
              ],
              legacy_stem_md:
                "Observe the image.\n\n![qa_fixture_02_stem_001](asset://qa_fixture_02_stem_001)",
            })
          ),
          expectOk: true,
        },
        {
          name: "fixture_03_four_option_images",
          sourceRefsJson: buildLegacySourceRefs(
            buildQuestionVisualStructure({
              question_uid: "fixture_03_four_option_images",
              visual_assets: fourOptionAssets,
              options: fourOptionAssets.map((asset) =>
                makeOption(asset.option_key, [asset.asset_id])
              ),
              content_blocks: fourOptionAssets.flatMap((asset, index) => [
                {
                  block_id: `blk_opt_${asset.option_key}_text`,
                  block_order: index * 2 + 1,
                  scope: "option",
                  option_key: asset.option_key,
                  block_type: "markdown",
                  text_md: `${asset.option_key}.`,
                },
                {
                  block_id: `blk_opt_${asset.option_key}_img`,
                  block_order: index * 2 + 2,
                  scope: "option",
                  option_key: asset.option_key,
                  block_type: "image",
                  asset_id: asset.asset_id,
                  display_ref: asset.display_ref,
                },
              ]),
              legacy_stem_md: fourOptionAssets
                .map((asset) => `${asset.option_key}. ![${asset.asset_id}](${asset.display_ref})`)
                .join("\n\n"),
            })
          ),
          expectOk: true,
        },
        {
          name: "fixture_04_two_column_option_images",
          sourceRefsJson: buildLegacySourceRefs(
            buildQuestionVisualStructure({
              question_uid: "fixture_04_two_column_option_images",
              visual_assets: fourOptionAssets.map((asset) => ({
                ...asset,
                asset_id: `${asset.asset_id}_two_column`,
                display_ref: `asset://${asset.asset_id}_two_column`,
              })),
              options: fourOptionAssets.map((asset) =>
                makeOption(asset.option_key, [`${asset.asset_id}_two_column`])
              ),
              legacy_stem_md: fourOptionAssets
                .map((asset) => `${asset.option_key}. ![${asset.asset_id}_two_column](asset://${asset.asset_id}_two_column)`)
                .join("\n\n"),
            })
          ),
          expectOk: true,
        },
        {
          name: "fixture_05_sparse_option_images",
          sourceRefsJson: buildLegacySourceRefs(
            buildQuestionVisualStructure({
              question_uid: "fixture_05_sparse_option_images",
              visual_assets: [
                buildVisualAsset({ questionUid: "fixture_05_sparse_option_images", optionKey: "A" }),
                buildVisualAsset({ questionUid: "fixture_05_sparse_option_images", optionKey: "C", assetId: "qa_fixture_05_C_001" }),
              ],
              options: [
                makeOption("A", ["qa_fixture_05_sparse_option_images_option_A_001"]),
                makeOption("B"),
                makeOption("C", ["qa_fixture_05_C_001"]),
                makeOption("D"),
              ],
              legacy_stem_md:
                "A. ![qa_fixture_05_sparse_option_images_option_A_001](asset://qa_fixture_05_sparse_option_images_option_A_001)\n\nC. ![qa_fixture_05_C_001](asset://qa_fixture_05_C_001)",
            })
          ),
          expectOk: true,
        },
        {
          name: "fixture_06_text_below_image",
          sourceRefsJson: buildLegacySourceRefs(
            buildQuestionVisualStructure({
              question_uid: "fixture_06_text_below_image",
              content_blocks: [
                {
                  block_id: "blk_opt_A_img",
                  block_order: 1,
                  scope: "option",
                  option_key: "A",
                  block_type: "image",
                  asset_id: "qa_fixture_06_A_001",
                  display_ref: "asset://qa_fixture_06_A_001",
                },
                {
                  block_id: "blk_opt_A_text",
                  block_order: 2,
                  scope: "option",
                  option_key: "A",
                  block_type: "markdown",
                  text_md: "A.",
                },
              ],
              visual_assets: [
                buildVisualAsset({
                  questionUid: "fixture_06_text_below_image",
                  optionKey: "A",
                  assetId: "qa_fixture_06_A_001",
                }),
              ],
              options: [makeOption("A", ["qa_fixture_06_A_001"])],
              legacy_stem_md:
                "![qa_fixture_06_A_001](asset://qa_fixture_06_A_001)\n\nA.",
            })
          ),
          expectOk: true,
        },
        {
          name: "fixture_07_analysis_image",
          sourceRefsJson: buildLegacySourceRefs(
            buildQuestionVisualStructure({
              question_uid: "fixture_07_analysis_image",
              visual_assets: [
                buildVisualAsset({
                  questionUid: "fixture_07_analysis_image",
                  placementScope: "after_analysis",
                  assetRole: "analysis",
                  optionKey: null,
                  assetId: "qa_fixture_07_analysis_001",
                }),
              ],
              options: ["A", "B", "C", "D"].map((key) => makeOption(key)),
              content_blocks: [
                {
                  block_id: "blk_analysis_text",
                  block_order: 1,
                  scope: "analysis",
                  block_type: "markdown",
                  text_md: "See the analysis figure.",
                },
                {
                  block_id: "blk_analysis_image",
                  block_order: 2,
                  scope: "analysis",
                  block_type: "image",
                  asset_id: "qa_fixture_07_analysis_001",
                  display_ref: "asset://qa_fixture_07_analysis_001",
                },
              ],
              legacy_stem_md: "Choose the correct answer.",
            })
          ),
          expectOk: true,
        },
        {
          name: "fixture_08_evidence_only_unassigned",
          sourceRefsJson: buildLegacySourceRefs(
            buildQuestionVisualStructure({
              question_uid: "fixture_08_evidence_only_unassigned",
              visual_assets: [
                buildVisualAsset({
                  questionUid: "fixture_08_evidence_only_unassigned",
                  placementScope: "evidence_only",
                  assetRole: "evidence",
                  optionKey: null,
                  assetId: "qa_fixture_08_evidence_001",
                  attachStatus: "not_attached_unassigned",
                  reviewFlags: ["option_asset_unassigned"],
                }),
              ],
              options: ["A", "B", "C", "D"].map((key) => makeOption(key)),
              legacy_stem_md: "Choose the correct answer.",
              review_flags: ["option_asset_unassigned"],
            })
          ),
          expectOk: true,
        },
        {
          name: "fixture_09_stem_and_option_images",
          sourceRefsJson: buildLegacySourceRefs(
            buildQuestionVisualStructure({
              question_uid: "fixture_09_stem_and_option_images",
              visual_assets: [
                buildVisualAsset({
                  questionUid: "fixture_09_stem_and_option_images",
                  placementScope: "after_stem",
                  assetRole: "stem",
                  optionKey: null,
                  assetId: "qa_fixture_09_stem_001",
                }),
                buildVisualAsset({
                  questionUid: "fixture_09_stem_and_option_images",
                  optionKey: "A",
                  assetId: "qa_fixture_09_option_A_001",
                }),
              ],
              options: [makeOption("A", ["qa_fixture_09_option_A_001"])],
              legacy_stem_md:
                "Observe the public image.\n\n![qa_fixture_09_stem_001](asset://qa_fixture_09_stem_001)\n\nA. ![qa_fixture_09_option_A_001](asset://qa_fixture_09_option_A_001)",
            })
          ),
          expectOk: true,
        },
        {
          name: "fixture_10_cross_option_image",
          sourceRefsJson: buildLegacySourceRefs(
            buildQuestionVisualStructure({
              question_uid: "fixture_10_cross_option_image",
              visual_assets: [
                buildVisualAsset({
                  questionUid: "fixture_10_cross_option_image",
                  placementScope: "evidence_only",
                  assetRole: "evidence",
                  optionKey: null,
                  assetId: "qa_fixture_10_cross_001",
                  attachStatus: "not_attached_unassigned",
                  reviewFlags: ["cross_option_image_detected"],
                }),
              ],
              options: ["A", "B", "C", "D"].map((key) => makeOption(key)),
              review_flags: ["cross_option_image_detected"],
              legacy_stem_md: "Choose the correct answer.",
            })
          ),
          expectOk: true,
        },
        {
          name: "fixture_11_bbox_missing",
          sourceRefsJson: buildLegacySourceRefs(
            buildQuestionVisualStructure({
              question_uid: "fixture_11_bbox_missing",
              visual_assets: [
                buildVisualAsset({
                  questionUid: "fixture_11_bbox_missing",
                  optionKey: "A",
                  assetId: "qa_fixture_11_A_001",
                  bboxSpace: "",
                }),
              ],
              options: [makeOption("A", ["qa_fixture_11_A_001"])],
              legacy_stem_md:
                "A. ![qa_fixture_11_A_001](asset://qa_fixture_11_A_001)",
            })
          ),
          expectOk: false,
          expectedError: "bbox_space_missing:qa_fixture_11_A_001",
        },
        {
          name: "fixture_12_source_image_missing",
          sourceRefsJson: buildLegacySourceRefs(
            buildQuestionVisualStructure({
              question_uid: "fixture_12_source_image_missing",
              visual_assets: [
                buildVisualAsset({
                  questionUid: "fixture_12_source_image_missing",
                  optionKey: "A",
                  assetId: "qa_fixture_12_A_001",
                  sourceImageAssetId: "",
                  sourceImageStorageKey: "",
                }),
              ],
              options: [makeOption("A", ["qa_fixture_12_A_001"])],
              legacy_stem_md:
                "A. ![qa_fixture_12_A_001](asset://qa_fixture_12_A_001)",
            })
          ),
          expectOk: false,
          expectedError: "source_image_ref_missing:qa_fixture_12_A_001",
        },
        {
          name: "fixture_13_asset_materialize_failed",
          sourceRefsJson: buildLegacySourceRefs(
            buildQuestionVisualStructure({
              question_uid: "fixture_13_asset_materialize_failed",
              visual_assets: [
                buildVisualAsset({
                  questionUid: "fixture_13_asset_materialize_failed",
                  optionKey: "A",
                  assetId: "qa_fixture_13_A_001",
                  fileStatus: "failed",
                  reviewFlags: ["asset_materialize_failed"],
                }),
              ],
              options: [makeOption("A", ["qa_fixture_13_A_001"])],
              legacy_stem_md:
                "A. ![qa_fixture_13_A_001](asset://qa_fixture_13_A_001)",
            })
          ),
          expectOk: false,
          expectedError: "asset_not_materialized:asset://qa_fixture_13_A_001",
        },
        {
          name: "fixture_14_absolute_storage_key",
          sourceRefsJson: buildLegacySourceRefs(
            buildQuestionVisualStructure({
              question_uid: "fixture_14_absolute_storage_key",
              visual_assets: [
                buildVisualAsset({
                  questionUid: "fixture_14_absolute_storage_key",
                  optionKey: "A",
                  assetId: "qa_fixture_14_A_001",
                  storageKey: "C:/absolute/path/not_allowed.png",
                }),
              ],
              options: [makeOption("A", ["qa_fixture_14_A_001"])],
              legacy_stem_md:
                "A. ![qa_fixture_14_A_001](asset://qa_fixture_14_A_001)",
            })
          ),
          expectOk: false,
          expectedError: "asset_storage_key_not_relative:qa_fixture_14_A_001",
        },
      ];

      const results = [];
      for (const fixture of fixtures) {
        assertBaseContract(fixture.sourceRefsJson, fixture.name);
        const validation = validateQuestionVisualSourceRefs(fixture.sourceRefsJson);
        expect(
          validation.ok === fixture.expectOk,
          `${fixture.name}:validation_mismatch:${JSON.stringify(validation)}`
        );
        if (fixture.expectedError) {
          expect(
            validation.errors.includes(fixture.expectedError),
            `${fixture.name}:expected_error_missing:${JSON.stringify(validation.errors)}`
          );
        }
        results.push({
          name: fixture.name,
          ok: validation.ok,
          errorCount: validation.errors.length,
        });
      }
      return {
        fixtures: results,
      };
    },
  });

  register({
    id: "RG-QVS-02",
    suite: "release_gate_qvs",
    title: "Reruns keep stable asset:// ids while generating versioned storage_key paths",
    required: true,
    async run() {
      const oldAsset = buildVisualAsset({
        questionUid: "fixture_15_rerun",
        runtimeRunId: "run_old",
        optionKey: "A",
        assetId: "qa_fixture_15_A_001",
      });
      const newAsset = buildVisualAsset({
        questionUid: "fixture_15_rerun",
        runtimeRunId: "run_new",
        optionKey: "A",
        assetId: "qa_fixture_15_A_001",
      });
      const oldRefs = buildLegacySourceRefs(
        buildQuestionVisualStructure({
          question_uid: "fixture_15_rerun",
          runtime_run_id: "run_old",
          visual_assets: [oldAsset],
          options: [makeOption("A", [oldAsset.asset_id])],
          legacy_stem_md: `A. ![${oldAsset.asset_id}](${oldAsset.display_ref})`,
        })
      );
      const newRefs = buildLegacySourceRefs(
        buildQuestionVisualStructure({
          question_uid: "fixture_15_rerun",
          runtime_run_id: "run_new",
          visual_assets: [newAsset],
          options: [makeOption("A", [newAsset.asset_id])],
          legacy_stem_md: `A. ![${newAsset.asset_id}](${newAsset.display_ref})`,
        })
      );
      const oldValidation = validateQuestionVisualSourceRefs(oldRefs);
      const newValidation = validateQuestionVisualSourceRefs(newRefs);
      expect(oldValidation.ok, `fixture_15_old_invalid:${JSON.stringify(oldValidation)}`);
      expect(newValidation.ok, `fixture_15_new_invalid:${JSON.stringify(newValidation)}`);
      expect(
        oldAsset.storage_key !== newAsset.storage_key,
        "fixture_15_storage_key_should_change_on_rerun"
      );
      const oldResolved = resolveQuestionVisualAsset(
        oldRefs,
        oldAsset.display_ref
      );
      const newResolved = resolveQuestionVisualAsset(
        newRefs,
        newAsset.display_ref
      );
      expect(oldResolved.ok, "fixture_15_old_asset_should_resolve");
      expect(newResolved.ok, "fixture_15_new_asset_should_resolve");
      return {
        oldStorageKey: oldAsset.storage_key,
        newStorageKey: newAsset.storage_key,
      };
    },
  });
}
