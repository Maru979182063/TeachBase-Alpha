/**
 * Purpose:
 * - centralize the visual split contract that bridges question asset manifests,
 *   lesson draft bundles, and export preflight validation.
 * - keep the runtime on one schema path: source_refs_json.question_visual_structure.
 */

import path from "node:path";

export const QUESTION_VISUAL_STRUCTURE_SCHEMA = "question_visual_structure.v1.1";
const assetDisplayRefPattern = /asset:\/\/[A-Za-z0-9._:-]+/g;

function deepCloneJson(value) {
  return value === undefined ? undefined : JSON.parse(JSON.stringify(value));
}

function toPlainObject(value) {
  return value && typeof value === "object" && !Array.isArray(value)
    ? deepCloneJson(value)
    : {};
}

function normalizeStringArray(values) {
  const list = Array.isArray(values)
    ? values
    : values === undefined || values === null
      ? []
      : [values];
  return [...new Set(list.map((value) => String(value || "").trim()).filter(Boolean))];
}

function coalesceString(...values) {
  for (const value of values) {
    if (value === undefined || value === null) continue;
    const text = String(value);
    if (text.trim()) {
      return text;
    }
  }
  return "";
}

function isRelativeStorageKey(storageKey) {
  const value = String(storageKey || "").trim();
  if (!value) {
    return false;
  }
  if (/^[A-Za-z][A-Za-z0-9+.-]*:\/\//.test(value)) {
    return false;
  }
  if (value.startsWith("\\\\")) {
    return false;
  }
  if (path.posix.isAbsolute(value) || path.win32.isAbsolute(value)) {
    return false;
  }
  const normalized = value.replace(/\\/g, "/");
  return !normalized
    .split("/")
    .filter(Boolean)
    .some((segment) => segment === "." || segment === "..");
}

function normalizeVisualAsset(asset) {
  if (!asset || typeof asset !== "object" || Array.isArray(asset)) {
    return null;
  }
  const normalized = deepCloneJson(asset);
  normalized.asset_id = String(normalized.asset_id || "").trim();
  normalized.display_ref =
    String(normalized.display_ref || "").trim() ||
    (normalized.asset_id ? `asset://${normalized.asset_id}` : "");
  normalized.storage_key = String(normalized.storage_key || "").trim();
  normalized.attach_status = String(normalized.attach_status || "").trim() || "attached";
  normalized.file_status = String(normalized.file_status || "").trim() || "planned";
  normalized.placement_scope = String(normalized.placement_scope || normalized.placement || "").trim();
  normalized.review_flags = normalizeStringArray(normalized.review_flags);
  return normalized;
}

function collectDuplicateAssetIds(assets = []) {
  const counts = new Map();
  for (const asset of assets) {
    const assetId = String(asset?.asset_id || "").trim();
    if (!assetId) {
      continue;
    }
    counts.set(assetId, (counts.get(assetId) || 0) + 1);
  }
  return [...counts.entries()]
    .filter(([, count]) => count > 1)
    .map(([assetId]) => assetId);
}

function stripNonPortableFields(value) {
  const cloned = toPlainObject(value);
  delete cloned.crop_path;
  delete cloned.cropPath;
  delete cloned.absolute_path;
  delete cloned.absolutePath;
  return cloned;
}

export function normalizeQuestionVisualStructure(questionVisualStructure = {}, options = {}) {
  const base = toPlainObject(questionVisualStructure);
  const normalized = {
    ...base,
    schema_version:
      String(base.schema_version || "").trim() || QUESTION_VISUAL_STRUCTURE_SCHEMA,
    generated_by:
      String(base.generated_by || options.generatedBy || "runtime_visual_split_adapter").trim(),
    runtime_run_id: String(
      options.runtimeRunId ?? base.runtime_run_id ?? ""
    ).trim(),
    question_uid: String(options.questionUid ?? base.question_uid ?? "").trim(),
    stem_md: coalesceString(base.stem_md, options.stemMd, options.stem),
    answer_md: coalesceString(base.answer_md, options.answerMd, options.answer),
    analysis_md: coalesceString(
      base.analysis_md,
      options.analysisMd,
      options.explanation
    ),
    legacy_stem_md: coalesceString(
      base.legacy_stem_md,
      options.legacyStemMd,
      base.stem_md,
      options.stemMd,
      options.stem
    ),
    gating: toPlainObject(base.gating),
    options: Array.isArray(base.options)
      ? base.options.filter((item) => item && typeof item === "object" && !Array.isArray(item)).map((item) => deepCloneJson(item))
      : [],
    content_blocks: Array.isArray(base.content_blocks)
      ? base.content_blocks.filter((item) => item && typeof item === "object" && !Array.isArray(item)).map((item) => deepCloneJson(item))
      : [],
    visual_assets: (Array.isArray(base.visual_assets) ? base.visual_assets : [])
      .map((item) => normalizeVisualAsset(item))
      .filter(Boolean),
    review_flags: normalizeStringArray(base.review_flags),
  };
  if (!normalized.question_uid) {
    normalized.question_uid = String(options.fallbackQuestionUid || "").trim();
  }
  return normalized;
}

export function mergeSourceRefsJson(existing = {}, questionVisualStructure = {}) {
  const merged = toPlainObject(existing);
  const schemaVersions = toPlainObject(merged.schema_versions);
  const normalizedQvs = normalizeQuestionVisualStructure(questionVisualStructure);
  schemaVersions.question_visual_structure =
    normalizedQvs.schema_version || QUESTION_VISUAL_STRUCTURE_SCHEMA;
  merged.schema_versions = schemaVersions;
  merged.question_visual_structure = normalizedQvs;
  return merged;
}

export function normalizeTaskSourceRefs(task = {}, options = {}) {
  const explicitRefs = stripNonPortableFields(task.source_refs_json);
  const mergedRefs = stripNonPortableFields(task.merged_source_refs_json);
  const baseRefs =
    Object.keys(mergedRefs).length > 0 ? mergedRefs : deepCloneJson(explicitRefs);
  const qvsCandidate =
    task.question_visual_structure || baseRefs.question_visual_structure || null;
  if (!qvsCandidate) {
    return baseRefs;
  }
  const normalizedQvs = normalizeQuestionVisualStructure(qvsCandidate, {
    runtimeRunId:
      options.runtimeRunId ||
      baseRefs.question_visual_structure?.runtime_run_id ||
      "",
    questionUid:
      task.question_uid ||
      baseRefs.question_visual_structure?.question_uid ||
      options.questionUid ||
      task.local_task_id ||
      options.fallbackQuestionUid ||
      "",
    stem: task.stem || task.stem_text_md || "",
    answer: task.answer || task.answer_text_md || "",
    explanation: task.explanation || task.analysis_text_md || "",
  });
  return mergeSourceRefsJson(baseRefs, normalizedQvs);
}

export function normalizeBundleTask(task = {}, options = {}) {
  const sourceRefsJson = normalizeTaskSourceRefs(task, options);
  const qvs = toPlainObject(sourceRefsJson.question_visual_structure);
  const normalized = {
    ...deepCloneJson(task),
    source_refs_json: sourceRefsJson,
  };
  normalized.stem = coalesceString(
    normalized.stem,
    normalized.stem_text_md,
    qvs.legacy_stem_md,
    qvs.stem_md
  );
  normalized.answer = coalesceString(
    normalized.answer,
    normalized.answer_text_md,
    qvs.answer_md
  );
  normalized.explanation = coalesceString(
    normalized.explanation,
    normalized.analysis_text_md,
    qvs.analysis_md
  );
  return normalized;
}

export function normalizeLessonDraftBundle(bundle = {}, options = {}) {
  const normalized = deepCloneJson(bundle) || {};
  normalized.tasks = Array.isArray(normalized.tasks)
    ? normalized.tasks.map((task) =>
        normalizeBundleTask(task, {
          runtimeRunId:
            options.runtimeRunId ||
            normalized.runtime_run_id ||
            normalized.run_id ||
            "",
        })
      )
    : [];
  return normalized;
}

export function looksLikeVisualQuestionManifest(value) {
  return Boolean(
    value &&
      typeof value === "object" &&
      !Array.isArray(value) &&
      Array.isArray(value.questions) &&
      !Array.isArray(value.tasks)
  );
}

export function adaptQuestionAssetManifestToLessonDraftBundle(manifest = {}, options = {}) {
  const questions = Array.isArray(manifest.questions) ? manifest.questions : [];
  const sourceTree =
    Array.isArray(options.source_tree) && options.source_tree.length
      ? deepCloneJson(options.source_tree)
      : [
          {
            source_node_local_id: "root",
            node_type: "lesson",
            phase: "knowledge_main",
            title:
              options.rootTitle ||
              options.title ||
              options.lessonTitle ||
              options.lesson_id ||
              "visual_split_lesson",
            order_index: 0,
          },
        ];
  return normalizeLessonDraftBundle(
    {
      bundle_id:
        options.bundle_id ||
        options.bundleId ||
        options.lesson_id ||
        options.lessonId ||
        "visual_split_bundle",
      lesson_id: options.lesson_id || options.lessonId || "visual_split_lesson",
      title:
        options.title ||
        options.lessonTitle ||
        options.lesson_id ||
        options.lessonId ||
        "visual_split_lesson",
      subject: options.subject || null,
      stage: options.stage || null,
      track_code: options.track_code || options.trackCode || null,
      grade: options.grade || null,
      season: options.season || null,
      source_tree: sourceTree,
      tasks: questions.map((question, index) =>
        normalizeBundleTask(
          {
            local_task_id:
              question.local_task_id ||
              question.localTaskId ||
              question.question_uid ||
              question.question_id ||
              `visual_question_${index + 1}`,
            source_node_local_id:
              question.source_node_local_id ||
              question.sourceNodeLocalId ||
              sourceTree[0]?.source_node_local_id ||
              "root",
            question_type:
              question.question_type ||
              question.component_kind ||
              question.component_label ||
              "question",
            stem:
              question.display_markdown ||
              question.stem_text_md ||
              question.stem ||
              "",
            answer: question.answer_text_md || question.answer || "",
            explanation:
              question.analysis_text_md || question.explanation || "",
            checkpoint_codes:
              question.checkpoint_codes ||
              (question.checkpoint ? [question.checkpoint] : []),
            subject_tags: question.subject_tags || question.tags || [],
            source_refs_json:
              question.merged_source_refs_json ||
              question.source_refs_json ||
              {},
            merged_source_refs_json: question.merged_source_refs_json || null,
            question_visual_structure: question.question_visual_structure || null,
            question_uid:
              question.question_uid || question.question_id || `visual_question_${index + 1}`,
            stem_text_md: question.stem_text_md || "",
            answer_text_md: question.answer_text_md || "",
            analysis_text_md: question.analysis_text_md || "",
          },
          {
            runtimeRunId:
              options.runtime_run_id || options.runtimeRunId || "",
            questionUid:
              question.question_uid || question.question_id || `visual_question_${index + 1}`,
          }
        )
      ),
    },
    {
      runtimeRunId: options.runtime_run_id || options.runtimeRunId || "",
    }
  );
}

export function extractAssetDisplayRefs(markdown = "") {
  return [...new Set(String(markdown || "").match(assetDisplayRefPattern) || [])];
}

export function resolveQuestionVisualAsset(sourceRefsJson = {}, displayRef = "", options = {}) {
  const refs = toPlainObject(sourceRefsJson);
  const qvs = toPlainObject(refs.question_visual_structure);
  const assets = (Array.isArray(qvs.visual_assets) ? qvs.visual_assets : [])
    .map((item) => normalizeVisualAsset(item))
    .filter(Boolean);
  const duplicateAssetIds = collectDuplicateAssetIds(assets);
  const normalizedRef = String(displayRef || "").trim();
  if (!normalizedRef.startsWith("asset://")) {
    return {
      ok: false,
      error: "unsupported_asset_display_ref",
      displayRef: normalizedRef,
    };
  }
  const assetId = normalizedRef.slice("asset://".length);
  if (duplicateAssetIds.includes(assetId)) {
    return {
      ok: false,
      error: "duplicate_asset_id",
      assetId,
      displayRef: normalizedRef,
    };
  }
  const asset = assets.find((item) => item?.asset_id === assetId);
  if (!asset) {
    return {
      ok: false,
      error: "asset_id_not_found",
      assetId,
      displayRef: normalizedRef,
    };
  }
  if (!isRelativeStorageKey(asset.storage_key)) {
    return {
      ok: false,
      error: "asset_storage_key_not_relative",
      assetId,
      asset,
    };
  }
  if (options.requireAttached !== false && asset.attach_status !== "attached") {
    return {
      ok: false,
      error: "asset_not_attached",
      assetId,
      asset,
    };
  }
  if (options.requireMaterialized !== false && asset.file_status !== "materialized") {
    return {
      ok: false,
      error: "asset_not_materialized",
      assetId,
      asset,
    };
  }
  if (options.allowEvidenceOnly !== true && asset.placement_scope === "evidence_only") {
    return {
      ok: false,
      error: "asset_evidence_only",
      assetId,
      asset,
    };
  }
  return {
    ok: true,
    assetId,
    asset,
  };
}

export function validateQuestionVisualSourceRefs(sourceRefsJson = {}, options = {}) {
  const refs = toPlainObject(sourceRefsJson);
  const qvs = refs.question_visual_structure
    ? normalizeQuestionVisualStructure(refs.question_visual_structure)
    : null;
  if (!qvs) {
    return {
      ok: true,
      skipped: true,
      errors: [],
      warnings: [],
      assetRefs: [],
    };
  }

  const errors = [];
  const warnings = [];
  const assets = qvs.visual_assets || [];
  const duplicateAssetIds = collectDuplicateAssetIds(assets);
  const assetById = new Map(assets.map((asset) => [asset.asset_id, asset]));
  const assetRefs = extractAssetDisplayRefs(qvs.legacy_stem_md || "");

  if (!qvs.runtime_run_id) {
    warnings.push("question_visual_structure_runtime_run_id_missing");
  }

  for (const assetId of duplicateAssetIds) {
    errors.push(`duplicate_asset_id:${assetId}`);
  }

  for (const asset of assets) {
    if (!asset.storage_key || !isRelativeStorageKey(asset.storage_key)) {
      errors.push(
        `asset_storage_key_not_relative:${asset.asset_id || "unknown"}`
      );
    }
    if (String(asset.display_ref || "").trim() && asset.display_ref !== `asset://${asset.asset_id}`) {
      warnings.push(`asset_display_ref_noncanonical:${asset.asset_id}`);
    }
    if (!String(asset.bbox_space || "").trim()) {
      errors.push(`bbox_space_missing:${asset.asset_id || "unknown"}`);
    }
    if (
      !String(asset.source_image_asset_id || "").trim() &&
      !String(asset.source_image_storage_key || "").trim()
    ) {
      errors.push(`source_image_ref_missing:${asset.asset_id || "unknown"}`);
    }
    if (
      String(asset.placement_scope || "").trim() === "option_inline" &&
      !String(asset.option_key || "").trim()
    ) {
      errors.push(`option_asset_option_key_missing:${asset.asset_id || "unknown"}`);
    }
    if (
      String(asset.asset_role || "").trim() === "analysis" &&
      String(asset.option_key || "").trim()
    ) {
      errors.push(`analysis_asset_option_key_forbidden:${asset.asset_id || "unknown"}`);
    }
  }

  for (const displayRef of assetRefs) {
    const resolved = resolveQuestionVisualAsset(sourceRefsJson, displayRef, {
      requireAttached: options.requireAttached !== false,
      requireMaterialized: options.requireMaterialized !== false,
    });
    if (!resolved.ok) {
      errors.push(`${resolved.error}:${displayRef}`);
      continue;
    }
    if (resolved.asset.placement_scope === "evidence_only") {
      errors.push(`evidence_asset_in_legacy_markdown:${displayRef}`);
    }
  }

  for (const option of qvs.options || []) {
    const optionKey = String(option.option_key || option.key || "").trim() || "unknown";
    const assetIds = normalizeStringArray(option.asset_ids);
    for (const assetId of assetIds) {
      const asset = assetById.get(assetId);
      if (!asset) {
        errors.push(`option_asset_missing:${optionKey}:${assetId}`);
        continue;
      }
      if (asset.placement_scope === "evidence_only") {
        errors.push(`option_asset_cannot_be_evidence_only:${optionKey}:${assetId}`);
      }
      if (String(asset.attach_status || "").trim() !== "attached") {
        errors.push(`option_asset_not_attached:${optionKey}:${assetId}`);
      }
      if (
        typeof asset.confidence === "number" &&
        Number.isFinite(asset.confidence) &&
        asset.confidence < 0.75
      ) {
        errors.push(`option_asset_low_confidence:${optionKey}:${assetId}`);
      }
    }
  }

  for (const block of qvs.content_blocks || []) {
    const assetId = String(block.asset_id || "").trim();
    if (assetId && !assetById.has(assetId)) {
      errors.push(`content_block_asset_missing:${assetId}`);
    }
  }

  return {
    ok: errors.length === 0,
    skipped: false,
    errors: normalizeStringArray(errors),
    warnings: normalizeStringArray(warnings),
    assetRefs,
    assetCount: assets.length,
    questionUid: qvs.question_uid || "",
  };
}
