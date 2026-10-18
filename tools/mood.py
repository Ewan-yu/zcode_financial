#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""市场情绪指标层 CLI（docs/webapp-design.md §3.10，schema v2.3）。

可插拔指标注册制：每篇文章一个指标（key），采集口径固化在技能 mood-collect 的
模板里，本工具只负责登记 / 入库 / 查询。数据来自 AI 会话经 MCP 采集后落盘的
快照（data/snapshots/<日期>/mood_*.json）或直接数值（锚点）。

常用：
  python tools/mood.py init                       # 建表 + 预置注册（net_break_pb/market_pb）
  python tools/mood.py register --key xxx --name 名称 --domain 估值 --unit % \
      --source 问财 --method "口径描述" --direction 1
  python tools/mood.py add --key net_break_pb --date 2026-10-16 --value 8.17 \
      --count 427 --denom 5224 --source 问财三段 --meta '{"snap":"data/snapshots/20261016/mood_net_break.json"}'
  python tools/mood.py import-edb --file data/snapshots/mood_market_pb.json   # 长序列批量入库
  python tools/mood.py anchor-add --key net_break_pb --date 2005-07-11 \
      --label 998历史大底 --value 24.4 --source 复利人生2026-10-14
  python tools/mood.py latest                    # 各指标最新值+动态分位
  python tools/mood.py series --key market_pb [--days 250]
  python tools/mood.py selftest
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PRESETS = [
    ("net_break_pb", "破净股占比", "情绪/顶底", "%", "问财三段截面+sector_data家数",
     "0<PB<1 家数 / 全A家数（净资产为正自动排除资不抵债；含ST；剔除退市整理股；分母=板块001005010成分数）",
     1),  # direction=+1：越高越悲观（底部信号）
    ("market_pb", "全市场市净率", "估值", "倍", "万得EDB M0071672",
     "沪深两市整体市净率（中证指数公司口径，2011-05-03 起）——长期估值背景线；2026-10-18 实测 wind-economic EDB 取数受限（超限），待权限恢复后回补", 0),
]


def _out(msg):
    try:
        sys.stdout.write(msg + "\n")
    except UnicodeEncodeError:
        sys.stdout.buffer.write((msg + "\n").encode("utf-8", "replace"))


def db_path():
    import os
    return Path(os.environ.get("WORKBENCH_DB", ROOT / "data" / "workbench.db"))


def connect():
    p = db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    return conn


def jdump(x):
    return json.dumps(x, ensure_ascii=False) if x is not None else None


def percentile(conn, key, value, until=None):
    """当前值在历史序列中的分位（0-100，查询时动态算，不落库）。"""
    rows = conn.execute(
        "SELECT value FROM mood_obs WHERE key=? AND value IS NOT NULL"
        + (" AND date<=?" if until else "") + " ORDER BY value", (key,) if not until else (key, until)
    ).fetchall()
    vals = [r["value"] for r in rows]
    if not vals:
        return None
    below = sum(1 for v in vals if v <= value)
    return round(below / len(vals) * 100, 1)


# ---------------- init ----------------

def cmd_init(a):
    conn = connect()
    with conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS mood_indicators (
          key TEXT PRIMARY KEY, name TEXT, domain TEXT, unit TEXT, source TEXT,
          method TEXT, direction INT DEFAULT 0, active INT DEFAULT 1, created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS mood_obs (
          key TEXT, date TEXT, value REAL, sample_count INT, denominator INT,
          source TEXT, meta TEXT, PRIMARY KEY(key, date)
        );
        CREATE TABLE IF NOT EXISTS mood_anchors (
          key TEXT, date TEXT, label TEXT, value REAL, sample_count INT,
          source TEXT, verified TEXT, PRIMARY KEY(key, date, label)
        );
        """)
        import datetime
        today = datetime.date.today().isoformat()
        for key, name, domain, unit, source, method, direction in PRESETS:
            conn.execute(
                "INSERT INTO mood_indicators VALUES (?,?,?,?,?,?,?,1,?)"
                " ON CONFLICT(key) DO UPDATE SET name=excluded.name, domain=excluded.domain,"
                " unit=excluded.unit, source=excluded.source, method=excluded.method,"
                " direction=excluded.direction, active=1, created_at=excluded.created_at",
                (key, name, domain, unit, source, method, direction, today))
    _out("mood init OK（预置：%s）" % ", ".join(p[0] for p in PRESETS))
    return 0


# ---------------- register ----------------

def cmd_register(a):
    conn = connect()
    import datetime
    with conn:
        conn.execute(
            "INSERT INTO mood_indicators VALUES (?,?,?,?,?,?,?,1,?)"
            " ON CONFLICT(key) DO UPDATE SET name=excluded.name, domain=excluded.domain,"
            " unit=excluded.unit, source=excluded.source, method=excluded.method,"
            " direction=excluded.direction, active=1, created_at=excluded.created_at",
            (a.key, a.name, a.domain, a.unit, a.source, a.method, a.direction,
             datetime.date.today().isoformat()))
    _out("register OK: %s（%s）" % (a.key, a.name))
    return 0


# ---------------- add ----------------

def cmd_add(a):
    conn = connect()
    meta = None
    if a.meta:
        meta = a.meta if a.meta.strip().startswith("{") else json.dumps({"note": a.meta}, ensure_ascii=False)
    with conn:
        conn.execute("INSERT OR REPLACE INTO mood_obs VALUES (?,?,?,?,?,?,?)",
                     (a.key, a.date, a.value, a.count, a.denom, a.source, meta))
    p = percentile(conn, a.key, a.value, until=a.date)
    _out("add OK %s %s value=%s（历史分位 %s%%，样本含当日 %s 条）"
         % (a.key, a.date, a.value, p, conn.execute(
             "SELECT COUNT(*) FROM mood_obs WHERE key=?", (a.key,)).fetchone()[0]))
    return 0


# ---------------- import-edb（长序列批量） ----------------

def cmd_import_edb(a):
    """快照格式：[[date, value], ...] 或 {"series": [[date, value], ...]} 或 {date: value}。"""
    data = json.loads(Path(a.file).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        series = data.get("series") or data.get("data") or [(k, v) for k, v in sorted(data.items())]
    else:
        series = data
    conn = connect()
    n = 0
    with conn:
        for row in series:
            date, value = row[0], row[1]
            try:
                fpath = str(Path(a.file).relative_to(ROOT))
            except ValueError:
                fpath = a.file
            conn.execute("INSERT OR REPLACE INTO mood_obs VALUES (?,?,?,?,?,?,?)",
                         (a.key, date, float(value), None, None,
                          a.source or json.dumps({"file": fpath}, ensure_ascii=False),
                          None))
            n += 1
    d0, d1 = series[0][0], series[-1][0]
    _out("import-edb OK %s：%d 条（%s ~ %s）" % (a.key, n, d0, d1))
    return 0


# ---------------- import-wencai（破净三段名单合并入库） ----------------

def cmd_import_wencai(a):
    """合并问财分段名单快照 → 剔除退市整理（简称含'退'）→ 去重 → 计数算占比入库。

    快照格式=问财原始返回 {列:[], 行:[{股票代码,股票简称,市净率(pb)[日期],...}]}。
    """
    import datetime
    all_rows, files = [], []
    for f in a.files.split(","):
        f = f.strip()
        if not f:
            continue
        data = json.loads(Path(f).read_text(encoding="utf-8"))
        rows = data.get("行", data if isinstance(data, list) else [])
        pb_col = next((c for c in data.get("列", []) if "市净率" in c), None) \
            if isinstance(data, dict) else None
        for r in rows:
            pb = r.get(pb_col) if pb_col else next(
                (v for k, v in r.items() if "市净率" in k), None)
            all_rows.append((r.get("股票代码", ""), r.get("股票简称", ""), pb))
        files.append(f)
    seen, uniq, dropped = set(), [], []
    for code, name, pb in all_rows:
        if code in seen:
            continue
        seen.add(code)
        if "退" in (name or ""):  # 退市整理期股票剔除（口径：含ST、含北交所）
            dropped.append("%s %s" % (code, name))
            continue
        uniq.append((code, name, pb))
    if not a.denom or a.denom <= 0:
        _out("FAIL 需要 --denom 全A家数")
        return 1
    value = round(len(uniq) / a.denom * 100, 4)
    conn = connect()
    meta = {"snapshots": files, "dropped_delisting": dropped,
            "denom": a.denom, "denom_source": "sector_data 001005010",
            "collected_at": datetime.date.today().isoformat()}
    with conn:
        conn.execute("INSERT OR REPLACE INTO mood_obs VALUES (?,?,?,?,?,?,?)",
                     (a.key, a.date, value, len(uniq), a.denom, "问财三段截面", jdump(meta)))
    _out("import-wencai OK %s %s：破净 %d 只（剔除退市整理 %d：%s）/ 全A %d = %.2f%%"
         % (a.key, a.date, len(uniq), len(dropped), "、".join(dropped) or "无",
            a.denom, value))
    return 0


# ---------------- anchor ----------------

def cmd_anchor_add(a):
    conn = connect()
    with conn:
        conn.execute("INSERT OR REPLACE INTO mood_anchors VALUES (?,?,?,?,?,?,?)",
                     (a.key, a.date, a.label, a.value, a.count, a.source, a.verified))
    _out("anchor-add OK %s %s「%s」= %s" % (a.key, a.date, a.label, a.value))
    return 0


def cmd_anchor_verify(a):
    conn = connect()
    with conn:
        cur = conn.execute("UPDATE mood_anchors SET verified=? WHERE key=? AND date=? AND label=?",
                           (a.verified, a.key, a.date, a.label))
    _out("anchor-verify updated=%d" % cur.rowcount)
    return 0


# ---------------- latest / series ----------------

def cmd_latest(a):
    conn = connect()
    for r in conn.execute("SELECT * FROM mood_indicators WHERE active=1 ORDER BY key"):
        last = conn.execute("SELECT * FROM mood_obs WHERE key=? ORDER BY date DESC LIMIT 1",
                            (r["key"],)).fetchone()
        n = conn.execute("SELECT COUNT(*) FROM mood_obs WHERE key=?", (r["key"],)).fetchone()[0]
        if not last:
            _out("%-14s %-8s 无观测" % (r["key"], r["name"]))
            continue
        p = percentile(conn, r["key"], last["value"])
        detail = ""
        if last["sample_count"]:
            detail = "（%s/%s" % (last["sample_count"], last["denominator"] or "?")
            if last["denominator"]:
                detail += "=%.2f%%" % (last["sample_count"] / last["denominator"] * 100)
            detail += "）"
        warm = "" if n >= 250 else " [样本不足]"
        _out("%-14s %-8s %s %s @%s 分位%s%%%s%s" % (
            r["key"], r["name"], last["value"], r["unit"], last["date"], p, warm, detail))
    return 0


def cmd_series(a):
    conn = connect()
    where, args = "key=?", [a.key]
    if a.days:
        where += " AND date>=date('now','-%d day')" % a.days
    rows = conn.execute("SELECT * FROM mood_obs WHERE %s ORDER BY date" % where, args).fetchall()
    for r in rows[-(a.tail or 20):]:
        _out("%s %s %s" % (r["date"], r["value"], r["sample_count"] or ""))
    _out("(%d 条)" % len(rows))
    return 0


# ---------------- selftest ----------------

def cmd_selftest(a):
    import os
    import shutil
    import tempfile
    tmp = Path(tempfile.mkdtemp()) / "mood_selftest.db"
    os.environ["WORKBENCH_DB"] = str(tmp)
    ok = True
    try:
        ns = argparse.Namespace
        cmd_init(ns())
        cmd_add(ns(key="net_break_pb", date="2026-10-16", value=8.17, count=427, denom=5224,
                   source="自测", meta='{"snap":"x"}'))
        cmd_add(ns(key="net_break_pb", date="2026-10-17", value=9.0, count=None, denom=None,
                   source="自测", meta=None))
        # 长序列导入：dict 与 list 两种格式
        f1 = tmp.parent / "s1.json"
        f1.write_text(json.dumps([["2024-01-02", 1.5], ["2024-01-03", 1.6]]), encoding="utf-8")
        cmd_import_edb(ns(file=str(f1), key="market_pb", source=None))
        f2 = tmp.parent / "s2.json"
        f2.write_text(json.dumps({"2024-01-04": 1.55, "2024-01-05": 1.4}), encoding="utf-8")
        cmd_import_edb(ns(file=str(f2), key="market_pb", source=None))
        cmd_anchor_add(ns(key="net_break_pb", date="2005-07-11", label="998历史大底",
                          value=24.4, count=None, source="复利人生2026-10-14", verified=None))
        conn = connect()
        checks = {
            "注册表=2": conn.execute("SELECT COUNT(*) FROM mood_indicators").fetchone()[0] == 2,
            "破净序列=2": conn.execute("SELECT COUNT(*) FROM mood_obs WHERE key='net_break_pb'").fetchone()[0] == 2,
            "EDB序列=4": conn.execute("SELECT COUNT(*) FROM mood_obs WHERE key='market_pb'").fetchone()[0] == 4,
            "分位=100": percentile(conn, "net_break_pb", 9.0) == 100.0,
            "锚点=1": conn.execute("SELECT COUNT(*) FROM mood_anchors").fetchone()[0] == 1,
        }
        for k, v in checks.items():
            if not v:
                ok = False
            _out(("PASS " if v else "FAIL ") + k)
        cmd_latest(ns())
    finally:
        os.environ.pop("WORKBENCH_DB", None)
        shutil.rmtree(tmp.parent, ignore_errors=True)
    _out("selftest: %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="市场情绪指标层 CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init").set_defaults(fn=cmd_init)

    p = sub.add_parser("register")
    for arg in ("key", "name", "domain", "unit", "source", "method"):
        p.add_argument("--" + arg, required=True)
    p.add_argument("--direction", type=int, default=0)
    p.set_defaults(fn=cmd_register)

    p = sub.add_parser("add")
    p.add_argument("--key", required=True)
    p.add_argument("--date", required=True)
    p.add_argument("--value", type=float, required=True)
    p.add_argument("--count", type=int)
    p.add_argument("--denom", type=int)
    p.add_argument("--source", default="")
    p.add_argument("--meta", default="")
    p.set_defaults(fn=cmd_add)

    p = sub.add_parser("import-edb")
    p.add_argument("--key", required=True)
    p.add_argument("--file", required=True)
    p.add_argument("--source")
    p.set_defaults(fn=cmd_import_edb)

    p = sub.add_parser("import-wencai")
    p.add_argument("--key", required=True)
    p.add_argument("--date", required=True)
    p.add_argument("--files", required=True, help="问财分段快照，逗号分隔")
    p.add_argument("--denom", type=int, required=True, help="全A家数")
    p.set_defaults(fn=cmd_import_wencai)

    p = sub.add_parser("anchor-add")
    p.add_argument("--key", required=True)
    p.add_argument("--date", required=True)
    p.add_argument("--label", required=True)
    p.add_argument("--value", type=float, required=True)
    p.add_argument("--count", type=int)
    p.add_argument("--source", required=True)
    p.add_argument("--verified")
    p.set_defaults(fn=cmd_anchor_add)

    p = sub.add_parser("anchor-verify")
    p.add_argument("--key", required=True)
    p.add_argument("--date", required=True)
    p.add_argument("--label", required=True)
    p.add_argument("--verified", required=True)
    p.set_defaults(fn=cmd_anchor_verify)

    sub.add_parser("latest").set_defaults(fn=cmd_latest)

    p = sub.add_parser("series")
    p.add_argument("--key", required=True)
    p.add_argument("--days", type=int)
    p.add_argument("--tail", type=int, default=20)
    p.set_defaults(fn=cmd_series)

    sub.add_parser("selftest").set_defaults(fn=cmd_selftest)

    a = ap.parse_args(argv)
    return a.fn(a) or 0


if __name__ == "__main__":
    sys.exit(main())
