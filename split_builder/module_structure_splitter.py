# Purpose:
# - Parses teacher handout text into lesson, task, and module nodes.
# - Risk flags emitted here help maintainers spot where rule-based splitting may be fragile.

import argparse
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import pdfplumber


ANSWER_MARKERS = ["【答案】", "【解析】", "【分析】", "【解答】", "【详解】", "【点评】", "【点拨】"]

EXPLICIT_SECTION_PATTERNS = [
    r"^知识导入$",
    r"^课程衔接$",
    r"^与.+差异性$",
    r"^【?思维导图】?$",
    r"^知识梳理$",
    r"^要点小测$",
    r"^例题讲解$",
    r"^强化训练$",
    r"^能力进阶$",
    r"^要点回顾$",
    r"^课堂小结$",
    r"^课程总结$",
    r"^课后练习$",
    r"^考点\s*\d+\s*[:：].+",
]

NUMBERED_SECTION_RE = re.compile(r"^[一二三四五六七八九十]+[、.．]\s*[^，。；：:]{2,28}$")
QUESTION_RE = re.compile(r"^(\d{1,3})[．.、]\s*(.+)")
OBJECTIVE_RE = re.compile(r"^\d+[、.．]\s*(能够|掌握|理解|了解|熟练|自由组合|致死|复等位|多对|学会|认识|会)")
PAGE_NUMBER_RE = re.compile(r"^\d{1,3}$")


@dataclass
class Line:
    page: int
    text: str


@dataclass
class Task:
    task_id: str
    parent_node_id: str
    question_no: str
    title: str
    page_start: int
    page_end: int
    stem: str
    answer: str = ""
    explanation: str = ""
    markers_found: List[str] = field(default_factory=list)
    risk_flags: List[str] = field(default_factory=list)
    confidence: float = 0.75


@dataclass
class Node:
    node_id: str
    parent_id: Optional[str]
    node_type: str
    phase: str
    title: str
    order_index: int
    page_start: int
    page_end: int
    text: str
    confidence: float
    risk_flags: List[str] = field(default_factory=list)


def clean_line(raw: str) -> str:
    text = raw.replace("\u200b", "").strip()
    text = re.sub(r"[ \t]+", " ", text)
    return text


def extract_lines(pdf_path: Path) -> Tuple[int, List[Line], Dict[int, int]]:
    lines: List[Line] = []
    images_by_page: Dict[int, int] = {}
    with pdfplumber.open(str(pdf_path)) as pdf:
        page_count = len(pdf.pages)
        for page_index, page in enumerate(pdf.pages, start=1):
            images_by_page[page_index] = len(page.images)
            text = page.extract_text(x_tolerance=1, y_tolerance=3) or ""
            for raw in text.splitlines():
                text_line = clean_line(raw)
                if not text_line or PAGE_NUMBER_RE.fullmatch(text_line):
                    continue
                lines.append(Line(page_index, text_line))
    return page_count, lines, images_by_page


def looks_like_section(text: str) -> bool:
    if any(re.match(pattern, text) for pattern in EXPLICIT_SECTION_PATTERNS):
        return True
    return bool(NUMBERED_SECTION_RE.match(text))


def phase_for_title(title: str) -> str:
    if "课程目标" in title:
        return "learning_objectives"
    if title in {"知识导入", "课程衔接"} or "差异性" in title:
        return "intro_or_prerequisite"
    if "思维导图" in title:
        return "mind_map"
    if "知识" in title or NUMBERED_SECTION_RE.match(title):
        return "knowledge_main"
    if title.startswith("考点"):
        return "exam_point"
    if "小测" in title:
        return "diagnostic_quiz"
    if "例题" in title:
        return "example_or_task"
    if "强化" in title or "训练" in title or "练习" in title:
        return "student_practice"
    if "能力" in title or "进阶" in title:
        return "extension"
    if "回顾" in title or "总结" in title or "小结" in title:
        return "summary_or_transfer"
    return "knowledge_main"


def risk_flags_for_text(text: str) -> List[str]:
    risks = []
    if any(symbol in text for symbol in ["", "", "", "", "", "", "", "", ""]):
        risks.append("formula_text_layer")
    if re.search(r"如图|图中|下图|表格|曲线|坐标系|遗传图解", text):
        risks.append("visual_or_table_asset")
    if re.search(r"证明|求证|实验设计|推理|探究", text):
        risks.append("reasoning_or_proof")
    if any(marker in text for marker in ANSWER_MARKERS):
        risks.append("teacher_answer_layer")
    return sorted(set(risks))


def split_answer_blocks(text: str) -> Tuple[str, str, str, List[str]]:
    positions = []
    for marker in ANSWER_MARKERS:
        index = text.find(marker)
        if index >= 0:
            positions.append((index, marker))
    if not positions:
        return text.strip(), "", "", []
    positions.sort()
    stem = text[: positions[0][0]].strip()
    blocks: Dict[str, str] = {}
    for idx, (start, marker) in enumerate(positions):
        end = positions[idx + 1][0] if idx + 1 < len(positions) else len(text)
        blocks[marker] = text[start + len(marker) : end].strip()
    answer = blocks.get("【答案】", "")
    explanation = "\n".join(value for key, value in blocks.items() if key != "【答案】" and value).strip()
    return stem, answer, explanation, [marker for _, marker in positions]


def compact_text(lines: Iterable[Line]) -> str:
    return "\n".join(line.text for line in lines).strip()


def build_node(
    node_id: str,
    parent_id: Optional[str],
    node_type: str,
    title: str,
    order_index: int,
    segment: List[Line],
    confidence: float,
) -> Node:
    text = compact_text(segment)
    if segment:
        page_start, page_end = segment[0].page, segment[-1].page
    else:
        page_start = page_end = 1
    return Node(
        node_id=node_id,
        parent_id=parent_id,
        node_type=node_type,
        phase=phase_for_title(title),
        title=title,
        order_index=order_index,
        page_start=page_start,
        page_end=page_end,
        text=text,
        confidence=confidence,
        risk_flags=risk_flags_for_text(text),
    )


def parse_tasks(parent_node_id: str, segment: List[Line]) -> List[Task]:
    tasks: List[Task] = []
    current_no: Optional[str] = None
    current_lines: List[Line] = []
    last_question_no = 0

    def flush() -> None:
        nonlocal current_no, current_lines
        if not current_no or not current_lines:
            return
        raw = compact_text(current_lines)
        stem, answer, explanation, markers = split_answer_blocks(raw)
        title = stem.splitlines()[0][:80] if stem else f"题目 {current_no}"
        tasks.append(
            Task(
                task_id=f"{parent_node_id}_q{current_no}",
                parent_node_id=parent_node_id,
                question_no=current_no,
                title=title,
                page_start=current_lines[0].page,
                page_end=current_lines[-1].page,
                stem=stem,
                answer=answer,
                explanation=explanation,
                markers_found=markers,
                risk_flags=risk_flags_for_text(raw),
                confidence=0.85 if markers else 0.72,
            )
        )
        current_no = None
        current_lines = []

    for line in segment:
        match = QUESTION_RE.match(line.text)
        is_next_question = False
        if match:
            number = int(match.group(1))
            is_next_question = number == 1 if last_question_no == 0 else number == last_question_no + 1
        if match and is_next_question:
            flush()
            current_no = match.group(1)
            last_question_no = int(current_no)
            current_lines = [line]
        elif current_no:
            current_lines.append(line)
    flush()
    return tasks


def slug(value: str) -> str:
    value = re.sub(r"\s+", "_", value.strip())
    value = re.sub(r"[^\w\u4e00-\u9fff]+", "_", value)
    return value.strip("_")[:40] or "node"


def parse_pdf(pdf_path: Path, subject: str = "unknown") -> Dict:
    page_count, lines, images_by_page = extract_lines(pdf_path)
    if not lines:
        return {
            "schema_version": "module_split_v0.2",
            "source": {"path": str(pdf_path), "subject": subject, "file_name": pdf_path.name},
            "lesson": {"title": pdf_path.stem, "page_count": page_count},
            "nodes": [],
            "tasks": [],
            "quality": {
                "page_count": page_count,
                "line_count": 0,
                "node_count": 0,
                "task_count": 0,
                "answer_bound_task_count": 0,
                "image_count": sum(images_by_page.values()),
                "pages_with_images": [page for page, count in images_by_page.items() if count],
                "low_confidence_nodes": [],
                "risk_flags": ["ocr_required", "no_text_layer"],
            },
        }

    title = lines[0].text
    cursor = 1
    objective_lines: List[Line] = []
    while cursor < len(lines) and OBJECTIVE_RE.match(lines[cursor].text):
        objective_lines.append(lines[cursor])
        cursor += 1

    section_starts: List[int] = []
    for index in range(cursor, len(lines)):
        if looks_like_section(lines[index].text):
            section_starts.append(index)

    nodes: List[Node] = [
        Node(
            node_id="lesson_root",
            parent_id=None,
            node_type="lesson",
            phase="lesson_meta",
            title=title,
            order_index=0,
            page_start=1,
            page_end=page_count,
            text=title,
            confidence=0.95,
            risk_flags=[],
        )
    ]

    if objective_lines:
        nodes.append(
            build_node(
                "learning_objectives",
                "lesson_root",
                "learning_objectives",
                "课程目标",
                1,
                objective_lines,
                0.82,
            )
        )

    preface_end = section_starts[0] if section_starts else len(lines)
    preface_lines = lines[cursor:preface_end]
    if preface_lines:
        nodes.append(
            build_node(
                "knowledge_preface",
                "lesson_root",
                "knowledge_block",
                "知识梳理",
                2,
                preface_lines,
                0.70,
            )
        )

    tasks: List[Task] = []
    for order, start in enumerate(section_starts, start=3):
        end = section_starts[section_starts.index(start) + 1] if section_starts.index(start) + 1 < len(section_starts) else len(lines)
        title_line = lines[start]
        body = lines[start + 1 : end]
        node_id = f"node_{order}_{slug(title_line.text)}"
        node_type = "exam_point" if title_line.text.startswith("考点") else "teaching_node"
        node = build_node(node_id, "lesson_root", node_type, title_line.text, order, [title_line] + body, 0.86)
        nodes.append(node)
        if node.phase in {"exam_point", "diagnostic_quiz", "example_or_task", "student_practice", "extension"}:
            tasks.extend(parse_tasks(node_id, body))

    node_payload = [node.__dict__ for node in nodes]
    task_payload = [task.__dict__ for task in tasks]
    quality = {
        "page_count": page_count,
        "line_count": len(lines),
        "node_count": len(nodes),
        "task_count": len(tasks),
        "answer_bound_task_count": sum(1 for task in task_payload if task["answer"] or task["explanation"]),
        "image_count": sum(images_by_page.values()),
        "pages_with_images": [page for page, count in images_by_page.items() if count],
        "low_confidence_nodes": [node["node_id"] for node in node_payload if node["confidence"] < 0.75],
        "risk_flags": sorted({risk for node in node_payload for risk in node["risk_flags"]} | {risk for task in task_payload for risk in task["risk_flags"]}),
    }
    return {
        "schema_version": "module_split_v0.2",
        "source": {"path": str(pdf_path), "subject": subject, "file_name": pdf_path.name},
        "lesson": {"title": title, "page_count": page_count},
        "nodes": node_payload,
        "tasks": task_payload,
        "quality": quality,
    }


def write_markdown(payload: Dict, output_path: Path) -> None:
    quality = payload["quality"]
    lines = [
        f"# 讲义模块拆分复核：{payload['lesson']['title']}",
        "",
        "## 基本结果",
        "",
        f"- 来源文件：{payload['source']['file_name']}",
        f"- 页数：{quality['page_count']}",
        f"- 识别模块：{quality['node_count']}",
        f"- 识别题块：{quality['task_count']}",
        f"- 已绑定答案/解析题块：{quality['answer_bound_task_count']}",
        f"- 图片/图表资产页：{', '.join(map(str, quality['pages_with_images'])) if quality['pages_with_images'] else '未检测到'}",
        f"- 风险标记：{', '.join(quality['risk_flags']) if quality['risk_flags'] else '无'}",
        "",
        "## 结构树",
        "",
    ]
    for node in payload["nodes"]:
        indent = "" if node["parent_id"] is None else "  "
        lines.append(
            f"{indent}- {node['node_id']} | {node['phase']} | p{node['page_start']}-p{node['page_end']} | {node['title']} | 置信度 {node['confidence']:.2f}"
        )
    lines.extend(["", "## 前 20 个题块", ""])
    for task in payload["tasks"][:20]:
        answer_state = "有答案/解析" if task["answer"] or task["explanation"] else "未识别答案"
        lines.append(
            f"- {task['task_id']} | p{task['page_start']}-p{task['page_end']} | {answer_state} | {task['title']}"
        )
    lines.extend(
        [
            "",
            "## 复核意见",
            "",
            "- 这份结果只做结构拆分，不做难度分层和版面组装。",
            "- 低置信度模块需要进入人工/模型复核队列。",
            "- 带 formula_text_layer、visual_or_table_asset 的题块后续需要公式或图表资产插件参与。",
        ]
    )
    output_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Split a teaching handout PDF into reviewable module and task structure.")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--subject", default="unknown")
    parser.add_argument("--out-dir", type=Path, default=Path("outputs/module_splitter"))
    args = parser.parse_args()

    payload = parse_pdf(args.pdf, subject=args.subject)
    lesson_slug = slug(payload["lesson"]["title"])
    out_dir = args.out_dir / lesson_slug
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "module_split.json"
    md_path = out_dir / "module_split_review.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(payload, md_path)
    print(json_path)
    print(md_path)


if __name__ == "__main__":
    main()
