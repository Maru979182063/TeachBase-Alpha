/**
 * 用途：
 * - 运行故障注入检查的轻量 CLI 包装器。
 * - 包装器让调用更简单，具体场景仍留在共享测试中。
 */

import { runProductionReadiness } from "./runtime_backbone_production_readiness.mjs";

const report = await runProductionReadiness({
  runId: "failure_injection_checks",
  suites: new Set(["failure_injection"]),
});

process.exitCode = report.summary.failed > 0 ? 1 : 0;
