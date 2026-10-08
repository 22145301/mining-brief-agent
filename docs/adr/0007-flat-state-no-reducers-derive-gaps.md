# state 用扁平 TypedDict、零 reducer；缺失靠推导而非累积

`BriefState` 是一个扁平的 `TypedDict`，**没有任何 `Annotated[..., reducer]`**。三个并行 fetch 节点各写自己的 key（`news` / `prices` / `resources`），不往共享列表里累积；缺失信息由 `assemble` 从三个信封（ADR-0005）推导。并行扇出用**静态三边**：`check_scope` 三条 `add_edge` 指向三个 fetch 节点，三条 `add_edge` 收进汇聚节点。

非并发写者一律不带 reducer —— LangGraph 的默认行为就是覆盖，对单写者正确。

## Considered Options

- **给共享的 `errors` 列表挂 `operator.add`**（LangGraph 的常见套路）：能让三个分支并发累积失败原因。否决 —— 它把"缺失"拆成两处：信封里已经有 `source_status` 与 `reason`，共享列表里又存一份，两处会漂移。推导一次比累积两次代码更少，也少一个漂移点。
- **用 `Send` API 动态扇出**：文档明确 `Send` 是给"分支数量运行时才知道 / 每个分支要拿不同输入"的场景，且它传给节点的是**你指定的那份 dict、不是整图累积 state**。我们分支数固定为三、且三者要读同一份 scope，静态边语义更自然。

## Consequences

- 失败分支天然可表达：某个 fetch 彻底挂了，它的 key 就停在初始的 `None`，`assemble` 把 `None` 当"该分支完全失败"，不需要额外的错误通道。
- **不要"顺手"给 state 加 reducer。** 只有当某个 key 真的被两个以上并行分支并发写时才需要，当前没有任何这样的 key。
- `BriefState` 里一个 `Annotated` 都没有，这是刻意的，不是遗漏。
