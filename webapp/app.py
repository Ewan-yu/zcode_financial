#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本地 Web 应用（P2/P3）：workbench.db 只读展示 + 股池导入。

启动：python webapp/app.py → http://127.0.0.1:8787 （仅本机绑定；写仅 POST /pool/import）
"""
import json
import re
import sqlite3
import sys
from pathlib import Path

from flask import Flask, abort, redirect, render_template, request, url_for

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

app = Flask(__name__)
DB = ROOT / "data" / "workbench.db"
# 条目代号→中文标题（本地生成：python tools/gen_entries.py；含方法论标题，不入远端）
ENTRIES = {}
_ep = ROOT / "data" / "entries.json"
if _ep.exists():
    ENTRIES = json.loads(_ep.read_text(encoding="utf-8"))
STAGES = ["冰点", "启动", "发酵", "高潮", "退潮"]
STAGE_COLOR = {"冰点": "#8b95a5", "启动": "#4c8dff", "发酵": "#e5484d",
               "高潮": "#e2b341", "退潮": "#2fb37c"}


def q(sql, args=(), one=False):
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(sql, args).fetchall()
    conn.close()
    if one:
        return dict(rows[0]) if rows else None
    return [dict(r) for r in rows]


def stage_of(text):
    for st in STAGES:
        if st in str(text or ""):
            return st
    return "冰点"


def ma(series, n):
    out, s = [], 0.0
    for i, v in enumerate(series):
        s += v
        if i >= n:
            s -= series[i - n]
        out.append(round(s / n, 2) if i >= n - 1 else None)
    return out


def candle(code, end_date, tail=40):
    rows = q("SELECT date,open,high,low,close FROM stock_daily WHERE code=? AND date<=?"
             " ORDER BY date DESC LIMIT ?", (code, end_date, tail + 25))[::-1]
    if not rows:
        return None
    closes = [r["close"] for r in rows]
    return {"dates": [r["date"][5:] for r in rows][-tail:],
            "ohlc": [[r["open"], r["close"], r["low"], r["high"]] for r in rows][-tail:],
            "ma5": ma(closes, 5)[-tail:], "ma20": ma(closes, 20)[-tail:]}


def jload(s, default=None):
    try:
        return json.loads(s) if s else default
    except (TypeError, ValueError):
        return default


@app.context_processor
def inject_latest_review():
    row = q("SELECT MAX(date) d FROM sentiment", one=True)
    return {"latest_review": row["d"] if row else None}


# ---------------- 页面：总览 ----------------

@app.route("/")
def index():
    s = q("SELECT * FROM sentiment ORDER BY date DESC LIMIT 1", one=True)
    d = s["date"] if s else None
    idx = q("SELECT date,close,amount_yi FROM market_daily WHERE code='000001.SH' AND date<=?"
            " ORDER BY date", (d or "9999",)) if d else []
    breadth = q("SELECT * FROM market_daily WHERE code='A_SHARE' AND date=?",
                (d,), one=True) if d else None
    cands = q("SELECT * FROM candidates WHERE date=?", (d,)) if d else []
    pending = q("SELECT * FROM predictions WHERE result IS NULL ORDER BY reg_date DESC")
    reports = q("SELECT id,date,kind,title,conclusion FROM reports ORDER BY date DESC,id DESC LIMIT 6")
    pools = q("SELECT p.key,p.title,(SELECT COUNT(*) FROM pool_members m WHERE m.pool=p.key"
              " AND m.status='active') c FROM pools p WHERE p.active=1 ORDER BY p.key")
    stats = {
        "待验证判断": len(pending),
        "已验证": q("SELECT COUNT(*) c FROM predictions WHERE result IS NOT NULL", one=True)["c"],
        "报告数": q("SELECT COUNT(*) c FROM reports", one=True)["c"],
    }
    return render_template("index.html", s=s, d=d, idx=idx, breadth=breadth, cands=cands,
                           pending=pending, reports=reports, pools=pools, stats=stats,
                           stage=stage_of(s.get("l2")) if s else None)


# ---------------- 页面：情绪时序 ----------------

@app.route("/trend")
def trend():
    sents = q("SELECT * FROM sentiment ORDER BY date")
    idx = q("SELECT date,close,pct,amount_yi FROM market_daily WHERE code='000001.SH' ORDER BY date")
    breadth = q("SELECT date,up_count,down_count FROM market_daily WHERE code='A_SHARE' ORDER BY date")
    bmap = {r["date"]: r for r in breadth}
    return render_template("trend.html", sents=sents, idx=idx, breadth=breadth, bmap=bmap)


# ---------------- 页面：台账 ----------------

@app.route("/ledger")
def ledger():
    rows = q("SELECT * FROM predictions ORDER BY reg_date DESC, id DESC")
    done = [r for r in rows if r["result"]]
    win = sum(1 for r in done if r["result"] == "对")
    lose = sum(1 for r in done if r["result"] == "错")
    stats = {"总判断": len(rows), "待验证": len(rows) - len(done),
             "对": win, "错": lose,
             "胜率": round(win / (win + lose) * 100, 1) if win + lose else None}
    by_dir = {}
    for r in done:
        by_dir.setdefault(r["direction"], {"对": 0, "错": 0, "其他": 0})
        by_dir[r["direction"]]["对" if r["result"] == "对" else "错" if r["result"] == "错" else "其他"] += 1
    # 条目级胜率：依据条目拆分聚合（策略更新与选股胜率的统计跟踪）
    by_refs = {}
    for r in rows:
        for ref in re.split(r"[;；,，]", r["refs"] or ""):
            ref = ref.strip()
            if not ref or ref == "盘感":
                continue
            s = by_refs.setdefault(ref, {"对": 0, "错": 0, "其他": 0, "待": 0})
            if r["result"] == "对":
                s["对"] += 1
            elif r["result"] == "错":
                s["错"] += 1
            elif r["result"]:
                s["其他"] += 1
            else:
                s["待"] += 1
    by_refs = sorted(by_refs.items(), key=lambda kv: -(kv[1]["对"] + kv[1]["错"] + kv[1]["其他"] + kv[1]["待"]))
    return render_template("ledger.html", rows=rows, stats=stats, by_dir=by_dir,
                           by_refs=by_refs, entries=ENTRIES)


# ---------------- 页面：股池 ----------------

@app.route("/pools")
def pools():
    ps = q("SELECT p.*,(SELECT COUNT(*) FROM pool_members m WHERE m.pool=p.key AND m.status='active') c"
           " FROM pools p WHERE p.active=1 ORDER BY p.key")
    events = q("SELECT * FROM pool_events ORDER BY id DESC LIMIT 20")
    return render_template("pools.html", pools=ps, events=events)


@app.route("/pool/<key>")
def pool_detail(key):
    p = q("SELECT * FROM pools WHERE key=?", (key,), one=True)
    if not p:
        abort(404)
    members = q("SELECT * FROM pool_members WHERE pool=? ORDER BY status,code", (key,))
    events = q("SELECT * FROM pool_events WHERE pool=? ORDER BY id DESC", (key,))
    return render_template("pool_detail.html", p=p, members=members, events=events,
                           imported=request.args.get("imported", type=int))


@app.route("/pool/import", methods=["POST"])
def pool_import():
    """自助导入：每行 `code[,name[,note]]` 或 `code:name[:note]`。写权限仅此一处。"""
    pool = (request.form.get("pool") or "").strip()
    text = request.form.get("text") or ""
    if not re.fullmatch(r"[a-z0-9_]{2,30}", pool):
        abort(400)
    parsed, bad = [], []
    for line in text.splitlines():
        line = line.strip().replace("，", ",")
        if not line or line.startswith("#"):
            continue
        parts = re.split(r"[,:]", line, maxsplit=2)
        code = parts[0].strip()
        if re.fullmatch(r"[0-9A-Za-z.\-]{5,12}", code):
            parsed.append((code, parts[1].strip() if len(parts) > 1 else "",
                           parts[2].strip() if len(parts) > 2 else ""))
        else:
            bad.append(line)
    conn = sqlite3.connect(str(DB))
    today = __import__("datetime").date.today().isoformat()
    with conn:
        if not conn.execute("SELECT 1 FROM pools WHERE key=?", (pool,)).fetchone():
            conn.execute("INSERT INTO pools VALUES (?,?,?,?,?,?,1)",
                         (pool, pool, "DT", "user", "Web 自助导入创建", today))
        for code, name, note in parsed:
            conn.execute("INSERT OR REPLACE INTO pool_members VALUES (?,?,?,?,?,?,?)",
                         (pool, code, name or code, today, "active", None, note))
            conn.execute("INSERT INTO pool_events (date,pool,code,name,event,reason,created_at)"
                         " VALUES (?,?,?,?,?,?,?)", (today, pool, code, name or code, "add",
                                                     note or "Web 导入", today))
    conn.close()
    return redirect(url_for("pool_detail", key=pool, imported=len(parsed)))


# ---------------- 页面：报告中心 ----------------

@app.route("/reports")
def reports():
    rows = q("SELECT id,date,kind,domain,title,conclusion,related_codes,related_sectors"
             " FROM reports ORDER BY date DESC, id DESC")
    for r in rows:
        codes = jload(r.get("related_codes"), []) or []
        sectors = jload(r.get("related_sectors"), []) or []
        r["related_pretty"] = "、".join(sectors + codes) or "—"
    return render_template("reports.html", rows=rows)


@app.route("/report/<int:rid>")
def report_detail(rid):
    r = q("SELECT * FROM reports WHERE id=?", (rid,), one=True)
    if not r:
        abort(404)
    return render_template("report_detail.html", r=r)


# ---------------- 页面：每日复盘（P3，REAL_DATA 由库组装） ----------------

@app.route("/review/<date>")
def review(date):
    data = build_review_data(date)
    if data is None:
        abort(404)
    dates = [r["date"] for r in q("SELECT date FROM sentiment ORDER BY date")]
    i = dates.index(date) if date in dates else -1
    recent = q("SELECT date,limit_ups,limit_downs,max_boards,promo_rate,premium,amount_yi,"
               "l1,l2,combo_tone FROM sentiment WHERE date<=? ORDER BY date DESC LIMIT 10",
               (date,))[::-1]
    recent_preds = q("SELECT * FROM predictions ORDER BY reg_date DESC, id DESC LIMIT 8")
    return render_template("review.html", data=data, date=date, dates=dates,
                           prev=dates[i - 1] if i > 0 else None,
                           nxt=dates[i + 1] if 0 <= i < len(dates) - 1 else None,
                           recent=recent, recent_preds=recent_preds)


def build_review_data(d):
    s = q("SELECT * FROM sentiment WHERE date=?", (d,), one=True)
    if not s:
        return None
    idx = q("SELECT date,close,amount_yi FROM market_daily WHERE code='000001.SH' AND date<=?"
            " ORDER BY date", (d,))
    secs = q("SELECT * FROM sectors WHERE date=? ORDER BY count DESC", (d,))
    cands = q("SELECT * FROM candidates WHERE date=?", (d,))
    preds = q("SELECT * FROM predictions WHERE reg_date=? ORDER BY id", (d,))
    combo = s.get("combo_tone") or ""
    stage = stage_of(s.get("l2"))

    cards = [
        ["组合基调", combo or "—", "三层判定（环境×博弈）", "down" if "退潮" in combo or "低迷" in combo else "warn"],
        ["L1 大盘环境", s.get("l1") or "—", "趋势口径，非单日红绿", "warn" if s.get("l1") == "低迷" else ""],
        ["L2 博弈阶段", s.get("l2") or "—",
         "高度 %s 板 × 晋级率 %s%% × 溢价 %s%%" % (s.get("max_boards"), s.get("promo_rate"), s.get("premium")),
         "down" if stage in ("退潮", "冰点") else ""],
        ["两市成交额", "%s 亿" % s.get("amount_yi"), "沪+深（不含北交所）", "warn"],
    ]
    l2table = [["涨停家数", s.get("limit_ups"), "非ST"], ["跌停家数", s.get("limit_downs"), "非ST"],
               ["最高连板", "%s 板 · %s" % (s.get("max_boards"), (s.get("max_board_stock") or "")[:12]), ""],
               ["连板晋级率", "%s%%" % s.get("promo_rate"), ""],
               ["昨日涨停平均溢价", "%s%%" % s.get("premium"), "负溢价=接力亏钱"],
               ["炸板家数", s.get("zhaba"), "盘中触板未封"]]

    def sec_color(stage_text):
        st = stage_of(stage_text)
        return {"启动": "#4c8dff", "发酵": "#e5484d", "高潮": "#e2b341"}.get(
            st, "#2fb37c" if st == "退潮" else "#8b95a5")

    sectors_tbl = [[r["name"], r["count"], r["leader"] or "", r["catalyst"] or "",
                    r["stage"] or "", r["grade"] or ""] for r in secs]
    qualified = [r for r in secs if r["qualified"]]
    gate = [[ "持续性核心逻辑", "%s（%s）" % (r["grade"] or "", r["catalyst"] or ""), "✓" if r["grade"] and "产业" in str(r["grade"]) + str(r["catalyst"]) else "△"]
            for r in qualified] or [["（当日无板块通过门槛）", "—", "✗"]]
    mainline_concl = ("具备入池资格：%s" % "、".join(r["name"] for r in qualified)) if qualified \
        else "无板块通过入池门槛"
    if s.get("market_note"):
        mainline_concl += "；" + str(s["market_note"])

    cand_cards = []
    for c in cands:
        ind = jload(c.get("indicators"), {}) or {}
        metrics = [[k, v, ""] for k, v in ind.items()]
        five = [[k, v] for k, v in (jload(c.get("five_dim"), {}) or {}).items()]
        cand_cards.append({
            "name": c["name"], "code": c["code"], "badge": c.get("grade") or "",
            "sector": "%s" % (c.get("sector") or ""),
            "horizon": "标准 1-2 周",
            "five": five, "score": "%s/5" % c.get("score", "—"),
            "metrics": metrics, "action": c.get("action") or "",
            "k": candle(c["code"], d),
        })

    events = q("SELECT * FROM pool_events WHERE date=?", (d,))
    members = q("SELECT * FROM pool_members WHERE status='active' LIMIT 8")
    watch = {
        "roll": "股池事件（当日）：新增 %d / 移出 %d；当前活跃成员 %d 只（详见股池页）" % (
            sum(1 for e in events if e["event"] == "add"),
            sum(1 for e in events if e["event"] in ("remove", "move")),
            q("SELECT COUNT(*) c FROM pool_members WHERE status='active'", one=True)["c"]),
        "cols": ["标的", "池", "状态", "horizon", "备注"],
        "rows": [[m["name"], m["pool"], m["status"], m["horizon"] or "标准", m["note"] or ""]
                 for m in members] or [["（暂无活跃成员）", "—", "—", "—", "—"]],
        "holding": [["（无持仓）", "—", "—"],
                    ["规则参考：打板/接力票", "涨停介入", "三部曲时间窗+状态灯；放量破均价线立即走"],
                    ["规则参考：主线波段票", "1-2周~1月", "五日线持股+板块退潮即离场"],
                    ["规则参考：趋势大票", "巨量流动性", "收盘破5日线走"]],
    }
    ledger_rows = [[r["reg_date"], "%s %s" % (r["code"], r["name"]), r["direction"],
                    (r["content"] or "")[:60] + ("…" if len(r["content"] or "") > 60 else ""),
                    r["verify_date"] or r["timeframe"] or "", r["result"] or "待验证"]
                   for r in preds]
    return {
        "meta": {"title": "%s 每日复盘" % d, "date": d, "asof": "收盘",
                 "tone": {"text": combo or (s.get("l1") or "") + "×" + (s.get("l2") or "")}},
        "temp": {"cards": cards,
                 "combo": {"text": combo or "—", "meaning": s.get("market_note") or ""},
                 "stageStrip": {"current": stage, "tip": "晋级率 %s%% × 溢价 %s%%" % (s.get("promo_rate"), s.get("premium"))},
                 "l2table": l2table,
                 "idx": {"dates": [r["date"][5:] for r in idx],
                         "close": [r["close"] for r in idx],
                         "amount": [r["amount_yi"] for r in idx]}},
        "sectors": {"bars": {"names": [r["name"].split("（")[0][:8] for r in secs],
                                 "values": [r["count"] for r in secs],
                                 "colors": [sec_color(r["stage"]) for r in secs]},
                    "table": sectors_tbl},
        "mainline": {"gate": gate, "conclusion": mainline_concl,
                     "leaders": "；".join("%s：%s" % (r["name"], r["leader"]) for r in secs[:3])},
        "candNote": "候选与观察标的（数据自 workbench.db candidates 表；指标参考组全文见当日报告）",
        "cands": cand_cards,
        "watch": watch,
        "ledger": {"rows": ledger_rows},
        "provenance": [["情绪/板块/候选/台账", "workbench.db（raw 溯源见 sentiment.raw_path）"],
                       ["指数与个股日K", "market_daily / stock_daily 表"]],
    }


# ---------------- 页面：柚子哥（实证校准） ----------------

@app.route("/youzi")
def youzi():
    rows = q("SELECT * FROM youzi_picks ORDER BY date DESC, code")
    recs = []
    for r in rows:
        rec = {**r, "f": jload(r.get("features"), {}) or {},
               "w": jload(r.get("fwd"), {}) or {}}
        # 生命周期派生：状态 / 观察→卖出自然日 / 操作盈亏%
        import datetime as _dt
        wd, bd, sd = rec.get("watch_date"), rec.get("buy_date"), rec.get("sell_date")
        rec["status"] = ("已了结" if sd else "在池中")
        try:
            d0 = _dt.date.fromisoformat((wd or rec["date"])[:10])
            d1 = _dt.date.fromisoformat((sd or _dt.date.today().isoformat())[:10])
            rec["days"] = (d1 - d0).days
        except ValueError:
            rec["days"] = None
        ep, sp = rec.get("entry_ref"), rec.get("sell_price")
        rec["op_ret"] = round((sp / ep - 1) * 100, 2) if ep and sp else None
        recs.append(rec)
    t1 = [r["w"].get("t1_close%") for r in recs if r["w"].get("t1_close%") is not None]
    retr = [r["w"].get("t1_冲高回落%") for r in recs if r["w"].get("t1_冲高回落%") is not None]
    ops = [r["op_ret"] for r in recs if r["op_ret"] is not None]
    stats = {"记录数": len(recs), "标的数": len({r["code"] for r in recs}),
             "T+1均值%": round(sum(t1) / len(t1), 2) if t1 else None,
             "T+1平均冲高回落%": round(sum(retr) / len(retr), 2) if retr else None,
             "状态分布": "了结%d / 在池%d" % (
                 sum(1 for r in recs if r["status"] == "已了结"),
                 sum(1 for r in recs if r["status"] == "在池中")),
             "操作盈亏均值%": round(sum(ops) / len(ops), 2) if ops else None}
    profile = None
    pp = ROOT / "data" / "youzi_profile.json"
    if pp.exists():
        profile = json.loads(pp.read_text(encoding="utf-8"))
    return render_template("youzi.html", recs=recs, stats=stats, profile=profile)


# ---------------- 页面：市场情绪指标（复刻复利人生看板版式） ----------------

# 作者公开的尾部分布锚点（复利人生 2026-10-14 文）：P(破净比例 ≥ x)%
TAIL_PTS = [(8.17, 16.8), (10.0, 8.1), (12.0, 3.9)]
ZONES = [("冰点 · 极度恐惧", 0, 20, "#2563eb"), ("偏冷 · 恐惧", 20, 40, "#93c5fd"),
         ("温和 · 中性", 40, 60, "#e5e7eb"), ("偏热 · 贪婪", 60, 80, "#fca5a5"),
         ("过热 · 极度贪婪", 80, 100.01, "#ef4444")]


def tail_pctile(ratio):
    """P(≥x) 对数线性插值（x≥8.17 有效；更低区间作者未公布，返回 None 待自有样本积累）。"""
    import math
    if ratio < TAIL_PTS[0][0]:
        return None
    if ratio >= TAIL_PTS[-1][0]:
        slope = math.log(TAIL_PTS[1][1] / TAIL_PTS[2][1]) / (TAIL_PTS[2][0] - TAIL_PTS[1][0])
        return max(TAIL_PTS[2][1] * math.exp(slope * (ratio - TAIL_PTS[2][0])), 0.3)
    for (x0, p0), (x1, p1) in zip(TAIL_PTS, TAIL_PTS[1:]):
        if x0 <= ratio <= x1:
            return p0 * math.exp(math.log(p1 / p0) * (ratio - x0) / (x1 - x0))


def zone_of(temp):
    for label, lo, hi, color in ZONES:
        if lo <= temp < hi:
            return label, color
    return ZONES[0][0], ZONES[0][3]


@app.route("/mood")
def mood():
    """破净股与市场情绪温度看板（版式复刻复利人生 kimi 看板）。

    温度=100−尾部分位；尾部分布用作者公开三点（8.17%→83.2分位、10%→91.9、12%→96.1）
    对数插值近似，待自有观测≥250 日后切换为自有序列分位。蓝色"家数"历史线目前为
    锚点+前向观测（逐日历史不可廉价回补），随每日采集加密。
    """
    last = q("SELECT * FROM mood_obs WHERE key='net_break_pb' ORDER BY date DESC LIMIT 1", one=True)
    anchors = q("SELECT * FROM mood_anchors WHERE key='net_break_pb' ORDER BY date")
    obs = q("SELECT * FROM mood_obs WHERE key='net_break_pb' ORDER BY date")
    daily = q("SELECT date,close FROM market_daily WHERE code='000001.SH' ORDER BY date")
    n_obs = q("SELECT COUNT(*) c FROM mood_obs WHERE key='net_break_pb'", one=True)["c"]

    temp = zone = zcolor = pctile = None
    narr = "暂无观测。运行 mood-collect 技能采集当日破净截面后，此看板自动点亮。"
    if last:
        p_ge = tail_pctile(last["value"])          # P(破净比例≥当前值)%，即“cold 度”
        pctile = round(100 - p_ge, 1) if p_ge is not None else None   # 历史百分位 P(≤x)
        temp = round(p_ge) if p_ge is not None else None              # 温度=超越概率
        zone, zcolor = zone_of(temp) if temp is not None else (None, None)
        deep = "已跌破" if last["value"] >= 10 else "尚未突破"
        tail_note = ("高于历史上约 %s%% 的交易日" % pctile) if pctile else "更低价位区间（作者分布未覆盖，分位待积累）"
        narr = ("当前市场温度 %s°，处于「%s」区间：破净股 %s 家，破净比例 %s%%，%s（作者尾部分布近似，"
                "自有样本 %d 日积累中）——市场整体估值偏低、投资者情绪偏向恐惧而非贪婪。"
                "但绝对比例%s 10%% 的深度低估线（2024 年 2 月极端时曾达 16.6%%、850 家），"
                "属于显著偏冷、接近历史底部区域而未到极端冰点的状态。"
                % (temp, zone, last["sample_count"], last["value"], tail_note, n_obs, deep)) \
            if pctile else \
            ("破净比例 %s%%（%s 家）——该水平低于作者公布分布的覆盖下限（8.17%%），分位与温度待自有样本积累。"
             % (last["value"], last["sample_count"]))

    ip = ROOT / "data" / "cache" / "mood_index_monthly.json"
    index_m = json.loads(ip.read_text(encoding="utf-8"))["series"] if ip.exists() else []
    return render_template("mood.html", last=last, anchors=anchors, obs=obs, daily=daily,
                           index_m=index_m, temp=temp, zone=zone, zcolor=zcolor,
                           pctile=pctile, narr=narr, zones=ZONES, n_obs=n_obs)


# ---------------- 页面：个股档案（P3） ----------------

@app.route("/stock/<code>")
def stock(code):
    rows = q("SELECT * FROM stock_daily WHERE code=? ORDER BY date", (code,))
    if not rows:
        abort(404)
    name = q("SELECT name FROM candidates WHERE code=? ORDER BY date DESC", (code,), one=True)
    name = (name or {}).get("name") or code
    k = {"dates": [r["date"][5:] for r in rows][-60:],
         "ohlc": [[r["open"], r["close"], r["low"], r["high"]] for r in rows][-60:],
         "ma5": ma([r["close"] for r in rows], 5)[-60:],
         "ma20": ma([r["close"] for r in rows], 20)[-60:]}
    cands = q("SELECT * FROM candidates WHERE code=? ORDER BY date DESC", (code,))
    preds = q("SELECT * FROM predictions WHERE code=? ORDER BY reg_date DESC, id DESC", (code,))
    pevents = q("SELECT * FROM pool_events WHERE code=? ORDER BY date DESC", (code,))
    reps = q("SELECT id,date,kind,title FROM reports WHERE related_codes LIKE ? ORDER BY date DESC",
             ('%"' + code + '"%',))
    tl = sorted(
        [{"date": c["date"], "type": "分析", "text": "%s %s/5 · %s" % (c.get("grade") or "", c.get("score"), c.get("action") or "")} for c in cands]
        + [{"date": p["reg_date"], "type": "判断", "text": "[%s] %s → %s" % (p["direction"], (p["content"] or "")[:50], p["result"] or "待验证")} for p in preds]
        + [{"date": e["date"], "type": "池变动", "text": "%s · %s %s" % (e["pool"], e["event"], e["reason"] or "")} for e in pevents],
        key=lambda x: x["date"], reverse=True)
    pools_in = q("SELECT pool FROM pool_members WHERE code=? AND status='active'", (code,))
    return render_template("stock.html", code=code, name=name, k=k, cands=cands,
                           preds=preds, reports=reps, tl=tl,
                           pools_in=[p["pool"] for p in pools_in])


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8787, debug=False, threaded=True)
