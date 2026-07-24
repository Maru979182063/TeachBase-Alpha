/**
 * 用途：
 * - 记录冒烟级性能和延迟预期。
 * - 把它当作早期预警，而不是完整基准测试框架。
 */

import {
  expect,
  readJsonFixture,
} from "../helpers/runtime_testkit.mjs";

function percentile(values, ratio) {
  if (!values.length) return 0;
  const sorted = [...values].sort((left, right) => left - right);
  const index = Math.min(sorted.length - 1, Math.ceil(sorted.length * ratio) - 1);
  return sorted[index];
}

async function collectLatencies(count, action) {
  const latencies = [];
  let errors = 0;
  for (let index = 0; index < count; index += 1) {
    const startedAt = performance.now();
    try {
      const response = await action();
      if (!response.ok) {
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
    p99: Number(percentile(latencies, 0.99).toFixed(2)),
  };
}

export function registerTests(register) {
  register({
    id: "PERF-SMOKE",
    suite: "performance",
    title: "Health and task search stay within smoke-load latency thresholds",
    required: true,
    async run({ harness }) {
      const bundle = await readJsonFixture("math", "minimal_bundle.json");
      const server = await harness.startPostgresServer("performance_smoke_test");
      const imported = await server.request("/api/runtime/imports/lesson-draft-bundles", {
        method: "POST",
        body: {
          actor: "performance_suite",
          bundle: {
            ...bundle,
            bundle_id: `${bundle.bundle_id}_perf`,
            lesson_id: `${bundle.lesson_id}_perf`,
          },
        },
      });
      expect(imported.ok, "performance_import_failed");
      await server.request(`/api/runtime/review-tasks/${imported.data.result.reviewTaskId}/approve`, {
        method: "POST",
        body: {
          actor: "performance_reviewer",
        },
      });
      await server.request(`/api/runtime/lessons/${bundle.lesson_id}_perf/publish`, {
        method: "POST",
        body: {
          actor: "performance_publisher",
          lessonRevisionId: imported.data.result.lessonRevisionId,
        },
      });

      const health = await collectLatencies(20, () => server.request("/health"));
      const search = await collectLatencies(
        20,
        () =>
          server.request(
            `/api/runtime/task-projections/search?subject=${encodeURIComponent("数学")}&publishedOnly=true&q=${encodeURIComponent("方程")}`
          )
      );

      expect(health.errors === 0, `health_smoke_errors:${health.errors}`);
      expect(search.errors === 0, `search_smoke_errors:${search.errors}`);
      expect(health.p95 < 200, `health_p95_too_high:${health.p95}`);
      expect(search.p95 < 800, `search_p95_too_high:${search.p95}`);
      return {
        health,
        search,
      };
    },
  });
}
