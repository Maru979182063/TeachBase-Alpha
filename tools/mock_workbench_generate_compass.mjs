/**
 * 用途：
 * - 根据 mock 工作台演示数据生成面向管理层的摘要罗盘。
 * - 这个脚本专注展示，不应和原始演示数据组装混在一起。
 */

import fs from "fs";
import path from "path";
import { createRequire } from "module";

const require = createRequire("C:/Users/EDY/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/");
const PptxGenJS = require("pptxgenjs");

const payloadArgIndex = process.argv.indexOf("--payload");
const outputArgIndex = process.argv.indexOf("--output");

if (payloadArgIndex === -1 || outputArgIndex === -1) {
  process.exit(1);
}

const payload = JSON.parse(fs.readFileSync(process.argv[payloadArgIndex + 1], "utf8"));
const outputPath = process.argv[outputArgIndex + 1];
const lesson = payload.lesson;
const splitLesson = payload.splitLesson;
const reviewItems = payload.reviewItems || [];

const pptx = new PptxGenJS();
pptx.layout = "LAYOUT_WIDE";
pptx.author = "Codex";
pptx.company = "领世培优";
pptx.subject = "讲义拆分导出罗盘";
pptx.title = `${lesson.lesson_title} 导出罗盘`;
pptx.lang = "zh-CN";
pptx.theme = {
  headFontFace: "Microsoft YaHei",
  bodyFontFace: "Microsoft YaHei",
  lang: "zh-CN",
};

const colors = {
  blue: "2D6DF6",
  blueSoft: "EDF4FF",
  line: "D8E4F2",
  text: "1D2736",
  muted: "6D7A8C",
  green: "1EA76A",
  orange: "F59B23",
  red: "F05555",
};

function addTitle(slide, title, subtitle = "") {
  slide.addText(title, {
    x: 0.6,
    y: 0.45,
    w: 8.6,
    h: 0.45,
    fontFace: "Microsoft YaHei",
    fontSize: 24,
    bold: true,
    color: colors.text,
  });
  if (subtitle) {
    slide.addText(subtitle, {
      x: 0.62,
      y: 0.92,
      w: 9.2,
      h: 0.28,
      fontFace: "Microsoft YaHei",
      fontSize: 10.5,
      color: colors.muted,
    });
  }
}

function addCard(slide, x, y, w, h, title, value, color = colors.blue) {
  slide.addShape(pptx.ShapeType.roundRect, {
    x,
    y,
    w,
    h,
    rectRadius: 0.08,
    line: { color: colors.line, pt: 1 },
    fill: { color: "FFFFFF" },
  });
  slide.addText(title, {
    x: x + 0.18,
    y: y + 0.15,
    w: w - 0.3,
    h: 0.25,
    fontSize: 10,
    color: colors.muted,
  });
  slide.addText(String(value), {
    x: x + 0.18,
    y: y + 0.45,
    w: w - 0.3,
    h: 0.38,
    fontSize: 22,
    bold: true,
    color,
  });
}

function versionStats() {
  const stats = { 基础版: 0, 常用版: 0, 进阶版: 0 };
  for (const q of splitLesson.questions || []) {
    for (const tag of q.effectiveVersionTags || q.versionTags || []) {
      if (stats[tag] !== undefined) stats[tag] += 1;
    }
  }
  return stats;
}

const slide1 = pptx.addSlide();
addTitle(slide1, "讲义拆分导出罗盘", `${lesson.grade} · ${lesson.season} · ${lesson.lesson_title}`);
slide1.addShape(pptx.ShapeType.roundRect, {
  x: 0.62,
  y: 1.4,
  w: 11.9,
  h: 1.45,
  rectRadius: 0.08,
  line: { color: colors.blue, pt: 1.4 },
  fill: { color: "FFFFFF" },
});
slide1.addText("本次导出聚焦于“按课次 + 最小知识点”的讲义重组。文件会按基础版 / 常用版 / 进阶版输出，同时保留教师版与学生版两种落地形态。", {
  x: 0.88,
  y: 1.76,
  w: 9.8,
  h: 0.6,
  fontSize: 17,
  color: colors.text,
  breakLine: false,
});
addCard(slide1, 0.7, 3.35, 2.7, 1.15, "总题块数", splitLesson.question_count || splitLesson.questions.length, colors.blue);
addCard(slide1, 3.65, 3.35, 2.7, 1.15, "知识点数", lesson.knowledge_point_count, colors.green);
addCard(slide1, 6.6, 3.35, 2.7, 1.15, "视觉已审", splitLesson.auditSummary?.reviewedCount || 0, colors.orange);
addCard(slide1, 9.55, 3.35, 2.7, 1.15, "待人工关注", splitLesson.auditSummary?.pendingCount || reviewItems.length, colors.red);

const slide2 = pptx.addSlide();
addTitle(slide2, "课次底盘", "把讲义身份、来源与课程目标收束成一张底盘页，适合给老师快速对焦。");
slide2.addShape(pptx.ShapeType.roundRect, {
  x: 0.65,
  y: 1.3,
  w: 4.2,
  h: 4.9,
  rectRadius: 0.06,
  line: { color: colors.line, pt: 1 },
  fill: { color: "FFFFFF" },
});
slide2.addText(
  [
    { text: "学段：", options: { bold: true } },
    { text: lesson.stage },
    { text: "\n年级：", options: { bold: true } },
    { text: lesson.grade },
    { text: "\n季节：", options: { bold: true } },
    { text: lesson.season },
    { text: "\n讲次：", options: { bold: true } },
    { text: `第${lesson.lesson_no}讲` },
    { text: "\n来源：", options: { bold: true } },
    { text: lesson.source_pdf_name },
  ],
  {
    x: 0.92,
    y: 1.62,
    w: 3.5,
    h: 3.7,
    fontSize: 15,
    color: colors.text,
    breakLine: true,
  }
);
slide2.addShape(pptx.ShapeType.roundRect, {
  x: 5.1,
  y: 1.3,
  w: 7.45,
  h: 4.9,
  rectRadius: 0.06,
  line: { color: colors.line, pt: 1 },
  fill: { color: "FFFFFF" },
});
slide2.addText("课程目标", {
  x: 5.38,
  y: 1.58,
  w: 2,
  h: 0.3,
  fontSize: 16,
  bold: true,
  color: colors.text,
});
slide2.addText(
  (lesson.objectives || "")
    .split(/\n+/)
    .filter(Boolean)
    .map((line) => `• ${line.trim()}`)
    .join("\n"),
  {
    x: 5.38,
    y: 2.02,
    w: 6.55,
    h: 3.7,
    fontSize: 14,
    color: colors.text,
    breakLine: true,
    valign: "top",
  }
);

const slide3 = pptx.addSlide();
addTitle(slide3, "知识树与版本分布", "这页专门展示当前课次的结构根茎，以及三个版本的题量差异。");
slide3.addShape(pptx.ShapeType.roundRect, {
  x: 0.65,
  y: 1.28,
  w: 7.1,
  h: 5.35,
  rectRadius: 0.06,
  line: { color: colors.line, pt: 1 },
  fill: { color: "FFFFFF" },
});
slide3.addText("知识树摘要", {
  x: 0.95,
  y: 1.56,
  w: 2.4,
  h: 0.3,
  fontSize: 16,
  bold: true,
  color: colors.text,
});
let treeY = 2.0;
for (const module of splitLesson.tree || []) {
  slide3.addText(`• ${module.module}`, {
    x: 0.98,
    y: treeY,
    w: 5.9,
    h: 0.25,
    fontSize: 14,
    bold: true,
    color: colors.blue,
  });
  treeY += 0.35;
  for (const item of module.items || []) {
    slide3.addText(`- ${item}`, {
      x: 1.25,
      y: treeY,
      w: 5.8,
      h: 0.23,
      fontSize: 11.5,
      color: colors.text,
    });
    treeY += 0.26;
    if (treeY > 5.95) break;
  }
  treeY += 0.12;
  if (treeY > 5.95) break;
}
slide3.addShape(pptx.ShapeType.roundRect, {
  x: 8.02,
  y: 1.28,
  w: 4.55,
  h: 5.35,
  rectRadius: 0.06,
  line: { color: colors.line, pt: 1 },
  fill: { color: "FFFFFF" },
});
slide3.addText("版本题量", {
  x: 8.32,
  y: 1.56,
  w: 2.2,
  h: 0.3,
  fontSize: 16,
  bold: true,
  color: colors.text,
});
const stats = versionStats();
const bars = [
  ["基础版", stats["基础版"], colors.blue],
  ["常用版", stats["常用版"], colors.orange],
  ["进阶版", stats["进阶版"], colors.green],
];
let barY = 2.1;
const maxValue = Math.max(...bars.map((item) => item[1] || 1), 1);
for (const [label, value, color] of bars) {
  slide3.addText(label, { x: 8.34, y: barY, w: 1.0, h: 0.22, fontSize: 12, color: colors.text });
  slide3.addShape(pptx.ShapeType.roundRect, {
    x: 8.34,
    y: barY + 0.28,
    w: 3.25,
    h: 0.24,
    rectRadius: 0.06,
    line: { color: "EAF1FB", pt: 0.5 },
    fill: { color: "F4F7FC" },
  });
  slide3.addShape(pptx.ShapeType.roundRect, {
    x: 8.34,
    y: barY + 0.28,
    w: Math.max(0.35, (value / maxValue) * 3.25),
    h: 0.24,
    rectRadius: 0.06,
    line: { color, pt: 0.5 },
    fill: { color },
  });
  slide3.addText(String(value), { x: 11.75, y: barY + 0.13, w: 0.45, h: 0.22, fontSize: 12, bold: true, color });
  barY += 1.08;
}

const slide4 = pptx.addSlide();
addTitle(slide4, "风险关注点", "把需要人工盯一下的题块提前捞出来，演示时会很直观。");
const risky = (reviewItems.length ? reviewItems : (splitLesson.questions || []).filter((q) => q.risk !== "低风险")).slice(0, 4);
let cardX = 0.72;
let cardY = 1.45;
for (let i = 0; i < risky.length; i += 1) {
  const item = risky[i];
  const question = item.cropPath ? item : (splitLesson.questions || []).find((q) => q.id === item.questionId) || item;
  slide4.addShape(pptx.ShapeType.roundRect, {
    x: cardX,
    y: cardY,
    w: 5.75,
    h: 2.18,
    rectRadius: 0.06,
    line: { color: colors.line, pt: 1 },
    fill: { color: "FFFFFF" },
  });
  slide4.addText(`${question.localNumber || item.queueNo || ""}｜${question.checkpoint || item.title || ""}`, {
    x: cardX + 0.2,
    y: cardY + 0.16,
    w: 3.8,
    h: 0.28,
    fontSize: 12.5,
    bold: true,
    color: colors.text,
  });
  slide4.addText(question.risk || item.risk || "待审", {
    x: cardX + 4.7,
    y: cardY + 0.16,
    w: 0.7,
    h: 0.22,
    fontSize: 11,
    bold: true,
    color: question.risk === "高风险" ? colors.red : colors.orange,
    align: "right",
  });
  if (question.cropPath && fs.existsSync(question.cropPath)) {
    slide4.addImage({ path: question.cropPath, x: cardX + 0.2, y: cardY + 0.52, w: 2.0, h: 1.2, contain: true });
  }
  slide4.addText((question.reviewNote || (item.tags || []).join("；") || "建议人工再确认一次视觉边界。").slice(0, 80), {
    x: cardX + 2.4,
    y: cardY + 0.58,
    w: 3.05,
    h: 1.0,
    fontSize: 10.5,
    color: colors.text,
    breakLine: true,
    valign: "mid",
  });
  if (cardX > 6.5) {
    cardX = 0.72;
    cardY += 2.45;
  } else {
    cardX = 6.72;
  }
}

await pptx.writeFile({ fileName: outputPath });
