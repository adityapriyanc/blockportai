"""Tests for BlockPort AI Green Port Intelligence (report §5.5, §3 Objective 4).

Validates:
- Transparent, auditable emissions calculations across 4 scopes
- Shore power (cold ironing) auxiliary emissions reduction
- >= 5% CO2 emissions per cargo unit reduction on optimized scenarios
- Multi-objective trade-off conflict detection (e.g. time vs emissions divergence)
- Factor documentation provenance
"""
from datetime import datetime, timezone

from blockport.green.estimator import GreenPortIntelligence
from blockport.green.factors import DEFAULT_EMISSION_FACTORS, VESSEL_PROFILES
from blockport.green.tradeoffs import evaluate_tradeoffs
from blockport.models import VesselType
from blockport.twin.engine import simulate
from blockport.twin.model import TwinBerth, TwinVessel
from blockport.twin.scenarios import run_section7


def test_emission_factors_documentation():
    factors = DEFAULT_EMISSION_FACTORS
    assert factors.mdo_kg_co2_per_kg == 3.206
    assert factors.hfo_kg_co2_per_kg == 3.114
    assert factors.lng_kg_co2_per_kg == 2.750
    assert "IMO" in factors.sources["mdo_kg_co2_per_kg"]
    assert "EPA" in factors.sources["truck_diesel_kg_co2_per_litre"]
    assert VesselType.CONTAINER in VESSEL_PROFILES


def test_green_accounting_breakdown():
    green = GreenPortIntelligence()

    # Simple 1-vessel simulation
    berths = [
        TwinBerth(
            name="A1",
            terminal="Terminal A",
            length_m=350,
            depth_m=15,
            compatible_types=frozenset({VesselType.CONTAINER}),
            cranes=4,
        )
    ]
    vessels = [
        TwinVessel(
            id=1,
            name="Test Vessel",
            vessel_type=VesselType.CONTAINER,
            loa_m=300,
            draft_m=13.0,
            cargo_units=1500,
            arrival=datetime(2026, 6, 1, 8, 0, tzinfo=timezone.utc),
        )
    ]
    sim = simulate(vessels, berths)

    report = green.calculate(sim)
    bd = report.breakdown
    assert bd.total_cargo_units == 1500
    assert bd.total_co2_kg > 0
    assert bd.emissions_per_cargo_unit > 0
    assert bd.crane_handling_co2_kg > 0
    assert bd.truck_drayage_co2_kg > 0
    assert bd.berth_hoteling_co2_kg > 0
    assert len(report.energy_records) > 0


def test_shore_power_cold_ironing_reduces_hoteling_emissions():
    berths = [
        TwinBerth(
            name="A1",
            terminal="Terminal A",
            length_m=350,
            depth_m=15,
            compatible_types=frozenset({VesselType.CONTAINER}),
            cranes=4,
        )
    ]
    vessels = [
        TwinVessel(
            id=1,
            name="Vessel 1",
            vessel_type=VesselType.CONTAINER,
            loa_m=280,
            draft_m=12.0,
            cargo_units=1200,
            arrival=datetime(2026, 6, 1, 6, 0, tzinfo=timezone.utc),
        )
    ]
    sim = simulate(vessels, berths)

    green_aux = GreenPortIntelligence(use_shore_power=False)
    green_shore = GreenPortIntelligence(use_shore_power=True)

    rep_aux = green_aux.calculate(sim)
    rep_shore = green_shore.calculate(sim)

    # Shore power should significantly lower berth hoteling emissions vs onboard diesel combustion
    assert rep_shore.breakdown.berth_hoteling_co2_kg < rep_aux.breakdown.berth_hoteling_co2_kg
    assert rep_shore.electricity_kwh > rep_aux.electricity_kwh


def test_section_7_emissions_reduction_exceeds_target():
    """Verify Section 7 benchmark achieves >= 5% CO2 emissions per cargo unit reduction."""
    s7 = run_section7()
    sim_a = s7["option_a"]
    sim_b = s7["option_b"]

    green = GreenPortIntelligence()
    comparison = green.compare_to_baseline(sim_a, sim_b)

    # In Option B, waiting time was eliminated (12h wait -> 0h) AND Terminal B is 12 miles closer
    assert comparison.reduction_pct >= 5.0
    assert comparison.met_target is True
    assert comparison.total_co2_saved_kg > 0
    assert "Emissions intensity decreased" in comparison.explanation


def test_tradeoff_divergence_analysis():
    s7 = run_section7()
    sim_a = s7["option_a"]
    sim_b = s7["option_b"]

    to = evaluate_tradeoffs(sim_a, sim_b, candidate_label="Option B")
    assert to.time_delta_h < 0  # time saved
    assert to.emissions_delta_kg < 0  # emissions saved
    assert to.cost_delta_usd < 0  # cost saved
    assert to.conflict_detected is False
    assert len(to.underlying_assumptions) > 0
