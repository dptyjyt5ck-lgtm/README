"""Прогнозисты: Kronos и два простых эталона для сравнения.

Каждый возвращает для каждого окна массив [samples] — прогноз цены закрытия через horizon свечей.
"""
import numpy as np
import pandas as pd

MODELS = {
    "mini": ("NeoQuasar/Kronos-mini", "NeoQuasar/Kronos-Tokenizer-2k", 2048),
    "small": ("NeoQuasar/Kronos-small", "NeoQuasar/Kronos-Tokenizer-base", 512),
    "base": ("NeoQuasar/Kronos-base", "NeoQuasar/Kronos-Tokenizer-base", 512),
}


class KronosForecaster:
    """Обёртка над KronosPredictor: каждое окно повторяется samples раз, sample_count=1 —
    так получаем отдельные пути, а не их среднее."""
    name = "kronos"

    def __init__(self, size="mini", samples=8, device=None, predictor=None, T=1.0, top_p=0.9):
        self.samples, self.T, self.top_p = samples, T, top_p
        if predictor is None:
            from model import Kronos, KronosPredictor, KronosTokenizer  # из git clone shiyu-coder/Kronos
            model_id, tok_id, ctx = MODELS[size]
            predictor = KronosPredictor(Kronos.from_pretrained(model_id), KronosTokenizer.from_pretrained(tok_id),
                                        device=device, max_context=ctx)
        self.predictor = predictor
        self.name = f"kronos-{size}"

    def forecast(self, windows, horizon, freq="h"):
        dfs, xs, ys = [], [], []
        for w in windows:
            last = w["timestamps"].iloc[-1]
            y_ts = pd.Series(pd.date_range(last + pd.Timedelta(1, freq), periods=horizon, freq=freq))
            for _ in range(self.samples):
                dfs.append(w[["open", "high", "low", "close", "volume", "amount"]].reset_index(drop=True))
                xs.append(w["timestamps"].reset_index(drop=True))
                ys.append(y_ts)
        preds = self.predictor.predict_batch(dfs, xs, ys, pred_len=horizon, T=self.T, top_p=self.top_p,
                                             sample_count=1, verbose=False)
        closes = np.array([p["close"].iloc[-1] for p in preds], dtype=float)
        return closes.reshape(len(windows), self.samples)


class RandomWalkForecaster:
    """Эталон «рынок случаен»: пути из перемешанных прошлых доходностей окна. Преимущества быть не должно."""
    name = "random-walk"

    def __init__(self, samples=8, seed=0):
        self.samples, self.rng = samples, np.random.default_rng(seed)

    def forecast(self, windows, horizon, freq="h"):
        out = []
        for w in windows:
            r = np.diff(np.log(w["close"].to_numpy()))
            draws = self.rng.choice(r - r.mean(), size=(self.samples, horizon)).sum(axis=1)
            out.append(w["close"].iloc[-1] * np.exp(draws))
        return np.array(out)


class MomentumForecaster:
    """Эталон «тренд продолжится»: последнее движение за horizon свечей повторится."""
    name = "momentum"

    def __init__(self, samples=8):
        self.samples = samples

    def forecast(self, windows, horizon, freq="h"):
        out = []
        for w in windows:
            c = w["close"].to_numpy()
            move = c[-1] / c[-1 - horizon]
            out.append(np.full(self.samples, c[-1] * move))
        return np.array(out)
