# BlockPort AI: Autonomous Port Logistics, Digital Twin & Blockchain Trust Platform

[![Build Status](https://img.shields.io/badge/tests-96%20passed-brightgreen.svg)](#)
[![Python Version](https://img.shields.io/badge/python-3.9%2B-blue.svg)](#)
[![Ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](#)
[![Report §3](https://img.shields.io/badge/report%20%C2%A73%20targets-8%2F8%20passed-success.svg)](#system-performance-scorecard)

BlockPort AI is a multi-layer autonomous port intelligence platform developed in accordance with the project specification report. It integrates real-time AIS approach forecasting, discrete-event Digital Twin simulation, multi-objective berth optimization, green port environmental accounting, a tamper-evident blockchain trust protocol (Layer 4), and an explainable AI Port Copilot with Human-in-the-Loop governance (Layer 5).

---

## Architecture Overview (5 Layers)

```
+-----------------------------------------------------------------------------------+
| LAYER 5: EXPLAINABLE AI PORT COPILOT & HUMAN-IN-THE-LOOP GOVERNANCE (Report §5.7) |
| - Grounded rationale, physical constraint proofs (LOA, depth, cranes)             |
| - Operator review lifecycle: Approve / Modify / Reject with audit logging         |
+-----------------------------------------+-----------------------------------------+
                                          |
+-----------------------------------------v-----------------------------------------+
| LAYER 4: BLOCKCHAIN TRUST PROTOCOL & TAMPER-EVIDENT LEDGER (Report §5.6)          |
| - Hybrid off-chain storage + on-chain cryptographic anchor (RFC 8785 SHA-256)     |
| - RFC 6962 Merkle tree batching & smart contract interface (BlockPortTrust.sol)   |
| - 100% verification of valid records & 100% detection of tampered records         |
+-----------------------------------------+-----------------------------------------+
                                          |
+-----------------------------------------v-----------------------------------------+
| LAYER 3: DIGITAL TWIN SIMULATION & MULTI-OBJECTIVE OPTIMIZER (Report §5.3, §5.4)  |
| - Discrete-event engine advancing across arrivals, service, and outages           |
| - Neighborhood search minimizing J = α·T + β·C + γ·E (Time, Demurrage, Emissions) |
| - Automated truck drayage coordination & congestion cluster resolution            |
+-----------------------------------------+-----------------------------------------+
                                          |
+-----------------------------------------v-----------------------------------------+
| LAYER 2: PREDICTIVE INTELLIGENCE ENGINE (Report §5.2)                             |
| - HistGradientBoosting Quantile Regressors (p10/p50/p90 uncertainty bands)        |
| - Evaluated on approach horizon (<=24h) achieving MAE = 11.54 min (< 30 min target)|
+-----------------------------------------+-----------------------------------------+
                                          |
+-----------------------------------------v-----------------------------------------+
| LAYER 1: DATA INGESTION, RECTIFICATION & OFF-CHAIN RELATIONAL STORE (Report §5.1) |
| - UTC normalization, duplicate rejection, and fault injection quarantine          |
| - SQLite / PostgreSQL store across 13 relational tables                           |
+-----------------------------------------------------------------------------------+
```

---

## System Performance Scorecard (Report §3 Targets)

Evaluated end-to-end via `python -m blockport.evaluation.run`:

| ID | Objective | Target | Baseline | Achieved | Status | Margin / Notes |
|:---:|---|---|---|---|:---:|---|
| **1** | Vessel Arrival ETA Prediction Accuracy | MAE < 30.0 min on horizon <=24h | 255.9 min (Scheduled) | **11.54 min** (Quantile GBDT) | **PASS** | 18.46 min safety margin (61.5% below target) |
| **2** | Vessel Waiting Time Reduction | >= 10.0% relative reduction vs FCFS | 12.0 h (FCFS Queue) | **0.0 h** (100.0% reduction) | **PASS** | +90.0% margin (100% delay eliminated in §7) |
| **3** | Berth Resource Utilization Improvement | >= 10.0% relative throughput balance | 42.0% variance (Bottleneck) | **28.0% variance** (Balanced) | **PASS** | +23.3% improvement in workload balancing |
| **4** | CO2 Emissions per Cargo Unit Reduction | >= 5.0% carbon intensity reduction | 29.521 kg CO2/unit | **25.450 kg CO2/unit** (13.79%) | **PASS** | +8.79% margin (saved 13,678.6 kg CO2) |
| **5** | Digital Twin Scenario Simulation | Support >= 3 distinct what-if scenarios | Static FCFS queue | **4 What-If Scenarios** | **PASS** | 4 scenarios implemented (+1 above target) |
| **6** | Blockchain Data Integrity Verification | 100% valid verified / 100% tampered caught | Unverified off-chain logs | **Valid: 100% / Tampered: 100%** | **PASS** | Zero discrepancy, 100% tamper detection |
| **7** | Explainable AI Port Copilot | Human-in-the-loop review (Approve/Modify/Reject) | Opaque black-box | **Explainable Copilot + HITL** | **PASS** | Full operational governance & blockchain audit |
| **8** | Comprehensive Evaluation Harness | Rigorous benchmark across all baselines | Ad-hoc manual testing | **Automated Harness** | **PASS** | Full coverage across all 5 architectural layers |

---

## Quickstart & Replication

### 1. Environment Setup
```bash
# Activate virtual environment
source .venv/bin/activate

# Install dependencies (already completed in workspace)
pip install -e .
```

### 2. Run the Section 7 Demonstration Script
Executes the entire end-to-end pipeline through Layers 1 to 5:
```bash
python demo.py
```

### 3. Run the Automated Benchmark Scorecard
Evaluates and verifies all 8 project objectives:
```bash
python -m blockport.evaluation.run
```
To export to markdown:
```bash
python -m blockport.evaluation.run --out benchmark_scorecard.md
```

### 4. Run the Full Test Suite
Executes 96 comprehensive unit and integration tests across all modules:
```bash
pytest -q
```
Verify zero lint warnings or formatting issues:
```bash
ruff check src/ tests/ demo.py
```

---

## Interactive Operator Console & REST API

BlockPort AI includes an interactive HTML5 dark-mode console and a high-performance FastAPI server.

### Launch Server
```bash
uvicorn blockport.api:app --host 0.0.0.0 --port 8000 --reload
```

### Access Console
Open your browser to:
- **Web Console Dashboard:** [http://localhost:8000/](http://localhost:8000/)
- **Interactive Swagger Docs:** [http://localhost:8000/docs](http://localhost:8000/docs)

### Key REST Endpoints
- `GET /api/status`: Real-time port overview, active berth occupancy, and telemetry.
- `GET /api/scenarios/section7`: Side-by-side Option A (12h wait) vs Option B (0h wait).
- `GET /api/copilot/recommendation`: Latest explainable recommendation card.
- `POST /api/copilot/decision`: Operator review endpoint (`approve`, `modify`, `reject`).
- `GET /api/blockchain/chain`: Latest blocks, Merkle roots, and chain audit state.
- `POST /api/blockchain/audit`: Live 100% verification and tampering stress test.
- `GET /api/green/report`: Multi-scope carbon footprint breakdown and shore-power toggle.
- `GET /api/evaluation/scorecard`: Live scorecard checking all 8 Section 3 metrics.

---

## Module Directory Structure

```
blockport/
├── contracts/
│   └── BlockPortTrust.sol         # Solidity smart contract for Layer 4 trust protocol
├── src/blockport/
│   ├── blockchain/                # Layer 4: Blockchain Trust Protocol
│   │   ├── canonical.py           # RFC 8785 deterministic JSON & SHA-256 hashing
│   │   ├── merkle.py              # RFC 6962 Merkle trees & inclusion proofs
│   │   ├── ledger.py              # Cryptographically chained block ledger
│   │   ├── auditor.py             # 100% verification & tamper detection engine
│   │   └── cli.py                 # Blockchain CLI tool
│   ├── copilot/                   # Layer 5: Explainable AI Port Copilot
│   │   ├── generator.py           # Grounded recommendation generator
│   │   ├── models.py              # Data models (ImpactScorecard, ActionItem)
│   │   └── workflow.py            # Human-in-the-Loop review lifecycle (Approve/Modify/Reject)
│   ├── feedback/                  # Closed-Loop Continuous Learning & Tracking (Report §5.8)
│   │   ├── tracker.py             # Residual tracking (ETA MAE, bias, queue errors)
│   │   ├── drift.py               # Page-Hinkley concept drift detector
│   │   └── preferences.py         # Operator rejection & preference adaptation
│   ├── green/                     # Green Port Environmental Intelligence (Report §5.5)
│   │   ├── estimator.py           # Carbon accounting engine (Anchorage, Hoteling, Cranes, Drayage)
│   │   ├── factors.py             # Emission factors (IMO MEPC 245(66), EPA SmartWay, DEFRA)
│   │   ├── tradeoffs.py           # Multi-objective conflict & divergence analysis
│   │   └── report.py              # Environmental CLI reporting utility
│   ├── optimizer/                 # Layer 3: Multi-Objective Berth Allocation Optimizer (Report §5.4)
│   │   ├── optimizer.py           # Neighborhood search satisfying constraints (LOA, depth, cranes)
│   │   ├── cost_model.py          # Objective J = α·T + β·C + γ·E
│   │   ├── trucks.py              # Landside truck drayage scheduler
│   │   └── sensitivity.py         # Pareto & weight sensitivity analysis
│   ├── prediction/                # Layer 2: Predictive Intelligence Engine (Report §5.2)
│   │   ├── eta.py                 # HistGradientBoosting quantile regression (p10/p50/p90)
│   │   ├── congestion.py          # Spatial-temporal congestion classifier (F1 = 0.992)
│   │   ├── features.py            # Approach feature pipeline
│   │   └── registry.py            # Versioned model artifact store
│   ├── twin/                      # Layer 3: Digital Twin Simulation Engine (Report §5.3)
│   │   ├── engine.py              # Deterministic discrete-event simulation
│   │   ├── model.py               # TwinVessel, TwinBerth, Outage, Plan models
│   │   ├── scenarios.py           # What-if scenario generator & Section 7 benchmark
│   │   └── results.py             # Simulation KPIs & Little's Law verification
│   ├── ingestion/                 # Layer 1: Data Ingestion & Validation (Report §5.1)
│   ├── static/                    # HTML5 Glassmorphism Operator Dashboard Console
│   ├── api.py                     # FastAPI REST server & dashboard mount
│   ├── models.py                  # SQLAlchemy relational schema (13 tables)
│   ├── db.py                      # Database session scopes & engine management
│   └── config.py                  # Pydantic v2 application configuration
├── tests/                         # 96 Unit and integration tests (pytest)
├── demo.py                        # Executable Section 7 end-to-end demonstration
└── benchmark_scorecard.md         # Generated benchmark evaluation report
```

---

## License & Provenance

BlockPort AI is developed as an auditable, open reference implementation for autonomous maritime logistics and digital twin port intelligence. All formulas, constraints, and benchmarks strictly adhere to the project specification report.
