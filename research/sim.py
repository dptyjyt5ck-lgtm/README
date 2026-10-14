"""Симулятор советника B1 «Зигзаг» (MT5) на истории M15/H1.

Повторяет логику B1_Zigzag v1.23 / v1.29 (см. mt5/), плюс исследовательские
варианты (флаги в CFG). Цена из файлов считается bid; ask = bid + spread.
Внутри 15-минутной свечи цена идёт open -> (low, high) или (high, low) -> close,
как в тестере MT5 «OHLC на M1»: бычья свеча сначала к low, медвежья сначала к high.
"""
import math
import numpy as np

LR = (0.618, 0.5, 0.382, 0.236, 0.14)
EPS = 1e-9

BASE = dict(
    name="v123",
    exits="v123",          # 'v123' | 'v129'
    extreme_hours=120,
    trend_min_atr=8.0,
    impulse_min_atr=2.0,
    trend_bars=0, trend_eff=0.0,   # фильтр «пила» v1.29
    stop_k=0.14,
    levels=LR,
    weights=(0.6, 0.1, 0.1, 0.1, 0.1),
    target_k=1.618,
    trail_atr=3.0,
    max_hold_days=28,
    partial_at_b=67.0,     # v123: % текущего объёма; v129: % начального объёма
    target_part=30.0,      # v129: % начального объёма на цели
    be_at_b=True,
    stag_bars=0, stag_min_r=0.7, stag_give=40.0, stag_min_cur=0.2,
    late_mode="skip",      # 'skip' (v1.23) | 'shift' (v1.27+)
    min_lot_each=False,    # v1.29: каждый уровень не меньше мин. лота
    zz_left=3, zz_right=1,
    # исследовательские фильтры (выкл. = как в советнике)
    bos=False,             # слом структуры: импульс AB пробил последний экстремум перед A
    bos_lookback=0,
    risk_cap=0.0,          # >0: пропустить фигуру, если факт. риск > risk_cap * план
)


def cfg(**kw):
    c = dict(BASE)
    c.update(kw)
    return c


V123 = cfg()
V129 = cfg(name="v129", exits="v129", extreme_hours=72, trend_bars=48, trend_eff=0.30,
           partial_at_b=25.0, target_part=30.0, stag_bars=12, late_mode="shift", min_lot_each=True)


class Market:
    """Ряды M15 одного инструмента + производные H1."""

    def __init__(self, sym, t, o, h, l, c, spread, value_fn, period=3600):
        self.period = period
        self.sym = sym
        self.t = t            # numpy datetime64[s] -> int seconds
        self.o, self.h, self.l, self.c = o, h, l, c
        self.spread = spread
        self.value_fn = value_fn   # (time_sec, price) -> USD за 1.0 цены на 1 лот
        hour = t // period
        # индекс начала каждого часа
        starts = np.flatnonzero(np.r_[True, hour[1:] != hour[:-1]])
        self.h1_start = starts
        ends = np.r_[starts[1:], len(t)]
        self.H_t = t[starts] - (t[starts] % period)
        self.H_o = o[starts]
        self.H_h = np.maximum.reduceat(h, starts)
        self.H_l = np.minimum.reduceat(l, starts)
        self.H_c = c[ends - 1]
        n = len(starts)
        tr = np.empty(n)
        tr[0] = self.H_h[0] - self.H_l[0]
        tr[1:] = np.maximum(self.H_h[1:], self.H_c[:-1]) - np.minimum(self.H_l[1:], self.H_c[:-1])
        cs = np.r_[0.0, np.cumsum(tr)]
        idx = np.arange(n)
        lo = np.maximum(0, idx - 13)
        self.ATR = (cs[idx + 1] - cs[lo]) / (idx + 1 - lo)
        self.bar_hour = np.repeat(np.arange(n), ends - starts)


class Sim:
    def __init__(self, m, c, balance=100000.0, risk_pct=1.0, compound=False,
                 vmin=1e-6, step=1e-6, start_t=None, end_t=None):
        self.m, self.c = m, c
        self.balance0 = balance
        self.balance = balance
        self.risk_pct = risk_pct
        self.compound = compound
        self.vmin, self.step = vmin, step
        self.start_t, self.end_t = start_t, end_t
        self.zz = []          # [kind, index, price]
        self.seen = []
        self.setups = []
        self.grp = None
        self.trades = []
        self.next_id = 1
        self.stat = {}

    # ---------------- H1 структура ----------------
    def pivots_at(self, i, left, right):
        m = self.m
        j = i - right
        if j - left < 0:
            return []
        lh = m.H_h[j - left:j].max(); ll = m.H_l[j - left:j].min()
        rh = m.H_h[j + 1:i + 1].max(); rl = m.H_l[j + 1:i + 1].min()
        out = []
        if m.H_h[j] > lh and m.H_h[j] >= rh:
            out.append([1, j, m.H_h[j]])
        if m.H_l[j] < ll and m.H_l[j] <= rl:
            out.append([-1, j, m.H_l[j]])
        return out

    def zz_update(self, i):
        c = self.pivots_at(i, self.c["zz_left"], self.c["zz_right"])
        p = self.zz
        if len(c) == 2 and p and c[0][0] == p[-1][0]:
            c = [c[1], c[0]]
        ne = 0
        for x in c:
            if p and p[-1][0] == x[0]:
                more = x[2] > p[-1][2] if x[0] == 1 else x[2] < p[-1][2]
                if more:
                    p[-1] = x; ne += 1
            else:
                p.append(x); ne += 1
        if len(p) > 400:
            del p[:200]
        return ne

    def bump(self, k):
        self.stat[k] = self.stat.get(k, 0) + 1

    def ctx_ok(self, idx, kind, price):
        m, c = self.m, self.c
        lo = max(0, idx - c["extreme_hours"])
        if kind == 1:
            if price < m.H_h[lo:idx + 1].max() - 1e-12:
                return "notext"
            opp = m.H_l[lo:idx + 1].min()
        else:
            if price > m.H_l[lo:idx + 1].min() + 1e-12:
                return "notext"
            opp = m.H_h[lo:idx + 1].max()
        if c["trend_min_atr"] > 0 and abs(price - opp) < c["trend_min_atr"] * m.ATR[idx]:
            return "notrend"
        if c["trend_eff"] > 0 and c["trend_bars"] > 0:
            s0 = idx - c["trend_bars"]
            if s0 < 1:
                return "chop"
            cl = m.H_c[s0:idx + 1]
            path = abs(price - m.H_c[idx]) + np.abs(np.diff(cl)).sum()
            net = price - m.H_c[s0] if kind == 1 else m.H_c[s0] - price
            if path <= 0 or net / path < c["trend_eff"]:
                return "chop"
        return None

    def bos_ok(self, pa_kind):
        """Слом структуры: B пробил последний противоположный экстремум ZigZag перед A."""
        p = self.zz
        if len(p) < 3:
            return False
        a, b = p[-2], p[-1]
        prev = p[-3]                 # экстремум перед A, того же типа, что B
        return b[2] < prev[2] if b[0] == -1 else b[2] > prev[2]

    def process_h1(self, i, bid, ask):
        m, c = self.m, self.c
        if self.zz_update(i) == 0 or len(self.zz) < 2:
            return
        pa, pb = self.zz[-2], self.zz[-1]
        imp = pb[2] - pa[2]
        if imp == 0:
            return
        key = (pa[1], pb[1])
        if key in self.seen[-50:]:
            return
        self.seen.append(key)
        if len(self.seen) > 200:
            del self.seen[:100]
        self.bump("legs")
        if pa[1] == pb[1]:
            return
        if c["impulse_min_atr"] > 0 and abs(imp) < c["impulse_min_atr"] * m.ATR[i]:
            self.bump("small"); return
        why = self.ctx_ok(pa[1], pa[0], pa[2])
        if why:
            self.bump(why); return
        if c["bos"] and not self.bos_ok(pa[0]):
            self.bump("nobos"); return
        buy = imp > 0
        lv = [pa[2] + k * imp for k in c["levels"]]
        w = list(c["weights"])
        done = [False] * len(lv)
        k0 = 0
        while k0 < len(lv) and (ask <= lv[k0] if buy else bid >= lv[k0]):
            k0 += 1
        if k0 > 0:
            if c["late_mode"] == "skip" or k0 >= len(lv):
                self.bump("late"); return
            moved = sum(w[:k0])
            for q in range(k0):
                w[q] = 0.0; done[q] = True
            w[k0] += moved
            self.bump("latemove")
        s = dict(id=self.next_id, aIdx=pa[1], bIdx=pb[1], A=pa[2], B=pb[2], buy=buy, lv=lv, w=w,
                 done=done, lots=[0.0] * len(lv), stop=pa[2] - c["stop_k"] * imp,
                 target=pa[2] + c["target_k"] * imp, alive=True, any=False, t=int(m.H_t[i]))
        self.next_id += 1
        self.setups.append(s)
        self.bump("setups")

    # ---------------- деньги ----------------
    def vpu(self, t, price):
        return self.m.value_fn(t, price)

    def size_setup(self, s, t):
        c = self.c
        val = self.vpu(t, s["lv"][0])
        bal = self.balance if self.compound else self.balance0
        denom = sum(s["w"][k] * abs(s["lv"][k] - s["stop"]) * val for k in range(len(s["lv"])))
        if denom <= 0:
            return False
        plan = bal * self.risk_pct / 100.0
        total = plan / denom
        anyl = False
        risk = 0.0
        for k in range(len(s["lv"])):
            if s["w"][k] <= 0:
                s["lots"][k] = 0.0; continue
            l = math.floor(s["w"][k] * total / self.step + 1e-9) * self.step
            if c["min_lot_each"]:
                l = max(l, self.vmin)
            elif l < self.vmin - 1e-12:
                l = 0.0
            s["lots"][k] = l
            if l > 0:
                anyl = True
                risk += l * abs(s["lv"][k] - s["stop"]) * val
        s["plan"] = plan
        s["risk_full"] = risk
        if c["risk_cap"] > 0 and risk > c["risk_cap"] * plan:
            self.bump("riskcap"); return False
        return anyl

    # ---------------- позиция ----------------
    def open_fill(self, s, k, price, t):
        g = self.grp
        lots = s["lots"][k]
        if g is None:
            g = self.grp = dict(sid=s["id"], buy=s["buy"], B=s["B"], target=s["target"], stop0=s["stop"],
                                sl=s["stop"], vol=0.0, avg=0.0, initVol=0.0, pnl=0.0, beDone=False,
                                partDone=False, tpDone=False, opened=t, ext=price, lastExt=self.cur_h,
                                plan=s["plan"], risk_full=s["risk_full"], fills=[], setup=s,
                                t_open=t, maxR=0.0)
            s["any"] = True
        g["avg"] = (g["avg"] * g["vol"] + price * lots) / (g["vol"] + lots)
        g["vol"] += lots
        g["initVol"] += lots
        g["fills"].append(k)
        if self.c["exits"] == "v129":
            g["ext"] = price; g["lastExt"] = self.cur_h

    def close_vol(self, vol, price, t, why):
        g = self.grp
        vol = min(vol, g["vol"])
        d = 1 if g["buy"] else -1
        g["pnl"] += (price - g["avg"]) * d * vol * self.vpu(t, price)
        g["vol"] -= vol
        if g["vol"] <= 1e-12:
            self.finish(t, why)

    def finish(self, t, why):
        g = self.grp
        s = g["setup"]
        s["alive"] = False
        if self.compound:
            self.balance += g["pnl"]
        self.trades.append(dict(sym=self.m.sym, t_open=g["t_open"], t_close=t, buy=g["buy"],
                                pnl=g["pnl"], plan=g["plan"], R=g["pnl"] / g["plan"],
                                risk_full=g["risk_full"], fills=len(g["fills"]), why=why,
                                bal=self.balance))
        self.grp = None

    def close_share(self, pct, price, t, why):
        g = self.grp
        total = g["vol"]
        want = round(g["initVol"] * pct / 100.0 / self.step) * self.step
        if want < self.vmin - 1e-12:
            want = self.vmin
        if total < 2 * self.vmin - 1e-12:
            return
        if total - want < self.vmin - 1e-12:
            self.close_vol(total, price, t, why); return
        self.close_vol(want, price, t, why)

    # ---------------- тик ----------------
    def tick(self, bid, t, gap):
        """Один тик: стоп на сервере, затем CheckGroup/CheckFills/CheckBreakeven/CheckTargets."""
        c, spr = self.c, self.m.spread
        ask = bid + spr
        g = self.grp
        # стоп позиции (сервер)
        if g is not None:
            if g["buy"] and bid <= g["sl"] + EPS:
                self.close_vol(g["vol"], bid if gap else g["sl"], t, "sl")
            elif (not g["buy"]) and ask >= g["sl"] - EPS:
                self.close_vol(g["vol"], ask if gap else g["sl"], t, "sl")
        g = self.grp
        # CheckFills
        for s in self.setups:
            if not s["alive"]:
                continue
            buy = s["buy"]
            if (bid >= s["B"] - EPS) if buy else (bid <= s["B"] + EPS):
                s["alive"] = False
                if not s["any"]:
                    self.bump("gone")
                continue
            if not s["any"] and ((bid <= s["stop"] + EPS) if buy else (ask >= s["stop"] - EPS)):
                s["alive"] = False; self.bump("stopfirst"); continue
            if s["any"] and (self.grp is None or self.grp["sid"] != s["id"]):
                s["alive"] = False; continue
            for k in range(len(s["lv"])):
                if s["done"][k]:
                    continue
                hit = (ask <= s["lv"][k] + EPS) if buy else (bid >= s["lv"][k] - EPS)
                if not hit:
                    break
                s["done"][k] = True
                if not s["any"]:
                    if self.grp is not None:
                        s["alive"] = False; self.bump("busy"); break
                    if not self.size_setup(s, t):
                        s["alive"] = False; self.bump("vol"); break
                if s["lots"][k] > 0:
                    px = ask if buy else bid
                    if not gap:
                        px = s["lv"][k]
                    self.open_fill(s, k, px, t)
        g = self.grp
        if g is None:
            return
        buy = g["buy"]
        px_exit = bid if buy else ask
        # CheckBreakeven: цена ушла за B
        if not g["beDone"] and (bid >= g["B"] - EPS if buy else bid <= g["B"] + EPS):
            if c["exits"] == "v123":
                if c["partial_at_b"] > 0 and not g["partDone"]:
                    vol = g["vol"]
                    vc = math.floor(vol * c["partial_at_b"] / 100.0 / self.step + 1e-9) * self.step
                    if vc >= self.vmin - 1e-12 and vol - vc >= self.vmin - 1e-12:
                        self.close_vol(vc, px_exit, t, "partB")
                g["partDone"] = True
                if self.grp is None:
                    return
                if c["be_at_b"]:
                    be = g["avg"]
                    if (be > g["sl"]) if buy else (be < g["sl"]):
                        g["sl"] = be
                g["beDone"] = True
            else:
                if c["partial_at_b"] > 0 and not g["partDone"]:
                    self.close_share(c["partial_at_b"], px_exit, t, "partB")
                    g["partDone"] = True
                    if self.grp is None:
                        return
                if c["be_at_b"]:
                    be = g["avg"] + spr if buy else g["avg"] - spr
                    if (be > g["sl"]) if buy else (be < g["sl"]):
                        g["sl"] = be
                g["beDone"] = True
        g = self.grp
        if g is None:
            return
        # CheckTargets
        if not g["tpDone"] and (bid >= g["target"] - EPS if buy else ask <= g["target"] + EPS):
            if c["exits"] == "v123":
                vol = g["vol"]
                vA = math.floor(vol * 2.0 / 3.0 / self.step + 1e-9) * self.step
                if vA < self.vmin - 1e-12 or vol - vA < self.vmin - 1e-12:
                    self.close_vol(vol, px_exit, t, "target"); return
                self.close_vol(vA, px_exit, t, "target")
                be = g["avg"]
            else:
                self.close_share(c["target_part"], px_exit, t, "target")
                if self.grp is None:
                    return
                be = g["avg"] + spr if buy else g["avg"] - spr
            if (be > g["sl"]) if buy else (be < g["sl"]):
                g["sl"] = be
            g["tpDone"] = True

    def manage(self, prev_hi, prev_lo, bid, t):
        """ManageTrades на открытии новой M15 (по закрытой предыдущей)."""
        g, c = self.grp, self.c
        if g is None:
            return
        buy = g["buy"]
        ne = max(g["ext"], prev_hi) if buy else min(g["ext"], prev_lo)
        if (ne > g["ext"] + EPS) if buy else (ne < g["ext"] - EPS):
            g["lastExt"] = self.cur_h
        g["ext"] = ne
        px = bid if buy else bid + self.m.spread
        if t - g["opened"] >= c["max_hold_days"] * 86400:
            self.close_vol(g["vol"], px, t, "time"); return
        if c["exits"] == "v129" and c["stag_bars"] > 0:
            risk = abs(g["avg"] - g["stop0"])
            if risk > 0:
                d = 1 if buy else -1
                curR = (px - g["avg"]) * d / risk
                maxR = (g["ext"] - g["avg"]) * d / risk
                if (maxR >= c["stag_min_r"] and self.cur_h - g["lastExt"] >= c["stag_bars"]
                        and maxR - curR >= c["stag_give"] / 100.0 * maxR and curR >= c["stag_min_cur"]):
                    self.close_vol(g["vol"], px, t, "stag"); return
        if c["exits"] == "v123":
            if not (g["tpDone"] or g["beDone"]):
                return
        elif not g["tpDone"]:
            return
        atr = self.m.ATR[self.cur_h - 1] if self.cur_h > 0 else 0
        cand = g["ext"] - c["trail_atr"] * atr if buy else g["ext"] + c["trail_atr"] * atr
        if c["exits"] == "v123":
            nsl = max(g["sl"], cand, g["avg"]) if buy else min(g["sl"], cand, g["avg"])
        else:
            nsl = max(g["sl"], cand) if buy else min(g["sl"], cand)
        better = nsl > g["sl"] + EPS if buy else nsl < g["sl"] - EPS
        valid = nsl < px if buy else nsl > px
        if better and valid:
            g["sl"] = nsl

    # ---------------- пороги для непрерывного движения ----------------
    def thresholds(self):
        spr = self.m.spread
        out = []
        g = self.grp
        if g is not None:
            out.append(g["sl"] if g["buy"] else g["sl"] - spr)
            if not g["beDone"]:
                out.append(g["B"])
            if not g["tpDone"]:
                out.append(g["target"] if g["buy"] else g["target"] - spr)
        for s in self.setups:
            if not s["alive"]:
                continue
            out.append(s["B"])
            if not s["any"]:
                out.append(s["stop"] if s["buy"] else s["stop"] - spr)
            for k in range(len(s["lv"])):
                if not s["done"][k]:
                    out.append(s["lv"][k] - spr if s["buy"] else s["lv"][k])
                    break
        return out

    def move(self, p, q, t):
        if q == p:
            return
        up = q > p
        x = p
        for _ in range(200):
            if self.grp is None and not any(s["alive"] for s in self.setups):
                return
            th = self.thresholds()
            if up:
                cand = [v for v in th if x + EPS < v <= q + EPS]
                if not cand:
                    return
                x = min(cand)
            else:
                cand = [v for v in th if q - EPS <= v < x - EPS]
                if not cand:
                    return
                x = max(cand)
            self.tick(x, t, gap=False)

    # ---------------- основной цикл ----------------
    def run(self):
        m = self.m
        n = len(m.t)
        prev_c = m.o[0]
        prev_hi = prev_lo = None
        warm = 300
        for b in range(n):
            t = int(m.t[b])
            hb = m.bar_hour[b]
            self.cur_h = hb
            o, h, l, cc = m.o[b], m.h[b], m.l[b], m.c[b]
            active = self.end_t is None or t < self.end_t
            started = self.start_t is None or t >= self.start_t
            # первый тик бара (open): гэп
            self.tick(o, t, gap=True) if (self.grp is not None or self.setups) and o != prev_c else None
            if b > 0 and hb != m.bar_hour[b - 1]:
                i = hb - 1
                if i >= warm:
                    nset = len(self.setups)
                    self.process_h1(i, o, o + m.spread)
                    if not (active and started) and len(self.setups) > nset:
                        self.setups[-1]["alive"] = False
                    if self.setups:
                        self.setups = [s for s in self.setups if s["alive"] or (self.grp and s["id"] == self.grp["sid"])]
                    self.tick(o, t, gap=True)
            if prev_hi is not None:
                self.manage(prev_hi, prev_lo, o, t)
            if self.grp is not None or self.setups:
                if cc >= o:
                    pts = (l, h, cc)
                else:
                    pts = (h, l, cc)
                x = o
                for y in pts:
                    self.move(x, y, t)
                    x = y
            prev_c, prev_hi, prev_lo = cc, h, l
        if self.grp is not None:
            self.close_vol(self.grp["vol"], m.c[-1], int(m.t[-1]), "end")
        return self.trades
