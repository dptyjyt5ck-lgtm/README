"""Bot 7 — Reviewer: after a trade closes, compares what the team said with what happened.

Its lessons are fed back to Risk and Decision as data. They can never change the code limits.
"""
from .base import run_bot

_STR_LIST = {"type": "array", "items": {"type": "string"}}

SCHEMA = {
    "type": "object",
    "properties": {
        "outcome": {"type": "string", "enum": ["win", "loss", "breakeven", "unknown"]},
        "what_went_right": _STR_LIST,
        "what_went_wrong": _STR_LIST,
        "lesson": {"type": "string"},
        "tags": _STR_LIST,
    },
    "required": ["outcome", "what_went_right", "what_went_wrong", "lesson", "tags"],
    "additionalProperties": False,
}


def run(trade, provider, log=None):
    return run_bot("reviewer", SCHEMA, trade, provider, log=log)
