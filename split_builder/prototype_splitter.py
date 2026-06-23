# Purpose:
# - Provides the early full-document splitter for lesson structure, goals, and answers.
# - Later pipelines still rely on the heuristics prototyped here, so keep behavior notes close.

import argparse
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pdfplumber


SECTION_RE = re.compile(r"^考点\s*(\d+)\s*[:：]\s*(.+)$")
QUESTION_RE = re.compile(r"^(\d{1,2})[．.、]\s*(.*)$")
ANSWER_MARKER_RE = re.compile(
    r"(【答案】|【解析】|【分析】|【详解】|【解答】|【解题思路】|【解答过程】|【点评】)"
)


@dataclass
class ParsedTask:
    section_no: str
    section_title: str
    question_no: str
    lines: List[str] = field(default_factory=list)
    pages: List[int] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"s{self.section_no}_q{self.question_no}"

    @property
    def raw_text(self) -> str:
        return "\n".join(self.lines).strip()


@dataclass
class ParsedSection:
    section_no: str
    title: str
    page_start: int
    intro_lines: List[str] = field(default_factory=list)
    tasks: List[ParsedTask] = field(default_factory=list)

    @property
    def section_id(self) -> str:
        return f"section_{self.section_no}"


@dataclass
class ParsedDoc:
    path: str
    page_count: int
    intro_lines: List[str]
    sections: List[ParsedSection]


def clean_line(line: str) -> str:
    line = line.replace("\u200b", "")
    line = re.sub(r"[ \t]+", " ", line)
    return line.strip()


def extract_lines(pdf_path: Path) -> Tuple[int, List[Tuple[int, str]]]:
    rows: List[Tuple[int, str]] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        page_count = len(pdf.pages)
        for page_index, page in enumerate(pdf.pages, start=1):
            text = page.extract_text(x_tolerance=1, y_tolerance=3) or ""
            for raw in text.splitlines():
                line = clean_line(raw)
                if not line:
                    continue
                if line == str(page_index):
                    continue
                rows.append((page_index, line))
    return page_count, rows


def flush_task(current: Optional[ParsedTask], current_section: Optional[ParsedSection]) -> None:
    if current is not None and current_section is not None and current.raw_text:
        current_section.tasks.append(current)


# Parsing stage: converts PDF text into sections and tasks while preserving page provenance.
def parse_doc(pdf_path: Path) -> ParsedDoc:
    page_count, rows = extract_lines(pdf_path)
    intro_lines: List[str] = []
    sections: List[ParsedSection] = []
    current_section: Optional[ParsedSection] = None
    current_task: Optional[ParsedTask] = None

    for page, line in rows:
        section_match = SECTION_RE.match(line)
        if section_match:
            flush_task(current_task, current_section)
            current_task = None
            current_section = ParsedSection(
                section_no=section_match.group(1),
                title=section_match.group(2).strip(),
                page_start=page,
            )
            sections.append(current_section)
            continue

        question_match = QUESTION_RE.match(line)
        if question_match and current_section is not None:
            flush_task(current_task, current_section)
            current_task = ParsedTask(
                section_no=current_section.section_no,
                section_title=current_section.title,
                question_no=question_match.group(1),
                lines=[line],
                pages=[page],
            )
            continue

        if current_section is None:
            intro_lines.append(line)
        elif current_task is None:
            current_section.intro_lines.append(line)
        else:
            current_task.lines.append(line)
            if page not in current_task.pages:
                current_task.pages.append(page)

    flush_task(current_task, current_section)
    return ParsedDoc(str(pdf_path), page_count, intro_lines, sections)


def split_teacher_answer(raw_text: str) -> Tuple[str, Dict[str, str]]:
    match = ANSWER_MARKER_RE.search(raw_text)
    if not match:
        return raw_text.strip(), {}

    stem = raw_text[: match.start()].strip()
    rest = raw_text[match.start() :]
    parts = ANSWER_MARKER_RE.split(rest)
    blocks: Dict[str, List[str]] = {}
    current_marker: Optional[str] = None
    for part in parts:
        if not part:
            continue
        if ANSWER_MARKER_RE.fullmatch(part):
            current_marker = part.strip("【】")
            blocks.setdefault(current_marker, [])
        elif current_marker:
            blocks[current_marker].append(part.strip())

    return stem, {key: "\n".join(value).strip() for key, value in blocks.items()}


def infer_lesson_title(intro_lines: List[str], fallback: str) -> str:
    for line in intro_lines:
        if line and not line.startswith("领世"):
            return line
    return fallback


def infer_goals(intro_lines: List[str]) -> List[str]:
    goals: List[str] = []
    current: Optional[str] = None
    for line in intro_lines[1:]:
        if re.match(r"^\d+、(能够|掌握|了解|理解|会|能)", line):
            if current:
                goals.append(current)
            current = line
            continue
        if current and not re.match(r"^\d+、", line):
            current += line
            continue
        if current and re.match(r"^\d+、", line):
            goals.append(current)
            current = None
            break
    if current:
        goals.append(current)
    return goals[:5]


def infer_risks(text: str) -> List[str]:
    risks: List[str] = []
    if re.search(r"[]|√|≤|≥|[a-zA-Z]\s*[²³]", text):
        risks.append("formula_normalization")
    if re.search(r"如图|图中|作图|几何|三角形|圆", text):
        risks.append("visual_asset_required")
    if re.search(r"求证|证明", text):
        risks.append("proof_item")
    if "【答案】" in text or "【解析】" in text or "【详解】" in text:
        risks.append("answer_layer")
    return sorted(set(risks))


def infer_tier(section_no: str, question_no: str, text: str) -> Tuple[str, str, str]:
    section = int(section_no)
    q = int(question_no)
    if re.search(r"参数|恒成立|综合|求证|证明", text):
        return "advanced", "weak", "far"
    if section >= 3 or re.search(r"函数|最大值|最小值|配凑|消元|整体|若", text):
        return "standard", "medium", "near"
    if section == 1 and q <= 4:
        return "basic", "strong", "prototype"
    return "standard", "medium", "near"


def normalize_answer(answer_raw: str, stem: str) -> str:
    answer = re.sub(r"\s+", " ", answer_raw).strip()
    is_choice = "（ ）" in stem or re.search(r"\bA[．.]", stem)
    if is_choice:
        match = re.match(r"^([A-D])(\b|[ .。．])", answer)
        if match:
            return match.group(1)
    return answer_raw.strip()


def task_map(doc: ParsedDoc) -> Dict[str, ParsedTask]:
    return {task.key: task for section in doc.sections for task in section.tasks}


# Assembly stage: merges teacher and student views into the canonical split JSON shape.
def build_split(teacher_doc: ParsedDoc, student_doc: ParsedDoc, args: argparse.Namespace) -> Dict:
    teacher_tasks = task_map(teacher_doc)
    student_tasks = task_map(student_doc)
    all_keys = sorted(set(teacher_tasks) | set(student_tasks), key=lambda x: [int(v) for v in re.findall(r"\d+", x)])

    lesson_title = infer_lesson_title(student_doc.intro_lines or teacher_doc.intro_lines, args.lesson_title)
    goals = infer_goals(student_doc.intro_lines or teacher_doc.intro_lines)
    lesson_id = re.sub(r"\W+", "_", f"{args.subject}_{args.grade}_{args.lesson_no}_{lesson_title}")[:80]

    nodes: List[Dict] = []
    tasks: List[Dict] = []

    nodes.append(
        {
            "node_id": "lesson_root",
            "parent_id": None,
            "order_index": 0,
            "node_type": "lesson",
            "phase": "lesson_meta",
            "title": lesson_title,
            "text": "",
            "page_range": [1],
            "visibility": "student_all",
            "risk_flags": [],
        }
    )

    if goals:
        nodes.append(
            {
                "node_id": "learning_objectives",
                "parent_id": "lesson_root",
                "order_index": 1,
                "node_type": "learning_objective",
                "phase": "learning_objectives",
                "title": "课程目标",
                "text": "\n".join(goals),
                "page_range": [1],
                "visibility": "student_all",
                "risk_flags": [],
            }
        )

    intro_text = "\n".join(student_doc.intro_lines[1:]).strip()
    nodes.append(
        {
            "node_id": "knowledge_outline",
            "parent_id": "lesson_root",
            "order_index": 2,
            "node_type": "knowledge_block",
            "phase": "knowledge_main",
            "title": "知识主干",
            "text": intro_text,
            "page_range": [1],
            "visibility": "student_all",
            "risk_flags": infer_risks(intro_text),
        }
    )

    section_lookup = {section.section_no: section for section in student_doc.sections}
    if not section_lookup:
        section_lookup = {section.section_no: section for section in teacher_doc.sections}

    for order, section in enumerate(section_lookup.values(), start=10):
        nodes.append(
            {
                "node_id": f"section_{section.section_no}",
                "parent_id": "lesson_root",
                "order_index": order,
                "node_type": "exam_point",
                "phase": "method_path",
                "title": f"考点 {section.section_no}：{section.title}",
                "text": "\n".join(section.intro_lines).strip(),
                "page_range": [section.page_start],
                "visibility": "student_all",
                "risk_flags": infer_risks(section.title + "\n" + "\n".join(section.intro_lines)),
            }
        )

    unmatched_teacher: List[str] = []
    unmatched_student: List[str] = []

    for key in all_keys:
        teacher_task = teacher_tasks.get(key)
        student_task = student_tasks.get(key)
        source_task = student_task or teacher_task
        if source_task is None:
            continue

        teacher_stem = ""
        answer_blocks: Dict[str, str] = {}
        if teacher_task:
            teacher_stem, answer_blocks = split_teacher_answer(teacher_task.raw_text)
        if student_task:
            student_stem = student_task.raw_text
        else:
            student_stem = teacher_stem
            unmatched_teacher.append(key)
        if teacher_task is None:
            unmatched_student.append(key)

        answer_raw = answer_blocks.get("答案", "")
        answer = normalize_answer(answer_raw, student_stem or teacher_stem)
        explanation_parts = [
            value
            for marker, value in answer_blocks.items()
            if marker in {"解析", "分析", "详解", "解答", "解题思路", "解答过程", "点评"}
        ]
        explanation = "\n\n".join(part for part in explanation_parts if part)
        if answer:
            answer_status = "explicit_answer"
        elif explanation:
            answer_status = "solution_only"
        else:
            answer_status = "missing_or_unrecognized"
        combined_text = "\n".join([student_stem, teacher_stem, answer, explanation])
        tier, support, transfer = infer_tier(source_task.section_no, source_task.question_no, combined_text)
        risk_flags = infer_risks(combined_text)
        if student_task and ANSWER_MARKER_RE.search(student_task.raw_text):
            risk_flags.append("possible_answer_leakage")

        tasks.append(
            {
                "task_id": key,
                "section_id": f"section_{source_task.section_no}",
                "question_no": source_task.question_no,
                "student_stem": student_stem,
                "teacher_stem": teacher_stem,
                "answer": answer,
                "answer_raw": answer_raw,
                "answer_status": answer_status,
                "explanation": explanation,
                "source_pages": {
                    "student": student_task.pages if student_task else [],
                    "teacher": teacher_task.pages if teacher_task else [],
                },
                "difficulty_tier": tier,
                "support_level": support,
                "transfer_level": transfer,
                "visibility": "student_all",
                "alignment_status": "aligned" if teacher_task and student_task else "needs_review",
                "risk_flags": sorted(set(risk_flags)),
            }
        )

    quality = {
        "teacher_pages": teacher_doc.page_count,
        "student_pages": student_doc.page_count,
        "section_count": len(section_lookup),
        "task_count": len(tasks),
        "aligned_task_count": sum(1 for task in tasks if task["alignment_status"] == "aligned"),
        "unmatched_teacher_tasks": unmatched_teacher,
        "unmatched_student_tasks": unmatched_student,
        "audit_notes": [
            "首版样例使用规则拆分，后续需接入模型复核题型、分层和跨页边界。",
            "公式符号来自 PDF 文本层，结构可用但数学排版需资产/公式插件进一步标准化。",
        ],
    }

    return {
        "schema_version": "0.1",
        "doc_pair": {
            "subject": args.subject,
            "stage": args.stage,
            "grade": args.grade,
            "season": args.season,
            "lesson_no": args.lesson_no,
            "teacher_path": teacher_doc.path,
            "student_path": student_doc.path,
            "pair_confidence": 0.92,
        },
        "lesson": {
            "lesson_id": lesson_id,
            "title": lesson_title,
            "phase_order": [
                "lesson_meta",
                "learning_objectives",
                "knowledge_main",
                "method_path",
                "example_or_task",
                "student_practice",
                "teacher_feedback",
            ],
            "learning_goals": goals,
        },
        "nodes": nodes,
        "tasks": tasks,
        "quality": quality,
    }


# Review stage: writes a human-readable markdown summary of the parsed split.
def write_review(split: Dict, output_path: Path) -> None:
    lines: List[str] = []
    lesson = split["lesson"]
    quality = split["quality"]
    lines.append(f"# 拆分样例复核摘要：{lesson['title']}")
    lines.append("")
    lines.append("## 基本结果")
    lines.append("")
    lines.append(f"- 教师版页数：{quality['teacher_pages']}")
    lines.append(f"- 学生版页数：{quality['student_pages']}")
    lines.append(f"- 识别考点数：{quality['section_count']}")
    lines.append(f"- 识别题块数：{quality['task_count']}")
    lines.append(f"- 教师/学生对齐题块：{quality['aligned_task_count']}")
    lines.append("")
    lines.append("## 考点结构")
    lines.append("")
    for node in split["nodes"]:
        if node["node_type"] == "exam_point":
            count = sum(1 for task in split["tasks"] if task["section_id"] == node["node_id"])
            lines.append(f"- {node['title']}：{count} 题")
    lines.append("")
    lines.append("## 分层统计")
    lines.append("")
    counts: Dict[str, int] = {}
    for task in split["tasks"]:
        counts[task["difficulty_tier"]] = counts.get(task["difficulty_tier"], 0) + 1
    for tier in ["basic", "standard", "advanced"]:
        lines.append(f"- {tier}：{counts.get(tier, 0)}")
    lines.append("")
    lines.append("## 前 8 个题块样例")
    lines.append("")
    for task in split["tasks"][:8]:
        stem = re.sub(r"\s+", " ", task["student_stem"])[:160]
        answer = re.sub(r"\s+", " ", task["answer"])[:80] if task["answer"] else task["answer_status"]
        lines.append(
            f"- {task['task_id']} | {task['difficulty_tier']} | {task['alignment_status']} | 答案：{answer} | 题干：{stem}"
        )
    lines.append("")
    lines.append("## 需要人工/模型复核")
    lines.append("")
    for note in quality["audit_notes"]:
        lines.append(f"- {note}")
    flagged = [task for task in split["tasks"] if task["risk_flags"]]
    lines.append(f"- 带风险标记题块：{len(flagged)}")
    output_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--teacher", required=True)
    parser.add_argument("--student", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--subject", default="数学")
    parser.add_argument("--stage", default="高中")
    parser.add_argument("--grade", default="高一")
    parser.add_argument("--season", default="暑假")
    parser.add_argument("--lesson-no", default="第6讲")
    parser.add_argument("--lesson-title", default="基本不等式")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    teacher_doc = parse_doc(Path(args.teacher))
    student_doc = parse_doc(Path(args.student))
    split = build_split(teacher_doc, student_doc, args)

    json_path = out_dir / "lesson_split.json"
    review_path = out_dir / "review_summary.md"
    json_path.write_text(json.dumps(split, ensure_ascii=False, indent=2), encoding="utf-8")
    write_review(split, review_path)
    print(f"wrote {json_path}")
    print(f"wrote {review_path}")


if __name__ == "__main__":
    main()
