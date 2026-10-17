# -*- coding: utf-8 -*-
"""分时量价指标工具箱 —— knowledge/distilled/dt/volume-price.md 的实现。

纯标准库实现，无第三方依赖。输入统一为"分钟K列表"，每根 bar 为 dict：
  {"time": "09:31", "open": f, "high": f, "low": f, "close": f,
   "volume": float(手), "amount": float(元)}
时间升序排列。历史日线/分钟线建议先落盘 data/snapshots/，盘中增量计算。

用法（库）:
    from indicators import vwap_series, sell_check_sanbuqu
用法（CLI 冒烟自测）:
    python tools/indicators.py selftest
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# ---------- 基础工具 ----------

def load_bars(path: str | Path) -> list[dict]:
    bars = json.loads(Path(path).read_text(encoding="utf-8"))
    bars.sort(key=lambda b: b["time"])
    return bars


def _num(v) -> float | None:
    """None/空串安全转 float（一字板零成交日的 volume/amount 常为 null）。"""
    if v is None or v == "":
        return None
    return float(v)


def cum(bars: list[dict], key: str) -> list[float]:
    """逐根累计（volume 或 amount），null 视为 0。"""
    out, s = [], 0.0
    for b in bars:
        v = _num(b.get(key)) or 0.0
        s += v
        out.append(s)
    return out


# ---------- DT-R-041 VWAP（黄线） ----------

def vwap_series(bars: list[dict]) -> list[dict]:
    """累计成交额 ÷ 累计成交量，逐分钟返回 {time, vwap}。全天零成交返回 None。"""
    amounts, vols = cum(bars, "amount"), cum(bars, "volume")
    out = []
    for b, a, v in zip(bars, amounts, vols):
        out.append({"time": b["time"], "vwap": (a / v) if v > 0 else None})
    return out


def bias(price: float, vwap: float) -> float:
    """白线对黄线的乖离（%），DT-R-004/006 的 3% 阈值即此值。"""
    return (price - vwap) / vwap * 100


# ---------- DT-R-042 同期量比 ----------

def volume_ratio_at(today: list[dict], hist_days: list[list[dict]], at_time: str) -> float | None:
    """今日 at_time 累计量 ÷ 近N日同时刻累计量均值。hist 缺该时刻则跳过该日。"""
    idx = next((i for i, b in enumerate(today) if b["time"] >= at_time), len(today) - 1)
    t_vol = cum(today, "volume")[idx]
    vals = []
    for day in hist_days:
        j = next((i for i, b in enumerate(day) if b["time"] >= at_time), None)
        if j is None or cum(day, "volume")[j] <= 0:
            continue
        vals.append(cum(day, "volume")[j])
    if not vals or sum(vals) == 0:
        return None
    return t_vol / (sum(vals) / len(vals))


def volume_ratio_labels(r: float | None) -> str:
    if r is None:
        return "无基数"
    if r < 0.7:
        return "显著缩量"
    if r < 1.5:
        return "常态"
    if r < 3:
        return "温和放量"
    return "显著放量"


# ---------- DT-R-043 上行量/下行量 ----------

def updown_volume(bars: list[dict]) -> dict:
    """按分钟 close vs open 涨跌归类量（平盘减半入上行）。窗口≥30分钟才有意义。"""
    up = down = flat = 0.0
    for b in bars:
        v = _num(b.get("volume")) or 0.0
        o, c = _num(b.get("open")), _num(b.get("close"))
        if o is None or c is None:
            flat += v
            continue
        if c > o:
            up += v
        elif c < o:
            down += v
        else:
            flat += v
    total = up + down + flat
    return {
        "up": up, "down": down, "flat": flat, "total": total,
        "up_ratio": (up + flat / 2) / total * 100 if total > 0 else None,
    }


# ---------- DT-R-044 脉冲量与回撤测试 ----------

def pulse_events(bars: list[dict], mult: float = 3.0, lookback: int = 20, check_after: int = 5) -> list[dict]:
    """单分钟额 > 前lookback分钟均值×mult 记脉冲；检验其后check_after分钟的价格回落。
    小票（日额<5亿）建议 mult=5（专章第六节噪声规则）。涨停/跌停价附近的脉冲只记不判。
    """
    events = []
    for i in range(lookback, len(bars) - check_after):
        amt = _num(bars[i].get("amount")) or 0.0
        base = sum(_num(b.get("amount")) or 0.0 for b in bars[i - lookback:i]) / lookback
        if base <= 0 or amt < base * mult:
            continue
        p0 = _num(bars[i].get("close"))
        after = [b for b in bars[i + 1:i + 1 + check_after] if _num(b.get("low")) is not None]
        if p0 is None or not after:
            drop = None
        else:
            trough = min(_num(b.get("low")) for b in after)
            drop = (p0 - trough) / p0 * 100
        verdict = None if drop is None else ("承接强" if drop < 0.3 else "出货嫌疑" if drop > 1.0 else "中性")
        events.append({"time": bars[i]["time"], "amount": amt, "drop_pct": drop, "verdict": verdict})
    return events


# ---------- DT-J-022 量价状态矩阵 ----------

def state_matrix(bars: list[dict], hist_days: list[list[dict]] | None = None,
                 prev_close: float | None = None, support: float | None = None) -> dict:
    """合成持仓状态灯。参数: prev_close=昨收(红盘基准), support=5日线(可选)。
    返回各分量与灯色: 绿/黄/红。规则见 volume-price.md DT-J-022/DT-R-045。
    """
    if not bars:
        return {"state": "无数据"}
    vw = [x["vwap"] for x in vwap_series(bars) if x["vwap"]]
    price = _num(bars[-1]["close"])
    # VWAP 斜率：近10分钟首尾变化率
    slope = None
    if len(vw) >= 10:
        slope = (vw[-1] - vw[-10]) / vw[-10] * 100
    # 同期量比
    vr = volume_ratio_at(bars, hist_days or [], bars[-1]["time"]) if hist_days else None
    on_vwap = vw and price >= vw[-1]
    below_vwap = vw and price < vw[-1]
    red = prev_close is not None and price > prev_close

    state, action = None, None
    if slope is not None and slope < -0.02 and (vr or 0) >= 1.5 and below_vwap:
        state, action = "红·放量破线", "立即走，不等时间窗（DT-R-045）"
    elif slope is not None and slope < -0.02 and (vr is not None and vr < 0.7):
        far = support is not None and (price - support) / support * 100 > 3
        state = "红·衰竭阴跌" + ("（离支撑远）" if far else "")
        action = "早走" if far else "按三部曲时间窗"
    elif slope is not None and abs(slope) <= 0.02 and (vr is not None and vr < 0.7):
        state, action = "黄·缩量预警", "收紧为破黄线即走"
    elif slope is not None and slope > 0.02 and on_vwap and red:
        state, action = "绿·强承接", "持有"
    else:
        state, action = "绿·均衡观察", "持有观察"
    return {
        "time": bars[-1]["time"], "price": price, "vwap": vw[-1] if vw else None,
        "vwap_slope_pct_10min": slope, "volume_ratio": vr,
        "volume_ratio_label": volume_ratio_labels(vr),
        "above_vwap": on_vwap, "red": red, "state": state, "action": action,
    }


# ---------- DT-R-001/002/003 三部曲时间窗检查 ----------

def sell_check_sanbuqu(bars: list[dict], prev_close: float, prev_day_limit_up: bool,
                       now_time: str | None = None) -> dict:
    """三部曲第一条：N分钟内是否曾翻红（close > prev_close）。
    prev_day_limit_up=True → 30分钟窗；False → 60分钟窗。
    未翻红且分时向上爬 → 宽限提示（DT-R-003）。
    """
    window = 30 if prev_day_limit_up else 60
    now = now_time or bars[-1]["time"]
    window_bars = [b for b in bars if b["time"] <= _plus_min("09:30", window)]
    ever_red = any((_num(b.get("close")) or 0) > prev_close for b in window_bars if _num(b.get("close")))
    # 宽限：最近10根 bar 收盘价逐升（近似白线上爬）
    recent = [(_num(b.get("close")) or 0) for b in bars[-10:]]
    climbing = len(recent) >= 5 and all(y > x for x, y in zip(recent, recent[1:]))
    if ever_red:
        verdict, action = "已翻红", "第一条不触发，走第二/三条（冲高回落/尾盘）"
    elif now > _plus_min("09:30", window) and not climbing:
        verdict, action = f"{window}分钟未红盘", "执行卖出（DT-R-001/002）"
    elif now > _plus_min("09:30", window) and climbing:
        verdict, action = f"{window}分钟未红但分时向上", "宽限观察（DT-R-003），转平即卖"
    else:
        verdict, action = f"窗口内({window}分钟)", "等待"
    return {"window_min": window, "ever_red": ever_red, "verdict": verdict, "action": action}


def _plus_min(hhmm: str, minutes: int) -> str:
    h, m = map(int, hhmm.split(":"))
    return f"{h + (m + minutes) // 60:02d}:{(m + minutes) % 60:02d}"


# ---------- DT-R-024/025 实际流通口径 ----------

def actual_free_float(market_cap: float, top10_pct: float) -> float:
    """实际流通市值 = 流通市值 × (1 − 前十大流通股东合计占比)。top10_pct 传百分数。"""
    return market_cap * (1 - top10_pct / 100)


def actual_turnover(turnover_pct: float, top10_pct: float) -> float | None:
    free = 1 - top10_pct / 100
    return turnover_pct / free if free > 0 else None


# ---------- DT-R-018 竞价金额 ----------

def auction_amount(volume_hands: float, open_price: float) -> float:
    """集合竞价成交金额 = 竞价成交量(手) × 100 × 开盘价。"""
    return volume_hands * 100 * open_price


# ---------- DT-R-030 情绪指标组聚合 ----------

def sentiment_stats(lu_today: list, prev_lu_perf: list[dict], limit_down_count: int,
                    adv: int, dec: int, turnover_yi: float) -> dict:
    """lu_today: 今日涨停清单(问财结果行)；prev_lu_perf: 昨日涨停股今日表现
    （每行含 涨跌幅 数值与 连续涨停天数）；adv/dec 全市场涨跌家数；turnover_yi 两市成交额(亿)。
    """
    n_lu = len(lu_today)
    max_streak = max((int(r.get("连续涨停天数", 0) or 0) for r in lu_today), default=0)
    promoted = [r for r in prev_lu_perf if int(r.get("连续涨停天数", 0) or 0) > 0]
    promo_rate = len(promoted) / len(prev_lu_perf) * 100 if prev_lu_perf else None
    rets = [float(r["涨跌幅:前复权"]) for r in prev_lu_perf if r.get("涨跌幅:前复权") not in (None, "")]
    avg_premium = sum(rets) / len(rets) if rets else None
    return {
        "涨停家数": n_lu, "跌停家数": limit_down_count, "最高连板": max_streak,
        "晋级率%": round(promo_rate, 1) if promo_rate is not None else None,
        "昨日涨停今日平均溢价%": round(avg_premium, 2) if avg_premium is not None else None,
        "涨跌家数": f"{adv}/{dec}", "两市成交额(亿)": turnover_yi,
    }


# ---------- 冒烟自测 ----------

def _selftest() -> str:
    bars, price = [], 10.0
    for i in range(1, 61):  # 模拟 9:31-10:30：先横盘承接后脉冲拉升
        t = _plus_min("09:30", i)
        amt = 8_000_000
        if i == 40:
            amt = 40_000_000
        price += 0.01 if i > 35 else 0.0
        bars.append({"time": t, "open": price, "high": price, "low": price,
                     "close": price, "volume": amt / price, "amount": amt})
    vw = vwap_series(bars)
    ud = updown_volume(bars)
    pe = pulse_events(bars)
    sm = state_matrix(bars, prev_close=9.9)
    sq = sell_check_sanbuqu(bars, prev_close=9.9, prev_day_limit_up=True)
    return json.dumps({
        "vwap_last": round(vw[-1]["vwap"], 3),
        "bias_pct": round(bias(price, vw[-1]["vwap"]), 3),
        "up_ratio": round(ud["up_ratio"], 1),
        "pulses": pe,
        "matrix": sm,
        "sanbuqu": sq,
        "actual_float_example": actual_free_float(110e8, 85),
        "actual_turnover_example": actual_turnover(5.0, 80),
        "auction_example": auction_amount(375026, 3.66),
    }, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "selftest"
    if cmd == "selftest":
        print(_selftest())
    else:
        print(__doc__)
