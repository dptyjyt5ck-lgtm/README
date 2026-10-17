"""Live bot calls through the official Anthropic SDK (Claude)."""
from .base import BotError, redact

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class ClaudeProvider:
    def __init__(self, model="claude-opus-5-5", effort="medium", max_tokens=16000,
                 use_fallbacks=True, client=None):
        if client is None:
            import anthropic  # imported here so the offline mock run needs no SDK
            client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment
        self.client = client
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens
        self.use_fallbacks = use_fallbacks

    def complete(self, bot, system, user, schema, context):
        import anthropic

        request = dict(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            # Structured outputs: the API constrains the reply to this exact JSON shape.
            output_config={
                "effort": self.effort,
                "format": {"type": "json_schema", "schema": schema},
            },
        )
        try:
            if self.use_fallbacks:
                # If a safety classifier declines, the API retries on a fallback model.
                response = self.client.beta.messages.create(
                    betas=[FALLBACK_BETA], fallbacks="default", **request
                )
            else:
                response = self.client.messages.create(**request)
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
        if response.stop_reason == "max_tokens":
            return ""  # truncated JSON -> treated as invalid -> retried once
        return "".join(b.text for b in response.content if b.type == "text")
