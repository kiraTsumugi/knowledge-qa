# 交付说明 · 企业知识问答 Agent

## 提交信息

| 项 | 内容 |
|---|---|
| 题号 | 企业知识问答 Agent（项目题四选一） |
| GitHub URL | ⬅️ 待填（如 https://github.com/<用户名>/knowledge-qa）|
| 分支 | `main` |
| 交付 tag | `submission-v1` |
| 运行方式 | CLI |
| 依赖 | 零第三方依赖，Python ≥ 3.10 |

> **关于 commit SHA**：本文件被写入最终提交，无法记录自身 SHA（自引用）。
> 请以 git tag `submission-v1` 指向的提交为交付版本：
> ```bash
> git rev-list -n1 submission-v1
> ```

## 一句话概述

面向员工的知识助手：回答问题并**附文档 ID 与原文片段**；文档冲突时**列出冲突并请求确认**，
绝不擅自选一个；资料外问题返回缺口，**无依据不回答**。

## 评审入口（先看这里）

```bash
cd knowledge-qa

# 核心：冲突处理全过程（每步 动作→参数→决策依据）
python -m src.main --q "报销期限多久" -v

# 全量测试
python -m unittest discover -s tests -v
```

预期：检索到 D01(30天) 与 D02(15天) 同 key 不同原文 → 列冲突 + 请求确认，**不选边**。

## 需求映射（验收点 → 证据）

| 验收点 | 命令 | 状态 | 证据 |
|---|---|---|---|
| 文档冲突 | `--q "报销期限多久"` | `needs_clarification` | `examples/trace_conflict.json` |
| 明确答案 | `--q "年假有多少天"` | `answered` + 引用 | `examples/trace_clear_answer.json` |
| 资料外问题 | `--q "食堂几点开饭"` | `not_found` | `examples/trace_out_of_scope.json` |
| 改写相似问题 | `--q "退款什么时候到账"` | `answered` | `examples/trace_paraphrase.json` |
| 场景限定（无冲突可答）| `--q "出差报销要多久"` | `answered` + D01 | `examples/trace_scoped_no_conflict.json` |
| 上下文追问 | `--q "那它的期限呢" --history "年假怎么休"` | `answered` | `examples/trace_followup.json` |
| 工具失败 | `--q "触发故障的提问"` | `tool_error` | `examples/trace_tool_failure.json` |
| 替换文档行为改变 | — | 答案/状态随数据变 | `tests/test_agent.py::TestDataSwap` |

## 核心思路（文件里放不下的取舍）

1. **工具返回事实，冲突是模型的比较结果**：代码里没有 `if 冲突 then 询问`。
   `search_docs` 返回全部命中片段，模型读到 D01+D02 同 key 不同原文后决定请求确认。
2. **引用安全是结构保证**：`answered` 无 `quotes` → 循环层直接拦截，不信任 prompt 自律。
   引用文本经测试断言必须来自原文。
3. **检索改进（高分点）**：同义词表（数据驱动）+ IDF 加权 + **unique-token 优先**——
   "出差报销要多久"（含单文档信号词）答 D01；"报销期限多久"（泛化）报冲突，与参考实例一致。
4. **数据可替换**：`Tools(data_dir=...)`，测试用临时目录换文档内容验证行为改变（审核要点）。
5. **零依赖**：标准库 `urllib` 直连 OpenAI 兼容端点；离线 Mock 消费检索事实。
6. **不用框架**：原生循环 ~50 行，引入 LangGraph 等无增益。

## 已知限制

1. 默认离线 Mock 为确定性规则器，**不代表真实 LLM 决策质量**；真实能力需配 `MODEL_*` 实测。
2. 中文分词为 2-4 字滑窗近似，同义改写覆盖有限。
3. 冲突检测按 `section_key` 分组，跨 key 的语义冲突可能漏检。
4. 多轮会话由调用方提供 `--history`，未做持久化。

## 目录导览

```
README.md              环境/运行/评审入口
SUBMISSION.md          本文件
BRIEF.md               实现前说明
src/agent/             models / tools / llm / react_loop
tests/test_agent.py    23 项测试
examples/              Trace + CLI 输出 + INDEX + 生成/验证脚本
data/                  合成制度文档 + 同义词表
docs/01~05             需求/方案/评估/AI使用/复盘
```
