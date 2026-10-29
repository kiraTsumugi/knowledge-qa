#!/usr/bin/env python3
"""生成 examples/ 下的运行记录（Trace + CLI 实际输出）。

运行：python examples/generate_traces.py
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.agent.llm import ModelClient
from src.agent.react_loop import run
from src.agent.tools import Tools

EX = ROOT / "examples"

CASES = [
    ("conflict", "报销期限多久", None, "文档冲突：D01(30天) vs D02(15天)，列冲突请求确认"),
    ("clear_answer", "年假有多少天", None, "明确答案：附 D03 引用原文"),
    ("out_of_scope", "食堂几点开饭", None, "资料外问题：返回缺口，绝不编造"),
    ("paraphrase", "退款什么时候到账", None, "改写相似问题：同义词归一化后命中 D05"),
    ("scoped_no_conflict", "出差报销要多久", None, "带场景限定：仅 D01 相关，依据 D01 作答"),
    ("followup", "那它的期限呢", ["年假怎么休"], "上下文追问：结合历史补全检索词"),
    ("tool_failure", "触发故障的提问", None, "工具失败：重试一次后明确失败"),
]

HISTORY_CASES = {"followup"}


def main():
    EX.mkdir(exist_ok=True)
    index = []
    for name, q, hist, desc in CASES:
        tools = Tools()
        model = ModelClient(offline=True)
        history = [{"role": "user", "content": h} for h in (hist or [])]
        r = run(q, history=history, model=model, tools=tools)
        record = {
            "case": name,
            "description": desc,
            "question": q,
            "history": hist or [],
            "model_mode": model.mode,
            "status": r.status,
            "answer": r.answer,
            "quotes": [qt.to_dict() for qt in r.quotes],
            "conflicts": r.conflicts,
            "gap": r.gap,
            "final": r.final,
            "trace": [vars(s) for s in r.trace],
        }
        (EX / f"trace_{name}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

        cmd = [sys.executable, "-m", "src.main", "--q", q, "--offline"]
        if hist:
            cmd += ["--history", *hist]
        out = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        (EX / f"run_{name}.txt").write_text(out.stdout, encoding="utf-8")
        index.append((name, desc, r.status))
        print(f"[{name}] status={r.status}")

    lines = ["# 运行记录索引", "",
             "| 用例 | 场景 | 最终状态 | Trace | CLI 输出 |",
             "|---|---|---|---|---|"]
    for name, desc, status in index:
        lines.append(f"| {name} | {desc} | `{status}` | "
                     f"[trace_{name}.json](trace_{name}.json) | [run_{name}.txt](run_{name}.txt) |")
    (EX / "INDEX.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("written to", EX)


if __name__ == "__main__":
    main()
