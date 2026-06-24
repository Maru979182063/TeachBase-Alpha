/**
 * 用途：
 * - 运行 soak 套件的轻量 CLI 包装器。
 * - 长时间 soak 调度在这里保持轻量，详细场景留在测试中。
 */

import { runProductionReadiness } from "./runtime_backbone_production_readiness.mjs";

const report = await runProductionReadiness({
  runId: "soak_checks",
  suites: new Set(["performance"]),
});

process.exitCode = report.summary.failed > 0 ? 1 : 0;
