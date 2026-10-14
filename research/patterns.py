"""Остальные стратегии: сигналы на закрытых H1-свечах и простой исполнитель заявок на M15.

Каждый сигнал — независимая «бумажная» сделка (без ограничения «одна позиция»), чтобы мерить
перевес самой фигуры. R считается от риска при исполнении всех лимиток.

Стратегии (правила — из «ВСЕ_СТРАТЕГИИ.md» и «стратегии поэтапно.docx»):
  S3  — глубокая коррекция XA (AB = 0,5–0,70 XA); лимитки A − r·XA (r = 0,14/0,236/0,382);
        стоп A + 0,14·XA; цель 0,786 XA (= 1,272 AB).
  S4  — «перехай»: B за X на 1,13–1,618 XA; лимитки B − r·AB; стоп B + 0,14·AB; цель 1,618 AB.
  S6  — бабочка: AB = 0,236–0,5 XA; лимитки A + r·(B − A) (r = 0,14/0,236/0,382/0,5); стоп A + 0,14·AB;
        цель D = 1,618 XA от A.
  WY  — спринг/аптраст Вайкоффа: ложный выход за границу боковика и закрытие обратно внутри.
  DON — пробой канала на D1 (не из курса, для сравнения).
"""
import numpy as np

from sim import Sim

LV3 = (0.14, 0.236, 0.382)


# ---------------------------------------------------------------- зигзаг-поток
class ZZStream(Sim):
    """Инкрементальный ZigZag(3,1) как в советнике; на каждом изменении — вызов детекторов."""

    def __init__(self, m, detectors, left=3, right=1):
        super().__init__(m, dict(zz_left=left, zz_right=right))
        self.dets = detectors
        self.sig = []
        self.keys = set()

    def scan(self):
        m = self.m
        for i in range(300, len(m.H_t) - 1):
            if self.zz_update(i) == 0:
                continue
            for d in self.dets:
                for s in d(self.zz, i, m):
                    k = (s["name"],) + s["key"]
                    if k in self.keys:
                        continue
                    self.keys.add(k)
                    s["i"] = i
                    self.sig.append(s)
        return self.sig


def _big(zz, i, m, min_leg):
    X, A, B = zz[-3], zz[-2], zz[-1]
    return max(abs(A[2] - X[2]), abs(B[2] - A[2])) >= min_leg * m.ATR[i]


def _sig(name, key, buy, entries, weights, stop, target, cancel=None, expiry=120):
    return dict(name=name, key=key, buy=buy, entries=list(entries), weights=list(weights),
                stop=stop, target=target, cancel=cancel if cancel is not None else target, expiry=expiry)


def det_s3(zz, i, m, min_leg=0.0, lo=0.5, hi=0.70, tgt=0.786):
    if len(zz) < 3:
        return []
    X, A, B = zz[-3], zz[-2], zz[-1]
    xa = A[2] - X[2]
    if xa == 0 or not _big(zz, i, m, min_leg):
        return []
    r = (A[2] - B[2]) / xa
    if not (lo <= r <= hi):
        return []
    buy = xa < 0            # A — минимум: покупаем у A
    ent = [A[2] - k * xa for k in LV3]
    return [_sig("S3", (X[1], A[1], B[1]), buy, ent, [1 / 3] * 3, A[2] + 0.14 * xa, A[2] - tgt * xa)]


def det_s4(zz, i, m, min_leg=0.0, lo=1.13, hi=1.618, tgt=1.618):
    if len(zz) < 3:
        return []
    X, A, B = zz[-3], zz[-2], zz[-1]
    xa = X[2] - A[2]
    ab = B[2] - A[2]
    if xa == 0 or not _big(zz, i, m, min_leg):
        return []
    r = ab / xa
    if not (lo <= r <= hi):
        return []
    buy = ab < 0            # B — новый минимум ниже X: покупка
    ent = [B[2] - k * ab for k in LV3]
    return [_sig("S4", (X[1], A[1], B[1]), buy, ent, [1 / 3] * 3, B[2] + 0.14 * ab, B[2] - tgt * ab)]


def det_s6(zz, i, m, min_leg=0.0, lo=0.236, hi=0.5, tgt=1.618):
    if len(zz) < 3:
        return []
    X, A, B = zz[-3], zz[-2], zz[-1]
    xa = A[2] - X[2]
    ab = B[2] - A[2]
    if xa == 0 or not _big(zz, i, m, min_leg):
        return []
    r = -ab / xa
    if not (lo <= r <= hi):
        return []
    buy = xa < 0
    ent = [A[2] + k * ab for k in (0.14, 0.236, 0.382, 0.5)]
    return [_sig("S6", (X[1], A[1], B[1]), buy, ent, [0.25] * 4, A[2] - 0.14 * ab, A[2] - tgt * xa)]


# ---------------------------------------------------------------- Вайкофф
def wyckoff_signals(m, n=48, max_h_atr=6.0, max_pen=0.3, target="opp", stop_atr=0.1):
    """Спринг: минимум свечи i ниже минимума боковика (n свечей до неё), закрытие обратно внутри.
    Боковик: высота ≤ max_h_atr·ATR; прокол ≤ max_pen·высоты. Вход по рынку на открытии следующей свечи.
    Стоп за экстремумом свечи i (± stop_atr·ATR). Цель: 'opp' — противоположная граница, 'mid' — середина."""
    H_h, H_l, H_c, ATR = m.H_h, m.H_l, m.H_c, m.ATR
    out = []
    last = -10**9
    for i in range(max(300, n + 1), len(H_c) - 1):
        hi = H_h[i - n:i].max(); lo = H_l[i - n:i].min()
        hgt = hi - lo
        a = ATR[i - 1]
        if hgt <= 0 or hgt > max_h_atr * a * np.sqrt(n / 24.0) or i - last < 6:
            continue
        mid = (hi + lo) / 2
        if H_l[i] < lo and H_c[i] > lo and lo - H_l[i] <= max_pen * hgt and H_h[i] < hi:
            tg = hi if target == "opp" else mid
            out.append(dict(name="WY", key=(i,), buy=True, entries=[None], weights=[1.0],
                            stop=H_l[i] - stop_atr * a, target=tg, cancel=None, expiry=1, i=i))
            last = i
        elif H_h[i] > hi and H_c[i] < hi and H_h[i] - hi <= max_pen * hgt and H_l[i] > lo:
            tg = lo if target == "opp" else mid
            out.append(dict(name="WY", key=(i,), buy=False, entries=[None], weights=[1.0],
                            stop=H_h[i] + stop_atr * a, target=tg, cancel=None, expiry=1, i=i))
            last = i
    return out


# ---------------------------------------------------------------- исполнитель
def execute(m, s, max_hold_bars=96 * 28, intrabar="color"):
    """Одна сделка по сигналу s на M15 после закрытия H1-свечи s['i']. Возвращает R или None (нет входа)."""
    spr = m.spread
    buy = s["buy"]
    start = m.h1_start[s["i"] + 1]
    exp_end = m.h1_start[min(s["i"] + 1 + s["expiry"], len(m.h1_start) - 1)]
    n = len(m.o)
    ent, w = s["entries"], s["weights"]
    stop, tgt, cancel = s["stop"], s["target"], s["cancel"]
    done = [False] * len(ent)
    vol = 0.0; cost = 0.0
    # риск при исполнении всех входов (в цене)
    if ent[0] is None:
        ent = [m.o[start] + (spr if buy else 0.0)]
    risk = sum(wk * abs(e - stop) for wk, e in zip(w, ent))
    if risk <= 0:
        return None
    d = 1 if buy else -1
    end = min(n, start + max_hold_bars)
    for b in range(start, end):
        o, h, l, c = m.o[b], m.h[b], m.l[b], m.c[b]
        pts = (o, l, h, c) if (c >= o) else (o, h, l, c)
        x = pts[0]
        for k, y in enumerate(pts):
            # цена (bid) движется от x к y; события по порядку
            seg_lo, seg_hi = min(x, y), max(x, y)
            if k == 0:
                seg_lo = seg_hi = y
            if vol == 0.0:
                if b >= exp_end:
                    return None
                # отмена: цена дошла до цели раньше входа / стоп раньше входа
                if cancel is not None and ((seg_hi >= cancel) if buy else (seg_lo + spr <= cancel)):
                    return None
                if (seg_lo <= stop) if buy else (seg_hi + spr >= stop):
                    return None
            # входы
            for j, e in enumerate(ent):
                if done[j]:
                    continue
                hit = (seg_lo + spr <= e) if buy else (seg_hi >= e)
                if hit:
                    done[j] = True
                    px = e
                    if k == 0:   # гэп/открытие: по цене открытия
                        px = min(e, y + spr) if buy else max(e, y)
                    vol += w[j]; cost += w[j] * px
            if vol > 0:
                avg = cost / vol
                # стоп раньше цели (консервативно)
                if (seg_lo <= stop) if buy else (seg_hi + spr >= stop):
                    px = stop if k > 0 else (min(stop, y) if buy else max(stop, y + spr))
                    return (px - avg) * d * vol / risk
                if (seg_hi >= tgt) if buy else (seg_lo + spr <= tgt):
                    px = tgt if k > 0 else (max(tgt, y) if buy else min(tgt, y + spr))
                    return (px - avg) * d * vol / risk
            x = y
    if vol > 0:
        avg = cost / vol
        px = m.c[end - 1] if buy else m.c[end - 1] + spr
        return (px - avg) * d * vol / risk
    return None


# ---------------------------------------------------------------- пробой канала (D1)
def donchian(m, n_in=55, n_out=20, stop_atr=2.0):
    """m — рынок с period=86400. Вход на закрытии дня за n_in-дневным экстремумом; выход на закрытии
    за n_out-дневным противоположным экстремумом или по стопу stop_atr·ATR. R от начального риска."""
    H_h, H_l, H_c, ATR, spr = m.H_h, m.H_l, m.H_c, m.ATR, m.spread
    out = []
    pos = 0; entry = stop = risk = 0.0; t_in = 0
    for i in range(n_in + 1, len(H_c)):
        if pos != 0:
            # стоп внутри дня
            if (pos > 0 and H_l[i] <= stop) or (pos < 0 and H_h[i] + spr >= stop):
                out.append((t_in, int(m.H_t[i]), pos > 0, (stop - entry) * pos / risk)); pos = 0
            elif (pos > 0 and H_c[i] < H_l[i - n_out:i].min()) or (pos < 0 and H_c[i] > H_h[i - n_out:i].max()):
                px = H_c[i] if pos > 0 else H_c[i] + spr
                out.append((t_in, int(m.H_t[i]), pos > 0, (px - entry) * pos / risk)); pos = 0
        if pos == 0:
            a = ATR[i]
            if H_c[i] > H_h[i - n_in:i].max():
                pos = 1; entry = H_c[i] + spr; stop = entry - stop_atr * a; risk = entry - stop; t_in = int(m.H_t[i])
            elif H_c[i] < H_l[i - n_in:i].min():
                pos = -1; entry = H_c[i]; stop = entry + stop_atr * a; risk = stop - entry; t_in = int(m.H_t[i])
    return out
