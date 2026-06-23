/**
 * Purpose:
 * - Calls the Doubao model to place visual lesson material into candidate curriculum buckets.
 * - Keep request shaping and result packaging together here so prompt changes are auditable.
 */

import fs from "node:fs/promises";
import path from "node:path";

const DEFAULT_MODEL = "doubao-seed-2-0-pro-260215";
const API_URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions";

function parseArgs(argv) {
  const args = {};
  for (let i = 0; i < argv.length; i += 1) {
    const key = argv[i];
    if (!key.startsWith("--")) continue;
    const next = argv[i + 1];
    if (!next || next.startsWith("--")) {
      args[key.slice(2)] = true;
    } else {
      args[key.slice(2)] = next;
      i += 1;
    }
  }
  return args;
}

function normalizeText(text) {
  return String(text || "").replace(/\s+/g, " ").trim();
}

function extractJsonObject(text) {
  const raw = String(text || "").trim().replace(/^```(?:json)?\s*/i, "").replace(/\s*```$/, "");
  try {
    return JSON.parse(raw);
  } catch {}

  const start = raw.indexOf("{");
  if (start < 0) throw new Error("json_object_not_found");
  let depth = 0;
  let inString = false;
  let escape = false;
  for (let i = start; i < raw.length; i += 1) {
    const ch = raw[i];
    if (inString) {
      if (escape) escape = false;
      else if (ch === "\\") escape = true;
      else if (ch === '"') inString = false;
      continue;
    }
    if (ch === '"') inString = true;
    else if (ch === "{") depth += 1;
    else if (ch === "}") {
      depth -= 1;
      if (depth === 0) return JSON.parse(raw.slice(start, i + 1));
    }
  }
  throw new Error("json_object_not_closed");
}

async function readJson(filePath) {
  return JSON.parse(await fs.readFile(filePath, "utf8"));
}

async function ensureDir(dirPath) {
  await fs.mkdir(dirPath, { recursive: true });
}

function buildCandidateLine(point) {
  return `${point.knowledge_id}|${point.level_2_module}|${point.level_3_min_knowledge_point}`;
}

function buildPrompt(lesson, knowledgePoints, question) {
  const candidateLines = knowledgePoints.map(buildCandidateLine).join("；");
  return [
    `题目来自${lesson.stage}数学/${lesson.grade}/${lesson.season}/${lesson.lesson_title}。`,
    `候选知识点：${candidateLines}。`,
    `题目OCR：${normalizeText(question.text_preview || "")}。`,
    `讲义标签：${question.checkpoint || ""}；组件：${question.component_label || ""}；题号：${question.local_number || ""}。`,
    "请给出层级判断。",
    '只输出json：{"stage":"初中|高中","stage_reason":"<=40字","grade":"...","grade_reason":"<=40字","lesson_id":"...","lesson_reason":"<=40字","top3":["knowledge_id1","knowledge_id2","knowledge_id3"],"confidence":"high|medium|low","review_status":"accepted_candidate|needs_teacher_review","reason":"<=80字"}',
  ].join("");
}

async function callDoubao({ apiKey, model, prompt }) {
  const payload = {
    model,
    temperature: 0.1,
    messages: [
      { role: "system", content: "你是数学教研助手，只输出JSON。" },
      { role: "user", content: prompt },
    ],
  };

  const response = await fetch(API_URL, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${apiKey}`,
    },
    body: JSON.stringify(payload),
  });

  const text = await response.text();
  if (!response.ok) {
    throw new Error(`http_${response.status}: ${text}`);
  }
  const data = JSON.parse(text);
  const content = data?.choices?.[0]?.message?.content || "";
  return { raw: data, parsed: extractJsonObject(content) };
}

async function callDoubaoWithRetry({ apiKey, model, prompt, retries = 3, backoffMs = 1600 }) {
  let lastError = null;
  for (let attempt = 1; attempt <= retries; attempt += 1) {
    try {
      return await callDoubao({ apiKey, model, prompt });
    } catch (error) {
      lastError = error;
      if (attempt >= retries) break;
      await new Promise((resolve) => setTimeout(resolve, backoffMs * attempt));
    }
  }
  throw lastError || new Error("unknown_fetch_failure");
}

function toTop3Records(parsed, pointMap) {
  const top3 = Array.isArray(parsed.top3) ? parsed.top3.slice(0, 3) : [];
  return top3.map((knowledgeId, index) => {
    const point = pointMap.get(knowledgeId) || {};
    return {
      rank: index + 1,
      knowledge_id: knowledgeId,
      grade: parsed.grade || point.grade || "",
      lesson_title: point.lesson_title || "",
      module: point.level_2_module || "",
      min_knowledge_point: point.level_3_min_knowledge_point || "",
      confidence: index === 0 ? parsed.confidence || "medium" : "medium",
      teacher_review_note:
        index === 0
          ? parsed.reason || "模型给出首选落位。"
          : `作为备选保留，便于教师复核同课次内的相近知识点。`,
    };
  });
}

function buildStructuredPlacement(parsed, lesson, question, pointMap) {
  const top3Records = toTop3Records(parsed, pointMap);
  const stagePrediction = parsed.stage || lesson.stage;
  const gradePrediction = parsed.grade || lesson.grade;
  const lessonPrediction = parsed.lesson_id || lesson.lesson_id;
  const fineCandidates = top3Records.map((item, index) => ({
    knowledge_id: item.knowledge_id,
    module: item.module,
    min_knowledge_point: item.min_knowledge_point,
    confidence: index === 0 ? parsed.confidence || "medium" : "medium",
    reason:
      index === 0
        ? parsed.reason || "模型将其作为首选最小知识点。"
        : `保留为同课次内的相近备选知识点。`,
  }));

  const topModule = fineCandidates[0]?.module || "";

  return {
    question_id: question.question_id,
    question_reading: {
      core_objects: [question.checkpoint || "题块", question.component_label || "题目"],
      conditions: [
        `讲义标签：${question.checkpoint || "未标注"}`,
        `组件：${question.component_label || "未标注"}`,
        `OCR摘要：${normalizeText(question.text_preview || "").slice(0, 140)}`,
      ],
      asked_result: "将题目落到当前课次的最小知识点",
      visual_dependency: "formula",
    },
    layered_trace: {
      stage: {
        prediction: stagePrediction,
        confidence: parsed.confidence || "medium",
        reason: parsed.stage_reason || `模型判定该题属于${stagePrediction}数学范畴。`,
      },
      grade: {
        top_candidates: [
          {
            grade: gradePrediction,
            confidence: parsed.confidence || "medium",
            reason: parsed.grade_reason || `模型判定该题更贴合${gradePrediction}内容边界。`,
          },
        ],
      },
      lesson: {
        top_candidates: [
          {
            lesson_id: lessonPrediction,
            lesson_title: lesson.lesson_title,
            confidence: parsed.confidence || "medium",
            reason: parsed.lesson_reason || `模型判定该题落在《${lesson.lesson_title}》课次内。`,
          },
        ],
      },
      module: {
        top_candidates: topModule
          ? [
              {
                module: topModule,
                confidence: parsed.confidence || "medium",
                reason: `首选知识点位于模块「${topModule}」。`,
              },
            ]
          : [],
      },
      fine_point: {
        top_candidates: fineCandidates,
      },
    },
    final_top3: top3Records,
    review_status: parsed.review_status || "needs_teacher_review",
  };
}

function buildCompactRecord(question, structured) {
  const top1 = structured.final_top3?.[0] || {};
  return {
    question_id: question.question_id,
    checkpoint: question.checkpoint || "",
    status: "ok",
    top1_knowledge_id: top1.knowledge_id || "",
    top1_module: top1.module || "",
    top1_min_knowledge_point: top1.min_knowledge_point || "",
    top1_confidence: top1.confidence || "",
    review_status: structured.review_status || "",
  };
}

async function writeSummary(outPath, lesson, knowledgePoints, records) {
  const pointMap = new Map(knowledgePoints.map((point) => [point.knowledge_id, point]));
  const counter = new Map();
  const needsReview = [];

  for (const record of records) {
    const top1 = record.placement?.final_top3?.[0];
    if (top1?.knowledge_id) {
      counter.set(top1.knowledge_id, (counter.get(top1.knowledge_id) || 0) + 1);
    }
    if (record.placement?.review_status !== "accepted_candidate") {
      needsReview.push(record);
    }
  }

  const lines = [
    "# 豆包落位结果\n\n",
    `- 课次：${lesson.lesson_title}（${lesson.lesson_id}）\n`,
    `- 题量：${records.length}\n`,
    `- 需要教师复核：${needsReview.length}\n\n`,
    "## Top1 分布\n\n",
  ];

  [...counter.entries()]
    .sort((a, b) => b[1] - a[1])
    .forEach(([knowledgeId, count]) => {
      const point = pointMap.get(knowledgeId) || {};
      lines.push(`- ${knowledgeId} | ${point.level_2_module || ""} / ${point.level_3_min_knowledge_point || ""} ：${count}题\n`);
    });

  lines.push("\n## 复核清单\n\n");
  if (!needsReview.length) {
    lines.push("- 本轮无强制复核题。\n");
  } else {
    for (const record of needsReview) {
      const top1 = record.placement?.final_top3?.[0] || {};
      lines.push(`- ${record.question_id} | ${record.checkpoint} | ${top1.knowledge_id || ""} | ${top1.teacher_review_note || ""}\n`);
    }
  }

  await fs.writeFile(outPath, lines.join(""), "utf8");
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const apiKey = args["api-key"] || process.env.ARK_API_KEY || "";
  if (!apiKey) throw new Error("missing_api_key");

  const splitJson = args["split-json"];
  const knowledgeJson = args["knowledge-json"];
  const lessonsJson = args["lessons-json"];
  const lessonId = args["lesson-id"];
  const outDir = args["out-dir"];
  const model = args.model || DEFAULT_MODEL;
  const limit = Number(args.limit || 0);
  const sleepMs = Number(args["sleep-ms"] || 250);
  const retries = Number(args.retries || 3);
  const onlyQuestionIds = String(args["question-ids"] || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);

  if (!splitJson || !knowledgeJson || !lessonsJson || !lessonId || !outDir) {
    throw new Error("missing_required_args");
  }

  await ensureDir(outDir);
  const rawDir = path.join(outDir, "raw");
  await ensureDir(rawDir);

  const splitData = await readJson(splitJson);
  const allPoints = await readJson(knowledgeJson);
  const allLessons = await readJson(lessonsJson);
  const lesson = allLessons.find((item) => item.lesson_id === lessonId);
  if (!lesson) throw new Error(`lesson_not_found:${lessonId}`);
  const knowledgePoints = allPoints.filter((item) => item.lesson_id === lessonId);
  if (!knowledgePoints.length) throw new Error(`knowledge_points_not_found:${lessonId}`);
  const pointMap = new Map(knowledgePoints.map((point) => [point.knowledge_id, point]));

  let questions = limit > 0 ? splitData.questions.slice(0, limit) : splitData.questions;
  if (onlyQuestionIds.length) {
    const questionSet = new Set(onlyQuestionIds);
    questions = questions.filter((item) => questionSet.has(item.question_id));
  }
  const records = [];

  for (const question of questions) {
    const prompt = buildPrompt(lesson, knowledgePoints, question);
    try {
      const result = await callDoubaoWithRetry({ apiKey, model, prompt, retries });
      await fs.writeFile(
        path.join(rawDir, `${question.question_id}.response.json`),
        JSON.stringify(result.raw, null, 2),
        "utf8",
      );
      const placement = buildStructuredPlacement(result.parsed, lesson, question, pointMap);
      records.push({
        question_id: question.question_id,
        checkpoint: question.checkpoint || "",
        component_label: question.component_label || "",
        status: "ok",
        input_mode: "text_only",
        placement,
      });
    } catch (error) {
      records.push({
        question_id: question.question_id,
        checkpoint: question.checkpoint || "",
        component_label: question.component_label || "",
        status: "failed",
        input_mode: "text_only",
        error: String(error?.message || error),
      });
    }
    if (sleepMs > 0) {
      await new Promise((resolve) => setTimeout(resolve, sleepMs));
    }
  }

  const resultBundle = {
    lesson_id: lessonId,
    lesson_title: lesson.lesson_title,
    model,
    input_mode: "text_only",
    question_count: records.length,
    ok_count: records.filter((item) => item.status === "ok").length,
    failed_count: records.filter((item) => item.status !== "ok").length,
    records,
  };

  await fs.writeFile(path.join(outDir, "placement_results.json"), JSON.stringify(resultBundle, null, 2), "utf8");
  const compact = records
    .filter((item) => item.status === "ok")
    .map((item) => buildCompactRecord({ question_id: item.question_id, checkpoint: item.checkpoint }, item.placement));
  await fs.writeFile(path.join(outDir, "placement_compact.json"), JSON.stringify(compact, null, 2), "utf8");
  await writeSummary(path.join(outDir, "placement_summary.md"), lesson, knowledgePoints, records.filter((item) => item.status === "ok"));

  console.log(
    JSON.stringify(
      {
        out_dir: outDir,
        question_count: resultBundle.question_count,
        ok_count: resultBundle.ok_count,
        failed_count: resultBundle.failed_count,
      },
      null,
      2,
    ),
  );
}

main().catch((error) => {
  console.error(String(error?.stack || error));
  process.exitCode = 1;
});
