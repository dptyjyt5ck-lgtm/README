"""Общие функции поиска перевеса: загрузка данных в UTC, дневные свечи, статистика, портфель.

Время везде — секунды UTC. Дневная свеча — торговый день брокера (17:00 Нью-Йорка → 17:00),
как у MT5 с временем NY+7: пять свечей в неделю, без воскресных огрызков.
"""
import glob
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import data  # noqa: E402

SPREAD = data.SPREAD
SYMS = data.SYMS_OLD
DATA = data.DATA

TRAIN = ("2013-01-01", "2019-01-01")
VALID = ("2019-01-01", "2022-03-05")
HOLD_FX = ("2026-03-26", "2026-09-26")
HOLD_XAU = ("2022-03-05", "2026-09-01")


def ts(s):
    return int(pd.Timestamp(s).value // 10**9)


def split_of(t, sym, era):
    """Отрезок по времени входа: train / valid / hold / None."""
    if era == "old":
        if ts(TRAIN[0]) <= t < ts(TRAIN[1]):
            return "train"
        if ts(VALID[0]) <= t < ts(VALID[1]):
            return "valid"
        return None
    a, b = HOLD_XAU if sym == "XAUUSD" else HOLD_FX
    return "hold" if ts(a) <= t < ts(b) else None


# ------------------------------------------------------------------ загрузка M15 в UTC
def _broker_to_utc(t):
    """Время брокера (NY+7) → UTC с учётом перехода на летнее время в США."""
    d = pd.to_datetime(t, unit="s") - pd.Timedelta(hours=7)
    u = d.tz_localize("America/New_York", ambiguous="NaT", nonexistent="shift_forward").tz_convert("UTC")
    u = u.tz_localize(None)
    ok = ~u.isna()
    return u.values.astype("datetime64[s]").astype(np.int64), np.asarray(ok)


def _xau_hold_m15():
    """Золото M1 (bid, UTC) 2021-09 … 2026-09 → M15."""
    fs = sorted(glob.glob(os.path.join(DATA, "xau_m1", "*.csv")))
    df = pd.concat([pd.read_csv(f, usecols=[0, 1, 2, 3, 4]) for f in fs])
    t = pd.to_datetime(df["timestamp"]).values.astype("datetime64[s]").astype(np.int64)
    k = t - t % 900
    g = pd.DataFrame(dict(k=k, o=df.open_bid.values, h=df.high_bid.values, l=df.low_bid.values,
                          c=df.close_bid.values)).groupby("k", sort=True)
    a = g.agg(o=("o", "first"), h=("h", "max"), l=("l", "min"), c=("c", "last"))
    a = a[~a.index.duplicated()]
    return a.index.values.astype(np.int64), a.o.values, a.h.values, a.l.values, a.c.values


_cache = {}


def m15(sym, era):
    """(t_utc, o, h, l, c) M15. era: 'old' (ejtrader, 2012–2022) или 'new' (2026; золото 2021–2026)."""
    key = (sym, era)
    if key in _cache:
        return _cache[key]
    if era == "old":
        t, o, h, l, c = data.load_raw(sym, "old")
        u, ok = _broker_to_utc(t)
        r = (u[ok], o[ok], h[ok], l[ok], c[ok])
    elif sym == "XAUUSD":
        r = _xau_hold_m15()
    else:
        r = data.load_raw(sym, "new")
    _cache[key] = r
    return r


# ------------------------------------------------------------------ дневные свечи
def day_key(t_utc):
    """Номер торгового дня брокера: дата по (Нью-Йорк + 7 ч)."""
    d = pd.to_datetime(t_utc, unit="s").tz_localize("UTC").tz_convert("America/New_York") + pd.Timedelta(hours=7)
    return d.tz_localize(None).normalize().values.astype("datetime64[D]").astype(np.int64)


def daily(sym, era):
    """Дневные свечи. Возвращает DataFrame: t (UTC начала дня), o,h,l,c, w (сколько торговых дней в свече),
    warm (True — свеча только для разогрева индикаторов)."""
    t, o, h, l, c = m15(sym, era)
    k = day_key(t)
    df = pd.DataFrame(dict(k=k, t=t, o=o, h=h, l=l, c=c))
    g = df.groupby("k", sort=True).agg(t=("t", "first"), o=("o", "first"), h=("h", "max"),
                                         l=("l", "min"), c=("c", "last"), n=("t", "size"))
    g = g[g.n >= 8]                     # отбрасываем огрызки (< 2 часов торговли)
    d = pd.DataFrame(dict(t=g.t.values, o=g.o.values, h=g.h.values, l=g.l.values, c=g.c.values))
    d["w"] = 1.0
    d["warm"] = False
    if era == "new":
        d = _prepend_warmup(sym, d)
    return d.reset_index(drop=True)


def _prepend_warmup(sym, d):
    """Для HOLD: дорисовать историю до начала выборки (только для индикаторов)."""
    t0 = d.t.iloc[0]
    if sym == "XAUUSD":
        old = daily(sym, "old")
        old = old[old.t < t0].copy()
        old["warm"] = True
        return pd.concat([old, d])
    f = os.path.join(DATA, "gdw", f"{sym.lower()}_1w.csv")
    if not os.path.exists(f):
        return d
    w = pd.read_csv(f)
    wt = pd.to_datetime(w["datetime"], utc=True).dt.tz_localize(None).values.astype("datetime64[s]").astype(np.int64)
    m = wt + 7 * 86400 <= t0           # только полностью закрытые недели до начала выборки
    ww = pd.DataFrame(dict(t=wt[m], o=w.open.values[m], h=w.high.values[m], l=w.low.values[m],
                           c=w.close.values[m], w=5.0, warm=True))
    return pd.concat([ww, d])


# ------------------------------------------------------------------ индикаторы
def ema_w(x, n, w):
    """EMA с учётом «веса» свечи: недельная свеча = 5 шагов дневной EMA."""
    a = 2.0 / (n + 1)
    out = np.empty(len(x))
    e = x[0]
    for i in range(len(x)):
        aa = 1 - (1 - a) ** w[i]
        e = e + aa * (x[i] - e)
        out[i] = e
    return out


def atr(d, n=20):
    """ATR по дневным свечам (недельные — делим размах на √5)."""
    h, l, c, w = d.h.values, d.l.values, d.c.values, d.w.values
    pc = np.r_[c[0], c[:-1]]
    tr = (np.maximum(h, pc) - np.minimum(l, pc)) / np.sqrt(w)
    return pd.Series(tr).rolling(n, min_periods=5).mean().values


def rsi(c, n=2):
    dc = np.diff(c, prepend=c[0])
    up = pd.Series(np.maximum(dc, 0)).ewm(alpha=1 / n, adjust=False).mean().values
    dn = pd.Series(np.maximum(-dc, 0)).ewm(alpha=1 / n, adjust=False).mean().values
    return 100 - 100 / (1 + up / np.maximum(dn, 1e-12))


# ------------------------------------------------------------------ статистика
def stats(R):
    R = np.asarray(R, float)
    n = len(R)
    if n == 0:
        return dict(n=0, mean=np.nan, t=np.nan, win=np.nan, pf=np.nan)
    sd = R.std(ddof=1) if n > 1 else np.nan
    g, b = R[R > 0].sum(), -R[R < 0].sum()
    return dict(n=n, mean=R.mean(), t=R.mean() / sd * np.sqrt(n) if sd and sd > 0 else np.nan,
                win=(R > 0).mean(), pf=g / b if b > 0 else np.inf)


def portfolio(tr, start=1000.0, risk=0.01):
    """Сделки (t_in, t_out, R) → помесячная доходность счёта при риске risk от текущего счёта на сделку.
    Размер фиксируется на входе по счёту из уже закрытых сделок; результат — на выходе."""
    if len(tr) == 0:
        return None
    tr = tr.sort_values("t_in").reset_index(drop=True)
    ev = []                                           # (время, тип, номер): 0 = выход, 1 = вход
    for i, r in tr.iterrows():
        ev.append((r.t_in, 1, i)); ev.append((r.t_out, 0, i))
    ev.sort()
    eq = start; size = {}; done = set(); pts = [(tr.t_in.min() - 1, eq)]
    for t, kind, i in ev:
        if kind == 1:
            if i not in done:
                size[i] = eq * risk
        else:
            eq += size.pop(i, eq * risk) * tr.R[i]   # если выход совпал со входом — размер по текущему счёту
            done.add(i)
            pts.append((t, eq))
    s = pd.Series([p[1] for p in pts], index=pd.to_datetime([p[0] for p in pts], unit="s"))
    me = s.resample("ME").last().ffill()
    first = pd.Series([start], index=[me.index[0] - pd.offsets.MonthEnd(1)])
    me = pd.concat([first, me])
    ret = me.pct_change().dropna()
    dd = (s / s.cummax() - 1).min()
    yrs = max((s.index[-1] - s.index[0]).days / 365.25, 1 / 12)
    return dict(months=len(ret), pos=(ret > 0).mean(), avg=ret.mean(), worst=ret.min(),
                maxdd=dd, cagr=(s.iloc[-1] / start) ** (1 / yrs) - 1,
                sharpe=ret.mean() / ret.std() * np.sqrt(12) if ret.std() > 0 else np.nan,
                end=s.iloc[-1], ret=ret)
