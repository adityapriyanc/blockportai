"""Train + evaluate the ETA model and congestion forecaster, then register the model.

    python -m blockport.prediction.train --db sqlite:///./blockport.db
"""
from __future__ import annotations

import argparse
import json

from ..config import get_settings
from ..db import make_engine, session_scope
from .congestion import evaluate_congestion
from .eta import PRIMARY_MAX_LEAD_H, EtaModel, evaluate
from .features import build_snapshots, load_tables, time_split
from .registry import save_model


def run(db_url: str, seed: int = 0, register: bool = True) -> dict:
    engine = make_engine(db_url)
    with session_scope(engine) as s:
        tables = load_tables(s)
    snaps = build_snapshots(tables, seed=seed)
    train_ids, val_ids, test_ids = time_split(tables)
    part = {name: snaps[snaps["call_id"].isin(ids)]
            for name, ids in (("train", train_ids), ("val", val_ids), ("test", test_ids))}

    model = EtaModel(seed=seed).fit(part["train"])
    report = {
        "split_calls": {"train": len(train_ids), "val": len(val_ids), "test": len(test_ids)},
        "split_rows": {k: len(v) for k, v in part.items()},
        "eta_validation": evaluate(model, part["val"]),
        "eta_test": evaluate(model, part["test"]),
    }
    p50 = model.predict(snaps)["p50"]
    report["congestion_test"] = evaluate_congestion(tables, snaps, p50, test_ids)

    target = get_settings().targets.eta_mae_minutes_max
    primary = report["eta_test"][f"primary_lead_le_{PRIMARY_MAX_LEAD_H:g}h"]["mae_model_min"]
    report["target_check"] = {
        "target_mae_min": target, "primary_horizon_h": PRIMARY_MAX_LEAD_H,
        "primary_mae_min": primary, "met": bool(primary < target),
        "overall_mae_min": report["eta_test"]["overall"]["mae_model_min"],
        "overall_met": bool(report["eta_test"]["overall"]["mae_model_min"] < target),
    }
    if register:
        report["model_dir"] = str(save_model(model, "eta", report))
    return report


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--db", default=None)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--no-register", action="store_true")
    args = p.parse_args()
    print(json.dumps(run(args.db, args.seed, not args.no_register), indent=2, default=float))


if __name__ == "__main__":
    main()
