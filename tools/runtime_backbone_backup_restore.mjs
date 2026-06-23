/**
 * Purpose:
 * - Thin CLI wrapper that runs the backup and restore test suite.
 * - Keep wrappers like this minimal so the real test logic stays inside the shared test tree.
 */

import { runProductionReadiness } from "./runtime_backbone_production_readiness.mjs";

const report = await runProductionReadiness({
  runId: "backup_restore_checks",
  suites: new Set(["backup_restore"]),
});

process.exitCode = report.summary.failed > 0 ? 1 : 0;
