"""Bot 5 — Risk gate. The model may tighten the human rules, never loosen them."""
from .base import run_bot

SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["approve", "reduce", "reject"]},
        "maximum_simulated_size": {"type": "number"},
        "maximum_simulated_loss": {"type": "number"},
        "risk_flags": {"type": "array", "items": {"type": "string"}},
        "reason": {"type": "string"},
    },
    "required": ["status", "maximum_simulated_size", "maximum_simulated_loss", "risk_flags", "reason"],
    "additionalProperties": False,
}

STRICTNESS = {"approve": 0, "reduce": 1, "reject": 2}


def code_flags(packet, outputs, rules, simulation):
    """Flags computed in plain code from the data, independent of any model."""
    flags = []
    bars = packet.get("price_history") or []
    if not bars:
        flags.append("no_price_data")
    else:
        avg_dollar_volume = sum(b["volume"] * b["close"] for b in bars) / len(bars)
        if avg_dollar_volume < rules["min_liquidity_usd"]:
            flags.append("liquidity_below_minimum")
    balance = simulation["starting_balance_usd"]
    if simulation.get("simulated_loss_today_usd", 0) >= balance * rules["max_daily_loss_pct"] / 100:
        flags.append("daily_loss_limit_reached")
    if outputs["news"]["unverified_claims"]:
        flags.append("unverified_claims")
    if outputs["sentiment"]["possible_hype"]:
        flags.append("possible_hype")
    if outputs["charts"]["missing_data"]:
        flags.append("incomplete_chart_data")
    if outputs["charts"]["trend"] == "unknown":
        flags.append("trend_unknown")
    if outputs["scout"]["data_quality"] == "poor":
        flags.append("poor_data_quality")
    return flags


def caps(rules, simulation):
    balance = simulation["starting_balance_usd"]
    return {
        "max_size_usd": round(balance * rules["max_position_pct_of_balance"] / 100, 2),
        "max_loss_usd": round(balance * rules["max_loss_pct_per_trade"] / 100, 2),
    }


def enforce(model_out, flags, rules, simulation):
    """Combine the model's answer with the human rules; the stricter side always wins."""
    if any(f in rules["reject_if_any"] for f in flags):
        code_status = "reject"
    elif any(f in rules["reduce_if_any"] for f in flags):
        code_status = "reduce"
    else:
        code_status = "approve"
    status = max(model_out["status"], code_status, key=STRICTNESS.get)

    limit = caps(rules, simulation)
    factor = {"approve": 1.0, "reduce": 0.5, "reject": 0.0}[status]
    max_size = limit["max_size_usd"] * factor
    max_loss = limit["max_loss_usd"] * factor

    reason = model_out["reason"]
    if status != model_out["status"]:
        reason += f" | Code rules raised status to {status}."
    return {
        "status": status,
        "maximum_simulated_size": round(min(max(model_out["maximum_simulated_size"], 0), max_size), 2),
        "maximum_simulated_loss": round(min(max(model_out["maximum_simulated_loss"], 0), max_loss), 2),
        "risk_flags": sorted(set(model_out["risk_flags"]) | set(flags)),
        "reason": reason,
    }


def run(packet, outputs, provider, rules, simulation, log=None):
    flags = code_flags(packet, outputs, rules, simulation)
    inputs = {**outputs, "risk_rules": rules, "code_flags": flags, "caps": caps(rules, simulation)}
    model_out = run_bot("risk", SCHEMA, packet, provider, inputs=inputs, log=log)
    return enforce(model_out, flags, rules, simulation)
