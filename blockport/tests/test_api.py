"""Tests for BlockPort AI REST API and Interactive Dashboard (report §6, §7.3)."""
from fastapi.testclient import TestClient

from blockport.api import app


def test_api_health_and_targets():
    client = TestClient(app)
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"

    res_targets = client.get("/config/targets")
    assert res_targets.status_code == 200
    assert "eta_mae_minutes_max" in res_targets.json()


def test_api_status_overview():
    client = TestClient(app)
    res = client.get("/api/status")
    assert res.status_code == 200
    data = res.json()
    assert "berths" in data
    assert len(data["berths"]) >= 4
    assert "weather" in data


def test_api_section7_scenario():
    client = TestClient(app)
    res = client.get("/api/scenarios/section7")
    assert res.status_code == 200
    data = res.json()
    assert data["option_a"]["total_wait_hours"] > data["option_b"]["total_wait_hours"]
    assert data["impact"]["cost_saved_usd"] > 0


def test_api_copilot_and_governance_decision():
    client = TestClient(app)
    res_rec = client.get("/api/copilot/recommendation")
    assert res_rec.status_code == 200
    rec = res_rec.json()
    assert "id" in rec
    assert rec["confidence_score"] > 0

    res_dec = client.post(
        "/api/copilot/decision",
        json={
            "recommendation_id": rec["id"],
            "decision": "APPROVED",
            "operator": "test_harbor_master",
            "reason": "Test approval verification",
        },
    )
    assert res_dec.status_code == 200
    dec = res_dec.json()
    assert dec["decision"] == "APPROVED"
    assert dec["blockchain_tx_hash"] is not None


def test_api_blockchain_chain_and_audit():
    client = TestClient(app)
    res_chain = client.get("/api/blockchain/chain")
    assert res_chain.status_code == 200
    assert res_chain.json()["chain_valid"] is True

    res_audit = client.post("/api/blockchain/audit")
    assert res_audit.status_code == 200
    audit = res_audit.json()
    assert audit["valid_verification_rate_pct"] == 100.0
    assert audit["tampered_detection_rate_pct"] == 100.0
    assert audit["target_met"] is True


def test_api_green_report_and_scorecard():
    client = TestClient(app)
    res_green = client.get("/api/green/report")
    assert res_green.status_code == 200
    assert res_green.json()["co2_saved_kg"] > 0

    res_score = client.get("/api/evaluation/scorecard")
    assert res_score.status_code == 200
    assert len(res_score.json()["scorecard"]) == 8
    assert res_score.json()["all_targets_met"] is True


def test_api_index_html_dashboard_mounted():
    client = TestClient(app)
    res = client.get("/")
    assert res.status_code == 200
    assert "BlockPort AI" in res.text
    assert "Digital Twin Autonomous Port Simulation" in res.text


def test_api_realtime_blockchain_anchor_and_verify():
    client = TestClient(app)
    payload = {"vessel": "MV Delayed", "berth": "B1", "kw": 2400}
    res_anchor = client.post(
        "/api/blockchain/anchor",
        json={"record_type": "SHORE_POWER", "data": payload},
    )
    assert res_anchor.status_code == 200
    anchor_data = res_anchor.json()
    assert anchor_data["status"] == "anchored"
    assert "merkle_root" in anchor_data

    # Verify authentic
    res_valid = client.post(
        "/api/blockchain/verify-record",
        json={"record_type": "SHORE_POWER", "data": payload},
    )
    assert res_valid.status_code == 200
    assert res_valid.json()["verified"] is True
    assert res_valid.json()["tampered"] is False

    # Verify tampered
    mutated_payload = {"vessel": "MV Delayed", "berth": "B1", "kw": 9999}
    res_tampered = client.post(
        "/api/blockchain/verify-record",
        json={"record_type": "SHORE_POWER", "data": mutated_payload},
    )
    assert res_tampered.status_code == 200
    assert res_tampered.json()["verified"] is False
    assert res_tampered.json()["tampered"] is True


def test_api_berths_schedule_and_reset():
    client = TestClient(app)
    # Test schedule option b
    res_b = client.get("/api/berths/schedule?scenario=b")
    assert res_b.status_code == 200
    data_b = res_b.json()
    assert "allocations" in data_b
    assert any(a["berth"] == "B1" and a["vessel"] == "MV Delayed" for a in data_b["allocations"])

    # Test schedule option a
    res_a = client.get("/api/berths/schedule?scenario=a")
    assert res_a.status_code == 200
    data_a = res_a.json()
    assert any(a["status"] == "POST_DELAY_DOCK" for a in data_a["allocations"])

    # Test copilot reset
    res_reset = client.post("/api/copilot/reset")
    assert res_reset.status_code == 200
    assert res_reset.json()["state"] == "PENDING"

    # Test scenarios list
    res_list = client.get("/api/scenarios/list")
    assert res_list.status_code == 200
    assert len(res_list.json()["scenarios"]) >= 3


def test_api_dynamic_operations_flow():
    client = TestClient(app)

    # 1. Fetch dynamic state
    res_state = client.get("/api/dynamic/state")
    assert res_state.status_code == 200
    state = res_state.json()
    assert "vessels" in state
    assert "berths" in state
    assert "copilot" in state
    assert "gantt" in state
    init_vessel_count = len(state["vessels"])

    # 2. Add custom ad-hoc vessel
    res_add = client.post(
        "/api/dynamic/add-vessel",
        json={
            "name": "MV Pacific Star",
            "vessel_type": "container",
            "loa_m": 310.0,
            "draft_m": 12.5,
            "cargo_units": 1400.0,
            "arrival_hour": 9.5,
        },
    )
    assert res_add.status_code == 200
    state_after_add = res_add.json()
    assert len(state_after_add["vessels"]) == init_vessel_count + 1

    # 3. Inject weather storm disruption
    res_storm = client.post(
        "/api/dynamic/disruption",
        json={
            "kind": "WEATHER_STORM",
            "wind_speed": 48.0,
            "wave_height": 3.8,
        },
    )
    assert res_storm.status_code == 200
    state_storm = res_storm.json()
    assert state_storm["weather"]["condition"] == "GALE_WARNING"

    # 4. Switch preset back to section7
    res_preset = client.post(
        "/api/dynamic/preset",
        json={"preset": "section7"},
    )
    assert res_preset.status_code == 200
    state_preset = res_preset.json()
    assert state_preset["kpis"]["total_wait_saved_hours"] == 12.0


def test_api_responders_and_sos():
    client = TestClient(app)

    # 1. Test /api/sos
    res_sos = client.get("/api/sos")
    assert res_sos.status_code == 200
    assert res_sos.json()["status"] == "CLEAR"
    assert "emergency_channel" in res_sos.json()

    # 2. Test /api/responders & /responders (GET)
    for path in ["/api/responders", "/responders"]:
        res_resp = client.get(path)
        assert res_resp.status_code == 200
        data = res_resp.json()
        assert data["status"] == "OPERATIONAL"
        assert data["total_active"] >= 1
        assert len(data["responders"]) >= 1

    # 3. Test POST /sos & /api/sos broadcast
    for sos_path in ["/api/sos", "/sos"]:
        res_post_sos = client.post(
            sos_path,
            json={
                "vessel": "MV Delayed",
                "incident_type": "ENGINE_COOLING_ALERT",
                "severity": "HIGH",
            },
        )
        assert res_post_sos.status_code == 200
        data_sos = res_post_sos.json()
        assert data_sos["status"] == "ACKNOWLEDGED"
        assert len(data_sos["dispatched_responders"]) >= 1

    # 4. Test POST /responders & /api/responders dispatch
    for resp_path in ["/api/responders", "/responders"]:
        res_post_resp = client.post(
            resp_path,
            json={"responder_id": "RESP-02", "action": "DISPATCH"},
        )
        assert res_post_resp.status_code == 200
        assert res_post_resp.json()["status"] == "DISPATCHED"




