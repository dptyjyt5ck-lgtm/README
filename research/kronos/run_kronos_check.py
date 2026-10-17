"""Проверка Kronos на истории крипты с комиссиями Bybit.

Запуск (на своём компьютере, нужен доступ к huggingface.co и api.bybit.com):
    git clone https://github.com/shiyu-coder/Kronos ../../../Kronos
    pip install torch einops huggingface_hub safetensors pandas requests
    python run_kronos_check.py --kronos-path ../../../Kronos

Прогнозы кэшируются в preds/, так что прерванный запуск продолжается с места остановки.
"""
import argparse
import json
import os
import sys
import time

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import bybit_data  # noqa: E402
from evaluate import evaluate, summarize_paths  # noqa: E402
from forecasters import KronosForecaster, MomentumForecaster, RandomWalkForecaster  # noqa: E402


def windows_for(df, lookback, horizon, step):
    """Точки входа t: окно df[t-lookback:t], вход по close[t-1], выход по close[t-1+horizon]."""
    return list(range(lookback, len(df) - horizon + 1, step))


def predict_symbol(df, forecaster, lookback, horizon, step, batch, cache_path, log=print):
    done = pd.read_csv(cache_path, parse_dates=["time"]) if os.path.exists(cache_path) else None
    have = set(done["time"]) if done is not None else set()
    points = [t for t in windows_for(df, lookback, horizon, step) if df["timestamps"].iloc[t - 1] not in have]
    rows = [] if done is None else [done]
    started = time.time()
    for i in range(0, len(points), batch):
        chunk = points[i:i + batch]
        windows = [df.iloc[t - lookback:t] for t in chunk]
        paths = forecaster.forecast(windows, horizon)
        entry = np.array([df["close"].iloc[t - 1] for t in chunk])
        part = pd.DataFrame({"time": [df["timestamps"].iloc[t - 1] for t in chunk], "entry": entry,
                             "actual": [df["close"].iloc[t - 1 + horizon] for t in chunk],
                             **summarize_paths(entry, paths)})
        rows.append(part)
        pd.concat(rows).to_csv(cache_path, index=False)
        done_n = i + len(chunk)
        eta = (time.time() - started) / done_n * (len(points) - done_n)
        if (i // batch) % 10 == 0 or done_n == len(points):
            log(f"  {forecaster.name}: {done_n}/{len(points)} окон, осталось ~{eta / 60:.0f} мин")
    return pd.concat(rows) if rows else pd.DataFrame()


def fmt(s):
    if not s["trades"]:
        return "нет сделок"
    return (f"{s['trades']} сделок, прибыльных {s['win_pct']}%, в среднем {s['avg_bps']:+} б.п., "
            f"итого {s['total_pct']:+}%, t={s['t_stat']}")


def report(results, args):
    lines = [
        "# Kronos на крипте: проверка с комиссиями",
        "",
        f"- Рынки: {', '.join(args.symbols)}; свечи {args.interval} мин; {args.start} … {args.end}.",
        f"- Окно {args.lookback} свечей, прогноз на {args.horizon} свечей вперёд, новая точка каждые {args.step}.",
        f"- Путей на прогноз: {args.samples}. Издержки: {args.cost_bps} б.п. на сторону "
        f"(тейкер Bybit 5,5 + проскальзывание), {2 * args.cost_bps} б.п. на сделку.",
        "- Первая половина периода — подбор порога уверенности, вторая — проверка.",
        "- Эталоны: random-walk (рынок случаен, преимущества нет) и momentum (тренд продолжится).",
        "",
        "Как читать: «угадано направлений» около 50% и IC около 0 — нет предсказательной силы. "
        "«Диапазон 80%» должен накрывать факт примерно в 80% случаев. "
        "Главное — строка «проверка»: средний результат после издержек > 0 и t > 2.",
        "",
    ]
    for symbol, by_model in results.items():
        lines += [f"## {symbol}", "", "| Модель | Угадано направлений | IC | Диапазон 80% | Порог | Подбор (1-я половина) | Проверка (2-я половина) |",
                  "|---|---|---|---|---|---|---|"]
        for name, r in by_model.items():
            lines.append(f"| {name} | {r['direction_hit_pct']}% | {r['ic_spearman']} | {r['band80_coverage_pct']}% | "
                         f"{r['threshold']} | {fmt(r['train'])} | {fmt(r['test'])} |")
        lines.append("")
    return "\n".join(lines)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    p.add_argument("--interval", default="60")
    # Модель опубликована в августе 2025: берём период после этого, чтобы она не «видела» эти данные.
    p.add_argument("--start", default="2025-09-01")
    p.add_argument("--end", default=pd.Timestamp.now("UTC").strftime("%Y-%m-%d"))
    p.add_argument("--lookback", type=int, default=256)
    p.add_argument("--horizon", type=int, default=12)
    p.add_argument("--step", type=int, default=12)
    p.add_argument("--samples", type=int, default=8)
    p.add_argument("--batch", type=int, default=16, help="окон за один вызов модели")
    p.add_argument("--size", default="mini", choices=["mini", "small", "base"])
    p.add_argument("--device", default=None, help="cpu / cuda:0 / mps; по умолчанию автоматически")
    p.add_argument("--cost-bps", type=float, default=7.5)
    p.add_argument("--kronos-path", default=os.environ.get("KRONOS_PATH"))
    p.add_argument("--baselines-only", action="store_true", help="без Kronos — проверить, что всё работает")
    args = p.parse_args(argv)

    forecasters = [RandomWalkForecaster(args.samples), MomentumForecaster(args.samples)]
    if not args.baselines_only:
        if not args.kronos_path:
            p.error("укажите --kronos-path (папка git clone https://github.com/shiyu-coder/Kronos)")
        sys.path.insert(0, os.path.abspath(args.kronos_path))
        forecasters.append(KronosForecaster(args.size, args.samples, device=args.device))

    os.makedirs(os.path.join(HERE, "preds"), exist_ok=True)
    results = {}
    for symbol in args.symbols:
        print(f"{symbol}: загрузка свечей…")
        df = bybit_data.load(symbol, args.start, args.end, args.interval)
        print(f"{symbol}: {len(df)} свечей")
        results[symbol] = {}
        for fc in forecasters:
            cache = os.path.join(HERE, "preds", f"{symbol}_{fc.name}_{args.start}_{args.end}_"
                                               f"L{args.lookback}H{args.horizon}S{args.step}N{args.samples}.csv")
            pred = predict_symbol(df, fc, args.lookback, args.horizon, args.step, args.batch, cache)
            results[symbol][fc.name] = evaluate(pred, args.cost_bps)

    text = report(results, args)
    out = os.path.join(HERE, "REPORT_kronos.md")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(text + "\n")
    with open(os.path.join(HERE, "results_kronos.json"), "w", encoding="utf-8") as fh:
        json.dump(results, fh, ensure_ascii=False, indent=2)
    print(text)
    print(f"\nОтчёт: {out}")


if __name__ == "__main__":
    main()
