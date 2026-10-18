"""One cycle of the autonomous team: look at the markets, maybe open one trade, report."""
import csv
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from agents import charts, news, picker, reviewer, risk, sentiment, trade_decision

JOURNAL_FIELDS = ["time", "venue", "symbol", "side", "qty", "leverage", "entry", "stop", "take", "risk_usd",
                  "risk_status", "order_id", "reasons"]


def summarize(symbol, bars):
    """Numbers computed in code for the Scout's watchlist overview."""
    closes = [b["close"] for b in bars]
    ranges = [b["high"] - b["low"] for b in bars[-14:]]
    avg_vol = sum(b["volume"] for b in bars[:-1]) / max(1, len(bars) - 1)
    sma20 = sum(closes[-20:]) / 20
    sma50 = sum(closes[-50:]) / min(50, len(closes))
    return {
        "symbol": symbol,
        "last_price": closes[-1],
        "change_pct": round((closes[-1] / closes[-25] - 1) * 100, 2) if len(closes) > 25 else 0.0,
        "volume_ratio": round(bars[-1]["volume"] / avg_vol, 2) if avg_vol else 0.0,
        "atr_pct": round(sum(ranges) / len(ranges) / closes[-1] * 100, 2),
        "trend_sma20_vs_sma50": "up" if sma20 > sma50 else "down",
    }


class Engine:
    def __init__(self, venue, provider, notifier, config, rules, root, log):
        self.venue = venue
        self.provider = provider
        self.notifier = notifier
        self.config = config
        self.rules = rules
        self.root = Path(root)
        self.log = log
        self.state_dir = self.root / config["state_dir"]
        self.state_path = self.state_dir / "state.json"
        self.state = json.loads(self.state_path.read_text(encoding="utf-8")) if self.state_path.exists() else {}

    # ---- state and commands ----------------------------------------------
    def save(self):
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self.state, indent=2), encoding="utf-8")

    def stopped(self):
        return (self.root / "STOP").exists() or self.state.get("paused", False)

    def handle_commands(self):
        for cmd in self.notifier.commands(self.state):
            if cmd == "/stop":
                self.state["paused"] = True
                self.notifier.send("⏸ Торговля на паузе. Новые сделки не открываются. /start — продолжить.")
            elif cmd == "/start":
                self.state["paused"] = False
                self.notifier.send("▶️ Торговля возобновлена.")
            elif cmd == "/status":
                self.notifier.send(self.status_text())
        self.save()

    def status_text(self):
        try:
            equity, positions = self.venue.equity(), self.venue.positions()
        except Exception as exc:
            return f"Статус недоступен: {type(exc).__name__}"
        lines = [f"📊 {self.venue.name}: equity {equity:,.2f}",
                 f"Пауза: {'да' if self.stopped() else 'нет'}"]
        lines += [f"• {s} {p['side']} {p['qty']} @ {p['entry']}" for s, p in positions.items()]
        if not positions:
            lines.append("Открытых позиций нет")
        return "\n".join(lines)

    # ---- learning from closed trades --------------------------------------
    def lessons_path(self):
        return self.state_dir / "lessons.jsonl"

    def handle_exit(self, symbol, exit_price, pnl, reason):
        """Report the exit, ask the Reviewer what went right/wrong, store the lesson."""
        trade = self.state.setdefault("open_trades", {}).pop(symbol, None)
        r_multiple = round(pnl / trade["risk_usd"], 2) if trade and pnl is not None and trade["risk_usd"] else None
        lesson = None
        if trade:
            packet = {**trade, "result": {"exit_price": exit_price, "pnl_usd": pnl, "r_multiple": r_multiple,
                                          "closed_by": reason}}
            try:
                review = reviewer.run(packet, self.provider, log=self.log)
                lesson = review["lesson"]
            except Exception as exc:  # a failed review must not block trading
                self.log.warning("review %s failed: %s", symbol, exc)
                review = None
            record = {"closed": datetime.now(timezone.utc).isoformat(timespec="seconds"), "market": symbol,
                      "side": trade["side"], "leverage": trade["leverage"], "pnl_usd": pnl,
                      "r_multiple": r_multiple, "closed_by": reason, "review": review}
            self.state_dir.mkdir(parents=True, exist_ok=True)
            with self.lessons_path().open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        self.save()
        result = f"результат {pnl:+.2f}" + (f" ({r_multiple:+.2f}R)" if r_multiple is not None else "") \
            if pnl is not None else "результат уточните на бирже"
        price = f"цена {exit_price}, " if exit_price is not None else ""
        lines = [f"🔚 ВЫХОД ({self.venue.name}) {symbol} — {reason}: {price}{result}"]
        if lesson:
            lines.append(f"📝 Урок: {lesson}")
        self.notifier.send("\n".join(lines))

    def past_performance(self):
        """Code statistics plus the latest Reviewer lessons, given to Risk and Decision as data."""
        path = self.lessons_path()
        if not path.exists():
            return {"closed_trades": 0, "note": "Истории сделок ещё нет."}
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        known = [r for r in rows if r["r_multiple"] is not None]

        def stats(items):
            wins = sum(r["r_multiple"] > 0 for r in items)
            return {"trades": len(items), "win_rate_pct": round(100 * wins / len(items)) if items else None,
                    "avg_r": round(sum(r["r_multiple"] for r in items) / len(items), 2) if items else None}

        by = {}
        for key in ("market", "side"):
            groups = {}
            for r in known:
                groups.setdefault(r[key], []).append(r)
            by[key] = {k: stats(v) for k, v in groups.items()}
        return {
            "closed_trades": len(rows),
            "overall": stats(known),
            "by_market": by["market"],
            "by_side": by["side"],
            "losing_streak": self.losing_streak(known),
            "recent_lessons": [{"market": r["market"], "side": r["side"], "r": r["r_multiple"],
                                "lesson": (r.get("review") or {}).get("lesson"),
                                "tags": (r.get("review") or {}).get("tags", [])} for r in rows[-10:]],
        }

    @staticmethod
    def losing_streak(known):
        streak = 0
        for r in reversed(known):
            if r["r_multiple"] >= 0:
                break
            streak += 1
        return streak

    # ---- one cycle ---------------------------------------------------------
    def run_cycle(self):
        self.handle_commands()
        if self.stopped():
            return {"status": "paused"}

        reported = set()
        for event in self.venue.sync():
            reported.add(event["symbol"])
            self.handle_exit(event["symbol"], event["exit"], event["pnl"],
                             "стоп" if event["reason"] == "stop" else "цель")
        positions = self.venue.positions()
        for symbol in sorted(set(self.state.get("open_symbols", [])) - set(positions) - reported):
            opened = self.state.get("open_trades", {}).get(symbol, {}).get("opened_ts", time.time() - 86400)
            result = self.venue.closed_result(symbol, opened) or {}
            self.handle_exit(symbol, result.get("exit"), result.get("pnl"), "стоп или цель")
        self.state["open_symbols"] = sorted(positions)

        equity = self.venue.equity()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self.state.get("day") != today:
            self.state.update(day=today, day_start_equity=equity, daily_stop_sent=False)
        self.save()

        loss_today = self.state["day_start_equity"] - equity
        if loss_today >= self.state["day_start_equity"] * self.rules["max_daily_loss_pct"] / 100:
            if not self.state.get("daily_stop_sent"):
                self.state["daily_stop_sent"] = True
                self.save()
                self.notifier.send(f"🛑 Дневной лимит убытка достигнут ({loss_today:,.2f}). "
                                   "Новых сделок до завтра (UTC) не будет.")
            return {"status": "daily_stop"}
        if len(positions) >= self.rules["max_open_positions"]:
            return {"status": "max_positions"}

        symbols = self.config["watchlist"]
        universe = self.config.get("universe")
        if universe:
            symbols = self.venue.universe(universe["top_n"], universe["min_turnover_24h_usd"]) or symbols
        bars_by_symbol = {}
        for symbol in symbols:
            if symbol in positions:
                continue  # one position per market
            if not self.venue.is_tradable(symbol):
                continue  # market closed: no analysis, no Claude cost
            try:
                bars = self.venue.candles(symbol, self.config["candles"])
            except Exception as exc:
                self.log.warning("candles %s failed: %s", symbol, exc)
                continue
            if len(bars) >= 30:
                bars_by_symbol[symbol] = bars
        if not bars_by_symbol:
            return {"status": "no_data"}

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        label = f"LIVE market data from {self.venue.name}, timeframe {self.config['timeframe_label']}"
        watch_packet = {"_label": label, "as_of": now,
                        "watchlist": [summarize(s, b) for s, b in bars_by_symbol.items()]}

        outputs = {"scout": picker.run(watch_packet, self.provider, log=self.log)}
        self.log.info("pick -> %s", json.dumps(outputs["scout"], ensure_ascii=False))
        symbol = outputs["scout"]["market"]
        if symbol == picker.NONE:
            return {"status": "no_pick"}

        bars = bars_by_symbol[symbol]
        packet = {"_label": label, "market": symbol, "as_of": now, "price_history": bars,
                  "intraday": {"timeframe": self.config["timeframe_label"]}, "news": [], "social_posts": []}
        outputs["news"] = news.run_live(packet, self.provider, log=self.log)
        outputs["sentiment"] = sentiment.run_live(packet, self.provider, log=self.log)
        outputs["charts"] = charts.run(packet, self.provider, log=self.log)
        outputs["past_performance"] = experience = self.past_performance()

        # The Risk gate sizes by equity: max loss = risk % per trade; notional is limited later by leverage.
        rules = {**self.rules, "max_loss_pct_per_trade": self.rules["risk_pct_per_trade"],
                 "max_position_pct_of_balance": self.rules["max_leverage"] * 100}
        simulation = {"starting_balance_usd": equity, "simulated_loss_today_usd": max(0.0, loss_today)}
        outputs["risk"] = risk.run(packet, outputs, self.provider, rules, simulation, log=self.log)
        self.log.info("risk -> %s", json.dumps(outputs["risk"], ensure_ascii=False))
        if outputs["risk"]["status"] == "reject":
            return {"status": "risk_reject", "symbol": symbol, "outputs": outputs}

        outputs["decision"] = trade_decision.run(packet, outputs, self.provider, log=self.log)
        dec = outputs["decision"]
        self.log.info("decision -> %s", json.dumps(dec, ensure_ascii=False))
        if dec["decision"] not in trade_decision.TRADES:
            return {"status": dec["decision"].lower(), "symbol": symbol, "outputs": outputs}

        entry = bars[-1]["close"]
        problems = trade_decision.check_plan(dec, entry, self.rules)
        if problems:
            self.log.info("plan rejected: %s", problems)
            return {"status": "plan_rejected", "symbol": symbol, "problems": problems, "outputs": outputs}

        risk_usd = outputs["risk"]["maximum_simulated_loss"]
        streak_limit = self.rules.get("losing_streak_halve_risk", 0)
        if streak_limit and experience.get("losing_streak", 0) >= streak_limit:
            risk_usd /= 2  # cool down after a run of losses until the next win
        leverage = trade_decision.safe_leverage(dec, entry, self.rules)
        # Each open position may use at most its share of the margin, so the next trade still fits.
        margin_share = equity * 0.9 / self.rules["max_open_positions"]
        max_notional = min(outputs["risk"]["maximum_simulated_size"], margin_share * leverage)
        qty = self.venue.size(symbol, entry, dec["stop_loss"], risk_usd, max_notional)
        if qty <= 0:
            return {"status": "too_small", "symbol": symbol, "outputs": outputs}

        budget_usd = risk_usd
        risk_usd = qty * abs(entry - dec["stop_loss"])  # actual loss at the stop after leverage/margin caps
        self.venue.set_leverage(symbol, leverage)
        order = self.venue.market_order(symbol, dec["decision"], qty, dec["stop_loss"], dec["take_profit"])
        self.state["open_symbols"] = sorted(set(self.state["open_symbols"]) | {symbol})
        self.state.setdefault("open_trades", {})[symbol] = {
            "market": symbol, "side": dec["decision"], "entry": order["price"], "stop": dec["stop_loss"],
            "take": dec["take_profit"], "leverage": leverage, "qty": qty, "risk_usd": round(risk_usd, 2),
            "opened": now, "opened_ts": time.time(),
            "team_said": {k: outputs[k] for k in ("scout", "news", "sentiment", "charts", "risk", "decision")},
        }
        self.save()
        self.journal(symbol, dec, qty, leverage, order, risk_usd, outputs["risk"]["status"])
        icon = "🟢" if dec["decision"] == "BUY" else "🔴"
        self.notifier.send("\n".join([
            f"{icon} ВХОД ({self.venue.name}) {dec['decision']} {symbol}",
            f"Объём: {qty} · Плечо: x{leverage} · Цена ≈ {order['price']}",
            f"Стоп: {dec['stop_loss']} · Цель: {dec['take_profit']}",
            f"Риск: ${risk_usd:,.2f} ({risk_usd / equity * 100:.2f}% счёта · Risk Bot: {outputs['risk']['status']})",
            *(["⚠️ Серия убытков — риск снижен вдвое до первой прибыльной сделки"]
              if budget_usd < outputs["risk"]["maximum_simulated_loss"] else []),
            "Почему: " + "; ".join(dec["reasons"][:3]),
        ]))
        return {"status": "opened", "symbol": symbol, "order": order, "qty": qty, "leverage": leverage,
                "outputs": outputs}

    def journal(self, symbol, dec, qty, leverage, order, risk_usd, risk_status):
        path = self.state_dir / "trades.csv"
        new = not path.exists()
        with path.open("a", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=JOURNAL_FIELDS)
            if new:
                writer.writeheader()
            writer.writerow({
                "time": datetime.now(timezone.utc).isoformat(timespec="seconds"), "venue": self.venue.name,
                "symbol": symbol, "side": dec["decision"], "qty": qty, "leverage": leverage, "entry": order["price"],
                "stop": dec["stop_loss"], "take": dec["take_profit"], "risk_usd": round(risk_usd, 2),
                "risk_status": risk_status, "order_id": order["id"], "reasons": " | ".join(dec["reasons"]),
            })
