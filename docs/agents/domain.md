# Domain Docs

本仓库的领域文档布局，以及工程技能探索代码库时应如何消费它。

## 布局：单上下文（single-context）

```
/
├── CONTEXT.md          ← 领域术语表（尚未创建）
├── docs/adr/           ← 架构决策记录（尚未创建）
│   └── 0001-....md
└── src/
```

本仓库无 monorepo 信号（无 `pnpm-workspace.yaml`、无 `workspaces` 字段、无 `packages/*`），因此不使用 `CONTEXT-MAP.md` 多上下文布局。

## 探索之前先读这些

- 根目录的 `CONTEXT.md`
- 根目录的 `CONTEXT-MAP.md`（若存在）：它指向每个上下文各自的 `CONTEXT.md`，读与当前主题相关的那些
- `docs/adr/`：读与即将改动的区域相关的 ADR

这些文件若不存在，**静默跳过** —— 不要报告缺失，也不要主动建议创建。`/domain-modeling` 技能（经由 `/grill-with-docs` 与 `/improve-codebase-architecture` 触达）会在术语或决策真正被敲定时惰性创建它们。

## 用术语表的词汇

当你的输出要命名一个领域概念（工单标题、重构提案、假设、测试名）时，用 `CONTEXT.md` 里的定义，不要漂移成术语表明确回避的同义词。

如果需要的概念还不在术语表里，那是一个信号：要么你在发明项目不使用的语言（重新考虑），要么存在真实空白（记下来交给 `/domain-modeling`）。

## ADR 冲突要显式指出

如果你的输出与既有 ADR 矛盾，显式提出来，不要静默覆盖：

> _与 ADR-0007（事件溯源订单）矛盾，但值得重开，因为……_
