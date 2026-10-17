"""Часовые свечи бессрочных USDT-контрактов Bybit (публичный API, без ключа) с кэшем в CSV."""
import os
import time

import pandas as pd

URL = "https://api.bybit.com/v5/market/kline"
CACHE = os.path.join(os.path.dirname(__file__), "data")


def download(symbol, start, end, interval="60", http=None):
    """Свечи [start, end) по возрастанию времени. start/end — строки или Timestamp (UTC)."""
    if http is None:
        import requests as http
    start_ms = int(pd.Timestamp(start, tz="UTC").timestamp() * 1000)
    end_ms = int(pd.Timestamp(end, tz="UTC").timestamp() * 1000)
    rows, cursor = {}, end_ms
    while cursor > start_ms:
        resp = http.get(URL, params={"category": "linear", "symbol": symbol, "interval": interval,
                                     "start": start_ms, "end": cursor - 1, "limit": 1000}, timeout=20)
        resp.raise_for_status()
        batch = resp.json()["result"]["list"]  # новые сначала
        if not batch:
            break
        for r in batch:
            rows[int(r[0])] = r
        cursor = min(int(r[0]) for r in batch)
        time.sleep(0.1)
    df = pd.DataFrame(sorted(rows.values(), key=lambda r: int(r[0])),
                      columns=["ts", "open", "high", "low", "close", "volume", "amount"])
    df["timestamps"] = pd.to_datetime(df["ts"].astype("int64"), unit="ms", utc=True).dt.tz_localize(None)
    for col in ["open", "high", "low", "close", "volume", "amount"]:
        df[col] = df[col].astype(float)
    df = df[(df["ts"].astype("int64") >= start_ms) & (df["ts"].astype("int64") < end_ms)]
    return df.drop(columns="ts").reset_index(drop=True)


def load(symbol, start, end, interval="60"):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, f"{symbol}_{interval}_{pd.Timestamp(start):%Y%m%d}_{pd.Timestamp(end):%Y%m%d}.csv")
    if os.path.exists(path):
        return pd.read_csv(path, parse_dates=["timestamps"])
    df = download(symbol, start, end, interval)
    df.to_csv(path, index=False)
    return df
