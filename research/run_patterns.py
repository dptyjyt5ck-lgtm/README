"""Прогон стратегий S3/S4/S6/WY/DON по всем инструментам; итоги в R по отрезкам."""
import functools
import sys
from multiprocessing import Pool

import numpy as np
import pandas as pd

import data
import patterns as P

JOBS = [(s, "old") for s in data.SYMS_OLD] + [(s, "new") for s in data.SYMS_NEW]


def part_of(t, era):
    if era == "new":
        return "hold"
    d = pd.Timestamp(t, unit="s")
    if d < pd.Timestamp("2013-01-01"):
        return None
    return "train" if d < pd.Timestamp("2019-01-01") else "valid"


def run_zz(args):
    (sym, era), dets = args
    m = data.market(sym, era)
    sigs = P.ZZStream(m, dets).scan()
    rows = []
    for s in sigs:
        R = P.execute(m, s)
        if R is None:
            continue
        pt = part_of(int(m.H_t[s["i"]]), era)
        if pt:
            rows.append(dict(sym=sym, name=s["name"], part=pt, R=R, t=int(m.H_t[s["i"]]), buy=s["buy"]))
    return rows


def run_wy(args):
    (sym, era), kw, tag = args
    m = data.market(sym, era)
    rows = []
    for s in P.wyckoff_signals(m, **kw):
        R = P.execute(m, s)
        if R is None:
            continue
        pt = part_of(int(m.H_t[s["i"]]), era)
        if pt:
            rows.append(dict(sym=sym, name=tag, part=pt, R=R, t=int(m.H_t[s["i"]]), buy=s["buy"]))
    return rows


def run_don(args):
    (sym, era), kw, tag = args
    m = data.market(sym, era, 86400)
    rows = []
    for t_in, t_out, buy, R in P.donchian(m, **kw):
        pt = part_of(t_in, era)
        if pt:
            rows.append(dict(sym=sym, name=tag, part=pt, R=R, t=t_in, buy=buy))
    return rows


def table(df):
    g = df.groupby(["name", "part"])["R"].agg(["count", "mean"]).unstack("part")
    return g.round(3)


def pool_map(f, jobs):
    with Pool(4) as p:
        return [x for r in p.map(f, jobs, chunksize=1) for x in r]
