from fastapi.testclient import TestClient
from sqlalchemy import inspect

from blockport.api import app
from blockport.config import get_settings
from blockport.db import init_db, make_engine, session_scope
from blockport.models import (
    Berth,
    PortCall,
    Recommendation,
    RecommendationStatus,
    Terminal,
    Vessel,
    VesselType,
    utcnow,
)


def test_settings_load_and_validate():
    s = get_settings()
    assert s.objective_weights.alpha > 0
    assert s.targets.eta_mae_minutes_max == 30
    assert s.targets.min_scenarios == 3


def test_all_tables_created():
    engine = make_engine("sqlite://")
    init_db(engine)
    tables = set(inspect(engine).get_table_names())
    expected = {
        "terminals", "berths", "equipment", "vessels", "port_calls", "ais_observations",
        "weather_observations", "energy_records", "truck_schedules", "quarantined_records",
        "recommendations", "approvals", "chain_records",
    }
    assert expected <= tables


def test_relationships_roundtrip():
    engine = make_engine("sqlite://")
    init_db(engine)
    with session_scope(engine) as s:
        t = Terminal(name="Terminal A")
        b = Berth(terminal=t, name="A1", length_m=350, depth_m=16,
                  compatible_types=[VesselType.CONTAINER.value])
        v = Vessel(imo="IMO1234567", name="MV Test", vessel_type=VesselType.CONTAINER,
                   carrier="Maersk", loa_m=300, draft_m=13)
        pc = PortCall(vessel=v, scheduled_eta=utcnow(), cargo_units=5000)
        r = Recommendation(plan={"berth": "A1"}, metrics={"wait_saved_h": 1.0})
        s.add_all([t, b, v, pc, r])
    with session_scope(engine) as s:
        assert s.query(Berth).one().terminal.name == "Terminal A"
        assert s.query(PortCall).one().vessel.imo == "IMO1234567"
        assert s.query(Recommendation).one().status == RecommendationStatus.PENDING


def test_health_endpoint():
    client = TestClient(app)
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/config/targets").json()["min_scenarios"] == 3
