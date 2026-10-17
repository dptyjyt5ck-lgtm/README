import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import autotrade  # noqa: E402
from agents import trade_decision  # noqa: E402
from agents.mock_provider import MockProvider  # noqa: E402
from autotrader.engine import Engine  # noqa: E402
from autotrader.telegram import Notifier  # noqa: E402
from brokers.base import VenueError  # noqa: E402
from brokers.bybit_demo import BybitDemoVenue  # noqa: E402
from brokers.mt5_demo import MT5DemoVenue  # noqa: E402
from brokers.paper import PaperVenue, top_by_turnover  # noqa: E402

CONFIG = json.loads((ROOT / "autotrade.example.json").read_text(encoding="utf-8"))
RULES = CONFIG["rules"]
LOG = logging.getLogger("test-autotrade")


def make_bars(start_price, step_pct, n=120, last_volume_mult=1.0, start=datetime(2026, 10, 1)):
    bars, price = [], start_price
    for i in range(n):
        o = price
        c = o * (1 + step_pct / 100)
        bars.append({"date": (start + timedelta(hours=i)).strftime("%Y-%m-%d %H:%M"), "open": o,
                     "high": max(o, c) * 1.002, "low": min(o, c) * 0.998, "close": c, "volume": 1000.0})
        price = c
    bars[-1]["volume"] *= last_volume_mult
    return bars


MARKET = {
    "BTCUSDT": make_bars(30000, 0.15, last_volume_mult=3.0),  # trending up, volume spike
    "ETHUSDT": make_bars(2000, 0.0),
    "SOLUSDT": make_bars(150, 0.0),
}


class FakeNotifier:
    def __init__(self, commands=None):
        self.sent, self.pending = [], list(commands or [])

    def send(self, text):
        self.sent.append(text)

    def commands(self, state):
        found, self.pending = self.pending, []
        return found


def engine(tmp_path, notifier=None, provider=None, market=MARKET, equity=10000.0):
    venue = PaperVenue(tmp_path / "state" / "paper.json", equity, candle_source=lambda s, n: market[s][-n:])
    config = {"watchlist": list(market), "candles": 120, "timeframe_label": "60m", "state_dir": "state"}
    return Engine(venue, provider or MockProvider(), notifier or FakeNotifier(), config, RULES, tmp_path, LOG)


def test_cycle_opens_trade_and_sends_telegram(tmp_path):
    eng = engine(tmp_path)
    result = eng.run_cycle()
    assert result["status"] == "opened" and result["symbol"] == "BTCUSDT"
    message = eng.notifier.sent[-1]
    assert "ВХОД" in message and "BUY BTCUSDT" in message and "Стоп" in message
    dec = result["outputs"]["decision"]
    loss_at_stop = result["qty"] * abs(result["order"]["price"] - dec["stop_loss"])
    assert loss_at_stop <= 10000 * RULES["risk_pct_per_trade"] / 100 + 1e-6
    assert (tmp_path / "state" / "trades.csv").exists()


def test_no_second_position_in_same_market(tmp_path):
    eng = engine(tmp_path)
    eng.run_cycle()
    assert eng.run_cycle()["status"] == "no_pick"  # BTC excluded, the rest is flat
    assert len(eng.venue.positions()) == 1


def test_stop_file_pauses(tmp_path):
    (tmp_path / "STOP").write_text("")
    assert engine(tmp_path).run_cycle()["status"] == "paused"


def test_telegram_stop_and_start(tmp_path):
    eng = engine(tmp_path, notifier=FakeNotifier(["/stop"]))
    assert eng.run_cycle()["status"] == "paused"
    eng.notifier.pending = ["/start"]
    assert eng.run_cycle()["status"] == "opened"


def test_daily_loss_limit_stops_and_alerts_once(tmp_path):
    eng = engine(tmp_path)
    eng.state.update(day=datetime.now(timezone.utc).strftime("%Y-%m-%d"), day_start_equity=12000)  # -16.7% today
    assert eng.run_cycle()["status"] == "daily_stop"
    assert eng.run_cycle()["status"] == "daily_stop"
    assert sum("Дневной лимит" in m for m in eng.notifier.sent) == 1


def test_max_open_positions(tmp_path):
    eng = engine(tmp_path)
    for i, symbol in enumerate(["X1", "X2", "X3"]):
        eng.venue.state["positions"][symbol] = {"id": str(i), "side": "BUY", "qty": 1, "entry": 1,
                                                "stop": 0.5, "take": 2, "opened": "2099-01-01 00:00"}
    eng.venue.candle_source = lambda s, n: MARKET.get(s, MARKET["ETHUSDT"])[-n:]
    assert eng.run_cycle()["status"] == "max_positions"


def test_model_cannot_raise_size(tmp_path):
    class Greedy(MockProvider):
        def complete(self, bot, system, user, schema, context):
            data = json.loads(super().complete(bot, system, user, schema, context))
            if bot == "risk":
                data.update(status="approve", maximum_simulated_size=1e9, maximum_simulated_loss=1e9)
            return json.dumps(data)

    result = engine(tmp_path, provider=Greedy()).run_cycle()
    cap = 10000 * RULES["risk_pct_per_trade"] / 100
    assert result["outputs"]["risk"]["maximum_simulated_loss"] == cap
    stop = result["outputs"]["decision"]["stop_loss"]
    assert result["qty"] * abs(result["order"]["price"] - stop) <= cap + 1e-6


def test_check_plan_rejects_bad_stops():
    base = {"decision": "BUY", "stop_loss": 99, "take_profit": 103}
    assert trade_decision.check_plan(base, 100, RULES) == []
    assert trade_decision.check_plan({**base, "stop_loss": 101}, 100, RULES)  # stop above entry
    assert trade_decision.check_plan({**base, "take_profit": 100.5}, 100, RULES)  # reward/risk < 1.5
    assert trade_decision.check_plan({**base, "stop_loss": 80, "take_profit": 150}, 100, RULES)  # 20% stop
    assert trade_decision.check_plan({"decision": "SELL", "stop_loss": 101, "take_profit": 97}, 100, RULES) == []


def test_paper_closes_at_stop_and_reports_exit(tmp_path):
    later = make_bars(30000, -0.5, n=5, start=datetime(2099, 1, 1))
    eng = engine(tmp_path)
    eng.venue.state["positions"]["BTCUSDT"] = {"id": "p", "side": "BUY", "qty": 0.01, "entry": 30000,
                                               "stop": 29800, "take": 30600, "opened": "2098-12-31 23:00"}
    eng.state["open_symbols"] = ["BTCUSDT"]
    eng.venue.candle_source = lambda s, n: (later if s == "BTCUSDT" else MARKET[s])[-n:]
    eng.run_cycle()
    exits = [m for m in eng.notifier.sent if "ВЫХОД" in m]
    assert len(exits) == 1 and "стоп" in exits[0]
    assert eng.venue.equity() == pytest.approx(10000 - 2.0)


def test_mode_guard(tmp_path, monkeypatch):
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: None)
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({**CONFIG, "venue": "BYBIT_DEMO"}))
    monkeypatch.setenv("TRADING_MODE", "SIMULATION_ONLY")
    assert autotrade.main(["--config", str(cfg), "--once"]) == 2
    monkeypatch.setenv("TRADING_MODE", "LIVE")
    assert autotrade.main(["--config", str(cfg), "--once"]) == 2


def test_mt5_refuses_real_account():
    mt5 = SimpleNamespace(ACCOUNT_TRADE_MODE_DEMO=0, ACCOUNT_TRADE_MODE_REAL=2,
                          initialize=lambda **k: True, shutdown=lambda: None,
                          account_info=lambda: SimpleNamespace(trade_mode=2), last_error=lambda: "")
    with pytest.raises(VenueError, match="NOT a demo"):
        MT5DemoVenue("1", "pw", "Server", mt5_module=mt5)


def test_bybit_is_always_demo_and_rounds_qty():
    created = {}

    class FakeHTTP:
        def __init__(self, **kwargs):
            created.update(kwargs)

        def get_instruments_info(self, **k):
            return {"retCode": 0, "result": {"list": [{"lotSizeFilter": {"qtyStep": "0.001", "minOrderQty": "0.001"},
                                                       "priceFilter": {"tickSize": "0.1"}}]}}

    venue = BybitDemoVenue("key", "secret", http_class=FakeHTTP)
    assert created["demo"] is True
    assert venue.size("BTCUSDT", 30000, 29700, 50, 10000) == pytest.approx(0.166)
    assert venue.size("BTCUSDT", 30000, 29700, 0.01, 10000) == 0.0  # below minimum -> no trade


def test_telegram_ignores_other_chats_and_redacts(monkeypatch):
    fake_key = "sk-ant-api03-FAKEKEYFAKEKEY123456"
    posted = []

    class HTTP:
        def post(self, url, json, timeout):
            posted.append(json["text"])

        def get(self, url, params, timeout):
            return SimpleNamespace(json=lambda: {"result": [
                {"update_id": 5, "message": {"chat": {"id": 999}, "text": "/stop"}},
                {"update_id": 6, "message": {"chat": {"id": 42}, "text": "/status"}},
            ]})

    notifier = Notifier("token", 42, http=HTTP())
    state = {}
    assert notifier.commands(state) == ["/status"]
    assert state["tg_offset"] == 6
    notifier.send(f"leak {fake_key}")
    assert fake_key not in posted[0]


def test_leverage_is_clamped_by_cap_and_liquidation():
    dec = {"decision": "BUY", "stop_loss": 98, "take_profit": 106, "leverage": 50}
    assert trade_decision.safe_leverage(dec, 100, RULES) == RULES["max_leverage"]
    wide = {**dec, "stop_loss": 80}  # 20% stop -> liquidation at x5 would hit first
    assert trade_decision.safe_leverage(wide, 100, {**RULES, "max_leverage": 50}) == 4
    assert trade_decision.safe_leverage({**dec, "leverage": 0}, 100, RULES) == 1


def test_trade_uses_bot_leverage_and_message_shows_it(tmp_path):
    eng = engine(tmp_path)
    calls = []
    eng.venue.set_leverage = lambda symbol, lev: calls.append((symbol, lev))
    result = eng.run_cycle()
    assert result["leverage"] == 5 and calls == [("BTCUSDT", 5)]
    assert "Плечо: x5" in eng.notifier.sent[-1]
    margin = result["qty"] * result["order"]["price"] / result["leverage"]
    assert margin <= 10000 * 0.9 / RULES["max_open_positions"] + 1e-6


def test_universe_picks_most_traded_usdt_coins(tmp_path):
    rows = [{"symbol": "BTCUSDT", "turnover24h": "9e9"}, {"symbol": "ETHUSDT", "turnover24h": "5e9"},
            {"symbol": "TINYUSDT", "turnover24h": "1e6"}, {"symbol": "BTCPERP", "turnover24h": "8e9"},
            {"symbol": "SOLUSDT", "turnover24h": "2e9"}]
    assert top_by_turnover(rows, 2, 5e7) == ["BTCUSDT", "ETHUSDT"]

    eng = engine(tmp_path)
    eng.config["universe"] = {"top_n": 2, "min_turnover_24h_usd": 5e7}
    eng.venue.ticker_source = lambda: rows
    seen = []
    source = eng.venue.candle_source
    eng.venue.candle_source = lambda s, n: seen.append(s) or source(s, n)
    eng.run_cycle()
    assert set(seen) <= {"BTCUSDT", "ETHUSDT"}


def test_bybit_leverage_not_modified_is_ok():
    class Err(Exception):
        status_code = 110043
        message = "leverage not modified"

    class FakeHTTP:
        def __init__(self, **kwargs):
            pass

        def set_leverage(self, **k):
            raise Err()

    BybitDemoVenue("key", "secret", http_class=FakeHTTP).set_leverage("BTCUSDT", 5)
