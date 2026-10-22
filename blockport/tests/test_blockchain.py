"""Comprehensive tests for BlockPort AI Blockchain Trust Protocol (report §5.6, §3 Objective 6).

Verifies:
1. RFC 8785 canonical serialization determinism (key order, floats, timestamps)
2. Merkle tree construction and cryptographic inclusion proofs
3. Block chaining, hash continuity, and break-in-chain tamper detection
4. 100% verification rate on valid records and 100% detection rate on tampered records
"""
from datetime import datetime, timezone

from blockport.blockchain.auditor import BlockchainAuditor
from blockport.blockchain.canonical import canonical_json, sha256_hash
from blockport.blockchain.ledger import BlockPortLedger
from blockport.blockchain.merkle import MerkleTree


def test_canonical_json_determinism():
    # Different key insertion orders must yield byte-for-byte identical output
    d1 = {"z_key": 100, "a_key": "vessel", "nested": {"b": 2, "a": 1}}
    d2 = {"nested": {"a": 1, "b": 2}, "a_key": "vessel", "z_key": 100}

    assert canonical_json(d1) == canonical_json(d2)
    assert sha256_hash(d1) == sha256_hash(d2)


def test_canonical_json_datetime_and_float_handling():
    dt_local = datetime(2026, 3, 3, 13, 30, 0, tzinfo=timezone.utc)
    d = {"timestamp": dt_local, "fuel_litres": 1500.50000000, "int_val": 42.0}
    c_json = canonical_json(d)

    assert "2026-03-03T13:30:00Z" in c_json
    assert '"fuel_litres":1500.5' in c_json
    assert '"int_val":42' in c_json


def test_merkle_tree_construction_and_inclusion_proofs():
    leaves = [f"record_payload_{i}" for i in range(8)]
    tree = MerkleTree(leaves)

    assert len(tree.root_hex) == 64

    # Verify inclusion proofs for each leaf
    for i, leaf in enumerate(leaves):
        proof = tree.get_proof(i)
        assert len(proof) == 3  # log2(8)
        assert MerkleTree.verify_proof(leaf, proof, tree.root_hex) is True

    # Tampered leaf must fail verification
    proof_0 = tree.get_proof(0)
    assert MerkleTree.verify_proof("tampered_payload_0", proof_0, tree.root_hex) is False


def test_merkle_tree_odd_leaves_handling():
    leaves = ["leaf_1", "leaf_2", "leaf_3"]
    tree = MerkleTree(leaves)
    assert len(tree.root_hex) == 64

    for i, leaf in enumerate(leaves):
        proof = tree.get_proof(i)
        assert MerkleTree.verify_proof(leaf, proof, tree.root_hex) is True


def test_ledger_chain_continuity_and_tamper_detection():
    ledger = BlockPortLedger()
    assert len(ledger.blocks) == 1  # genesis

    tx1 = ledger.anchor_record("APPROVE_PLAN", "approvals", 1, "hash_1")
    tx2 = ledger.anchor_record("VESSEL_DOCK", "port_calls", 1, "hash_2")
    _ = ledger.anchor_record("VESSEL_DEPART", "port_calls", 1, "hash_3")

    assert len(ledger.blocks) == 4
    valid, msg = ledger.verify_chain_integrity()
    assert valid is True
    assert "4 blocks cryptographically verified" in msg

    # Retrieve by hash
    assert ledger.get_by_record_hash("hash_1") == tx1
    assert ledger.get_by_tx_hash(tx2.tx_hash) == tx2

    # Tamper with block 2 previous_hash -> must detect chain break
    original_prev = ledger.blocks[2].previous_hash
    ledger.blocks[2].previous_hash = "deadbeef" * 8
    tampered_valid, tampered_msg = ledger.verify_chain_integrity()
    assert tampered_valid is False
    assert "Chain break at block 2" in tampered_msg

    # Restore previous_hash but tamper with block transaction
    ledger.blocks[2].previous_hash = original_prev
    ledger.blocks[2].block_hash = "badhash" * 8
    corrupt_valid, corrupt_msg = ledger.verify_chain_integrity()
    assert corrupt_valid is False
    assert "Block 2 hash corruption" in corrupt_msg


def test_objective_6_benchmark_100_percent_valid_and_tampered():
    """Verify Objective 6: 100% valid verification rate AND 100% tampered detection rate."""
    ledger = BlockPortLedger()
    auditor = BlockchainAuditor(ledger)

    records = [
        (
            "APPROVE_PLAN",
            "approvals",
            10,
            {"operator": "john_doe", "status": "APPROVED", "berth": "A1"},
        ),
        (
            "VESSEL_DOCK",
            "port_calls",
            10,
            {"vessel_id": 4, "berth": "A1", "loa_m": 300.0, "draft_m": 12.5},
        ),
        (
            "VESSEL_DEPART",
            "port_calls",
            10,
            {"vessel_id": 4, "cranes": 3, "service_h": 14.5, "cargo": 1200},
        ),
        (
            "EMISSIONS_CERT",
            "energy_records",
            10,
            {"co2_kg": 34100.5, "cargo_units": 1200, "intensity": 28.41},
        ),
    ]

    report = auditor.run_benchmark_suite(records)

    assert report.total_valid_tested == 4
    assert report.valid_verified == 4
    assert report.valid_verification_rate_pct == 100.0

    assert report.total_tampered_tested == 4
    assert report.tampered_detected == 4
    assert report.tampered_detection_rate_pct == 100.0

    assert report.target_met is True
    assert "PASSED (100% / 100%)" in report.summary


def test_batch_anchoring():
    ledger = BlockPortLedger()
    batch = [
        {
            "record_hash": f"h_{i}",
            "record_type": "EVENT",
            "subject_table": "events",
            "subject_id": i,
        }
        for i in range(5)
    ]
    block = ledger.anchor_batch(batch, operator="cron_anchor")

    assert block.index == 1
    assert len(block.transactions) == 5
    assert len(block.merkle_root) == 64

    valid, _ = ledger.verify_chain_integrity()
    assert valid is True
    assert ledger.get_by_record_hash("h_3") is not None
