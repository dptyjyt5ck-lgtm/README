"""Bot 4 — Charts: trend, levels and volume from the numbers only."""
from .base import run_bot

_NUM_LIST = {"type": "array", "items": {"type": "number"}}

SCHEMA = {
    "type": "object",
    "properties": {
        "trend": {"type": "string", "enum": ["up", "down", "sideways", "unknown"]},
        "support_levels": _NUM_LIST,
        "resistance_levels": _NUM_LIST,
        "volume_summary": {"type": "string"},
        "setup_quality": {"type": "string", "enum": ["good", "fair", "poor", "unknown"]},
        "missing_data": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["trend", "support_levels", "resistance_levels", "volume_summary", "setup_quality", "missing_data"],
    "additionalProperties": False,
}


def run(packet, provider, log=None):
    return run_bot("charts", SCHEMA, packet, provider, log=log)
