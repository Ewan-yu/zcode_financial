---
name: mood-collect
description: 市场情绪指标层采集与扩展（docs/webapp-design.md §3.10）。每日收盘后采集破净股占比截面入 workbench.db；知识星球「复利人生」情绪系列每出新文章时登记新指标并补锚点。产出页面 /mood。
---

# 市场情绪指标采集（mood-collect）

> 权威存储：`data/workbench.db` 表 `mood_indicators` / `mood_obs` / `mood_anchors`。
> CLI：`python tools/mood.py`（init/register/add/import-wencai/import-legulegu/anchor-add/latest/series/gaps/selftest）。
> 展示：`python webapp/app.py` → http://127.0.0.1:8787/mood（指标卡自动渲染 active=1 的注册指标）。
> 历史底座：乐咕乐股破净统计逐日日线（2005-01 起，5272 日，沪深口径与作者完全一致）已入库；
> 温度与历史百分位用自有序列分位，问财截面只做**前向增量**。

## 一、每日采集（交易日收盘后，约 3-4 次 MCP 调用）

前置：确认是交易日（非交易日跳过，AGENTS.md 第 9 条）。D=当日（YYYYMMDD）。

1. **全A家数（分母）**：查 `data/cache/all_a_count_*.json`，7 天内直接用；否则调
   `hexin-index sector_data code=001005010 date=<D>` 取「成份股个数」，写新 cache 文件。
   **口径变更（2026-10-18）：对齐作者改不含北交所。** 分母优先方案（待实测）：
   sector_data 传板块名「沪深A股」取当日家数；若不支持则用 001005010 全A家数 − 北交所家数
   （问财「{D}北交所A股」返回名单可数）。分子句式同步改：
2. **问财破净三段（分子，固定句式，规避 50KB 返回截断）**，调
   `hexin-stock search_stocks` domain=stock：
   - `市净率大于0且小于0.5的沪深A股`
   - `市净率大于等于0.5且小于0.75的沪深A股`
   - `市净率大于等于0.75且小于1的沪深A股`
   （「沪深A股」排除北交所；import-wencai 另有 .BJ 后缀强制剔除双保险。首用日期须核对
   返回无 920xxx.BJ 代码且句式能被问财解析；若「沪深A股」解析失败，退回「A股」句式+
   依赖 .BJ 剔除，分母同步减北交所家数。）
   每段返回应为完整名单（无截断标记）。若被截断：把该段再对半细分区间重拉。
3. **快照落盘** `data/snapshots/<D>/mood_net_break_s{1,2,3}.json`，格式
   `{"查询":句式,"工具":"hexin search_stocks","口径日期":"<D>","列":[...],"行":[{股票代码,股票简称,市净率},...]}`
   （2026-10-16 首采有现成样例）。
4. **入库**：
   ```
   python tools/mood.py import-wencai --key net_break_pb --date <YYYY-MM-DD> \
     --denom <家数> --files data/snapshots/<D>/mood_net_break_s1.json,...s2,...s3
   ```
   （自动：合并去重、剔除简称含「退」的退市整理股、算占比）
5. `python tools/mood.py latest` 核对，观察是否触及关键带：
   - **≥10%**：历史最悲观 8% 时段（作者口径的深度低估区）→ 在当日复盘报告的 L1 环境节引用
   - **≤1%**：趋近顶部信号区

## 一点五、断档检测与自动回补（用户不每日打开时的续档机制）

指标为分位/趋势型，**中断几天不破坏有效性**（分位计算对缺日不敏感）；回补的价值在于
不漏掉大底期间的峰值与 10% 关键带触发。每次采集（或用户说"更新情绪指标"）时先做：

1. **取交易日历**：`wind-index get_index_kline` 000001.SH 拉「最后观测日 ~ 今天」小段
   （几天到几周，体积极小），日期数组落盘 `data/cache/trading_days_<起>_<止>.json`。
2. **检测缺口**：`python tools/mood.py gaps --key net_break_pb --days-file <上述文件>`
   （只报首个观测日之后的缺口；起点之前是未采集历史，不算断档）。
3. **逐日回补**（问财历史日期筛选，已实测支持任意历史日）：对每个缺口日 D 调三段
   `D日市净率大于0且小于0.5的A股` 等（句式="2026年10月14日市净率大于0且小于0.5的A股"），
   快照落盘 `data/snapshots/<D>/mood_net_break_s{1,2,3}.json` → `import-wencai`。
   缺口 N 天成本≈3N 次调用；N>5 时提示用户确认或只补最近 5 日（成本控制）。
4. **⚠ 日期校验红线（必做）**：问财对非交易日查询会**静默回退到上一交易日取数**
   （2026-10-18 实测：查 10-17 周六返回 [20261016] 数据）。因此回补每段必须核对
   返回列名日期==查询日（如 `市净率(pb)[20261014]`），不一致即该日非交易日/异常，
   **跳过不得入库**。交易日历来自步骤 1，正常不会踩到；该校验是最后防线。

## 一点七、历史底座与断档批量回补（乐咕乐股通道，2026-10-18 起为首选）

**net_break_pb 的逐日历史已一次性解决**：乐咕乐股《全部A股破净股统计》
（https://legulegu.com/stockdata/below-net-asset-statistics?marketId=1）页面 API 返回
2005-01-05 起逐日 `{date, belowNetAsset, totalCompany, close}`，免登录免 VIP，
`totalCompany≈5226` 即沪深A股家数——**与作者口径完全一致**（2024-09-18 乐咕 16.43% ==
作者锚点 16.43%，逐值对上）。问财 dt-scout 分片采样模式（2 日期/代理、只回 JSON 计数）
自此对破净指标停用，留作其他新指标无现成历史源时的备选方案。

**刷新/回补流程**（断档>5 天、季度校准、或作者口径需要复核时跑一次）：

1. 内置浏览器打开上述页面（研究性抓取，不走 MCP、不占配额；AGENTS.md 第 2 条的
   「不引入 Python 直连数据源」约束不变——此为 AI 会话浏览器取证式抓取，非管线自动化）。
2. 页面上下文 fetch 页面自己的 API（token 从 `performance.getEntriesByType("resource")`
   里的 `/api/stock-data/below-net-asset-statistics?marketId=1&token=...` 取，每次会话不同），
   返回 `{data:[...], descriptions, vip, ...}`。
3. 快照落盘 `data/snapshots/<当日>/mood_legulegu_below_net_asset_m1_<当日>.json`
   （含 retrieved_at/source/url/caliber 元数据，样例 20261018）。
4. 入库：`python tools/mood.py import-legulegu --file <快照>`（INSERT OR REPLACE，
   value=count/totalCompany*100；同日与问财增量重叠时以乐咕覆盖，口径最齐）。
   支持可选 `--from-date` 限定只补某日之后。

前向日常增量（当日截面）仍走第一节问财三段（MCP，合规管线）；两者同日并存时以乐咕为准。
乐咕 2026-10-16 = 468/5224=8.96%，问财含BJ读数 470−2(BJ破净)=468，逐日可互验。

## 二、新文章扩展流程（作者出新指标维度时）

1. 完整阅读文章（含图表）→ 提炼：指标定义、口径、方向语义、历次顶底参考值。
2. **先登记采集目录**（AGENTS.md 第 14 条）：`docs/webapp-design.md` §3.10 表格加行。
3. **注册指标**：
   ```
   python tools/mood.py register --key <英文key> --name <名> --domain <估值/情绪/拥挤度/广度> \
     --unit <%或倍> --source <工具> --method "<口径定义，含剔除规则>" --direction <1或-1>
   ```
   direction：+1=值越高越悲观（底部信号型）；-1=值越高越乐观（顶部信号型）。
4. **锚点入库**：文章给的历次顶底值逐条 `anchor-add`，--source 写明文章标题与日期
   （引用未复算）；后续如用我方口径复算，`anchor-verify` 回填。
5. **定采集句式**：问财能否直接筛出该截面（参照三段法拆区间防截断）？能→写入本技能
   「每日采集」节新条目；不能→评估 wind 通道或降频（周/月），在 method 里注明。
6. 页面无需改码：`/mood` 自动渲染新注册指标卡；若新指标需要专属图表再改 mood.html。
7. 采集一次当日截面入库（同流程一）。

## 三、口径与红线（不可漂移）

- 分子口径：0<PB<1（净资产为正自动排除资不抵债；PB<0 不纳入）、含 ST、**不含北交所
  （2026-10-18 对齐作者）**、剔除简称含「退」的退市整理股；分母=沪深A股家数。
- **历史底座已全量入库**（乐咕乐股日线 5272 日，沪深口径），旧含北交所问财采样点已被
  import-legulegu 覆盖 33 处（REPLACE，最大偏差 8.29pp 即 BJ 口径差），**无需再做 13 点
  重校**；作者 12 个锚点日期全部落在乐咕序列内，页面锚点自动去重不双画。
- 作者锚点（mood_anchors）保留作对照：2005-07-11 锚点 24.4% vs 乐咕同日 20.81%（998 点
  区域，口径/时点微差）；2024-09-18 两者完全一致（16.43%）。温度与分位**只对自有序列
  内部计算**（5272 日，≥250 达标）；作者尾部分布三点仅作对照备注（页面已固化）。
- 前向引用：报告/复盘引用本指标结论时注明 `mood_obs(net_break_pb) + 复利人生系列`；
  触发关键带（≥10% 深度低估 / ≤1% 过热区）时按 AGENTS.md 第 6 条登记判断。
- 配额：日常增量每日 3-4 次 MCP；乐咕刷新 0 次 MCP（浏览器抓取）。
- 问财历史日查询注意（其他指标仍适用）：非交易日静默回退上一交易日（列名日期红线）；
- 配额：本采集每日 3-4 次，计入 AGENTS.md 第 14 条 10-15 次/日预算。

## 四、已停用/受限通道备忘（2026-10-18 实测）

- `wind-economic EDB` 指标取数整体受限（M0071672、R3515837 均报「超限」）→ market_pb
  长历史线搁置（指标已注册 direction=-1，待权限恢复按分段下载回补）。
- `hexin get_stock_performance` 周行情配额易爆（-4302）且试用限 5 年 → 上证指数日线走
  每日复盘既有链路（daily_k_4codes → market_daily），不单独回补历史。
- `wind-index get_index_kline` 单段超 3 年必截断（50KB 预算），如需用按 ≤2 年分段。
