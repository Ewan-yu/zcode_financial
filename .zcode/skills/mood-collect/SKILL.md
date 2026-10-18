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

## 一、每日采集（交易日收盘后，乐咕通道 0 次 MCP）

前置：确认是交易日（非交易日跳过，AGENTS.md 第 9 条）。

1. **乐咕刷新（首选，2026-10-18 用户指示起生效）**：走 §一点七 流程——内置浏览器打开
   破净页 → fetch 页面 API → 快照落盘 `data/snapshots/<当日>/mood_legulegu_below_net_asset_m1_<当日>.json`
   → `python tools/mood.py import-legulegu --file <快照>`（全量幂等 REPLACE，自动含当日与任何缺口日）。
   一次刷新同时完成「当日增量 + 断档回补」，无需再走 §一点五 的逐日检测。
2. `python tools/mood.py latest` 核对，观察是否触及关键带：
   - **≥10%**：历史最悲观 8% 时段（作者口径的深度低估区）→ 在当日复盘报告的 L1 环境节引用
   - **≤1%**：趋近顶部信号区
3. **回退（仅乐咕不可用时）**：问财三段截面——分母查 `data/cache/all_a_count_*.json`
   （7 天内有效；否则 sector_data 001005010 全A家数 **减北交所家数**，问财
   「{D}北交所A股」名单可数）。分子三段句式（「沪深A股」措辞，import-wencai 另有
   .BJ 强制剔除双保险，首用须核对返回列名日期==查询日且无 920xxx.BJ）：
   - `市净率大于0且小于0.5的沪深A股`
   - `市净率大于等于0.5且小于0.75的沪深A股`
   - `市净率大于等于0.75且小于1的沪深A股`
   每段应完整无截断（被截断则对半细分重拉）。快照落盘
   `data/snapshots/<D>/mood_net_break_s{1,2,3}.json` → `import-wencai --denom <沪深家数>`。
   回退入库的日期，下次乐咕刷新会被自动覆盖归一（口径以乐咕为准）。

## 一点五、断档处理（2026-10-18 起大幅简化）

乐咕日线是全量序列——**一次刷新即补齐所有缺口**，无需逐日检测回补。流程：

1. 用户说"更新情绪指标"或例行采集时：直接走 §一点七 乐咕刷新（全量 REPLACE，
   缺多少天都一次补上，0 次 MCP）。
2. `python tools/mood.py gaps --key net_break_pb --days-file <交易日历JSON>` 仍可用于
   **核对**刷新后是否还有缺口（交易日历来自 wind-index 小段拉取）。
3. 深度回退（乐咕长期不可用才启用）：问财历史日期筛选逐日回补，⚠ 红线——问财对非交易
   日查询**静默回退上一交易日**（10-18 实测查周六返回周五数据），每段必须核对返回列名
   日期==查询日，不一致跳过不得入库；缺口 N 天≈3N 次调用，N>5 提示用户确认。
   问财 2015 年及更早召回不全（2007/2015 无数据）——乐咕不存在此问题。

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
- 问财历史日查询注意（其他指标仍适用）：非交易日静默回退上一交易日（列名日期红线）；
- 配额：本采集每日 3-4 次，计入 AGENTS.md 第 14 条 10-15 次/日预算；乐咕刷新 0 次 MCP。

## 四、已停用/受限通道备忘（2026-10-18 实测）

- `wind-economic EDB` 指标取数整体受限（M0071672、R3515837 均报「超限」）→ market_pb
  长历史线不再等 EDB：**乐咕「全部A股(沪深)市净率」/stockdata/a-pb（及市盈率 /stockdata/a-pe）
  同法抓取即可替代**，按 §一点七 流程 register+抓取+入库。
- `hexin get_stock_performance` 周行情配额易爆（-4302）且试用限 5 年 → 上证指数日线走
  每日复盘既有链路（daily_k_4codes → market_daily），不单独回补历史。
- `wind-index get_index_kline` 单段超 3 年必截断（50KB 预算），如需用按 ≤2 年分段。
- 问财仍不可替代的场景：个股/名单级明细（成分名单、截面筛选导出）、板块家数以外的
  自定义条件统计——乐咕只给统计序列，不给底层名单。

## 五、市场广度采集（breadth，P1 已落地 2026-10-18）

复利人生系列第 2 篇（SRC-FRL-02）对应指标：8 指数口径×MA5/10/20/60 广度。
**完整设计见 `docs/breadth-backtest-design.md`（v1.2）**，实跑要点：

- **双通道刷新**：①乐咕 ma-statistics 8 口径全量（0 次 MCP，幂等 UPSERT 入
  breadth_daily 宽表）——**免费数据滞后 15 个交易日（滚动）**，历史永无缺口但新鲜度
  T-15；②问财新鲜尾部：4 关键口径（hs300/zz500/cyb/all）×MA20/MA60=8 次/日补 T-0
  （句式「{D}日{指数}成分股收盘价大于{N}日均线」，首用须实测句式支持度——
  **2026-10-18 配额未恢复，此项待办**，并优先补 2026-09-18 起缺口含 10-08 创业板共振日）。
- 事件口径=**滞回**（跌破触发、收复50重新武装），验证式回测核心锚 5/5 PASS
  （2026-10-18）；信号引擎 `python tools/breadth.py signals / verify-author`。
- 每次刷新后跑 `python tools/breadth.py check`（完整性校验）。
- **`data/snapshots/*/breadth_ma_*.json` 永不清理**——滚动窗口的唯一可再生备份。
