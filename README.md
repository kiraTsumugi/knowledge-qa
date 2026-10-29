# 企业知识问答 Agent

面向员工的知识助手：回答制度或产品问题，**每个答案都附文档 ID 与原文片段**；文档冲突时**列出冲突并请求确认**，绝不擅自选一个；资料外问题明确返回缺口，**绝不无依据作答**。

模型驱动 ReAct 循环：**模型选动作 → 执行工具 → 观察结果 → 模型调整下一步或结束**。

## 快速开始

无需任何第三方依赖（纯标准库），Python ≥ 3.10。

```bash
# 1. 文档冲突：D01(30天) vs D02(15天) → 列出冲突，请求确认（不擅自选）
python -m src.main --q "报销期限多久" -v

# 2. 明确答案：附引用原文
python -m src.main --q "年假有多少天"

# 3. 带场景限定：仅 D01 相关 → 依据 D01 作答（参考实例规定）
python -m src.main --q "出差报销要多久"

# 4. 改写相似问题：同义词归一化后命中
python -m src.main --q "退款什么时候到账"

# 5. 上下文追问：结合历史补全检索词
python -m src.main --q "那它的期限呢" --history "年假怎么休"

# 6. 资料外问题：返回缺口，不编造
python -m src.main --q "食堂几点开饭"

# 7. 工具失败
python -m src.main --q "触发故障的提问"
```

**评审入口**：`python -m src.main --q "报销期限多久" -v` 打印每步 `动作 → 参数 → 决策依据`（完整 ReAct Trace）。

## 运行模式

- **离线 Mock（默认，无 key 时自动）**：确定性决策，消费检索事实。`--offline` 强制。
  边界：Mock 只验证**流程、边界与冲突逻辑**，不证明真实模型决策效果。
- **真实模型**：任意 OpenAI 兼容端点：
  ```bash
  export MODEL_BASE_URL=https://api.openai.com/v1
  export MODEL_API_KEY=sk-...
  export MODEL_NAME=gpt-4o-mini
  ```

## 测试

```bash
python -m unittest discover -s tests -v        # 23 项测试
python examples/generate_traces.py             # 重新生成运行记录
python examples/verify_live_path.py            # 验证真实模型 HTTP 接入契约
```

## 决策模型

| 工具事实 | 模型动作 | 最终状态 |
|---|---|---|
| 无命中 | finish | `not_found` + 缺口 |
| 同 key 多文档不同答案 | finish | `needs_clarification` + 冲突列表 |
| 单一/一致来源 | finish | `answered` + 引用 |
| 工具连续失败 | finish | `tool_error` |
| 步数超限 | abort | `incomplete` |

## 安全红线

- **无引用不输出答案**：`answered` 必须携带 `quotes`，否则循环层拦截（结构保证）。
- **引用必须来自原文**：测试断言引用文本能在文档中找到。
- **冲突不选边**：D01/D02 冲突时输出空答案 + 双方候选 + 原文。

## 目录

```
src/agent/        核心：models / tools / llm / react_loop
src/main.py       CLI 入口
tests/            可执行测试（23 项）
examples/         运行记录（Trace + CLI 输出）+ 生成/验证脚本
data/             合成制度文档 + 同义词表
docs/             01~05 设计文档
BRIEF.md          实现前说明
```

详见 [docs/01-requirements.md](docs/01-requirements.md) 起的设计文档。
