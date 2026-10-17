#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""报告模板自检（四类短线产出的结构契约检查）。

用法：
  python tools/report_lint.py <报告.md> --type review|stock|sector|briefing [--dashboard <看板.html>]
  python tools/report_lint.py --selftest

检查项：
  1) md 报告：必需章节/关键词齐全（按模板逐节锁定）
  2) md 报告：无残留占位符（{{ / TODO）
  3) html 看板：不出现知识条目编号（用户看不懂）；含"数据出处"页脚
退出码：0 通过；1 存在问题（问题清单打印到 stdout）。
"""
import argparse
import re
import sys
import tempfile
from pathlib import Path

REQUIRED = {
    "review": [
        r"## 0\.", r"## 1\.", "三层情绪", "组合基调",
        r"## 2\.", "板块地图", "主线",
        r"## 3\.", "推荐标的", "指标参考",
        r"## 4\.", "自选滚动", "持仓对策",
        r"## 5\.", "预判验证",
        r"## 6\.", "台账登记", "附录A", "数据出处",
    ],
    "stock": [
        r"## 0\.", "结论卡", r"## 1\.", "前次判断对账",
        r"## 2\.", r"## 3\.", "日线位置", r"## 4\.", "分时承接力",
        r"## 5\.", "情绪环境", r"## 6\.", "综合判定", r"## 7\.", "台账登记",
        "附录A", "数据出处",
    ],
    "sector": [
        r"## 0\.", "环节", r"## 1\.", "对比池", r"## 2\.", "对比矩阵",
        r"## 3\.", "逐标的点评", r"## 4\.", "结论排序", r"## 5\.", "台账登记",
        "附录A", "数据出处",
    ],
    "briefing": [
        r"## 0\.", "基调预案", r"## 1\.", "消息面", r"## 2\.", "昨日情绪",
        r"## 3\.", "观察清单", r"## 4\.", r"## 5\.", "附录A", "数据出处",
    ],
}
FORBIDDEN_MD = ["{{", "TODO"]
FORBIDDEN_HTML = ["DT-J-", "DT-R-", "DT-S-", "XC-J-", "XC-R-", "SRC-DT", "SRC-TR", "USER-20"]
REQUIRED_HTML = ["数据出处"]


def lint_md(path: Path, typ: str):
    text = path.read_text(encoding="utf-8")
    issues = []
    for pat in REQUIRED[typ]:
        if not re.search(pat, text, re.M):
            issues.append("缺少必需章节/关键词: %s" % pat)
    for w in FORBIDDEN_MD:
        if w in text:
            issues.append("残留未填占位符: %s" % w)
    return issues


def lint_html(path: Path):
    text = path.read_text(encoding="utf-8")
    issues = []
    for w in FORBIDDEN_HTML:
        if w in text:
            issues.append("看板出现知识条目代号（用户看不懂）: %s" % w)
    for w in REQUIRED_HTML:
        if w not in text:
            issues.append("看板缺少必需元素: %s" % w)
    return issues


def _out(msg):
    try:
        sys.stdout.write(msg + "\n")
    except UnicodeEncodeError:
        sys.stdout.buffer.write((msg + "\n").encode("utf-8", "replace"))


def main(argv=None):
    ap = argparse.ArgumentParser(description="报告模板自检")
    ap.add_argument("report", nargs="?", help="报告 md 路径")
    ap.add_argument("--type", choices=sorted(REQUIRED), help="模板类型")
    ap.add_argument("--dashboard", help="看板 html 路径（可选）")
    ap.add_argument("--selftest", action="store_true", help="内置样例自测")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()

    if not args.report or not args.type:
        ap.error("需要 <报告.md> 与 --type")
    report = Path(args.report)
    if not report.exists():
        _out("FAIL 文件不存在: %s" % report)
        return 1

    issues = lint_md(report, args.type)
    if args.dashboard:
        db = Path(args.dashboard)
        if not db.exists():
            issues.append("看板文件不存在: %s" % db)
        else:
            issues += lint_html(db)

    if issues:
        _out("FAIL %s（type=%s）" % (report.name, args.type))
        for i in issues:
            _out("  - " + i)
        return 1
    _out("PASS %s（type=%s%s）" % (report.name, args.type,
                                   " + 看板" if args.dashboard else ""))
    return 0


GOOD_STOCK = """# 测试票（000000.TEST）短线分析 · 2026-10-17
## 0. 结论卡
| 项 | 内容 |
| 综合评级 | B |
## 1. 前次判断对账
首次分析，无历史台账。
## 2. 基本面与题材定位（事实层）
数据缺失（问财未返回）
## 3. 日线位置（事实层）
收盘 10.00。
## 4. 分时承接力（指标层——必须实际运行 tools/indicators.py）
| 指标 | 数值 | 状态 |
## 5. 情绪环境（引用当日已落盘数据，勿重算）
L1 低迷。
## 6. 综合判定（判断层）
| # | 判断 | 类型 | 依据 | 支撑数据 |
## 7. 台账登记
本次无可验证判断新增。
## 附录A. 数据出处
| 数据 | 工具 | 落盘文件 / 说明 |
"""

BAD_STOCK = """# 测试票 短线分析
## 0. 结论卡
{{评级}}
## 2. 某节
TODO
## 附录A. 数据出处
"""

GOOD_DASH = """<!DOCTYPE html><html><body>看板 OK 数据出处：示例</body></html>"""
BAD_DASH = """<!DOCTYPE html><html><body>依据 DT-J-017 判定</body></html>"""


def selftest():
    tmp = Path(tempfile.mkdtemp())
    ok = True

    g = tmp / "good.md"
    g.write_text(GOOD_STOCK, encoding="utf-8")
    gd = tmp / "good.html"
    gd.write_text(GOOD_DASH, encoding="utf-8")
    r = main([str(g), "--type", "stock", "--dashboard", str(gd)])
    if r != 0:
        ok = False
        _out("selftest: 应通过的正例未通过")

    b = tmp / "bad.md"
    b.write_text(BAD_STOCK, encoding="utf-8")
    bd = tmp / "bad.html"
    bd.write_text(BAD_DASH, encoding="utf-8")
    r = main([str(b), "--type", "stock", "--dashboard", str(bd)])
    if r == 0:
        ok = False
        _out("selftest: 应失败的反例竟通过")
    _out("selftest: %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
