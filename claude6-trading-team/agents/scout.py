"""Bot 1 — Scout: is this market worth researching at all?"""
from .base import run_bot

SCHEMA = {
    "type": "object",
    "properties": {
        "market": {"type": "string"},
        "reason_to_research": {"type": "string"},
        "liquidity_status": {"type": "string", "enum": ["high", "medium", "low", "unknown"]},
        "data_quality": {"type": "string", "enum": ["good", "partial", "poor"]},
        "sources": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "integer"},
    },
    "required": ["market", "reason_to_research", "liquidity_status", "data_quality", "sources", "confidence"],
    "additionalProperties": False,
}


def run(packet, provider, log=None):
    return run_bot("scout", SCHEMA, packet, provider, log=log)
