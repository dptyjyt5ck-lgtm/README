"""Оценка прогнозов: угадывание направления, IC, калибровка диапазона и торговля с комиссиями.

Порог входа подбирается на первой половине периода, проверяется на второй — как в research/REPORT.md.
"""
import numpy as np
import pandas as pd

THRESHOLDS = [0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9]
MIN_TRADES = 30


def summarize_paths(entry, paths):
    """Из путей [n, samples] — медиана, 10/90 перцентили и доля путей выше цены входа."""
    return {
        "pred_median": np.median(paths, axis=1),
        "pred_q10": np.quantile(paths, 0.1, axis=1),
        "pred_q90": np.quantile(paths, 0.9, axis=1),
        "p_up": (paths > entry[:, None]).mean(axis=1),
    }


def _rank(x):
    return pd.Series(x).rank().to_numpy()


def spearman(a, b):
    if len(a) < 3:
        return float("nan")
    return float(np.corrcoef(_rank(a), _rank(b))[0, 1])


def trades(df, thr, cost_bps):
    """Лонг при p_up >= thr, шорт при p_up <= 1-thr, выход через horizon свечей. Доходность в б.п. после издержек."""
    side = np.where(df["p_up"] >= thr, 1, np.where(df["p_up"] <= 1 - thr, -1, 0))
    if thr == 0.5:  # ровно 0.5 — ни туда ни сюда
        side = np.where(df["p_up"] > 0.5, 1, np.where(df["p_up"] < 0.5, -1, 0))
    gross = side * (df["actual"] / df["entry"] - 1) * 1e4
    mask = side != 0
    return gross[mask] - 2 * cost_bps


def stats(net):
    net = np.asarray(net, dtype=float)
    n = len(net)
    if n == 0:
        return {"trades": 0, "win_pct": None, "avg_bps": None, "total_pct": None, "t_stat": None}
    sd = net.std(ddof=1) if n > 1 else 0.0
    return {
        "trades": n,
        "win_pct": round(100 * (net > 0).mean(), 1),
        "avg_bps": round(net.mean(), 1),
        "total_pct": round(net.sum() / 100, 1),
        "t_stat": round(net.mean() / (sd / np.sqrt(n)), 2) if sd > 0 else None,
    }


def evaluate(pred, cost_bps):
    """pred: DataFrame с колонками time, entry, actual, pred_median, pred_q10, pred_q90, p_up."""
    pred = pred.sort_values("time").reset_index(drop=True)
    half = len(pred) // 2
    train, test = pred.iloc[:half], pred.iloc[half:]

    real = test["actual"] / test["entry"] - 1
    fore = test["pred_median"] / test["entry"] - 1
    direction = (np.sign(real) == np.sign(fore))[fore != 0]

    best_thr, best_avg = None, -np.inf
    for thr in THRESHOLDS:
        net = trades(train, thr, cost_bps)
        if len(net) >= MIN_TRADES and net.mean() > best_avg:
            best_thr, best_avg = thr, net.mean()

    return {
        "points": len(pred),
        "direction_hit_pct": round(100 * direction.mean(), 1) if len(direction) else None,
        "ic_spearman": round(spearman(fore.to_numpy(), real.to_numpy()), 3),
        "band80_coverage_pct": round(100 * ((test["actual"] >= test["pred_q10"]) &
                                             (test["actual"] <= test["pred_q90"])).mean(), 1),
        "threshold": best_thr,
        "train": stats(trades(train, best_thr, cost_bps)) if best_thr else stats([]),
        "test": stats(trades(test, best_thr, cost_bps)) if best_thr else stats([]),
        "test_all_signals": stats(trades(test, 0.5, cost_bps)),
    }
