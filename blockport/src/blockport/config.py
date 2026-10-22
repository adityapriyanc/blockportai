"""Typed configuration loaded from YAML (objective weights, emission factors, targets)."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "default.yaml"


class ObjectiveWeights(BaseModel):
    """Weights of J = alpha*T + beta*C + gamma*E (report §5.4)."""

    alpha: float = Field(ge=0)
    beta: float = Field(ge=0)
    gamma: float = Field(ge=0)


class EmissionFactors(BaseModel):
    marine_fuel_oil_kg_co2_per_kg_fuel: float = Field(gt=0)
    marine_diesel_kg_co2_per_kg_fuel: float = Field(gt=0)
    grid_electricity_kg_co2_per_kwh: float = Field(gt=0)
    truck_diesel_kg_co2_per_litre: float = Field(gt=0)


class Targets(BaseModel):
    """Proposed performance targets (report §3). These are goals, not guarantees."""

    eta_mae_minutes_max: float
    waiting_time_reduction_min_pct: float
    utilization_improvement_min_pct: float
    emissions_per_cargo_reduction_min_pct: float
    min_scenarios: int
    integrity_verification_rate_pct: float


class DataSettings(BaseModel):
    stale_after_minutes: int = Field(gt=0)
    database_url: str


class Settings(BaseModel):
    objective_weights: ObjectiveWeights
    emission_factors: EmissionFactors
    targets: Targets
    data: DataSettings


@lru_cache(maxsize=1)
def get_settings(path: str | None = None) -> Settings:
    """Load settings from `path`, $BLOCKPORT_CONFIG, or the bundled default."""
    cfg_path = Path(path or os.environ.get("BLOCKPORT_CONFIG") or DEFAULT_CONFIG_PATH)
    with cfg_path.open() as fh:
        return Settings.model_validate(yaml.safe_load(fh))
