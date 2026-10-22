"""Unit and Integration Tests for BlockPort AI 5-Layer Architecture (Report §6).

Covers:
  - Layer 1: Sensing and Data Ingestion ("Eyes and Ears", §6.1)
  - Layer 2: Predictive Intelligence Engine ("Forecaster", §6.2)
  - Layer 3: Digital Twin and Green Optimization Core ("Virtual Sandbox", §6.3)
  - Layer 4: Blockchain Trust Protocol ("Permanent Record", §6.4)
  - Layer 5: AI Port Copilot ("Human Interface", §6.5)
  - End-to-End Coordinated Pipeline Flow & REST APIs
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from blockport.api import app
from blockport.architecture import (
    BlockPortArchitecturePipeline,
    Layer1SensingIngestion,
    Layer2PredictiveEngine,
    Layer3DigitalTwinOptimizer,
    Layer4BlockchainTrust,
    Layer5PortCopilot,
)


def test_layer1_sensing_ingestion_feed():
    l1 = Layer1SensingIngestion()
    output = l1.process()

    assert output.active_iot_sensors > 0
    assert output.ais_observations_count >= 1
    assert output.weather_observations_count >= 1
    assert "wind_speed_knots" in output.metocean_conditions
    assert len(output.equipment_statuses) >= 3


def test_layer2_predictive_intelligence_engine():
    l1 = Layer1SensingIngestion()
    l1_out = l1.process()

    l2 = Layer2PredictiveEngine()
    l2_out = l2.process(l1_out)

    assert l2_out.target_vessel == "MV Delayed"
    assert "p10_optimistic" in l2_out.confidence_band_p10_p90
    assert "p50_median" in l2_out.confidence_band_p10_p90
    assert "p90_conservative" in l2_out.confidence_band_p10_p90
    assert l2_out.eta_mae_min < 30.0  # Report §3 Objective 1 Target
    assert "forecasts conditions" in l2_out.governance_boundary


def test_layer3_digital_twin_and_green_optimizer():
    l1 = Layer1SensingIngestion()
    l1_out = l1.process()
    l2 = Layer2PredictiveEngine()
    l2_out = l2.process(l1_out)

    l3 = Layer3DigitalTwinOptimizer()
    l3_out = l3.process(l1_out, l2_out)

    assert l3_out.virtual_sandbox_status == "COMPLETED_ALTERNATIVE_EVALUATION"
    assert l3_out.baseline_wait_hours == 12.0
    assert l3_out.optimized_wait_hours == 0.0
    assert l3_out.wait_time_saved_hours == 12.0
    assert l3_out.demurrage_saved_usd == 14400.0
    assert l3_out.net_co2_saved_kg > 0.0
    assert l3_out.intensity_reduction_pct >= 5.0  # Report §3 Objective 4 Target
    assert len(l3_out.recommended_allocations) == 3


def test_layer4_blockchain_trust_protocol():
    l1 = Layer1SensingIngestion()
    l1_out = l1.process()
    l2 = Layer2PredictiveEngine()
    l2_out = l2.process(l1_out)
    l3 = Layer3DigitalTwinOptimizer()
    l3_out = l3.process(l1_out, l2_out)

    l4 = Layer4BlockchainTrust()
    l4_out = l4.process(l2_out, l3_out)

    assert l4_out.hybrid_storage_mode == "OFFCHAIN_DATA_LAKE_ONCHAIN_MERKLE_ROOTS"
    assert len(l4_out.canonical_rfc8785_hash) == 64
    assert len(l4_out.merkle_root_hash) == 64
    assert l4_out.onchain_block_index >= 1
    assert l4_out.chain_integrity_verified is True
    assert l4_out.tamper_audit_status == "ZERO_DISCREPANCY_PASS"


def test_layer5_ai_port_copilot_human_interface():
    l1 = Layer1SensingIngestion()
    l1_out = l1.process()
    l2 = Layer2PredictiveEngine()
    l2_out = l2.process(l1_out)
    l3 = Layer3DigitalTwinOptimizer()
    l3_out = l3.process(l1_out, l2_out)
    l4 = Layer4BlockchainTrust()
    l4_out = l4.process(l2_out, l3_out)

    l5 = Layer5PortCopilot()
    l5_out = l5.process(l2_out, l3_out, l4_out, operator="Harbor_Master_Davis")

    assert l5_out.confidence_score_pct == 96.0
    assert "12.0h" in l5_out.plain_english_summary
    assert "12 miles" in l5_out.plain_english_summary
    assert len(l5_out.physical_safety_proofs) >= 3
    assert l5_out.operator_assigned == "Harbor_Master_Davis"
    assert "APPROVE" in l5_out.action_options


def test_end_to_end_5_layer_architecture_pipeline():
    pipeline = BlockPortArchitecturePipeline()
    res = pipeline.execute_pipeline(scenario="section7", operator="Harbor_Master_Davis")

    assert res.all_layers_succeeded is True
    assert len(res.steps) == 5
    assert res.total_duration_ms > 0.0

    step_names = [s.layer_name for s in res.steps]
    assert step_names == [
        "Sensing and Data Ingestion",
        "Predictive Intelligence Engine",
        "Digital Twin & Green Optimization Core",
        "Blockchain Trust Protocol",
        "AI Port Copilot",
    ]

    expected_subtitles = [
        "Eyes and Ears (§6.1)",
        "Forecaster (§6.2)",
        "Virtual Sandbox (§6.3)",
        "Permanent Record (§6.4)",
        "Human Interface (§6.5)",
    ]
    actual_subtitles = [s.subtitle for s in res.steps]
    assert actual_subtitles == expected_subtitles


def test_api_architecture_endpoints():
    client = TestClient(app)

    # 1. Spec endpoint
    res_spec = client.get("/api/architecture/spec")
    assert res_spec.status_code == 200
    spec = res_spec.json()
    assert spec["title"] == "Proposed Model: The BlockPort AI Architecture"
    assert len(spec["layers"]) == 5
    assert spec["layers"][0]["section"] == "6.1"
    assert spec["layers"][4]["section"] == "6.5"

    # 2. Pipeline run endpoint
    res_run = client.post(
        "/api/architecture/pipeline/run",
        json={"scenario": "section7", "operator": "Chief_Dispatcher"},
    )
    assert res_run.status_code == 200
    run_data = res_run.json()
    assert run_data["all_layers_succeeded"] is True
    assert len(run_data["steps"]) == 5

    # 3. Pipeline latest endpoint
    res_latest = client.get("/api/architecture/pipeline/latest")
    assert res_latest.status_code == 200
    assert len(res_latest.json()["steps"]) == 5

    # 4. Layers live status endpoint
    res_layers = client.get("/api/architecture/layers")
    assert res_layers.status_code == 200
    layers_data = res_layers.json()
    assert len(layers_data["layers"]) == 5
    assert layers_data["layers"][0]["layer_number"] == 1
    assert layers_data["layers"][4]["layer_number"] == 5
