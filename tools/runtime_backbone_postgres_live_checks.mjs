/**
 * Purpose:
 * - Runs live Postgres validation checks against the current runtime environment.
 * - Keep operator-facing diagnostics here so they can be reused outside the test harness.
 */

import {
  createHarness,
} from "../tests/helpers/runtime_testkit.mjs";

async function main() {
  const harness = await createHarness({ runId: "postgres_live_checks" });
  try {
    const server = await harness.startPostgresServer("live_check_test");
    const health = await server.request("/health");
    const consistency = await server.request("/api/runtime/internal/consistency");
    const payload = {
      ok: health.ok && consistency.ok && consistency.data.detail.ok,
      database: server.database.maskedConnectionString,
      postgresVersion: harness.postgresCluster?.version || null,
      runtimeMode: health.data?.runtimeMode || null,
      consistencyStatus: consistency.data?.detail?.status || null,
      migrationVersion: health.data?.storeHealth?.migrationVersion || null,
    };
    process.stdout.write(`${JSON.stringify(payload, null, 2)}\n`);
    process.exitCode = payload.ok ? 0 : 1;
  } finally {
    await harness.dispose();
  }
}

await main();
