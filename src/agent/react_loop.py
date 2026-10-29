"""ReAct 决策循环。

循环骨架：模型输出动作 → 执行工具 → 观察结果喂回模型 → 模型决定下一步。
硬约束：
- 步数上限 MAX_STEPS，达到即返回 incomplete。
- status=answered 必须携带 quotes（引用支持回答）——无引用不允许输出答案。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from .llm import ModelClient
from .models import Answer, Quote
from .tools import Tools

MAX_STEPS = 8
TOOL_ACTIONS = {"search_docs", "read_doc"}

SYSTEM_PROMPT = """你是"企业知识问答 Agent"。职责：为员工的问题找到可靠答案，并给出引用。

只能通过 JSON 动作调用工具：
- {"action":"search_docs","args":{"query":"..."},"reason":"..."}
- {"action":"read_doc","args":{"doc_id":"D01","section_key":"..."},"reason":"..."}
结束用：{"action":"finish","status":"answered|needs_clarification|not_found|tool_error|incomplete","answer":"...","quotes":[{"doc_id":"...","section_key":"...","text":"...","version_date":"..."}],"conflicts":[...],"gap":["..."],"reason":"..."}

铁律：
1. 回答必须附引用（quotes），引用原文必须支持答案，禁止无依据作答。
2. 多个文档对同一问题给出不同答案且未给适用范围时，列出冲突并请求确认，绝不擅自选一个。
3. 资料外问题返回 not_found 与缺口，不编造。
4. 上下文追问：结合对话历史补全问题后再检索。
5. 每次只输出一个 JSON 动作。"""


@dataclass
class TraceStep:
    n: int
    action: str
    args: dict
    reason: str
    observation: dict | None = None


@dataclass
class Result:
    status: str
    question: str
    answer: str = ""
    quotes: list[Quote] = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)
    gap: list[str] = field(default_factory=list)
    trace: list[TraceStep] = field(default_factory=list)
    final: dict = field(default_factory=dict)


def run(question: str, history: list[dict] | None = None,
        model: ModelClient | None = None, tools: Tools | None = None) -> Result:
    model = model or ModelClient()
    tools = tools or Tools()
    history = history or []

    intent = json.dumps({
        "task": f"回答员工问题：{question}",
        "question": question,
        "history": history,
    }, ensure_ascii=False)

    messages: list[dict] = [{"role": "user", "content": intent}]
    trace: list[TraceStep] = []

    for step_no in range(1, MAX_STEPS + 1):
        action = model.decide(SYSTEM_PROMPT, messages)

        if not isinstance(action, dict):
            trace.append(TraceStep(step_no, "<invalid>", {}, "模型返回非结构化输出",
                                   {"error": "invalid_action"}))
            messages.append({"role": "user", "content": json.dumps(
                {"error": "invalid_action", "hint": "只输出一个 JSON 动作"})})
            continue

        name = action.get("action", "")
        args = action.get("args", {}) or {}
        reason = action.get("reason", "")
        ts = TraceStep(step_no, name, args, reason)

        if name == "finish":
            ts.observation = {"finished": True, "status": action.get("status")}
            trace.append(ts)
            return _build_result(action, question, trace)

        if name in TOOL_ACTIONS:
            obs = _dispatch(tools, name, args)
            ts.observation = obs
            trace.append(ts)
            messages.append({"role": "assistant", "content": json.dumps(action)})
            messages.append({"role": "user", "content": json.dumps(obs, ensure_ascii=False)})
            continue

        ts.observation = {"error": "unknown_action", "action": name}
        trace.append(ts)
        messages.append({"role": "user", "content": json.dumps(
            {"error": "unknown_action", "action": name, "hint": "重选合法动作"})})

    trace.append(TraceStep(MAX_STEPS + 1, "abort", {}, "达到步数上限",
                           {"error": "max_steps_exceeded"}))
    return Result(status="incomplete", question=question, trace=trace,
                  gap=["执行步数超限，未完成任务"],
                  final={"reason": f"达到最大步数 {MAX_STEPS} 仍未完成"})


def _build_result(action: dict, question: str, trace: list[TraceStep]) -> Result:
    status = action.get("status", "incomplete")
    quotes = [Quote(doc_id=q.get("doc_id", ""), section_key=q.get("section_key", ""),
                    text=q.get("text", ""), version_date=q.get("version_date", ""))
              for q in action.get("quotes", [])]
    answer = action.get("answer", "")

    # 结构保证：answered 必须携带引用，否则降级为无依据、不允许输出答案
    if status == "answered" and not quotes:
        return Result(status="incomplete", question=question,
                      gap=["模型试图无引用作答，已拦截"], trace=trace,
                      final={"reason": "answered 缺少 quotes，拒绝无依据回答"})

    return Result(status=status, question=question, answer=answer, quotes=quotes,
                  conflicts=action.get("conflicts", []),
                  gap=action.get("gap", []), trace=trace, final=action)


def _dispatch(tools: Tools, name: str, args: dict) -> dict:
    if name == "search_docs":
        return tools.search_docs(args.get("query", ""))
    if name == "read_doc":
        return tools.read_doc(args.get("doc_id", ""), args.get("section_key"))
    return {"ok": False, "error": "unknown_action", "action": name}
