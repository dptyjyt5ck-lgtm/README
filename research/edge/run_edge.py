"""Прогон пяти заявленных семейств: сетка на TRAIN, выбор, VALID и HOLD без перенастройки.

Запуск:  ZZ_DATA=... python3 run_edge.py [папка_для_результатов]   (EDGE_NOSPREAD=1 — без спреда)
Пишет trades.pkl (все сделки) и results.md (таблицы для отчёта).
"""
import os
import sys
from multiprocessing import Pool

import numpy as np
import pandas as pd

import common as C
import families as F

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "out")
GRID = F.grid()
if os.environ.get("EDGE_NOSPREAD"):          # проверка «до издержек»: спред = 0
    for k in C.SPREAD:
        C.SPREAD[k] = 0.0
NEW_SYMS = [s for s in C.SYMS if s in C.data.SYMS_NEW or s == "XAUUSD"]


def tag(rows, fam, name, sym, era):
    for r in rows:
        r.update(fam=fam, var=name, sym=sym, era=era, part=C.split_of(r["t_in"], sym, era))
    return [r for r in rows if r["part"]]


def f5_dirs(sym):
    """Направление и допуск для F5 по TRAIN: знак среднего «сырого» результата окна, |t| ≥ 2."""
    res = {}
    for w in F.WINDOWS:
        tr = pd.DataFrame(F.f5_window(sym, "old", w, 1.0, 0))
        tr = tr[[C.split_of(x, sym, "old") == "train" for x in tr.t_in]]
        st = C.stats(tr.R)
        res[w] = (int(np.sign(st["mean"])) if abs(st["t"]) >= 2 else 0, st["t"])
    return res


def work(args):
    sym, era, dirs = args
    rows = []
    for fam, name, fn, kw in GRID:
        if fam == "F5":
            d = dirs[sym][kw["win"]][0]
            if d == 0:
                continue
            rows += tag(fn(sym, era, dir_=d, **kw), fam, name, sym, era)
        else:
            rows += tag(fn(sym, era, **kw), fam, name, sym, era)
    return rows


def main():
    os.makedirs(OUT, exist_ok=True)
    with Pool(4) as p:
        dl = p.map(f5_dirs, C.SYMS)
        dirs = dict(zip(C.SYMS, dl))
        jobs = [(s, "old", dirs) for s in C.SYMS] + [(s, "new", dirs) for s in NEW_SYMS]
        rows = [r for part in p.map(work, jobs, chunksize=1) for r in part]
    tr = pd.DataFrame(rows)
    tr.to_pickle(os.path.join(OUT, "trades.pkl"))
    pd.to_pickle(dirs, os.path.join(OUT, "f5_dirs.pkl"))
    print(len(tr), "сделок")


if __name__ == "__main__":
    main()
