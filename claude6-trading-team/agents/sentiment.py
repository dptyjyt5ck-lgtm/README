"""Bot 3 — Sentiment: crowd mood and hype detection."""
from .base import run_bot

_STR_LIST = {"type": "array", "items": {"type": "string"}}

SCHEMA = {
    "type": "object",
    "properties": {
        "sentiment": {"type": "string", "enum": ["positive", "negative", "mixed", "neutral", "unknown"]},
        "score": {"type": "integer"},
        "main_reasons": _STR_LIST,
        "possible_hype": _STR_LIST,
        "sources": _STR_LIST,
    },
    "required": ["sentiment", "score", "main_reasons", "possible_hype", "sources"],
    "additionalProperties": False,
}


def run(packet, provider, log=None):
    return run_bot("sentiment", SCHEMA, packet, provider, log=log)


def run_live(packet, provider, log=None):
    """Same output shape; the prompt tells Claude to search the web for crowd mood."""
    return run_bot("sentiment", SCHEMA, packet, provider, log=log, prompt="sentiment_live")
