"""MetaTrader 5 demo account via the official MetaTrader5 Python package (Windows only).

Refuses to run unless the connected account reports trade_mode == DEMO.
"""
import time
from datetime import datetime, timezone

from .base import Venue, VenueError, floor_step

MAGIC = 6060606  # marks positions opened by this program
STALE_TICK_SECONDS = 15 * 60  # no quote for 15 minutes -> market treated as closed


class MT5DemoVenue(Venue):
    name = "MT5 Demo"

    def __init__(self, login, password, server, timeframe="H1", max_lots=1.0, mt5_module=None, path=None):
        if mt5_module is None:
            try:
                import MetaTrader5 as mt5_module
            except ImportError:
                raise VenueError("pip install MetaTrader5 (works only on Windows next to a running MT5 terminal)")
        self.mt5 = mt5 = mt5_module
        if not login or not password or not server:
            raise VenueError("MT5_LOGIN, MT5_PASSWORD and MT5_SERVER must be set in .env")
        kwargs = {"login": int(login), "password": password, "server": server}
        if path:
            kwargs["path"] = path  # terminal64.exe, needed only if several terminals are installed
        if not mt5.initialize(**kwargs):
            raise VenueError(f"MT5 initialize failed: {mt5.last_error()}")
        info = mt5.account_info()
        if info is None or info.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO:
            mt5.shutdown()
            raise VenueError("Connected MT5 account is NOT a demo account — refusing to trade")
        self.timeframe = getattr(mt5, f"TIMEFRAME_{timeframe}")
        self.max_lots = max_lots

    def is_demo(self):
        return self.mt5.account_info().trade_mode == self.mt5.ACCOUNT_TRADE_MODE_DEMO

    def _symbol(self, symbol):
        if not self.mt5.symbol_select(symbol, True):
            raise VenueError(f"MT5 symbol {symbol} not available (check the broker's symbol name)")
        return self.mt5.symbol_info(symbol)

    def is_tradable(self, symbol):
        """Trading allowed for the symbol and quotes are fresh (catches weekends and holidays)."""
        try:
            info = self._symbol(symbol)
        except VenueError:
            return False
        tick = self.mt5.symbol_info_tick(symbol)
        if tick is None or info.trade_mode != self.mt5.SYMBOL_TRADE_MODE_FULL:
            return False
        return time.time() - tick.time < STALE_TICK_SECONDS

    def candles(self, symbol, count):
        self._symbol(symbol)
        rates = self.mt5.copy_rates_from_pos(symbol, self.timeframe, 0, count)
        if rates is None:
            raise VenueError(f"MT5 no candles for {symbol}: {self.mt5.last_error()}")
        return [{
            "date": datetime.fromtimestamp(int(r["time"]), timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "open": float(r["open"]), "high": float(r["high"]), "low": float(r["low"]),
            "close": float(r["close"]), "volume": float(r["tick_volume"]),
        } for r in rates]

    def equity(self):
        return float(self.mt5.account_info().equity)

    def positions(self):
        rows = self.mt5.positions_get() or []
        return {p.symbol: {"side": "BUY" if p.type == self.mt5.POSITION_TYPE_BUY else "SELL",
                           "qty": float(p.volume), "entry": float(p.price_open)}
                for p in rows if p.magic == MAGIC}

    def closed_result(self, symbol, opened_ts):
        mt5 = self.mt5
        deals = mt5.history_deals_get(datetime.fromtimestamp(opened_ts, timezone.utc), datetime.now(timezone.utc),
                                      group=symbol) or []
        mine = [d for d in deals if d.magic == MAGIC]
        exits = [d for d in mine if d.entry == mt5.DEAL_ENTRY_OUT]
        if not exits:
            return None
        pnl = sum(d.profit + d.commission + d.swap for d in mine)
        return {"exit": float(exits[-1].price), "pnl": round(pnl, 2)}

    def size(self, symbol, entry, stop, risk_usd, max_notional_usd):
        info = self._symbol(symbol)
        loss_per_lot = abs(entry - stop) / info.trade_tick_size * info.trade_tick_value
        lots = floor_step(min(risk_usd / loss_per_lot, self.max_lots), info.volume_step)
        return round(lots, 2) if lots >= info.volume_min else 0.0

    def market_order(self, symbol, side, qty, stop, take):
        mt5 = self.mt5
        info = self._symbol(symbol)
        tick = mt5.symbol_info_tick(symbol)
        buy = side == "BUY"
        filling = mt5.ORDER_FILLING_FOK if info.filling_mode & 1 else (
            mt5.ORDER_FILLING_IOC if info.filling_mode & 2 else mt5.ORDER_FILLING_RETURN)
        request = {
            "action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": float(qty),
            "type": mt5.ORDER_TYPE_BUY if buy else mt5.ORDER_TYPE_SELL,
            "price": tick.ask if buy else tick.bid,
            "sl": round(stop, info.digits), "tp": round(take, info.digits),
            "deviation": 20, "magic": MAGIC, "comment": "claude6 demo",
            "type_time": mt5.ORDER_TIME_GTC, "type_filling": filling,
        }
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            raise VenueError(f"MT5 order failed: {getattr(result, 'comment', mt5.last_error())}")
        return {"ok": True, "id": str(result.order), "price": float(result.price), "message": "sent to MT5 Demo"}
