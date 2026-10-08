# 数据源层两段式：Fetcher 与 Parser 分离，adapter 只做编排

每个数据源拆成三段：`Fetcher`（取原始响应，协议 `fetch(url) -> RawResponse{body, content_type, status, fetched_at}`，实现有 HTTP / 无头浏览器 / fixture 回放三种）、`Parser`（纯函数 `parse(raw) -> T`，无 IO）、adapter（组合前两者，输出领域对象）。

回放与 `--live` 的差异被完全吸收进"注入哪个 Fetcher"：五个数据源（新闻、三所价格、PDF）的 adapter 代码里**没有任何 `if replay` 分支**，因此两种模式之间没有可漂移的分支。

## Considered Options

- **一段式**（adapter 内部自己取数 + 解析，只暴露 `fetch_series()`）：少一层。否决，因为 LME 的无头浏览器依赖会硬编码进 adapter，而且模式判断会散进每一个 adapter。
- **折中**（fetcher 可插拔，但解析写在 adapter 里）：解决了注入问题，但解析仍与 adapter 的业务逻辑（symbol 映射、字段改名）缠在一起，无法单独测。

## Consequences

- 这一层不是预设的抽象，是被数据源逼出来的：实测三所里**只有 LME 必须走无头浏览器**（Cloudflare 拦截，`curl` / `requests` / 页面内 `fetch()` 全部 403），GFEX 与 DCE 是直取。"怎么取"本身就有两种实现，所以它必须有地方安放。
- parser 是纯函数，A5 / A6 那批断言可以拿 fixture 里的原始响应直接测 —— 不需要网络，不需要起子进程，不需要 mock 任何东西。
- GFEX / DCE 的 parser 会很薄（近乎字段改名）。保留这一层的理由是"要在默认路径上离线测解析"，不是这一层本身有复杂度。被问到"这算不算过度设计"时，答案在这里。
