# 02 · 方案

## 调用流程

```
用户问题 (+ 对话历史)
      │
      ▼
┌──────────────────────────────────────────────┐
│ ReAct 循环 (src/agent/react_loop.py)          │
│  模型 decide() ──► 动作                        │
│      │                                         │
│      ├─ search_docs ──► 命中片段（含冲突候选）  │
│      ├─ read_doc    ──► 原文片段（引用核对）    │
│      └─ finish      ──► answered / needs_      │
│                         clarification /       │
│                         not_found / tool_error│
│      ▲                     │                   │
│      └── 观察结果喂回 ◄─────┘                    │
│  步数上限 8；answered 无 quotes → 拦截          │
└──────────────────────────────────────────────┘
```

## 动态决策（ReAct 的核心）

**工具只返回事实**：`search_docs` 返回全部命中片段（不判断哪个对）；
**冲突是模型对事实的比较结果**，代码里没有 `if 冲突 then 询问`。

三条典型路径：

- **路径 A（明确答案）**：`search → read_doc(核对) → finish(answered+引用)`
- **路径 B（冲突）**：`search(命中 D01+D02 同 key) → read_doc(D01) → read_doc(D02) → finish(needs_clarification+冲突列表)`
- **路径 C（资料外）**：`search(0 命中) → finish(not_found+缺口)`

见 `examples/`。

## 关键设计取舍

### 1. 无引用不允许输出答案（结构保证）
`_build_result` 检查：`status==answered` 且 `quotes` 为空 → 拦截，降级 `incomplete`。
这不是"提示模型要引用"，而是**循环层的硬校验**。

### 2. 冲突检测：同 section_key 多文档且原文不同
`OfflineMock._detect_conflict` 按 `section_key` 分组，≥2 文档且文本不同 → 冲突。
输出双方**引用+版本日期+数值**，请求用户确认适用范围，**不选边**。

### 3. 检索改进：同义词归一化 + IDF 加权 + unique-token 优先
- **同义词表**（数据驱动）：`多久→期限`，改写问法归一化后命中同一文档。
- **IDF 加权**：`1/df`，稀有词权重高，通用词（"期限"）权重低。
- **unique-token 优先**：命中仅在单一文档出现的词（如"出差"）→ 锁定该文档；
  否则按相对阈值（60%）过滤低权误召回。
这套组合让"出差报销要多久"（有场景限定）答 D01、"报销期限多久"（泛化）报冲突 —— 与参考实例一致。

### 4. 上下文追问改写
问题含代词（它/那/这个…）时，拼接最近一条用户历史成完整检索词，检索动作带上历史主题词。

### 5. 数据可替换
`Tools(data_dir=...)` 支持换数据目录；测试用临时目录替换文档内容，
断言答案/状态随之改变（审核要点）。

### 6. 零依赖 + Mock 与真实模型同构
标准库 `urllib` 直连 OpenAI 兼容端点；`ModelClient.decide` 唯一接口，切换后端不改循环。

## 技术栈

- Python 3.12，标准库 only
- 模型：OpenAI 兼容 `/chat/completions`（`response_format=json_object`）
