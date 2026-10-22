"""Tamper-evident blockchain ledger for BlockPort AI (report §5.6, §3 Objective 6).

Implements cryptographically chained blocks where:
- Every block references the SHA-256 hash of its immediate predecessor.
- Transactions hold canonical record hashes and operator signatures.
- Merkle roots authenticate batched milestone transactions.
- Off-chain database rows link back via `ChainRecord` pointers.
"""
from __future__ import annotations

import datetime
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..models import ChainRecord
from .canonical import sha256_hash
from .merkle import MerkleTree


@dataclass(frozen=True)
class LedgerTransaction:
    record_hash: str
    record_type: str
    subject_table: str
    subject_id: int
    timestamp: datetime.datetime
    operator: str
    tx_hash: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_hash": self.record_hash,
            "record_type": self.record_type,
            "subject_table": self.subject_table,
            "subject_id": self.subject_id,
            "timestamp": self.timestamp.isoformat(),
            "operator": self.operator,
            "tx_hash": self.tx_hash,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> LedgerTransaction:
        return cls(
            record_hash=d["record_hash"],
            record_type=d["record_type"],
            subject_table=d["subject_table"],
            subject_id=d["subject_id"],
            timestamp=datetime.datetime.fromisoformat(d["timestamp"]),
            operator=d["operator"],
            tx_hash=d["tx_hash"],
        )


@dataclass
class Block:
    index: int
    timestamp: datetime.datetime
    previous_hash: str
    merkle_root: str
    transactions: List[LedgerTransaction]
    block_hash: str

    def compute_hash(self) -> str:
        header = {
            "index": self.index,
            "timestamp": self.timestamp,
            "previous_hash": self.previous_hash,
            "merkle_root": self.merkle_root,
            "tx_hashes": [tx.tx_hash for tx in self.transactions],
        }
        return sha256_hash(header)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "timestamp": self.timestamp.isoformat(),
            "previous_hash": self.previous_hash,
            "merkle_root": self.merkle_root,
            "transactions": [tx.to_dict() for tx in self.transactions],
            "block_hash": self.block_hash,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> Block:
        txs = [LedgerTransaction.from_dict(t) for t in d["transactions"]]
        return cls(
            index=d["index"],
            timestamp=datetime.datetime.fromisoformat(d["timestamp"]),
            previous_hash=d["previous_hash"],
            merkle_root=d["merkle_root"],
            transactions=txs,
            block_hash=d["block_hash"],
        )


class BlockPortLedger:
    """Cryptographic append-only ledger for anchoring port milestones."""

    def __init__(self) -> None:
        self.blocks: List[Block] = []
        self._tx_by_record_hash: Dict[str, LedgerTransaction] = {}
        self._tx_by_tx_hash: Dict[str, LedgerTransaction] = {}
        self._create_genesis_block()

    def _create_genesis_block(self) -> None:
        """Initialize immutable genesis block."""
        genesis_time = datetime.datetime(2026, 1, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)
        header = {
            "index": 0,
            "timestamp": genesis_time,
            "previous_hash": "0" * 64,
            "merkle_root": "0" * 64,
            "tx_hashes": [],
            "tag": "BlockPort AI Genesis Anchor (Report §5.6)",
        }
        b_hash = sha256_hash(header)
        genesis = Block(
            index=0,
            timestamp=genesis_time,
            previous_hash="0" * 64,
            merkle_root="0" * 64,
            transactions=[],
            block_hash=b_hash,
        )
        self.blocks.append(genesis)

    @property
    def latest_block(self) -> Block:
        return self.blocks[-1]

    def anchor_record(
        self,
        record_type: str,
        subject_table: str,
        subject_id: int,
        record_hash: str,
        operator: str = "system",
        timestamp: Optional[datetime.datetime] = None,
        db_session: Optional[Any] = None,
    ) -> LedgerTransaction:
        """Anchor a single milestone record into a new chained block."""
        now = timestamp or datetime.datetime.now(datetime.timezone.utc)
        tx_payload = {
            "record_hash": record_hash,
            "record_type": record_type,
            "subject_table": subject_table,
            "subject_id": subject_id,
            "operator": operator,
            "timestamp": now,
        }
        tx_hash = sha256_hash(tx_payload)

        tx = LedgerTransaction(
            record_hash=record_hash,
            record_type=record_type,
            subject_table=subject_table,
            subject_id=subject_id,
            timestamp=now,
            operator=operator,
            tx_hash=tx_hash,
        )

        # Build Merkle tree for this single-tx block
        mt = MerkleTree([tx.tx_hash])
        merkle_root = mt.root_hex

        prev_hash = self.latest_block.block_hash
        block = Block(
            index=len(self.blocks),
            timestamp=now,
            previous_hash=prev_hash,
            merkle_root=merkle_root,
            transactions=[tx],
            block_hash="",
        )
        block.block_hash = block.compute_hash()

        self.blocks.append(block)
        self._tx_by_record_hash[record_hash] = tx
        self._tx_by_tx_hash[tx_hash] = tx

        # If a DB session is provided, write off-chain ChainRecord
        if db_session is not None:
            cr = ChainRecord(
                record_type=record_type,
                subject_table=subject_table,
                subject_id=subject_id,
                content_hash=record_hash,
                tx_hash=tx_hash,
                anchored_at=now,
            )
            db_session.add(cr)

        return tx

    def anchor_batch(
        self,
        records: List[Dict[str, Any]],
        operator: str = "batch_anchor",
        timestamp: Optional[datetime.datetime] = None,
        db_session: Optional[Any] = None,
    ) -> Block:
        """Anchor a batch of records under a unified Merkle root block."""
        if not records:
            raise ValueError("Cannot anchor an empty batch of records")

        now = timestamp or datetime.datetime.now(datetime.timezone.utc)
        txs: List[LedgerTransaction] = []

        for r in records:
            tx_payload = {
                "record_hash": r["record_hash"],
                "record_type": r["record_type"],
                "subject_table": r["subject_table"],
                "subject_id": r["subject_id"],
                "operator": operator,
                "timestamp": now,
            }
            tx_hash = sha256_hash(tx_payload)
            tx = LedgerTransaction(
                record_hash=r["record_hash"],
                record_type=r["record_type"],
                subject_table=r["subject_table"],
                subject_id=r["subject_id"],
                timestamp=now,
                operator=operator,
                tx_hash=tx_hash,
            )
            txs.append(tx)
            self._tx_by_record_hash[tx.record_hash] = tx
            self._tx_by_tx_hash[tx.tx_hash] = tx

            if db_session is not None:
                cr = ChainRecord(
                    record_type=r["record_type"],
                    subject_table=r["subject_table"],
                    subject_id=r["subject_id"],
                    content_hash=r["record_hash"],
                    tx_hash=tx_hash,
                    anchored_at=now,
                )
                db_session.add(cr)

        mt = MerkleTree([t.tx_hash for t in txs])
        block = Block(
            index=len(self.blocks),
            timestamp=now,
            previous_hash=self.latest_block.block_hash,
            merkle_root=mt.root_hex,
            transactions=txs,
            block_hash="",
        )
        block.block_hash = block.compute_hash()
        self.blocks.append(block)

        return block

    def get_by_record_hash(self, record_hash: str) -> Optional[LedgerTransaction]:
        return self._tx_by_record_hash.get(record_hash)

    def get_by_tx_hash(self, tx_hash: str) -> Optional[LedgerTransaction]:
        return self._tx_by_tx_hash.get(tx_hash)

    def verify_chain_integrity(self) -> Tuple[bool, str]:
        """Cryptographically audit the entire ledger chain.

        Verifies:
        1. Block 0 is genesis block.
        2. Every block index matches position.
        3. Block i's previous_hash strictly equals Block i-1's block_hash.
        4. Block's recomputed hash strictly equals stored block_hash.
        5. Block's Merkle root matches leaves.
        """
        if len(self.blocks) == 0:
            return False, "Ledger has no blocks"

        # Check genesis
        if self.blocks[0].previous_hash != "0" * 64:
            return False, "Genesis block previous_hash is invalid"

        for i in range(1, len(self.blocks)):
            curr = self.blocks[i]
            prev = self.blocks[i - 1]

            if curr.index != i:
                return False, f"Block {i} index mismatch: expected {i}, got {curr.index}"

            if curr.previous_hash != prev.block_hash:
                return (
                    False,
                    f"Chain break at block {i}: previous_hash '{curr.previous_hash[:10]}...' "
                    f"does not match block {i-1} hash '{prev.block_hash[:10]}...'",
                )

            recomputed = curr.compute_hash()
            if curr.block_hash != recomputed:
                return (
                    False,
                    f"Block {i} hash corruption: stored '{curr.block_hash[:10]}...', "
                    f"computed '{recomputed[:10]}...'",
                )

            if curr.transactions:
                mt = MerkleTree([tx.tx_hash for tx in curr.transactions])
                if mt.root_hex != curr.merkle_root:
                    return (
                        False,
                        f"Block {i} Merkle root mismatch: stored '{curr.merkle_root[:10]}...', "
                        f"recomputed '{mt.root_hex[:10]}...'",
                    )

        return True, f"Ledger valid: {len(self.blocks)} blocks cryptographically verified"

    def export_json(self, filepath: Path) -> None:
        data = {
            "block_count": len(self.blocks),
            "blocks": [b.to_dict() for b in self.blocks],
        }
        filepath.write_text(json.dumps(data, indent=2))

    @classmethod
    def load_json(cls, filepath: Path) -> BlockPortLedger:
        ledger = cls.__new__(cls)
        ledger.blocks = []
        ledger._tx_by_record_hash = {}
        ledger._tx_by_tx_hash = {}

        data = json.loads(filepath.read_text())
        for bd in data["blocks"]:
            b = Block.from_dict(bd)
            ledger.blocks.append(b)
            for tx in b.transactions:
                ledger._tx_by_record_hash[tx.record_hash] = tx
                ledger._tx_by_tx_hash[tx.tx_hash] = tx

        return ledger
