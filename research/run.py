"""Прогон конфигураций по инструментам и периодам; итоги в R (идеальные дробные лоты)."""
import sys
import time
from multiprocessing import Pool

import numpy as np
import pandas as pd

import data
from sim import Sim

TRAIN = ("2013-01-01", "2019-01-01")
VALID = ("2019-01-01", "2022-03-05")
HOLD = ("2026-01-01", "2027-01-01")


def ts(s):
    return int(pd.Timestamp(s).value // 10**9)


def one(args):
    sym, era, c, start, end = args
    m = data.market(sym, era, c.get('period', 3600))
    s = Sim(m, c, start_t=ts(start) if start else None, end_t=ts(end) if end else None)
    tr = s.run()
    for x in tr:
        x["cfg"] = c["name"]
        x["era"] = era
    return tr, s.stat


def run_cfgs(cfgs, jobs=None, procs=4):
    """cfgs: список конфигураций. Возвращает DataFrame сделок по всем периодам."""
    if jobs is None:
        jobs = []
        for c in cfgs:
            for sym in data.SYMS_OLD:
                jobs.append((sym, "old", c, TRAIN[0], VALID[1]))
            for sym in data.SYMS_NEW:
                jobs.append((sym, "new", c, None, None))
    with Pool(procs) as p:
        res = p.map(one, jobs, chunksize=1)
    rows = [x for tr, _ in res for x in tr]
    df = pd.DataFrame(rows)
    if len(df):
        df["date"] = pd.to_datetime(df["t_open"], unit="s")
        df["part"] = np.where(df["era"] == "new", "hold",
                              np.where(df["date"] < TRAIN[1], "train", "valid"))
    return df


def summary(df):
    g = df.groupby(["cfg", "part"])["R"]
    out = g.agg(n="count", meanR="mean", sumR="sum").unstack("part")
    return out


if __name__ == "__main__":
    from sim import V123, V129
    t0 = time.time()
    df = run_cfgs([V123, V129])
    print(summary(df).round(3))
    print("time", round(time.time() - t0, 1))
