"""业务工具层。

铁律：工具只返回"事实"，绝不返回"决策"。
- search_docs 返回命中的全部片段（含冲突候选），不判断哪个对。
- read_doc 返回指定文档的原文片段，供引用核对。
- 工具不判断"该不该回答""是否冲突"——那是模型的活。
"""
from __future__ import annotations

import json
from pathlib import Path

from .models import DATA_DIR, Document, Hit


def _load(name: str, data_dir: Path | None = None):
    with open((data_dir or DATA_DIR) / name, "r", encoding="utf-8") as f:
        return json.load(f)


_STOPWORDS = {"的", "了", "吗", "呢", "是", "有", "和", "与", "在", "我", "请问"}


class Tools:
    def __init__(self, data_dir: Path | None = None):
        raw = _load("docs.json", data_dir)
        self._docs: dict[str, Document] = {
            d["id"]: Document(id=d["id"], title=d["title"],
                              version_date=d["version_date"],
                              sections=d["sections"])
            for d in raw["docs"]
        }
        self._synonyms: dict[str, str] = _load("synonyms.json", data_dir)["synonyms"]
        self._fail = raw.get("_fail_injection", {})
        self._df = self._build_df()  # 词 → 出现该词的文档数（IDF 用）

    def _build_df(self) -> dict[str, int]:
        df: dict[str, int] = {}
        for doc in self._docs.values():
            doc_tokens: set[str] = set()
            for sec in doc.sections:
                doc_tokens |= self._tokens(sec["key"] + " " + sec["text"])
            for t in doc_tokens:
                df[t] = df.get(t, 0) + 1
        return df

    # --- 内部：归一化 -----------------------------------------------------
    def _normalize(self, text: str) -> str:
        for src, dst in self._synonyms.items():
            text = text.replace(src, dst)
        return text

    def _tokens(self, text: str) -> set[str]:
        norm = self._normalize(text)
        tokens = set()
        # 按标点/空格切分后，再取 2-4 字滑窗做中文分词近似
        for seg in norm.replace("？", " ").replace("?", " ").replace("，", " ").split():
            seg = "".join(ch for ch in seg if ch not in _STOPWORDS)
            if not seg:
                continue
            tokens.add(seg)
            for n in (2, 3, 4):
                for i in range(len(seg) - n + 1):
                    tokens.add(seg[i:i + n])
        return tokens

    # --- 1. 文档检索：返回全部命中片段 ------------------------------------
    def search_docs(self, query: str) -> dict:
        # 故障注入
        if self._fail.get("tool") == "search_docs" and any(
                k in query for k in self._fail.get("keywords", [])):
            return {"ok": False, "error": "tool_error",
                    "tool": "search_docs",
                    "message": "检索服务暂时不可用（故障注入）"}

        q_tokens = self._tokens(query)
        # 稀有词（df<=1，仅存在于一个文档）是强信号：命中即锁定该文档。
        unique_tokens = {t for t in q_tokens if self._df.get(t, 0) <= 1}
        hits: list[tuple[Hit, bool]] = []
        for doc in self._docs.values():
            for sec in doc.sections:
                sec_text = sec["key"] + " " + sec["text"]
                s_tokens = self._tokens(sec_text)
                matched = q_tokens & s_tokens
                if not matched:
                    continue
                # 权重 = 1/df（稀有词权重高，"期限"这类通用词权重低）
                weighted = sum(1.0 / self._df.get(t, 1) for t in matched)
                has_unique = any(t in unique_tokens for t in matched)
                hits.append((Hit(doc_id=doc.id, title=doc.title,
                                 version_date=doc.version_date,
                                 section_key=sec["key"], text=sec["text"],
                                 score=weighted), has_unique))
        hits.sort(key=lambda pair: -pair[0].score)
        # 有强命中（命中稀有词）时只保留强命中；否则用相对阈值过滤低权误召回
        strong = [h for h, u in hits if u]
        if unique_tokens and strong:
            hits = [(h, u) for h, u in hits if u]
        else:
            best = hits[0][0].score if hits else 0
            hits = [(h, u) for h, u in hits if h.score >= best * 0.6]
        return {
            "ok": True,
            "query": query,
            "normalized_query": self._normalize(query),
            "hits": [h.to_dict() for h, _ in hits],
            "doc_ids": sorted({h.doc_id for h, _ in hits}),
        }

    # --- 2. 片段读取：返回指定文档原文 ------------------------------------
    def read_doc(self, doc_id: str, section_key: str | None = None) -> dict:
        doc = self._docs.get(doc_id)
        if doc is None:
            return {"ok": False, "error": "not_found", "doc_id": doc_id}
        if section_key:
            q = doc.quote(section_key)
            if q is None:
                return {"ok": False, "error": "section_not_found",
                        "doc_id": doc_id, "section_key": section_key}
            return {"ok": True, "doc_id": doc.id, "title": doc.title,
                    "version_date": doc.version_date,
                    "sections": [{"key": q.section_key, "text": q.text}]}
        return {"ok": True, "doc_id": doc.id, "title": doc.title,
                "version_date": doc.version_date,
                "sections": [dict(s) for s in doc.sections]}
