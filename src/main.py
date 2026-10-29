"""CLI 入口。

用法：
  python -m src.main --q "报销期限多久"
  python -m src.main --q "那它的期限呢" --history "年假怎么休" ...
  python -m src.main --q "报销期限多久" -v
  python -m src.main --q "报销期限多久" --json
  python -m src.main --q "报销期限多久" --trace out.json
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from .agent.llm import ModelClient
from .agent.react_loop import Result, run
from .agent.tools import Tools

STATUS_LABEL = {
    "answered": "已作答（附引用）",
    "needs_clarification": "存在文档冲突，待确认",
    "not_found": "知识库无相关资料",
    "tool_error": "工具失败",
    "incomplete": "未完成",
}


def _to_dict(r: Result) -> dict:
    return {
        "status": r.status,
        "status_label": STATUS_LABEL.get(r.status, r.status),
        "question": r.question,
        "answer": r.answer,
        "quotes": [q.to_dict() for q in r.quotes],
        "conflicts": r.conflicts,
        "gap": r.gap,
        "final": r.final,
        "trace": [asdict(s) for s in r.trace],
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="knowledge-qa")
    p.add_argument("--q", required=True, help="员工问题")
    p.add_argument("--history", nargs="*", default=[],
                   help="可选对话历史（按顺序给出用户消息）")
    p.add_argument("--json", action="store_true", help="以 JSON 输出完整结果")
    p.add_argument("--trace", default=None, help="将完整 trace 写入文件")
    p.add_argument("--offline", action="store_true", help="强制离线 Mock 模型")
    p.add_argument("--verbose", "-v", action="store_true", help="打印每步决策")
    args = p.parse_args(argv)

    history = [{"role": "user", "content": h} for h in args.history]
    model = ModelClient(offline=True if args.offline else None)
    tools = Tools()

    result = run(args.q, history=history, model=model, tools=tools)
    out = _to_dict(result)
    out["model_mode"] = model.mode

    if args.trace:
        with open(args.trace, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)

    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    if args.verbose:
        print(f"[model] {model.mode}")
        for s in result.trace:
            print(f"  step {s.n}: {s.action} args={s.args}  ← {s.reason}")
            if s.observation:
                print(f"           obs={json.dumps(s.observation, ensure_ascii=False)[:150]}")

    print(f"\n问题: {result.question}")
    print(f"状态: {STATUS_LABEL.get(result.status, result.status)}")

    if result.answer:
        print(f"回答: {result.answer}")

    if result.quotes:
        print("引用:")
        for q in result.quotes:
            print(f"  - [{q.doc_id}] {q.section_key} ({q.version_date}): {q.text}")

    if result.conflicts:
        print("冲突:")
        for c in result.conflicts:
            print(f"  - 字段「{c['section_key']}」存在多个不同来源:")
            for cand in c["candidates"]:
                print(f"      [{cand['doc_id']}] ({cand['version_date']}): {cand['text']}")

    if result.gap:
        print("资料缺口 / 待确认:")
        for g in result.gap:
            print(f"  - {g}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
