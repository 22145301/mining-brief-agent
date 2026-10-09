# `PricePoint` 加 `publisher`：合约所在的交易所未必是数据的发布方

`PricePoint` 与 `PriceSource` 各加一个**必需的** `publisher: str`，值是**人声明的**数据发布方，一路带到 `Citation.publisher`。铁矿石那条是 `新浪财经`（合约归 DCE），锂与铜分别是 `GFEX` 与 `LME`（发布方就是它自己）。

这是对已冻结 PRD §6.1 的**第二处契约加字段** —— 第一处是 ADR-0004 的 `requested_date`，那条 ADR 里"唯一一处契约加字段"的说法自本 ADR 起不再成立，已在原处加注指向此处。加字段不破坏题面给定的工具签名。

## 背景：这个字段是从产物的一处自相矛盾里长出来的

2026-10-09 跑 `--live` 验收时，产物第 [22] 条印成这样：

```
铁矿石 682.5 元/吨（DCE I0，2026-10-08，当日）
**[22]**（价格）DCE I0
  DCE · 2026-10-08
  <https://finance.sina.com.cn/futures/quotes/I0.shtml>
```

正文与引用块的标题 `DCE I0` 是对的 —— 那是**合约**，读者靠它认行情。错的是出处那一行：它写 `DCE`，下面那条链接却指向 `finance.sina.com.cn`。同一条引用里"谁给的"有两个互不相同的答案，读者无从判断该信哪一头。

根子不在文案，在契约：

- `PricePoint` 只有 `exchange`，没有发布方，于是 `nodes.py` 只能把合约方当发布方印出去；
- 而 `Citation.publisher` 的契约原文是「`title` / `url` / `publisher` / `timestamp` 四个字段是**原样搬运**工具返回值」（`contracts/brief.py`）—— 工具根本不返回发布方，那一行搬不出东西来，只能现场编一个。

也就是说，**这条引用违背了它自己的契约**。`config/sources.py` 的注释当时已经写明"引用块里 `publisher` 记的是新浪财经，不是 DCE：数据的**发布方**是谁就写谁" —— 那份注释描述的是一个不存在的字段。这不是注释写错，是设计意图没落进契约。

需要强调的是：**数据事实从头到尾没错。** 铁矿石那个数确实取自新浪转载的 DCE `i` 合约，`source_url` 如实指向新浪，且与 GFEX 官方口径交叉核对过（2026-10-08 结算价、持仓量两处一致）。这一处要修的自始至终只是**命名**。

## Considered Options

- **改注释，让它如实描述已实现的行为（发布方 = 交易所，取数点由 URL 承载）**：零代码改动。否决 —— 等于承认"发布方"这个概念在产物上不表达，而 `DCE · <日期>` 配一条新浪链接的割裂感原样保留；更要紧的是它把 `Citation.publisher` 的契约改成一句空话（"原样搬运工具返回值"搬的是个同名不同义的字段）。
- **把正文的 `DCE I0` 也改成 `新浪财经`**：看起来"统一"了。否决 —— 合约名是读者认行情用的东西，从正文里拿掉它，那一行就只剩一个陌生的发布方名称，反而更难读。正文说**合约**、引用说**出处**，本来就是两件事。
- **给 `PriceSource` 加 `publisher`，但 `PricePoint` 不加，让节点去查登记表**：能少动一处契约。否决 —— `nodes.py` 是纯函数节点，它只看得见 state 里的 `PricePoint`；让它回查 `PRICE_SOURCES` 就把"数据源登记表"这条依赖带进了排版层，而这一层现在对数据源一无所知。
- **`publisher` 默认为 `exchange`**：省掉三处显式声明。否决 —— 见下。

## Consequences

- 三处解析器（`parse_gfex_daily` / `parse_sina_kline` / `parse_lme_hero`）各自从 `source.publisher` 取，`nodes.py` 用 `latest.publisher`。**没有任何一处默认为 `exchange`**：发布方读不出来、写错了也不报错，只会在产物里安静地印一个错出处 —— 这与单位（`ReportColumn.scale`）是同一类必须由人声明、由人核对的东西，所以它同样是**必填**。三个源里只有铁矿石与 `exchange` 不同，一旦允许默认，它必然被写错。
- 正文与引用块的分工现在写死在测试里：正文留 `DCE I0`（合约），引用块的 `publisher` 是 `新浪财经`（发布方），`title` 仍是 `DCE I0`。`tests/test_prices_section.py::test_the_citation_names_the_publisher_not_the_exchange` 把这条钉住，防止日后有人"顺手统一"其中一处。
- **回放的 key 不受影响**：`narrate` 节点的输入由 `narrative_payload` 构造，它只取 `fact.text`，不含 `citation`；事实文本一字未动（仍用 `latest.exchange`）。这是刻意的 —— 把发布方塞进正文会顺带作废六节的全部 LLM 录播，而这次修的是出处，不是正文。
- 若将来接入一个"合约与发布方相同"的新源，必须仍显式写出 `publisher`。写上等于没说，但**省略不了** —— 这是代价，也是这个字段唯一的防线。
