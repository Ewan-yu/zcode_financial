#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""workbench.db 管理与写入 CLI（Web 应用 P1 数据层）。

权威存储：data/workbench.db（SQLite，WAL）。AI 会话经本工具写库，Web 服务只读
（写仅股池导入接口，属 P2）。 judgments 权威源=predictions 表；predictions.csv
已冻结为 2026-10-16 前历史存档。

常用：
  python tools/db.py init
  python tools/db.py import-predictions-csv predictions/predictions.csv
  python tools/db.py import-day 20261016 [--qualified 汽车零部件]
  python tools/db.py add-prediction --date 2026-10-19 --code 000887.SZ --name 中鼎股份 \
      --direction 中性 --content "..." --refs DT-J-011 --timeframe 1个交易日
  python tools/db.py verify 3 --result 对 --outcome 2.5 --note "..."
  python tools/db.py pool add dt_watchlist --codes 600825.SH:新华传媒 --reason "..."
  python tools/db.py pool move 600825.SH --from dt_watchlist --to dt_rejected --reason "..."
  python tools/db.py report-add --date 2026-10-16 --kind review --title 市场复盘 \
      --md reports/daily/20261016/市场复盘.md --codes 000887.SZ --sectors 低空经济
  python tools/db.py export 20261016
  python tools/db.py query "SELECT * FROM sentiment"
  python tools/db.py selftest
"""
import argparse
import csv
import datetime
import json
import os
import re
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX_NAMES = {"000001.SH": "上证指数", "399001.SZ": "深证成指", "399006.SZ": "创业板指"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (version INT, applied_at TEXT);
CREATE TABLE IF NOT EXISTS sentiment (
  date TEXT PRIMARY KEY, limit_ups INT, limit_downs INT, max_boards INT,
  max_board_stock TEXT, promo_rate REAL, premium REAL, zhaba INT, amount_yi REAL,
  l1 TEXT, l2 TEXT, combo_tone TEXT, market_note TEXT, raw_path TEXT
);
CREATE TABLE IF NOT EXISTS market_daily (
  date TEXT, code TEXT, name TEXT, close REAL, pct REAL, amount_yi REAL,
  up_count INT, down_count INT, PRIMARY KEY(date, code)
);
CREATE TABLE IF NOT EXISTS ladder_daily (
  date TEXT, boards INT, count INT, names TEXT, PRIMARY KEY(date, boards)
);
CREATE TABLE IF NOT EXISTS premium_pool (
  date TEXT, code TEXT, name TEXT, yest_limit INT, today_pct REAL,
  PRIMARY KEY(date, code)
);
CREATE TABLE IF NOT EXISTS dragon_tiger (
  date TEXT, code TEXT, name TEXT, rank INT, net_buy_yi REAL, note TEXT,
  PRIMARY KEY(date, code)
);
CREATE TABLE IF NOT EXISTS market_valuation (
  date TEXT, code TEXT, name TEXT, pe REAL, pb REAL, pctile TEXT,
  PRIMARY KEY(date, code)
);
CREATE TABLE IF NOT EXISTS sectors (
  date TEXT, name TEXT, family TEXT, count INT, stage TEXT, grade TEXT,
  catalyst TEXT, leader TEXT, leader_boards INT, qualified INT, note TEXT,
  PRIMARY KEY(date, name)
);
CREATE TABLE IF NOT EXISTS news (
  id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, title TEXT, summary TEXT,
  tags TEXT, related_sectors TEXT, related_codes TEXT, source TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS stock_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  code TEXT, name TEXT, date TEXT, event_type TEXT, content TEXT, impact TEXT
);
CREATE TABLE IF NOT EXISTS candidates (
  date TEXT, code TEXT, name TEXT, sector TEXT,
  five_dim TEXT, score REAL, grade TEXT, action TEXT,
  indicators TEXT, intraday TEXT, plan TEXT,
  PRIMARY KEY(date, code)
);
CREATE TABLE IF NOT EXISTS stock_daily (
  code TEXT, date TEXT, open REAL, high REAL, low REAL, close REAL,
  amount REAL, turnover REAL, PRIMARY KEY(code, date)
);
CREATE TABLE IF NOT EXISTS stock_profile (
  code TEXT PRIMARY KEY, name TEXT, updated_at TEXT,
  float_mv REAL, top10_pct REAL, real_float REAL,
  pe REAL, pb REAL, industry TEXT, main_business TEXT, note TEXT
);
CREATE TABLE IF NOT EXISTS fundamentals (
  code TEXT, report_date TEXT, revenue REAL, net_profit REAL, roe REAL,
  gross_margin REAL, debt_ratio REAL, pe REAL, pb REAL, val_pctile TEXT,
  PRIMARY KEY(code, report_date)
);
CREATE TABLE IF NOT EXISTS predictions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  reg_date TEXT, code TEXT, name TEXT, direction TEXT, content TEXT,
  refs TEXT, trigger_cond TEXT, invalid_cond TEXT, timeframe TEXT,
  verify_date TEXT, result TEXT, outcome REAL, note TEXT
);
CREATE TABLE IF NOT EXISTS pools (
  key TEXT PRIMARY KEY, title TEXT, domain TEXT, source TEXT,
  description TEXT, created_at TEXT, active INT DEFAULT 1
);
CREATE TABLE IF NOT EXISTS pool_members (
  pool TEXT, code TEXT, name TEXT, added TEXT, status TEXT,
  horizon TEXT, note TEXT, PRIMARY KEY(pool, code)
);
CREATE TABLE IF NOT EXISTS pool_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  date TEXT, pool TEXT, code TEXT, name TEXT, event TEXT,
  reason TEXT, extra TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS reports (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  date TEXT, kind TEXT, domain TEXT DEFAULT 'DT', title TEXT,
  content_md TEXT, conclusion TEXT,
  related_codes TEXT, related_sectors TEXT, refs TEXT,
  md_path TEXT, html_path TEXT, created_at TEXT,
  UNIQUE(date, kind, title)
);
CREATE TABLE IF NOT EXISTS fund_nav (
  code TEXT, date TEXT, nav REAL, acc_nav REAL, close REAL,
  PRIMARY KEY(code, date)
);
CREATE TABLE IF NOT EXISTS trade_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  date TEXT, code TEXT, name TEXT, side TEXT, price REAL, qty REAL, reason TEXT
);
CREATE TABLE IF NOT EXISTS author_picks (
  date TEXT, code TEXT, name TEXT,
  note TEXT,                          -- 作者理由/用户转述备注
  entry_ref REAL,                     -- 参考介入价（如提供）
  features TEXT,                      -- 入选日特征快照 JSON
  fwd TEXT,                           -- 前向收益 JSON {t1_open,t1_high,t1,t3,t5,t10,...}
  PRIMARY KEY(date, code)
);
CREATE TABLE IF NOT EXISTS macro (
  code TEXT, date TEXT, value REAL, PRIMARY KEY(code, date)
);
"""

PRESET_POOLS = [
    ("dt_watchlist", "短线自选池", "DT", "system",
     "dt-review A级入池；status/horizon/days_watched 生命周期，标准票>10日无进展移出"),
    ("author_short", "作者短线池", "DT", "author", "用户每日导入作者名单（实证校准数据流）"),
    ("author_long", "作者长线池", "VF", "author", "作者长线标的（模块B对照）"),
    ("dt_rejected", "短线淘汰池", "DT", "system",
     "复盘剔除/门槛拦截/自选移出；前向跟踪检验假阴性"),
]


def _out(msg):
    try:
        sys.stdout.write(msg + "\n")
    except UnicodeEncodeError:
        sys.stdout.buffer.write((msg + "\n").encode("utf-8", "replace"))


def db_path():
    return Path(os.environ.get("WORKBENCH_DB", ROOT / "data" / "workbench.db"))


def connect():
    p = db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def norm_date(s):
    s = s.strip()
    return f"{s[:4]}-{s[4:6]}-{s[6:]}" if re.fullmatch(r"\d{8}", s) else s


def today():
    return datetime.date.today().isoformat()


def jdump(x):
    return json.dumps(x, ensure_ascii=False) if x is not None else None


def parse_codes(spec):
    """'600825.SH:新华传媒,000887.SZ' -> [(code, name)]"""
    out = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        code, _, name = part.partition(":")
        out.append((code.strip(), name.strip() or None))
    return out


# ---------------- init ----------------

def cmd_init(a):
    conn = connect()
    with conn:
        conn.executescript(SCHEMA)
        for key, title, domain, source, desc in PRESET_POOLS:
            conn.execute("INSERT OR IGNORE INTO pools VALUES (?,?,?,?,?,?,1)",
                         (key, title, domain, source, desc, today()))
        conn.execute("INSERT OR REPLACE INTO schema_version VALUES (1, ?)", (today(),))
    _out("init OK -> %s（预置池：%s）" % (db_path(), ", ".join(p[0] for p in PRESET_POOLS)))


# ---------------- import-day ----------------

def cmd_import_day(a):
    d = norm_date(a.day)
    snap = ROOT / "data" / "snapshots" / a.day.strip()
    if not snap.is_dir():
        _out("FAIL 快照目录不存在: %s" % snap)
        return 1
    conn = connect()
    n = {}

    def load(name):
        p = snap / name
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    s = load("sentiment.json")
    ms = load("market_summary.json")
    dk = load("daily_k_4codes.json")
    cands = load("candidates.json")

    with conn:
        if s:
            lu = a.limit_ups or s.get("涨停家数") or (ms or {}).get("涨停家数_全量非ST")
            conn.execute("INSERT OR REPLACE INTO sentiment VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                d, lu, s.get("跌停家数"), s.get("最高连板"), s.get("最高连板_标的"),
                s.get("连板晋级率%"), s.get("昨日涨停今日平均溢价%"), s.get("炸板家数"),
                s.get("两市成交额(亿)"),
                a.l1 or (s.get("L1_大盘环境") or {}).get("判定", ""),
                a.l2 or s.get("阶段判定", ""),
                a.combo or (s.get("组合基调") or {}).get("矩阵", ""),
                a.note or s.get("明日基调", ""),
                "data/snapshots/%s/sentiment.json" % a.day.strip()))
            n["sentiment"] = 1
            m = re.match(r"\s*(\d+)\s*/\s*(\d+)", str(s.get("沪深涨跌家数", "")))
            if m:
                conn.execute("INSERT OR REPLACE INTO market_daily VALUES (?,?,?,?,?,?,?,?)",
                             (d, "A_SHARE", "沪深A股(广度)", None, None, None, int(m.group(1)), int(m.group(2))))
                n["breadth"] = 1
        if ms:
            for sec in ms.get("板块聚类", []):
                conn.execute("INSERT OR REPLACE INTO sectors VALUES (?,?,?,?,?,?,?,?,?,?,?)", (
                    d, sec.get("板块", ""), None, sec.get("家数"), sec.get("环节", ""),
                    sec.get("分级", ""), sec.get("催化", ""), sec.get("梯队", ""), None,
                    1 if (a.qualified and a.qualified in sec.get("板块", "")) else 0,
                    sec.get("龙虎榜", "")))
                n["sectors"] = n.get("sectors", 0) + 1
            for i, t in enumerate(ms.get("龙虎榜净买入TOP10", [])):
                conn.execute("INSERT OR REPLACE INTO dragon_tiger VALUES (?,?,?,?,?,?)",
                             (d, t["code"], t["name"], i + 1, t["net_buy_yi"], ""))
                n["dragon_tiger"] = n.get("dragon_tiger", 0) + 1
        if dk:
            for code, rows in dk.items():
                if not isinstance(rows, list):
                    continue
                if code in INDEX_NAMES:  # 指数 → market_daily（含 pct 逐日计算）
                    prev = None
                    for r in rows:
                        close = r["收盘价"]
                        pct = None if prev in (None, 0) else round((close / prev - 1) * 100, 3)
                        prev = close
                        conn.execute("INSERT OR REPLACE INTO market_daily VALUES (?,?,?,?,?,?,?,?)",
                                     (r["日期"], code, INDEX_NAMES[code], close, pct,
                                      round(r.get("成交额", 0) / 1e8, 1), None, None))
                        n["market_daily"] = n.get("market_daily", 0) + 1
                else:  # 个股 → stock_daily
                    for r in rows:
                        conn.execute("INSERT OR REPLACE INTO stock_daily VALUES (?,?,?,?,?,?,?,?)",
                                     (code, r["日期"], r.get("开盘价"), r.get("最高价"),
                                      r.get("最低价"), r.get("收盘价"), r.get("成交额"),
                                      r.get("换手率")))
                        n["stock_daily"] = n.get("stock_daily", 0) + 1
        if cands:
            for c in cands:
                conn.execute("INSERT OR REPLACE INTO candidates VALUES (?,?,?,?,?,?,?,?,?,?,?)", (
                    d, c["code"], c.get("name", ""), c.get("sector", ""),
                    jdump(c.get("five_dim")), c.get("score"), c.get("grade", ""),
                    c.get("action", ""), jdump(c.get("indicators")),
                    jdump(c.get("intraday")), jdump(c.get("plan"))))
                n["candidates"] = n.get("candidates", 0) + 1
    _out("import-day %s: %s" % (d, ", ".join("%s=%d" % kv for kv in sorted(n.items())) or "无数据"))
    return 0


# ---------------- predictions ----------------

CSV_MAP = {  # CSV 列名 -> 表列名
    "日期": "reg_date", "代码": "code", "名称": "name", "方向": "direction",
    "判断内容": "content", "依据条目": "refs", "触发/目标条件": "trigger_cond",
    "失效/止损条件": "invalid_cond", "时间框架": "timeframe", "验证日期": "verify_date",
    "结果": "result", "复盘备注": "note",
}


def cmd_import_predictions_csv(a):
    src = Path(a.path)
    rows = list(csv.DictReader(open(src, encoding="utf-8")))
    conn = connect()
    with conn:
        for r in rows:
            note = r.get("复盘备注", "")
            if r.get("资产类型"):
                note = ("[%s] " % r["资产类型"]) + note
            conn.execute(
                "INSERT INTO predictions (reg_date,code,name,direction,content,refs,"
                "trigger_cond,invalid_cond,timeframe,verify_date,result,outcome,note)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (r.get("日期"), r.get("代码"), r.get("名称"), r.get("方向"), r.get("判断内容"),
                 r.get("依据条目"), r.get("触发/目标条件"), r.get("失效/止损条件"),
                 r.get("时间框架"), r.get("验证日期") or None, r.get("结果") or None,
                 float(r["盈亏幅度"]) if r.get("盈亏幅度") else None, note))
    _out("import-predictions-csv: %d 行（源文件冻结为历史存档）" % len(rows))


def cmd_add_prediction(a):
    conn = connect()
    with conn:
        cur = conn.execute(
            "INSERT INTO predictions (reg_date,code,name,direction,content,refs,"
            "trigger_cond,invalid_cond,timeframe) VALUES (?,?,?,?,?,?,?,?,?)",
            (norm_date(a.date), a.code, a.name, a.direction, a.content, a.refs,
             a.trigger, a.invalid, a.timeframe))
        _out("add-prediction OK id=%d" % cur.lastrowid)


def cmd_verify(a):
    conn = connect()
    sets, vals = ["verify_date=?"], [a.date or today()]
    if a.result is not None:
        sets.append("result=?"); vals.append(a.result)
    if a.outcome is not None:
        sets.append("outcome=?"); vals.append(a.outcome)
    if a.note:
        sets.append("note=COALESCE(note||char(10),'')||?"); vals.append(a.note)
    vals.append(a.id)
    with conn:
        cur = conn.execute("UPDATE predictions SET %s WHERE id=?" % ", ".join(sets), vals)
    _out("verify id=%d updated=%d" % (a.id, cur.rowcount))


# ---------------- pool ----------------

def _ensure_pool(conn, key, date):
    row = conn.execute("SELECT 1 FROM pools WHERE key=?", (key,)).fetchone()
    if not row:
        conn.execute("INSERT INTO pools VALUES (?,?,?,?,'',?,1)",
                     (key, key, "DT" if key.startswith(("dt_", "author_")) else "VF",
                      "user" if key.startswith("user_") else "user", date))


def cmd_pool(a):
    conn = connect()
    d = norm_date(a.date) if a.date else today()
    with conn:
        if a.action == "add":
            _ensure_pool(conn, a.pool, d)
            for code, name in parse_codes(a.codes):
                conn.execute("INSERT OR REPLACE INTO pool_members VALUES (?,?,?,?,?,?,?)",
                             (a.pool, code, name, d, "active", a.horizon, a.reason))
                conn.execute("INSERT INTO pool_events (date,pool,code,name,event,reason,extra,created_at)"
                             " VALUES (?,?,?,?,?,?,?,?)",
                             (d, a.pool, code, name, "add", a.reason, jdump({"horizon": a.horizon}), today()))
            _out("pool add %s: %d 只" % (a.pool, len(parse_codes(a.codes))))
        elif a.action == "remove":
            for code, name in parse_codes(a.codes):
                conn.execute("UPDATE pool_members SET status='removed' WHERE pool=? AND code=?",
                             (a.pool, code))
                conn.execute("INSERT INTO pool_events (date,pool,code,name,event,reason,created_at)"
                             " VALUES (?,?,?,?,?,?,?)", (d, a.pool, code, name, "remove", a.reason, today()))
            _out("pool remove %s: %d 只" % (a.pool, len(parse_codes(a.codes))))
        elif a.action == "move":
            # 文档用法是 pool move <代码> --from ... --to ...：代码落在第一个位置参数上
            code = a.code or (a.pool if a.pool and re.fullmatch(r"[0-9A-Za-z.\-]{5,12}", a.pool) else None)
            if not code or not a.frm or not a.to:
                _out("FAIL move 需要：pool move <代码> --from <源池> --to <目标池> [--name 名称]")
                return 1
            _ensure_pool(conn, a.to, d)
            conn.execute("UPDATE pool_members SET status='removed' WHERE pool=? AND code=?", (a.frm, code))
            conn.execute("INSERT OR REPLACE INTO pool_members VALUES (?,?,?,?,?,?,?)",
                         (a.to, code, a.name or code, d, "active", None, a.reason))
            conn.execute("INSERT INTO pool_events (date,pool,code,name,event,reason,extra,created_at)"
                         " VALUES (?,?,?,?,?,?,?,?)",
                         (d, a.to, code, a.name or code, "move", a.reason,
                          jdump({"from": a.frm, "to": a.to}), today()))
            _out("pool move %s: %s -> %s" % (code, a.frm, a.to))
        elif a.action == "list":
            for r in conn.execute("SELECT p.key,p.title,p.source,"
                                  "(SELECT COUNT(*) FROM pool_members m WHERE m.pool=p.key AND m.status='active') c"
                                  " FROM pools p ORDER BY p.key"):
                _out("%-14s %-10s %-7s 成员 %d" % (r["key"], r["title"], r["source"], r["c"]))
        elif a.action == "events":
            for r in conn.execute("SELECT date,pool,code,name,event,reason FROM pool_events %s ORDER BY id"
                                  % ("WHERE pool='%s'" % a.pool if a.pool else ""),
                                  ):
                _out("%s %-14s %-10s %-12s %-6s %s" % (r["date"], r["pool"], r["code"],
                                                        r["name"] or "", r["event"], r["reason"] or ""))


# ---------------- report-add ----------------

def cmd_report_add(a):
    md = Path(a.md)
    if not md.is_file():
        _out("FAIL md 不存在: %s" % md)
        return 1
    content = md.read_text(encoding="utf-8")
    conn = connect()
    with conn:
        cur = conn.execute(
            "INSERT INTO reports (date,kind,domain,title,content_md,conclusion,"
            "related_codes,related_sectors,refs,md_path,html_path,created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(date,kind,title) DO UPDATE SET content_md=excluded.content_md,"
            " conclusion=excluded.conclusion, related_codes=excluded.related_codes,"
            " related_sectors=excluded.related_sectors, refs=excluded.refs,"
            " md_path=excluded.md_path, html_path=excluded.html_path",
            (norm_date(a.date), a.kind, a.domain or "DT", a.title, content, a.conclusion or "",
             jdump([c.strip() for c in a.codes.split(",") if c.strip()]) if a.codes else "[]",
             jdump([s.strip() for s in a.sectors.split(",") if s.strip()]) if a.sectors else "[]",
             a.refs or "", str(md), a.html or "", today()))
        _out("report-add OK id=%s（《%s》%d 字符）" % (cur.lastrowid, a.title, len(content)))
    return 0


# ---------------- export / query ----------------

def cmd_export(a):
    d = norm_date(a.day)
    out = ROOT / "data" / "exports" / d
    out.mkdir(parents=True, exist_ok=True)
    conn = connect()
    spec = [("sentiment", "date"), ("sectors", "date"), ("candidates", "date"),
            ("dragon_tiger", "date"), ("market_daily", "date"), ("stock_daily", "date"),
            ("pool_events", None), ("predictions", None),
            ("reports", "date")]
    wrote = []
    for table, col in spec:
        where = "WHERE %s=?" % col if col else ""
        rows = conn.execute("SELECT * FROM %s %s" % (table, where), (d,) if col else ()).fetchall()
        if table == "reports":  # 导出元数据，全文以 reports/ 存档原件为准
            rows = [{k: r[k] for k in r.keys() if k != "content_md"} for r in rows]
        else:
            rows = [dict(r) for r in rows]
        p = out / ("%s.csv" % table)
        with open(p, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["empty"])
            w.writeheader()
            w.writerows(rows)
        wrote.append("%s(%d)" % (table, len(rows)))
    _out("export %s -> %s：%s" % (d, out, ", ".join(wrote)))


def cmd_query(a):
    sql = a.sql.strip()
    if not sql.lower().startswith("select"):
        _out("FAIL 仅允许 SELECT")
        return 1
    conn = connect()
    cur = conn.execute(sql)
    cols = [c[0] for c in cur.description]
    rows = cur.fetchall()
    _out(" | ".join(cols))
    for r in rows[:500]:
        _out(" | ".join(str(v) for v in tuple(r)))
    if len(rows) > 500:
        _out("...（共 %d 行，仅显示 500）" % len(rows))
    else:
        _out("(%d 行)" % len(rows))


# ---------------- selftest ----------------

def cmd_selftest(a):
    tmp = Path(tempfile.mkdtemp()) / "selftest.db"
    os.environ["WORKBENCH_DB"] = str(tmp)
    ok = True
    try:
        cmd_init(argparse.Namespace())
        conn = connect()
        with conn:
            conn.execute("INSERT INTO pool_members VALUES ('dt_watchlist','600000.SH','测试票','2026-10-17','active','标准','自测')")
        ns = argparse.Namespace
        cmd_pool(ns(action="add", pool="dt_watchlist", codes="600001.SH:浦发", reason="自测",
                    horizon=None, date="20261017", frm=None, to=None, code=None, name=None))
        cmd_add_prediction(ns(date="2026-10-17", code="600001.SH", name="浦发", direction="看多",
                              content="自测判断", refs="DT-J-004", trigger="t", invalid="i",
                              timeframe="1日"))
        cmd_verify(ns(id=1, result="对", outcome=1.5, note="自测", date="2026-10-18"))
        md = tmp.parent / "r.md"
        md.write_text("# 自测报告\n正文", encoding="utf-8")
        cmd_report_add(ns(date="2026-10-17", kind="review", domain="DT", title="自测",
                          md=str(md), conclusion="c", codes="600001.SH", sectors="银行",
                          refs="DT-J-004", html=None))
        checks = {
            "sentiment 表存在": conn.execute("SELECT COUNT(*) FROM sentiment").fetchone()[0] >= 0,
            "预置池=4": conn.execute("SELECT COUNT(*) FROM pools").fetchone()[0] == 4,
            "成员=2": conn.execute("SELECT COUNT(*) FROM pool_members").fetchone()[0] == 2,
            "事件≥1": conn.execute("SELECT COUNT(*) FROM pool_events").fetchone()[0] >= 1,
            "台账=1 且已验证": conn.execute(
                "SELECT result,outcome FROM predictions WHERE id=1").fetchone()[0] == "对",
            "报告全文": conn.execute("SELECT content_md FROM reports").fetchone()[0].startswith("# 自测"),
        }
        for k, v in checks.items():
            if not v:
                ok = False
            _out(("PASS " if v else "FAIL ") + k)
        cmd_export(ns(day="2000-01-01"))  # 自测导出走固定假日期，避免污染真实日期目录
        import shutil
        shutil.rmtree(ROOT / "data" / "exports" / "2000-01-01", ignore_errors=True)
    finally:
        os.environ.pop("WORKBENCH_DB", None)
    _out("selftest: %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


# ---------------- main ----------------

def main(argv=None):
    ap = argparse.ArgumentParser(description="workbench.db 管理与写入 CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init").set_defaults(fn=cmd_init)

    p = sub.add_parser("import-day")
    p.add_argument("day")
    p.add_argument("--l1"); p.add_argument("--l2"); p.add_argument("--combo")
    p.add_argument("--note"); p.add_argument("--qualified")
    p.add_argument("--limit-ups", type=int)
    p.set_defaults(fn=cmd_import_day)

    p = sub.add_parser("import-predictions-csv")
    p.add_argument("path")
    p.set_defaults(fn=cmd_import_predictions_csv)

    p = sub.add_parser("add-prediction")
    for arg, kw in [("date", {}), ("code", {}), ("name", {}), ("direction", {}),
                    ("content", {}), ("refs", {"default": ""}), ("trigger", {"default": ""}),
                    ("invalid", {"default": ""}), ("timeframe", {"default": ""})]:
        p.add_argument("--" + arg, required=(arg in ("date", "code", "name", "direction", "content")), **kw)
    p.set_defaults(fn=cmd_add_prediction)

    p = sub.add_parser("verify")
    p.add_argument("id", type=int)
    p.add_argument("--result"); p.add_argument("--outcome", type=float)
    p.add_argument("--note", default=""); p.add_argument("--date")
    p.set_defaults(fn=cmd_verify)

    p = sub.add_parser("pool")
    p.add_argument("action", choices=["add", "remove", "move", "list", "events"])
    p.add_argument("pool", nargs="?")
    p.add_argument("code", nargs="?")  # move/remove 的标的代码（位置参数）
    p.add_argument("--codes"); p.add_argument("--name")
    p.add_argument("--from", dest="frm"); p.add_argument("--to")
    p.add_argument("--reason", default=""); p.add_argument("--horizon")
    p.add_argument("--date")
    p.set_defaults(fn=cmd_pool)

    p = sub.add_parser("report-add")
    p.add_argument("--date", required=True); p.add_argument("--kind", required=True)
    p.add_argument("--title", required=True); p.add_argument("--md", required=True)
    p.add_argument("--domain"); p.add_argument("--conclusion")
    p.add_argument("--codes", default=""); p.add_argument("--sectors", default="")
    p.add_argument("--refs", default=""); p.add_argument("--html")
    p.set_defaults(fn=cmd_report_add)

    p = sub.add_parser("export")
    p.add_argument("day")
    p.set_defaults(fn=cmd_export)

    p = sub.add_parser("query")
    p.add_argument("sql")
    p.set_defaults(fn=cmd_query)

    sub.add_parser("selftest").set_defaults(fn=cmd_selftest)

    a = ap.parse_args(argv)
    rc = a.fn(a)
    return rc or 0


if __name__ == "__main__":
    sys.exit(main())
