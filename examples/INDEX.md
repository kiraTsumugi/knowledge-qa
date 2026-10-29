# 运行记录索引

| 用例 | 场景 | 最终状态 | Trace | CLI 输出 |
|---|---|---|---|---|
| conflict | 文档冲突：D01(30天) vs D02(15天)，列冲突请求确认 | `needs_clarification` | [trace_conflict.json](trace_conflict.json) | [run_conflict.txt](run_conflict.txt) |
| clear_answer | 明确答案：附 D03 引用原文 | `answered` | [trace_clear_answer.json](trace_clear_answer.json) | [run_clear_answer.txt](run_clear_answer.txt) |
| out_of_scope | 资料外问题：返回缺口，绝不编造 | `not_found` | [trace_out_of_scope.json](trace_out_of_scope.json) | [run_out_of_scope.txt](run_out_of_scope.txt) |
| paraphrase | 改写相似问题：同义词归一化后命中 D05 | `answered` | [trace_paraphrase.json](trace_paraphrase.json) | [run_paraphrase.txt](run_paraphrase.txt) |
| scoped_no_conflict | 带场景限定：仅 D01 相关，依据 D01 作答 | `answered` | [trace_scoped_no_conflict.json](trace_scoped_no_conflict.json) | [run_scoped_no_conflict.txt](run_scoped_no_conflict.txt) |
| followup | 上下文追问：结合历史补全检索词 | `answered` | [trace_followup.json](trace_followup.json) | [run_followup.txt](run_followup.txt) |
| tool_failure | 工具失败：重试一次后明确失败 | `tool_error` | [trace_tool_failure.json](trace_tool_failure.json) | [run_tool_failure.txt](run_tool_failure.txt) |
