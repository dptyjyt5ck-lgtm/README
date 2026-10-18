"""Scout in autonomous mode: ranks up to a few markets from the allowed watchlist (empty list = nothing)."""
import copy

from . import scout
from .base import run_bot


def schema_for(symbols):
    schema = copy.deepcopy(scout.SCHEMA)
    del schema["properties"]["market"]
    schema["properties"]["markets"] = {"type": "array", "items": {"type": "string", "enum": list(symbols)}}
    schema["required"] = ["markets" if k == "market" else k for k in schema["required"]]
    return schema


def run(watchlist_packet, provider, log=None):
    symbols = [row["symbol"] for row in watchlist_packet["watchlist"]]
    return run_bot("pick", schema_for(symbols), watchlist_packet, provider, log=log, prompt="scout_pick")


def scout_view(pick, symbol):
    """The pick reshaped into the regular Scout output for one market, so Risk can read it."""
    return {"market": symbol, **{k: v for k, v in pick.items() if k != "markets"}}
