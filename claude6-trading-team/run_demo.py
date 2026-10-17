"""Run the six-bot research team on one market. Educational simulation only."""
import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from agents import charts, decision, news, risk, scout, sentiment
from agents.base import BotError, redact
from agents.mock_provider import MockProvider

ROOT = Path(__file__).resolve().parent


def load_json(preferred, fallback):
    path = ROOT / preferred
    if not path.exists():
        path = ROOT / fallback
    return json.loads(path.read_text(encoding="utf-8"))


def make_provider(config):
    name = os.environ.get("MODEL_PROVIDER", "MOCK").upper()
    if name == "MOCK":
        return MockProvider()
    if name == "CLAUDE":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise BotError("MODEL_PROVIDER=CLAUDE needs ANTHROPIC_API_KEY in .env")
        from agents.claude_provider import ClaudeProvider
        return ClaudeProvider(
            model=config["model"],
            effort=config.get("effort", "medium"),
            max_tokens=config.get("max_output_tokens", 16000),
            use_fallbacks=config.get("use_refusal_fallbacks", True),
        )
    raise BotError(f"Unknown MODEL_PROVIDER={name!r} (use MOCK or CLAUDE)")


def setup_log(path):
    log = logging.getLogger(f"run-{path.stem}")
    log.setLevel(logging.INFO)
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(handler)
    return log


def run(market_path, provider=None):
    config = load_json("config.json", "config.example.json")
    rules = load_json("risk-rules.json", "risk-rules.example.json")
    packet = json.loads(Path(market_path).read_text(encoding="utf-8"))

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    reports_dir = ROOT / config["reports_dir"]
    logs_dir = ROOT / config["logs_dir"]
    reports_dir.mkdir(exist_ok=True)
    logs_dir.mkdir(exist_ok=True)
    log = setup_log(logs_dir / f"run-{stamp}.log")
    log.info("market=%s label=%s", packet.get("market"), packet.get("_label"))

    outputs, final, error = {}, "SKIP", None
    try:
        provider = provider or make_provider(config)
        log.info("provider=%s", type(provider).__name__)
        for step, (name, module) in enumerate(
            [("scout", scout), ("news", news), ("sentiment", sentiment), ("charts", charts)], 1
        ):
            outputs[name] = module.run(packet, provider, log=log)
            log.info("%s -> %s", name, json.dumps(outputs[name], ensure_ascii=False))
            print(f"[{step}/6] {name.capitalize()} Bot complete")

        outputs["risk"] = risk.run(packet, outputs, provider, rules, config["simulation"], log=log)
        log.info("risk -> %s", json.dumps(outputs["risk"], ensure_ascii=False))
        print("[5/6] Risk Bot complete")

        if outputs["risk"]["status"] == "reject":
            print("Risk Bot rejected — Decision Bot not run.")
            log.info("stopped: risk rejected")
        else:
            outputs["decision"] = decision.run(packet, outputs, provider, log=log)
            log.info("decision -> %s", json.dumps(outputs["decision"], ensure_ascii=False))
            print("[6/6] Decision Bot complete")
            final = outputs["decision"]["decision"]
    except BotError as exc:
        error = str(exc)
        log.error("stopped: %s", error)
        print(f"Stopped safely: {redact(error)}")

    report = {
        "run_id": stamp,
        "trading_mode": "SIMULATION_ONLY",
        "data_label": packet.get("_label"),
        "market": packet.get("market"),
        "final_result": final,
        "human_review_required": True,
        "error": error,
        "outputs": outputs,
        "disclaimer": "Educational simulation only. Not financial advice. No order was sent.",
    }
    report_path = reports_dir / f"report-{stamp}.json"
    report_path.write_text(redact(json.dumps(report, ensure_ascii=False, indent=2)), encoding="utf-8")
    for handler in list(log.handlers):
        handler.close()
        log.removeHandler(handler)
    _scrub_file(logs_dir / f"run-{stamp}.log")

    print(f"Final result: {final}")
    print(f"Report saved -> {report_path.relative_to(ROOT)}")
    return report, report_path


def _scrub_file(path):
    path.write_text(redact(path.read_text(encoding="utf-8")), encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market", default=str(ROOT / "data" / "sample_market.json"))
    args = parser.parse_args(argv)
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    if os.environ.get("TRADING_MODE") != "SIMULATION_ONLY":
        print("Refusing to start: set TRADING_MODE=SIMULATION_ONLY in .env", file=sys.stderr)
        return 2
    run(args.market)
    return 0


if __name__ == "__main__":
    sys.exit(main())
