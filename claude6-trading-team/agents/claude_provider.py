"""Live bot calls through the official Anthropic SDK (Claude)."""
from .base import BotError, redact

FALLBACK_BETA = "server-side-fallback-2026-07-01"
# Server-side refusal fallback exists only for these models (not for Haiku).
FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}
WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search", "max_uses": 3}  # $10 per 1000 searches
MAX_CONTINUATIONS = 4


class ClaudeProvider:
    def __init__(self, model="claude-haiku-5-5", effort="medium", max_tokens=16000,
                 use_fallbacks=True, client=None, web_search_bots=(), models=None):
        if client is None:
            import anthropic  # imported here so the offline mock run needs no SDK
            client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment
        self.client = client
        self.model = model
        self.models = models or {}  # per-bot override, e.g. {"trade_decision": "claude-opus-5-5"}
        self.effort = effort
        self.max_tokens = max_tokens
        self.use_fallbacks = use_fallbacks
        self.web_search_bots = set(web_search_bots)

    def _create(self, **request):
        if self.use_fallbacks and request["model"] in FALLBACK_MODELS:
            # If a safety classifier declines, the API retries on a fallback model.
            return self.client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **request)
        return self.client.messages.create(**request)

    def complete(self, bot, system, user, schema, context):
        import anthropic

        messages = [{"role": "user", "content": user}]
        request = dict(
            model=self.models.get(bot, self.model),
            max_tokens=self.max_tokens,
            system=system,
            # Structured outputs: the API constrains the reply to this exact JSON shape.
            output_config={
                "effort": self.effort,
                "format": {"type": "json_schema", "schema": schema},
            },
        )
        if bot in self.web_search_bots:
            request["tools"] = [WEB_SEARCH_TOOL]  # runs on Anthropic's servers; no local tool code
        try:
            response = self._create(messages=messages, **request)
            for _ in range(MAX_CONTINUATIONS):
                if response.stop_reason != "pause_turn":
                    break
                messages = [messages[0], {"role": "assistant", "content": response.content}]
                response = self._create(messages=messages, **request)
        except anthropic.AuthenticationError:
            raise BotError("Claude rejected the API key (check ANTHROPIC_API_KEY in .env)")
        except anthropic.RateLimitError:
            raise BotError("Claude rate limit reached; try again later")
        except anthropic.APIStatusError as exc:
            raise BotError(redact(f"Claude API error {exc.status_code}: {exc.message}"))
        except anthropic.APIConnectionError:
            raise BotError("Cannot reach api.anthropic.com (network)")

        if response.stop_reason == "refusal":
            raise BotError(f"{bot} bot: Claude declined the request")
        if response.stop_reason in ("max_tokens", "pause_turn"):
            return ""  # truncated JSON -> treated as invalid -> retried once
        # With web search the answer follows the search results; keep only the final text.
        blocks = list(response.content)
        last_tool = max((i for i, b in enumerate(blocks) if b.type.endswith("tool_result")), default=-1)
        return "".join(b.text for b in blocks[last_tool + 1:] if b.type == "text")
