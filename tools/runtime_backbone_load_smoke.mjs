/**
 * 用途：
 * - 运行冒烟负载检查的轻量 CLI 包装器。
 * - 在更深入的 soak 或基准运行前，把它作为快速运行探针。
 */

import { runProductionReadiness } from "./runtime_backbone_production_readiness.mjs";

const report = await runProductionReadiness({
  runId: "load_smoke_checks",
  suites: new Set(["performance"]),
});

process.exitCode = report.summary.failed > 0 ? 1 : 0;
