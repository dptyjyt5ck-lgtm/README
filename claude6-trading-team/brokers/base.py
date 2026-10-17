"""What every execution venue must provide. Only demo and paper venues exist in this project."""
import math


class VenueError(RuntimeError):
    pass


def floor_step(value, step):
    if step <= 0:
        return value
    return math.floor(value / step + 1e-9) * step


class Venue:
    name = "venue"

    def is_demo(self) -> bool:
        raise NotImplementedError

    def candles(self, symbol, count):
        """Oldest-first list of {date, open, high, low, close, volume}."""
        raise NotImplementedError

    def equity(self) -> float:
        raise NotImplementedError

    def positions(self) -> dict:
        """{symbol: {"side": "BUY"|"SELL", "qty": float, "entry": float}}"""
        raise NotImplementedError

    def size(self, symbol, entry, stop, risk_usd, max_notional_usd) -> float:
        """Quantity whose loss at the stop is <= risk_usd, rounded down to the venue's step."""
        raise NotImplementedError

    def market_order(self, symbol, side, qty, stop, take) -> dict:
        """Open a position with stop and target attached. Returns {"ok", "id", "price", "message"}."""
        raise NotImplementedError

    def sync(self):
        """Venue housekeeping; returns a list of closed-position events (may be empty)."""
        return []
