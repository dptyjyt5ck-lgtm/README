"""Загрузка котировок M15 и пересчёт в доллары.

Источники (открытые, бесплатные):
  * github.com/ejtraderLabs/historical-data — 12 инструментов, 2012-11 … 2022-03 (цены ×1e5/1e3/1e2);
  * github.com/getdata-finance/<pair>-15m-ohlcv-forex-historical-data — 8 пар, 2026-03-26 … 2026-09-25 (UTC).
"""
import os
import numpy as np
import pandas as pd

from sim import Market

DATA = os.environ.get("ZZ_DATA", os.path.join(os.path.dirname(__file__), "..", "..", "data"))

# спред + комиссия, в цене (оценка для ECN-счёта: ~1 пункт на мажорах)
SPREAD = dict(EURUSD=0.00010, GBPUSD=0.00014, AUDUSD=0.00012, USDCAD=0.00016, USDCHF=0.00015,
              USDJPY=0.011, EURJPY=0.016, GBPJPY=0.025, AUDJPY=0.018, EURGBP=0.00014,
              EURCHF=0.00018, XAUUSD=0.30)
SCALE = dict(USDJPY=1e3, EURJPY=1e3, GBPJPY=1e3, AUDJPY=1e3, XAUUSD=1e2)
SYMS_OLD = ["EURUSD", "GBPUSD", "AUDUSD", "USDCAD", "USDCHF", "USDJPY", "EURJPY", "GBPJPY",
            "AUDJPY", "EURGBP", "EURCHF", "XAUUSD"]
SYMS_NEW = ["EURUSD", "GBPUSD", "AUDUSD", "USDCAD", "USDCHF", "USDJPY", "EURJPY", "EURGBP"]

_cache = {}


def load_raw(sym, era):
    key = (sym, era)
    if key in _cache:
        return _cache[key]
    if era == "old":
        f = os.path.join(DATA, "ej", sym, f"{sym}m15.csv")
        df = pd.read_csv(f)
        t = pd.to_datetime(df["Date"]).values.astype("datetime64[s]").astype(np.int64)
        sc = SCALE.get(sym, 1e5)
        arr = [df[c].values / sc for c in ("open", "high", "low", "close")]
    else:
        f = os.path.join(DATA, "gd", f"{sym.lower()}_15m.csv")
        df = pd.read_csv(f)
        t = pd.to_datetime(df["datetime"], utc=True).dt.tz_localize(None).values.astype("datetime64[s]").astype(np.int64)
        arr = [df[c].values.astype(float) for c in ("open", "high", "low", "close")]
    o, h, l, c = arr
    ok = (h >= np.maximum(o, c) - 1e-9) & (l <= np.minimum(o, c) + 1e-9)
    order = np.argsort(t, kind="stable")
    t, o, h, l, c, ok = t[order], o[order], h[order], l[order], c[order], ok[order]
    keep = ok & np.r_[True, t[1:] != t[:-1]]
    r = (t[keep], o[keep], h[keep], l[keep], c[keep])
    _cache[key] = r
    return r


def rate_fn(sym, era):
    t, o, h, l, c = load_raw(sym, era)

    def f(ts):
        i = np.searchsorted(t, ts, side="right") - 1
        return c[max(i, 0)]
    return f


def value_fn(sym, era):
    """USD за изменение цены на 1.0 при объёме 1 лот."""
    if sym == "XAUUSD":
        return lambda ts, p: 100.0
    if sym.endswith("USD"):
        return lambda ts, p: 100000.0
    if sym.startswith("USD"):
        return lambda ts, p: 100000.0 / p
    quote = sym[3:]
    conv = {"JPY": "USDJPY", "CHF": "USDCHF", "GBP": "GBPUSD"}[quote]
    rf = rate_fn(conv, era)
    if conv.endswith("USD"):
        return lambda ts, p: 100000.0 * rf(ts)
    return lambda ts, p: 100000.0 / rf(ts)


def market(sym, era, period=3600):
    t, o, h, l, c = load_raw(sym, era)
    return Market(sym, t, o, h, l, c, SPREAD[sym], value_fn(sym, era), period)
