# -*- coding: utf-8 -*-
"""Persistent, hash-authorized path-epoch checkpoints for R1 15A2 V2.4.8.

The SQLite route store is proposal evidence only.  Reuse never authorizes a
candidate: every candidate still requires a fresh native Visum recomputation and
live diagnostics.  A cache is reusable only when its immutable contract and an
explicit state binding match the currently opened model.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import os
import shutil
import sqlite3
import uuid

import r1_15a2_core as core
from r1_15a2_supply import SupplyContractError, canonical_hash, observation_identity, number

MANIFEST_SCHEMA = "R1_15A2_PERSISTENT_PATH_EPOCH_MANIFEST_V248"
BINDING_SCHEMA = "R1_15A2_PERSISTENT_PATH_EPOCH_BINDING_V248"
INDEX_SCHEMA = "R1_15A2_PERSISTENT_PATH_EPOCH_INDEX_V248"
CACHE_FORMAT_VERSION = 1
STORE_NAME = "TWO_MODE_PATH_STORE.sqlite"
MANIFEST_NAME = "PATH_EPOCH_MANIFEST.json"
STORE_SHA_NAME = "TWO_MODE_PATH_STORE.sqlite.sha256"
LATEST_NAME = "LATEST_PERSISTENT_PATH_EPOCH.json"
INDEX_NAME = "PATH_EPOCH_INDEX.json"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp." + uuid.uuid4().hex)
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=True, allow_nan=False, indent=2, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(str(tmp), str(path))


def read_json(path):
    path = Path(path)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SupplyContractError("PERSISTENT_PATH_CACHE_INVALID_JSON:%s:%s" % (path.name, exc))
    if not isinstance(value, dict):
        raise SupplyContractError("PERSISTENT_PATH_CACHE_JSON_NOT_OBJECT:" + path.name)
    return value


def atomic_text(path, value, encoding="utf-8"):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp." + uuid.uuid4().hex)
    with tmp.open("w", encoding=encoding) as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(str(tmp), str(path))


def sha256_file(path, chunk_size=8 * 1024 * 1024):
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def _profile_id(row):
    value = core.first_value(row, ("countlocation_no", "obs_id", "code"), "")
    value = str(value).strip()
    if not value:
        raise SupplyContractError("PERSISTENT_PATH_CACHE_INVALID_PROFILE_ID")
    return value


def profile_order_hash(rows):
    ids = [_profile_id(row) for row in rows]
    if len(ids) != len(set(ids)):
        raise SupplyContractError("PERSISTENT_PATH_CACHE_DUPLICATE_PROFILE_ID")
    return canonical_hash(ids)


def profile_model_hash(rows):
    return canonical_hash([(_profile_id(row), number(row.get("model"), "model")) for row in rows])


def immutable_snapshot_contract(snapshot):
    required = ("fixed_link_hash", "dseg_hash", "operations_hash")
    missing = [key for key in required if not snapshot.get(key)]
    if missing:
        raise SupplyContractError("PERSISTENT_PATH_CACHE_SNAPSHOT_CONTRACT_MISSING:" + ",".join(missing))
    return {key: snapshot[key] for key in required}


def origin_snapshot_contract(snapshot):
    keys = ("state_hash", "fixed_link_hash", "dseg_hash", "operations_hash",
            "addval_hash", "matrix_hash", "generation_hash", "td_hash")
    missing = [key for key in keys if not snapshot.get(key)]
    if missing:
        raise SupplyContractError("PERSISTENT_PATH_CACHE_ORIGIN_CONTRACT_MISSING:" + ",".join(missing))
    return {key: snapshot[key] for key in keys}


def _sqlite_uri(path):
    return Path(path).resolve().as_uri() + "?mode=ro"


def sqlite_metadata(path):
    """Read only the metadata table; integrity is checked after a candidate matches."""
    path = Path(path)
    if not path.is_file() or path.stat().st_size <= 0:
        raise SupplyContractError("PERSISTENT_PATH_CACHE_SQLITE_MISSING_OR_EMPTY")
    db = sqlite3.connect(_sqlite_uri(path), uri=True)
    try:
        db.execute("PRAGMA query_only=ON")
        return {str(k): str(v) for k, v in db.execute("SELECT key,value FROM metadata")}
    finally:
        db.close()


def sqlite_integrity(path, *, quick=True):
    path = Path(path)
    if not path.is_file() or path.stat().st_size <= 0:
        raise SupplyContractError("PERSISTENT_PATH_CACHE_SQLITE_MISSING_OR_EMPTY")
    db = sqlite3.connect(_sqlite_uri(path), uri=True)
    try:
        db.execute("PRAGMA query_only=ON")
        check = "quick_check" if quick else "integrity_check"
        rows = [str(row[0]) for row in db.execute("PRAGMA %s" % check)]
        if rows != ["ok"]:
            raise SupplyContractError("PERSISTENT_PATH_CACHE_SQLITE_%s_FAILED:%r" % (check.upper(), rows[:8]))
        fk = list(db.execute("PRAGMA foreign_key_check"))
        if fk:
            raise SupplyContractError("PERSISTENT_PATH_CACHE_SQLITE_FOREIGN_KEY_FAILED:%r" % (fk[:8],))
        metadata = {str(k): str(v) for k, v in db.execute("SELECT key,value FROM metadata")}
        return {"check": check, "result": rows[0], "foreign_key_violations": 0,
                "metadata": metadata}
    finally:
        db.close()


def cache_contract(cfg, snapshot, profiles, links, sqlite_schema):
    path_files = cfg.get("implementation_files", {})
    relevant_names = (
        "r1_15a2_two_mode_v238.py", "r1_15a2_trial_adapter_v240.py",
        "r1_15a2_persistent_path_cache_v248.py", "r1_15a2_sequence_v23.py",
        "r1_15a2_supply.py", "r1_15a2_core.py", "r1_15a2_runtime_v1.py",
    )
    implementation = {name: path_files.get(name) for name in relevant_names}
    if any(not value for value in implementation.values()):
        raise SupplyContractError("PERSISTENT_PATH_CACHE_IMPLEMENTATION_HASH_MISSING")
    two = cfg.get("two_mode", {})
    seq = cfg.get("supply", {}).get("sequence", {})
    contract = {
        "cache_format_version": CACHE_FORMAT_VERSION,
        "sqlite_schema": sqlite_schema,
        "config_sha256": cfg.get("config_sha256"),
        "path_implementation_files": implementation,
        "expected_zones": int(cfg.get("expected_zones")),
        "path_export_dsegs": sorted(core.norm_code(x) for x in cfg.get("path_export_dsegs", [])),
        "passenger_dsegs": sorted(core.norm_code(x) for x in cfg.get("supply", {}).get("passenger_dsegs", [])),
        "representatives": {core.norm_code(k): core.norm_code(v)
                            for k, v in two.get("representatives", {}).items()},
        "path_epoch_volume_comparison_decimals": int(two.get("path_epoch_volume_comparison_decimals", 6)),
        "duplicate_scope_policy": seq.get("design_only_duplicate_scope_policy"),
        "max_unique_sequences": int(seq.get("max_unique_sequences", 100000)),
        "max_pairs_per_market": int(seq.get("max_pairs_per_market", 64)),
        "observation_authority_hash": observation_identity(profiles, include_model=False),
        "profile_order_hash": profile_order_hash(profiles),
        "edge_dictionary_sha256": canonical_hash(sorted(tuple(int(v) for v in key) for key in links)),
        "immutable_snapshot": immutable_snapshot_contract(snapshot),
    }
    if not contract["config_sha256"] or len(str(contract["config_sha256"])) != 64:
        raise SupplyContractError("PERSISTENT_PATH_CACHE_CONFIG_HASH_MISSING")
    contract["contract_hash"] = canonical_hash(contract)
    return contract


class PersistentPathCacheManager:
    def __init__(self, cfg, control=None):
        perf = cfg.get("performance", {}).get("persistent_path_cache", {})
        self.cfg = cfg
        self.options = perf
        self.control = control
        self.enabled = perf.get("enabled") is True
        root = cfg.get("runtime_persistent_path_cache_root")
        self.root = Path(root) if root else None
        self.legacy_roots = [Path(x) for x in cfg.get("runtime_legacy_path_cache_roots", [])]
        self.retain = int(perf.get("retain_epoch_checkpoints", 3))
        self.max_total_bytes = int(float(perf.get("max_total_cache_gib", 24.0)) * (1024 ** 3))
        self.verify_sha = perf.get("verify_sha256_on_restore") is True
        self.quick_check = perf.get("sqlite_quick_check_on_restore") is True
        self.allow_legacy = perf.get("allow_legacy_v247_import") is True
        self.active_manifest = None
        if self.enabled:
            if self.root is None:
                raise SupplyContractError("PERSISTENT_PATH_CACHE_ROOT_MISSING")
            self.root.mkdir(parents=True, exist_ok=True)
            (self.root / "BINDINGS").mkdir(parents=True, exist_ok=True)
            (self.root / ".staging").mkdir(parents=True, exist_ok=True)

    def checkpoint(self, phase, **details):
        if self.control is None:
            return
        try:
            self.control.checkpoint(phase, force=True, **details)
        except TypeError:
            self.control.checkpoint(phase)

    def _binding_path(self, state_hash):
        return self.root / "BINDINGS" / (str(state_hash) + ".json")

    def _manifest_path(self, cache_dir):
        return Path(cache_dir) / MANIFEST_NAME

    def _load_manifest(self, cache_dir):
        manifest = read_json(self._manifest_path(cache_dir))
        if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("cache_format_version") != CACHE_FORMAT_VERSION:
            raise SupplyContractError("PERSISTENT_PATH_CACHE_MANIFEST_SCHEMA_MISMATCH")
        expected = canonical_hash({k: v for k, v in manifest.items()
                                   if k != "manifest_sha256"})
        if manifest.get("manifest_sha256") != expected:
            raise SupplyContractError("PERSISTENT_PATH_CACHE_MANIFEST_HASH_MISMATCH")
        return manifest

    def allocate_staging(self):
        if not self.enabled:
            raise SupplyContractError("PERSISTENT_PATH_CACHE_NOT_ENABLED")
        path = self.root / ".staging" / ("BUILD_" + uuid.uuid4().hex)
        path.mkdir(parents=False, exist_ok=False)
        return path

    def _candidate_from_binding(self, snapshot):
        path = self._binding_path(snapshot.get("state_hash"))
        if not path.is_file():
            return None
        binding = read_json(path)
        if binding.get("schema") != BINDING_SCHEMA or binding.get("state_hash") != snapshot.get("state_hash"):
            raise SupplyContractError("PERSISTENT_PATH_CACHE_BINDING_SCHEMA_MISMATCH")
        cache_dir = Path(binding.get("cache_dir", ""))
        if not cache_dir.is_dir():
            return None
        manifest = self._load_manifest(cache_dir)
        expected_immutable = immutable_snapshot_contract(snapshot)
        checks = {
            "cache_id": manifest.get("cache_id"),
            "manifest_sha256": manifest.get("manifest_sha256"),
            "origin_state_hash": manifest.get("origin_snapshot", {}).get("state_hash"),
            "immutable_snapshot": expected_immutable,
            "path_basis_hash": manifest.get("path_basis_hash"),
            "path_basis_comparison_hash": manifest.get("path_basis_comparison_hash"),
        }
        for key, expected in checks.items():
            if binding.get(key) != expected:
                raise SupplyContractError("PERSISTENT_PATH_CACHE_BINDING_MISMATCH:" + key)
        if expected_immutable != manifest.get("contract", {}).get("immutable_snapshot"):
            raise SupplyContractError("PERSISTENT_PATH_CACHE_BINDING_IMMUTABLE_CONTEXT_CHANGED")
        return cache_dir, binding

    def _candidate_from_origin(self, snapshot):
        for path in sorted(self.root.glob("EPOCH_*/" + MANIFEST_NAME), reverse=True):
            try:
                manifest = read_json(path)
            except SupplyContractError:
                continue
            if (manifest.get("schema") == MANIFEST_SCHEMA and
                    manifest.get("origin_snapshot", {}).get("state_hash") == snapshot.get("state_hash")):
                return path.parent, None
        return None

    def find_candidate(self, snapshot):
        if not self.enabled:
            return None
        bound = self._candidate_from_binding(snapshot)
        if bound is not None:
            return bound
        return self._candidate_from_origin(snapshot)

    def _explicit_predecessor_contract_compatibility(self, manifest, actual, expected):
        """Authorize a reviewed predecessor cache as a read-only path-data source.

        Historical releases keep their original exact-config/subset-module bridge.
        V2.4.8.8 uses the stricter *path semantic* bridge: the complete config
        digest is provenance only, every explicit path-data field remains exact,
        and the complete seven-module source implementation map must match a
        reviewed predecessor release.
        """
        rule = self.options.get("explicit_predecessor_read_compatibility", {})
        if rule.get("enabled") is not True:
            return None
        if self.cfg.get("release") != rule.get("target_release"):
            return None
        predecessors = rule.get("predecessors")
        if not isinstance(predecessors, list):
            return None

        semantic_policy = (
            "READ_ONLY_EXACT_PATH_DATA_CONTRACT_FULL_SOURCE_IMPL_PIN_"
            "CONFIG_DIGEST_PROVENANCE_ONLY")
        if rule.get("policy") != semantic_policy:
            # Preserve the V2.4.8.3--V2.4.8.7 compatibility semantics exactly.
            source = None
            for candidate in predecessors:
                if (isinstance(candidate, dict) and
                        manifest.get("release") == candidate.get("source_release") and
                        actual.get("config_sha256") == candidate.get("source_config_sha256")):
                    source = candidate
                    break
            if source is None or set(actual) != set(expected):
                return None
            ignored = {"config_sha256", "path_implementation_files", "contract_hash"}
            for key in expected:
                if key in ignored:
                    continue
                if actual.get(key) != expected.get(key):
                    return None
            actual_impl = actual.get("path_implementation_files")
            expected_impl = expected.get("path_implementation_files")
            source_impl = source.get("source_path_implementation_files")
            if (not isinstance(actual_impl, dict) or
                    not isinstance(expected_impl, dict) or
                    not isinstance(source_impl, dict)):
                return None
            if set(actual_impl) != set(expected_impl):
                return None
            if not source_impl or not set(source_impl).issubset(set(actual_impl)):
                return None
            for name, target_hash in expected_impl.items():
                predecessor_hash = actual_impl.get(name)
                if name in source_impl:
                    if predecessor_hash != source_impl.get(name):
                        return None
                elif predecessor_hash != target_hash:
                    return None
            return {
                "mode": "EXPLICIT_PREDECESSOR_READ_COMPATIBILITY",
                "target_release": self.cfg.get("release"),
                "source_release": manifest.get("release"),
                "source_config_sha256": actual.get("config_sha256"),
                "target_config_sha256": expected.get("config_sha256"),
                "allowed_path_implementation_differences": sorted(source_impl),
                "policy": "READ_ONLY_STORE_EXACT_DATA_CONTRACT_NO_ROUTE_SHARE_INVENTION",
            }

        # V2.4.8.8 path-semantic bridge.
        source = None
        for candidate in predecessors:
            if (isinstance(candidate, dict) and
                    manifest.get("release") == candidate.get("source_release")):
                source = candidate
                break
        if source is None or set(actual) != set(expected):
            return None

        # config_sha256 and contract_hash are provenance-only for path-cache
        # compatibility. Every explicit path semantic field remains exact.
        ignored = {"config_sha256", "path_implementation_files", "contract_hash"}
        for key in expected:
            if key in ignored:
                continue
            if actual.get(key) != expected.get(key):
                return None

        actual_impl = actual.get("path_implementation_files")
        expected_impl = expected.get("path_implementation_files")
        source_impl = source.get("source_path_implementation_files")
        if (not isinstance(actual_impl, dict) or
                not isinstance(expected_impl, dict) or
                not isinstance(source_impl, dict)):
            return None
        # The source rule pins the COMPLETE implementation map, not just files
        # known to have changed. Target code may differ because it only reads the
        # immutable store; saved path semantics are separately exact above.
        if set(actual_impl) != set(expected_impl) or set(source_impl) != set(actual_impl):
            return None
        if actual_impl != source_impl:
            return None

        known_cfg = source.get("source_config_sha256s")
        if known_cfg is None:
            one = source.get("source_config_sha256")
            known_cfg = [one] if one else []
        if not isinstance(known_cfg, list):
            return None
        if any((not isinstance(x, str) or len(x) != 64) for x in known_cfg):
            return None
        actual_cfg = actual.get("config_sha256")
        config_digest_recognized = actual_cfg in known_cfg if known_cfg else False

        return {
            "mode": "EXPLICIT_PREDECESSOR_PATH_SEMANTIC_COMPATIBILITY",
            "target_release": self.cfg.get("release"),
            "source_release": manifest.get("release"),
            "source_config_sha256": actual_cfg,
            "source_config_sha256_recognized": bool(config_digest_recognized),
            "known_source_config_sha256s": known_cfg,
            "target_config_sha256": expected.get("config_sha256"),
            "path_implementation_hashes_fully_pinned": True,
            "policy": "READ_ONLY_STORE_EXACT_PATH_DATA_CONTRACT_FULL_SOURCE_IMPL_PIN",
        }

    def validate_manifest(self, manifest, snapshot, profiles, links, sqlite_schema):
        expected = cache_contract(self.cfg, snapshot, profiles, links, sqlite_schema)
        actual = manifest.get("contract")
        if not isinstance(actual, dict):
            raise SupplyContractError("PERSISTENT_PATH_CACHE_CONTRACT_MISSING")
        keys = ("cache_format_version", "sqlite_schema", "config_sha256",
                "path_implementation_files", "expected_zones", "path_export_dsegs",
                "passenger_dsegs", "representatives",
                "path_epoch_volume_comparison_decimals", "duplicate_scope_policy",
                "max_unique_sequences", "max_pairs_per_market",
                "observation_authority_hash", "profile_order_hash",
                "edge_dictionary_sha256", "immutable_snapshot", "contract_hash")
        mismatches = [key for key in keys if actual.get(key) != expected.get(key)]
        rule = self.options.get("explicit_predecessor_read_compatibility", {})
        semantic_policy = (
            "READ_ONLY_EXACT_PATH_DATA_CONTRACT_FULL_SOURCE_IMPL_PIN_"
            "CONFIG_DIGEST_PROVENANCE_ONLY")

        if rule.get("policy") != semantic_policy:
            # Historical behavior: the full config digest is part of exact
            # identity and only a pinned predecessor bridge may differ.
            if mismatches:
                compatibility = self._explicit_predecessor_contract_compatibility(
                    manifest, actual, expected)
                if compatibility is None:
                    raise SupplyContractError(
                        "PERSISTENT_PATH_CACHE_CONTRACT_MISMATCH:" + mismatches[0])
            else:
                compatibility = {
                    "mode": "EXACT_CONTRACT",
                    "source_release": manifest.get("release"),
                    "target_release": self.cfg.get("release"),
                }
        else:
            # V2.4.8.8: a complete config digest changes for unrelated
            # Generation/TD/Supply controls. It remains provenance, while the
            # explicit saved-path semantics and reviewed implementation identity
            # are the restore authority.
            semantic_keys = tuple(
                k for k in keys if k not in ("config_sha256", "contract_hash"))
            semantic_mismatches = [
                key for key in semantic_keys if actual.get(key) != expected.get(key)]
            if not semantic_mismatches:
                compatibility = {
                    "mode": ("EXACT_CONTRACT" if not mismatches else
                             "PATH_SEMANTIC_CONFIG_DIGEST_COMPATIBILITY"),
                    "source_release": manifest.get("release"),
                    "target_release": self.cfg.get("release"),
                    "source_config_sha256": actual.get("config_sha256"),
                    "target_config_sha256": expected.get("config_sha256"),
                    "full_config_digest_is_provenance_only": bool(mismatches),
                }
            else:
                compatibility = self._explicit_predecessor_contract_compatibility(
                    manifest, actual, expected)
                if compatibility is None:
                    raise SupplyContractError(
                        "PERSISTENT_PATH_CACHE_CONTRACT_MISMATCH:" +
                        semantic_mismatches[0])

        if manifest.get("origin_snapshot", {}).get("fixed_link_hash") != snapshot.get("fixed_link_hash"):
            raise SupplyContractError("PERSISTENT_PATH_CACHE_FIXED_LINK_CONTEXT_CHANGED")
        return compatibility

    def validate_store(self, cache_dir, manifest):
        store = Path(cache_dir) / STORE_NAME
        if not store.is_file() or store.stat().st_size != int(manifest.get("store_size_bytes", -1)):
            raise SupplyContractError("PERSISTENT_PATH_CACHE_STORE_SIZE_MISMATCH")
        self.checkpoint("PERSISTENT_PATH_CACHE_SQLITE_INTEGRITY", cache=str(cache_dir))
        integrity = sqlite_integrity(store, quick=self.quick_check)
        if integrity["metadata"].get("schema") != manifest.get("sqlite_schema"):
            raise SupplyContractError("PERSISTENT_PATH_CACHE_SQLITE_SCHEMA_MISMATCH")
        if integrity["metadata"].get("parent_hash") != manifest.get("origin_snapshot", {}).get("state_hash"):
            raise SupplyContractError("PERSISTENT_PATH_CACHE_PARENT_HASH_MISMATCH")
        if integrity["metadata"].get("structural_export_complete") != "true":
            raise SupplyContractError("PERSISTENT_PATH_CACHE_EXPORT_INCOMPLETE")
        if integrity["metadata"].get("incidence_ready") != "true":
            raise SupplyContractError("PERSISTENT_PATH_CACHE_INCIDENCE_NOT_READY")
        digest = None
        if self.verify_sha:
            self.checkpoint("PERSISTENT_PATH_CACHE_SHA256", bytes=store.stat().st_size)
            digest = sha256_file(store)
            if digest != manifest.get("store_sha256"):
                raise SupplyContractError("PERSISTENT_PATH_CACHE_SHA256_MISMATCH")
            sidecar = Path(cache_dir) / STORE_SHA_NAME
            if not sidecar.is_file():
                raise SupplyContractError("PERSISTENT_PATH_CACHE_SHA256_SIDECAR_MISSING")
            parts = sidecar.read_text(encoding="ascii").strip().split()
            if len(parts) != 2 or parts[0] != digest or parts[1] != STORE_NAME:
                raise SupplyContractError("PERSISTENT_PATH_CACHE_SHA256_SIDECAR_MISMATCH")
        return {"store": store, "integrity": integrity, "sha256": digest}

    def bind_state(self, snapshot, manifest, *, reason, phase):
        if not self.enabled or manifest is None:
            return None
        immutable = immutable_snapshot_contract(snapshot)
        if immutable != manifest.get("contract", {}).get("immutable_snapshot"):
            raise SupplyContractError("PERSISTENT_PATH_CACHE_BINDING_IMMUTABLE_CONTEXT_CHANGED")
        record = {
            "schema": BINDING_SCHEMA,
            "created_utc": utc_now(),
            "state_hash": snapshot["state_hash"],
            "cache_id": manifest["cache_id"],
            "cache_dir": manifest["cache_dir"],
            "manifest_sha256": manifest["manifest_sha256"],
            "origin_state_hash": manifest["origin_snapshot"]["state_hash"],
            "immutable_snapshot": immutable,
            "path_basis_hash": manifest["path_basis_hash"],
            "path_basis_comparison_hash": manifest["path_basis_comparison_hash"],
            "reason": str(reason),
            "phase": str(phase).upper(),
        }
        atomic_json(self._binding_path(snapshot["state_hash"]), record)
        return record

    def _write_index(self, manifest):
        index_path = self.root / INDEX_NAME
        if index_path.is_file():
            try:
                index = read_json(index_path)
            except SupplyContractError:
                index = {"schema": INDEX_SCHEMA, "entries": []}
        else:
            index = {"schema": INDEX_SCHEMA, "entries": []}
        if index.get("schema") != INDEX_SCHEMA or not isinstance(index.get("entries"), list):
            index = {"schema": INDEX_SCHEMA, "entries": []}
        entries = [e for e in index["entries"] if e.get("cache_id") != manifest["cache_id"]]
        entries.append({k: manifest[k] for k in (
            "cache_id", "cache_dir", "created_utc", "origin_snapshot",
            "path_basis_hash", "path_basis_comparison_hash", "store_sha256",
            "store_size_bytes", "manifest_sha256")})
        index["entries"] = sorted(entries, key=lambda e: e.get("created_utc", ""))
        index["updated_utc"] = utc_now()
        atomic_json(index_path, index)
        latest = {"schema": INDEX_SCHEMA, "updated_utc": utc_now(),
                  "latest": index["entries"][-1]}
        atomic_json(self.root / LATEST_NAME, latest)

    def _prune(self, keep_cache_ids):
        if self.retain < 1 or self.max_total_bytes <= 0:
            raise SupplyContractError("PERSISTENT_PATH_CACHE_INVALID_RETENTION")
        manifests = []
        for path in self.root.glob("EPOCH_*/" + MANIFEST_NAME):
            try:
                m = self._load_manifest(path.parent)
                manifests.append((m.get("created_utc", ""), path.parent, m))
            except SupplyContractError:
                continue
        manifests.sort(key=lambda item: item[0], reverse=True)
        mandatory = set(keep_cache_ids)
        keep = set()
        retained_bytes = 0
        # The just-published/active cache is mandatory even if it alone approaches
        # the configured total cap.
        for _, _, manifest in manifests:
            if manifest.get("cache_id") in mandatory:
                keep.add(manifest.get("cache_id"))
                retained_bytes += int(manifest.get("store_size_bytes", 0))
        for _, _, manifest in manifests:
            cache_id = manifest.get("cache_id")
            if cache_id in keep:
                continue
            size = int(manifest.get("store_size_bytes", 0))
            if len(keep) >= self.retain:
                continue
            if retained_bytes + size > self.max_total_bytes:
                continue
            keep.add(cache_id)
            retained_bytes += size
        removed = []
        for _, cache_dir, manifest in manifests:
            if manifest.get("cache_id") in keep:
                continue
            shutil.rmtree(cache_dir)
            removed.append(manifest.get("cache_id"))
        if removed:
            for binding_path in (self.root / "BINDINGS").glob("*.json"):
                try:
                    binding = read_json(binding_path)
                    if binding.get("cache_id") in removed:
                        binding_path.unlink()
                except Exception:
                    pass
        # Always rebuild public pointers from physical survivors; neither an old
        # index entry nor an old binding may authorize a pruned cache.
        survivors = [m for _, cache_dir, m in manifests
                     if m.get("cache_id") in keep and cache_dir.is_dir()]
        survivors.sort(key=lambda m: m.get("created_utc", ""))
        if not survivors:
            raise SupplyContractError("PERSISTENT_PATH_CACHE_PRUNE_REMOVED_ALL_EPOCHS")
        entries = [{k: m[k] for k in (
            "cache_id", "cache_dir", "created_utc", "origin_snapshot",
            "path_basis_hash", "path_basis_comparison_hash", "store_sha256",
            "store_size_bytes", "manifest_sha256")} for m in survivors]
        atomic_json(self.root / INDEX_NAME, {
            "schema": INDEX_SCHEMA, "updated_utc": utc_now(),
            "entries": entries, "retained_bytes": retained_bytes,
            "retention_count_limit": self.retain,
            "retention_byte_limit": self.max_total_bytes,
        })
        atomic_json(self.root / LATEST_NAME, {
            "schema": INDEX_SCHEMA, "updated_utc": utc_now(),
            "latest": entries[-1],
        })
        return removed

    def publish(self, staging_dir, collector, snapshot, profiles, links, *,
                sequence_evidence_ready, source_version_sha256=None,
                legacy_imported_from=None):
        if not self.enabled:
            raise SupplyContractError("PERSISTENT_PATH_CACHE_NOT_ENABLED")
        staging_dir = Path(staging_dir)
        store = staging_dir / STORE_NAME
        if Path(collector.route_db_path).resolve() != store.resolve():
            raise SupplyContractError("PERSISTENT_PATH_CACHE_STAGING_PATH_MISMATCH")
        collector.prepare_incidence_evidence()
        basis = collector.path_basis_hash()
        comparison = collector.path_basis_comparison_hash()
        structure = collector.path_structure_hash()
        sqlite_schema = str(collector.summary.get("schema"))
        contract = cache_contract(self.cfg, snapshot, profiles, links, sqlite_schema)
        # Persist only immutable cache metadata.  Dynamic driver evidence remains
        # rebuildable from normalized geometry and profile hits.
        collector.db.execute("INSERT OR REPLACE INTO metadata VALUES(?,?)",
                             ("persistent_cache_format", str(CACHE_FORMAT_VERSION)))
        collector.db.execute("INSERT OR REPLACE INTO metadata VALUES(?,?)",
                             ("observation_authority_hash", contract["observation_authority_hash"]))
        collector.db.execute("INSERT OR REPLACE INTO metadata VALUES(?,?)",
                             ("profile_order_hash", contract["profile_order_hash"]))
        collector.db.execute("INSERT OR REPLACE INTO metadata VALUES(?,?)",
                             ("path_basis_hash", basis))
        collector.db.execute("INSERT OR REPLACE INTO metadata VALUES(?,?)",
                             ("path_basis_comparison_hash", comparison))
        collector.db.execute("INSERT OR REPLACE INTO metadata VALUES(?,?)",
                             ("path_structure_hash", structure))
        collector.db.commit()
        collector.close()
        integrity = sqlite_integrity(store, quick=False)
        self.checkpoint("PERSISTENT_PATH_CACHE_PUBLISH_HASH", bytes=store.stat().st_size)
        digest = sha256_file(store)
        cache_id = "EPOCH_%s_%s_%s" % (
            datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
            snapshot["state_hash"][:12], basis[:12])
        final_dir = self.root / cache_id
        if final_dir.exists():
            raise SupplyContractError("PERSISTENT_PATH_CACHE_ID_COLLISION")
        manifest = {
            "schema": MANIFEST_SCHEMA,
            "cache_format_version": CACHE_FORMAT_VERSION,
            "cache_id": cache_id,
            "cache_dir": str(final_dir),
            "created_utc": utc_now(),
            "release": self.cfg.get("release"),
            "source_version_sha256": source_version_sha256,
            "origin_snapshot": origin_snapshot_contract(snapshot),
            "contract": contract,
            "sqlite_schema": sqlite_schema,
            "store_file": STORE_NAME,
            "store_size_bytes": store.stat().st_size,
            "store_sha256": digest,
            "sqlite_integrity": {"check": integrity["check"], "result": integrity["result"],
                                 "foreign_key_violations": 0},
            "path_basis_hash": basis,
            "path_basis_comparison_hash": comparison,
            "path_structure_hash": structure,
            "sequence_evidence_persisted": False,
            "sequence_evidence_was_ready_at_publish": bool(sequence_evidence_ready),
            "acceptance_authority": "FRESH_VISUM_ASSIGNMENT_PLUS_LIVE_12D_11D",
            "legacy_imported_from": str(legacy_imported_from) if legacy_imported_from else None,
        }
        manifest["manifest_sha256"] = canonical_hash({k: v for k, v in manifest.items()
                                                       if k != "manifest_sha256"})
        atomic_json(staging_dir / MANIFEST_NAME, manifest)
        atomic_text(staging_dir / STORE_SHA_NAME,
                    "%s  %s\n" % (digest, STORE_NAME), encoding="ascii")
        os.replace(str(staging_dir), str(final_dir))
        # Read back from final location before publishing pointers/bindings.
        manifest = self._load_manifest(final_dir)
        if manifest.get("manifest_sha256") != canonical_hash({k: v for k, v in manifest.items()
                                                               if k != "manifest_sha256"}):
            raise SupplyContractError("PERSISTENT_PATH_CACHE_MANIFEST_READBACK_MISMATCH")
        self.validate_store(final_dir, manifest)
        self.active_manifest = manifest
        # Publication order is deliberate: immutable payload + manifest first,
        # then origin-state binding, and only then public index/latest pointers.
        self.bind_state(snapshot, manifest, reason="PATH_EPOCH_ORIGIN_PUBLISHED", phase="ENUMERATION")
        self._write_index(manifest)
        removed = self._prune({manifest["cache_id"]})
        return manifest, {"published": True, "cache_id": manifest["cache_id"],
                          "cache_dir": str(final_dir), "store_sha256": digest,
                          "store_size_bytes": manifest["store_size_bytes"],
                          "pruned_cache_ids": removed}

    def import_legacy(self, source_store, collector, snapshot, profiles, links,
                      *, source_version_sha256=None):
        """Copy an already validated V2.4.7/V2.4.5 store into V2.4.8 authority."""
        staging = self.allocate_staging()
        destination = staging / STORE_NAME
        collector.close()
        source_store = Path(source_store)
        reserve = int(float(self.cfg.get("two_mode", {}).get("min_free_disk_gib", 1.0)) * (1024 ** 3))
        free = shutil.disk_usage(staging).free
        if free < source_store.stat().st_size + reserve:
            shutil.rmtree(staging, ignore_errors=True)
            raise SupplyContractError("PERSISTENT_PATH_CACHE_LEGACY_IMPORT_INSUFFICIENT_DISK")
        shutil.copy2(str(source_store), str(destination))
        # Reopen a minimal writable connection only to add immutable metadata;
        # publish() will then close it and make the final store read-only in use.
        from r1_15a2_two_mode_v238 import TwoModeRouteCollector
        reopened = TwoModeRouteCollector.open_existing(
            profiles, collector.policy, links, destination, collector.settings,
            collector.control, duplicate_scope_policy=self.cfg.get("supply", {}).get(
                "sequence", {}).get("design_only_duplicate_scope_policy", "FAIL"),
            max_unique_sequences=collector.max_unique_sequences,
            max_pairs_per_market=collector.max_pairs_per_market,
            read_only=False,
        )
        return self.publish(staging, reopened, snapshot, profiles, links,
                            sequence_evidence_ready=False,
                            source_version_sha256=source_version_sha256,
                            legacy_imported_from=source_store)

    def legacy_candidates(self, snapshot, sqlite_schema, max_candidates=20):
        if not self.enabled or not self.allow_legacy:
            return []
        found = []
        for root in self.legacy_roots:
            if not root.is_dir():
                continue
            try:
                paths = sorted(root.rglob(STORE_NAME), key=lambda p: p.stat().st_mtime, reverse=True)
            except OSError:
                continue
            for path in paths:
                if len(found) >= max_candidates:
                    break
                try:
                    meta = sqlite_metadata(path)
                    if (meta.get("schema") == sqlite_schema and
                            meta.get("parent_hash") == snapshot.get("state_hash") and
                            meta.get("structural_export_complete") == "true" and
                            meta.get("incidence_ready") == "true"):
                        found.append(path)
                except Exception:
                    continue
            if len(found) >= max_candidates:
                break
        return found

    def close(self):
        pass
