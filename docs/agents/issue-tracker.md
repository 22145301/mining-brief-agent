# Issue tracker：本地 Markdown

本仓库没有 git remote，issue 与 spec 一律以 Markdown 文件存放在 `.scratch/` 下，不走 GitHub / GitLab Issues。

## 目录约定

- 一个 feature 一个目录：`.scratch/<feature-slug>/`
- 需求冻结在 `.scratch/<feature-slug>/PRD.md`，**不随实现改动**
- spec 为 `.scratch/<feature-slug>/spec.md`（由 `/to-spec` 从 PRD 综合而来）
- 工单一张一个文件：`.scratch/<feature-slug>/issues/<NN>-<slug>.md`，从 `01` 起编号，**禁止**把多张工单合并成一个 tickets 文件
- 工单文件顶部的 `**Status:**` 行记 state 角色、`**Category:**` 行记 category 角色（取值见 `triage-labels.md`）
- 评论与讨论历史追加到文件底部的 `## Comments` 标题下

## 为什么 spec 与 PRD 是两个文件

最初配置时把两者等同了（"spec 就叫 `PRD.md`"），那是还没走到 `/to-spec` 时的误判。实际走到这一步才发现它们不是一回事：

| | `PRD.md` | `spec.md` |
|---|---|---|
| 内容 | 需求（问题、目标、契约、验收标准） | 实现规格（用户故事、实现决策、测试切面） |
| 生命周期 | 冻结，17 轮拷问的产物，**不随实现改动** | 实现期可修订 |
| 谁写 | 用户与我一起 | `/to-spec` 从 PRD 综合 |

同一个文件里混两种生命周期，会让"需求变了没有"这个问题失去答案。`to-tickets` 从调用参数取 spec 路径，因此这个偏离不影响技能链。

`<feature-slug>` 用小写连字符，当前唯一 feature 是 `mining-daily-brief`。

## commit message 如何引用工单

本地 tracker 没有 `#123` 式编号体系，而 `/code-review` 依赖"从 commit message 里找 issue 引用"这一轴。约定：

- 引用某张工单时写工单编号，例：`实现 03-pilbara-mcp-server：…`
- 引用 feature 整体时写目录 slug，例：`…（mining-daily-brief）`

## 当技能说"发布到 issue tracker"

在 `.scratch/<feature-slug>/` 下新建文件（目录不存在就建）。

## 当技能说"取出对应工单"

直接读该路径的文件。用户通常会直接把路径或编号给你。

## Wayfinding 操作（`/wayfinder` 用）

map 是一个文件，每张工单一个 child 文件。

- **Map**：`.scratch/<effort>/map.md`（承载 Notes / Decisions-so-far / Fog 正文）
- **Child ticket**：`.scratch/<effort>/issues/NN-<slug>.md`，从 `01` 起编号，问题写在正文里。`Type:` 行记录工单类型（`research` / `prototype` / `grilling` / `task`）；`Status:` 行记录 `claimed` / `resolved`
- **Blocking**：顶部 `Blocked by: NN, NN` 行。所列文件全部 `resolved` 时该工单才算解锁
- **Frontier**：扫描 `.scratch/<effort>/issues/`，取"未关闭、未阻塞、未被认领"的文件，编号最小者优先
- **Claim**：动手前先写 `Status: claimed` 并保存
- **Resolve**：在 `## Answer` 标题下追加答案，置 `Status: resolved`，再把一条上下文指针（要点 + 链接）追加到 `map.md` 的 Decisions-so-far

## 非目标档案

`/triage` 把"已拒绝的需求"沉淀到仓库根目录的 `.out-of-scope/`：一个概念一个文件（不是一 issue 一个），按需惰性创建，当前尚未创建。PRD §2.2「非目标」N1–N4 是该目录的首批候选记录。
