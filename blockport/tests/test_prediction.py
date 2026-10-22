from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from blockport.db import init_db, make_engine, session_scope
from blockport.domain import (
    POOL_BULK_LIQUID,
    POOL_CAPACITY,
    POOL_CONTAINER,
    pool_for_type,
    service_time_hours,
)
from blockport.ingestion.synthetic import seed_database
from blockport.models import AisObservation, VesselType
from blockport.prediction.congestion import (
    congestion_flags,
    demand_profile,
    evaluate_congestion,
)
from blockport.prediction.eta import EtaModel, evaluate
from blockport.prediction.features import (
    FEATURES,
    build_snapshots,
    load_tables,
    time_split,
)
from blockport.prediction.registry import load_latest, save_model

T0 = pd.Timestamp(datetime(2026, 1, 1, tzinfo=timezone.utc))


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    path = tmp_path_factory.mktemp("db") / "t.db"
    engine = make_engine(f"sqlite:///{path}")
    init_db(engine)
    with session_scope(engine) as s:
        seed_database(s, days=60, seed=3)
    with session_scope(engine) as s:
        tables = load_tables(s)
    snaps = build_snapshots(tables, seed=0)
    train, val, test = time_split(tables)
    model = EtaModel(seed=0, max_iter=80).fit(snaps[snaps["call_id"].isin(train)])
    return engine, tables, snaps, (train, val, test), model


# ------------------------------------------------------------------ domain
def test_service_time_and_pools():
    assert pool_for_type(VesselType.CONTAINER) == POOL_CONTAINER
    assert pool_for_type(VesselType.TANKER) == POOL_BULK_LIQUID
    assert service_time_hours(VesselType.CONTAINER, 1200) == pytest.approx(2 + 10)
    assert sum(POOL_CAPACITY.values()) == 4  # matches the 4-berth layout


# ------------------------------------------------------------------ features / split
def test_every_ais_row_linked_to_a_call(world):
    engine, tables, snaps, *_ = world
    with session_scope(engine) as s:
        assert s.query(AisObservation).filter(AisObservation.port_call_id.is_(None)).count() == 0
    assert len(snaps) == len(tables.ais)
    assert set(FEATURES) <= set(snaps.columns)
    assert not snaps[FEATURES + ["remaining_min"]].isna().any().any()


def test_target_matches_actual_arrival(world):
    _, tables, snaps, *_ = world
    calls = tables.calls.set_index("call_id")
    row = snaps.iloc[10]
    arrival = calls.loc[row["call_id"], "actual_arrival"]
    expected = (arrival - row["observed_at"]).total_seconds() / 60
    assert row["remaining_min"] == pytest.approx(expected)
    assert (snaps["remaining_min"] >= -1e-6).all()  # last obs is at or before arrival


def test_time_split_is_chronological_and_leak_free(world):
    _, tables, _, (train, val, test), _ = world
    assert train.isdisjoint(val) and train.isdisjoint(test) and val.isdisjoint(test)
    assert len(train | val | test) == len(tables.calls)
    sched = tables.calls.set_index("call_id")["scheduled_eta"]
    assert sched[list(train)].max() <= sched[list(val)].min()
    assert sched[list(val)].max() <= sched[list(test)].min()


def test_features_use_only_past_information(world):
    """Changing the FUTURE of a call must not change features of an earlier snapshot, except the
    simulated weather forecast; the observed-state features depend only on observations <= t."""
    _, _, snaps, *_ = world
    g = snaps[snaps["call_id"] == snaps["call_id"].iloc[0]].reset_index(drop=True)
    # speed_mean_6 at row i equals the mean of at most the 6 most recent speeds up to i
    for i in (0, 3, 10):
        lo = max(0, i - 5)
        assert g.loc[i, "speed_mean_6"] == pytest.approx(g.loc[lo:i, "speed_knots"].mean())


# ------------------------------------------------------------------ model
def test_model_beats_baselines_on_test(world):
    _, _, snaps, (_, _, test), model = world
    rep = evaluate(model, snaps[snaps["call_id"].isin(test)])
    prim = rep["primary_lead_le_24h"]
    assert prim["mae_model_min"] < prim["mae_scheduled_min"] / 5
    # at least on par with the distance/speed baseline
    assert prim["mae_model_min"] < prim["mae_naive_min"] * 1.1
    assert rep["overall"]["mae_model_min"] < 60


def test_quantiles_are_ordered_and_nonnegative(world):
    _, _, snaps, _, model = world
    p = model.predict(snaps.head(500))
    assert (p["p10"] <= p["p50"]).all() and (p["p50"] <= p["p90"]).all()
    assert (p >= 0).all().all()


def test_unfitted_model_refuses_to_predict(world):
    _, _, snaps, *_ = world
    with pytest.raises(RuntimeError):
        EtaModel().predict(snaps.head(3))


def test_registry_roundtrip(world, tmp_path):
    _, _, snaps, _, model = world
    save_model(model, "eta", {"mae": 1.0}, root=tmp_path)
    loaded, meta = load_latest("eta", root=tmp_path)
    assert meta["metrics"] == {"mae": 1.0}
    sample = snaps.head(50)
    np.testing.assert_allclose(loaded.predict(sample).to_numpy(), model.predict(sample).to_numpy())


# ------------------------------------------------------------------ congestion
def test_demand_profile_and_flags():
    occ = [(T0, 3.0, POOL_BULK_LIQUID), (T0 + timedelta(hours=1), 3.0, POOL_BULK_LIQUID),
           (T0, 2.0, POOL_CONTAINER)]
    d = demand_profile(occ, T0, 6)
    assert d[POOL_BULK_LIQUID].tolist() == [1, 2, 2, 1, 0, 0]
    assert d[POOL_CONTAINER].tolist() == [1, 1, 0, 0, 0, 0]
    flags = congestion_flags(d)  # bulk pool has 1 berth -> hours 1,2 congested
    assert flags[POOL_BULK_LIQUID].tolist() == [False, True, True, False, False, False]
    assert not flags[POOL_CONTAINER].any()


def test_congestion_backtest_runs_and_is_sane(world):
    _, tables, snaps, (_, _, test), model = world
    rep = evaluate_congestion(tables, snaps, model.predict(snaps)["p50"], test)
    assert rep["cells"] > 0 and 0 <= rep["congestion_base_rate"] <= 1
    for k in ("model", "baseline_scheduled_eta"):
        for m in ("precision", "recall", "f1"):
            v = rep[k][m]
            assert np.isnan(v) or 0 <= v <= 1
