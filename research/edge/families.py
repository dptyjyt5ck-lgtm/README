"""Пять заранее заявленных семейств (см. REPORT.md, «Поиск стратегии с реальным перевесом»).

Каждая функция возвращает список сделок: dict(t_in, t_out, buy, R).
Цены в данных — bid; ask = bid + спред. Покупка входит по ask и выходит по bid, продажа — наоборот.
R = результат после спреда / начальный риск (расстояние от цены входа до стопа).
"""
import numpy as np
import pandas as pd

from common import SPREAD, atr, daily, ema_w, m15, rsi

MONTH = 30.44 * 86400


# ====================================================================== дневные системы
class Pos:
    """Одна открытая позиция на дневных свечах."""

    def __init__(self, d, s, out):
        self.t, self.o, self.h, self.l, self.c = d.t.values, d.o.values, d.h.values, d.l.values, d.c.values
        self.s = s
        self.out = out
        self.dir = 0

    def open(self, i, dir_, risk):
        self.dir = dir_
        self.entry = self.o[i] + self.s if dir_ > 0 else self.o[i]
        self.risk = risk
        self.stop = self.entry - risk if dir_ > 0 else self.entry + risk   # long: уровень bid, short: уровень ask
        self.i_in = i
        self.ext = self.entry                                              # для трейлинга

    def _close(self, i, px_exit):
        R = (px_exit - self.entry) * self.dir / self.risk
        self.out.append(dict(t_in=int(self.t[self.i_in]), t_out=int(self.t[i]), buy=self.dir > 0, R=R))
        self.dir = 0

    def exit_open(self, i):
        self._close(i, self.o[i] if self.dir > 0 else self.o[i] + self.s)

    def exit_close(self, i):
        self._close(i, self.c[i] if self.dir > 0 else self.c[i] + self.s)

    def check_stop(self, i):
        """Стоп внутри дня; при гэпе — исполнение по открытию."""
        if self.dir > 0 and self.l[i] <= self.stop:
            self._close(i, min(self.o[i], self.stop) if i > self.i_in else self.stop)
            return True
        if self.dir < 0 and self.h[i] + self.s >= self.stop:
            self._close(i, max(self.o[i] + self.s, self.stop) if i > self.i_in else self.stop)
            return True
        return False


def f1_tsmom(sym, era, L, k):
    """F1: знак изменения цены за L месяцев; стоп k·ATR(20); переворот при смене знака."""
    d = daily(sym, era)
    t, c, warm = d.t.values, d.c.values, d.warm.values
    A = atr(d)
    j = np.searchsorted(t, t - L * MONTH, side="right") - 1
    sig = np.where(j >= 0, np.sign(c - c[np.maximum(j, 0)]), 0)
    out = []
    p = Pos(d, SPREAD[sym], out)
    blocked = 0
    for i in range(1, len(t)):
        s = sig[i - 1]
        if s != blocked:
            blocked = 0
        if p.dir and s == -p.dir:
            p.exit_open(i)
        if not p.dir and s != 0 and s != blocked and not warm[i] and A[i - 1] > 0:
            p.open(i, int(s), k * A[i - 1])
        if p.dir and p.check_stop(i):
            blocked = s
    if p.dir:
        p.exit_close(len(t) - 1)
    return out


def f2_ema(sym, era, fast, slow, m):
    """F2: пересечение EMA; начальный и скользящий стоп m·ATR от экстремального закрытия."""
    d = daily(sym, era)
    t, c, w, warm = d.t.values, d.c.values, d.w.values, d.warm.values
    A = atr(d)
    side = np.sign(ema_w(c, fast, w) - ema_w(c, slow, w))
    out = []
    p = Pos(d, SPREAD[sym], out)
    for i in range(2, len(t)):
        cross = side[i - 1] != side[i - 2] and side[i - 1] != 0
        if cross and p.dir and side[i - 1] == -p.dir:
            p.exit_open(i)
        if cross and not p.dir and not warm[i] and not warm[i - 1] and A[i - 1] > 0:
            p.open(i, int(side[i - 1]), m * A[i - 1])
        if p.dir and not p.check_stop(i):
            # трейлинг по закрытию дня (действует со следующего дня)
            if p.dir > 0:
                p.ext = max(p.ext, c[i]); p.stop = max(p.stop, p.ext - m * A[i])
            else:
                p.ext = min(p.ext, c[i]); p.stop = min(p.stop, p.ext + m * A[i])
    if p.dir:
        p.exit_close(len(t) - 1)
    return out


def f3_rsi2(sym, era, th, filt, exit_):
    """F3: RSI(2) < θ — покупка (> 100−θ — продажа); фильтр EMA(200); выход SMA(5) или 5 дней; стоп 3·ATR."""
    d = daily(sym, era)
    t, c, w, warm = d.t.values, d.c.values, d.w.values, d.warm.values
    A = atr(d)
    r = rsi(c, 2)
    e200 = ema_w(c, 200, w)
    sma5 = pd.Series(c).rolling(5).mean().values
    out = []
    p = Pos(d, SPREAD[sym], out)
    for i in range(1, len(t)):
        k = i - 1                                   # решение по закрытию вчерашнего дня
        if p.dir:
            if exit_ == "sma5" and ((p.dir > 0 and c[k] > sma5[k]) or (p.dir < 0 and c[k] < sma5[k])):
                p.exit_open(i)
            elif exit_ == "5d" and i - p.i_in >= 5:
                p.exit_open(i)
        if not p.dir and not warm[i] and not warm[k] and A[k] > 0 and k >= 5:
            up = (not filt) or c[k] > e200[k]
            dn = (not filt) or c[k] < e200[k]
            if r[k] < th and up:
                p.open(i, 1, 3 * A[k])
            elif r[k] > 100 - th and dn:
                p.open(i, -1, 3 * A[k])
        if p.dir:
            p.check_stop(i)
    if p.dir:
        p.exit_close(len(t) - 1)
    return out


# ====================================================================== внутридневные (M15, время Лондона)
_lon = {}


def london_days(sym, era):
    """M15 + разметка по лондонскому времени; ATR(20) дневной на начало лондонских суток."""
    key = (sym, era)
    if key in _lon:
        return _lon[key]
    t, o, h, l, c = m15(sym, era)
    loc = pd.to_datetime(t, unit="s").tz_localize("UTC").tz_convert("Europe/London")
    mins = (loc.hour * 60 + loc.minute).values
    date = loc.tz_localize(None).normalize().values.astype("datetime64[D]").astype(np.int64)
    wd = loc.dayofweek.values
    d = daily(sym, era)
    A = atr(d)
    dt = d.t.values
    starts = np.flatnonzero(np.r_[True, date[1:] != date[:-1]])
    ends = np.r_[starts[1:], len(t)]
    days = []
    for a, b in zip(starts, ends):
        if wd[a] >= 5:
            continue
        t0 = t[a] - mins[a] * 60                    # приблизительно 00:00 по Лондону
        q = np.searchsorted(dt, t0, side="right") - 2   # последний закрытый торговый день
        if q < 20:
            continue
        days.append((a, b, A[q]))
    r = (t, o, h, l, c, mins, days)
    _lon[key] = r
    return r


def f4_london(sym, era, stop_mode, tgt, narrow):
    """F4: пробой диапазона 00:00–07:00 Лондона стоп-ордерами 07:00–12:00; выход 16:00."""
    t, o, h, l, c, mins, days = london_days(sym, era)
    s = SPREAD[sym]
    out = []
    ratios = []
    for a, b, A in days:
        mm = mins[a:b]
        rng = np.flatnonzero(mm < 420) + a
        win = np.flatnonzero((mm >= 420) & (mm < 720)) + a
        if len(rng) < 20 or len(win) < 12:
            continue
        RH, RL = h[rng].max(), l[rng].min()
        ratio = (RH - RL) / A
        med = np.median(ratios[-100:]) if len(ratios) >= 20 else None
        ratios.append(ratio)
        if narrow and (med is None or ratio >= med):
            continue
        if RH - RL <= 2 * s:
            continue
        exit_j = np.flatnonzero(mm >= 960)
        last = (exit_j[0] + a) if len(exit_j) else b       # индекс бара выхода (по открытию) или конец дня
        dir_ = 0
        for j in win:
            up, dn = h[j] >= RH, l[j] <= RL
            if not (up or dn):
                continue
            dir_ = 1 if up else -1
            both = up and dn
            if dir_ > 0:
                entry = max(o[j], RH) + s
                stop = RL if stop_mode == "edge" else (RH + RL) / 2
                risk = entry - stop
            else:
                entry = min(o[j], RL)
                stop = (RH if stop_mode == "edge" else (RH + RL) / 2) + s
                risk = stop - entry
            target = entry + dir_ * tgt * risk if tgt else None
            R = None
            # бар входа: если в нём же достижим стоп — считаем стоп (худший исход); цель в баре входа не берём
            if both or (dir_ > 0 and l[j] <= stop) or (dir_ < 0 and h[j] + s >= stop):
                R = -1.0
            else:
                for q in range(j + 1, last):
                    if dir_ > 0:
                        if l[q] <= stop:
                            R = (min(o[q], stop) - entry) / risk; break
                        if target is not None and h[q] >= target:
                            R = (max(o[q], target) - entry) / risk; break
                    else:
                        if h[q] + s >= stop:
                            R = (entry - max(o[q] + s, stop)) / risk; break
                        if target is not None and l[q] + s <= target:
                            R = (entry - min(o[q] + s, target)) / risk; break
                if R is None:
                    px = o[last] if last < b else c[b - 1]
                    px = px if dir_ > 0 else px + s
                    R = (px - entry) * dir_ / risk
            out.append(dict(t_in=int(t[j]), t_out=int(t[min(last, b - 1)]), buy=dir_ > 0, R=R))
            break
    return out


WINDOWS = dict(W1=(0, 420), W2=(420, 720), W3=(720, 960), W4=(960, 1260))


def f5_window(sym, era, win, k, dir_):
    """F5: держим позицию dir_ в окне win (лондонское время); стоп k·ATR(D1).
    dir_=0 — «сырые» доходности окна без издержек (для выбора направления на TRAIN)."""
    t, o, h, l, c, mins, days = london_days(sym, era)
    s = SPREAD[sym]
    a0, b0 = WINDOWS[win]
    out = []
    for a, b, A in days:
        mm = mins[a:b]
        ii = np.flatnonzero((mm >= a0) & (mm < b0))
        if len(ii) < (b0 - a0) // 15 - 4 or mm[ii[0]] > a0 + 30:
            continue
        j0 = ii[0] + a
        nxt = np.flatnonzero(mm >= b0)
        if not len(nxt):
            continue
        j1 = nxt[0] + a
        if dir_ == 0:
            out.append(dict(t_in=int(t[j0]), t_out=int(t[j1]), buy=True, R=(o[j1] - o[j0]) / A))
            continue
        risk = k * A
        entry = o[j0] + s if dir_ > 0 else o[j0]
        stop = entry - risk if dir_ > 0 else entry + risk
        R = None
        for q in range(j0, j1):
            if dir_ > 0 and l[q] <= stop:
                R = (min(o[q], stop) - entry) / risk; break
            if dir_ < 0 and h[q] + s >= stop:
                R = (entry - max(o[q] + s, stop)) / risk; break
        if R is None:
            px = o[j1] if dir_ > 0 else o[j1] + s
            R = (px - entry) * dir_ / risk
        out.append(dict(t_in=int(t[j0]), t_out=int(t[j1]), buy=dir_ > 0, R=R))
    return out


# ====================================================================== сетки
def grid():
    g = []
    for L in (1, 3, 6, 12):
        for k in (3, 6):
            g.append(("F1", f"L={L}м k={k}", f1_tsmom, dict(L=L, k=k)))
    for fs in ((10, 50), (20, 100), (50, 200)):
        for m in (3, 5):
            g.append(("F2", f"EMA{fs[0]}/{fs[1]} m={m}", f2_ema, dict(fast=fs[0], slow=fs[1], m=m)))
    for th in (5, 10, 20):
        for filt in (True, False):
            for ex in ("sma5", "5d"):
                g.append(("F3", f"θ={th} {'EMA200' if filt else 'без фильтра'} {ex}", f3_rsi2,
                          dict(th=th, filt=filt, exit_=ex)))
    for sm in ("edge", "mid"):
        for tg in (1.0, 2.0, None):
            for nar in (True, False):
                g.append(("F4", f"стоп={'граница' if sm == 'edge' else 'середина'} цель={tg or 'нет'} "
                                f"{'узкий' if nar else 'любой'}", f4_london, dict(stop_mode=sm, tgt=tg, narrow=nar)))
    for w in WINDOWS:
        for k in (0.5, 1.0):
            g.append(("F5", f"{w} k={k}", f5_window, dict(win=w, k=k)))
    return g
