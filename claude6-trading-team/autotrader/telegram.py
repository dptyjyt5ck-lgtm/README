"""Telegram notifications and the /stop /start /status commands. Falls back to console output."""
from agents.base import redact

API = "https://api.telegram.org/bot{token}/{method}"


class Notifier:
    def __init__(self, token=None, chat_id=None, log=None, http=None):
        self.token = token
        self.chat_id = str(chat_id) if chat_id else None
        self.log = log
        if http is None:
            import requests as http
        self.http = http

    @property
    def enabled(self):
        return bool(self.token and self.chat_id)

    def send(self, text):
        text = redact(text)
        print(text, flush=True)
        if not self.enabled:
            return
        try:
            self.http.post(API.format(token=self.token, method="sendMessage"),
                           json={"chat_id": self.chat_id, "text": text}, timeout=10)
        except Exception as exc:  # a failed alert must never break the cycle
            if self.log:
                self.log.warning("telegram send failed: %s", type(exc).__name__)

    def commands(self, state):
        """New commands from the configured chat only, e.g. ["/stop"]. Updates state["tg_offset"]."""
        if not self.enabled:
            return []
        try:
            resp = self.http.get(API.format(token=self.token, method="getUpdates"),
                                 params={"offset": state.get("tg_offset", 0) + 1, "timeout": 0}, timeout=10)
            updates = resp.json().get("result", [])
        except Exception as exc:
            if self.log:
                self.log.warning("telegram poll failed: %s", type(exc).__name__)
            return []
        found = []
        for update in updates:
            state["tg_offset"] = max(state.get("tg_offset", 0), update["update_id"])
            message = update.get("message") or {}
            if str(message.get("chat", {}).get("id")) != self.chat_id:
                continue  # ignore everyone except the owner
            text = (message.get("text") or "").strip().split("@")[0].lower()
            if text in ("/stop", "/start", "/status"):
                found.append(text)
        return found
