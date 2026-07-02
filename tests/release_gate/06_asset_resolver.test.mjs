import {
  expect,
} from "../helpers/runtime_testkit.mjs";
import { resolveQuestionVisualAsset } from "../../tools/runtime_visual_split_adapter.mjs";
import {
  buildLegacySourceRefs,
  buildQuestionVisualStructure,
  buildVisualAsset,
} from "./release_gate_shared.mjs";

export function registerTests(register) {
  register({
    id: "RG-ASSET-01",
    suite: "release_gate_asset_resolver",
    title: "asset:// resolver enforces attached materialized relative assets and rejects duplicate or cross-question lookups",
    required: true,
    async run() {
      const goodAsset = buildVisualAsset({
        questionUid: "resolver_good",
        optionKey: "A",
        assetId: "qa_resolver_good_A_001",
      });
      const goodRefs = buildLegacySourceRefs(
        buildQuestionVisualStructure({
          question_uid: "resolver_good",
          visual_assets: [goodAsset],
          options: [
            {
              option_key: "A",
              asset_ids: [goodAsset.asset_id],
              bbox_space: "option_crop",
            },
          ],
          legacy_stem_md: `A. ![${goodAsset.asset_id}](${goodAsset.display_ref})`,
        })
      );

      const positive = resolveQuestionVisualAsset(goodRefs, goodAsset.display_ref);
      expect(positive.ok, `resolver_positive_failed:${JSON.stringify(positive)}`);

      const missing = resolveQuestionVisualAsset(
        goodRefs,
        "asset://does_not_exist"
      );
      expect(
        missing.error === "asset_id_not_found",
        `resolver_missing_should_be_clear:${JSON.stringify(missing)}`
      );

      const missingStorageRefs = buildLegacySourceRefs(
        buildQuestionVisualStructure({
          question_uid: "resolver_missing_storage",
          visual_assets: [
            buildVisualAsset({
              questionUid: "resolver_missing_storage",
              assetId: "qa_resolver_missing_storage_001",
              storageKey: "",
            }),
          ],
          options: [
            {
              option_key: "A",
              asset_ids: ["qa_resolver_missing_storage_001"],
              bbox_space: "option_crop",
            },
          ],
          legacy_stem_md:
            "A. ![qa_resolver_missing_storage_001](asset://qa_resolver_missing_storage_001)",
        })
      );
      const missingStorage = resolveQuestionVisualAsset(
        missingStorageRefs,
        "asset://qa_resolver_missing_storage_001"
      );
      expect(
        missingStorage.error === "asset_storage_key_not_relative",
        `resolver_missing_storage_should_fail:${JSON.stringify(missingStorage)}`
      );

      const absolutePath = resolveQuestionVisualAsset(
        buildLegacySourceRefs(
          buildQuestionVisualStructure({
            question_uid: "resolver_absolute_path",
            visual_assets: [
              buildVisualAsset({
                questionUid: "resolver_absolute_path",
                assetId: "qa_resolver_absolute_path_001",
                storageKey: "C:/private/path/image.png",
              }),
            ],
            options: [
              {
                option_key: "A",
                asset_ids: ["qa_resolver_absolute_path_001"],
                bbox_space: "option_crop",
              },
            ],
            legacy_stem_md:
              "A. ![qa_resolver_absolute_path_001](asset://qa_resolver_absolute_path_001)",
          })
        ),
        "asset://qa_resolver_absolute_path_001"
      );
      expect(
        absolutePath.error === "asset_storage_key_not_relative",
        `resolver_absolute_path_should_fail:${JSON.stringify(absolutePath)}`
      );

      const traversal = resolveQuestionVisualAsset(
        buildLegacySourceRefs(
          buildQuestionVisualStructure({
            question_uid: "resolver_traversal",
            visual_assets: [
              buildVisualAsset({
                questionUid: "resolver_traversal",
                assetId: "qa_resolver_traversal_001",
                storageKey: "../../secret.png",
              }),
            ],
            options: [
              {
                option_key: "A",
                asset_ids: ["qa_resolver_traversal_001"],
                bbox_space: "option_crop",
              },
            ],
            legacy_stem_md:
              "A. ![qa_resolver_traversal_001](asset://qa_resolver_traversal_001)",
          })
        ),
        "asset://qa_resolver_traversal_001"
      );
      expect(
        traversal.error === "asset_storage_key_not_relative",
        `resolver_traversal_should_fail:${JSON.stringify(traversal)}`
      );

      const notMaterialized = resolveQuestionVisualAsset(
        buildLegacySourceRefs(
          buildQuestionVisualStructure({
            question_uid: "resolver_not_materialized",
            visual_assets: [
              buildVisualAsset({
                questionUid: "resolver_not_materialized",
                assetId: "qa_resolver_not_materialized_001",
                fileStatus: "failed",
              }),
            ],
            options: [
              {
                option_key: "A",
                asset_ids: ["qa_resolver_not_materialized_001"],
                bbox_space: "option_crop",
              },
            ],
            legacy_stem_md:
              "A. ![qa_resolver_not_materialized_001](asset://qa_resolver_not_materialized_001)",
          })
        ),
        "asset://qa_resolver_not_materialized_001"
      );
      expect(
        notMaterialized.error === "asset_not_materialized",
        `resolver_not_materialized_should_fail:${JSON.stringify(notMaterialized)}`
      );

      const notAttached = resolveQuestionVisualAsset(
        buildLegacySourceRefs(
          buildQuestionVisualStructure({
            question_uid: "resolver_not_attached",
            visual_assets: [
              buildVisualAsset({
                questionUid: "resolver_not_attached",
                assetId: "qa_resolver_not_attached_001",
                attachStatus: "not_attached_unassigned",
              }),
            ],
            options: [
              {
                option_key: "A",
                asset_ids: ["qa_resolver_not_attached_001"],
                bbox_space: "option_crop",
              },
            ],
            legacy_stem_md:
              "A. ![qa_resolver_not_attached_001](asset://qa_resolver_not_attached_001)",
          })
        ),
        "asset://qa_resolver_not_attached_001"
      );
      expect(
        notAttached.error === "asset_not_attached",
        `resolver_not_attached_should_fail:${JSON.stringify(notAttached)}`
      );

      const evidenceOnlyRefs = buildLegacySourceRefs(
        buildQuestionVisualStructure({
          question_uid: "resolver_evidence_only",
          visual_assets: [
            buildVisualAsset({
              questionUid: "resolver_evidence_only",
              assetId: "qa_resolver_evidence_only_001",
              placementScope: "evidence_only",
              assetRole: "evidence",
              optionKey: null,
              attachStatus: "not_attached_unassigned",
            }),
          ],
          options: [],
          legacy_stem_md: "No inline asset should appear here.",
        })
      );
      const formalEvidenceLookup = resolveQuestionVisualAsset(
        evidenceOnlyRefs,
        "asset://qa_resolver_evidence_only_001",
        {
          requireAttached: false,
          requireMaterialized: false,
        }
      );
      expect(
        formalEvidenceLookup.error === "asset_evidence_only",
        `resolver_evidence_only_should_not_enter_formal_export:${JSON.stringify(formalEvidenceLookup)}`
      );
      const htmlEvidenceLookup = resolveQuestionVisualAsset(
        evidenceOnlyRefs,
        "asset://qa_resolver_evidence_only_001",
        {
          requireAttached: false,
          requireMaterialized: false,
          allowEvidenceOnly: true,
        }
      );
      expect(htmlEvidenceLookup.ok, "resolver_html_should_allow_evidence_only");

      const duplicate = resolveQuestionVisualAsset(
        buildLegacySourceRefs(
          buildQuestionVisualStructure({
            question_uid: "resolver_duplicate",
            visual_assets: [
              buildVisualAsset({
                questionUid: "resolver_duplicate",
                assetId: "qa_resolver_duplicate_001",
              }),
              buildVisualAsset({
                questionUid: "resolver_duplicate",
                assetId: "qa_resolver_duplicate_001",
                storageKey:
                  "question_assets/resolver_duplicate/run_release_gate_visual_001/options/A/002.png",
              }),
            ],
            options: [
              {
                option_key: "A",
                asset_ids: ["qa_resolver_duplicate_001"],
                bbox_space: "option_crop",
              },
            ],
            legacy_stem_md:
              "A. ![qa_resolver_duplicate_001](asset://qa_resolver_duplicate_001)",
          })
        ),
        "asset://qa_resolver_duplicate_001"
      );
      expect(
        duplicate.error === "duplicate_asset_id",
        `resolver_duplicate_should_fail:${JSON.stringify(duplicate)}`
      );

      const otherQuestionRefs = buildLegacySourceRefs(
        buildQuestionVisualStructure({
          question_uid: "resolver_other_question",
          visual_assets: [],
          options: [],
          legacy_stem_md: "Other question without this asset.",
        })
      );
      const crossQuestion = resolveQuestionVisualAsset(
        otherQuestionRefs,
        goodAsset.display_ref
      );
      expect(
        crossQuestion.error === "asset_id_not_found",
        `resolver_cross_question_should_not_leak:${JSON.stringify(crossQuestion)}`
      );

      return {
        positiveStorageKey: positive.asset.storage_key,
        htmlEvidenceStorageKey: htmlEvidenceLookup.asset.storage_key,
      };
    },
  });
}
