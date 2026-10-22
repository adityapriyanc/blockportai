"""ETA model: quantile gradient boosting with uncertainty bands (report §5.2, §3 objective 1).

Predicts minutes remaining until arrival at the 10th/50th/90th percentiles. The median is the
point estimate; the p10-p90 band exposes uncertainty, since "a prediction is not a guarantee".
"""
from __future__ import annotations

from typing import Dict, Sequence

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from .features import CATEGORICAL, FEATURES

QUANTILES = (0.1, 0.5, 0.9)
LEAD_BUCKETS_H = ((0, 6), (6, 12), (12, 24), (24, 1e9))  # true time-to-arrival buckets (hours)
PRIMARY_MAX_LEAD_H = 24.0  # primary metric horizon: operationally relevant planning window


class EtaModel:
    def __init__(self, seed: int = 0, max_iter: int = 300, learning_rate: float = 0.06):
        cat_mask = [f in CATEGORICAL for f in FEATURES]
        self.models = {
            q: HistGradientBoostingRegressor(
                loss="quantile", quantile=q, max_iter=max_iter, learning_rate=learning_rate,
                categorical_features=cat_mask, random_state=seed,
            ) for q in QUANTILES
        }
        self.fitted = False

    def fit(self, train: pd.DataFrame) -> "EtaModel":
        X, y = train[FEATURES], train["remaining_min"]
        for m in self.models.values():
            m.fit(X, y)
        self.fitted = True
        return self

    def predict(self, df: pd.DataFrame) -> pd.DataFrame:
        """Return p10/p50/p90 minutes-to-arrival (non-negative, monotone across quantiles)."""
        if not self.fitted:
            raise RuntimeError("model is not fitted")
        raw = np.column_stack([self.models[q].predict(df[FEATURES]) for q in QUANTILES])
        raw = np.sort(np.clip(raw, 0.0, None), axis=1)  # fix quantile crossing
        return pd.DataFrame(raw, columns=["p10", "p50", "p90"], index=df.index)


def mae(err: Sequence[float]) -> float:
    return float(np.mean(np.abs(err)))


def evaluate(model: EtaModel, df: pd.DataFrame) -> Dict[str, object]:
    """MAE (minutes) of the model vs. two baselines, overall and by time-to-arrival bucket."""
    pred = model.predict(df)
    y = df["remaining_min"].to_numpy()
    err_model = pred["p50"].to_numpy() - y
    err_sched = df["scheduled_remaining_min"].to_numpy() - y
    err_naive = df["naive_remaining_min"].to_numpy() - y
    lead_h = y / 60.0

    def block(mask: np.ndarray) -> Dict[str, float]:
        if not mask.any():
            return {"n": 0}
        lo_q, hi_q = pred["p10"].to_numpy()[mask], pred["p90"].to_numpy()[mask]
        inside = (y[mask] >= lo_q) & (y[mask] <= hi_q)
        return {
            "n": int(mask.sum()),
            "mae_model_min": mae(err_model[mask]),
            "mae_scheduled_min": mae(err_sched[mask]),
            "mae_naive_min": mae(err_naive[mask]),
            "interval_coverage_p10_p90": float(inside.mean()),
        }

    buckets = {f"{lo:g}-{hi:g}h" if hi < 1e8 else f">{lo:g}h": block((lead_h >= lo) & (lead_h < hi))
               for lo, hi in LEAD_BUCKETS_H}
    return {
        "overall": block(np.ones(len(y), dtype=bool)),
        f"primary_lead_le_{PRIMARY_MAX_LEAD_H:g}h": block(lead_h <= PRIMARY_MAX_LEAD_H),
        "by_lead_time": buckets,
    }
