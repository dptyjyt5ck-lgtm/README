"""Таблицы для отчёта из trades.pkl: сетка TRAIN, выбор, VALID/HOLD, разбивки, помесячная статистика.

Запуск:  python3 report.py <папка с trades.pkl>
"""
import os
import sys

import numpy as np
import pandas as pd

import common as C

D = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "out")
tr = pd.read_pickle(os.path.join(D, "trades.pkl"))
dirs = pd.read_pickle(os.path.join(D, "f5_dirs.pkl"))
FAMS = ["F1", "F2", "F3", "F4", "F5"]


def f(x, nd=3):
    return "—" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:+.{nd}f}"


def pct(x):
    return "—" if x is None or np.isnan(x) else f"{100 * x:.1f}"


def row(st):
    return f"{st['n']} | {f(st['mean'])} | {f(st['t'], 2)} | {pct(st['win'])} | {st['pf']:.2f}" if st["n"] else "0 | — | — | — | —"


lines = []
P = lines.append
summary = []
for fam in FAMS:
    a = tr[tr.fam == fam]
    P(f"\n### {fam}\n")
    P("Сетка на TRAIN (все инструменты вместе):\n")
    P("| Вариант | сделок | R/сделку | t | винрейт % | PF |")
    P("|---|---|---|---|---|---|")
    best, bt = None, -np.inf
    for var, g in a[a.part == "train"].groupby("var", sort=False):
        st = C.stats(g.R)
        P(f"| {var} | {row(st)} |")
        if st["mean"] > 0 and st["t"] > bt:
            best, bt = var, st["t"]
    if best is None:                       # ни одного плюса на TRAIN — для справки берём лучший по t
        g = a[a.part == "train"].groupby("var").R.agg(lambda r: C.stats(r)["t"])
        best = g.idxmax()
        P(f"\nНа TRAIN нет варианта с R > 0; для справки взят лучший по t: **{best}**.")
    else:
        P(f"\nВыбран на TRAIN: **{best}**.")
    s = a[a["var"] == best]
    P("\n| Отрезок | сделок | R/сделку | t | винрейт % | PF | мес. в плюсе % | средний мес. % | худший мес. % | макс. просадка % | CAGR % | Шарп |")
    P("|---|---|---|---|---|---|---|---|---|---|---|---|")
    res = {}
    for part in ("train", "valid", "hold"):
        g = s[s.part == part]
        st = C.stats(g.R)
        pf = C.portfolio(g[["t_in", "t_out", "R"]].reset_index(drop=True))
        res[part] = (st, pf)
        if pf:
            P(f"| {part} | {row(st)} | {pct(pf['pos'])} | {pct(pf['avg'])} | {pct(pf['worst'])} | {pct(pf['maxdd'])} | "
              f"{pct(pf['cagr'])} | {pf['sharpe']:.2f} |")
        else:
            P(f"| {part} | 0 | | | | | | | | | | |")
    # по инструментам
    P("\nПо инструментам (R/сделку, в скобках число сделок):\n")
    P("| Инструмент | TRAIN | VALID | HOLD |")
    P("|---|---|---|---|")
    pos_valid, n_valid = 0, 0
    for sym in C.SYMS:
        cells = []
        for part in ("train", "valid", "hold"):
            g = s[(s.sym == sym) & (s.part == part)]
            cells.append(f"{f(g.R.mean())} ({len(g)})" if len(g) else "—")
            if part == "valid" and len(g):
                n_valid += 1; pos_valid += g.R.mean() > 0
        P(f"| {sym} | " + " | ".join(cells) + " |")
    # по годам
    yr = pd.to_datetime(s.t_in, unit="s").dt.year
    P("\nПо годам (R/сделку, сделок):\n")
    P("| " + " | ".join(str(y) for y in sorted(yr.unique())) + " |")
    P("|" + "---|" * yr.nunique())
    P("| " + " | ".join(f"{f(g.mean(), 2)} ({len(g)})" for _, g in s.R.groupby(yr)) + " |")
    # критерий
    stv, pfv = res["valid"]
    sth, _ = res["hold"]
    c1 = stv["n"] > 0 and stv["mean"] > 0 and (stv["t"] >= 2 or (pfv and pfv["sharpe"] >= 0.5))
    c2 = n_valid > 0 and pos_valid / n_valid >= 0.6
    c3 = sth["n"] == 0 or not (sth["t"] <= -1)
    ok = c1 and c2 and c3
    P(f"\nКритерий: VALID R>0 и t≥2 (или Шарп≥0,5) — {'да' if c1 else 'нет'}; "
      f"плюс на ≥60 % инструментов — {pos_valid}/{n_valid} — {'да' if c2 else 'нет'}; "
      f"HOLD не явно отрицательный — {'да' if c3 else 'нет'}. **Итог: {'ПРОШЛО' if ok else 'НЕ ПРОШЛО'}**.")
    summary.append((fam, best, res, pos_valid, n_valid, ok))

P("\n### Сводка\n")
P("| Семейство | выбранный вариант | TRAIN R (t) | VALID R (t) | VALID: инструм. в плюсе | HOLD R (t) | Итог |")
P("|---|---|---|---|---|---|---|")
for fam, best, res, pv, nv, ok in summary:
    c = [f"{f(res[p][0]['mean'])} ({f(res[p][0]['t'], 1)}, n={res[p][0]['n']})" for p in ("train", "valid", "hold")]
    P(f"| {fam} | {best} | {c[0]} | {c[1]} | {pv}/{nv} | {c[2]} | {'прошло' if ok else 'не прошло'} |")

P("\nF5: направление окон, выбранное на TRAIN (+1 покупка, −1 продажа, 0 — |t|<2, не торгуем):\n")
P("| Инструмент | " + " | ".join(F for F in ["W1 00–07", "W2 07–12", "W3 12–16", "W4 16–21"]) + " |")
P("|---|---|---|---|---|")
for sym in C.SYMS:
    P(f"| {sym} | " + " | ".join(f"{d[0]:+d} (t={d[1]:+.1f})" for d in dirs[sym].values()) + " |")

txt = "\n".join(lines)
open(os.path.join(D, "results.md"), "w").write(txt)
print(txt)
