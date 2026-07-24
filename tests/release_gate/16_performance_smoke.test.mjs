import {
  expect,
  readJsonFixture,
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

function percentile(values, ratio) {
  if (!values.length) {
    return 0;
  }
  const sorted = [...values].sort((left, right) => left - right);
  const index = Math.min(
    sorted.length - 1,
    Math.ceil(sorted.length * ratio) - 1
  );
  return sorted[index];
}

async function collectLatencies(count, action) {
  const latencies = [];
  let errors = 0;
  for (let index = 0; index < count; index += 1) {
    const startedAt = performance.now();
    try {
      const result = await action(index);
      if (result?.ok === false) {
        errors += 1;
      }
    } catch {
      errors += 1;
    }
    latencies.push(performance.now() - startedAt);
  }
  return {
    count,
    errors,
    p50: Number(percentile(latencies, 0.5).toFixed(2)),
    p95: Number(percentile(latencies, 0.95).toFixed(2)),
  };
}

export function registerTests(register) {
  register({
    id: "RG-PERF-01",
    suite: "release_gate_performance",
    title: "Release gate smoke keeps search and visual validation responsive on a moderate multi-track seed set",
    required: false,
    async run({ harness }) {
      const bundles = [
        await readJsonFixture("three_track", "math_junior_bundle.json"),
        await readJsonFixture("three_track", "math_senior_bundle.json"),
        await readJsonFixture("three_track", "english_senior_bundle.json"),
      ];
      const server = await harness.startPostgresServer({
        prefix: "release_gate_performance_test",
        env: {
          // This suite measures steady-state query responsiveness after seeding;
          // rate limiting is covered separately in the security gate.
          RUNTIME_RATE_LIMIT_MAX_REQUESTS: "64",
        },
      });

      for (let round = 0; round < 3; round += 1) {
        for (const bundle of bundles) {
          // Keep the seed actors unique per lesson so this smoke suite measures
          // read/query responsiveness instead of tripping the dedicated rate-limit gate.
          const actorPrefix = `release_gate_perf_${round}_${bundle.track_code}`;
          const imported = await server.request(
            "/api/runtime/imports/lesson-draft-bundles",
            {
              method: "POST",
              body: {
                actor: actorPrefix,
                bundle: {
                  ...bundle,
                  bundle_id: `${bundle.bundle_id}_perf_${round}`,
                  lesson_id: `${bundle.lesson_id}_perf_${round}`,
                },
              },
            }
          );
          expect(imported.ok, `release_gate_perf_import_failed:${JSON.stringify(imported.data)}`);
          const approved = await server.request(
            `/api/runtime/review-tasks/${imported.data.result.reviewTaskId}/approve`,
            {
              method: "POST",
              body: {
                actor: `${actorPrefix}_reviewer`,
              },
            }
          );
          expect(approved.ok, `release_gate_perf_approve_failed:${JSON.stringify(approved.data)}`);
          const published = await server.request(
            `/api/runtime/lessons/${bundle.lesson_id}_perf_${round}/publish`,
            {
              method: "POST",
              body: {
                actor: `${actorPrefix}_publisher`,
                lessonRevisionId: imported.data.result.lessonRevisionId,
              },
            }
          );
          expect(published.ok, `release_gate_perf_publish_failed:${JSON.stringify(published.data)}`);
        }
      }

      const sampleQvs = buildQuestionVisualStructure({
        question_uid: "release_gate_perf_q1",
        visual_assets: [
          buildVisualAsset({
            questionUid: "release_gate_perf_q1",
            optionKey: "A",
            assetId: "qa_release_gate_perf_q1_A_001",
          }),
        ],
        options: [
          {
            option_key: "A",
            asset_ids: ["qa_release_gate_perf_q1_A_001"],
            bbox_space: "option_crop",
          },
        ],
        legacy_stem_md:
          "A. ![qa_release_gate_perf_q1_A_001](asset://qa_release_gate_perf_q1_A_001)",
      });
      const sampleRefs = buildLegacySourceRefs(sampleQvs);

      const search = await collectLatencies(20, () =>
        server.request(
          `/api/runtime/task-projections/search?publishedOnly=true&subject=${encodeURIComponent(
            "数学"
          )}&q=${encodeURIComponent("函数")}`
        )
      );
      const difficulty = await collectLatencies(20, () =>
        server.request(
          `/api/runtime/task-projections/search?publishedOnly=true&subject=${encodeURIComponent(
            "英语"
          )}&difficultyLevel=3`
        )
      );
      const resolver = await collectLatencies(200, () => {
        const result = resolveQuestionVisualAsset(
          sampleRefs,
          "asset://qa_release_gate_perf_q1_A_001"
        );
        if (!result.ok) {
          throw new Error(result.error);
        }
        return { ok: true };
      });
      const validator = await collectLatencies(200, () => {
        const result = validateQuestionVisualSourceRefs(sampleRefs);
        if (!result.ok) {
          throw new Error("release_gate_perf_validator_failed");
        }
        return { ok: true };
      });

      expect(search.errors === 0, `release_gate_perf_search_errors:${search.errors}`);
      expect(difficulty.errors === 0, `release_gate_perf_difficulty_errors:${difficulty.errors}`);
      expect(resolver.errors === 0, `release_gate_perf_resolver_errors:${resolver.errors}`);
      expect(validator.errors === 0, `release_gate_perf_validator_errors:${validator.errors}`);
      expect(search.p95 < 1500, `release_gate_perf_search_p95_too_high:${search.p95}`);
      expect(difficulty.p95 < 1500, `release_gate_perf_difficulty_p95_too_high:${difficulty.p95}`);
      expect(resolver.p95 < 80, `release_gate_perf_resolver_p95_too_high:${resolver.p95}`);
      expect(validator.p95 < 80, `release_gate_perf_validator_p95_too_high:${validator.p95}`);

      return {
        seededLessons: 9,
        search,
        difficulty,
        resolver,
        validator,
      };
    },
  });
}
