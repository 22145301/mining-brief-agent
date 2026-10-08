# Triage 标签词表

技能内部说"角色"，本文件把角色映射到本仓库实际使用的标签串。本仓库沿用默认词表：**标签串与角色同名**，右列与左列一致，不做改名。

## Category 角色（每个已分级 issue 恰好一个）

| 角色 | 本仓库标签串 | 含义 |
| --- | --- | --- |
| `bug` | `bug` | 有东西坏了 |
| `enhancement` | `enhancement` | 新功能或改进 |

## State 角色（每个已分级 issue 恰好一个）

| 角色 | 本仓库标签串 | 含义 |
| --- | --- | --- |
| `needs-triage` | `needs-triage` | 待维护者评估 |
| `needs-info` | `needs-info` | 等报告人补充信息 |
| `ready-for-agent` | `ready-for-agent` | 规格完整，可交给 AFK agent |
| `ready-for-human` | `ready-for-human` | 需人工实现 |
| `wontfix` | `wontfix` | 不予处理 |

当技能提到某个角色（如"打上 AFK-ready 标签"），取上表右列对应的标签串。

## 本地 Markdown tracker 上怎么落盘

本仓库没有标签机制，角色写成工单文件里的一行：

- state 角色 → `**Status:** <角色串>`，与 `/to-tickets` 生成的工单模板一致
- category 角色 → `**Category:** <角色串>`

**注**：state 行的形状来自 `/to-tickets` 实际生成的模板；category 行是上游技能未定义、由本仓库按同一形状外推的约定。
