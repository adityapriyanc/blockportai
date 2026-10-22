"""Merkle Tree implementation for batched operational record anchoring (report §5.6).

Follows RFC 6962 domain separation standards:
- Leaf hash: H(0x00 || leaf_data)
- Internal node hash: H(0x01 || left || right)
This prevents second-preimage attacks and validates batch membership proofs.
"""
from __future__ import annotations

import hashlib
from typing import Any, List, Sequence, Tuple

from .canonical import canonical_json


def _leaf_hash(data: Any) -> bytes:
    """Hash a leaf node with 0x00 domain separation prefix."""
    if isinstance(data, bytes):
        raw = data
    elif isinstance(data, str):
        raw = data.encode("utf-8")
    else:
        raw = canonical_json(data).encode("utf-8")
    return hashlib.sha256(b"\x00" + raw).digest()


def _node_hash(left: bytes, right: bytes) -> bytes:
    """Hash two child nodes with 0x01 domain separation prefix."""
    return hashlib.sha256(b"\x01" + left + right).digest()


class MerkleTree:
    """Cryptographic Merkle tree for batch record anchoring and inclusion proofs."""

    def __init__(self, elements: Sequence[Any]):
        if not elements:
            raise ValueError("MerkleTree cannot be empty")
        self.elements = list(elements)
        self.leaves: List[bytes] = [_leaf_hash(el) for el in self.elements]
        self.levels: List[List[bytes]] = [self.leaves]
        self._build_tree()

    def _build_tree(self) -> None:
        current_level = self.leaves
        while len(current_level) > 1:
            next_level: List[bytes] = []
            for i in range(0, len(current_level), 2):
                left = current_level[i]
                if i + 1 < len(current_level):
                    right = current_level[i + 1]
                else:
                    # Duplicate last odd leaf to maintain balanced binary structure
                    right = left
                parent = _node_hash(left, right)
                next_level.append(parent)
            self.levels.append(next_level)
            current_level = next_level

    @property
    def root(self) -> bytes:
        """Binary root hash of the tree."""
        return self.levels[-1][0]

    @property
    def root_hex(self) -> str:
        """Hex-encoded root hash of the tree."""
        return self.root.hex()

    def get_proof(self, index: int) -> List[Tuple[str, str]]:
        """Generate a cryptographic inclusion proof for leaf at `index`.

        Returns a list of tuples: (sibling_hex, 'left' | 'right')
        """
        if index < 0 or index >= len(self.leaves):
            raise IndexError("Leaf index out of bounds")

        proof: List[Tuple[str, str]] = []
        curr_idx = index

        for level in self.levels[:-1]:
            if curr_idx % 2 == 0:
                # Target is left child, sibling is right
                sibling_idx = curr_idx + 1 if curr_idx + 1 < len(level) else curr_idx
                sibling_dir = "right"
            else:
                # Target is right child, sibling is left
                sibling_idx = curr_idx - 1
                sibling_dir = "left"

            sibling_bytes = level[sibling_idx]
            proof.append((sibling_bytes.hex(), sibling_dir))
            curr_idx = curr_idx // 2

        return proof

    @staticmethod
    def verify_proof(
        element: Any,
        proof: Sequence[Tuple[str, str]],
        root_hex: str,
    ) -> bool:
        """Verify an inclusion proof against an expected root hash."""
        curr_bytes = _leaf_hash(element)

        for sibling_hex, direction in proof:
            sibling_bytes = bytes.fromhex(sibling_hex)
            if direction == "right":
                curr_bytes = _node_hash(curr_bytes, sibling_bytes)
            else:
                curr_bytes = _node_hash(sibling_bytes, curr_bytes)

        return curr_bytes.hex() == root_hex
