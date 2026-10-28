"""Tamper-evident blockchain ledger for BlockPort AI (report §5.6, §3 Objective 6).

Architecture:
  OperatorWallet   – Generates or loads an ECDSA secp256k1 key-pair via
                     eth-account.  Derives an Ethereum-compatible 0x… address
                     that directly corresponds to 'address operator' in the
                     BlockPortTrust.sol smart contract.

  LedgerTransaction – A proper signed blockchain transaction (not a plain
                     class).  Created exclusively via LedgerTransaction.sign(),
                     which:
                       1. Serialises the payload to canonical JSON.
                       2. Computes a SHA-256 record_hash over that payload.
                       3. Signs the hash with the operator's private key
                          (EIP-191 personal_sign / eth-account).
                       4. Records the hex signature and the operator's
                          Ethereum address so any verifier can recover the
                          signer without knowing the private key.
                       5. Derives the tx_hash from the (record_hash +
                          signature), making the transaction ID unforgeable.
                     Signature verification is available via .verify().

  Block            – Immutable sealed block; created via Block.create() or
                     GenesisBlock.create().  compute_hash() is the sole
                     authority on the block hash.

  Blockchain       – Append-only sequence of Blocks; owns integrity
                     verification and JSON persistence.

  BlockPortLedger  – Port-operations service layer; builds signed
                     LedgerTransactions using a per-session OperatorWallet
                     (or an injected wallet for known operators), then drives
                     Blockchain.append_block().

Cryptographic stack:
  - ECDSA secp256k1 key-pairs via eth-account (matches Solidity ecrecover).
  - EIP-191 personal_sign so signatures are replay-protected.
  - SHA-256 record hashing (RFC 8785 canonical JSON).
  - RFC 6962 Merkle trees for batch block roots.
"""
from __future__ import annotations

import datetime
import json
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from eth_account import Account
from eth_account.messages import encode_defunct

from ..models import ChainRecord
from .canonical import canonical_json, sha256_hash
from .merkle import MerkleTree

# Enable eth-account's unaudited HD-wallet / mnemonic features (needed for
# create_with_mnemonic() / from_mnemonic() but harmless otherwise).
Account.enable_unaudited_hdwallet_features()


# ─────────────────────────────────────────────────────────────────────────────
# GENESIS BLOCK CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

GENESIS_PREVIOUS_HASH: str = "0" * 64
GENESIS_MERKLE_ROOT: str = "0" * 64
GENESIS_TIMESTAMP: datetime.datetime = datetime.datetime(
    2026, 1, 1, 0, 0, 0, tzinfo=datetime.timezone.utc
)
GENESIS_TAG: str = "BlockPort AI Genesis Anchor (Report §5.6)"


# ─────────────────────────────────────────────────────────────────────────────
# OPERATOR WALLET  (ECDSA secp256k1 key-pair)
# ─────────────────────────────────────────────────────────────────────────────


class OperatorWallet:
    """Ethereum-compatible ECDSA wallet for a port operator.

    Wraps an ``eth_account.LocalAccount`` so every transaction is signed with
    a real secp256k1 private key.  The derived ``address`` (0x…) directly
    corresponds to the ``address operator`` field in BlockPortTrust.sol, so
    on-chain ``ecrecover`` can identify the signer without trusting any
    off-chain string.

    Usage::

        wallet = OperatorWallet.generate()          # random fresh key-pair
        wallet = OperatorWallet.from_private_key(hex_key)   # load known key
        signed_tx = wallet.sign_transaction(payload_dict)
    """

    def __init__(self, account: Any) -> None:
        """Internal – use factory methods instead."""
        self._account = account

    # ------------------------------------------------------------------
    # Factories
    # ------------------------------------------------------------------

    @classmethod
    def generate(cls) -> "OperatorWallet":
        """Generate a cryptographically random ECDSA key-pair."""
        private_key_bytes = secrets.token_bytes(32)
        account = Account.from_key(private_key_bytes)
        return cls(account)

    @classmethod
    def from_private_key(cls, private_key_hex: str) -> "OperatorWallet":
        """Restore a wallet from a 32-byte hex-encoded private key."""
        account = Account.from_key(private_key_hex)
        return cls(account)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def address(self) -> str:
        """Ethereum checksummed address (0x…).

        This value is stored in LedgerTransaction.operator_address and
        mirrors 'address operator' in BlockPortTrust.sol.
        """
        return self._account.address

    @property
    def private_key_hex(self) -> str:
        """Hex-encoded 32-byte private key (keep secret!)."""
        return self._account.key.hex()

    # ------------------------------------------------------------------
    # Signing
    # ------------------------------------------------------------------

    def sign_message(self, message_hex: str) -> str:
        """Sign a hex-encoded message digest using EIP-191 personal_sign.

        Args:
            message_hex: Hex string of the bytes to sign (e.g. a SHA-256 hash).

        Returns:
            Hex-encoded 65-byte ECDSA signature (r + s + v).
        """
        msg_bytes = bytes.fromhex(message_hex)
        signable = encode_defunct(msg_bytes)
        signed = self._account.sign_message(signable)
        return signed.signature.hex()

    # ------------------------------------------------------------------
    # Verification (static – no private key needed)
    # ------------------------------------------------------------------

    @staticmethod
    def recover_signer(message_hex: str, signature_hex: str) -> str:
        """Recover the Ethereum address that produced *signature_hex*.

        This is the Python equivalent of Solidity's ``ecrecover``.  If the
        returned address matches the stored ``operator_address`` on a
        LedgerTransaction, the signature is authentic.

        Args:
            message_hex:   Hex of the original signed bytes.
            signature_hex: Hex of the 65-byte ECDSA signature.

        Returns:
            Checksummed Ethereum address of the signer.
        """
        msg_bytes = bytes.fromhex(message_hex)
        signable = encode_defunct(msg_bytes)
        return Account.recover_message(signable, signature=bytes.fromhex(signature_hex))

    def __repr__(self) -> str:  # pragma: no cover
        return f"OperatorWallet(address={self.address})"


# ─────────────────────────────────────────────────────────────────────────────
# LEDGER TRANSACTION  (proper signed blockchain transaction)
# ─────────────────────────────────────────────────────────────────────────────


class LedgerTransaction:
    """A cryptographically signed port-operations transaction.

    This is **not** a plain dataclass.  Every instance is created by
    :meth:`LedgerTransaction.sign`, which:

    1. Serialises the domain payload to RFC 8785 canonical JSON.
    2. Computes a ``record_hash`` (SHA-256) over that canonical form.
    3. Signs the ``record_hash`` bytes with the operator's ECDSA private key
       using EIP-191 ``personal_sign`` (same algorithm as MetaMask / web3.py).
    4. Stores the hex ``signature`` and the operator's Ethereum ``address``
       so any third party can verify via :meth:`verify` without the private key.
    5. Derives ``tx_hash`` = SHA-256(record_hash + signature), making the
       transaction ID unforgeable without the signing key.

    Fields
    ------
    record_type      : domain category (e.g. ``APPROVE_PLAN``, ``VESSEL_DOCK``).
    subject_table    : off-chain table name (mirrors ``subjectRef`` in Solidity).
    subject_id       : off-chain primary key.
    timestamp        : UTC anchoring time.
    operator_address : Ethereum checksummed address of the signing operator.
                       Matches ``address operator`` in BlockPortTrust.sol.
    record_hash      : SHA-256 hex digest of the canonical payload.
    signature        : 65-byte ECDSA secp256k1 signature in hex (EIP-191).
    tx_hash          : SHA-256(record_hash + signature) – the transaction ID.

    The ``payload`` is stored in-memory but not persisted (only its hash is
    stored on-chain), matching the hybrid off-chain/on-chain architecture of
    BlockPortTrust.sol.
    """

    __slots__ = (
        "record_type",
        "subject_table",
        "subject_id",
        "timestamp",
        "operator_address",
        "record_hash",
        "signature",
        "tx_hash",
        "_payload",
    )

    def __init__(
        self,
        record_type: str,
        subject_table: str,
        subject_id: int,
        timestamp: datetime.datetime,
        operator_address: str,
        record_hash: str,
        signature: str,
        tx_hash: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.record_type = record_type
        self.subject_table = subject_table
        self.subject_id = subject_id
        self.timestamp = timestamp
        self.operator_address = operator_address
        self.record_hash = record_hash
        self.signature = signature
        self.tx_hash = tx_hash
        self._payload = payload  # in-memory only; not persisted

    # ------------------------------------------------------------------
    # Factory: sign
    # ------------------------------------------------------------------

    @classmethod
    def sign(
        cls,
        record_type: str,
        subject_table: str,
        subject_id: int,
        payload: Dict[str, Any],
        wallet: OperatorWallet,
        timestamp: Optional[datetime.datetime] = None,
    ) -> "LedgerTransaction":
        """Build and sign a new LedgerTransaction.

        Steps:
        1. Canonical-JSON-serialise payload (RFC 8785) so identical data
           always produces the same bytes regardless of key ordering.
        2. SHA-256 hash → record_hash (matches hash_record() domain pattern).
        3. Sign record_hash bytes with wallet's ECDSA private key (EIP-191).
        4. tx_hash = SHA-256(record_hash_bytes + signature_bytes).

        Args:
            record_type:   Milestone category string.
            subject_table: Off-chain table name.
            subject_id:    Off-chain row primary key.
            payload:       Arbitrary dict of operation data to anchor.
            wallet:        :class:`OperatorWallet` whose private key signs.
            timestamp:     UTC time; defaults to now.

        Returns:
            A fully signed, sealed :class:`LedgerTransaction`.
        """
        now = timestamp or datetime.datetime.now(datetime.timezone.utc)

        # 1. Canonical payload – include metadata so the hash covers context.
        full_payload: Dict[str, Any] = {
            "record_type": record_type,
            "subject_table": subject_table,
            "subject_id": subject_id,
            "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "operator_address": wallet.address,
            **payload,
        }
        canonical = canonical_json(full_payload)

        # 2. Record hash (SHA-256 of canonical bytes).
        record_hash = sha256_hash(canonical)

        # 3. ECDSA signature over the record_hash bytes (EIP-191).
        signature = wallet.sign_message(record_hash)

        # 4. Transaction ID = SHA-256(record_hash_bytes || signature_bytes).
        tx_preimage = bytes.fromhex(record_hash) + bytes.fromhex(signature)
        tx_hash = sha256_hash(tx_preimage)

        return cls(
            record_type=record_type,
            subject_table=subject_table,
            subject_id=subject_id,
            timestamp=now,
            operator_address=wallet.address,
            record_hash=record_hash,
            signature=signature,
            tx_hash=tx_hash,
            payload=full_payload,
        )

    # ------------------------------------------------------------------
    # Verification (no private key required)
    # ------------------------------------------------------------------

    def verify(self) -> bool:
        """Verify the ECDSA signature and transaction hash.

        Returns True iff:
        * The recovered Ethereum address from the signature matches
          ``operator_address`` (proves signing key ownership).
        * The ``tx_hash`` matches SHA-256(record_hash + signature) (proves
          the tx_hash was not tampered post-signing).
        """
        try:
            recovered = OperatorWallet.recover_signer(self.record_hash, self.signature)
        except Exception:
            return False

        if recovered != self.operator_address:
            return False

        tx_preimage = bytes.fromhex(self.record_hash) + bytes.fromhex(self.signature)
        expected_tx_hash = sha256_hash(tx_preimage)
        return self.tx_hash == expected_tx_hash

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a JSON-safe dict (payload excluded – off-chain only)."""
        return {
            "record_type": self.record_type,
            "subject_table": self.subject_table,
            "subject_id": self.subject_id,
            "timestamp": self.timestamp.isoformat(),
            "operator_address": self.operator_address,
            "record_hash": self.record_hash,
            "signature": self.signature,
            "tx_hash": self.tx_hash,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "LedgerTransaction":
        """Reconstruct a LedgerTransaction from its serialised dict.

        The ``_payload`` is not restored (it is off-chain only).
        """
        return cls(
            record_type=d["record_type"],
            subject_table=d["subject_table"],
            subject_id=d["subject_id"],
            timestamp=datetime.datetime.fromisoformat(d["timestamp"]),
            operator_address=d["operator_address"],
            record_hash=d["record_hash"],
            signature=d["signature"],
            tx_hash=d["tx_hash"],
            payload=None,
        )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"LedgerTransaction(type={self.record_type!r}, "
            f"operator={self.operator_address}, "
            f"tx={self.tx_hash[:12]}...)"
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, LedgerTransaction):
            return NotImplemented
        return self.tx_hash == other.tx_hash

    def __hash__(self) -> int:
        return hash(self.tx_hash)


# ─────────────────────────────────────────────────────────────────────────────
# BLOCK  (first-class sealed object)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class Block:
    """A single immutable link in the BlockPort cryptographic chain.

    Fields
    ------
    index         : position in chain (0 = genesis).
    timestamp     : UTC creation time.
    previous_hash : SHA-256 of the preceding block's header.
    merkle_root   : RFC 6962 Merkle root of tx_hashes in this block.
    transactions  : ordered list of :class:`LedgerTransaction`.
    block_hash    : SHA-256 of this block's canonical header (sealed on
                    creation via :meth:`compute_hash`).

    Use :meth:`Block.create` or :meth:`GenesisBlock.create` – never the
    dataclass constructor directly.
    """

    index: int
    timestamp: datetime.datetime
    previous_hash: str
    merkle_root: str
    transactions: List[LedgerTransaction]
    block_hash: str

    # ------------------------------------------------------------------
    # Hashing
    # ------------------------------------------------------------------

    def compute_hash(self) -> str:
        """SHA-256 over this block's canonical header.

        Covers every tamper-evident field.  Changing any field invalidates
        all subsequent blocks' ``previous_hash`` pointers.
        """
        header: Dict[str, Any] = {
            "index": self.index,
            "timestamp": self.timestamp,
            "previous_hash": self.previous_hash,
            "merkle_root": self.merkle_root,
            "tx_hashes": [tx.tx_hash for tx in self.transactions],
        }
        return sha256_hash(header)

    def verify_self(self) -> bool:
        """Return True iff ``block_hash`` matches a fresh ``compute_hash()``."""
        return self.block_hash == self.compute_hash()

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def create(
        cls,
        index: int,
        previous_hash: str,
        transactions: List[LedgerTransaction],
        timestamp: Optional[datetime.datetime] = None,
    ) -> "Block":
        """Build and seal a data block (index >= 1).

        Automatically computes the Merkle root and ``block_hash``.

        Raises:
            ValueError: if ``transactions`` is empty.
        """
        if not transactions:
            raise ValueError("A data block must contain at least one transaction.")

        now = timestamp or datetime.datetime.now(datetime.timezone.utc)
        merkle_root = MerkleTree([tx.tx_hash for tx in transactions]).root_hex

        blk = cls(
            index=index,
            timestamp=now,
            previous_hash=previous_hash,
            merkle_root=merkle_root,
            transactions=list(transactions),
            block_hash="",  # placeholder; sealed below
        )
        blk.block_hash = blk.compute_hash()
        return blk

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

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
    def from_dict(cls, d: Dict[str, Any]) -> "Block":
        txs = [LedgerTransaction.from_dict(t) for t in d["transactions"]]
        return cls(
            index=d["index"],
            timestamp=datetime.datetime.fromisoformat(d["timestamp"]),
            previous_hash=d["previous_hash"],
            merkle_root=d["merkle_root"],
            transactions=txs,
            block_hash=d["block_hash"],
        )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"Block(index={self.index}, txs={len(self.transactions)}, "
            f"hash={self.block_hash[:12]}...)"
        )


# ─────────────────────────────────────────────────────────────────────────────
# GENESIS BLOCK  (deterministic block #0)
# ─────────────────────────────────────────────────────────────────────────────


class GenesisBlock:
    """Factory for the unique genesis block (index=0) of the BlockPort chain.

    * ``previous_hash`` = 64 zero-hex digits (no predecessor).
    * ``merkle_root``   = 64 zero-hex digits (no transactions).
    * ``timestamp``     = ``GENESIS_TIMESTAMP`` (fixed → deterministic hash).
    * ``tag``           embedded in the canonical header for human readability.

    Two independent ledgers that call ``GenesisBlock.create()`` will produce
    identical genesis hashes, confirming they share the same root of trust.
    """

    @staticmethod
    def create() -> Block:
        """Build and seal the genesis block."""
        canonical_header: Dict[str, Any] = {
            "index": 0,
            "timestamp": GENESIS_TIMESTAMP,
            "previous_hash": GENESIS_PREVIOUS_HASH,
            "merkle_root": GENESIS_MERKLE_ROOT,
            "tx_hashes": [],
            "tag": GENESIS_TAG,
        }
        genesis_hash = sha256_hash(canonical_header)
        return Block(
            index=0,
            timestamp=GENESIS_TIMESTAMP,
            previous_hash=GENESIS_PREVIOUS_HASH,
            merkle_root=GENESIS_MERKLE_ROOT,
            transactions=[],
            block_hash=genesis_hash,
        )


# ─────────────────────────────────────────────────────────────────────────────
# BLOCKCHAIN  (sequence manager)
# ─────────────────────────────────────────────────────────────────────────────


class Blockchain:
    """Append-only, cryptographically chained sequence of :class:`Block` objects.

    Initialises automatically with the genesis block from
    :class:`GenesisBlock`.  All chain-management logic lives here; port
    operations are the concern of :class:`BlockPortLedger`.
    """

    def __init__(self) -> None:
        self._chain: List[Block] = []
        self._chain.append(GenesisBlock.create())

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    @property
    def genesis(self) -> Block:
        """Immutable genesis block (index 0)."""
        return self._chain[0]

    @property
    def latest_block(self) -> Block:
        return self._chain[-1]

    @property
    def height(self) -> int:
        """Number of blocks in the chain (including genesis)."""
        return len(self._chain)

    def __len__(self) -> int:
        return len(self._chain)

    def __iter__(self) -> Iterator[Block]:
        return iter(self._chain)

    def __getitem__(self, idx: int) -> Block:
        return self._chain[idx]

    # ------------------------------------------------------------------
    # Append
    # ------------------------------------------------------------------

    def append_block(self, block: Block) -> None:
        """Validate and append *block*.

        Raises:
            ValueError: on index mismatch, broken chain link, or bad hash.
        """
        expected_index = len(self._chain)
        if block.index != expected_index:
            raise ValueError(
                f"Block index mismatch: chain expects {expected_index}, "
                f"got {block.index}."
            )
        if block.previous_hash != self.latest_block.block_hash:
            raise ValueError(
                f"Chain link broken at block {block.index}: "
                f"previous_hash '{block.previous_hash[:12]}...' != "
                f"latest block_hash '{self.latest_block.block_hash[:12]}...'."
            )
        if not block.verify_self():
            raise ValueError(
                f"Block {block.index} self-verification failed: "
                f"stored hash does not match recomputed hash."
            )
        self._chain.append(block)

    # ------------------------------------------------------------------
    # Integrity
    # ------------------------------------------------------------------

    def verify_integrity(self) -> Tuple[bool, str]:
        """Cryptographically audit every link in the chain.

        Checks:
        1. Chain is non-empty.
        2. Block 0 carries the genesis sentinel.
        3. Sequential index.
        4. Chain-link (previous_hash → block_hash).
        5. Hash self-consistency (verify_self).
        6. Merkle root consistency.
        """
        if not self._chain:
            return False, "Chain is empty."

        if self._chain[0].previous_hash != GENESIS_PREVIOUS_HASH:
            return False, "Genesis block previous_hash is not the expected sentinel."

        for i in range(1, len(self._chain)):
            curr = self._chain[i]
            prev = self._chain[i - 1]

            if curr.index != i:
                return False, f"Block {i} index mismatch: expected {i}, got {curr.index}."

            if curr.previous_hash != prev.block_hash:
                return (
                    False,
                    f"Chain break at block {i}: previous_hash "
                    f"'{curr.previous_hash[:10]}...' != block {i - 1} hash "
                    f"'{prev.block_hash[:10]}...'.",
                )

            if not curr.verify_self():
                recomputed = curr.compute_hash()
                return (
                    False,
                    f"Block {i} hash corruption: stored '{curr.block_hash[:10]}...', "
                    f"computed '{recomputed[:10]}...'.",
                )

            if curr.transactions:
                mt = MerkleTree([tx.tx_hash for tx in curr.transactions])
                if mt.root_hex != curr.merkle_root:
                    return (
                        False,
                        f"Block {i} Merkle root mismatch: "
                        f"stored '{curr.merkle_root[:10]}...', "
                        f"recomputed '{mt.root_hex[:10]}...'.",
                    )

        return True, f"Ledger valid: {len(self._chain)} blocks cryptographically verified"

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {"block_count": len(self._chain), "blocks": [b.to_dict() for b in self._chain]}

    def export_json(self, filepath: Path) -> None:
        filepath.write_text(json.dumps(self.to_dict(), indent=2))

    @classmethod
    def load_json(cls, filepath: Path) -> "Blockchain":
        bc = cls.__new__(cls)
        bc._chain = []
        data = json.loads(filepath.read_text())
        for bd in data["blocks"]:
            bc._chain.append(Block.from_dict(bd))
        return bc


# ─────────────────────────────────────────────────────────────────────────────
# BLOCKPORT LEDGER  (port-operations service layer)
# ─────────────────────────────────────────────────────────────────────────────


class BlockPortLedger:
    """Cryptographic append-only ledger for anchoring port milestones.

    Uses a default :class:`OperatorWallet` (auto-generated) for transactions
    where no explicit wallet is provided.  You can inject a known wallet via
    ``anchor_record(..., wallet=my_wallet)`` so the Ethereum address in the
    transaction matches a real operator key registered with BlockPortTrust.sol.

    Delegates all chain management to an internal :class:`Blockchain`.
    """

    def __init__(self, default_wallet: Optional[OperatorWallet] = None) -> None:
        self._blockchain: Blockchain = Blockchain()
        self._default_wallet: OperatorWallet = default_wallet or OperatorWallet.generate()
        # Look-up indexes for O(1) retrieval.
        self._tx_by_record_hash: Dict[str, LedgerTransaction] = {}
        self._tx_by_tx_hash: Dict[str, LedgerTransaction] = {}

    # ------------------------------------------------------------------
    # Chain accessors
    # ------------------------------------------------------------------

    @property
    def blocks(self) -> List[Block]:
        """Ordered list of all blocks (snapshot)."""
        return list(self._blockchain)

    @property
    def latest_block(self) -> Block:
        return self._blockchain.latest_block

    @property
    def genesis_block(self) -> Block:
        return self._blockchain.genesis

    @property
    def default_wallet(self) -> OperatorWallet:
        """The default signing wallet for this ledger session."""
        return self._default_wallet

    # ------------------------------------------------------------------
    # Anchoring
    # ------------------------------------------------------------------

    def anchor_record(
        self,
        record_type: str,
        subject_table: str,
        subject_id: int,
        record_hash: str,
        operator: str = "system",
        timestamp: Optional[datetime.datetime] = None,
        db_session: Optional[Any] = None,
        wallet: Optional[OperatorWallet] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> LedgerTransaction:
        """Anchor a single milestone record into a new signed, chained block.

        If *wallet* is provided it is used for signing; otherwise the ledger's
        ``default_wallet`` is used.  If *payload* is provided the transaction
        is built from it (full ECDSA signing path); otherwise a minimal payload
        is constructed from the pre-computed *record_hash* (legacy path for
        backward compatibility with the auditor/benchmark).
        """
        w = wallet or self._default_wallet
        now = timestamp or datetime.datetime.now(datetime.timezone.utc)

        if payload is not None:
            # Full signed-transaction path.
            tx = LedgerTransaction.sign(
                record_type=record_type,
                subject_table=subject_table,
                subject_id=subject_id,
                payload=payload,
                wallet=w,
                timestamp=now,
            )
        else:
            # Legacy / auditor path: build a minimal signed tx from the
            # pre-computed record_hash so the auditor can still anchor records
            # without supplying full payloads.
            minimal_payload: Dict[str, Any] = {
                "record_hash": record_hash,
                "operator": operator,
            }
            tx = LedgerTransaction.sign(
                record_type=record_type,
                subject_table=subject_table,
                subject_id=subject_id,
                payload=minimal_payload,
                wallet=w,
                timestamp=now,
            )
            # Override record_hash so auditor look-ups still work.
            tx_dict = tx.to_dict()
            tx_dict["record_hash"] = record_hash
            # Recompute tx_hash over the new record_hash + same signature.
            tx_preimage = bytes.fromhex(record_hash) + bytes.fromhex(tx.signature)
            tx_dict["tx_hash"] = sha256_hash(tx_preimage)
            tx = LedgerTransaction.from_dict(tx_dict)

        block = Block.create(
            index=len(self._blockchain),
            previous_hash=self._blockchain.latest_block.block_hash,
            transactions=[tx],
            timestamp=now,
        )
        self._blockchain.append_block(block)

        self._tx_by_record_hash[tx.record_hash] = tx
        self._tx_by_tx_hash[tx.tx_hash] = tx

        if db_session is not None:
            cr = ChainRecord(
                record_type=record_type,
                subject_table=subject_table,
                subject_id=subject_id,
                content_hash=tx.record_hash,
                tx_hash=tx.tx_hash,
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
        wallet: Optional[OperatorWallet] = None,
    ) -> Block:
        """Anchor a batch of records under a single Merkle root block.

        Each record dict must contain at minimum: ``record_type``,
        ``subject_table``, ``subject_id``, and ``record_hash``.  An optional
        ``payload`` key can provide the full data dict for full ECDSA signing.
        """
        if not records:
            raise ValueError("Cannot anchor an empty batch of records.")

        w = wallet or self._default_wallet
        now = timestamp or datetime.datetime.now(datetime.timezone.utc)
        txs: List[LedgerTransaction] = []

        for r in records:
            p = r.get("payload") or {"record_hash": r["record_hash"], "operator": operator}
            tx = LedgerTransaction.sign(
                record_type=r["record_type"],
                subject_table=r["subject_table"],
                subject_id=r["subject_id"],
                payload=p,
                wallet=w,
                timestamp=now,
            )
            if "record_hash" in r and r["record_hash"] != tx.record_hash:
                # Override with the pre-computed hash (legacy anchor path).
                tx_dict = tx.to_dict()
                tx_dict["record_hash"] = r["record_hash"]
                tx_preimage = bytes.fromhex(r["record_hash"]) + bytes.fromhex(tx.signature)
                tx_dict["tx_hash"] = sha256_hash(tx_preimage)
                tx = LedgerTransaction.from_dict(tx_dict)

            txs.append(tx)
            self._tx_by_record_hash[tx.record_hash] = tx
            self._tx_by_tx_hash[tx.tx_hash] = tx

            if db_session is not None:
                cr = ChainRecord(
                    record_type=r["record_type"],
                    subject_table=r["subject_table"],
                    subject_id=r["subject_id"],
                    content_hash=tx.record_hash,
                    tx_hash=tx.tx_hash,
                    anchored_at=now,
                )
                db_session.add(cr)

        block = Block.create(
            index=len(self._blockchain),
            previous_hash=self._blockchain.latest_block.block_hash,
            transactions=txs,
            timestamp=now,
        )
        self._blockchain.append_block(block)
        return block

    # ------------------------------------------------------------------
    # Look-ups
    # ------------------------------------------------------------------

    def get_by_record_hash(self, record_hash: str) -> Optional[LedgerTransaction]:
        return self._tx_by_record_hash.get(record_hash)

    def get_by_tx_hash(self, tx_hash: str) -> Optional[LedgerTransaction]:
        return self._tx_by_tx_hash.get(tx_hash)

    # ------------------------------------------------------------------
    # Integrity & persistence
    # ------------------------------------------------------------------

    def verify_chain_integrity(self) -> Tuple[bool, str]:
        return self._blockchain.verify_integrity()

    def export_json(self, filepath: Path) -> None:
        self._blockchain.export_json(filepath)

    @classmethod
    def load_json(cls, filepath: Path) -> "BlockPortLedger":
        ledger = cls.__new__(cls)
        ledger._blockchain = Blockchain.load_json(filepath)
        ledger._default_wallet = OperatorWallet.generate()
        ledger._tx_by_record_hash = {}
        ledger._tx_by_tx_hash = {}
        for block in ledger._blockchain:
            for tx in block.transactions:
                ledger._tx_by_record_hash[tx.record_hash] = tx
                ledger._tx_by_tx_hash[tx.tx_hash] = tx
        return ledger


# ─────────────────────────────────────────────────────────────────────────────
# BLOCKCHAIN NODE  (single peer in the network)
# ─────────────────────────────────────────────────────────────────────────────


class BlockchainNode:
    """A single peer node in the BlockPort blockchain network.

    Each node:
    * Has a unique ``node_id`` (e.g. ``"Port-Singapore"``) and its own
      :class:`OperatorWallet` (ECDSA identity).
    * Maintains its own **independent** :class:`Blockchain` copy.
    * Keeps a reference to its peer nodes so it can **broadcast** and
      **receive** blocks.
    * Applies the *longest valid chain* consensus rule when syncing.

    Nodes never share a Blockchain object in memory — every node holds a full
    copy, mirroring how real blockchain peers work.

    Usage::

        node = BlockchainNode("Port-Singapore")
        node.add_peer(other_node)
        tx = LedgerTransaction.sign(...)
        node.submit_block([tx])          # seals block and broadcasts to peers
        node.sync_with_peers()           # adopt longest valid chain
        print(node.status())
    """

    def __init__(
        self,
        node_id: str,
        wallet: Optional[OperatorWallet] = None,
    ) -> None:
        self.node_id: str = node_id
        self.wallet: OperatorWallet = wallet or OperatorWallet.generate()
        # Each node starts with its own fresh Blockchain (identical genesis).
        self._blockchain: Blockchain = Blockchain()
        self._peers: List["BlockchainNode"] = []
        # Received-block dedup set (block_hash strings) to avoid re-broadcasting.
        self._seen_hashes: set = {self._blockchain.genesis.block_hash}
        # Log of network events for this node.
        self._log: List[str] = []

    # ------------------------------------------------------------------
    # Peers
    # ------------------------------------------------------------------

    def add_peer(self, peer: "BlockchainNode") -> None:
        """Register *peer* as a connected neighbour (one-directional)."""
        if peer is not self and peer not in self._peers:
            self._peers.append(peer)
            self._log.append(f"[{self.node_id}] Connected to peer '{peer.node_id}'")

    def connect(self, peer: "BlockchainNode") -> None:
        """Bi-directionally connect this node and *peer*."""
        self.add_peer(peer)
        peer.add_peer(self)

    # ------------------------------------------------------------------
    # Block submission (local + broadcast)
    # ------------------------------------------------------------------

    def submit_block(
        self,
        transactions: List[LedgerTransaction],
        timestamp: Optional[datetime.datetime] = None,
    ) -> Block:
        """Seal a new block from *transactions* and broadcast to all peers.

        Steps:
        1. Create and seal the block via ``Block.create()``.
        2. Append it to this node's local chain.
        3. Broadcast to all connected peers (who validate before accepting).

        Args:
            transactions: Non-empty list of signed :class:`LedgerTransaction`.
            timestamp:    UTC time; defaults to now.

        Returns:
            The sealed :class:`Block` added to this node's chain.
        """
        now = timestamp or datetime.datetime.now(datetime.timezone.utc)
        block = Block.create(
            index=len(self._blockchain),
            previous_hash=self._blockchain.latest_block.block_hash,
            transactions=transactions,
            timestamp=now,
        )
        self._blockchain.append_block(block)
        self._seen_hashes.add(block.block_hash)
        self._log.append(
            f"[{self.node_id}] * Sealed Block #{block.index} "
            f"(txs={len(transactions)}, hash={block.block_hash[:12]}...)"
        )
        # Broadcast to peers.
        for peer in self._peers:
            peer._receive_block(block, sender_id=self.node_id)
        return block

    def _receive_block(self, block: Block, sender_id: str) -> bool:
        """Accept an incoming block from a peer (internal).

        Returns True if the block was accepted into the local chain.
        """
        # Already seen - skip (prevents broadcast storms).
        if block.block_hash in self._seen_hashes:
            return False

        self._seen_hashes.add(block.block_hash)

        # Validate and try to append.
        try:
            self._blockchain.append_block(block)
            self._log.append(
                f"[{self.node_id}] [OK] Accepted Block #{block.index} "
                f"from '{sender_id}' (hash={block.block_hash[:12]}...)"
            )
            # Re-broadcast to our other peers (gossip protocol).
            for peer in self._peers:
                if peer.node_id != sender_id:
                    peer._receive_block(block, sender_id=self.node_id)
            return True
        except ValueError as exc:
            self._log.append(
                f"[{self.node_id}] [FAIL] Rejected Block #{block.index} "
                f"from '{sender_id}': {exc}"
            )
            return False

    # ------------------------------------------------------------------
    # Consensus: longest valid chain
    # ------------------------------------------------------------------

    def sync_with_peers(self) -> bool:
        """Adopt the longest valid chain among all known peers.

        Implements the *heaviest chain rule*: if a peer's chain is longer
        than ours **and** passes ``verify_integrity()``, we replace our
        local chain with theirs and re-log all their ``_seen_hashes``.

        Returns:
            True if this node switched to a peer's chain.
        """
        best_chain: Optional[Blockchain] = None
        best_height: int = len(self._blockchain)
        best_peer_id: str = ""

        for peer in self._peers:
            if len(peer._blockchain) <= best_height:
                continue
            valid, _ = peer._blockchain.verify_integrity()
            if valid:
                best_chain = peer._blockchain
                best_height = len(peer._blockchain)
                best_peer_id = peer.node_id

        if best_chain is None:
            self._log.append(f"[{self.node_id}] <-> sync: already on longest chain (height={len(self._blockchain)})")
            return False

        # Deep-copy the chain by round-tripping through dicts.
        self._blockchain = Blockchain.load_json.__func__(  # type: ignore[attr-defined]
            Blockchain,
            _chain_from_dict(best_chain.to_dict()),
        )
        for blk in self._blockchain:
            self._seen_hashes.add(blk.block_hash)

        self._log.append(
            f"[{self.node_id}] <=> Adopted chain from '{best_peer_id}' "
            f"(new height={len(self._blockchain)})"
        )
        return True

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    @property
    def chain_height(self) -> int:
        """Number of blocks in this node's local chain."""
        return len(self._blockchain)

    @property
    def latest_block(self) -> Block:
        return self._blockchain.latest_block

    @property
    def genesis(self) -> Block:
        return self._blockchain.genesis

    def get_block(self, index: int) -> Block:
        return self._blockchain[index]

    def verify(self) -> Tuple[bool, str]:
        """Run full integrity audit on this node's local chain."""
        return self._blockchain.verify_integrity()

    def log(self) -> List[str]:
        """Return the event log for this node."""
        return list(self._log)

    # ------------------------------------------------------------------
    # Status display
    # ------------------------------------------------------------------

    def status(self) -> Dict[str, Any]:
        """Return a JSON-serialisable status snapshot of this node."""
        valid, msg = self._blockchain.verify_integrity()
        return {
            "node_id": self.node_id,
            "address": self.wallet.address,
            "chain_height": self.chain_height,
            "genesis_hash": self._blockchain.genesis.block_hash[:16] + "...",
            "latest_hash": self.latest_block.block_hash[:16] + "...",
            "latest_merkle_root": self.latest_block.merkle_root[:16] + "...",
            "peers": [p.node_id for p in self._peers],
            "chain_valid": valid,
            "integrity_msg": msg,
        }

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"BlockchainNode(id={self.node_id!r}, "
            f"height={self.chain_height}, "
            f"peers={[p.node_id for p in self._peers]})"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _chain_from_dict(data: Dict[str, Any]) -> "Blockchain":
    """Reconstruct a Blockchain from its dict representation (no file I/O)."""
    bc = Blockchain.__new__(Blockchain)
    bc._chain = [Block.from_dict(bd) for bd in data["blocks"]]
    return bc


# ─────────────────────────────────────────────────────────────────────────────
# BLOCKCHAIN NETWORK  (multi-node coordinator)
# ─────────────────────────────────────────────────────────────────────────────


class BlockchainNetwork:
    """Coordinator that manages multiple :class:`BlockchainNode` instances.

    Simulates a permissioned port authority P2P blockchain network where each
    participant (terminal operator, port authority, customs hub, etc.) runs an
    independent node.

    Features
    --------
    * ``add_node``         – Register a named node (auto-generates wallet).
    * ``connect``          – Bi-directionally link two nodes as peers.
    * ``connect_all``      – Fully-mesh all nodes (every node peers with every other).
    * ``broadcast_tx``     – Sign a transaction on a named node and broadcast.
    * ``broadcast_batch``  – Sign multiple transactions as one block and broadcast.
    * ``sync_all``         – Run consensus across every node (longest chain wins).
    * ``network_status``   – Print / return a live snapshot of all nodes.
    * ``verify_all``       – Assert every node holds a valid chain.

    Example::

        net = BlockchainNetwork()
        net.add_node("Port-Authority")
        net.add_node("Terminal-A")
        net.add_node("Customs-Hub")
        net.connect_all()

        txs = [LedgerTransaction.sign(..., wallet=net["Port-Authority"].wallet)]
        net.broadcast_batch("Port-Authority", txs)
        net.sync_all()
        net.network_status()
    """

    def __init__(self, name: str = "BlockPort Network") -> None:
        self.name: str = name
        self._nodes: Dict[str, BlockchainNode] = {}

    # ------------------------------------------------------------------
    # Node management
    # ------------------------------------------------------------------

    def add_node(
        self,
        node_id: str,
        wallet: Optional[OperatorWallet] = None,
    ) -> BlockchainNode:
        """Add a new named node to the network.

        Args:
            node_id: Unique name (e.g. ``"Port-Authority"``).
            wallet:  Optional pre-existing wallet; a random one is generated
                     if omitted.

        Returns:
            The newly created :class:`BlockchainNode`.

        Raises:
            ValueError: if *node_id* is already registered.
        """
        if node_id in self._nodes:
            raise ValueError(f"Node '{node_id}' already exists in this network.")
        node = BlockchainNode(node_id=node_id, wallet=wallet)
        self._nodes[node_id] = node
        return node

    def __getitem__(self, node_id: str) -> BlockchainNode:
        """Access a node by its ID: ``network["Port-Authority"]``."""
        return self._nodes[node_id]

    def __contains__(self, node_id: str) -> bool:
        return node_id in self._nodes

    def nodes(self) -> List[BlockchainNode]:
        """Return all registered nodes."""
        return list(self._nodes.values())

    # ------------------------------------------------------------------
    # Topology
    # ------------------------------------------------------------------

    def connect(self, node_id_a: str, node_id_b: str) -> None:
        """Bi-directionally connect two nodes as peers."""
        self._nodes[node_id_a].connect(self._nodes[node_id_b])

    def connect_all(self) -> None:
        """Fully-mesh the network (every node peers with every other node)."""
        node_list = list(self._nodes.values())
        for i, a in enumerate(node_list):
            for b in node_list[i + 1:]:
                a.connect(b)

    def connect_ring(self) -> None:
        """Connect nodes in a ring topology (A→B→C→…→A)."""
        node_list = list(self._nodes.values())
        for i in range(len(node_list)):
            node_list[i].connect(node_list[(i + 1) % len(node_list)])

    def connect_star(self, hub_id: str) -> None:
        """Connect all nodes to a single hub node (spoke topology)."""
        hub = self._nodes[hub_id]
        for node in self._nodes.values():
            if node is not hub:
                hub.connect(node)

    # ------------------------------------------------------------------
    # Transaction / block broadcasting
    # ------------------------------------------------------------------

    def broadcast_tx(
        self,
        from_node_id: str,
        record_type: str,
        subject_table: str,
        subject_id: int,
        payload: Dict[str, Any],
        timestamp: Optional[datetime.datetime] = None,
    ) -> Tuple[LedgerTransaction, Block]:
        """Sign one transaction on *from_node_id* and broadcast as a new block.

        Returns:
            ``(LedgerTransaction, Block)`` sealed on the originating node.
        """
        node = self._nodes[from_node_id]
        tx = LedgerTransaction.sign(
            record_type=record_type,
            subject_table=subject_table,
            subject_id=subject_id,
            payload=payload,
            wallet=node.wallet,
            timestamp=timestamp,
        )
        block = node.submit_block([tx], timestamp=timestamp)
        return tx, block

    def broadcast_batch(
        self,
        from_node_id: str,
        transactions: List[LedgerTransaction],
        timestamp: Optional[datetime.datetime] = None,
    ) -> Block:
        """Broadcast a pre-built list of transactions as a single block.

        Returns:
            The sealed :class:`Block` appended to *from_node_id*'s chain.
        """
        node = self._nodes[from_node_id]
        return node.submit_block(transactions, timestamp=timestamp)

    # ------------------------------------------------------------------
    # Consensus
    # ------------------------------------------------------------------

    def sync_all(self) -> Dict[str, bool]:
        """Run one round of longest-chain consensus across every node.

        Returns:
            Dict mapping node_id → True if that node switched chains.
        """
        results: Dict[str, bool] = {}
        for node_id, node in self._nodes.items():
            results[node_id] = node.sync_with_peers()
        return results

    # ------------------------------------------------------------------
    # Network status & verification
    # ------------------------------------------------------------------

    def network_status(self, print_output: bool = True) -> List[Dict[str, Any]]:
        """Return (and optionally print) a live status table of all nodes.

        Columns: node_id, height, address, latest_hash, peers, chain_valid.
        """
        rows: List[Dict[str, Any]] = []
        for node in self._nodes.values():
            rows.append(node.status())

        if print_output:
            sep = "-" * 110
            header = (
                f"{'NODE':<22} {'HEIGHT':>7}  {'ADDRESS':<44} "
                f"{'LATEST HASH':<20} {'PEERS':<25} VALID"
            )
            print(f"\n{'=' * 110}")
            print(f"  {self.name} -- Network Status")
            print(f"{'=' * 110}")
            print(header)
            print(sep)
            for r in rows:
                peers_str = ", ".join(r["peers"]) if r["peers"] else "(none)"
                valid_str = "[OK]" if r["chain_valid"] else "[FAIL]"
                print(
                    f"  {r['node_id']:<20} {r['chain_height']:>7}  {r['address']:<44} "
                    f"{r['latest_hash']:<20} {peers_str:<25} {valid_str}"
                )
            print(f"{'=' * 110}\n")

        return rows

    def verify_all(self) -> Dict[str, Tuple[bool, str]]:
        """Run integrity audit on every node.

        Returns:
            Dict mapping node_id → ``(is_valid, message)``.
        """
        return {node_id: node.verify() for node_id, node in self._nodes.items()}

    def all_chains_agree(self) -> bool:
        """Return True iff every node's latest block hash is identical."""
        hashes = {node.latest_block.block_hash for node in self._nodes.values()}
        return len(hashes) == 1

    def network_log(self) -> List[str]:
        """Concatenated event log from every node, in node order."""
        lines: List[str] = []
        for node in self._nodes.values():
            lines.extend(node.log())
        return lines

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"BlockchainNetwork(name={self.name!r}, "
            f"nodes={list(self._nodes.keys())})"
        )
