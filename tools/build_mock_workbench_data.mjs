/**
 * 用途：
 * - 通过合并 OCR 预览、YAML 元数据和可信摘录构建 mock 工作台数据集。
 * - 大部分演示数据归一化规则集中在这里，让 UI 保持轻量。
 */

import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

// Derive the workspace root from the script location so clean clones stay portable.
const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const outputPath = path.join(projectRoot, "outputs/split_builder/mock_workbench/workbench_data.js");

const readJson = async (relativePath) => {
  const fullPath = path.join(projectRoot, relativePath);
  return JSON.parse(await fs.readFile(fullPath, "utf8"));
};

const readText = async (relativePath) => {
  const fullPath = path.join(projectRoot, relativePath);
  return fs.readFile(fullPath, "utf8");
};

function parseYamlScalar(raw) {
  const value = String(raw || "").trim();
  if (!value) return "";
  if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
    return value.slice(1, -1);
  }
  if (value === "true") return true;
  if (value === "false") return false;
  if (/^-?\d+(?:\.\d+)?$/.test(value)) return Number(value);
  return value;
}

function parseSimpleYaml(text) {
  const lines = String(text || "").replace(/\r/g, "").split("\n");

  function parseBlock(startIndex, indent) {
    const result = {};
    let index = startIndex;

    while (index < lines.length) {
      const rawLine = lines[index];
      if (!rawLine.trim() || rawLine.trim().startsWith("#")) {
        index += 1;
        continue;
      }

      const currentIndent = rawLine.match(/^ */)[0].length;
      if (currentIndent < indent) break;
      if (currentIndent > indent) {
        index += 1;
        continue;
      }

      const trimmed = rawLine.trim();
      const sepIndex = trimmed.indexOf(":");
      if (sepIndex < 0) {
        index += 1;
        continue;
      }

      const key = trimmed.slice(0, sepIndex).trim();
      const remainder = trimmed.slice(sepIndex + 1).trim();

      if (remainder) {
        result[key] = parseYamlScalar(remainder);
        index += 1;
        continue;
      }

      const child = parseBlock(index + 1, indent + 2);
      result[key] = child.value;
      index = child.nextIndex;
    }

    return { value: result, nextIndex: index };
  }

  return parseBlock(0, 0).value;
}

const gradeRank = {
  初一: 1,
  初二: 2,
  初三: 3,
  高一: 4,
  高二: 5,
  高三: 6,
};

const riskLabelMap = {
  PASS_BY_VISUAL_GATE: "低风险",
  NEEDS_MODEL_OR_HUMAN_REVIEW: "高风险",
};

const issueLabelMap = {
  no_clear_question_number: "题号不清晰",
};

const componentLabelMap = {
  example: "例题讲解",
  practice: "强化训练",
  advanced: "能力进阶",
  after_class: "课后落实",
  checkpoint: "考点",
};

function shortPreview(text, max = 116) {
  const clean = String(text || "").replace(/\s+/g, " ").trim();
  return clean.length > max ? `${clean.slice(0, max)}...` : clean;
}

function normalizePreviewText(text) {
  return String(text || "").replace(/\s+/g, " ").trim();
}

function clipOcrText(text, max = 480) {
  const clean = normalizePreviewText(text);
  if (!clean) return "";
  return clean.length > max ? `${clean.slice(0, max)}...` : clean;
}

const excerptStopMarkers = ["【答案】", "【分析】", "【解答】", "【点评】", "答案：", "分析：", "解："];

function extractTrustedExcerpt(text) {
  const clean = normalizePreviewText(text);
  if (!clean) return "";

  let cutIndex = clean.length;

  excerptStopMarkers.forEach((marker) => {
    const index = clean.indexOf(marker);
    if (index > 0 && index < cutIndex) cutIndex = index;
  });

  return clean
    .slice(0, cutIndex)
    .replace(/[，,；;：:。.\s]+$/, "")
    .trim();
}

function preprocessPreviewCandidate(text) {
  let clean = normalizePreviewText(text)
    .replace(/[\uE000-\uF8FF]/g, " ")
    .replace(/[•◆◇■□]/g, " ")
    .trim();

  clean = extractTrustedExcerpt(clean);
  if (!clean) return "";

  const questionLead = clean.match(/\d+\s*[．.]/);
  if (questionLead && questionLead.index !== undefined && questionLead.index <= 80) {
    clean = clean.slice(questionLead.index);
  }

  clean = clean
    .replace(/\s+([，。；：！？）】》])/g, "$1")
    .replace(/([（【《])\s+/g, "$1")
    .replace(/\s+([A-D])\s*[．.]/g, " $1．")
    .replace(/\b\d{1,3}\s*$/, "")
    .replace(/\s+/g, " ")
    .trim();

  return clean;
}

function isReadableQuestionExcerpt(text, sourceHint = "") {
  const stats = previewSignalStats(text);
  if (!stats.length) return false;

  const hasQuestionLead = /^\d+\s*[．.]/.test(stats.clean);
  const hasStemCue = /(已知|如图|下列|则|求|设|若|满足|函数|方程|不等式|向量|中点|共面)/.test(stats.clean);
  const hasChoiceCue = /A[．.]/.test(stats.clean) || /（\s*.*\s*）/.test(stats.clean);
  const readableCore = stats.noisyHits === 0 && stats.privateUseCount === 0;
  const denseEnough = stats.length >= 20 && stats.cjkCount >= 8;
  const ocrDenseEnough = sourceHint === "ocr_fallback" && stats.length >= 18 && stats.cjkCount >= 6;

  return readableCore && (denseEnough || ocrDenseEnough) && (hasQuestionLead || hasStemCue || hasChoiceCue);
}

function previewCandidateScore(text, sourceHint = "") {
  const stats = previewSignalStats(text);
  let score = 0;

  score += Math.min(stats.length, 140);
  score += stats.cjkCount * 3;
  score -= stats.noisyHits * 80;
  score -= stats.privateUseCount * 120;
  score -= Math.max(stats.mathSymbolCount - 18, 0) * 2;

  if (/^\d+\s*[．.]/.test(stats.clean)) score += 24;
  if (/(已知|如图|下列|则|求|设|若|满足|函数|方程|不等式|向量|中点|共面)/.test(stats.clean)) score += 20;
  if (sourceHint === "pdf_text_layer") score += 6;
  if (sourceHint === "ocr_fallback") score += 4;

  return score;
}

function previewSignalStats(text) {
  const clean = normalizePreviewText(text);
  const cjkCount = (clean.match(/[\u4e00-\u9fff]/g) || []).length;
  const latinCount = (clean.match(/[A-Za-z]/g) || []).length;
  const digitCount = (clean.match(/\d/g) || []).length;
  const privateUseCount = (clean.match(/[\uE000-\uF8FF]/g) || []).length;
  const mathSymbolCount = (clean.match(/[=+\-*/^<>≤≥(){}\[\]|_]/g) || []).length;
  const symbolCount = clean.length - cjkCount - latinCount - digitCount;
  const optionMarkerCount = (clean.match(/[A-D][．.、]/g) || []).length;
  const noisyTokens = ["\uFFFD", "", "", "", "", "", ""];
  const noisyHits = noisyTokens.reduce((sum, token) => sum + (clean.split(token).length - 1), 0);

  return {
    clean,
    length: clean.length,
    cjkCount,
    latinCount,
    digitCount,
    privateUseCount,
    mathSymbolCount,
    symbolCount,
    optionMarkerCount,
    noisyHits,
  };
}

function looksNoisyPreview(text) {
  const stats = previewSignalStats(text);
  if (!stats.length) return true;

  const sparseReadable = stats.cjkCount <= 8 && stats.length >= 24;
  const symbolHeavy =
    stats.length >= 32 && stats.symbolCount / Math.max(stats.length, 1) > 0.24 && stats.cjkCount < 20;
  const formulaNoise = stats.length >= 48 && stats.mathSymbolCount >= 7 && stats.cjkCount < 48;
  const privateUseNoise = stats.privateUseCount >= 1;
  const optionBurst = stats.optionMarkerCount >= 3 && stats.mathSymbolCount >= 6 && stats.cjkCount < 48;
  const optionFormulaMix = stats.optionMarkerCount >= 2 && stats.mathSymbolCount >= 4 && stats.cjkCount < 56;
  const tooShort = stats.length < 10;

  return stats.noisyHits >= 1 || privateUseNoise || sparseReadable || symbolHeavy || formulaNoise || optionBurst || optionFormulaMix || tooShort;
}

function buildStructuredFallback({ checkpoint, componentLabel, localNumber, page }) {
  const localPart = localNumber ? ` ${localNumber}` : "";
  const pagePart = page ? `P${String(page).padStart(2, "0")}` : "页码待复核";
  return `${checkpoint}｜${componentLabel}${localPart}｜${pagePart}。当前以题图为准，文字层待复核。`;
}

/**
 * 选择题目记录中存放的预览文本。
 * 顺序很重要：可信摘录优先于 OCR，结构化兜底让噪声页面仍可读。
 */
function buildStoredPreview({ rawText, pdfText, ocrText, sourceHint, checkpoint, componentLabel, localNumber, page }) {
  const normalizedRaw = normalizePreviewText(rawText);
  const normalizedPdf = normalizePreviewText(pdfText);
  const normalizedOcr = normalizePreviewText(ocrText);
  const candidates = [
    { source: sourceHint || "raw_text", text: normalizedRaw },
    { source: "pdf_text_layer", text: normalizedPdf },
    { source: "ocr_fallback", text: normalizedOcr },
  ]
    .map((candidate) => ({
      ...candidate,
      clean: preprocessPreviewCandidate(candidate.text),
    }))
    .filter((candidate) => candidate.clean);

  candidates.sort((a, b) => previewCandidateScore(b.clean, b.source) - previewCandidateScore(a.clean, a.source));
  const trustedCandidate = candidates.find((candidate) => isReadableQuestionExcerpt(candidate.clean, candidate.source));
  const trustedExcerpt = trustedCandidate?.clean || "";

  if (trustedExcerpt) {
    return {
      previewText: trustedExcerpt,
      previewShort: shortPreview(trustedExcerpt),
      trustedText: trustedExcerpt,
      ocrTextRaw: clipOcrText([normalizedPdf, normalizedOcr, normalizedRaw].filter(Boolean).join(" | ")),
      textStorageMode: "trusted_excerpt",
      storageNote:
        trustedCandidate?.source === "pdf_text_layer"
          ? "当前展示为从 PDF 文字层恢复并清洗后的题干摘录，答案与解析未直接进入主展示层。"
          : trustedCandidate?.source === "ocr_fallback"
            ? "当前展示为 OCR 补全后清洗的题干摘录，答案与解析未直接进入主展示层。"
            : "当前展示为清洗后的题干摘录，答案与解析未直接进入主展示层。",
    };
  }

  const fallback = buildStructuredFallback({ checkpoint, componentLabel, localNumber, page });
  return {
    previewText: fallback,
    previewShort: shortPreview(fallback),
    trustedText: "",
    ocrTextRaw: clipOcrText([normalizedPdf, normalizedOcr, normalizedRaw].filter(Boolean).join(" | ")),
    textStorageMode: "ocr_reference_only",
    storageNote: (normalizedPdf || normalizedOcr || normalizedRaw)
      ? "当前题块仍以题图为准，文字层存在公式噪声或抽取缺口，暂降级为内部参考。"
      : "当前题块暂未抽到稳定文字，先以题图为主。",
  };
}

/**
 * 把原始题目记录转成工作台 UI 使用的稳定演示 schema。
 * 审计元数据在这里合并，让前端过滤器不用理解源文件。
 */
function normalizeQuestions(questions, auditsById) {
  const seenInCheckpoint = new Map();

  return questions.map((question, index) => {
    const checkpointKey = question.checkpoint || "未命名考点";
    const currentCount = (seenInCheckpoint.get(checkpointKey) || 0) + 1;
    seenInCheckpoint.set(checkpointKey, currentCount);

    const audit = auditsById[question.question_id] || {
      audit_status: "PASS_BY_VISUAL_GATE",
      issues: [],
      qa: {},
    };

    const previewRaw = normalizePreviewText(question.text_preview || "");
    const componentKind = question.component_kind || "practice";
    const componentLabel = componentLabelMap[componentKind] || question.component_label || "棰樺潡";
    const localNumber = String(question.local_number ?? "");
    const page = question.fragments?.[0]?.page || question.visual_pages?.[0] || "";
    const storedPreview = buildStoredPreview({
      rawText: previewRaw,
      pdfText: question.text_preview_pdf || "",
      ocrText: question.text_preview_ocr || "",
      sourceHint: question.text_preview_source || "",
      checkpoint: checkpointKey,
      componentLabel,
      localNumber,
      page,
    });
    const preview = storedPreview.previewText;
    const versionTags = new Set(["常用版"]);

    if (componentKind === "example") {
      versionTags.add("基础版");
      if (currentCount >= 2 && preview.length > 120) versionTags.add("进阶版");
    } else if (componentKind === "practice") {
      if (currentCount <= 1) versionTags.add("基础版");
      if (currentCount >= 2 || preview.length > 150) versionTags.add("进阶版");
    } else if (componentKind === "advanced") {
      versionTags.add("进阶版");
    } else if (componentKind === "after_class") {
      versionTags.add("基础版");
    }

    const risk =
      audit.audit_status === "NEEDS_MODEL_OR_HUMAN_REVIEW"
        ? "高风险"
        : componentKind === "advanced"
          ? "中风险"
          : "低风险";

    return {
      id: question.question_id,
      order: index + 1,
      checkpoint: checkpointKey,
      componentKind,
      componentLabel: componentLabelMap[componentKind] || question.component_label || "题块",
      localNumber: String(question.local_number ?? ""),
      sourcePage: page,
      previewText: preview,
      previewShort: shortPreview(preview),
      trustedText: storedPreview.trustedText,
      ocrTextRaw: storedPreview.ocrTextRaw,
      textStorageMode: storedPreview.textStorageMode,
      storageNote: storedPreview.storageNote,
      cropPath: question.crop_path,
      reviewStatus: question.review_status,
      reviewNote: question.review_note,
      visualPages: question.visual_pages || [],
      versionTags: [...versionTags],
      risk,
      riskIssues: (audit.issues || []).map((issue) => issueLabelMap[issue] || issue),
      auditStatus: audit.audit_status,
      visualStats: audit.qa?.visual_stats || {},
    };
  });
}

/**
 * 根据扁平知识点记录构建学科年级知识树。
 * UI 会直接读取这棵层级树，因此 ID 和排序必须保持确定性。
 */
function buildKnowledgeTrees(knowledgePoints) {
  const treeMap = {};

  for (const point of knowledgePoints) {
    const lessonId = point.lesson_id;
    if (!treeMap[lessonId]) treeMap[lessonId] = [];

    let moduleNode = treeMap[lessonId].find((node) => node.module === point.level_2_module);
    if (!moduleNode) {
      moduleNode = {
        module: point.level_2_module,
        lessonTopic: point.level_1_lesson_topic,
        items: [],
      };
      treeMap[lessonId].push(moduleNode);
    }

    if (!moduleNode.items.includes(point.level_3_min_knowledge_point)) {
      moduleNode.items.push(point.level_3_min_knowledge_point);
    }
  }

  return treeMap;
}

function summarizeByVersion(questions) {
  const stats = {
    基础版: 0,
    常用版: 0,
    进阶版: 0,
  };

  questions.forEach((question) => {
    question.versionTags.forEach((tag) => {
      if (stats[tag] !== undefined) stats[tag] += 1;
    });
  });

  return stats;
}

/**
 * 创建 mock 工作台展示给操作者的审阅队列。
 * 队列项应保持紧凑，详情留在链接的课时/题目记录上。
 */
function buildReviewQueue(splitLessons) {
  const allQuestions = Object.values(splitLessons).flatMap((lesson) =>
    lesson.questions.map((question) => ({
      ...question,
      lessonId: lesson.lesson_id,
      lessonTitle: lesson.lesson_title,
      stage: lesson.stage,
      grade: lesson.grade,
      season: lesson.season,
      pdfName: lesson.source_pdf_name,
    })),
  );

  const riskWeight = { 高风险: 3, 中风险: 2, 低风险: 1 };
  const top = allQuestions
    .sort((a, b) => {
      const riskDelta = riskWeight[b.risk] - riskWeight[a.risk];
      if (riskDelta !== 0) return riskDelta;
      return a.order - b.order;
    })
    .slice(0, 8);

  return top.map((question, index) => ({
    id: question.id,
    queueNo: String(index + 1).padStart(2, "0"),
    title: `${question.checkpoint}｜${question.componentLabel}`,
    meta: `P.${String(question.sourcePage).padStart(2, "0")} ｜ ${question.lessonTitle} ｜ ${question.stage}${question.grade}`,
    status: question.risk === "高风险" ? "待审核" : question.risk === "中风险" ? "复核中" : "已校验",
    statusClass: question.risk === "高风险" ? "red" : question.risk === "中风险" ? "orange" : "green",
    risk: question.risk,
    tags: question.riskIssues.length ? question.riskIssues : [question.componentLabel],
    lessonId: question.lessonId,
    questionId: question.id,
  }));
}

const juniorLessons = await readJson("outputs/junior_math_knowledge_map/lessons.json");
const seniorLessons = await readJson("outputs/senior_math_knowledge_map/lessons.json");
const juniorPoints = await readJson("outputs/junior_math_knowledge_map/knowledge_points.json");
const seniorPoints = await readJson("outputs/senior_math_knowledge_map/knowledge_points.json");
const runtimeConfigRelativePath = "config/runtime_observability.yaml";
const runtimeConfigFullPath = path.join(projectRoot, runtimeConfigRelativePath);
const runtimeConfigRaw = await readText(runtimeConfigRelativePath);
const runtimeConfigParsed = parseSimpleYaml(runtimeConfigRaw);
const runtimeConfigStat = await fs.stat(runtimeConfigFullPath);

const allLessons = [...juniorLessons, ...seniorLessons]
  .map((lesson) => ({
    ...lesson,
    hasVisualSplit: [
      "junior_g7_12_003",
      "junior_g9_04_022",
      "senior_g11_00_033",
    ].includes(lesson.lesson_id),
  }))
  .sort((a, b) => {
    const stageDelta = (gradeRank[a.grade] || 99) - (gradeRank[b.grade] || 99);
    if (stageDelta !== 0) return stageDelta;
    return (a.lesson_no || 999) - (b.lesson_no || 999);
  });

const treeMap = buildKnowledgeTrees([...juniorPoints, ...seniorPoints]);

const splitConfigs = [
  {
    lessonId: "junior_g7_12_003",
    splitPath:
      "outputs/ingress_splitter_v0.1/skill_trial_junior_g7_eq_to_equation_v01/teacher_visual_question_split_v0.2.json",
    gatePath:
      "outputs/ingress_splitter_v0.1/skill_trial_junior_g7_eq_to_equation_v01/quality_gate_v01/visual_quality_gate_v01.json",
  },
  {
    lessonId: "junior_g9_04_022",
    splitPath:
      "outputs/ingress_splitter_v0.1/skill_trial_junior_math_quad_equation_ineq_v05/teacher_visual_question_split_v0.2.json",
    gatePath:
      "outputs/ingress_splitter_v0.1/skill_trial_junior_math_quad_equation_ineq_v05/quality_gate_v01/visual_quality_gate_v01.json",
  },
  {
    lessonId: "senior_g11_00_033",
    splitPath:
      "outputs/ingress_splitter_v0.1/teacher_visual_question_split_space_vector_v02_final2/teacher_visual_question_split_v0.2.json",
    gatePath:
      "outputs/ingress_splitter_v0.1/teacher_visual_question_split_space_vector_v02_final2/quality_gate_v01/visual_quality_gate_v01.json",
  },
];

const splitLessons = {};

for (const config of splitConfigs) {
  const split = await readJson(config.splitPath);
  const gate = await readJson(config.gatePath);
  const lessonMeta = allLessons.find((lesson) => lesson.lesson_id === config.lessonId);
  if (!lessonMeta) continue;

  const questions = normalizeQuestions(split.questions || [], gate.audits || {});
  const checkpoints = [...new Set(questions.map((item) => item.checkpoint))];
  const versionStats = summarizeByVersion(questions);
  const sourcePdfPath = lessonMeta.source_pdf_path;

  splitLessons[config.lessonId] = {
    ...lessonMeta,
    source_pdf_path: sourcePdfPath,
    source_pdf_name: lessonMeta.source_pdf_name,
    objectives: lessonMeta.objectives,
    principle: split.principle,
    question_count: split.question_count,
    segment_count: split.segment_count,
    checkpoint_count: checkpoints.length,
    tree: treeMap[config.lessonId] || [],
    questions,
    versionStats,
    auditSummary: {
      pass: gate.status_counts?.PASS_BY_VISUAL_GATE || 0,
      review: gate.status_counts?.NEEDS_MODEL_OR_HUMAN_REVIEW || 0,
    },
  };
}

const reviewQueue = buildReviewQueue(splitLessons);

const data = {
  generatedAt: new Date().toISOString(),
  filters: {
    subjects: ["数学"],
    stages: ["初中", "高中"],
    grades: [...new Set(allLessons.map((lesson) => lesson.grade))],
    seasons: [...new Set(allLessons.map((lesson) => lesson.season))],
  },
  summary: {
    lessonCount: allLessons.length,
    juniorLessonCount: juniorLessons.length,
    seniorLessonCount: seniorLessons.length,
    visualSplitLessonCount: Object.keys(splitLessons).length,
    questionCount: Object.values(splitLessons).reduce((sum, lesson) => sum + lesson.question_count, 0),
    pendingReviewCount: reviewQueue.filter((item) => item.risk === "高风险").length,
  },
  lessonCatalog: allLessons,
  knowledgeTrees: treeMap,
  splitLessons,
  reviewQueue,
  runtimeConfig: {
    filePath: runtimeConfigFullPath,
    relativePath: runtimeConfigRelativePath.replace(/\\/g, "/"),
    updatedAt: runtimeConfigStat.mtime.toISOString(),
    rawYaml: runtimeConfigRaw,
    parsed: runtimeConfigParsed,
  },
  taskFlow: {
    currentImportLessonId: "junior_g7_12_003",
    queueLessonIds: ["junior_g7_12_003", "junior_g9_04_022", "senior_g11_00_033", "junior_g8_02_014"],
    historyLessonIds: ["junior_g7_12_003", "junior_g9_04_022", "senior_g11_00_033"],
  },
};

const bundle = `window.WORKBENCH_DATA = ${JSON.stringify(data, null, 2)};\n`;
await fs.mkdir(path.dirname(outputPath), { recursive: true });
await fs.writeFile(outputPath, bundle, "utf8");

console.log(`Mock workbench data written to ${outputPath}`);
