"""Scout in autonomous mode: picks one market from the allowed watchlist, or NONE."""
import copy

from . import scout
from .base import run_bot

NONE = "NONE"


def schema_for(symbols):
    schema = copy.deepcopy(scout.SCHEMA)
    schema["properties"]["market"] = {"type": "string", "enum": list(symbols) + [NONE]}
    return schema


def run(watchlist_packet, provider, log=None):
    symbols = [row["symbol"] for row in watchlist_packet["watchlist"]]
    return run_bot("pick", schema_for(symbols), watchlist_packet, provider, log=log, prompt="scout_pick")
