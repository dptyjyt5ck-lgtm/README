"""Проверка самого стенда без сети и без torch: python -m pytest -q research/kronos"""
import os
import sys
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bybit_data  # noqa: E402
import run_kronos_check as rk  # noqa: E402
from evaluate import evaluate  # noqa: E402
from forecasters import KronosForecaster, RandomWalkForecaster  # noqa: E402

H = 12


def market(n=3000, seed=1):
    rng = np.random.default_rng(seed)
    close = 30000 * np.exp(np.cumsum(rng.normal(0, 0.006, n)))
    ts = pd.date_range("2025-09-01", periods=n, freq="h")
    return pd.DataFrame({"timestamps": ts, "open": close, "high": close * 1.002, "low": close * 0.998,
                         "close": close, "volume": 100.0, "amount": close * 100})


class Oracle:
    """Знает будущее — стенд обязан показать у него огромное преимущество."""
    name = "oracle"

    def __init__(self, df):
        self.df = df

    def forecast(self, windows, horizon, freq="h"):
        out = []
        for w in windows:
            t = self.df.index[self.df["timestamps"] == w["timestamps"].iloc[-1]][0]
            out.append(np.full(4, self.df["close"].iloc[t + horizon]))
        return np.array(out)


def run(df, fc, tmp_path):
    return rk.predict_symbol(df, fc, 256, H, H, 64, str(tmp_path / f"{fc.name}.csv"), log=lambda *_: None)


def test_oracle_has_edge_random_walk_does_not(tmp_path):
    df = market()
    good = evaluate(run(df, Oracle(df), tmp_path), cost_bps=7.5)
    assert good["direction_hit_pct"] == 100 and good["test"]["avg_bps"] > 50 and good["test"]["t_stat"] > 5
    noise = evaluate(run(df, RandomWalkForecaster(8), tmp_path), cost_bps=7.5)
    assert 35 < noise["direction_hit_pct"] < 65
    assert noise["test_all_signals"]["avg_bps"] < 10  # без преимущества комиссии съедают всё


def test_no_lookahead_in_windows():
    df = market(400)
    for t in rk.windows_for(df, 256, H, H):
        window = df.iloc[t - 256:t]
        assert window["timestamps"].iloc[-1] == df["timestamps"].iloc[t - 1]
        assert t - 1 + H < len(df)


def test_resume_from_cache(tmp_path):
    df = market(800)
    calls = []

    class Counting(RandomWalkForecaster):
        def forecast(self, windows, horizon, freq="h"):
            calls.append(len(windows))
            return super().forecast(windows, horizon, freq)

    first = run(df, Counting(4), tmp_path)
    n = sum(calls)
    second = run(df, Counting(4), tmp_path)
    assert sum(calls) == n and len(second) == len(first)


def test_kronos_adapter_splits_samples():
    seen = {}

    def predict_batch(dfs, xs, ys, pred_len, T, top_p, sample_count, verbose):
        seen.update(n=len(dfs), sample_count=sample_count, pred_len=pred_len, y=ys[0])
        return [pd.DataFrame({"close": np.full(pred_len, 100.0 + i)}) for i in range(len(dfs))]

    fc = KronosForecaster(samples=3, predictor=SimpleNamespace(predict_batch=predict_batch))
    df = market(300)
    paths = fc.forecast([df.iloc[:256], df.iloc[10:266]], H)
    assert paths.shape == (2, 3) and seen["n"] == 6 and seen["sample_count"] == 1
    assert seen["y"].iloc[0] == df["timestamps"].iloc[255] + pd.Timedelta(hours=1) and len(seen["y"]) == H


def test_bybit_pagination():
    start = pd.Timestamp("2025-09-01")
    all_rows = [[str(int((start + pd.Timedelta(hours=i)).timestamp() * 1000)), "1", "2", "0.5", "1.5", "10", "15"]
                for i in range(2500)]

    class HTTP:
        def get(self, url, params, timeout):
            rows = [r for r in all_rows if params["start"] <= int(r[0]) <= params["end"]][-params["limit"]:]
            return SimpleNamespace(raise_for_status=lambda: None,
                                   json=lambda: {"result": {"list": list(reversed(rows))}})

    df = bybit_data.download("BTCUSDT", "2025-09-01", "2025-12-01", http=HTTP())
    assert len(df) == 91 * 24 and df["timestamps"].is_monotonic_increasing
