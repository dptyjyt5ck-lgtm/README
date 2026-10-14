"""Событийный разбор: все фигуры A→B (фильтры v1.23) и путь цены после них в единицах сетки.

u = (цена − A) / (B − A): A = 0, B = 1, лимитки 0,618…0,14, стоп −0,14, цель 1,618.
Рост u — всегда в сторону сделки (и для покупок, и для продаж).
"""
import numpy as np
import pandas as pd

import data
from sim import Sim, cfg

HORIZON = 96 * 20      # 20 суток M15


class Rec(Sim):
    def __init__(self, m, c):
        super().__init__(m, c)
        self.rec = []

    def process_h1(self, i, bid, ask):
        n0 = len(self.setups)
        super().process_h1(i, bid, ask)
        if len(self.setups) > n0:
            s = self.setups[-1]
            s["alive"] = False          # не торгуем, только запоминаем
            m = self.m
            imp = s["B"] - s["A"]
            p = self.zz
            prev = p[-3][2] if len(p) >= 3 else np.nan
            # тренд перед A: размер хода в ATR за окно
            lo = max(0, s["aIdx"] - self.c["extreme_hours"])
            seg_h, seg_l = m.H_h[lo:s["aIdx"] + 1], m.H_l[lo:s["aIdx"] + 1]
            trend = (s["A"] - seg_l.min()) if imp < 0 else (seg_h.max() - s["A"])
            # дневной тренд: цена закрытия vs средняя за 20 суток
            d0 = max(0, i - 480)
            sma = m.H_c[d0:i + 1].mean()
            self.rec.append(dict(
                sym=m.sym, i=i, t=int(m.H_t[i]), bar=int(m.h1_start[i + 1]) if i + 1 < len(m.h1_start) else -1,
                buy=s["buy"], A=s["A"], B=s["B"], imp=abs(imp), atr=m.ATR[i],
                impATR=abs(imp) / m.ATR[i], trendATR=trend / m.ATR[s["aIdx"]],
                abBars=s["bIdx"] - s["aIdx"], confBars=i - s["bIdx"],
                bos=(s["B"] < prev) if imp < 0 else (s["B"] > prev),
                with_sma=((m.H_c[i] > sma) == s["buy"]),
                hour=int((m.H_t[i] // 3600) % 24), wd=int(((m.H_t[i] // 86400) + 3) % 7),
                spr_u=m.spread / abs(imp)))


def collect(c, syms_eras):
    out = []
    paths = []
    for sym, era in syms_eras:
        m = data.market(sym, era)
        r = Rec(m, c)
        r.run()
        for e in r.rec:
            b = e["bar"]
            if b < 0:
                continue
            e["era"] = era
            hi = m.h[b:b + HORIZON]; lo = m.l[b:b + HORIZON]
            d = e["B"] - e["A"]
            u_hi = ((hi if e["buy"] else lo) - e["A"]) / d
            u_lo = ((lo if e["buy"] else hi) - e["A"]) / d
            # первый тик бара (open) учтён в hi/lo; для продаж bid->ask сдвиг учитываем как издержку
            pu = np.full((2, HORIZON), np.nan, dtype=np.float32)
            pu[0, :len(u_hi)] = u_hi; pu[1, :len(u_lo)] = u_lo
            out.append(e); paths.append(pu)
    return pd.DataFrame(out), np.stack(paths)


def first_idx(mask):
    """Индекс первого True по оси 1, иначе большое число."""
    any_ = mask.any(axis=1)
    idx = mask.argmax(axis=1)
    return np.where(any_, idx, 10**9)


def eval_rule(P, ev, L, S, T, be=None, max_bars=HORIZON):
    """Одна лимитка на уровне L, стоп S, цель T (всё в единицах сетки). Возвращает R за сделку (nan = нет входа).
    Отмена лимитки, если цена ушла за B (u ≥ 1) до входа. Бар с одновременным стопом и целью — стоп (хуже)."""
    hi, lo = P[:, 0, :max_bars], P[:, 1, :max_bars]
    spr = ev["spr_u"].values
    fill = first_idx(lo <= L - spr[:, None])
    cancel = first_idx(hi >= 1.0)
    entered = fill < np.minimum(cancel, 10**9)
    # отмена в том же баре, что и вход: считаем, что вход был (цена сначала шла к уровню) — консервативно
    entered |= (fill == cancel) & (fill < 10**9)
    R = np.full(len(ev), np.nan)
    risk = L - S
    n = hi.shape[1]
    cols = np.arange(n)
    for j in np.flatnonzero(entered):
        f = fill[j]
        h = hi[j, f:]; l = lo[j, f:]
        st = first_idx((l <= S)[None, :])[0]
        tg = first_idx((h >= T)[None, :])[0]
        if f + 0 == f and h.size and h[0] >= T and l[0] <= S:
            tg = 10**9  # тот же бар — стоп
        if be is not None:
            # после касания уровня be стоп в безубыток
            b = first_idx((h >= be)[None, :])[0]
            if b < min(st, tg):
                st2 = first_idx((l[b + 1:] <= L)[None, :])[0]
                st2 = st2 + b + 1 if st2 < 10**9 else 10**9
                if tg <= st2 and tg < 10**9:
                    R[j] = (T - L) / risk
                elif st2 < 10**9:
                    R[j] = 0.0
                else:
                    last = h[~np.isnan(h)]
                    R[j] = ((last[-1] if last.size else L) - L) / risk if last.size else 0.0
                R[j] -= spr[j] / risk
                continue
        if st < 10**9 and st <= tg:
            R[j] = -1.0
        elif tg < 10**9:
            R[j] = (T - L) / risk
        else:
            valid = ~np.isnan(l)
            lastc = (h[valid][-1] + l[valid][-1]) / 2 if valid.any() else L
            R[j] = (lastc - L) / risk
        R[j] -= spr[j] / risk
    return R


def eval_cont(P, ev, L, S, T, max_bars=HORIZON, cancel_u=1.0):
    """Обратная сделка: цена откатила к A до уровня L — входим ПО старому тренду (к A и дальше).
    Стоп S (> L, ближе к B), цель T (< 0, за точкой A). Отмена, если до входа цена ушла за B."""
    hi, lo = P[:, 0, :max_bars], P[:, 1, :max_bars]
    spr = ev["spr_u"].values
    fill = first_idx(lo <= L)
    cancel = first_idx(hi >= cancel_u)
    entered = (fill < cancel) & (fill < 10**9)
    R = np.full(len(ev), np.nan)
    risk = S - L
    for j in np.flatnonzero(entered):
        f = fill[j]
        h = hi[j, f:]; l = lo[j, f:]
        st = first_idx((h >= S - spr[j])[None, :])[0]
        tg = first_idx((l <= T - spr[j])[None, :])[0]
        if st < 10**9 and st <= tg:
            R[j] = -1.0
        elif tg < 10**9:
            R[j] = (L - T) / risk
        else:
            v = ~np.isnan(l)
            lastc = (h[v][-1] + l[v][-1]) / 2 if v.any() else L
            R[j] = (L - lastc) / risk
        R[j] -= spr[j] / risk
    return R


def eval_break(P, ev, Lr, T, stop_mode="swing", S_fixed=-0.14, max_bars=HORIZON):
    """Вход стоп-ордером на пробое B (u ≥ 1) после отката хотя бы до уровня Lr.
    Стоп: 'swing' — за минимумом отката (точка C), 'fixed' — на S_fixed. Цель T."""
    hi, lo = P[:, 0, :max_bars], P[:, 1, :max_bars]
    spr = ev["spr_u"].values
    R = np.full(len(ev), np.nan)
    for j in range(len(ev)):
        h = hi[j]; l = lo[j]
        rt = first_idx((l <= Lr)[None, :])[0]
        gone = first_idx((h >= 1.0)[None, :])[0]
        if rt >= 10**9 or gone < rt:
            continue
        e = first_idx((h[rt:] >= 1.0 + spr[j])[None, :])[0]
        if e >= 10**9:
            continue
        e += rt
        if e == rt:
            continue  # откат и пробой в одном баре — неясно, пропускаем
        swing = np.nanmin(l[rt:e])
        if swing <= S_fixed:
            continue  # откат дошёл до стопа фигуры — фигуры нет
        S = swing - 0.05 if stop_mode == "swing" else S_fixed
        L = 1.0 + spr[j]
        risk = L - S
        hh = h[e:]; ll = l[e:]
        st = first_idx((ll <= S)[None, :])[0]
        tg = first_idx((hh >= T)[None, :])[0]
        if st < 10**9 and st <= tg:
            R[j] = -1.0
        elif tg < 10**9:
            R[j] = (T - L) / risk
        else:
            v = ~np.isnan(ll)
            R[j] = (((hh[v][-1] + ll[v][-1]) / 2 if v.any() else L) - L) / risk
        R[j] -= spr[j] / risk
    return R
