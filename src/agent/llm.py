"""模型接入层。

两种后端：
1. 真实模型：任意 OpenAI 兼容端点，仅用标准库 urllib。
2. 离线 Mock：无 API key 时自动降级。消费检索事实做确定性决策：
   无命中→拒答；同 key 不同值→列冲突请求确认；单一命中→引用作答。

边界声明：Mock 只验证流程、边界与冲突逻辑，不证明真实模型决策效果。
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request


class ModelClient:
    def __init__(self, offline: bool | None = None):
        self.base_url = os.environ.get("MODEL_BASE_URL", "").rstrip("/")
        self.api_key = os.environ.get("MODEL_API_KEY", "")
        self.model = os.environ.get("MODEL_NAME", "gpt-4o-mini")
        if offline is None:
            offline = not (self.base_url and self.api_key)
        self.offline = offline

    @property
    def mode(self) -> str:
        return "offline-mock" if self.offline else f"live:{self.model}"

    def decide(self, system: str, messages: list[dict]) -> dict:
        if self.offline:
            return OfflineMock.decide(messages)
        return self._call_live(system, messages)

    def _call_live(self, system: str, messages: list[dict]) -> dict:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, *messages],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.api_key}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = json.loads(resp.read().decode())
            return _parse_action(body["choices"][0]["message"]["content"])
        except urllib.error.URLError as e:
            raise RuntimeError(f"model_call_failed: {e}") from e


def _parse_action(content: str) -> dict:
    s = content.strip()
    if s.startswith("```"):
        s = s.strip("`")
        s = s.split("\n", 1)[1] if "\n" in s else s
        if s.endswith("```"):
            s = s[:-3]
    start, end = s.find("{"), s.rfind("}")
    if start >= 0 and end > start:
        s = s[start:end + 1]
    return json.loads(s)


class OfflineMock:
    """确定性决策器：消费工具事实，不消费预设剧本。"""

    MAX_SEARCH_RETRY = 1

    @staticmethod
    def decide(messages: list[dict]) -> dict:
        f = OfflineMock._collect(messages)
        question = f["question"]
        # 上下文追问：问题含代词/省略时，结合历史补全检索词
        search_query = OfflineMock._resolve_query(question, f["history"])

        # 步骤1：检索（故障可重试一次）
        if not f["searches"]:
            return {"action": "search_docs", "args": {"query": search_query},
                    "reason": "检索相关文档"
                              + ("（结合对话历史补全追问）" if search_query != question else "")}
        last_search = f["searches"][-1]
        if not last_search.get("ok"):
            if len(f["searches"]) <= OfflineMock.MAX_SEARCH_RETRY:
                return {"action": "search_docs", "args": {"query": search_query},
                        "reason": "检索工具失败，重试一次"}
            return {"action": "finish", "status": "tool_error",
                    "reason": "检索服务不可用，无法获取依据",
                    "gap": ["检索工具连续失败，请稍后重试"]}

        hits = last_search.get("hits", [])
        # 无命中 → 资料外问题，明确缺口，绝不无依据作答
        if not hits:
            return {"action": "finish", "status": "not_found",
                    "reason": "知识库中未找到与该问题相关的文档",
                    "gap": ["知识库无相关文档，请补充资料或换一种问法"]}

        # 步骤2：读取候选文档原文（核对引用）
        top_docs = []
        for h in hits[:4]:
            if h["doc_id"] not in [d["doc_id"] for d in f["read_docs"]]:
                top_docs.append(h["doc_id"])
        if top_docs:
            return {"action": "read_doc", "args": {"doc_id": top_docs[0]},
                    "reason": f"读取 {top_docs[0]} 原文以核对引用"}

        # 步骤3：冲突检测——同一 section_key 出现多个文档且原文不同
        conflict = OfflineMock._detect_conflict(hits)
        if conflict:
            return {"action": "finish", "status": "needs_clarification",
                    "reason": "多个文档对同一问题给出不同答案，需确认适用范围",
                    "conflicts": conflict,
                    "gap": ["请确认适用哪一份制度，或提供更具体的场景（如：国内出差/办公费用）"]}

        # 无冲突 → 依据唯一/一致来源作答
        best = hits[0]
        quote = {"doc_id": best["doc_id"], "section_key": best["section_key"],
                 "text": best["text"], "version_date": best["version_date"]}
        return {"action": "finish", "status": "answered",
                "answer": f"依据 {best['doc_id']}《{best['title']}》：{best['text']}",
                "quotes": [quote],
                "reason": "检索到唯一相关文档，依据原文作答"}

    @staticmethod
    def _detect_conflict(hits: list[dict]) -> list[dict] | None:
        """同一 section_key 出现在多个文档且原文（含数值）不同 → 冲突。

        返回冲突事实（各方引用），不选边。
        """
        by_key: dict[str, list[dict]] = {}
        for h in hits:
            by_key.setdefault(h["section_key"], []).append(h)
        conflicts = []
        for key, group in by_key.items():
            docs = {h["doc_id"] for h in group}
            texts = {h["text"] for h in group}
            if len(docs) >= 2 and len(texts) >= 2:
                conflicts.append({
                    "section_key": key,
                    "candidates": [
                        {"doc_id": h["doc_id"], "version_date": h["version_date"],
                         "text": h["text"],
                         "numbers": re.findall(r"\d+", h["text"])}
                        for h in group
                    ],
                })
        return conflicts or None

    @staticmethod
    def _resolve_query(question: str, history: list[dict]) -> str:
        """追问改写：问题含代词且过短时，拼接最近一条用户历史成完整检索词。"""
        pronouns = ("它", "他", "这个", "那个", "其", "这种", "该", "那")
        if history and any(p in question for p in pronouns):
            prev_user = next((h.get("content", "") for h in reversed(history)
                              if h.get("role") == "user"), "")
            if prev_user:
                # 去掉代词，拼上主题词
                q = question
                for p in pronouns:
                    q = q.replace(p, "")
                return f"{prev_user} {q}".strip()
        return question

    @staticmethod
    def _collect(messages: list[dict]) -> dict:
        question = ""
        history: list[dict] = []
        searches: list[dict] = []
        read_docs: list[dict] = []
        for m in messages:
            if m.get("role") == "user":
                try:
                    obs = json.loads(m.get("content", ""))
                except Exception:
                    continue
                if not isinstance(obs, dict):
                    continue
                if "question" in obs and "history" in obs:
                    question = obs["question"]
                    history = obs["history"]
                elif "hits" in obs or obs.get("tool") == "search_docs":
                    searches.append(obs)  # 含失败返回（无 hits 但有 tool=search_docs）
                elif "sections" in obs:
                    read_docs.append(obs)
        return {"question": question, "history": history,
                "searches": searches, "read_docs": read_docs}
