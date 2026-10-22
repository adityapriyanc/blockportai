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


