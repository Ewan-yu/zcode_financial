#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成数据库数据字典 docs/data-dictionary.md（结构从 workbench.db 实读，注释在本脚本维护）。
用法：python tools/gen_datadict.py   —— 表结构变更后重跑即可保持同步。"""
import sqlite3
import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "workbench.db"
OUT = ROOT / "docs" / "data-dictionary.md"

# ---------------- 表级说明：用途 / 写入方 / 频率 ----------------
TABLE_META = {
    "schema_version": ("库版本管理（迁移约定：升级只增不改历史）", "db.py init", "建库时"),
    "sentiment": ("情绪时序——每日一行，六指标 + 三层判定（环境L1/博弈L2/组合基调）",
                  "db.py import-day（晚间复盘）", "每交易日；可问财历史回补（炸板/广度除外）"),
    "market_daily": ("指数日线与市场广度——上证/深证综指日频 + A_SHARE 行存两市涨跌家数（快照类前向积累）",
                     "import-day（daily_k_4codes.json）/ _backfill 脚本（index_daily_6mo.json）", "每交易日；历史可回补约1年"),
    "ladder_daily": ("连板梯队——各高度家数与名单（预留，尚未接入采集）", "规划：import-day 扩展", "每交易日"),
    "premium_pool": ("昨日涨停今日表现明细（溢价分布原料，预留；当前仅均值入 sentiment.premium）",
                     "规划：问财③逐日明细", "每交易日"),
    "dragon_tiger": ("龙虎榜净买入 TOP（个股级，当日排名与金额）", "import-day（market_summary.json）", "每交易日"),
    "market_valuation": ("指数估值截面（沪深300/中证500 PE、PB 与分位）——预留", "规划：wind-index 周更", "每周"),
    "sectors": ("板块地图——当日每板块一行的环节/分级/催化/梯队/入池资格（复盘第2节结论）",
                "import-day（market_summary.json 板块聚类 + --qualified 标记）", "每交易日"),
    "news": ("复盘检索的要闻（催化密度回溯依据）——预留", "规划：dt-briefing/dt-review 写入", "每交易日"),
    "stock_events": ("个股公告/解禁/减持/业绩预告等排雷事件——预留", "规划：dt-briefing 盘前扫描", "盘前"),
    "candidates": ("候选与观察标的——五维评分、指标参考组、分时承接结论、对策（推荐标的的结构化落库）",
                   "import-day（candidates.json）", "每交易日（复盘产出）"),
    "stock_daily": ("跟踪池+当日候选的日K（OHLC/成交额(元)/换手率%）——不采全市场",
                    "import-day（daily_k_4codes.json）", "每交易日；历史随回补"),
    "stock_profile": ("低频档案——实际流通换算原料（前十大持股）、估值截面、行业归属", "规划：db.py upsert（cache 优先）", "每周"),
    "fundamentals": ("基本面摘要（模块B 预留）——营收/净利/ROE/毛利率/负债率 + 估值分位", "规划：hexin/wind 季频", "季"),
    "predictions": ("判断台账（权威源）——预判-验证循环的核心表；只追加，verify 仅回填结果列，禁改历史内容",
                    "db.py add-prediction / verify；dt-review/dt-monitor 会话调用", "产生判断即写；到期回填"),
    "pools": ("股池定义——预置 dt_watchlist/author_short/author_long/dt_rejected + user_* 自建",
              "db.py init（预置）/ pool add（自建）/ Web 导入", "低频"),
    "pool_members": ("股池当前成员——事件回放的物化视图（status=active/removed）", "db.py pool / Web 导入", "随池操作"),
    "pool_events": ("股池事件溯源——add/remove/move/status/note 全留痕（何时进池、为何移出）",
                    "db.py pool / Web 导入", "随池操作"),
    "reports": ("报告中心——md 全文 + 一句话结论 + 关联标的/板块（前端关联输出的依据）",
                "db.py report-add（与 reports/ 存档原件同动作写入）", "每份报告"),
    "fund_nav": ("基金净值——场外 nav/acc_nav 与场内 close（预留）", "规划：hexin-fund 周更 / wind-fund 日频", "周/日"),
    "trade_events": ("真实买卖事件（P4 预留）——用于判断质量与实际盈亏归因", "规划：用户记账", "随交易"),
    "youzi_picks": ("柚子哥自选池（实证校准数据流）——入选日特征快照 + 前向收益 + 操作记录",
                     "用户提供→会话结构化写入（快照落盘 youzi_picks_<D>.json）", "随柚子哥名单（每交易日）"),
    "macro": ("宏观指标（远期预留）——wind EDB 社融/LPR 等", "规划：wind-economic", "月/周"),
}

# ---------------- 列级注释 {表: {列: 说明}} ----------------
COLS = {
    "sentiment": {
        "date": "交易日 YYYY-MM-DD（主键）",
        "limit_ups": "涨停家数（非ST，全量口径；问财与万得互证）",
        "limit_downs": "跌停家数（非ST）",
        "max_boards": "最高连板数（当日口径）",
        "max_board_stock": "最高连板标的（含特征备注，如一字加速）",
        "promo_rate": "连板晋级率% = 再板数/前日涨停数",
        "premium": "昨日涨停今日平均溢价%（负值=接力亏钱）",
        "zhaba": "炸板家数（盘中触板收盘未封；历史无口径，回补日为 NULL）",
        "amount_yi": "两市成交额（亿，沪+深不含北交所）",
        "l1": "大盘环境判定：低迷/中性/偏暖（指数中期趋势，非单日红绿）",
        "l2": "短线博弈阶段：冰点/启动/发酵/高潮/退潮（指标组特征对照）",
        "combo_tone": "组合基调（L1×L2 矩阵查表结果，如「低迷 × 退潮 = 深冬」）",
        "market_note": "明日基调/操作提示一句话",
        "raw_path": "原始快照溯源路径（data/snapshots/<D>/sentiment.json）",
    },
    "market_daily": {
        "date": "交易日",
        "code": "000001.SH 上证指数 / 399106.SZ 深证综指 / A_SHARE 广度行",
        "name": "指数名（A_SHARE 行为「沪深A股(广度)」）", "close": "收盘点位（广度行为 NULL）",
        "pct": "日涨跌幅%（逐日计算）", "amount_yi": "成交额（亿；广度行为 NULL）",
        "up_count": "两市上涨家数（仅 A_SHARE 行；快照类，自2026-10-16前向积累）",
        "down_count": "两市下跌家数（同上）",
    },
    "dragon_tiger": {"date": "交易日", "code": "股票代码", "name": "名称",
                     "rank": "当日净买入排名", "net_buy_yi": "净买入金额（亿）", "note": "备注"},
    "sectors": {
        "date": "交易日", "name": "板块名（与 market_summary 板块聚类一致）",
        "family": "题材族（预留，手动归并）", "count": "板块涨停/领涨家数",
        "stage": "环节：启动/发酵/高潮/退潮（含细分如「高潮（补涨扩散）」）",
        "grade": "题材分级：政策级/产业级/事件级/一日游",
        "catalyst": "催化事件", "leader": "梯队结构文本（含龙头与高度）",
        "leader_boards": "龙头连板数（预留结构化）",
        "qualified": "入池资格标记（1=通过门槛四条件，import-day --qualified 子串标记）",
        "note": "龙虎榜佐证文本",
    },
    "candidates": {
        "date": "交易日", "code": "股票代码", "name": "名称", "sector": "所属板块（文本）",
        "five_dim": "JSON 五维评分 {启动结构/量能节奏/位置边际/回调质量/当日确认: 优|中|差}",
        "score": "五维总分（0-5）", "grade": "定级：A/B/拦截记录等",
        "action": "对策结论一句话",
        "indicators": "JSON 指标参考组（换手/成交额/量能类型两口径/板质量/龙虎榜/位置/分时承接文字）",
        "intraday": "JSON 分时承接实算指标（vwap_close/bias_close_pct/up_早中晚段/vr/open_depth_pct/reseal_bars/pulses；来源 indicators.py，无则为 NULL）",
        "plan": "JSON 对策预案 {介入观察/失效/兑现/反转确认/持有分档}",
    },
    "stock_daily": {"code": "股票代码", "date": "交易日",
                    "open/high/low/close": "OHLC（不复权）", "amount": "成交额（元）",
                    "turnover": "换手率%（名义口径）"},
    "predictions": {
        "id": "自增主键", "reg_date": "判断作出日", "code": "代码（全市场判断用 MARKET）",
        "name": "名称", "direction": "方向（看多/看空/中性偏多/中性偏空等）",
        "content": "判断内容全文（次日预期开盘与强弱——操作指导正文）",
        "refs": "依据条目编号（分号分隔；盘感判断标「盘感」）——条目级胜率统计的聚合键",
        "trigger_cond": "触发/介入条件（可验证口径）", "invalid_cond": "失效/止损条件",
        "timeframe": "时间框架（如 1个交易日(2026-10-19)）",
        "verify_date": "验证日", "result": "结果：对/错/部分/未触发（仅回填此列与 outcome/note）",
        "outcome": "理论盈亏%", "note": "复盘备注（错在哪/对在哪/条目要不要改）",
    },
    "pools": {"key": "池标识（dt_watchlist/author_short/author_long/dt_rejected/user_*）",
              "title": "中文名", "domain": "所属域（DT/VF）", "source": "来源（system/author/user）",
              "description": "用途说明", "created_at": "创建日", "active": "启用标记"},
    "pool_members": {"pool": "池 key", "code": "代码", "name": "名称", "added": "加入日",
                     "status": "active/removed（removed 保留行，历史可回放）",
                     "horizon": "标准(1-2周)/主线(≤1月)", "note": "加入理由"},
    "pool_events": {"date": "事件日", "pool": "池 key（move 事件记目标池）", "code": "代码",
                    "name": "名称", "event": "add/remove/move/status/note",
                    "reason": "原因（判断依据留痕）",
                    "extra": "JSON 附加 {horizon/days_watched/from/to}（move 的池间路径）",
                    "created_at": "写入时间"},
    "reports": {"id": "自增主键", "date": "报告日", "kind": "review/stock/sector/briefing/fundamental/industry/research/weekly",
                "domain": "DT/VF/TR/XC", "title": "标题（UNIQUE 约束之一）",
                "content_md": "md 全文（与 reports/ 存档原件同动作写入）",
                "conclusion": "一句话结论（列表页）",
                "related_codes/related_sectors": "JSON 数组——个股档案页/板块页关联输出的依据",
                "refs": "引用的方法论条目", "md_path/html_path": "存档原件路径",
                "created_at": "入库时间"},
    "schema_version": {"version": "结构版本号", "applied_at": "应用时间"},
    "youzi_picks": {
        "date": "入选日（作者名单日）", "code": "股票代码", "name": "名称",
        "note": "备注（用户转述原文/名称核实依据/柚子哥理由）",
        "entry_ref": "参考介入价（如提供；NULL=未知）",
        "features": "JSON 入选日特征快照（板块/收盘/振幅特征/近5日高点距离/换手/成交额/启动结构）",
        "fwd": "JSON 前向收益与柚子哥操作 {t1_open%/t1_high%/t1_close%/t1_冲高回落%/t3%/t5%/t10%/author_action}",
        "watch_date": "加入观察日（用户要求必记）", "buy_date": "买入日（未提供则 NULL）",
        "sell_date": "卖出日", "sell_price": "卖出价（与 entry_ref 算操作盈亏%）",
    },
}

JSON_EXAMPLES = """
## JSON 字段结构示例

```json
// candidates.five_dim
{"启动结构": "优", "量能节奏": "中", "位置边际": "差", "回调质量": "中", "当日确认": "中"}
// candidates.intraday（indicators.py 实算）
{"vwap_close": 17.30, "bias_close_pct": 2.41, "up_early_pct": 19, "up_reversal_pct": 97,
 "up_open_seg_pct": 37, "vr_1110": 3.07, "vr_close": 2.99, "open_depth_pct": -2.48,
 "reseal_bars": 3, "pulses_total": 5, "pulses_sell_suspect": ["14:15", "14:20", "14:30"]}
// candidates.plan
{"介入观察": "低开不破16.8+承接修复三条件", "失效": "放量跌破16.8", "兑现": "18.3-18.5遇阻即兑现",
 "反转确认": "站回19.4", "持有分档": "主线波段票"}
// pool_events.extra（move 事件）
{"from": "dt_watchlist", "to": "dt_rejected"}
// reports.related_codes
["603999.SH", "000887.SZ"]
```
"""

RELATIONSHIPS = """
## 关联关系

- **主键口径**：业务表以 `(date, code)` 或 `(date, name)` 为主键——同一交易日一票一行；
  `predictions` / `pool_events` / `news` 等流水表用自增 id。
- **个股聚合**：`stock_daily / candidates / predictions / pool_events / reports.related_codes`
  五处以 code 关联 → 个股档案页的合并时间线。
- **板块聚合**：`sectors.name` ↔ `candidates.sector`（文本关联）↔ `reports.related_sectors`。
- **溯源链**：`sentiment.raw_path` → 原始快照文件；`reports.md_path` → 存档原件；
  `candidates.intraday` ← `tools/indicators.py` 实算（输入为快照分钟K）。
- **备份**：`db.py export <D>` 单向导出 CSV（DB 为权威，data/exports/ 仅备份）。
"""


def main():
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    lines = ["# 数据字典（workbench.db）", "",
             "> 生成：`python tools/gen_datadict.py`（结构实读自库，注释维护于脚本内；改表后重跑）。",
             "> 生成时间：%s；库文件：data/workbench.db（SQLite，WAL，仅本地）。" % datetime.date.today(), "",
             "## 表清单", "",
             "| 表 | 用途 | 写入方 | 频率/回补 | 当前行数 |", "|---|---|---|---|---|"]
    counts = {}
    for t in tables:
        counts[t] = conn.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
        meta = TABLE_META.get(t, ("—", "—", "—"))
        lines.append("| %s | %s | %s | %s | %d |" % (t, meta[0], meta[1], meta[2], counts[t]))
    lines.append("")
    for t in tables:
        lines.append("## %s" % t)
        lines.append("")
        meta = TABLE_META.get(t, ("—", "—", "—"))
        lines.append("> %s　·　写入：%s　·　%s　·　当前 %d 行" % (meta[0], meta[1], meta[2], counts[t]))
        lines.append("")
        lines.append("| 列 | 类型 | 说明 |")
        lines.append("|---|---|---|")
        notes = COLS.get(t, {})
        for c in conn.execute("PRAGMA table_info(%s)" % t):
            note = notes.get(c["name"])
            if note is None:  # 允许斜杠合并写法（如 open/high/low/close）
                note = next((v for k, v in notes.items() if c["name"] in k.split("/")), "—")
            pk = "（PK）" if c["pk"] else ""
            lines.append("| %s%s | %s | %s |" % (c["name"], pk, c["type"] or "TEXT", note))
        lines.append("")
    lines.append(JSON_EXAMPLES)
    lines.append(RELATIONSHIPS)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print("written:", OUT, "（%d 表，%d 行文档）" % (len(tables), len(lines)))


if __name__ == "__main__":
    main()
