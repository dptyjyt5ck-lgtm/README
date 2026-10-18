"""The watchman: free, code-only market scan every minute. Claude is called only for its candidates.

A market is a candidate when the higher timeframes agree on a direction and the entry timeframe shows
a trigger in that direction: a pullback to the 20-bar average that turns back, a breakout of the last
20 bars, or a volume spike with a strong candle.
"""


def sma(values, n):
    return sum(values[-n:]) / min(n, len(values))


def trend(bars):
    """up / down / sideways from close vs SMA20 vs SMA50."""
    if len(bars) < 30:
        return "unknown"
    closes = [b["close"] for b in bars]
    s20, s50 = sma(closes, 20), sma(closes, 50)
    if closes[-1] > s20 > s50:
        return "up"
    if closes[-1] < s20 < s50:
        return "down"
    return "sideways"


def triggers(bars, direction):
    """Entry-timeframe reasons to look now, in the given direction ("up" / "down")."""
    found = []
    closes = [b["close"] for b in bars]
    last, s20 = bars[-1], sma(closes, 20)
    sign = 1 if direction == "up" else -1
    avg_vol = sum(b["volume"] for b in bars[-21:-1]) / 20
    vol_ratio = last["volume"] / avg_vol if avg_vol else 0.0

    recent = bars[-4:-1]
    touched = any(b["low"] <= s20 for b in recent) if sign > 0 else any(b["high"] >= s20 for b in recent)
    if touched and (last["close"] - s20) * sign > 0 and (last["close"] - last["open"]) * sign > 0:
        found.append("откат к средней и разворот по тренду")

    prior = bars[-21:-1]
    if sign > 0 and last["close"] > max(b["high"] for b in prior):
        found.append("пробой максимума 20 свечей")
    if sign < 0 and last["close"] < min(b["low"] for b in prior):
        found.append("пробой минимума 20 свечей")

    body = (last["close"] - last["open"]) * sign
    rng = last["high"] - last["low"]
    if vol_ratio >= 2.0 and body > 0 and rng and body / rng >= 0.5:
        found.append(f"всплеск объёма {vol_ratio:.1f}× с сильной свечой")
    return found, vol_ratio


def scan(symbol, entry_bars, context):
    """Candidate dict or None. context: {timeframe_label: bars} of higher timeframes (may be empty)."""
    if len(entry_bars) < 30:
        return None
    trends = {tf: trend(bars) for tf, bars in context.items()}
    votes = [t for t in trends.values() if t in ("up", "down")]
    if context:
        if not votes or len(set(votes)) != 1 or len(votes) < max(1, len(context) - 1):
            return None  # higher timeframes disagree or are flat
        direction = votes[0]
    else:
        direction = trend(entry_bars)
        if direction not in ("up", "down"):
            return None
    found, vol_ratio = triggers(entry_bars, direction)
    if not found:
        return None
    return {"symbol": symbol, "direction": direction, "triggers": found, "trends": trends,
            "volume_ratio": round(vol_ratio, 2), "score": len(found) + min(vol_ratio, 5) / 5}


def scout_output(candidate, label):
    """The candidate reshaped as a regular Scout Bot answer, so Risk and Decision read it the same way."""
    trends = ", ".join(f"{tf} {t}" for tf, t in candidate["trends"].items())
    return {
        "market": candidate["symbol"],
        "reason_to_research": f"Направление {candidate['direction']} ({trends or 'по входному таймфрейму'}); "
                              + "; ".join(candidate["triggers"]),
        "liquidity_status": "high",
        "data_quality": "good",
        "sources": [label],
        "confidence": min(90, 40 + 15 * len(candidate["triggers"])),
    }
