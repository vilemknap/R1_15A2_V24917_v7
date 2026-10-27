# -*- coding: utf-8 -*-
"""V2.4.9.4 semantic restart authority.

A Visum ``.ver`` file may be reserialized by a normal user save without a model
change.  Therefore the raw file SHA-256 is provenance and a within-run mutation
sentinel only. Restart acceptance is based on explicit model-semantic hashes
computed by the live adapter.
"""
from __future__ import annotations

import json
from pathlib import Path

from r1_15a2_supply import SupplyContractError, canonical_hash

SCHEMA = "R1_15A2_SEMANTIC_RESTART_AUTHORITY_V2494"
SEMANTIC_FIELDS = (
    "fixed_link_hash",
    "dseg_hash",
    "operations_hash",
    "addval_hash",
    "matrix_hash",
    "generation_hash",
    "td_hash",
)
RAW_VER_SHA_ROLE = (
    "PROVENANCE_AND_WITHIN_RUN_SOURCE_MUTATION_SENTINEL_ONLY_"
    "NOT_CROSS_RUN_RESTART_ACCEPTANCE"
)


def _require_hash(value, label):
    if not isinstance(value, str) or len(value) != 64:
        raise SupplyContractError("SEMANTIC_RESTART_HASH_MISSING:" + label)
    try:
        int(value, 16)
    except ValueError as exc:
        raise SupplyContractError("SEMANTIC_RESTART_HASH_INVALID:" + label) from exc
    return value.lower()


def semantic_hashes(snapshot):
    """Extract the stable restart contract from a live adapter snapshot."""
    if not isinstance(snapshot, dict):
        raise SupplyContractError("SEMANTIC_RESTART_SNAPSHOT_NOT_MAPPING")
    return {name: _require_hash(snapshot.get(name), name) for name in SEMANTIC_FIELDS}


def semantic_state_hash(snapshot):
    return canonical_hash({
        "schema": SCHEMA,
        "semantic_fields": list(SEMANTIC_FIELDS),
        "hashes": semantic_hashes(snapshot),
    })


def build_authority(snapshot, *, version_path=None, raw_ver_sha256=None,
                    origin="LIVE_VISUM_SNAPSHOT"):
    hashes = semantic_hashes(snapshot)
    return {
        "schema": SCHEMA,
        "origin": str(origin),
        "semantic_fields": list(SEMANTIC_FIELDS),
        "semantic_hashes": hashes,
        "semantic_state_hash": canonical_hash({
            "schema": SCHEMA,
            "semantic_fields": list(SEMANTIC_FIELDS),
            "hashes": hashes,
        }),
        "snapshot_state_hash_diagnostic": snapshot.get("state_hash"),
        "version_path_provenance": str(version_path) if version_path is not None else None,
        "raw_ver_sha256_provenance": (
            _require_hash(raw_ver_sha256, "raw_ver_sha256_provenance")
            if raw_ver_sha256 is not None else None),
        "raw_ver_sha_role": RAW_VER_SHA_ROLE,
        "raw_ver_sha_used_for_restart_acceptance": False,
        "cross_release_snapshot_state_hash_comparison_allowed": False,
    }


def compare_authorities(expected, actual, *, label="SEMANTIC_RESTART"):
    if not isinstance(expected, dict) or expected.get("schema") != SCHEMA:
        raise SupplyContractError(label + "_EXPECTED_SCHEMA_MISMATCH")
    if not isinstance(actual, dict) or actual.get("schema") != SCHEMA:
        raise SupplyContractError(label + "_ACTUAL_SCHEMA_MISMATCH")
    mismatches = []
    exp = expected.get("semantic_hashes", {})
    got = actual.get("semantic_hashes", {})
    for name in SEMANTIC_FIELDS:
        if exp.get(name) != got.get(name):
            mismatches.append(name)
    if expected.get("semantic_state_hash") != actual.get("semantic_state_hash"):
        if not mismatches:
            mismatches.append("semantic_state_hash")
    return {
        "passes": not mismatches,
        "mismatches": mismatches,
        "expected_semantic_state_hash": expected.get("semantic_state_hash"),
        "actual_semantic_state_hash": actual.get("semantic_state_hash"),
        "raw_ver_sha_compared": False,
    }


def require_authority_match(expected, actual, *, label="SEMANTIC_RESTART"):
    result = compare_authorities(expected, actual, label=label)
    if not result["passes"]:
        raise SupplyContractError(label + "_MISMATCH:" + ",".join(result["mismatches"]))
    return result


def sidecar_path(version_path):
    path = Path(version_path)
    return path.with_name(path.name + ".semantic.json")


def load_optional_sidecar(version_path):
    path = sidecar_path(version_path)
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SupplyContractError("SEMANTIC_RESTART_SIDECAR_UNREADABLE:" + str(path)) from exc
    if value.get("schema") != SCHEMA:
        raise SupplyContractError("SEMANTIC_RESTART_SIDECAR_SCHEMA_MISMATCH:" + str(path))
    # Validate every semantic hash, but intentionally do not compare the raw
    # .ver SHA: a legitimate manual Save may reserialize identical semantics.
    hashes = {}
    for name in SEMANTIC_FIELDS:
        hashes[name] = _require_hash(value.get("semantic_hashes", {}).get(name), name)
    stored = _require_hash(value.get("semantic_state_hash"), "semantic_state_hash")
    computed = canonical_hash({
        "schema": SCHEMA,
        "semantic_fields": list(SEMANTIC_FIELDS),
        "hashes": hashes,
    })
    if stored != computed:
        raise SupplyContractError(
            "SEMANTIC_RESTART_SIDECAR_SELF_INCONSISTENT:" + str(path))
    return value


__all__ = [
    "SCHEMA", "SEMANTIC_FIELDS", "RAW_VER_SHA_ROLE", "semantic_hashes",
    "semantic_state_hash", "build_authority", "compare_authorities",
    "require_authority_match", "sidecar_path", "load_optional_sidecar",
]
