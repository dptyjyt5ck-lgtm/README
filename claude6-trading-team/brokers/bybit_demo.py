"""Bybit Demo Trading (api-demo.bybit.com) via the official pybit SDK. USDT perpetuals.

The client is always created with demo=True; there is no switch to the real account here.
"""
from .base import Venue, VenueError, floor_step
from .paper import _bar, top_by_turnover

LEVERAGE_NOT_MODIFIED = 110043


class BybitDemoVenue(Venue):
    name = "Bybit Demo"
    category = "linear"

    def __init__(self, api_key, api_secret, interval="60", http_class=None):
        if not api_key or not api_secret:
            raise VenueError("BYBIT_API_KEY and BYBIT_API_SECRET must be set in .env (demo-mode key)")
        if http_class is None:
            from pybit.unified_trading import HTTP as http_class
        self.session = http_class(demo=True, api_key=api_key, api_secret=api_secret)
        self.interval = interval
        self._instruments = {}

    def _call(self, method, ok_codes=(), **params):
        try:
            resp = getattr(self.session, method)(**params)
        except Exception as exc:  # pybit raises InvalidRequestError for non-zero retCode
            code = getattr(exc, "status_code", None)
            if code in ok_codes:
                return {}
            raise VenueError(f"Bybit {method}: {getattr(exc, 'message', type(exc).__name__)} (code {code})")
        if resp.get("retCode") != 0 and resp.get("retCode") not in ok_codes:
            raise VenueError(f"Bybit {method}: {resp.get('retMsg')}")
        return resp["result"]

    def is_demo(self):
        return True

    def candles(self, symbol, count, timeframe=None):
        rows = self._call("get_kline", category=self.category, symbol=symbol,
                          interval=timeframe or self.interval, limit=count)["list"]
        return [_bar(r) for r in reversed(rows)]

    def equity(self):
        return float(self._call("get_wallet_balance", accountType="UNIFIED")["list"][0]["totalEquity"])

    def universe(self, top_n, min_turnover_usd):
        rows = self._call("get_tickers", category=self.category)["list"]
        return top_by_turnover(rows, top_n, min_turnover_usd)

    def set_leverage(self, symbol, leverage):
        self._call("set_leverage", ok_codes=(LEVERAGE_NOT_MODIFIED,), category=self.category, symbol=symbol,
                   buyLeverage=str(leverage), sellLeverage=str(leverage))

    def closed_result(self, symbol, opened_ts):
        rows = self._call("get_closed_pnl", category=self.category, symbol=symbol,
                          startTime=int(opened_ts * 1000), limit=50)["list"]
        if not rows:
            return None
        return {"exit": float(rows[0]["avgExitPrice"]), "pnl": round(sum(float(r["closedPnl"]) for r in rows), 2)}

    def positions(self):
        rows = self._call("get_positions", category=self.category, settleCoin="USDT")["list"]
        return {r["symbol"]: {"side": "BUY" if r["side"] == "Buy" else "SELL", "qty": float(r["size"]),
                              "entry": float(r["avgPrice"])}
                for r in rows if float(r.get("size") or 0) > 0}

    def _instrument(self, symbol):
        if symbol not in self._instruments:
            info = self._call("get_instruments_info", category=self.category, symbol=symbol)["list"][0]
            self._instruments[symbol] = {
                "qty_step": float(info["lotSizeFilter"]["qtyStep"]),
                "min_qty": float(info["lotSizeFilter"]["minOrderQty"]),
                "tick": float(info["priceFilter"]["tickSize"]),
            }
        return self._instruments[symbol]

    def size(self, symbol, entry, stop, risk_usd, max_notional_usd):
        inst = self._instrument(symbol)
        qty = floor_step(min(risk_usd / abs(entry - stop), max_notional_usd / entry), inst["qty_step"])
        return qty if qty >= inst["min_qty"] else 0.0

    def _fmt(self, value, step):
        decimals = max(0, len(f"{step:.10f}".rstrip("0").split(".")[1]))
        return f"{round(round(value / step) * step, decimals):.{decimals}f}"

    def market_order(self, symbol, side, qty, stop, take):
        inst = self._instrument(symbol)
        result = self._call(
            "place_order", category=self.category, symbol=symbol,
            side="Buy" if side == "BUY" else "Sell", orderType="Market",
            qty=self._fmt(qty, inst["qty_step"]),
            stopLoss=self._fmt(stop, inst["tick"]), takeProfit=self._fmt(take, inst["tick"]),
            tpslMode="Full",
        )
        price = self.candles(symbol, 1)[-1]["close"]
        return {"ok": True, "id": result.get("orderId", ""), "price": price, "message": "sent to Bybit Demo"}
