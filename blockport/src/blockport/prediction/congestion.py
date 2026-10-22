"""Congestion / resource-shortage forecast (report §5.2, §6.2): arrivals vs berth capacity.

Berth DEMAND at hour h = number of vessels whose berth occupancy window [arrival, arrival+service)
covers h. Congestion = demand exceeds the pool's berth count (a queue would form). This ignores
queueing delays (those are handled by the Digital Twin in Phase 4); it answers "will there be more
vessels wanting a berth than berths available, and when?".

Arrival-time knowledge at forecast time t, per vessel:
  * already arrived          -> actual arrival
  * on approach (AIS seen)   -> latest observation time + model median remaining time
  * not yet visible          -> carrier-scheduled ETA
The baseline forecaster uses the scheduled ETA for every not-yet-arrived vessel.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Dict, Iterable, List, Tuple

import numpy as np
import pandas as pd

from ..domain import POOL_CAPACITY, pool_for_type, service_time_hours
from ..models import VesselType
from .features import Tables


def demand_profile(
    occupancy: Iterable[Tuple[pd.Timestamp, float, str]], start: pd.Timestamp, horizon_h: int,
) -> Dict[str, np.ndarray]:
    """occupancy: (arrival, service_hours, pool). Returns per-pool berth demand per hour."""
    grid = [start + timedelta(hours=h) for h in range(horizon_h)]
    out = {p: np.zeros(horizon_h, dtype=int) for p in POOL_CAPACITY}
    for arrival, svc, pool in occupancy:
        end = arrival + timedelta(hours=svc)
        for i, g in enumerate(grid):
            if arrival <= g < end:
                out[pool][i] += 1
    return out


def congestion_flags(demand: Dict[str, np.ndarray]) -> Dict[str, np.ndarray]:
    return {p: d > POOL_CAPACITY[p] for p, d in demand.items()}


def _prf(tp: int, fp: int, fn: int) -> Dict[str, float]:
    p = tp / (tp + fp) if tp + fp else float("nan")
    r = tp / (tp + fn) if tp + fn else float("nan")
    f = 2 * p * r / (p + r) if (p + r) and not np.isnan(p + r) else float("nan")
    return {"precision": p, "recall": r, "f1": f}


def evaluate_congestion(
    tables: Tables, snapshots: pd.DataFrame, p50_minutes: pd.Series, call_ids: set,
    forecast_every_h: int = 6, horizon_h: int = 24,
) -> Dict[str, object]:
    """Back-test hourly congestion flags at regular forecast times over the given calls.

    `p50_minutes` is the model's median remaining time for every row of `snapshots`.
    Truth = demand computed from ACTUAL arrivals.
    """
    calls = tables.calls[tables.calls["call_id"].isin(call_ids)].set_index("call_id")
    snaps = snapshots[snapshots["call_id"].isin(call_ids)].copy()
    snaps["pred_arrival"] = snaps["observed_at"] + pd.to_timedelta(
        p50_minutes.loc[snaps.index], unit="m")
    by_call = {cid: g.sort_values("observed_at") for cid, g in snaps.groupby("call_id")}

    svc: Dict[int, Tuple[float, str]] = {}
    for cid, c in calls.iterrows():
        vt = VesselType(c["vessel_type"])
        svc[cid] = (service_time_hours(vt, c["cargo_units"]), pool_for_type(vt))

    t = calls["scheduled_eta"].min().ceil("h")
    t_end = calls["actual_arrival"].max()
    counts = {"model": [0, 0, 0], "baseline": [0, 0, 0]}  # tp, fp, fn
    n_true_cells = n_cells = 0
    while t <= t_end:
        truth: List[Tuple[pd.Timestamp, float, str]] = []
        model: List[Tuple[pd.Timestamp, float, str]] = []
        base: List[Tuple[pd.Timestamp, float, str]] = []
        for cid, c in calls.iterrows():
            s, pool = svc[cid]
            actual = c["actual_arrival"]
            truth.append((actual, s, pool))
            if actual <= t:
                model.append((actual, s, pool))
                base.append((actual, s, pool))
                continue
            base.append((c["scheduled_eta"], s, pool))
            g = by_call.get(cid)
            seen = g[g["observed_at"] <= t] if g is not None else None
            if seen is not None and len(seen):
                model.append((seen.iloc[-1]["pred_arrival"], s, pool))
            else:
                model.append((c["scheduled_eta"], s, pool))
        flags_t = congestion_flags(demand_profile(truth, t, horizon_h))
        for name, occ in (("model", model), ("baseline", base)):
            flags_p = congestion_flags(demand_profile(occ, t, horizon_h))
            for pool in POOL_CAPACITY:
                yt, yp = flags_t[pool], flags_p[pool]
                counts[name][0] += int((yt & yp).sum())
                counts[name][1] += int((~yt & yp).sum())
                counts[name][2] += int((yt & ~yp).sum())
        for pool in POOL_CAPACITY:
            n_true_cells += int(flags_t[pool].sum())
            n_cells += horizon_h
        t += timedelta(hours=forecast_every_h)

    return {
        "cells": n_cells, "congested_cells_truth": n_true_cells,
        "congestion_base_rate": n_true_cells / max(n_cells, 1),
        "model": _prf(*counts["model"]), "baseline_scheduled_eta": _prf(*counts["baseline"]),
        "horizon_h": horizon_h, "forecast_every_h": forecast_every_h,
    }
