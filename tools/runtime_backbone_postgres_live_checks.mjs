/**
 * 用途：
 * - 针对当前运行时环境执行在线 Postgres 校验检查。
 * - 面向操作者的诊断集中在这里，便于脱离测试框架复用。
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
