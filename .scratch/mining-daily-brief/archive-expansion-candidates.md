# 档案扩展候选（备查，**未采纳**）

> **这份文件不是交付物，也没有被任何代码引用。** 它记录的是"以后想扩 `config/archive.py`
> 时可以往哪儿找"，不是"这些矿已经在系统里"。
>
> **读之前必须先读这段可信度声明。** 下表来自三个**同行 agent 会话**的调研，**未经我逐条
> 核实**。唯一一条我独立核过的是 Kamoa-Kakula（下方标注）。agent 自己就自查出若干问题
> （报告体系标错、中文名为音译、链接只在 Wayback），**逐条列在每一行里，不要跳过备注列**。
> 采纳任何一行之前，至少要重新确认三件事：报告体系、资源量表能不能抽成文本、直链是否稳定。

**为什么要提这一嘴**：`config/archive.py` 现有 8 座矿（Pilgangoora、Mount Marion、Wodgina、
Kamoa-Kakula、Quellaveco、Los Pelambres、Gudai-Darri、Eliwana）。下表全部是**这 8 座之外**
的候选。

---

## 0. 采纳的代价（先看这个再决定要不要扩）

扩档案会改 `commodity_in_scope`，进而改 `resolve_entities` 的输入 —— 也就是**改录播寻址的
输入哈希**（ADR-0009）。具体后果：

1. **现有的 LLM 录播会全部失配**，`--live` 之外跑不出日报（06 号票扩档案时就重录过一次）。
2. **已验的产物 sha256 会变**：`0928bd75d0d1056e…`（Pilbara 那句）与 `880fb7af67314cca…`
   （整档案那句）都不再成立，README / RUN.md / 工单 10 里引的哈希要跟着改。
3. 新增矿若进不了"抽到表"那一档，储量节会多出若干条"数据缺失" —— **这是正确行为**，
   但产物会变长。

一句话：**扩档案不是改一行常量，是一次需要重录 + 重验的变更。**

---

## 1. 锂（agent 实际下到 6 份 `%PDF`，均 HTTP 200）

| id | 公司 | 项目 | 体系（agent 标注） | 直链 | 字节 | sha256 前 12 |
|---|---|---|---|---|---|---|
| greenbushes | IGO Limited | Greenbushes（FY24） | JORC | `igo.com.au/site/pdf/758934b3-…/FY24-Mineral-Resources-and-Ore-Reserves-Statement.pdf` | 13 108 553 | `bb83903492ee` |
| greenbushes | IGO Limited | Greenbushes（FY26） | JORC | `igo5.live.irmau.com/site/PDF/0caef7df-…/FY26MineralResourcesandOreReservesReport` | 2 343 038 | `b9db4e8d85d4` |
| whabouchi | Rio Tinto | Whabouchi | JORC | `cdn-rio.dataweavers.io/-/media/content/documents/invest/reserves-and-resources/2025/2025-lithium-mineral-resources-ore-reserves.pdf` | 10 464 532 | `82e15c45cf40` |
| james-bay | Rio Tinto | James Bay | NI 43-101 | `cdn-rio.dataweavers.io/…/operations/ar-lithium/jb-technical-report-eng-2022.pdf` | 19 410 303 | `0ab0675b1dcd` |
| mt-cattlin | Rio Tinto | Mt Cattlin | JORC | 与 whabouchi 同一份 Rio Tinto 2025 锂报告 | — | — |
| authier | Sayona Mining | Authier | NI 43-101 | `globexmining.com/wp-content/uploads/2026/06/20230412_Authier_Report.pdf` | 17 384 776 | `b08909681947` |
| rose | Critical Elements | Rose | NI 43-101 | `cecorp.ca/wp-content/uploads/161-14192-03_RPT-01_R1_V1_CELC_Rose-FS-2022.pdf` | 35 621 585 | `3c1005914e59` |

**已知缺口（agent 没拿到 `%PDF`，原因照抄）**：Wodgina 与 Mt Marion 只发 ASX 公告页（weblink
直链两次 404）；Finniss 公告直链 404、能下的 PFS 公告 20 页内无可抽的 Li₂O 表正文；
Moblan 官网 FS 链接 200 但 `content-type` 是 `text/html`（是网页不是 PDF）。

> ⚠️ **Wodgina 与 Mt Marion 已经在 `config/archive.py` 里了**（06 号票按"公司不单独发项目级
> 报告"记为数据缺失）。这两行只说明 agent 也没找到，不构成新信息。

---

## 2. 铜（agent 实际下到 5 份，均 HTTP 200 / `application/pdf`）

| id | 公司 | 项目 | 体系 | 直链 | 字节 | sha256 前 12 | 备注 |
|---|---|---|---|---|---|---|---|
| **kamoa-kakula** | Ivanhoe Mines | Kamoa-Kakula | NI 43-101 | `ivanhoemines.com/wp-content/uploads/1025010-Kamoa-Copper-Kamoa-Kakula-MRMR-Update-Technical-Report-31-March-2026_SEDAR-Copy.pdf` | **36 169 167** | **`29c81fcf304d`** | ✅ **我独立核过**：与工单 06 记的字节数、哈希**逐位一致** |
| warintza | Solaris Resources | Warintza | NI 43-101 | Dropbox（`…Warintza-PFS-NI-43-101_SEDAR-Copy.pdf?raw=1`） | 38 657 607 | `914455367b47` | 中文名为 agent 音译，非官方 |
| vizcachitas | Los Andes Copper | Vizcachitas | NI 43-101 | `losandescopper.com/site/assets/files/3685/techreport.pdf` | 28 282 582 | `b32c6fa19393` | ⚠️ **资源量表是位图**，抽不出文本 |
| los-helados | NGEx Minerals | Los Helados | NI 43-101 | `ngexminerals.com/wp-content/uploads/2025/08/Los-Helados-Technical-Report.pdf` | 13 936 810 | `66f9b489a679` | 中文名为音译 |
| platreef | Ivanhoe Mines | Platreef | NI 43-101 | `ivanhoemines.com/wp-content/uploads/250329-Platreef-IDP25_RevF.pdf` | 23 857 964 | `0202de5e3026` | ⚠️ **主矿种是 PGM（Pt-Pd-Rh-Au），铜是副产品** —— agent 自陈"非严格铜矿，是否收录请你定" |

**已知缺口**：Cobre Panama（q4cdn 直链 404，备用归档站返回 `image/jpeg`）；Marimaca（官网
两条候选路径被 Cloudflare 拦，返回 202 挑战页）；Filo del Sol（filocorp.com 直链 200 但实为
114 字节 HTML 跳转页）；Cactus（首次 SSL 握手失败、重试 502，两次即停）；Copper World
（只搜到 PEA 新闻稿，NI 43-101 在 SEDAR+/EDGAR，无直链）。

---

## 3. 铁矿石（agent 实际下到 6 份，均 HTTP 200 且 `%PDF-` 开头）

| id | 公司 | 项目 | 体系 | 直链 | 字节 | sha256 前 12 | 备注 |
|---|---|---|---|---|---|---|---|
| bloom-lake | Champion Iron | Bloom Lake | NI 43-101 | `championiron.com/wp-content/uploads/2023/10/cia-technical-report-ni-43-101-2023-…r00.pdf` | 16 586 397 | `6c877b6dbe6c` | |
| chichester-hub | Fortescue | Chichester Hub / Iron Bridge | JORC | `edge.sitecorecloud.io/…/fy24-annual-report.pdf` | 11 735 828 | `56b669d7d0e4` | ⚠️ 资源量表在**年报正文 P54**，非独立技术报告 |
| simandou | Rio Tinto | Simandou | ⚠️ **S-K 1300**（agent 表中填 JORC 是**错的**） | `cdn-rio.dataweavers.io/…/2024-simandou-technical-report-summary.pdf` | 7 751 745 | `d7b6e549a33e` | 表在 P11；agent 自陈"若这一列要求严格应写 S-K 1300" |
| serra-norte | Vale | Serra Norte / Carajás | ⚠️ **S-K 1300**（同上） | `sec.gov/Archives/edgar/data/917851/000129281426001844/ex96-1.pdf` | 20 222 549 | `b216680d15a5` | 表在 P18 |
| koolan-island | Mount Gibson Iron（现 MGX） | Koolan Island | JORC 声明 | `mtgibsoniron.com.au/wp-content/uploads/07-10-2014-MGX-Mineral-Resources-and-Ore-Reserves-at-30-June-2014.pdf` | 1 304 133 | `040205a8977e` | ⚠️ 截止 **2014-06-30**，非最新一期；表在 P3 |
| mary-river | Baffinland（现 ArcelorMittal 独资） | Mary River | NI 43-101 | `web.archive.org/web/20230106012703id_/…/MaryRiver_Technical_012011.pdf` | 7 213 187 | `311e168e4a44` | ⚠️ **只有 Wayback 快照**，原站直链已失效 |

**已知缺口**：Marampa（只公开可持续发展报告，无项目级技术报告全文）；Nimba（2021 Hatch PFS
只发新闻稿）；Kami（官网项目页无 PDF 直链，唯一下到的是 3 页新闻稿）；Savage River
（官网未暴露直链，MarketIndex 镜像 403）。

> ⚠️ **Fortescue 已在 `config/archive.py` 里**（Gudai-Darri / Eliwana 按"JORC 体系但不单独发
> 项目级报告"记为数据缺失）。上面那行年报直链对它有参考价值，但**不是**新矿山。

---

## 4. 采纳前必须重做的三件事（每座矿）

1. **核报告体系。** 上表"体系"一列有多处是 agent 的推断，已标出两处 S-K 1300 被误填成 JORC。
   体系写错 → `standard` 写错 → **R1 / R5 会引错法条**（`docs/risk-rules.md` §6 末）。
2. **核表能不能抽。** Vizcachitas 的表是位图，已是一个现成的反例。
3. **核直链稳定性。** Mary River 只有 Wayback；Koolan Island 是 2014 年的声明。

这三件事做完之前，任何一行都不该进 `config/archive.py`。
