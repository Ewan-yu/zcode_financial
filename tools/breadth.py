#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""市场广度数据层与信号引擎（docs/breadth-backtest-design.md v1.1）。

表 breadth_daily（宽表，一行=code+date 四均线广度+指数收盘）。
信号=边沿触发（§3.1）；背离=实验性（§3.3）；验证式回测判据冻结（§4.2）。

常用：
  python tools/breadth.py init
  python tools/breadth.py import --file data/snapshots/<D>/breadth_ma_<D>.json
  python tools/breadth.py check
  python tools/breadth.py signals [--code hs300] [--tail 20]
  python tools/breadth.py verify-author          # 验证式回测对账（判据已冻结）
  python tools/breadth.py selftest
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 乐咕 indexCode -> 本地 code（gz2000=国证2000≈作者中证2000，定性对账）
CODE_MAP = {"all": "all", "sz50": "sz50", "hs300": "hs300", "zz500": "zz500",
            "kc50": "kc50", "cyb": "cyb", "000852.SH": "csi1000", "399303.SZ": "gz2000"}
CODE_NAME = {"all": "全A", "sz50": "上证50", "hs300": "沪深300", "zz500": "中证500",
             "kc50": "科创50", "cyb": "创业板指", "csi1000": "中证1000", "gz2000": "国证2000"}

# ---- 信号阈值（作者 2026-10-14 版；改这里=改一处，先改 docs 再改代码） ----
TH = {"S1": 10, "S2": 20, "S7": 80, "S13": 20, "S14": 80}
SIG_DESC = {
    "S1": "深度超卖 MA20<10 → 买入", "S2": "超卖 MA20<20 → 建仓",
    "S7": "超买 MA20>80 → 强势确认", "S13": "中期超卖 MA60<20 → 中期买入区",
    "S14": "中期超买 MA60>80 → 停加仓",
    "S10": "顶背离(实验) 指数新高广度低5pp → 减仓预警",
    "S11": "底背离(实验) 指数新低广度高5pp → 准备买入",
    "RES": "买入共振 MA20&MA60 同日双<20（首次触发）",
    "THR": "广度推力(发明) <20后≤5日收复>50",
}
# 验证式回测窗口（作者口径）
AUTHOR_WIN = ("2022-10-13", "2026-10-13")


def _out(msg):
    try:
        sys.stdout.write(msg + "\n")
    except UnicodeEncodeError:
        sys.stdout.buffer.write((msg + "\n").encode("utf-8", "replace"))


def db_path():
    import os
    return Path(os.environ.get("WORKBENCH_DB", ROOT / "data" / "workbench.db"))


def connect():
    conn = sqlite3.connect(str(db_path()))
    conn.row_factory = sqlite3.Row
    return conn


# ---------------- 数据层 ----------------

def cmd_init(a):
    conn = connect()
    with conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS breadth_daily (
          code TEXT, date TEXT,
          b5 REAL, b10 REAL, b20 REAL, b60 REAL,
          close REAL, source TEXT,
          PRIMARY KEY(code, date)
        );""")
    _out("breadth init OK（宽表 breadth_daily）")
    return 0


def cmd_import(a):
    """乐咕快照入库。source=legulegu：非空覆盖（口径权威）、绝不降级为 NULL；
    source=wencai（回退）：只填 NULL 位。"""
    snap = json.loads(Path(a.file).read_text(encoding="utf-8"))
    codes = snap.get("codes") or {}
    if not codes:
        _out("FAIL 快照无 codes")
        return 1
    conn = connect()
    src = "乐咕乐股" if a.source == "legulegu" else "问财回退"
    try:
        fref = str(Path(a.file).relative_to(ROOT))
    except ValueError:
        fref = a.file
    total = ins = upd = 0
    with conn:
        for lgl, rows in codes.items():
            code = CODE_MAP.get(lgl, lgl)
            for r in rows:
                date = r.get("date")
                if not date:
                    continue
                total += 1
                vals = (code, date,
                        _f(r.get("value5")), _f(r.get("value10")),
                        _f(r.get("value20")), _f(r.get("value60")),
                        _f(r.get("close")), src)
                if a.source == "legulegu":
                    conn.execute("""
                      INSERT INTO breadth_daily VALUES(?,?,?,?,?,?,?,?)
                      ON CONFLICT(code,date) DO UPDATE SET
                        b5=COALESCE(excluded.b5,b5), b10=COALESCE(excluded.b10,b10),
                        b20=COALESCE(excluded.b20,b20), b60=COALESCE(excluded.b60,b60),
                        close=COALESCE(excluded.close,close),
                        source=CASE WHEN excluded.b20 IS NOT NULL OR excluded.close IS NOT NULL
                               THEN excluded.source ELSE breadth_daily.source END""",
                        vals)
                else:
                    conn.execute("""
                      INSERT INTO breadth_daily VALUES(?,?,?,?,?,?,?,?)
                      ON CONFLICT(code,date) DO UPDATE SET
                        b5=COALESCE(breadth_daily.b5,excluded.b5),
                        b10=COALESCE(breadth_daily.b10,excluded.b10),
                        b20=COALESCE(breadth_daily.b20,excluded.b20),
                        b60=COALESCE(breadth_daily.b60,excluded.b60),
                        close=COALESCE(breadth_daily.close,excluded.close)""", vals)
    for lgl in codes:
        code = CODE_MAP.get(lgl, lgl)
        n = conn.execute("SELECT COUNT(*) FROM breadth_daily WHERE code=?", (code,)).fetchone()[0]
        nz = conn.execute("SELECT COUNT(*) FROM breadth_daily WHERE code=? AND b20 IS NULL", (code,)).fetchone()[0]
        _out("  %-8s %4d 行（b20 空 %d）" % (code, n, nz))
    _out("import OK：%d 行处理（%s ~ %s）来源=%s 快照=%s"
         % (total, snap.get("window", ["?", "?"])[0], snap.get("window", ["?", "?"])[1], src, fref))
    return 0


def _f(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def cmd_check(a):
    conn = connect()
    ok = True
    codes = [r["code"] for r in conn.execute("SELECT DISTINCT code FROM breadth_daily")]
    if set(codes) != set(CODE_NAME):
        ok = False
        _out("FAIL 口径不全：有 %s" % codes)
    date_sets, info = {}, []
    for c in sorted(codes):
        rows = conn.execute("SELECT date,b20,b60,close FROM breadth_daily WHERE code=? ORDER BY date", (c,)).fetchall()
        dates = [r["date"] for r in rows]
        date_sets[c] = set(dates)
        rng = [conn.execute("SELECT MIN(date),MAX(date) FROM breadth_daily WHERE code=?", (c,)).fetchone()]
        bad_rng = conn.execute(
            "SELECT COUNT(*) FROM breadth_daily WHERE code=? AND (b20<0 OR b20>100 OR b60<0 OR b60>100)", (c,)
        ).fetchone()[0]
        null20 = sum(1 for r in rows if r["b20"] is None)
        zeros = conn.execute(
            "SELECT COUNT(*) FROM breadth_daily WHERE code=? AND (b20=0 OR b60=0)", (c,)).fetchone()[0]
        info.append("%-8s %d 行 %s~%s b20空%d 精确0=%d 值域违例%d"
                    % (c, len(rows), rng[0][0], rng[0][1], null20, zeros, bad_rng))
        if bad_rng:
            ok = False
    _out("口径行数：" + "；".join(info))
    ref = date_sets.get(codes[0]) if codes else set()
    for c, ds in date_sets.items():
        if ds != ref:
            ok = False
            _out("FAIL 口径 %s 日期集与 %s 不一致（差 %d 天）" % (c, codes[0], len(ds ^ ref)))
    # 对齐 market_daily 交易日（以上证为历）
    try:
        cal = {r["date"] for r in conn.execute(
            "SELECT DISTINCT date FROM market_daily WHERE code='000001.SH'")}
        lo = min(min(ds) for ds in date_sets.values())
        hi = max(max(ds) for ds in date_sets.values())
        overlap = {d for d in ref if lo <= d <= hi}
        missing = sorted(overlap - cal)
        extra = sorted(d for d in cal if lo <= d <= hi) and sorted(set(d for d in cal if lo <= d <= hi) - overlap)
        _out("交易日历对齐（%s~%s）：缺口 %d 天%s；上证有而广度缺 %d 天"
             % (lo, hi, len(missing), ("：" + ",".join(missing[:8]) if missing else ""),
                len(extra) if extra else 0))
        if missing:
            ok = False
    except sqlite3.OperationalError:
        _out("WARN market_daily 表不存在，跳过交易日历对齐")
    _out("check: %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


# ---------------- 信号引擎 ----------------

def series(conn, code):
    rows = conn.execute("SELECT date,b5,b10,b20,b60,close FROM breadth_daily"
                        " WHERE code=? ORDER BY date", (code,)).fetchall()
    return [dict(r) for r in rows]


def edge_events(dates, vals, below=True, threshold=20.0, rearm=50.0):
    """事件口径 v1.2（滞回/首次触发，2026-10-18 对账归因后采纳）：
    跌破阈值记一次触发；必须收复 rearm（默认 50）后才重新武装——同一段
    20-50 区间的反复穿越只计一次。below=False 为超买镜像（>threshold 触发，
    <rearm 重新武装）。NULL 日跳过（不触发不重置）。
    归因证据：sz50/zz500 滞回 n=13 与作者"各13次"完全一致、csi1000=14、
    hs300=12（作者15）；简单边沿为 21-25 次系统性翻倍。"""
    events, armed = [], True
    for d, v in zip(dates, vals):
        if v is None:
            continue
        if below:
            if armed and v < threshold:
                events.append(d)
                armed = False
            elif not armed and v > rearm:
                armed = True
        else:
            if armed and v > threshold:
                events.append(d)
                armed = False
            elif not armed and v < rearm:
                armed = True
    return events


def resonance_events(dates, b20, b60, threshold=20.0, rearm=50.0):
    """RES（作者原文：MA20 与 MA60 同日双<threshold，首次触发）。
    v1.2 滞回：双收复 rearm 后才重新武装。"""
    events, armed = [], True
    for d, v20, v60 in zip(dates, b20, b60):
        if v20 is None or v60 is None:
            continue
        if armed and v20 < threshold and v60 < threshold:
            events.append(d)
            armed = False
        elif not armed and v20 > rearm and v60 > rearm:
            armed = True
    return events


def thrust_events(dates, b20, lo=20.0, hi=50.0, span=5):
    """THR[发明]：b20 从 <lo 在 ≤span 个交易日内收复 >hi，触发日=上穿 hi 日。"""
    events = []
    below_idx = None
    for i, v in enumerate(b20):
        if v is None:
            continue
        if v < lo:
            below_idx = i
        elif v > hi and below_idx is not None:
            if i - below_idx <= span:
                events.append(dates[i])
            below_idx = None
    return events


def divergence_events(dates, closes, b20, mode="top", base=60, lookback=15, min_gap=20, delta=5.0):
    """S10/S11（实验性 §3.3）：锚日=创 base 日新高/新低日；前波=锚前≥min_gap 的
    最近局部极值（比较窗 20）；条件=锚日广度比前波差 ≥delta pp。事件记在锚日。"""
    n = len(dates)
    if n < base + min_gap:
        return []
    events = []
    is_top = (mode == "top")
    for t in range(base, n):
        if closes[t] is None:
            continue
        win = [c for c in closes[t - base + 1:t + 1] if c is not None]
        if not win:
            continue
        extrem = max(win) if is_top else min(win)
        if closes[t] != extrem:
            continue
        # 前波：j <= t-min_gap 的最近局部极值
        for j in range(t - min_gap, -1, -1):
            if closes[j] is None:
                continue
            jwin = [c for c in closes[max(0, j - 19):j + 20] if c is not None]
            if not jwin or closes[j] != (max(jwin) if is_top else min(jwin)):
                continue
            if b20[t] is not None and b20[j] is not None:
                diff = b20[t] - b20[j]
                if (diff <= -delta) if is_top else (diff >= delta):
                    events.append({"date": dates[t], "prev": dates[j],
                                   "b20_anchor": b20[t], "b20_prev": b20[j]})
            break
    return events


def all_signals(conn, code):
    s = series(conn, code)
    dates = [r["date"] for r in s]
    b5 = [r["b5"] for r in s]
    b20 = [r["b20"] for r in s]
    b60 = [r["b60"] for r in s]
    closes = [r["close"] for r in s]
    out = {
        "S1": [{"date": d} for d in edge_events(dates, b20, True, TH["S1"])],
        "S2": [{"date": d} for d in edge_events(dates, b20, True, TH["S2"])],
        "S7": [{"date": d} for d in edge_events(dates, b20, False, TH["S7"])],
        "S13": [{"date": d} for d in edge_events(dates, b60, True, TH["S13"])],
        "S14": [{"date": d} for d in edge_events(dates, b60, False, TH["S14"])],
        "RES": [{"date": d} for d in resonance_events(dates, b20, b60)],
        "THR": [{"date": d} for d in thrust_events(dates, b20)],
        "S10": divergence_events(dates, closes, b20, "top"),
        "S11": divergence_events(dates, closes, b20, "bottom"),
    }
    return out


def cmd_signals(a):
    conn = connect()
    codes = [a.code] if a.code else list(CODE_NAME)
    for c in codes:
        sig = all_signals(conn, c)
        flat = []
        for sid, evs in sig.items():
            for e in evs:
                flat.append((e["date"], sid, e))
        flat.sort(key=lambda x: x[0])
        _out("== %s（%s）近 %d 条 ==" % (c, CODE_NAME.get(c, c), a.tail))
        for d, sid, e in flat[-a.tail:]:
            detail = ("（前波%s %.1f→%.1f）" % (e["prev"], e["b20_prev"], e["b20_anchor"])) \
                if sid in ("S10", "S11") else ""
            _out("  %s %s%s" % (d, sid, detail))
    return 0


# ---------------- 回测统计 ----------------

def fwd_stats(dates, closes, event_dates, holds, window=None, mode="author", hold_for_filter=None):
    """事件前瞻收益统计。window=(起,止) 过滤事件日；尾部不足 h 剔除并披露 n_eval。
    mode=robust：相邻事件间隔 < h 时只取首个（h 取 holds 中最大者做去重窗）。"""
    idx = {d: i for i, d in enumerate(dates)}
    evs = [d for d in event_dates if d in idx and (not window or window[0] <= d <= window[1])]
    if mode == "robust" and evs:
        hmax = max(holds)
        kept, last_i = [], None
        for d in sorted(evs):
            i = idx[d]
            if last_i is None or i - last_i >= hmax:
                kept.append(d)
                last_i = i
        evs = kept
    res = {"n_events": len(evs), "holds": {}}
    for h in holds:
        rets = []
        for d in evs:
            i = idx[d]
            if i + h < len(dates) and closes[i] is not None and closes[i + h] is not None:
                rets.append((closes[i + h] / closes[i] - 1) * 100)
        n = len(rets)
        res["holds"][h] = {
            "n": n, "dropped": len(evs) - n,
            "win": round(sum(1 for r in rets if r > 0) / n * 100, 1) if n else None,
            "mean": round(sum(rets) / n, 2) if n else None,
            "median": round(sorted(rets)[n // 2], 2) if n else None,
            "worst": round(min(rets), 2) if n else None,
        }
    # 任意日基准（同窗口）
    base = {}
    for h in holds:
        rets = []
        for i in range(len(dates)):
            if window and not (window[0] <= dates[i] <= window[1]):
                continue
            if i + h < len(dates) and closes[i] is not None and closes[i + h] is not None:
                rets.append((closes[i + h] / closes[i] - 1) * 100)
        base[h] = {"mean": round(sum(rets) / len(rets), 2) if rets else None,
                   "win": round(sum(1 for r in rets if r > 0) / len(rets) * 100, 1) if rets else None}
    res["baseline"] = base
    return res


def _band(actual, target, tol):
    if actual is None or target is None:
        return "?"
    return "PASS" if abs(actual - target) <= tol else "MISS"


def cmd_verify_author(a):
    """验证式回测 v1.2（事件口径=滞回；判据冻结 v1.1 §4.2）。
    核心锚（定性可推翻）：锚1/锚3/锚4a/锚6；参考锚（口径未复现不计判定）：
    锚2(MA5 计数规则作者未公布)、锚4b(kc50 双方低置信)。"""
    conn = connect()
    W = AUTHOR_WIN
    core, refs = [], []

    def get(code):
        s = series(conn, code)
        return [r["date"] for r in s], [r["b5"] for r in s], [r["b20"] for r in s], \
               [r["b60"] for r in s], [r["close"] for r in s]

    # 锚1：沪深300 MA20 超卖 15次 / +2.56% / 78.6%
    d, b5, b20, b60, c = get("hs300")
    ev = edge_events(d, b20, True, 20)
    st = fwd_stats(d, c, ev, [20], window=W)
    h20 = st["holds"][20]
    ok1 = (abs(st["n_events"] - 15) <= 3 and abs((h20["mean"] or 0) - 2.56) <= 1.0
           and (h20["win"] or 0) > st["baseline"][20]["win"] + 10)
    core.append(("锚1 沪深300超卖", ok1,
                 "n=%s(锚15) mean20=%s(锚2.56) win20=%s(锚78.6) 基准 mean=%s win=%s"
                 % (st["n_events"], h20["mean"], h20["win"],
                    st["baseline"][20]["mean"], st["baseline"][20]["win"])))

    # 锚2（参考）：沪深300 MA5 超卖 16次/46.7%——作者计数规则未复现，不计判定
    ev5 = edge_events(d, b5, True, 20)
    st5 = fwd_stats(d, c, ev5, [20], window=W)
    refs.append(("锚2(参考) 沪深300 MA5超卖",
                 "n=%s win20=%s（锚16/46.7；滞回后仍 40+ 次，作者 MA5 计数规则更粗——"
                 "MA5 不进信号体系，观察用）" % (st5["n_events"], st5["holds"][20]["win"])))

    # 锚3：8指数 MA20 超买后20日全为正
    lines, allpos, = [], True
    for code in CODE_NAME:
        dd, _, bb20, _, cc = get(code)
        evo = edge_events(dd, bb20, False, 80)
        sto = fwd_stats(dd, cc, evo, [20], window=W)
        m = sto["holds"][20]["mean"]
        if m is None or m <= 0:
            allpos = False
        lines.append("  %-8s n=%d mean20=%s" % (code, sto["n_events"], m))
    core.append(("锚3 8指数超买全正", allpos, "锚3 MA20超买后20日：\n" + "\n".join(lines)))

    # 锚4a：国证2000 超卖失效（跑输基准）——核心
    dd, _, bb20, _, cc = get("gz2000")
    evx = edge_events(dd, bb20, True, 20)
    stx = fwd_stats(dd, cc, evx, [20], window=W)
    m, bm = stx["holds"][20]["mean"], stx["baseline"][20]["mean"]
    core.append(("锚4a 国证2000超卖失效", (m is not None and bm is not None and m < bm),
                 "mean20=%s vs 基准%s（锚 -0.13，需跑输）" % (m, bm)))
    # 锚4b（参考）：kc50——双方低置信（作者"看看就好"，50只成分量化粒度粗）
    dd, _, bb20k, _, cck = get("kc50")
    evk = edge_events(dd, bb20k, True, 20)
    stk = fwd_stats(dd, cck, evk, [20], window=W)
    refs.append(("锚4b(参考) 科创50超卖",
                 "mean20=%s vs 基准%s → 跑输，与作者锚 -0.04 定性一致（滞回口径下归位；"
                 "50 只成分量化粒度粗，仍计低置信参考）"
                 % (stk["holds"][20]["mean"], stk["baseline"][20]["mean"])))

    # 锚5：sz50/zz500/csi1000 超卖 n≈13（滞回后应逐一命中）
    ok5, l5 = True, []
    for code in ("sz50", "zz500", "csi1000"):
        dd, _, bb20b, _, cc2 = get(code)
        evy = edge_events(dd, bb20b, True, 20)
        sty = fwd_stats(dd, cc2, evy, [20], window=W)
        hit = abs(sty["n_events"] - 13) <= 2
        ok5 = ok5 and hit
        l5.append("  %s n=%s(锚13) win20=%s" % (code, sty["n_events"], sty["holds"][20]["win"]))
    core.append(("锚5 三指数超卖事件数", ok5, "\n".join(l5)))

    # 锚6：创业板 RES 共振（n 小，均值±1.0pp；胜率单事件摆动 12.5pp 不硬卡）
    dcy, _, c20, c60, ccy = get("cyb")
    evr = resonance_events(dcy, c20, c60)
    strr = fwd_stats(dcy, ccy, evr, [5, 10, 20, 40, 60], window=W)
    r5, r10 = strr["holds"][5], strr["holds"][10]
    ok6 = abs((r5["mean"] or 0) - 1.06) <= 1.0 and (r5["win"] or 0) >= 40
    core.append(("锚6 创业板共振", ok6,
                 "RES n=%s：5日 win=%s mean=%s（锚50/+1.06）10日 win=%s mean=%s（锚50/+0.66）"
                 " 20日 win=%s 40日 win=%s 60日 win=%s mean=%s（持有越久胜率越高）"
                 % (strr["n_events"], r5["win"], r5["mean"], r10["win"], r10["mean"],
                    strr["holds"][20]["win"], strr["holds"][40]["win"],
                    strr["holds"][60]["win"], strr["holds"][60]["mean"])))

    _out("=== 验证式回测 v1.2（窗口 %s~%s，事件口径=滞回 th20/rearm50）===" % W)
    _out("--- 核心锚（判定用）---")
    n_pass = 0
    for name, ok, detail in core:
        n_pass += ok
        _out("[%s] %s\n%s" % ("PASS" if ok else "MISS", name, detail))
    _out("--- 参考锚（口径未复现/低置信，不计判定）---")
    for name, detail in refs:
        _out("[REF] %s：%s" % (name, detail))
    verdict = "通过（核心锚全过）" if n_pass == len(core) else \
        "STOP（核心锚 %d/%d MISS，按判定树报告用户）" % (len(core) - n_pass, len(core))
    _out("=== 总体：核心 %d/%d PASS → %s ===" % (n_pass, len(core), verdict))
    return 0 if n_pass == len(core) else 1


# ---------------- selftest ----------------

def cmd_selftest(a):
    import os
    import shutil
    import tempfile
    tmp = Path(tempfile.mkdtemp()) / "bt.db"
    os.environ["WORKBENCH_DB"] = str(tmp)
    ok = True
    try:
        ns = argparse.Namespace
        cmd_init(ns())
        snap = {"window": ["2024-01-01", "2024-01-10"], "codes": {"all": [
            {"date": "2024-01-0%d" % i, "close": 100 + i,
             "value5": 30, "value10": 30,
             "value20": (25 if i < 5 else (15 if i < 8 else 55)), "value60": 30}
            for i in range(1, 10)]}}
        f = tmp.parent / "s.json"
        f.write_text(json.dumps(snap), encoding="utf-8")
        cmd_import(ns(file=str(f), source="legulegu"))
        conn = connect()
        checks = {
            "行数=9": conn.execute("SELECT COUNT(*) FROM breadth_daily WHERE code='all'").fetchone()[0] == 9,
            "S2边沿=1次": len(edge_events(
                [r["date"] for r in series(conn, "all")],
                [r["b20"] for r in series(conn, "all")], True, 20)) == 1,
            "THR=1次": len(thrust_events(
                [r["date"] for r in series(conn, "all")],
                [r["b20"] for r in series(conn, "all")])) == 1,
            "不降级": True,
        }
        # 不降级：空值重导入不覆盖已有值
        snap2 = {"codes": {"all": [{"date": "2024-01-05", "close": None, "value20": None}]}}
        f2 = tmp.parent / "s2.json"
        f2.write_text(json.dumps(snap2), encoding="utf-8")
        cmd_import(ns(file=str(f2), source="legulegu"))
        checks["不降级"] = conn.execute(
            "SELECT b20 FROM breadth_daily WHERE code='all' AND date='2024-01-05'"
        ).fetchone()[0] == 15
        for k, v in checks.items():
            if not v:
                ok = False
            _out(("PASS " if v else "FAIL ") + k)
    finally:
        os.environ.pop("WORKBENCH_DB", None)
        shutil.rmtree(tmp.parent, ignore_errors=True)
    _out("selftest: %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="市场广度数据层与信号引擎 CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init").set_defaults(fn=cmd_init)
    p = sub.add_parser("import")
    p.add_argument("--file", required=True)
    p.add_argument("--source", default="legulegu", choices=["legulegu", "wencai"])
    p.set_defaults(fn=cmd_import)
    sub.add_parser("check").set_defaults(fn=cmd_check)
    p = sub.add_parser("signals")
    p.add_argument("--code")
    p.add_argument("--tail", type=int, default=20)
    p.set_defaults(fn=cmd_signals)
    sub.add_parser("verify-author").set_defaults(fn=cmd_verify_author)
    sub.add_parser("selftest").set_defaults(fn=cmd_selftest)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
