"""Autonomous 24/7 mode: the six bots pick markets and open trades on a DEMO or paper account.

There is no real-money mode in this project. TRADING_MODE must be SIMULATION_ONLY (paper only)
or DEMO (paper, Bybit Demo, MT5 Demo).
"""
import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

from agents.base import redact
from agents.mock_provider import MockProvider
from autotrader.engine import Engine
from autotrader.telegram import Notifier

ROOT = Path(__file__).resolve().parent
ALLOWED = {"SIMULATION_ONLY": {"PAPER"}, "DEMO": {"PAPER", "BYBIT_DEMO", "MT5_DEMO"}}
MAX_CONSECUTIVE_ERRORS = 5


def load_config(path=None):
    path = Path(path) if path else ROOT / "autotrade.json"
    if not path.exists():
        path = ROOT / "autotrade.example.json"
    return json.loads(path.read_text(encoding="utf-8"))


def make_provider(config):
    name = os.environ.get("MODEL_PROVIDER", "MOCK").upper()
    if name == "MOCK":
        return MockProvider()
    if name != "CLAUDE":
        raise SystemExit(f"Unknown MODEL_PROVIDER={name!r} (use MOCK or CLAUDE)")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("MODEL_PROVIDER=CLAUDE needs ANTHROPIC_API_KEY in .env")
    from agents.claude_provider import ClaudeProvider
    return ClaudeProvider(model=config["model"], models=config.get("models"), effort=config["effort"],
                          max_tokens=config["max_output_tokens"], use_fallbacks=config["use_refusal_fallbacks"],
                          web_search_bots=("news", "sentiment"))


def make_venue(config):
    """Returns (venue, venue-specific settings)."""
    kind = config["venue"]
    if kind == "PAPER":
        from brokers.paper import PaperVenue
        settings = config["paper"]
        venue = PaperVenue(ROOT / config["state_dir"] / "paper.json", settings["starting_equity"],
                           interval=settings["interval"])
        return venue, settings, settings["interval"]
    if kind == "BYBIT_DEMO":
        from brokers.bybit_demo import BybitDemoVenue
        settings = config["bybit"]
        venue = BybitDemoVenue(os.environ.get("BYBIT_API_KEY"), os.environ.get("BYBIT_API_SECRET"),
                               interval=settings["interval"])
        return venue, settings, settings["interval"]
    if kind == "MT5_DEMO":
        from brokers.mt5_demo import MT5DemoVenue
        settings = config["mt5"]
        venue = MT5DemoVenue(os.environ.get("MT5_LOGIN"), os.environ.get("MT5_PASSWORD"),
                             os.environ.get("MT5_SERVER"), timeframe=settings["timeframe"],
                             max_lots=settings["max_lots"], path=os.environ.get("MT5_PATH") or None)
        return venue, settings, settings["timeframe"]
    raise SystemExit(f"Unknown venue {kind!r} (use PAPER, BYBIT_DEMO or MT5_DEMO)")


def build_engine(config, venue, settings, timeframe, provider, notifier, log):
    from autotrader.engine import TF_LABELS
    rules = {**config["rules"], **settings.get("rules", {})}  # venue-specific overrides (e.g. forex stops)
    engine_config = {"watchlist": settings["watchlist"], "universe": settings.get("universe"),
                     "candles": config["candles"], "context_timeframes": settings.get("context_timeframes", []),
                     "context_candles": config.get("context_candles", 60),
                     "markets_per_cycle": config.get("markets_per_cycle", 1),
                     "timeframe_label": TF_LABELS.get(timeframe, timeframe), "state_dir": config["state_dir"]}
    return Engine(venue, provider, notifier, engine_config, rules, ROOT, log)


def setup_log(config):
    logs = ROOT / config["logs_dir"]
    logs.mkdir(exist_ok=True)
    log = logging.getLogger("autotrade")
    log.setLevel(logging.INFO)
    handler = logging.FileHandler(logs / "autotrade.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(handler)
    return log


def check_mode(venue_kind):
    mode = os.environ.get("TRADING_MODE", "")
    if venue_kind not in ALLOWED.get(mode, set()):
        print(f"Refusing to start: venue {venue_kind} is not allowed with TRADING_MODE={mode or '(unset)'}. "
              "Use SIMULATION_ONLY for PAPER, DEMO for BYBIT_DEMO / MT5_DEMO.", file=sys.stderr)
        return False
    return True


def sleep_with_commands(engine, seconds):
    """Sleep, but keep answering /stop /start /status every 20 seconds."""
    end = time.time() + seconds
    while time.time() < end:
        engine.handle_commands()
        time.sleep(min(20, max(0, end - time.time())))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config")
    parser.add_argument("--once", action="store_true", help="run one cycle and exit")
    args = parser.parse_args(argv)
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass

    config = load_config(args.config)
    if not check_mode(config["venue"]):
        return 2
    log = setup_log(config)
    notifier = Notifier(os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID"), log=log)
    provider = make_provider(config)
    venue, settings, timeframe = make_venue(config)
    if not venue.is_demo():
        print("Refusing to start: venue is not a demo account", file=sys.stderr)
        return 2
    engine = build_engine(config, venue, settings, timeframe, provider, notifier, log)

    markets = (f"топ-{settings['universe']['top_n']} монет по обороту" if settings.get("universe")
               else f"рынков {len(settings['watchlist'])}")
    notifier.send(f"🤖 Команда ботов запущена: {venue.name}, {markets}, риск {config['rules']['risk_pct_per_trade']}% "
                  f"на сделку, "
                  f"проверка каждые {config['interval_minutes']} мин. Команды: /status /stop /start")
    errors = 0
    while True:
        try:
            result = engine.run_cycle()
            errors = 0
            log.info("cycle -> %s", result["status"])
            print(f"cycle: {result['status']} {result.get('symbol', '')}", flush=True)
        except Exception as exc:
            errors += 1
            message = redact(f"{type(exc).__name__}: {exc}")
            log.error("cycle failed: %s", message)
            notifier.send(f"⚠️ Ошибка цикла ({errors}/{MAX_CONSECUTIVE_ERRORS}): {message}")
            if errors >= MAX_CONSECUTIVE_ERRORS:
                engine.state["paused"] = True
                engine.save()
                notifier.send("⏸ Слишком много ошибок подряд — торговля на паузе. Проверьте и отправьте /start.")
        if args.once:
            return 0
        sleep_with_commands(engine, config["interval_minutes"] * 60)


if __name__ == "__main__":
    sys.exit(main())
