/**
 * Purpose:
 * - validate DOCX-native backend-aligned previews against the existing
 *   visual Runtime adapter contract.
 * - write an inspectable LessonDraftBundle preview without importing Runtime/DB.
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  adaptQuestionAssetManifestToLessonDraftBundle,
  validateQuestionVisualSourceRefs,
} from "./runtime_visual_split_adapter.mjs";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const workspaceRoot = path.resolve(__dirname, "..");

function parseArgs(argv = process.argv.slice(2)) {
  const args = {};
  for (let index = 0; index < argv.length; index += 1) {
    const item = argv[index];
    if (!item.startsWith("--")) {
      continue;
    }
    const key = item.slice(2);
    const value = argv[index + 1]?.startsWith("--") ? true : argv[index + 1];
    args[key] = value === undefined ? true : value;
    if (value !== true) {
      index += 1;
    }
  }
  return args;
}

function requiredPath(value, label) {
  if (!value || value === true) {
    throw new Error(`missing_${label}`);
  }
  return path.resolve(String(value));
}

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function writeJson(filePath, payload) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, JSON.stringify(payload, null, 2));
}

function isStorageFilePresent(storageKey) {
  const value = String(storageKey || "").trim();
  if (!value) {
    return false;
  }
  if (path.win32.isAbsolute(value) || path.posix.isAbsolute(value)) {
    return fs.existsSync(value);
  }
  return fs.existsSync(path.join(workspaceRoot, value.replace(/\\/g, "/")));
}

function inspectTask(task) {
  const sourceRefs = task.source_refs_json || {};
  const validation = validateQuestionVisualSourceRefs(sourceRefs);
  const qvs = sourceRefs.question_visual_structure || {};
  const visualAssets = Array.isArray(qvs.visual_assets) ? qvs.visual_assets : [];
  const contentBlocks = Array.isArray(qvs.content_blocks) ? qvs.content_blocks : [];
  const conditionBlocks = contentBlocks.filter(
    (block) => String(block?.block_type || "") === "condition_group"
  );
  const missingStorageKeys = [];
  const absoluteStorageKeys = [];
  for (const asset of visualAssets) {
    const storageKey = String(asset?.storage_key || "").trim();
    if (path.win32.isAbsolute(storageKey) || path.posix.isAbsolute(storageKey)) {
      absoluteStorageKeys.push({
        asset_id: asset?.asset_id || "",
        storage_key: storageKey,
      });
    }
    if (!isStorageFilePresent(storageKey)) {
      missingStorageKeys.push({
        asset_id: asset?.asset_id || "",
        storage_key: storageKey,
      });
    }
  }
  const errors = [...(validation.errors || [])];
  if (!task.local_task_id) errors.push("task_local_task_id_missing");
  if (!task.stem) errors.push("task_stem_missing");
  if (!sourceRefs.question_visual_structure) errors.push("task_qvs_missing");
  for (const item of missingStorageKeys) {
    errors.push(`storage_file_missing:${item.asset_id || "unknown"}`);
  }
  for (const item of absoluteStorageKeys) {
    errors.push(`storage_key_absolute:${item.asset_id || "unknown"}`);
  }
  return {
    local_task_id: task.local_task_id || "",
    question_uid: qvs.question_uid || task.question_uid || "",
    ok: errors.length === 0,
    errors: [...new Set(errors)],
    warnings: [...new Set(validation.warnings || [])],
    visual_asset_count: visualAssets.length,
    content_block_count: contentBlocks.length,
    condition_group_block_count: conditionBlocks.length,
    missing_storage_key_count: missingStorageKeys.length,
    absolute_storage_key_count: absoluteStorageKeys.length,
  };
}

export function runDocxNativeBackendContractCheck(options = {}) {
  const manifestPath = requiredPath(options.manifest, "manifest");
  const outPath = requiredPath(options.out, "out");
  const bundleOut = options["bundle-out"] ? path.resolve(String(options["bundle-out"])) : null;
  const manifest = readJson(manifestPath);
  const bundle = adaptQuestionAssetManifestToLessonDraftBundle(manifest, {
    bundle_id: options["bundle-id"] || options.bundleId || "docx_native_backend_aligned_bundle",
    lesson_id: options["lesson-id"] || options.lessonId || "docx_native_backend_aligned_lesson",
    title: options.title || "DOCX Native Backend Aligned Lesson",
    subject: options.subject || "math",
    stage: options.stage || "junior",
    track_code: options["track-code"] || options.trackCode || "math_junior",
    grade: options.grade || "g8",
    season: options.season || "summer",
    source_tree: [
      {
        source_node_local_id: "root",
        node_type: "lesson",
        phase: "knowledge_main",
        title: options.title || "DOCX Native Backend Aligned Lesson",
      },
    ],
    runtime_run_id: options["runtime-run-id"] || options.runtimeRunId || path.basename(path.dirname(manifestPath)),
  });
  const rows = bundle.tasks.map((task) => inspectTask(task));
  const errorRows = rows.filter((row) => !row.ok);
  const report = {
    schema_version: "docx_native_backend_contract_check.v0.1",
    status: errorRows.length ? "fail" : "ok",
    note: "contract check only; no Runtime import and no database write",
    manifest_path: manifestPath,
    bundle_out: bundleOut,
    task_count: bundle.tasks.length,
    failed_task_count: errorRows.length,
    visual_asset_count: rows.reduce((sum, row) => sum + row.visual_asset_count, 0),
    content_block_count: rows.reduce((sum, row) => sum + row.content_block_count, 0),
    condition_group_block_count: rows.reduce((sum, row) => sum + row.condition_group_block_count, 0),
    missing_storage_key_count: rows.reduce((sum, row) => sum + row.missing_storage_key_count, 0),
    absolute_storage_key_count: rows.reduce((sum, row) => sum + row.absolute_storage_key_count, 0),
    runtime_imported: false,
    database_written: false,
    rows,
  };
  writeJson(outPath, report);
  if (bundleOut) {
    writeJson(bundleOut, {
      note: "adapter bundle preview only; not imported into runtime/db",
      manifest_path: manifestPath,
      bundle,
    });
  }
  return report;
}

if (process.argv[1] && path.resolve(process.argv[1]) === __filename) {
  try {
    console.log(JSON.stringify(runDocxNativeBackendContractCheck(parseArgs()), null, 2));
  } catch (error) {
    console.error(error?.stack || String(error));
    process.exitCode = 1;
  }
}
