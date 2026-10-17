"""Decision in autonomous mode: BUY / SELL / WAIT / SKIP with a stop and a target.

Size is never chosen here; code computes it from the Risk output and the stop distance.
Leverage is proposed by the bot and clamped by code (cap and liquidation distance).
"""
import math
from .base import BotError, run_bot

TRADES = ["BUY", "SELL"]
_STR_LIST = {"type": "array", "items": {"type": "string"}}

SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": TRADES + ["WAIT", "SKIP"]},
        "stop_loss": {"type": "number"},
        "take_profit": {"type": "number"},
        "leverage": {"type": "integer"},
        "reasons": _STR_LIST,
        "conflicting_signals": _STR_LIST,
        "missing_information": _STR_LIST,
        "invalidation_conditions": _STR_LIST,
    },
    "required": ["decision", "stop_loss", "take_profit", "leverage", "reasons", "conflicting_signals",
                 "missing_information", "invalidation_conditions"],
    "additionalProperties": False,
}


class RiskRejected(BotError):
    """Raised when someone tries to decide after Risk said reject."""


def run(packet, outputs, provider, log=None):
    if outputs.get("risk", {}).get("status") not in ("approve", "reduce"):
        raise RiskRejected("Trade Decision cannot run: Risk Bot did not approve")
    return run_bot("trade_decision", SCHEMA, packet, provider, inputs=outputs, log=log, prompt="trade_decision")


def check_plan(decision, entry, rules):
    """Return a list of problems with the stop/target; empty means the plan is usable."""
    side, stop, take = decision["decision"], decision["stop_loss"], decision["take_profit"]
    if side not in TRADES:
        return ["not a trade"]
    problems = []
    if side == "BUY" and not stop < entry < take:
        problems.append("BUY needs stop < price < target")
    if side == "SELL" and not take < entry < stop:
        problems.append("SELL needs target < price < stop")
    if problems:
        return problems
    stop_pct = abs(entry - stop) / entry * 100
    if not rules["min_stop_pct"] <= stop_pct <= rules["max_stop_pct"]:
        problems.append(f"stop distance {stop_pct:.2f}% outside {rules['min_stop_pct']}–{rules['max_stop_pct']}%")
    reward_risk = abs(take - entry) / abs(entry - stop)
    if reward_risk < rules["min_reward_risk"]:
        problems.append(f"reward/risk {reward_risk:.2f} below {rules['min_reward_risk']}")
    return problems


def safe_leverage(decision, entry, rules):
    """Bot's leverage, but never above the cap and never so high that liquidation comes before the stop.

    Liquidation sits roughly 1/leverage away from entry; keep the stop inside 80% of that distance.
    """
    stop_fraction = abs(entry - decision["stop_loss"]) / entry
    by_stop = math.floor(rules["liquidation_buffer"] / stop_fraction) if stop_fraction > 0 else 1
    return max(1, min(decision["leverage"], rules["max_leverage"], by_stop))
