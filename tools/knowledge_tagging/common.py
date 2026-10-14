from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "knowledge_tagging_catalog_v0.1"


@dataclass(frozen=True)
class KnowledgeNode:
    pk: str
    source: str
    source_pk: str
    source_parent_pk: str
    parent_pk: str
    stage: str
    subject: str
    name: str
    path: str
    ancestors: list[str]
    depth: int
    is_leaf: bool
    url: str
    top_category: str
    searchable_text: str

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def normalize_text(value: str) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).casefold().strip()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: Any) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2))


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        # 临时文件与目标文件位于同一目录，os.replace 才能保证原子替换。
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as fh:
            temp_path = Path(fh.name)
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    temp_path: Path | None = None
    try:
        # JSONL 可能包含整棵树的向量，边迭代边写可避免为原子落盘复制一份完整内存。
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as fh:
            temp_path = Path(fh.name)
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
                count += 1
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temp_path, path)
        return count
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def read_json_or_jsonl(path: Path) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        rows: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8-sig") as fh:
            for line in fh:
                clean = line.strip()
                if clean:
                    rows.append(json.loads(clean))
        return rows
    payload = read_json(path)
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("questions", "items", "rows"):
            value = payload.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
    raise ValueError(f"Unsupported question payload shape: {path}")


def load_catalog(path: Path) -> list[KnowledgeNode]:
    rows = read_json_or_jsonl(path)
    return [KnowledgeNode(**row) for row in rows]


def source_scoped_pk(source: str, stage: str, subject: str, source_pk: str) -> str:
    return f"{source}:{stage}:{subject}:{source_pk}"


def build_searchable_text(*parts: str) -> str:
    clean_parts = [str(part).strip() for part in parts if str(part or "").strip()]
    return "\n".join(clean_parts)


def write_sqlite(path: Path, nodes: list[KnowledgeNode]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            CREATE TABLE knowledge_nodes (
              pk TEXT PRIMARY KEY,
              source TEXT NOT NULL,
              source_pk TEXT NOT NULL,
              source_parent_pk TEXT NOT NULL,
              parent_pk TEXT NOT NULL,
              stage TEXT NOT NULL,
              subject TEXT NOT NULL,
              name TEXT NOT NULL,
              path TEXT NOT NULL,
              ancestors_json TEXT NOT NULL,
              depth INTEGER NOT NULL,
              is_leaf INTEGER NOT NULL,
              url TEXT NOT NULL,
              top_category TEXT NOT NULL,
              searchable_text TEXT NOT NULL
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO knowledge_nodes VALUES (
              :pk, :source, :source_pk, :source_parent_pk, :parent_pk, :stage, :subject,
              :name, :path, :ancestors_json, :depth, :is_leaf, :url, :top_category, :searchable_text
            )
            """,
            [
                {
                    **node.to_json(),
                    "ancestors_json": json.dumps(node.ancestors, ensure_ascii=False),
                    "is_leaf": 1 if node.is_leaf else 0,
                }
                for node in nodes
            ],
        )
        conn.execute("CREATE INDEX idx_knowledge_stage_subject ON knowledge_nodes(stage, subject)")
        conn.execute("CREATE INDEX idx_knowledge_source_leaf ON knowledge_nodes(source, is_leaf)")
        conn.commit()
    finally:
        conn.close()
