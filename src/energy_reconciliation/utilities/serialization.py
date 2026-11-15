"""Canonical, exact JSON fingerprints shared by runtime services."""

import hashlib
import json
from uuid import NAMESPACE_URL, uuid5


def canonical(value: object) -> bytes:
    return (
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        )
        + "\n"
    ).encode("utf-8")


def fingerprint(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def stable_id(kind: str, value: object) -> str:
    return f"syn_{kind}_" + uuid5(NAMESPACE_URL, fingerprint(value)).hex
