/**
 * 用途：
 * - 运行备份与恢复测试套件的轻量 CLI 包装器。
 * - 这类包装器应保持最小化，让真正测试逻辑留在共享测试树中。
 */

import { runProductionReadiness } from "./runtime_backbone_production_readiness.mjs";

const report = await runProductionReadiness({
  runId: "backup_restore_checks",
  suites: new Set(["backup_restore"]),
});

process.exitCode = report.summary.failed > 0 ? 1 : 0;
