"""Deterministic offline answers so the whole pipeline runs with no key and no network.

Each function reads only the packet and earlier outputs, like a model would, and
returns a JSON string. They are simple rules, not analysis.
"""
import json

HYPE_WORDS = ("moon", "100x", "guaranteed", "can't lose", "🚀", "all in")
BULL_WORDS = ("buy", "strong", "up", "beat", "breakout", "bullish", "growth")
BEAR_WORDS = ("sell", "weak", "down", "miss", "dump", "bearish", "overvalued")
POSITIVE_NEWS = ("beat", "rise", "growth", "record", "raises", "up")
NEGATIVE_NEWS = ("miss", "fall", "lawsuit", "cut", "probe", "down")


def _bars(packet):
    return packet.get("price_history") or []


def scout(packet, inputs):
    bars = _bars(packet)
    if len(bars) < 2:
        return {
            "market": packet.get("market", "UNKNOWN"),
            "reason_to_research": "Нет истории цен — исследовать нечего.",
            "liquidity_status": "unknown",
            "data_quality": "poor",
            "sources": [packet.get("_label", "")],
            "confidence": 0,
        }
    last, prev = bars[-1], bars[-2]
    avg_vol = sum(b["volume"] for b in bars[:-1]) / (len(bars) - 1)
    ratio = last["volume"] / avg_vol
    move = (last["close"] / prev["close"] - 1) * 100
    dollar_vol = avg_vol * last["close"]
    liquidity = "high" if dollar_vol > 20e6 else "medium" if dollar_vol > 1e6 else "low"
    quality = "partial" if not packet.get("intraday") else "good"
    return {
        "market": packet["market"],
        "reason_to_research": f"Объём {ratio:.1f}× к среднему за {len(bars) - 1} дн. после движения {move:+.1f}%.",
        "liquidity_status": liquidity,
        "data_quality": quality,
        "sources": [packet.get("_label", "")],
        "confidence": 65 if ratio > 1.5 else 40,
    }


def news(packet, inputs):
    pos, neg, unverified, sources = [], [], [], []
    for item in packet.get("news", []):
        text = item.get("headline", "")
        sources.append(item.get("source", "?"))
        if item.get("source_type") != "newswire":
            unverified.append(f"{item.get('source', '?')}: {text}")
        elif any(w in text.lower() for w in POSITIVE_NEWS):
            pos.append(text)
        elif any(w in text.lower() for w in NEGATIVE_NEWS):
            neg.append(text)
    return {
        "summary": f"{len(pos)} позитивн., {len(neg)} негативн. сообщений; {len(unverified)} непроверенных утверждений.",
        "positive_events": pos,
        "negative_events": neg,
        "unverified_claims": unverified,
        "sources": sources,
        "last_updated": packet.get("as_of", ""),
    }


def sentiment(packet, inputs):
    posts = packet.get("social_posts", [])
    bull = bear = 0
    hype = []
    for p in posts:
        t = p.get("text", "").lower()
        bull += any(w in t for w in BULL_WORDS)
        bear += any(w in t for w in BEAR_WORDS)
        if any(w in t for w in HYPE_WORDS):
            hype.append(p.get("text", ""))
    if not posts:
        label, score = "unknown", 0
    else:
        score = round(100 * (bull - bear) / len(posts))
        label = "positive" if score > 40 else "negative" if score < -40 else "mixed" if bull and bear else "neutral"
    return {
        "sentiment": label,
        "score": score,
        "main_reasons": [f"бычьих постов: {bull}, медвежьих: {bear}, всего: {len(posts)}"],
        "possible_hype": hype,
        "sources": sorted({p.get("source", "?") for p in posts}),
    }


def charts(packet, inputs):
    bars = _bars(packet)
    missing = [] if packet.get("intraday") else ["intraday"]
    if len(bars) < 20:
        return {
            "trend": "unknown",
            "support_levels": [],
            "resistance_levels": [],
            "volume_summary": "Недостаточно данных.",
            "setup_quality": "unknown",
            "missing_data": ["price_history"] + missing,
        }
    closes = [b["close"] for b in bars]
    sma10, sma20 = sum(closes[-10:]) / 10, sum(closes[-20:]) / 20
    trend = "up" if closes[-1] > sma10 > sma20 else "down" if closes[-1] < sma10 < sma20 else "sideways"
    support = sorted({round(min(b["low"] for b in bars[-n:]), 2) for n in (10, 20)}, reverse=True)
    resist = sorted({round(max(b["high"] for b in bars[-n:]), 2) for n in (10, 20)})
    avg_vol = sum(b["volume"] for b in bars[:-1]) / (len(bars) - 1)
    return {
        "trend": trend,
        "support_levels": support,
        "resistance_levels": resist,
        "volume_summary": f"Последний объём {bars[-1]['volume'] / avg_vol:.1f}× к среднему.",
        "setup_quality": "fair" if missing else "good",
        "missing_data": missing,
    }


def risk(packet, inputs):
    flags = inputs.get("code_flags", [])
    rules = inputs.get("risk_rules", {})
    caps = inputs.get("caps", {})
    if any(f in rules.get("reject_if_any", []) for f in flags):
        status = "reject"
    elif any(f in rules.get("reduce_if_any", []) for f in flags):
        status = "reduce"
    else:
        status = "approve"
    return {
        "status": status,
        "maximum_simulated_size": caps.get("max_size_usd", 0),
        "maximum_simulated_loss": caps.get("max_loss_usd", 0),
        "risk_flags": flags,
        "reason": "Флаги: " + (", ".join(flags) if flags else "нет"),
    }


def decision(packet, inputs):
    risk_out = inputs.get("risk", {})
    charts_out = inputs.get("charts", {})
    sent = inputs.get("sentiment", {})
    conflicts = []
    if charts_out.get("trend") == "up" and sent.get("sentiment") in ("mixed", "negative"):
        conflicts.append("График вверх, настроение толпы смешанное")
    if risk_out.get("status") == "reduce" or conflicts:
        verdict = "WAIT"
    elif charts_out.get("trend") == "up" and sent.get("sentiment") == "positive":
        verdict = "BUY — SIMULATION ONLY"
    else:
        verdict = "SKIP"
    support = charts_out.get("support_levels") or []
    return {
        "decision": verdict,
        "reasons": [f"Риск: {risk_out.get('status')}", f"Тренд: {charts_out.get('trend')}"],
        "conflicting_signals": conflicts,
        "missing_information": charts_out.get("missing_data", []),
        "invalidation_conditions": [f"Закрытие ниже {support[0]}"] if support else [],
        "human_review_required": True,
    }


def pick(packet, inputs):
    """Most active market: biggest move times volume spike; NONE if nothing stands out."""
    best, best_score = None, 0.0
    for row in packet.get("watchlist", []):
        score = abs(row["change_pct"]) * row["volume_ratio"]
        if row["volume_ratio"] >= 1.2 and score > best_score:
            best, best_score = row, score
    if best is None:
        return {"market": "NONE", "reason_to_research": "Ничего не выделяется.", "liquidity_status": "unknown",
                "data_quality": "good", "sources": [packet.get("_label", "")], "confidence": 0}
    return {
        "market": best["symbol"],
        "reason_to_research": f"Движение {best['change_pct']:+.1f}% при объёме {best['volume_ratio']:.1f}× к среднему.",
        "liquidity_status": "high",
        "data_quality": "good",
        "sources": [packet.get("_label", "")],
        "confidence": 60,
    }


def trade_decision(packet, inputs):
    charts_out = inputs.get("charts", {})
    entry = packet["price_history"][-1]["close"]
    trend = charts_out.get("trend")
    if trend not in ("up", "down"):
        return {"decision": "WAIT", "stop_loss": 0, "take_profit": 0, "reasons": [f"Тренд: {trend}"],
                "conflicting_signals": [], "missing_information": [], "invalidation_conditions": []}
    lows = [b["low"] for b in packet["price_history"][-10:]]
    highs = [b["high"] for b in packet["price_history"][-10:]]
    if trend == "up":
        stop = min(min(lows), entry * 0.99)
        take = entry + 2 * (entry - stop)
    else:
        stop = max(max(highs), entry * 1.01)
        take = entry - 2 * (stop - entry)
    return {
        "decision": "BUY" if trend == "up" else "SELL",
        "stop_loss": round(stop, 6),
        "take_profit": round(take, 6),
        "reasons": [f"Тренд: {trend}", f"Риск: {inputs.get('risk', {}).get('status')}"],
        "conflicting_signals": [],
        "missing_information": [],
        "invalidation_conditions": [f"Цена за стопом {round(stop, 6)}"],
    }


ANSWERS = {f.__name__: f for f in (scout, news, sentiment, charts, risk, decision, pick, trade_decision)}


class MockProvider:
    def complete(self, bot, system, user, schema, context):
        return json.dumps(ANSWERS[bot](context["packet"], context["inputs"]), ensure_ascii=False)
