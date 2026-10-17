"""Bot 6 — Decision. Runs only after Risk approves or reduces."""
from .base import BotError, run_bot

DECISIONS = ["BUY — SIMULATION ONLY", "WAIT", "SKIP"]
_STR_LIST = {"type": "array", "items": {"type": "string"}}

SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": DECISIONS},
        "reasons": _STR_LIST,
        "conflicting_signals": _STR_LIST,
        "missing_information": _STR_LIST,
        "invalidation_conditions": _STR_LIST,
        "human_review_required": {"type": "boolean"},
    },
    "required": ["decision", "reasons", "conflicting_signals", "missing_information",
                 "invalidation_conditions", "human_review_required"],
    "additionalProperties": False,
}


class RiskRejected(BotError):
    """Raised when someone tries to run Decision after Risk said reject."""


def run(packet, outputs, provider, log=None):
    if outputs.get("risk", {}).get("status") not in ("approve", "reduce"):
        raise RiskRejected("Decision Bot cannot run: Risk Bot did not approve")
    result = run_bot("decision", SCHEMA, packet, provider, inputs=outputs, log=log)
    result["human_review_required"] = True  # never left to the model
    return result
