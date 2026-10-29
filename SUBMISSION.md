# 交付说明 · 企业知识问答 Agent

> 本文自包含全部评审所需信息（背景、运行、验证、取舍、限制），评审无需其他文档即可上手。

## 提交信息

| 项 | 内容 |
|---|---|
| 题号 | 企业知识问答 Agent（项目题四选一） |
| GitHub URL | https://github.com/kiraTsumugi/knowledge-qa |
| 分支 | `main` |
| 交付 tag | `submission-v1` |
| 运行方式 | CLI |
| 依赖 | 零第三方依赖，Python ≥ 3.10（无需 pip install） |
| 参考示例对照 | 覆盖 lwz1357/agent-campus-submission-example 的目录与验证材料规范，且实现了真实 ReAct 决策 |

> **关于 commit SHA**：本文件被写入最终提交，无法在文件内记录自身 SHA（自引用）。
> 请以 tag 指向的提交为交付版本：
> ```bash
> git rev-list -n1 submission-v1
> ```

## 项目概述

面向企业员工的知识问答 Agent：回答制度/产品问题，**每个答案都附文档 ID 与原文片段**；
文档冲突时**列出冲突并请求确认**，绝不擅自选一个；资料外问题明确返回缺口，**绝不无依据作答**。

**核心业务流程**：员工提问（可带对话历史）→ 模型驱动 ReAct 循环检索文档、读取原文片段、
比对冲突 → 产出「回答 + 引用 + 资料缺口 + 任务状态」。仅回答知识库内问题，不接真实系统。

## 评审入口（先看这两条）

```bash
cd knowledge-qa

# ① 核心：冲突处理全过程 Trace（每步 动作→参数→决策依据）
python -m src.main --q "报销期限多久" -v

# ② 全量测试
python -m unittest discover -s tests -v
```

预期 ①：检索到 D01(30天) 与 D02(15天) 同字段不同原文 → 列出双方引文 + 请求确认，**不选边、不回答 15 天**。

## 目录导览

```
README.md              环境/运行/评审入口
SUBMISSION.md          本文件（自包含交付说明）
BRIEF.md               实现前说明（10 行摘要 + 设计思路）
src/agent/models.py    数据结构（Quote 结构保证引用；状态正交）
src/agent/tools.py     工具层（检索 / 片段读取；只返回事实）
src/agent/llm.py       模型接入（OpenAI 兼容 urllib + 确定性离线 Mock）
src/agent/react_loop.py ReAct 循环（步数上限 8；无引用作答拦截）
src/main.py            CLI 入口
tests/test_agent.py    29 项可执行测试
examples/              运行记录（7 组 Trace + CLI 输出 + INDEX）+ 生成/验证脚本
data/                  合成制度文档（含 D01/D02 冲突样例）+ 同义词表
docs/01~05             需求 / 方案 / 评估 / AI 使用 / 复盘
```

## 需求映射（验收点 → 命令 → 证据）

| 验收点 | 命令 | 状态 | 证据文件 |
|---|---|---|---|
| 明确答案 | `--q "年假有多少天"` | `answered` + D03 引用 | `examples/trace_clear_answer.json` |
| 文档冲突 | `--q "报销期限多久"` | `needs_clarification` + 列冲突 | `examples/trace_conflict.json` |
| 资料外问题 | `--q "食堂几点开饭"` | `not_found` + 缺口 | `examples/trace_out_of_scope.json` |
| 改写相似问题 | `--q "退款什么时候到账"` | `answered` + D05 | `examples/trace_paraphrase.json` |
| 场景限定（无冲突可答） | `--q "出差报销要多久"` | `answered` + D01 | `examples/trace_scoped_no_conflict.json` |
| 上下文追问 | `--q "那它的期限呢" --history "年假怎么休"` | `answered` + D03 | `examples/trace_followup.json` |
| 工具失败 | `--q "触发故障的提问"` | `tool_error` | `examples/trace_tool_failure.json` |
| 替换文档行为改变 | — | 答案/状态随数据变 | `tests/…::TestDataSwap` |
| 引用精度 | 问"到账"引用"退款到账"片段 | 精确引用 | `tests/…::TestQuotePrecision` |
| 边界输入 | 空问题/纯标点/噪声 | `not_found` | `tests/…::TestEdgeInput` |
| 无引用作答拦截 | 模型返回 answered+空 quotes | 循环层拒绝 | `tests/…::TestSafety` |

完整测试清单：29 项，`python -m unittest discover -s tests -v` 全绿。

## ReAct 决策证据（两条不同路径）

`trace_conflict.json` 的完整轨迹（5 步）：

```
step1 search_docs("报销期限多久") → 命中 D01+D02 同字段「报销期限」，原文不同（30 vs 15）
step2 read_doc(D01)               ← 模型逐个读取候选原文核对引用
step3 read_doc(D02)               ← 事实齐备
step4 finish(needs_clarification) ← 列冲突+双方原文+版本日期，请求确认（不选边、空答案）
```

`trace_out_of_scope.json` 走**不同路径**：`search(0 命中) → finish(not_found)`——
**没有**读取文档、**没有**编造答案。同一段循环代码因检索事实不同走出不同决策。

## 核心思路（设计取舍）

1. **工具返回事实，决策权 100% 归模型**：代码里没有 `if 冲突 then 询问` 的分支。
   `search_docs` 返回全部命中片段（含冲突候选），冲突是模型对事实的比较结果。
2. **引用安全是结构保证，不是提示词祈祷**：`answered` 无 `quotes` → 循环层直接拦截，
   降级 `incomplete`。测试断言引用文本必须能在原文中找到。
3. **检索改进（高分点）**：同义词表（数据驱动归一化）+ IDF 加权（稀有词权重高）
   + unique-token 优先（单文档信号词如"出差"命中即锁定）。效果：
   - "出差报销要多久"（有场景限定）→ 依据 D01 回答；
   - "报销期限多久"（泛化）→ 报冲突请求确认。与参考实例完全一致。
4. **按同义词边界切分再生成 n-gram**：避免"退款什么时候到账"经归一化后跨词滑窗
   产生噪声"款时"、误命中"退款时限"（曾实际发生，回归测试已固化）。
5. **数据可替换**：`Tools(data_dir=...)` 支持换数据目录，测试用临时目录替换文档内容，
   断言答案/状态随之改变（对应审核要点"替换文档内容核对行为改变"）。
6. **零依赖**：标准库 `urllib` 直连任意 OpenAI 兼容端点；离线 Mock 消费工具事实做
   确定性决策（边界声明：Mock 只验证流程与决策边界，不证明真实模型决策质量）。
7. **不用框架**：原生循环 ~50 行，LangGraph 等只提供骨架、无增益，故不引入。

## 状态模型

| 工具事实 | 模型动作 | 最终状态 |
|---|---|---|
| 无命中 | finish | `not_found` + 缺口 |
| 同字段多文档不同原文 | finish | `needs_clarification` + 冲突列表 |
| 单一/一致来源 | finish | `answered` + 引用 |
| 工具连续失败 | finish | `tool_error` |
| 步数超限 | abort | `incomplete` |

## 已知限制（诚实声明）

1. **默认离线 Mock 不代表真实 LLM 决策质量** —— 只验证流程、边界与冲突逻辑；
   真实能力需配 `MODEL_BASE_URL / MODEL_API_KEY / MODEL_NAME` 后实测（本次未接真实付费模型）。
   接入方式已用本地 mock server 验证 HTTP 契约（`examples/verify_live_path.py` 通过）。
2. **中文分词为 2-4 字滑窗近似** —— 同义改写覆盖有限，更复杂问法需真实分词/向量检索。
3. **冲突检测按 section_key 分组** —— 跨 key 的语义级冲突可能漏检。
4. **多轮会话未持久化** —— `--history` 由调用方提供。
5. **版本日期不参与裁决** —— 冲突时展示版本日期作为线索，但按题目要求不做"新版本优先"的擅自裁决。

## AI 使用摘要（详见 docs/04）

代码与文档初稿由 AI（Claude Code）生成。人工把关修正：状态语义拆分、冲突检测
（unique-token 优先，修复误报与漏报）、引用精度（同义词边界切分，修复噪声 n-gram）、
工具失败死循环、引用安全硬校验、同义词表噪声词条清理。所有合成数据，无真实隐私或密钥。
