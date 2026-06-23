import { runProductionReadiness } from "./runtime_backbone_production_readiness.mjs";

const report = await runProductionReadiness({
  runId: "backup_restore_checks",
  suites: new Set(["backup_restore"]),
});

process.exitCode = report.summary.failed > 0 ? 1 : 0;
