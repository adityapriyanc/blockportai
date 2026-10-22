from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from blockport.db import init_db, make_engine, session_scope
from blockport.ingestion.faults import inject_faults
from blockport.ingestion.ingest import ingest_ais
from blockport.ingestion.synthetic import (
    WeatherSeries,
    generate_weather,
    headwind_ms,
    seed_database,
    simulate_approach,
)
from blockport.ingestion.validation import AisValidator, WeatherValidator
from blockport.models import AisObservation, PortCall, QuarantinedRecord, WeatherObservation

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _weather(speed: float, direction: float, hours: int = 200) -> WeatherSeries:
    z = np.zeros(hours)
    return WeatherSeries(T0, z + speed, z + direction, z + 1.0, z)


def _ais(**over) -> dict:
    rec = {"vessel_id": 1, "observed_at": T0, "lat": 1.5, "lon": 103.9, "speed_knots": 14.0,
           "heading_deg": 90.0, "distance_to_port_nm": 20.0}
    rec.update(over)
    return rec


# ------------------------------------------------------------------ generator
def test_headwind_sign_convention():
    assert headwind_ms(10, 90, 90) == pytest.approx(10)  # wind from where ship is heading
    assert headwind_ms(10, 270, 90) == pytest.approx(-10)  # tailwind
    assert headwind_ms(10, 0, 90) == pytest.approx(0, abs=1e-9)


def test_headwind_delays_arrival():
    rng1, rng2 = np.random.default_rng(1), np.random.default_rng(1)
    _, head = simulate_approach(rng1, 1, T0, 400, 90, 16, _weather(15, 90))
    _, tail = simulate_approach(rng2, 1, T0, 400, 90, 16, _weather(15, 270))
    assert head > tail


def test_approach_records_are_consistent():
    obs, arrival = simulate_approach(np.random.default_rng(3), 7, T0, 300, 135, 15,
                                     generate_weather(np.random.default_rng(3), T0, 200))
    d = [o["distance_to_port_nm"] for o in obs]
    assert d == sorted(d, reverse=True) and d[0] == 300
    assert arrival > obs[-1]["observed_at"] - timedelta(seconds=1)
    assert AisValidator().validate(obs).rejected == []  # generator output passes validation


def test_seed_database_is_deterministic_and_populated():
    counts = []
    for _ in range(2):
        engine = make_engine("sqlite://")
        init_db(engine)
        with session_scope(engine) as s:
            summary = seed_database(s, days=3, seed=7)
        with session_scope(engine) as s:
            assert s.query(PortCall).count() == summary.port_calls > 0
            assert s.query(AisObservation).count() == summary.ais_observations > 0
            assert s.query(WeatherObservation).count() == summary.weather_observations
            assert all(pc.actual_arrival is not None for pc in s.query(PortCall))
        counts.append((summary.port_calls, summary.ais_observations))
    assert counts[0] == counts[1]


# ------------------------------------------------------------------ validation rules
@pytest.mark.parametrize("rec,reason", [
    (_ais(speed_knots=None), "missing_field"),
    (_ais(speed_knots="fast"), "invalid_type"),
    (_ais(speed_knots=float("nan")), "invalid_type"),
    (_ais(speed_knots=99), "out_of_range"),
    (_ais(lat=95), "out_of_range"),
    (_ais(observed_at=T0.replace(tzinfo=None)), "naive_timestamp"),
    (_ais(observed_at="garbage"), "invalid_timestamp"),
])
def test_ais_rejections(rec, reason):
    assert AisValidator().check(rec)[1] == reason


def test_ais_timestamp_normalised_to_utc():
    ist = timezone(timedelta(hours=5, minutes=30))
    clean, reason = AisValidator().check(_ais(observed_at=T0.astimezone(ist).isoformat()))
    assert reason is None and clean["observed_at"] == T0
    assert clean["observed_at"].utcoffset() == timedelta(0)
    assert AisValidator().check(_ais(observed_at="2026-01-01T00:00:00Z"))[1] is None


def test_ais_stale_and_future():
    v = AisValidator(now=T0 + timedelta(hours=2), stale_after=timedelta(minutes=30))
    assert v.check(_ais())[1] == "stale"
    assert v.check(_ais(observed_at=T0 + timedelta(hours=1, minutes=45)))[1] is None
    assert v.check(_ais(observed_at=T0 + timedelta(hours=3), vessel_id=2))[1] == "future_timestamp"


def test_ais_duplicate_out_of_order_and_jump():
    v = AisValidator()
    assert v.check(_ais())[1] is None
    assert v.check(_ais())[1] == "duplicate"
    assert v.check(_ais(observed_at=T0 - timedelta(minutes=5)))[1] == "out_of_order"
    # 5 degrees latitude (300 nm) in 1 minute is impossible
    assert v.check(_ais(observed_at=T0 + timedelta(minutes=1), lat=6.5))[1] == "position_jump"
    # a different vessel is tracked independently
    assert v.check(_ais(vessel_id=2, observed_at=T0 - timedelta(hours=1)))[1] is None


def test_weather_validator():
    v = WeatherValidator()
    ok = {"observed_at": T0, "wind_speed_ms": 8, "wind_dir_deg": 90, "wave_height_m": 1.0}
    clean, reason = v.check(ok)
    assert reason is None and clean["tide_height_m"] == 0.0
    assert v.check(ok)[1] == "duplicate"
    assert v.check({**ok, "observed_at": T0 + timedelta(hours=1), "wind_speed_ms": 500})[1] \
        == "out_of_range"
    assert v.check({**ok, "wave_height_m": None})[1] == "missing_field"
    assert v.check({**ok, "observed_at": T0.replace(tzinfo=None)})[1] == "naive_timestamp"


# ------------------------------------------------------------------ fault injection end-to-end
def test_all_injected_faults_caught_and_no_clean_record_rejected():
    rng = np.random.default_rng(11)
    clean, _ = simulate_approach(rng, 1, T0, 600, 90, 15, generate_weather(rng, T0, 200))
    noisy, counts = inject_faults(clean, np.random.default_rng(5), rate=0.2)
    assert sum(counts.values()) > 10 and all(c > 0 for c in counts.values())

    now = clean[-1]["observed_at"] + timedelta(hours=1)
    res = AisValidator(now=now, stale_after=timedelta(days=30)).validate(noisy)
    assert len(res.accepted) == len(clean)  # every clean record kept
    assert len(res.rejected) == sum(counts.values())  # every fault rejected
    assert res.reasons() == {
        "stale": counts["stale"], "duplicate": counts["duplicate"],
        "missing_field": counts["missing_field"], "out_of_range": counts["out_of_range"],
        "naive_timestamp": counts["naive_timestamp"], "position_jump": counts["position_jump"],
    }


def test_rejected_records_are_quarantined_with_reason():
    engine = make_engine("sqlite://")
    init_db(engine)
    rec_ok, rec_bad = _ais(), _ais(speed_knots=None, observed_at=T0 + timedelta(minutes=30))
    with session_scope(engine) as s:
        ingest_ais(s, [rec_ok, rec_bad], AisValidator())
    with session_scope(engine) as s:
        assert s.query(AisObservation).count() == 1
        q = s.query(QuarantinedRecord).one()
        assert q.reason == "missing_field" and q.source == "ais"
        assert q.payload["observed_at"].startswith("2026-01-01T00:30")
