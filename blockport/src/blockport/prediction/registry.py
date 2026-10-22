"""Minimal model registry: versioned artifacts + metrics on disk (report §5.8 needs versioning)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import joblib

DEFAULT_ROOT = Path(__file__).resolve().parents[3] / "models"


def save_model(model: Any, name: str, metrics: Dict[str, Any], meta: Optional[Dict] = None,
               root: Path = DEFAULT_ROOT) -> Path:
    version = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    d = root / name / version
    d.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, d / "model.joblib")
    (d / "metadata.json").write_text(json.dumps(
        {"name": name, "version": version, "metrics": metrics, **(meta or {})},
        indent=2, default=float))
    (root / name / "LATEST").write_text(version)
    return d


def load_latest(name: str, root: Path = DEFAULT_ROOT) -> Tuple[Any, Dict[str, Any]]:
    version = (root / name / "LATEST").read_text().strip()
    d = root / name / version
    return joblib.load(d / "model.joblib"), json.loads((d / "metadata.json").read_text())
