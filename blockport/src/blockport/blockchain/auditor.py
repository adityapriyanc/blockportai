"""Audit and data integrity verification engine (report §5.6, §3 Objective 6).

Evaluates off-chain database state against the immutable blockchain ledger to prove:
1. Valid record verification rate = 100%
2. Tampered record detection rate = 100%
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .canonical import hash_record
from .ledger import BlockPortLedger


@dataclass(frozen=True)
class RecordAuditResult:
    subject_table: str
    subject_id: int
    record_type: str
    computed_hash: str
    is_valid: bool
    tampered: bool
    anchored_on_chain: bool
    tx_hash: Optional[str]
    details: str


@dataclass(frozen=True)
class IntegrityBenchmarkReport:
    total_valid_tested: int
    valid_verified: int
    valid_verification_rate_pct: float
    total_tampered_tested: int
    tampered_detected: int
    tampered_detection_rate_pct: float
    target_met: bool  # True if valid == 100% and tampered == 100% (report §3 obj 6)
    summary: str


class BlockchainAuditor:
    """Verifies off-chain operational data against on-chain cryptographic anchors."""

    def __init__(self, ledger: BlockPortLedger):
        self.ledger = ledger

    def audit_record(
        self,
        record_type: str,
        subject_table: str,
        subject_id: int,
        payload: Dict[str, Any],
        expected_tx_hash: Optional[str] = None,
    ) -> RecordAuditResult:
        """Audit an individual record against the ledger."""
        computed_h = hash_record(record_type, payload)
        tx = self.ledger.get_by_record_hash(computed_h)

        if tx is None:
            # Hash does not exist on chain.
            # If an expected_tx_hash was provided, that means the record was anchored earlier
            # but the current payload hash diverged (evidence of off-chain database tampering).
            if expected_tx_hash is not None:
                expected_tx = self.ledger.get_by_tx_hash(expected_tx_hash)
                if expected_tx is not None:
                    return RecordAuditResult(
                        subject_table=subject_table,
                        subject_id=subject_id,
                        record_type=record_type,
                        computed_hash=computed_h,
                        is_valid=False,
                        tampered=True,
                        anchored_on_chain=True,
                        tx_hash=expected_tx_hash,
                        details=(
                            f"TAMPERING DETECTED: Payload recomputed hash '{computed_h[:10]}...' "
                            f"does not match on-chain anchored hash "
                            f"'{expected_tx.record_hash[:10]}...'"
                        ),
                    )
            return RecordAuditResult(
                subject_table=subject_table,
                subject_id=subject_id,
                record_type=record_type,
                computed_hash=computed_h,
                is_valid=False,
                tampered=False,
                anchored_on_chain=False,
                tx_hash=None,
                details="Record has not been anchored on the blockchain ledger.",
            )

        # Hash was found on chain!
        if expected_tx_hash is not None and tx.tx_hash != expected_tx_hash:
            return RecordAuditResult(
                subject_table=subject_table,
                subject_id=subject_id,
                record_type=record_type,
                computed_hash=computed_h,
                is_valid=False,
                tampered=True,
                anchored_on_chain=True,
                tx_hash=tx.tx_hash,
                details=(
                    f"Transaction hash mismatch: expected {expected_tx_hash}, "
                    f"found {tx.tx_hash}"
                ),
            )

        return RecordAuditResult(
            subject_table=subject_table,
            subject_id=subject_id,
            record_type=record_type,
            computed_hash=computed_h,
            is_valid=True,
            tampered=False,
            anchored_on_chain=True,
            tx_hash=tx.tx_hash,
            details=(
                "VERIFIED: Cryptographically authenticated on block chain "
                f"(tx {tx.tx_hash[:12]})."
            ),
        )

    def run_benchmark_suite(
        self,
        test_samples: List[Tuple[str, str, int, Dict[str, Any]]],
    ) -> IntegrityBenchmarkReport:
        """Run full evaluation suite on clean vs tampered records (report §3 Objective 6)."""
        valid_tested = 0
        valid_verified = 0

        # Anchor clean records
        anchored_meta: List[Tuple[str, str, int, Dict[str, Any], str]] = []
        for rec_type, table, sid, payload in test_samples:
            h = hash_record(rec_type, payload)
            tx = self.ledger.anchor_record(
                record_type=rec_type,
                subject_table=table,
                subject_id=sid,
                record_hash=h,
            )
            anchored_meta.append((rec_type, table, sid, payload, tx.tx_hash))

        # 1. Audit all valid records
        for rec_type, table, sid, payload, tx_h in anchored_meta:
            valid_tested += 1
            res = self.audit_record(rec_type, table, sid, payload, expected_tx_hash=tx_h)
            if res.is_valid and not res.tampered:
                valid_verified += 1

        # 2. Generate and audit tampered variants
        tampered_tested = 0
        tampered_detected = 0

        tamper_mutations = [
            ("operator_tamper", lambda d: {**d, "operator": "unauthorized_actor"}),
            ("timestamp_shift", lambda d: {**d, "timestamp": "2026-12-31T23:59:59Z"}),
            ("emissions_forgery", lambda d: {**d, "co2_kg": 0.0}),
            ("cargo_manipulation", lambda d: {**d, "cargo_units": 999999}),
            ("decision_reversal", lambda d: {**d, "status": "REJECTED"}),
        ]

        for i, (rec_type, table, sid, payload, tx_h) in enumerate(anchored_meta):
            mutation_name, mutate_fn = tamper_mutations[i % len(tamper_mutations)]
            tampered_payload = mutate_fn(copy.deepcopy(payload))
            tampered_tested += 1

            audit_res = self.audit_record(
                rec_type, table, sid, tampered_payload, expected_tx_hash=tx_h
            )
            if audit_res.tampered and not audit_res.is_valid:
                tampered_detected += 1

        valid_rate = 100.0 * valid_verified / max(1, valid_tested)
        tamper_rate = 100.0 * tampered_detected / max(1, tampered_tested)
        target_met = (valid_rate == 100.0) and (tamper_rate == 100.0)

        summary = (
            f"Blockchain Integrity Benchmark (Report §3 Obj 6): "
            f"Valid verified: {valid_verified}/{valid_tested} ({valid_rate:.1f}%), "
            f"Tampered caught: {tampered_detected}/{tampered_tested} ({tamper_rate:.1f}%). "
            f"Target Status: {'PASSED (100% / 100%)' if target_met else 'FAILED'}."
        )

        return IntegrityBenchmarkReport(
            total_valid_tested=valid_tested,
            valid_verified=valid_verified,
            valid_verification_rate_pct=valid_rate,
            total_tampered_tested=tampered_tested,
            tampered_detected=tampered_detected,
            tampered_detection_rate_pct=tamper_rate,
            target_met=target_met,
            summary=summary,
        )
