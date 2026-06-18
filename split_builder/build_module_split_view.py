import html
import json
from pathlib import Path


ROOT = Path("outputs") / "module_splitter"
OUT = ROOT / "module_split_overview.html"


def badge(text: str, tone: str = "neutral") -> str:
    return f'<span class="badge {tone}">{html.escape(text)}</span>'


def render_doc(path: Path) -> str:
    data = json.loads(path.read_text(encoding="utf-8"))
    quality = data["quality"]
    title = data["lesson"]["title"]
    subject = data["source"]["subject"]
    risks = quality.get("risk_flags", [])
    stats = [
        ("页数", quality["page_count"]),
        ("模块", quality["node_count"]),
        ("题块", quality["task_count"]),
        ("答案/解析绑定", quality["answer_bound_task_count"]),
    ]
    stat_html = "".join(f"<div><b>{v}</b><span>{k}</span></div>" for k, v in stats)
    risk_html = "".join(badge(r, "risk") for r in risks) or badge("无", "ok")

    node_rows = []
    for node in data["nodes"]:
        indent = "root" if node["parent_id"] is None else "child"
        task_count = sum(1 for t in data["tasks"] if t["parent_node_id"] == node["node_id"])
        node_rows.append(
            f"""
            <div class="node {indent}">
              <div class="node-main">
                <span class="phase">{html.escape(node["phase"])}</span>
                <strong>{html.escape(node["title"])}</strong>
                <em>p{node["page_start"]}-p{node["page_end"]}</em>
              </div>
              <div class="node-meta">
                {badge(f"置信度 {node['confidence']:.2f}", "ok" if node["confidence"] >= 0.8 else "warn")}
                {badge(f"{task_count} 题", "neutral") if task_count else ""}
                {"".join(badge(r, "risk") for r in node.get("risk_flags", []))}
              </div>
            </div>
            """
        )

    task_rows = []
    for task in data["tasks"][:60]:
        answer_ok = bool(task["answer"] or task["explanation"])
        task_rows.append(
            f"""
            <tr>
              <td>{html.escape(task["task_id"])}</td>
              <td>p{task["page_start"]}-p{task["page_end"]}</td>
              <td>{badge("已绑定", "ok") if answer_ok else badge("待复核", "warn")}</td>
              <td>{html.escape(task["title"][:120])}</td>
            </tr>
            """
        )

    judgment = "可作为结构零件" if quality["task_count"] or quality["node_count"] else "不能直接拆，需要 OCR/视觉通道"
    if "ocr_required" in risks:
        judgment = "不是文本零件，需要 OCR 后再拆"
    elif subject == "生物" and quality["task_count"] == 0:
        judgment = "知识模块可用，题块零件未完成"

    return f"""
    <section class="doc">
      <header>
        <div>
          <p class="subject">{html.escape(subject)}</p>
          <h2>{html.escape(title)}</h2>
        </div>
        <div class="judgment">{html.escape(judgment)}</div>
      </header>
      <div class="stats">{stat_html}</div>
      <div class="risks">{risk_html}</div>
      <h3>结构树</h3>
      <div class="tree">{''.join(node_rows) or '<p class="empty">没有文本结构可拆</p>'}</div>
      <h3>题块样例</h3>
      <table>
        <thead><tr><th>题块 ID</th><th>页码</th><th>答案解析</th><th>题干开头</th></tr></thead>
        <tbody>{''.join(task_rows) or '<tr><td colspan="4" class="empty">暂无题块</td></tr>'}</tbody>
      </table>
    </section>
    """


def main() -> None:
    docs = sorted(ROOT.glob("*/module_split.json"))
    body = "\n".join(render_doc(path) for path in docs)
    html_text = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>讲义模块拆分结果总览</title>
<style>
body {{ margin:0; background:#eef2f7; color:#172033; font-family: "Microsoft YaHei", Arial, sans-serif; }}
.wrap {{ max-width: 1280px; margin: 0 auto; padding: 28px; }}
h1 {{ margin: 0 0 8px; font-size: 30px; }}
.lead {{ margin: 0 0 24px; color:#53627a; }}
.doc {{ background:white; border:1px solid #d7dfeb; border-radius: 14px; padding: 22px; margin-bottom: 22px; box-shadow: 0 8px 28px rgba(23,32,51,.06); }}
header {{ display:flex; justify-content:space-between; gap:18px; align-items:flex-start; border-bottom:1px solid #e6ecf4; padding-bottom:16px; }}
.subject {{ margin:0 0 4px; color:#2256d6; font-weight:700; }}
h2 {{ margin:0; font-size:22px; }}
.judgment {{ background:#f5f8ff; border:1px solid #cad9ff; color:#123a9c; border-radius:999px; padding:8px 14px; font-weight:700; white-space:nowrap; }}
.stats {{ display:grid; grid-template-columns:repeat(4, 1fr); gap:12px; margin:18px 0; }}
.stats div {{ background:#f7f9fc; border:1px solid #e2e8f2; border-radius:10px; padding:12px; }}
.stats b {{ display:block; font-size:24px; }}
.stats span {{ color:#60708a; }}
.badge {{ display:inline-flex; align-items:center; border-radius:999px; padding:3px 9px; font-size:12px; margin:2px 4px 2px 0; border:1px solid #dbe3ee; color:#4f5d74; background:#f8fafc; }}
.badge.ok {{ background:#ecfdf5; color:#067647; border-color:#b7ebd1; }}
.badge.warn {{ background:#fff7ed; color:#b45309; border-color:#fed7aa; }}
.badge.risk {{ background:#fff1f2; color:#be123c; border-color:#fecdd3; }}
h3 {{ font-size:16px; margin:20px 0 10px; }}
.tree {{ border:1px solid #e2e8f2; border-radius:10px; overflow:hidden; }}
.node {{ padding:10px 12px; border-bottom:1px solid #e8eef6; display:flex; justify-content:space-between; gap:14px; align-items:center; }}
.node:last-child {{ border-bottom:0; }}
.node.child {{ padding-left:32px; }}
.node-main {{ display:flex; gap:10px; align-items:center; min-width:0; }}
.phase {{ font-size:12px; color:#60708a; background:#f1f5f9; padding:3px 7px; border-radius:999px; }}
.node strong {{ overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
.node em {{ color:#718096; font-style:normal; white-space:nowrap; }}
.node-meta {{ white-space:nowrap; }}
table {{ width:100%; border-collapse:collapse; font-size:13px; }}
th, td {{ border-bottom:1px solid #e8eef6; padding:9px 8px; text-align:left; vertical-align:top; }}
th {{ color:#53627a; background:#f7f9fc; }}
.empty {{ color:#8a98ad; text-align:center; padding:16px; }}
</style>
</head>
<body>
<div class="wrap">
<h1>讲义模块拆分结果总览</h1>
<p class="lead">当前只验证“拆出结构树和题块零件”，不代表已经完成分层、排版或全量视觉验收。</p>
{body}
</div>
</body>
</html>"""
    OUT.write_text(html_text, encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
