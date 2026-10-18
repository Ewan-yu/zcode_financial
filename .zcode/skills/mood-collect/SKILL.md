---
name: mood-collect
description: 市场情绪指标层采集与扩展（docs/webapp-design.md §3.10）。每日收盘后采集破净股占比截面入 workbench.db；知识星球「复利人生」情绪系列每出新文章时登记新指标并补锚点。产出页面 /mood。
---

# 市场情绪指标采集（mood-collect）

> 权威存储：`data/workbench.db` 表 `mood_indicators` / `mood_obs` / `mood_anchors`。
> CLI：`python tools/mood.py`（init/register/add/import-wencai/anchor-add/latest/series/selftest）。
> 展示：`python webapp/app.py` → http://127.0.0.1:8787/mood（指标卡自动渲染 active=1 的注册指标）。

## 一、每日采集（交易日收盘后，约 3-4 次 MCP 调用）

前置：确认是交易日（非交易日跳过，AGENTS.md 第 9 条）。D=当日（YYYYMMDD）。

1. **全A家数（分母）**：查 `data/cache/all_a_count_*.json`，7 天内直接用；否则调
   `hexin-index sector_data code=001005010 date=<D>` 取「成份股个数」，写新 cache 文件。
2. **问财破净三段（分子，固定句式，规避 50KB 返回截断）**，调
   `hexin-stock search_stocks` domain=stock：
   - `市净率大于0且小于0.5的A股`
   - `市净率大于等于0.5且小于0.75的A股`
   - `市净率大于等于0.75且小于1的A股`
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

- 分子口径：0<PB<1（净资产为正自动排除资不抵债）、含 ST、含北交所、**剔除简称含「退」的
  退市整理股**；分母=板块 001005010 全部A股家数（含北交所，与问财「A股」口径一致）。
- 我方占比与作者绝对值存在系统性差异（作者分母≈5226），**分位与趋势只对我方序列内部
  计算**；作者值仅作锚点参照。此说明已固化在 /mood 页面。
- 判断引用：在报告/复盘中引用本指标结论时，注明来源
  `mood_obs(net_break_pb) + 复利人生系列`；触发关键带时按 AGENTS.md 第 6 条登记判断。
- 历史逐日全量回补**不做**（5000+ 次调用不经济）；历史认知用锚点，未来认知靠前向积累。
- 配额：本采集每日 3-4 次，计入 AGENTS.md 第 14 条 10-15 次/日预算。

## 四、已停用/受限通道备忘（2026-10-18 实测）

- `wind-economic EDB` 指标取数整体受限（M0071672、R3515837 均报「超限」）→ market_pb
  长历史线搁置（指标已注册 direction=-1，待权限恢复按分段下载回补）。
- `hexin get_stock_performance` 周行情配额易爆（-4302）且试用限 5 年 → 上证指数日线走
  每日复盘既有链路（daily_k_4codes → market_daily），不单独回补历史。
- `wind-index get_index_kline` 单段超 3 年必截断（50KB 预算），如需用按 ≤2 年分段。
