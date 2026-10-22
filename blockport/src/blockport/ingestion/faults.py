"""Fault injection for testing the validation pipeline (simulated sensor/feed faults)."""
from __future__ import annotations

from datetime import timedelta
from typing import Dict, List, Tuple

import numpy as np

FAULT_KINDS = ("stale", "duplicate", "missing_field", "out_of_range", "naive_timestamp",
               "position_jump")


def inject_faults(records: List[dict], rng: np.random.Generator,
                  rate: float = 0.05) -> Tuple[List[dict], Dict[str, int]]:
    """Return a corrupted copy of AIS records and a count of faults injected per kind.

    A faulty copy is emitted IMMEDIATELY AFTER the clean record it derives from, never replacing
    it. Each fault is designed to be rejected for a known reason, so tests can check that every
    injected fault is caught and no clean record is rejected.
    """
    out: List[dict] = []
    counts = {k: 0 for k in FAULT_KINDS}
    for rec in records:
        out.append(rec)
        if rng.random() >= rate:
            continue
        kind = FAULT_KINDS[int(rng.integers(len(FAULT_KINDS)))]
        bad = dict(rec)
        if kind == "stale":
            bad["observed_at"] = rec["observed_at"] - timedelta(days=365)
        elif kind == "missing_field":
            bad["speed_knots"] = None
        elif kind == "out_of_range":
            bad["speed_knots"] = 999.0
        elif kind == "naive_timestamp":
            bad["observed_at"] = rec["observed_at"].replace(tzinfo=None)
        elif kind == "position_jump":
            bad["observed_at"] = rec["observed_at"] + timedelta(minutes=1)
            bad["lat"] = rec["lat"] + 5.0
        # "duplicate": exact re-emission, bad is already a copy
        counts[kind] += 1
        out.append(bad)
    return out, counts
