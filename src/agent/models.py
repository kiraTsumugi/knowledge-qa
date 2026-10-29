"""核心数据结构。

设计原则：
- 没有 quotes 的答案结构上不允许出现——"引用支持回答"由数据结构保证。
- 状态正交：answered / needs_clarification / not_found / tool_error / incomplete。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def load_json(name: str) -> Any:
    with open(DATA_DIR / name, "r", encoding="utf-8") as f:
        return json.load(f)


@dataclass
class Quote:
    """原文片段引用：回答的依据。"""
    doc_id: str
    section_key: str
    text: str
    version_date: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Document:
    id: str
    title: str
    version_date: str
    sections: list[dict]

    def quote(self, section_key: str) -> Quote | None:
        for s in self.sections:
            if s["key"] == section_key:
                return Quote(doc_id=self.id, section_key=s["key"],
                             text=s["text"], version_date=self.version_date)
        return None


@dataclass
class Hit:
    """检索命中：文档 + 命中片段（事实，不含判断）。"""
    doc_id: str
    title: str
    version_date: str
    section_key: str
    text: str
    score: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Answer:
    """最终回答。quotes 为空时答案无效（由 Result 校验）。"""
    status: str
    question: str
    answer: str = ""
    quotes: list[Quote] = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)
    gap: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d
