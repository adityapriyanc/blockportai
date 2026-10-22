"""CLI interface for the BlockPort Blockchain Trust Protocol (report §5.6).

    python -m blockport.blockchain.cli benchmark
    python -m blockport.blockchain.cli chain-status
"""
from __future__ import annotations

import argparse
import json

from .auditor import BlockchainAuditor
from .canonical import sha256_hash
from .ledger import BlockPortLedger


def sample_records():
    return [
        (
            "APPROVE_PLAN",
            "approvals",
            101,
            {
                "operator": "harbor_master_davis",
                "decision": "APPROVED",
                "timestamp": "2026-03-03T09:15:00Z",
                "plan_id": "opt_2026_03_03_vessel3",
                "assigned_berth": "B1",
            },
        ),
        (
            "VESSEL_DOCK",
            "port_calls",
            101,
            {
                "vessel_id": 3,
                "vessel_name": "MV Delayed",
                "berth": "B1",
                "timestamp": "2026-03-03T08:00:00Z",
                "draft_m": 12.0,
                "loa_m": 300.0,
            },
        ),
        (
            "VESSEL_DEPART",
            "port_calls",
            101,
            {
                "vessel_id": 3,
                "departure_time": "2026-03-03T20:00:00Z",
                "service_hours": 12.0,
                "cranes_used": 3,
                "cargo_units": 960,
            },
        ),
        (
            "EMISSIONS_CERT",
            "energy_records",
            501,
            {
                "vessel_id": 3,
                "anchorage_waiting_hours": 0.0,
                "co2_kg": 28416.0,
                "cargo_units": 960,
                "emissions_per_cargo_unit": 29.6,
                "auditor_signature": "cert_auth_green_port_iso14064",
            },
        ),
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="BlockPort AI Blockchain Trust CLI")
    parser.add_argument("command", choices=["benchmark", "chain-status", "hash"])
    parser.add_argument("--payload", help="JSON payload to hash", default="{}")
    args = parser.parse_args()

    ledger = BlockPortLedger()

    if args.command == "hash":
        data = json.loads(args.payload)
        h = sha256_hash(data)
        print(f"Canonical Hash: {h}")
        return

    if args.command == "benchmark":
        auditor = BlockchainAuditor(ledger)
        report = auditor.run_benchmark_suite(sample_records())
        print(json.dumps(
            {
                "valid_tested": report.total_valid_tested,
                "valid_verified": report.valid_verified,
                "valid_verification_rate_pct": report.valid_verification_rate_pct,
                "tampered_tested": report.total_tampered_tested,
                "tampered_detected": report.tampered_detected,
                "tampered_detection_rate_pct": report.tampered_detection_rate_pct,
                "target_met": report.target_met,
                "summary": report.summary,
            },
            indent=2,
        ))
        valid_chain, chain_msg = ledger.verify_chain_integrity()
        print(f"\nLedger Chain Audit: {chain_msg} (Chain Valid: {valid_chain})")
        return

    if args.command == "chain-status":
        valid_chain, chain_msg = ledger.verify_chain_integrity()
        print(f"Blocks in chain: {len(ledger.blocks)}")
        print(f"Latest block hash: {ledger.latest_block.block_hash}")
        print(f"Integrity status: {chain_msg}")


if __name__ == "__main__":
    main()
