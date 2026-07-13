/**
 * Purpose:
 * - convert runtime_manifest.json outputs into the existing LessonDraftBundle boundary.
 * - keep runtime-manifest ingest as an adapter-only layer, so downstream import/review/publish
 *   still uses the same core backend write path.
 */

import fs from "node:fs";
import path from "node:path";
import { createHash } from "node:crypto";

import { normalizeDifficultyPayload, resolveTrackProfile } from "./runtime_subject_tracks.mjs";

function deepCloneJson(value) {
  return value === undefined ? undefined : JSON.parse(JSON.stringify(value));
}

function normalizeText(value) {
  return String(value || "").trim();
}

function slug(value) {
  return normalizeText(value)
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, "_")
    .replace(/^_+|_+$/g, "") || "runtime_manifest";
}

function computeStableHash(value) {
  return createHash("sha256").update(JSON.stringify(value)).digest("hex");
}

function readJsonIfExists(filePath) {
  try {
    if (!filePath || !fs.existsSync(filePath)) {
      return null;
    }
    return JSON.parse(fs.readFileSync(filePath, "utf8"));
  } catch {
    return null;
  }
}

function looksLikeReadableFile(filePath) {
  try {
    return Boolean(filePath) && fs.existsSync(filePath) && fs.statSync(filePath).isFile();
  } catch {
    return false;
  }
}

function resolveManifestBaseDir(options = {}) {
  const explicitBaseDir = normalizeText(
    options.base_dir ||
      options.baseDir ||
      options.document_metadata?.base_dir ||
      options.document_metadata?.baseDir ||
      options.documentMetadata?.base_dir ||
      options.documentMetadata?.baseDir
  );
  if (explicitBaseDir) {
    return path.resolve(explicitBaseDir);
  }

  const manifestPath = normalizeText(options.manifest_path || options.manifestPath);
  if (!manifestPath) {
    return "";
  }
  const manifestDir = path.dirname(path.resolve(manifestPath));
  const runtimeState = readJsonIfExists(path.join(manifestDir, "runtime_state.json"));
  const publishedRoot = normalizeText(runtimeState?.publish_root);
  if (publishedRoot) {
    return path.resolve(publishedRoot);
  }
  return manifestDir;
}

function resolvePublishedArtifactPath(originalPath, baseDir, fallbackFolder) {
  const rawPath = normalizeText(originalPath);
  if (!rawPath) {
    return "";
  }
  if (looksLikeReadableFile(rawPath)) {
    return path.resolve(rawPath);
  }
  if (!baseDir) {
    return "";
  }
  const basename = path.basename(rawPath);
  const candidate = path.join(baseDir, fallbackFolder, basename);
  return looksLikeReadableFile(candidate) ? candidate : "";
}

function readTextFile(filePath) {
  try {
    return looksLikeReadableFile(filePath) ? fs.readFileSync(filePath, "utf8") : "";
  } catch {
    return "";
  }
}

function comparePosition(left = {}, right = {}) {
  const leftPage = Number(left.page ?? left.start_page ?? 0);
  const rightPage = Number(right.page ?? right.start_page ?? 0);
  if (leftPage !== rightPage) {
    return leftPage - rightPage;
  }
  return Number(left.y ?? left.start_y ?? 0) - Number(right.y ?? right.start_y ?? 0);
}

function pickOwningComponent(question, components = []) {
  const ordered = [...components].sort(comparePosition);
  const questionPos = {
    page: Number(question.start_page || 0),
    y: Number(question.start_y || 0),
  };
  let candidate = null;
  for (const component of ordered) {
    const componentStart = {
      page: Number(component.start_page || 0),
      y: Number(component.start_y || 0),
    };
    if (comparePosition(componentStart, questionPos) <= 0) {
      candidate = component;
      continue;
    }
    break;
  }
  return candidate || ordered[0] || null;
}

function normalizeComponentLabel(component = {}) {
  return normalizeText(component.label || component.block_id || component.kind || "source_block");
}

function inferQuestionType(question = {}, transcript = "", previewText = "") {
  const combined = [question.label, transcript, previewText].filter(Boolean).join("\n");
  if (/[A-D][.．、)]\s*/u.test(combined) && /[B-D][.．、)]\s*/u.test(combined)) {
    return "single_choice";
  }
  if (/判断|true or false|t\/f/iu.test(combined)) {
    return "true_false";
  }
  return normalizeText(question.question_type || question.kind || "question");
}

function extractStemText(transcript = "", previewText = "") {
  const source = normalizeText(transcript) || normalizeText(previewText);
  if (!source) {
    return "";
  }
  const markerIndex = source.search(/【答案】|答案[:：]/u);
  return markerIndex >= 0 ? source.slice(0, markerIndex).trim() : source;
}

function extractAnswerText(transcript = "") {
  const source = normalizeText(transcript);
  if (!source) {
    return "";
  }
  const patterns = [
    /【答案】\s*([A-Z](?:\s*[,/]\s*[A-Z])*)/u,
    /答案[:：]\s*([A-Z](?:\s*[,/]\s*[A-Z])*)/u,
    /【答案】\s*([^\r\n]+)/u,
    /答案[:：]\s*([^\r\n]+)/u,
  ];
  for (const pattern of patterns) {
    const match = source.match(pattern);
    if (match?.[1]) {
      return normalizeText(match[1]);
    }
  }
  return "";
}

function extractExplanationText(transcript = "") {
  const source = normalizeText(transcript);
  if (!source) {
    return "";
  }
  const markers = ["【解析】", "【找】", "【翻译】"];
  for (const marker of markers) {
    const index = source.indexOf(marker);
    if (index >= 0) {
      return source.slice(index).trim();
    }
  }
  return "";
}

function buildCheckpointCandidates(component = null, question = {}) {
  return [...new Set([normalizeComponentLabel(component), normalizeText(question.label)].filter(Boolean))];
}

function buildSourceTree(components = [], lessonTitle, sourceDocumentRefs = []) {
  return [
    {
      source_node_local_id: "root",
      node_type: "lesson",
      phase: "runtime_manifest",
      title: lessonTitle,
      source_document_refs: deepCloneJson(sourceDocumentRefs),
      order_index: 0,
    },
    ...components.map((component, index) => ({
      source_node_local_id: normalizeText(component.block_id) || `component_${index + 1}`,
      parent_source_node_local_id: "root",
      node_type: "component",
      phase: normalizeText(component.kind || "runtime_component"),
      title: normalizeComponentLabel(component),
      checkpoint_candidates: [normalizeComponentLabel(component)].filter(Boolean),
      order_index: index + 1,
      source_refs_json: {
        runtime_manifest: {
          block_id: component.block_id || null,
          kind: component.kind || null,
          label: component.label || null,
          start_page: component.start_page ?? null,
          end_page: component.end_page ?? null,
          start_y: component.start_y ?? null,
          end_y: component.end_y ?? null,
        },
      },
    })),
  ];
}

export function looksLikeRuntimeManifest(value) {
  return Boolean(
    value &&
      typeof value === "object" &&
      !Array.isArray(value) &&
      Array.isArray(value.questions) &&
      Array.isArray(value.components) &&
      !Array.isArray(value.tasks) &&
      (value.run_name || value.source_pdf || value.question_count !== undefined)
  );
}

/**
 * Runtime manifests often point at temporary work directories, so the adapter
 * rewrites artifact paths back to the published bundle when that mirror exists.
 */
export function adaptRuntimeManifestToLessonDraftBundle(runtimeManifest = {}, options = {}) {
  const manifest = deepCloneJson(runtimeManifest) || {};
  if (!looksLikeRuntimeManifest(manifest)) {
    throw new Error("invalid_runtime_manifest_payload");
  }

  const trackProfile = resolveTrackProfile({
    track_code: options.track_code || options.trackCode,
    subject: options.subject,
    stage: options.stage,
    grade: options.grade,
  });
  const baseDir = resolveManifestBaseDir(options);
  const sourceDocumentRefs = Array.isArray(options.source_document_refs || options.sourceDocumentRefs)
    ? deepCloneJson(options.source_document_refs || options.sourceDocumentRefs)
    : [];
  const lessonId =
    normalizeText(options.lesson_id || options.lessonId) ||
    `runtime_manifest_${slug(trackProfile.track_code)}_${slug(manifest.run_name || manifest.source_pdf || "lesson")}`;
  const lessonTitle =
    normalizeText(
      options.title ||
        options.lessonTitle ||
        options.document_metadata?.lesson_title ||
        options.documentMetadata?.lesson_title ||
        manifest.run_name
    ) || lessonId;
  const bundleId =
    normalizeText(options.bundle_id || options.bundleId) ||
    `runtime_manifest:${trackProfile.track_code}:${slug(manifest.run_name || lessonId)}`;
  const runtimeRunId = normalizeText(options.runtime_run_id || options.runtimeRunId || manifest.run_name);
  const issues = [];
  const components = Array.isArray(manifest.components) ? manifest.components : [];
  const sourceTree = buildSourceTree(components, lessonTitle, sourceDocumentRefs);

  const tasks = (Array.isArray(manifest.questions) ? manifest.questions : []).map((question, index) => {
    const transcriptPath = resolvePublishedArtifactPath(
      question.transcript_path,
      baseDir,
      "question_transcripts"
    );
    const cropPath = resolvePublishedArtifactPath(question.crop_path, baseDir, "question_crops");
    const transcript = readTextFile(transcriptPath);
    const previewText = normalizeText(question.text_preview);
    const component = pickOwningComponent(question, components);
    const checkpointCandidates = buildCheckpointCandidates(component, question);
    if (!transcript && !previewText) {
      issues.push(`transcript_missing:${question.block_id || index + 1}`);
    }
    if (!cropPath) {
      issues.push(`crop_path_unresolved:${question.block_id || index + 1}`);
    }
    const difficultyMissing =
      question.difficulty_level === undefined &&
      question.difficultyLevel === undefined &&
      question.difficulty_scheme === undefined &&
      question.difficultyScheme === undefined;
    if (difficultyMissing) {
      issues.push(`difficulty_defaulted:${question.block_id || index + 1}`);
    }
    if (checkpointCandidates.length === 0) {
      issues.push(`checkpoint_candidates_missing:${question.block_id || index + 1}`);
    }
    const difficulty = normalizeDifficultyPayload(question, {
      defaultScheme: trackProfile.difficulty_scheme,
      defaultSource: "runtime_manifest_default",
      defaultConfidence: 0.2,
      defaultLevel: 3,
    });
    const sourceRefsJson = {
      page_no: question.start_page ?? null,
      source_document_refs: deepCloneJson(sourceDocumentRefs),
      runtime_manifest: {
        run_name: manifest.run_name || null,
        block_id: question.block_id || null,
        kind: question.kind || null,
        label: question.label || null,
        start_page: question.start_page ?? null,
        end_page: question.end_page ?? null,
        start_y: question.start_y ?? null,
        end_y: question.end_y ?? null,
        crop_path: cropPath || null,
        transcript_path: transcriptPath || null,
        text_preview: previewText || null,
        source_pdf: manifest.source_pdf || null,
      },
    };
    if (question.question_visual_structure && typeof question.question_visual_structure === "object") {
      sourceRefsJson.question_visual_structure = deepCloneJson(question.question_visual_structure);
    }
    return {
      local_task_id: normalizeText(question.local_task_id || question.localTaskId || question.block_id) || `question_${index + 1}`,
      source_node_local_id: normalizeText(component?.block_id) || "root",
      question_type: inferQuestionType(question, transcript, previewText),
      stem: extractStemText(transcript, previewText),
      answer: extractAnswerText(transcript || previewText),
      explanation: extractExplanationText(transcript || previewText),
      checkpoint_candidates: checkpointCandidates,
      checkpoint_codes: [],
      subject_tags: [normalizeComponentLabel(component), normalizeText(question.kind)].filter(Boolean),
      source_refs_json: sourceRefsJson,
      cropPath: cropPath || "",
      previewText: previewText || extractStemText(transcript, previewText),
      display_markdown: extractStemText(transcript, previewText),
      runtime_run_id: runtimeRunId,
      question_visual_structure:
        question.question_visual_structure && typeof question.question_visual_structure === "object"
          ? deepCloneJson(question.question_visual_structure)
          : null,
      ...difficulty,
    };
  });

  const bundle = {
    bundle_id: bundleId,
    lesson_id: lessonId,
    title: lessonTitle,
    subject: trackProfile.subject,
    stage: trackProfile.stage,
    track_code: trackProfile.track_code,
    grade: normalizeText(options.grade || options.document_metadata?.grade || options.documentMetadata?.grade),
    season: normalizeText(options.season || options.document_metadata?.season || options.documentMetadata?.season),
    runtime_run_id: runtimeRunId,
    source_tree: sourceTree,
    source_document_refs: sourceDocumentRefs,
    document_metadata: {
      ...deepCloneJson(options.document_metadata || options.documentMetadata || {}),
      source_pdf: manifest.source_pdf || null,
      page_count: manifest.page_count ?? null,
      component_count: manifest.component_count ?? components.length,
      question_count: manifest.question_count ?? tasks.length,
      run_name: manifest.run_name || null,
      base_dir: baseDir || null,
    },
    validation_issues: [...new Set(issues)],
    tasks,
  };
  bundle.content_hash = computeStableHash(bundle);
  return bundle;
}
