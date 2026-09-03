import fs from "node:fs/promises";
import path from "node:path";

import { workspaceRoot } from "../tests/helpers/runtime_testkit.mjs";

const reportDirectory = path.join(workspaceRoot, "docs", "reports");

async function readJson(name) {
  return JSON.parse(await fs.readFile(path.join(reportDirectory, name), "utf8"));
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const database = await readJson("java_foundation_database_inventory_20260831.json");
const prototype = await readJson("java_foundation_prototype_inventory_20260831.json");
const mapping = await readJson("java_foundation_legacy_mapping_20260831.json");
const environment = await readJson("java_foundation_environment_20260831.json");

const legacyTables = database.tables.map((table) => table.name).sort();
const mappedTables = mapping.legacyMappings.map((item) => item.legacyTable).sort();
const targetTables = mapping.targetTables.map((table) => table.name);

assert(database.summary.tableCount === 43, `expected_43_legacy_tables:${database.summary.tableCount}`);
assert(JSON.stringify(legacyTables) === JSON.stringify(mappedTables), "legacy_mapping_must_cover_every_table_exactly_once");
assert(new Set(targetTables).size === targetTables.length, "target_table_names_must_be_unique");
assert(targetTables.length === 42, `expected_42_candidate_target_tables:${targetTables.length}`);
assert(prototype.prototype.effectiveQuestionCount === 85, "prototype_question_inventory_changed");
assert(prototype.editor.model === "master-overrides-v1", "editor_model_contract_changed");
assert(prototype.questionContract.hasParentChildQuestions, "parent_child_question_contract_missing");
assert(prototype.questionContract.hasRevisionPins, "question_revision_pin_contract_missing");
assert(prototype.portability.absolutePathValueCount > 0, "expected_prototype_absolute_path_debt_not_detected");
assert(prototype.portability.absolutePathLocations.length === prototype.portability.absolutePathValueCount, "absolute_path_locations_must_be_recorded_without_values");
assert(mapping.strategy.dualWrite === false, "dual_write_must_remain_disabled");
assert(mapping.targetTables.every((table) => Number.isInteger(table.phase) && table.phase >= 1 && table.phase <= 4), "invalid_target_phase");
assert(environment.tools.java.version.startsWith("21."), "java_21_required");
assert(environment.tools.maven.effectiveJavaVersion.startsWith("17."), "maven_java_mismatch_must_be_resolved_before_build");
assert(environment.portable === true, "environment_report_must_not_contain_machine_path_contracts");

process.stdout.write(`${JSON.stringify({
  ok: true,
  legacyTableCount: legacyTables.length,
  mappedLegacyTableCount: mappedTables.length,
  candidateTargetTableCount: targetTables.length,
  prototypeQuestionCount: prototype.prototype.effectiveQuestionCount,
  prototypeAbsolutePathDebtCount: prototype.portability.absolutePathValueCount,
  mavenEffectiveJavaVersion: environment.tools.maven.effectiveJavaVersion,
}, null, 2)}\n`);
