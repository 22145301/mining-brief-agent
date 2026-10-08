# 04: 价格 · LME 走无头浏览器

**What to build:** 铜价出现在日报里。这是三个价格源里**唯一需要无头浏览器**的一个——Cloudflare 拦掉全部普通 HTTP 客户端，只能做真实页面导航——也是唯一带固有延迟的。

**Blocked by:** 03

**Status:** ready-for-agent

**Category:** enhancement

- [ ] 浏览器 Fetcher 实现与 HTTP Fetcher **同接口**，adapter 一行都不改（ADR-0003 的两段式在这里兑现价值）
- [ ] LME adapter 走真实页面导航取 `span.hero-metal-data__number`，不是 HTTP 直取
- [ ] 铜价 `delayed` 恒为 `true`；且它与"回退到了更早日期"是**两件不同的事**，测试分别断言（ADR-0004）
- [ ] 浏览器路径超时独立配置（起始 45s），与 HTTP 路径的 15s 分开，都只放在配置里
- [ ] **缺浏览器时明确报错，不静默降级成"无数据"**——静默降级会让数据缺失伪装成数据源没数据
- [ ] LME 的录播与故障 fixture 就位
- [ ] 日报"价格走势"一节有三项（锂 / 铜 / 铁矿石），截止时间各不相同且如实标注；铜的延迟属性在产物里可见
