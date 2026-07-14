/**
 * Purpose:
 * - dry-run DOCX native question asset manifests through the existing
 *   LessonDraftBundle adapter boundary.
 * - write an inspectable preview artifact without importing into Runtime/DB.
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { adaptQuestionAssetManifestToLessonDraftBundle } from "./runtime_visual_split_adapter.mjs";

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

export function runDocxNativeRuntimeAdapterDryRun(options = {}) {
  const manifestPath = requiredPath(options.manifest, "manifest");
  const outPath = requiredPath(options.out, "out");
  const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
  const bundle = adaptQuestionAssetManifestToLessonDraftBundle(manifest, {
    lesson_id: options["lesson-id"] || options.lessonId || "docx_native_preview_lesson",
    title: options.title || "DOCX Native Preview Lesson",
    subject: options.subject || "math",
    stage: options.stage || "junior",
    track_code: options["track-code"] || options.trackCode || "math_junior",
  });
  const payload = {
    note: "adapter dry-run only; not imported into runtime/db",
    manifest_path: manifestPath,
    task_count: bundle.tasks.length,
    review_flagged_task_count: bundle.tasks.filter(
      (task) => task.source_refs_json?.question_visual_structure?.review_flags?.length
    ).length,
    bundle,
  };
  fs.mkdirSync(path.dirname(outPath), { recursive: true });
  fs.writeFileSync(outPath, JSON.stringify(payload, null, 2));
  return {
    out: outPath,
    task_count: payload.task_count,
    review_flagged_task_count: payload.review_flagged_task_count,
  };
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    console.log(JSON.stringify(runDocxNativeRuntimeAdapterDryRun(parseArgs()), null, 2));
  } catch (error) {
    console.error(error?.stack || String(error));
    process.exitCode = 1;
  }
}
