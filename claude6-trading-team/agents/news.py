"""Bot 2 — News: separates reporting from unverified claims."""
from .base import run_bot

_STR_LIST = {"type": "array", "items": {"type": "string"}}

SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "positive_events": _STR_LIST,
        "negative_events": _STR_LIST,
        "unverified_claims": _STR_LIST,
        "sources": _STR_LIST,
        "last_updated": {"type": "string"},
    },
    "required": ["summary", "positive_events", "negative_events", "unverified_claims", "sources", "last_updated"],
    "additionalProperties": False,
}


def run(packet, provider, log=None):
    return run_bot("news", SCHEMA, packet, provider, log=log)
