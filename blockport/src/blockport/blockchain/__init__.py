"""Blockchain Trust Protocol package for BlockPort AI (report §5.6)."""
from .auditor import BlockchainAuditor, IntegrityBenchmarkReport, RecordAuditResult
from .canonical import canonical_json, hash_record, sha256_hash
from .ledger import (
    GENESIS_MERKLE_ROOT,
    GENESIS_PREVIOUS_HASH,
    GENESIS_TAG,
    GENESIS_TIMESTAMP,
    Block,
    Blockchain,
    BlockchainNetwork,
    BlockchainNode,
    BlockPortLedger,
    GenesisBlock,
    LedgerTransaction,
    OperatorWallet,
)
from .merkle import MerkleTree

__all__ = [
    # ECDSA signing
    "OperatorWallet",
    # Block primitives
    "Block",
    "Blockchain",
    "GenesisBlock",
    "LedgerTransaction",
    # Genesis constants
    "GENESIS_PREVIOUS_HASH",
    "GENESIS_MERKLE_ROOT",
    "GENESIS_TIMESTAMP",
    "GENESIS_TAG",
    # High-level ledger service
    "BlockPortLedger",
    # Multi-node network simulation
    "BlockchainNode",
    "BlockchainNetwork",
    # Auditing
    "BlockchainAuditor",
    "IntegrityBenchmarkReport",
    "RecordAuditResult",
    # Cryptographic primitives
    "MerkleTree",
    "canonical_json",
    "hash_record",
    "sha256_hash",
]
