# 03 · 评估

## 测试预期 vs 实际结果

全部测试：`python -m unittest discover -s tests -v` → **29 passed**。

| 用例 | 预期 | 实际 | 证据 |
|---|---|---|---|
| 文档冲突 | `needs_clarification`，列 D01+D02，空答案 | ✅ | `examples/trace_conflict.json` |
| 明确答案 | `answered` + D03 引用原文 | ✅ | `examples/trace_clear_answer.json` |
| 资料外问题 | `not_found` + 缺口 | ✅ | `examples/trace_out_of_scope.json` |
| 改写相似问题 | `answered` + D05（同义词归一化）| ✅ | `examples/trace_paraphrase.json` |
| 场景限定问法 | `answered` + D01（无冲突可答）| ✅ | `examples/trace_scoped_no_conflict.json` |
| 上下文追问 | `answered` + D03（检索词含历史主题）| ✅ | `examples/trace_followup.json` |
| 工具失败 | `tool_error` | ✅ | `examples/trace_tool_failure.json` |
| 无引用作答被拦截 | 循环层拒绝 | ✅ | `tests/test_agent.py::TestSafety` |
| 数据替换行为改变 | 答案/状态随文档变化 | ✅ | `tests/test_agent.py::TestDataSwap` |
| 引用精度 | 问"到账"引用"退款到账"片段 | ✅ | `tests/test_agent.py::TestQuotePrecision` |
| 边界输入 | 空问题/纯标点/噪声 → `not_found` | ✅ | `tests/test_agent.py::TestEdgeInput` |
| 畸形模型输出 ×2 | 不崩溃 | ✅ | `tests/test_agent.py::TestMalformedModelOutput` |

## ReAct 决策证据（核心）

`trace_conflict.json` 的完整轨迹：

```
step1 search_docs("报销期限多久") → 命中 D01+D02 同 key「报销期限」，原文不同
step2 read_doc(D01)               ← 模型逐个读取候选原文以核对引用
step3 read_doc(D02)               ← 读完两份，事实齐了
step4 finish(needs_clarification) ← 列出冲突+双方原文，请求确认（不选边、空答案）
```

`trace_out_of_scope.json` 走**不同路径**：`search(0 命中) → finish(not_found)`，
**没有**读取文档、**没有**编造答案。

**同一段循环代码，因检索事实不同走出不同决策** —— 满足 ReAct 要求。

## 冲突处理的正确性（对照参考实例）

| 问题 | 期望（参考实例）| 实际 |
|---|---|---|
| "报销期限多久"（泛化）| 列冲突+请求确认，不擅自答 15 天 | ✅ `needs_clarification` |
| "出差报销要多久"（有场景）| 仅 D01 相关时可依据 D01 回答 | ✅ `answered` + D01 |

## 安全核对

- `test_no_quotes_answer_blocked`：模型试图无引用作答 → 被拦截。
- `test_quotes_come_from_documents`：断言引用文本能在原文中找到（错误引用=关键缺陷，已防）。
- `test_conflict_does_not_pick_side`：冲突时 `answer == ""`，双方候选均展示。
- `test_not_found_no_answer`：资料外问题 `answer == ""`、`quotes == []`。

## 真实模型接入验证

`python examples/verify_live_path.py` 验证 `_call_live` 的 HTTP 契约
（payload / Bearer 鉴权 / JSON 解析）→ **通过**。

## 失败与限制

1. **Mock 非真实模型决策**：默认离线 Mock 是确定性规则器，只证明**流程、边界与冲突逻辑**，
   不证明真实 LLM 决策质量。真实能力需配 `MODEL_*` 后实测。
2. **检索为关键词近似**：中文分词用 2-4 字滑窗近似（无 jieba 等依赖），
   同义改写覆盖有限；更复杂问法需接入真实分词/向量检索。
3. **冲突检测粒度**：按 `section_key` 分组判断，若两文档用不同 key 描述同一事项则可能漏检。
4. **未做多轮会话持久化**：`--history` 由调用方提供。
5. **版本日期未参与裁决**：冲突时展示版本日期作为线索，但不擅自用"新版本优先"裁决
   （题目要求"未给优先级时不得擅自选"，本实现在冲突样例中未给优先级 → 正确行为是请求确认）。

## 越权检查

- 输出全程无「已发布」字样（`test_never_claims_published`）。
- 无依据不回答：`not_found` 时 `answer == ""`。
