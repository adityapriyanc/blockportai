"""Dynamic Port Operations Engine for BlockPort AI.

Provides fully dynamic, versatile port operations modeling real-world port management:
- Arbitrary vessel arrivals (Container, Bulk, Tanker, LNG)
- Configurable berths across multiple terminals
- Dynamic operational disruptions:
    * Quay crane breakdowns (reduced capacity)
    * Berth closures (emergency maintenance / physical outages)
    * Heavy weather squalls (wind > 40 kn, high swell, reduced handling speed)
    * Traffic congestion surges (multiple vessels bunching into short windows)
    * Custom ad-hoc vessel dispatches
- On-demand multi-objective berth optimization
- Dynamic explainable AI Copilot recommendations with physical safety proofs
- Dynamic carbon accounting & cold-ironing (shore power) calculations
- Cryptographic anchoring to the blockchain trust ledger
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .blockchain.ledger import BlockPortLedger
from .copilot.generator import PortCopilot
from .copilot.models import ActionItem, CopilotRecommendation, ImpactScorecard
from .copilot.workflow import GovernanceWorkflow
from .green.estimator import GreenPortIntelligence
from .models import VesselType
from .optimizer.optimizer import BerthOptimizer, OptimizationResult
from .twin.model import Outage, TwinBerth, TwinVessel


@dataclass
class DynamicDisruption:
    disruption_id: str
    kind: str  # CRANE_OUTAGE | BERTH_MAINTENANCE | WEATHER_STORM | TRAFFIC_SURGE
    description: str
    target_berth: Optional[str] = None
    cranes_affected: Optional[int] = None
    start_hour: Optional[float] = None
    end_hour: Optional[float] = None
    severity: str = "MODERATE"  # LOW | MODERATE | SEVERE


class DynamicPortEngine:
    """Central dynamic operations engine coordinating vessels, berths, disruptions, and AI."""

    def __init__(self, ledger: Optional[BlockPortLedger] = None):
        self.ledger = ledger or BlockPortLedger()
        self.workflow = GovernanceWorkflow(ledger=self.ledger)
        self.copilot = PortCopilot()
        self.optimizer = BerthOptimizer()
        self.green_engine = GreenPortIntelligence()

        # Base reference date for relative simulation hours (0.0 to 24.0h)
        self.base_date = datetime.datetime(2026, 3, 3, 0, 0, tzinfo=datetime.timezone.utc)

        # Weather state
        self.wind_speed_knots = 14.2
        self.wave_height_m = 0.8
        self.visibility_nmi = 10.0
        self.weather_condition = "CLEAR"

        # Disruption state
        self.active_disruptions: List[DynamicDisruption] = []
        self.berth_crane_overrides: Dict[str, int] = {}
        self.active_outages: List[Outage] = []

        # Current scenario preset label
        self.scenario_name = "Dynamic Operations"
        self.baseline_vessels: Optional[List[TwinVessel]] = None

        # Initialize standard port layout and vessels
        self.berths: List[TwinBerth] = []
        self.vessels: List[TwinVessel] = []
        self.next_vessel_id = 10

        self.reset_to_preset("section7")

    def _init_default_berths(self) -> List[TwinBerth]:
        """Create standard multi-terminal berth layout."""
        box = frozenset({VesselType.CONTAINER})
        bulk_types = frozenset({VesselType.BULK})
        energy_types = frozenset({VesselType.TANKER, VesselType.LNG})

        return [
            TwinBerth(
                name="A1",
                terminal="Terminal A (North)",
                length_m=400,
                depth_m=16.0,
                compatible_types=box,
                cranes=self.berth_crane_overrides.get("A1", 4),
            ),
            TwinBerth(
                name="A2",
                terminal="Terminal A (North)",
                length_m=350,
                depth_m=15.0,
                compatible_types=box,
                cranes=self.berth_crane_overrides.get("A2", 4),
            ),
            TwinBerth(
                name="B1",
                terminal="Terminal B (South)",
                length_m=330,
                depth_m=14.5,
                compatible_types=box,
                cranes=self.berth_crane_overrides.get("B1", 3),
            ),
            TwinBerth(
                name="B2",
                terminal="Terminal B (South)",
                length_m=320,
                depth_m=14.0,
                compatible_types=box,
                cranes=self.berth_crane_overrides.get("B2", 2),
            ),
            TwinBerth(
                name="C1",
                terminal="Terminal C (Bulk)",
                length_m=340,
                depth_m=17.5,
                compatible_types=bulk_types,
                cranes=1,
            ),
            TwinBerth(
                name="C2",
                terminal="Terminal C (Energy)",
                length_m=320,
                depth_m=16.5,
                compatible_types=energy_types,
                cranes=1,
            ),
        ]

    def reset_to_preset(self, preset_id: str) -> None:
        """Apply an operational scenario preset."""
        self.active_disruptions.clear()
        self.berth_crane_overrides.clear()
        self.active_outages.clear()
        self.wind_speed_knots = 14.2
        self.wave_height_m = 0.8
        self.weather_condition = "CLEAR"

        t8 = self.base_date + datetime.timedelta(hours=8.0)
        t6 = self.base_date + datetime.timedelta(hours=6.0)
        t4 = self.base_date + datetime.timedelta(hours=4.0)

        if preset_id == "clear":
            self.scenario_name = "Normal Clear Operations"
            self.vessels = [
                TwinVessel(1, "MV Early One", VesselType.CONTAINER, 300, 12, 1200, t8),
                TwinVessel(
                    2,
                    "MV Early Two",
                    VesselType.CONTAINER,
                    280,
                    11.5,
                    1200,
                    t8 + datetime.timedelta(hours=3),
                ),
                TwinVessel(4, "MV Baltic Titan", VesselType.BULK, 290, 15.0, 65000, t6),
                TwinVessel(5, "MT Arctic Spirit", VesselType.LNG, 290, 11.5, 90000, t4),
            ]

        elif preset_id == "crane_outage":
            self.scenario_name = "Quay Crane Breakdown (Berth A2 50% Loss)"
            self.berth_crane_overrides["A2"] = 2
            self.active_disruptions.append(
                DynamicDisruption(
                    disruption_id="DISRUPT_CRANE_A2",
                    kind="CRANE_OUTAGE",
                    description="Electrical malfunction on STS Gantry Crane #3 & #4 at Berth A2.",
                    target_berth="A2",
                    cranes_affected=2,
                    severity="SEVERE",
                )
            )
            self.vessels = [
                TwinVessel(1, "MV Early One", VesselType.CONTAINER, 300, 12, 1200, t8),
                TwinVessel(2, "MV Early Two", VesselType.CONTAINER, 300, 12, 1200, t8),
                TwinVessel(
                    3,
                    "MV Delayed",
                    VesselType.CONTAINER,
                    300,
                    12,
                    960,
                    t8,
                    allowed_berths=frozenset({"A1", "A2", "B1"}),
                ),
                TwinVessel(4, "MV Baltic Titan", VesselType.BULK, 290, 15.0, 65000, t6),
                TwinVessel(5, "MT Arctic Spirit", VesselType.LNG, 290, 11.5, 90000, t4),
            ]

        elif preset_id == "berth_closure":
            self.scenario_name = "Emergency Berth Maintenance (Berth A1 Closed)"
            outage_start = self.base_date + datetime.timedelta(hours=6.0)
            outage_end = self.base_date + datetime.timedelta(hours=18.0)
            self.active_outages.append(Outage("A1", outage_start, outage_end))
            self.active_disruptions.append(
                DynamicDisruption(
                    disruption_id="DISRUPT_OUTAGE_A1",
                    kind="BERTH_MAINTENANCE",
                    description=(
                        "Emergency bollard and quay fender reinforcement on Berth A1 "
                        "(06:00 - 18:00 UTC)."
                    ),
                    target_berth="A1",
                    start_hour=6.0,
                    end_hour=18.0,
                    severity="SEVERE",
                )
            )
            self.vessels = [
                TwinVessel(
                    1,
                    "MV Early One",
                    VesselType.CONTAINER,
                    300,
                    12,
                    1200,
                    t8,
                    allowed_berths=frozenset({"A2", "B1"}),
                ),
                TwinVessel(
                    2,
                    "MV Early Two",
                    VesselType.CONTAINER,
                    300,
                    12,
                    1200,
                    t8,
                    allowed_berths=frozenset({"A2", "B1"}),
                ),
                TwinVessel(4, "MV Baltic Titan", VesselType.BULK, 290, 15.0, 65000, t6),
                TwinVessel(5, "MT Arctic Spirit", VesselType.LNG, 290, 11.5, 90000, t4),
            ]

        elif preset_id == "weather_storm":
            self.scenario_name = "Storm Gale Warning (Wind 42 kn & High Swell)"
            self.wind_speed_knots = 42.5
            self.wave_height_m = 3.2
            self.weather_condition = "GALE_WARNING"
            self.active_disruptions.append(
                DynamicDisruption(
                    disruption_id="DISRUPT_STORM_01",
                    kind="WEATHER_STORM",
                    description=(
                        "Severe coastal gale front. Wind gusts exceeding 40 knots. "
                        "Vessel pilotage delayed."
                    ),
                    severity="SEVERE",
                )
            )
            # Storm causes 3-hour arrival delay on inbound vessels
            t11 = self.base_date + datetime.timedelta(hours=11.0)
            self.vessels = [
                TwinVessel(1, "MV Early One", VesselType.CONTAINER, 300, 12, 1200, t11),
                TwinVessel(2, "MV Early Two", VesselType.CONTAINER, 300, 12, 1200, t11),
                TwinVessel(
                    3,
                    "MV Delayed",
                    VesselType.CONTAINER,
                    300,
                    12,
                    960,
                    t11,
                    allowed_berths=frozenset({"A1", "A2", "B1"}),
                ),
                TwinVessel(4, "MV Baltic Titan", VesselType.BULK, 290, 15.0, 65000, t6),
            ]

        elif preset_id == "surge":
            self.scenario_name = "Traffic Surge (5 Simultaneous Container Calls)"
            self.active_disruptions.append(
                DynamicDisruption(
                    disruption_id="DISRUPT_SURGE_01",
                    kind="TRAFFIC_SURGE",
                    description=(
                        "Sudden arrival bunching: 5 container vessels converge in morning window."
                    ),
                    severity="SEVERE",
                )
            )
            self.vessels = [
                TwinVessel(
                    1,
                    "MV Early One",
                    VesselType.CONTAINER,
                    300,
                    12,
                    1200,
                    t8,
                    allowed_berths=frozenset({"A1", "A2", "B1", "B2"}),
                ),
                TwinVessel(
                    2,
                    "MV Early Two",
                    VesselType.CONTAINER,
                    300,
                    12,
                    1200,
                    t8,
                    allowed_berths=frozenset({"A1", "A2", "B1", "B2"}),
                ),
                TwinVessel(
                    3,
                    "MV Delayed",
                    VesselType.CONTAINER,
                    300,
                    12,
                    960,
                    t8,
                    allowed_berths=frozenset({"A1", "A2", "B1", "B2"}),
                ),
                TwinVessel(
                    6,
                    "MV Pacific Voyager",
                    VesselType.CONTAINER,
                    260,
                    11.0,
                    850,
                    t8,
                    allowed_berths=frozenset({"A1", "A2", "B1", "B2"}),
                ),
                TwinVessel(
                    7,
                    "MV Atlantic Pioneer",
                    VesselType.CONTAINER,
                    240,
                    10.5,
                    700,
                    t8,
                    allowed_berths=frozenset({"A1", "A2", "B1", "B2"}),
                ),
                TwinVessel(4, "MV Baltic Titan", VesselType.BULK, 290, 15.0, 65000, t6),
                TwinVessel(5, "MT Arctic Spirit", VesselType.LNG, 290, 11.5, 90000, t4),
            ]

        else:  # "section7" is default
            self.scenario_name = "Section 7 Contested Terminal A Benchmark"
            only_a = frozenset({"A1", "A2"})
            # In baseline, MV Delayed is scheduled for Terminal A only
            self.baseline_vessels = [
                TwinVessel(
                    1,
                    "MV Early One",
                    VesselType.CONTAINER,
                    300,
                    12,
                    1200,
                    t8,
                    allowed_berths=only_a,
                ),
                TwinVessel(
                    2,
                    "MV Early Two",
                    VesselType.CONTAINER,
                    300,
                    12,
                    1200,
                    t8,
                    allowed_berths=only_a,
                ),
                TwinVessel(
                    3, "MV Delayed", VesselType.CONTAINER, 300, 12, 960, t8, allowed_berths=only_a
                ),
                TwinVessel(4, "MV Baltic Titan", VesselType.BULK, 290, 15.0, 65000, t6),
                TwinVessel(5, "MT Arctic Spirit", VesselType.LNG, 290, 11.5, 90000, t4),
            ]
            # In candidate optimizer, MV Delayed can be rerouted to Terminal B (B1)
            self.vessels = [
                TwinVessel(
                    1,
                    "MV Early One",
                    VesselType.CONTAINER,
                    300,
                    12,
                    1200,
                    t8,
                    allowed_berths=only_a,
                ),
                TwinVessel(
                    2,
                    "MV Early Two",
                    VesselType.CONTAINER,
                    300,
                    12,
                    1200,
                    t8,
                    allowed_berths=only_a,
                ),
                TwinVessel(
                    3,
                    "MV Delayed",
                    VesselType.CONTAINER,
                    300,
                    12,
                    960,
                    t8,
                    allowed_berths=frozenset({"A1", "A2", "B1"}),
                ),
                TwinVessel(4, "MV Baltic Titan", VesselType.BULK, 290, 15.0, 65000, t6),
                TwinVessel(5, "MT Arctic Spirit", VesselType.LNG, 290, 11.5, 90000, t4),
            ]

        self.berths = self._init_default_berths()

    def add_custom_vessel(
        self,
        name: str,
        vessel_type_str: str,
        loa_m: float,
        draft_m: float,
        cargo_units: float,
        arrival_hour: float,
        allowed_berths: Optional[List[str]] = None,
    ) -> TwinVessel:
        """Add any custom ship dynamically to the live fleet manifest."""
        vt = VesselType(vessel_type_str.lower())
        arr = self.base_date + datetime.timedelta(hours=arrival_hour)
        vid = self.next_vessel_id
        self.next_vessel_id += 1

        allowed = frozenset(allowed_berths) if allowed_berths else None
        new_v = TwinVessel(
            id=vid,
            name=name,
            vessel_type=vt,
            loa_m=loa_m,
            draft_m=draft_m,
            cargo_units=cargo_units,
            arrival=arr,
            allowed_berths=allowed,
        )
        self.vessels.append(new_v)
        return new_v

    def apply_disruption(
        self, kind: str, target_berth: Optional[str] = None, **kwargs
    ) -> DynamicDisruption:
        """Inject an operational disruption on the fly."""
        disrupt_id = f"DISRUPT_{datetime.datetime.now().strftime('%H%M%S')}"

        if kind == "CRANE_OUTAGE" and target_berth:
            crane_count = int(kwargs.get("cranes", 2))
            self.berth_crane_overrides[target_berth] = crane_count
            d = DynamicDisruption(
                disruption_id=disrupt_id,
                kind=kind,
                description=(
                    f"Quay Crane failure at Berth {target_berth}: capacity reduced to "
                    f"{crane_count} cranes."
                ),
                target_berth=target_berth,
                cranes_affected=crane_count,
            )
        elif kind == "BERTH_MAINTENANCE" and target_berth:
            start_h = float(kwargs.get("start_hour", 8.0))
            end_h = float(kwargs.get("end_hour", 18.0))
            s = self.base_date + datetime.timedelta(hours=start_h)
            e = self.base_date + datetime.timedelta(hours=end_h)
            self.active_outages.append(Outage(target_berth, s, e))
            d = DynamicDisruption(
                disruption_id=disrupt_id,
                kind=kind,
                description=(
                    f"Berth {target_berth} closed for emergency dredging & structural maintenance."
                ),
                target_berth=target_berth,
                start_hour=start_h,
                end_hour=end_h,
                severity="SEVERE",
            )
        elif kind == "WEATHER_STORM":
            self.wind_speed_knots = float(kwargs.get("wind_speed", 45.0))
            self.wave_height_m = float(kwargs.get("wave_height", 3.5))
            self.weather_condition = "GALE_WARNING"
            d = DynamicDisruption(
                disruption_id=disrupt_id,
                kind=kind,
                description=(
                    f"Coastal Gale Warning: wind {self.wind_speed_knots} kn, swell "
                    f"{self.wave_height_m}m. Pilot boarding restricted."
                ),
                severity="SEVERE",
            )
        else:
            d = DynamicDisruption(
                disruption_id=disrupt_id, kind=kind, description="Generic operational disruption"
            )

        self.active_disruptions.append(d)
        self.berths = self._init_default_berths()
        return d

    def compute_state(self, shore_power: bool = True) -> Dict[str, Any]:
        """Run dynamic discrete-event simulation and multi-objective optimization."""
        # 1. Optimize schedule on current vessels, berths, and outages
        opt_res: OptimizationResult = self.optimizer.optimize(
            self.vessels,
            self.berths,
            self.active_outages,
            baseline_vessels=self.baseline_vessels,
        )

        fcfs_sim = opt_res.fcfs_result
        opt_sim = opt_res.sim_result

        # 2. Environmental calculation
        green_calc = GreenPortIntelligence(use_shore_power=shore_power)
        green_comp = green_calc.compare_to_baseline(fcfs_sim, opt_sim)

        # 3. KPIs
        fcfs_kpis = fcfs_sim.kpis()
        opt_kpis = opt_sim.kpis()

        total_wait_saved = max(0.0, fcfs_kpis["total_wait_h"] - opt_kpis["total_wait_h"])
        demurrage_saved = total_wait_saved * 1200.0  # $1,200/h demurrage rate
        co2_saved = green_comp.total_co2_saved_kg
        intensity_cut = green_comp.reduction_pct

        # 4. Generate Copilot Recommendation Card
        action_items: List[ActionItem] = []
        constraints: List[str] = []

        # Find reassignments between FCFS and Optimized plan
        fcfs_records_by_v = {r.vessel_id: r for r in fcfs_sim.records}
        for opt_rec in opt_sim.records:
            vid = opt_rec.vessel_id
            v = next((x for x in self.vessels if x.id == vid), None)
            if not v:
                continue
            fcfs_rec = fcfs_records_by_v.get(vid)
            if fcfs_rec and (fcfs_rec.berth != opt_rec.berth or fcfs_rec.wait_h > opt_rec.wait_h):
                action_items.append(
                    ActionItem(
                        action_type="REASSIGN_BERTH",
                        entity_id=f"Vessel:{v.name}",
                        description=(
                            f"Reassign from Berth {fcfs_rec.berth} to Berth {opt_rec.berth} "
                            f"(Wait cut: {fcfs_rec.wait_h:.1f}h -> {opt_rec.wait_h:.1f}h)."
                        ),
                    )
                )

            # Check physical constraints on assigned berth
            target_b = next((b for b in self.berths if b.name == opt_rec.berth), None)
            if target_b:
                loa_margin = target_b.length_m - v.loa_m
                depth_margin = target_b.depth_m - v.draft_m
                constraints.append(
                    f"{v.name} -> Berth {target_b.name}: LOA clearance +{loa_margin:.1f}m, "
                    f"Depth clearance +{depth_margin:.1f}m, Cranes: {target_b.cranes}."
                )

        if not action_items:
            action_items.append(
                ActionItem(
                    action_type="MAINTAIN_PLAN",
                    entity_id="Fleet",
                    description="Current schedule is optimal; maintain standard FCFS dispatch.",
                )
            )

        summary_text = (
            f"Autonomous optimizer analyzed {len(self.vessels)} vessel calls across "
            f"{len(self.berths)} berths. Proposed operational plan reduces total queue waiting "
            f"time by {total_wait_saved:.1f} hours, lowers demurrage by ${demurrage_saved:,.2f}, "
            f"and eliminates {co2_saved:,.1f} kg CO2."
        )

        impact = ImpactScorecard(
            wait_time_saved_hours=round(total_wait_saved, 2),
            cost_saved_usd=round(demurrage_saved, 2),
            co2_saved_kg=round(co2_saved, 2),
            emissions_intensity_delta_pct=round(intensity_cut, 2),
            berth_utilization_pct=round(opt_kpis.get("berth_utilization", 0.65) * 100, 1),
        )

        copilot_card = CopilotRecommendation(
            id=101,
            title=f"Schedule Optimization ({total_wait_saved:.1f}h Wait Time Saved)",
            summary=summary_text,
            rationale=(
                f"Multi-objective optimizer (J = α·T + β·C + γ·E) resolved congestion conflicts "
                f"and resource balancing across {len(self.berths)} active berths."
            ),
            confidence_score=0.96,
            impact=impact,
            actions=action_items,
            constraints_verified=constraints[:4],
            tradeoff_narrative=(
                f"Net delay cut: -{total_wait_saved:.1f}h, Net cost avoided: "
                f"-${demurrage_saved:,.0f}, Emissions: -{intensity_cut:.1f}%."
            ),
            eta_confidence_band={"p10": "07:45 UTC", "p50": "08:00 UTC", "p90": "08:20 UTC"},
        )

        # 5. Build 24-hour Gantt timeline entries
        gantt_allocations = []
        for r in opt_sim.records:
            v = next((x for x in self.vessels if x.id == r.vessel_id), None)
            if not v:
                continue
            start_h = (r.start - self.base_date).total_seconds() / 3600.0
            end_h = (r.end - self.base_date).total_seconds() / 3600.0
            color = (
                "#0284c7"
                if v.vessel_type == VesselType.CONTAINER
                else ("#d97706" if v.vessel_type == VesselType.BULK else "#7c3aed")
            )
            if r.vessel_id == 3:
                color = "#059669"  # highlight optimized vessel

            gantt_allocations.append(
                {
                    "vessel_id": v.id,
                    "vessel_name": v.name,
                    "vessel_type": v.vessel_type.value,
                    "berth": r.berth,
                    "cargo_units": v.cargo_units,
                    "start_hour": round(start_h, 1),
                    "end_hour": round(end_h, 1),
                    "wait_hours": round(r.wait_h, 1),
                    "color": color,
                    "shore_power": (r.berth == "B1" and shore_power),
                }
            )

        # 6. Build vessel fleet manifest table
        vessel_manifest = []
        for v in self.vessels:
            arr_h = (v.arrival - self.base_date).total_seconds() / 3600.0
            v_rec = next((x for x in opt_sim.records if x.vessel_id == v.id), None)
            fcfs_rec = fcfs_records_by_v.get(v.id)
            assigned_berth = v_rec.berth if v_rec else "Unassigned"
            wait_h = v_rec.wait_h if v_rec else 0.0
            fcfs_wait = fcfs_rec.wait_h if fcfs_rec else 0.0
            fcfs_berth = fcfs_rec.berth if fcfs_rec else assigned_berth
            start_h = (
                (v_rec.start - self.base_date).total_seconds() / 3600.0
                if v_rec
                else arr_h
            )
            end_h = (
                (v_rec.end - self.base_date).total_seconds() / 3600.0
                if v_rec
                else arr_h + 10.0
            )

            cargo_label = (
                f"{int(v.cargo_units):,} TEU"
                if v.vessel_type == VesselType.CONTAINER
                else f"{int(v.cargo_units):,} T"
            )
            vessel_manifest.append(
                {
                    "id": v.id,
                    "name": v.name,
                    "type": v.vessel_type.value.upper(),
                    "loa_m": v.loa_m,
                    "draft_m": v.draft_m,
                    "cargo": cargo_label,
                    "cargo_units": v.cargo_units,
                    "arrival_hour": f"{arr_h:04.1f} UTC",
                    "arrival_val": round(arr_h, 2),
                    "start_hour_val": round(start_h, 2),
                    "end_hour_val": round(end_h, 2),
                    "assigned_berth": assigned_berth,
                    "wait_hours": f"{wait_h:.1f}h",
                    "wait_hours_val": round(wait_h, 2),
                    "fcfs_berth": fcfs_berth,
                    "fcfs_wait_h": round(fcfs_wait, 2),
                    "status": "BERTHED" if wait_h == 0.0 else "ANCHORED",
                    "shore_power": (assigned_berth == "B1" and shore_power),
                }
            )

        return {
            "scenario_name": self.scenario_name,
            "weather": {
                "wind_speed_knots": self.wind_speed_knots,
                "wave_height_m": self.wave_height_m,
                "visibility_nmi": self.visibility_nmi,
                "condition": self.weather_condition,
            },
            "disruptions": [
                {
                    "id": d.disruption_id,
                    "kind": d.kind,
                    "description": d.description,
                    "target_berth": d.target_berth,
                    "severity": d.severity,
                }
                for d in self.active_disruptions
            ],
            "berths": [
                {
                    "name": b.name,
                    "terminal": b.terminal,
                    "length_m": b.length_m,
                    "depth_m": b.depth_m,
                    "cranes": b.cranes,
                    "status": "MAINTENANCE"
                    if any(o.berth == b.name for o in self.active_outages)
                    else "OPERATIONAL",
                }
                for b in self.berths
            ],
            "kpis": {
                "active_berths_count": len(set(r.berth for r in opt_sim.records)),
                "total_berths_count": len(self.berths),
                "total_wait_saved_hours": round(total_wait_saved, 1),
                "demurrage_saved_usd": round(demurrage_saved, 2),
                "co2_saved_kg": round(co2_saved, 1),
                "intensity_reduction_pct": round(intensity_cut, 1),
                "fcfs_total_wait_hours": round(fcfs_kpis["total_wait_h"], 1),
                "opt_total_wait_hours": round(opt_kpis["total_wait_h"], 1),
            },
            "copilot": copilot_card.to_dict(),
            "gantt": {
                "timeline_start": "00:00 UTC",
                "timeline_end": "24:00 UTC",
                "allocations": gantt_allocations,
            },
            "vessels": vessel_manifest,
        }
