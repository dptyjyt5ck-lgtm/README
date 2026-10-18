"""Paper venue: real public candles (or injected ones), fills simulated locally. No account needed."""
import json
from datetime import datetime, timezone
from pathlib import Path

from .base import Venue, floor_step

BYBIT_PUBLIC = "https://api.bybit.com/v5/market/kline"
BYBIT_TICKERS = "https://api.bybit.com/v5/market/tickers"


def top_by_turnover(rows, top_n, min_turnover_usd):
    """USDT perpetuals sorted by 24h turnover, filtered by a minimum."""
    rows = [r for r in rows if r["symbol"].endswith("USDT") and float(r.get("turnover24h") or 0) >= min_turnover_usd]
    rows.sort(key=lambda r: float(r["turnover24h"]), reverse=True)
    return [r["symbol"] for r in rows[:top_n]]


def bybit_public_candles(symbol, count, interval="60"):
    import requests

    resp = requests.get(BYBIT_PUBLIC, params={"category": "linear", "symbol": symbol,
                                              "interval": interval, "limit": count}, timeout=15)
    resp.raise_for_status()
    rows = resp.json()["result"]["list"]
    return [_bar(r) for r in reversed(rows)]


def _bar(r):
    return {
        "date": datetime.fromtimestamp(int(r[0]) / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "open": float(r[1]), "high": float(r[2]), "low": float(r[3]),
        "close": float(r[4]), "volume": float(r[5]),
    }


class PaperVenue(Venue):
    name = "Paper (simulated)"

    def __init__(self, state_path, starting_equity=10000.0, candle_source=None, interval="60", ticker_source=None):
        self.state_path = Path(state_path)
        self.interval = interval
        self.candle_source = candle_source or (lambda s, n, tf=None: bybit_public_candles(s, n, tf or interval))
        self.ticker_source = ticker_source
        if self.state_path.exists():
            self.state = json.loads(self.state_path.read_text(encoding="utf-8"))
        else:
            self.state = {"equity": starting_equity, "positions": {}, "next_id": 1}

    def _save(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self.state, indent=2), encoding="utf-8")

    def is_demo(self):
        return True

    def candles(self, symbol, count, timeframe=None):
        if timeframe is None or timeframe == self.interval:
            return self.candle_source(symbol, count)
        return self.candle_source(symbol, count, timeframe)

    def equity(self):
        return self.state["equity"]

    def universe(self, top_n, min_turnover_usd):
        if self.ticker_source:
            rows = self.ticker_source()
        else:
            import requests

            resp = requests.get(BYBIT_TICKERS, params={"category": "linear"}, timeout=15)
            resp.raise_for_status()
            rows = resp.json()["result"]["list"]
        return top_by_turnover(rows, top_n, min_turnover_usd)

    def positions(self):
        return {s: {k: p[k] for k in ("side", "qty", "entry")} for s, p in self.state["positions"].items()}

    def size(self, symbol, entry, stop, risk_usd, max_notional_usd):
        qty = min(risk_usd / abs(entry - stop), max_notional_usd / entry)
        return floor_step(qty, 0.001)

    def market_order(self, symbol, side, qty, stop, take):
        entry = self.candles(symbol, 1)[-1]["close"]
        order_id = f"paper-{self.state['next_id']}"
        self.state["next_id"] += 1
        self.state["positions"][symbol] = {
            "id": order_id, "side": side, "qty": qty, "entry": entry, "stop": stop, "take": take,
            "opened": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        }
        self._save()
        return {"ok": True, "id": order_id, "price": entry, "message": "filled (paper)"}

    def sync(self):
        """Close paper positions whose stop or target was touched by a later candle (stop checked first)."""
        closed = []
        for symbol, pos in list(self.state["positions"].items()):
            for bar in self.candles(symbol, 200):
                if bar["date"] <= pos["opened"]:
                    continue
                buy = pos["side"] == "BUY"
                hit_stop = bar["low"] <= pos["stop"] if buy else bar["high"] >= pos["stop"]
                hit_take = bar["high"] >= pos["take"] if buy else bar["low"] <= pos["take"]
                if hit_stop or hit_take:
                    exit_price = pos["stop"] if hit_stop else pos["take"]
                    pnl = (exit_price - pos["entry"]) * pos["qty"] * (1 if buy else -1)
                    self.state["equity"] += pnl
                    del self.state["positions"][symbol]
                    closed.append({"symbol": symbol, "side": pos["side"], "exit": exit_price,
                                   "pnl": round(pnl, 2), "reason": "stop" if hit_stop else "target"})
                    break
        if closed:
            self._save()
        return closed
