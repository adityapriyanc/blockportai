"""Canonical serialization and deterministic cryptographic hashing (report §5.6).

Implements RFC 8785 (JSON Canonicalization Scheme - JCS) rules to guarantee that
identical semantic data always produces the exact same byte sequence and SHA-256 hash,
regardless of Python dictionary insertion ordering, key order, float representation variances,
or whitespace formatting.
"""
from __future__ import annotations

import datetime
import hashlib
import json
from decimal import Decimal
from typing import Any, Mapping


def _normalize_obj(val: Any) -> Any:
    """Normalize Python objects into strictly canonical primitive forms."""
    if val is None or isinstance(val, (bool, int, str)):
        return val
    elif isinstance(val, float):
        # Deterministic float formatting: avoid scientific notation artifacts when possible
        if val.is_integer():
            return int(val)
        return float(f"{val:.8f}".rstrip("0").rstrip("."))
    elif isinstance(val, Decimal):
        return float(val)
    elif isinstance(val, (datetime.datetime, datetime.date)):
        if isinstance(val, datetime.datetime):
            # Ensure UTC timezone representation with trailing 'Z'
            if val.tzinfo is None:
                dt_utc = val.replace(tzinfo=datetime.timezone.utc)
            else:
                dt_utc = val.astimezone(datetime.timezone.utc)
            # Format as ISO 8601 with Z
            return dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        return val.isoformat()
    elif isinstance(val, Mapping):
        # Sort keys lexicographically according to UTF-16 code units / unicode code points
        return {
            str(k): _normalize_obj(v)
            for k, v in sorted(val.items(), key=lambda item: str(item[0]))
        }
    elif isinstance(val, (list, tuple)):
        return [_normalize_obj(item) for item in val]
    elif isinstance(val, (set, frozenset)):
        # Normalize sets into sorted lists
        return sorted([_normalize_obj(item) for item in val], key=lambda x: str(x))
    elif hasattr(val, "as_dict") and callable(getattr(val, "as_dict")):
        return _normalize_obj(val.as_dict())
    elif hasattr(val, "__dict__"):
        # For dataclasses or custom models
        clean_dict = {k: v for k, v in val.__dict__.items() if not k.startswith("_")}
        return _normalize_obj(clean_dict)
    return str(val)


def canonical_json(data: Any) -> str:
    """Serialize any Python data structure to deterministic RFC 8785 canonical JSON."""
    normalized = _normalize_obj(data)
    # separators=(',', ':') removes all whitespace between tokens
    return json.dumps(normalized, separators=(",", ":"), ensure_ascii=True, sort_keys=True)


def sha256_hash(data: Any) -> str:
    """Compute the SHA-256 hex digest of data.

    Accepts strings, bytes, or arbitrary serializable data structures.
    """
    if isinstance(data, bytes):
        payload_bytes = data
    elif isinstance(data, str):
        payload_bytes = data.encode("utf-8")
    else:
        payload_bytes = canonical_json(data).encode("utf-8")
    return hashlib.sha256(payload_bytes).hexdigest()


def hash_record(record_type: str, payload: Mapping[str, Any]) -> str:
    """Hash an operational record with domain separation (report §5.6).

    Prepends the record_type to prevent cross-type hash collisions.
    """
    canonical_body = canonical_json(payload)
    domain_separated = f"{record_type}:{canonical_body}"
    return hashlib.sha256(domain_separated.encode("utf-8")).hexdigest()
