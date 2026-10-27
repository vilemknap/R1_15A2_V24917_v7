"""V2.4.0 trial-calibration adapter.

Two-mode saved paths are used only to DESIGN candidate parameter changes.
Every candidate is accepted/rejected from a fresh real Visum assignment and
live 12D/11D diagnostics. Production release/apply is intentionally separate.
No LoadVersion is exposed by this adapter.
"""
from pathlib import Path
import copy
import inspect
import shutil

import numpy as np

import r1_15a2_runtime_v1 as rt
from r1_15a2_supply import SupplyContractError
from r1_15a2_supply_visum import VisumAdapter as BaseAdapter, base
from r1_15a2_sequence_v23 import propose_sequence_supply
from r1_15a2_two_mode_v238 import (
    TwoModeRouteCollector, collect_two_modes, DEFAULT_SETTINGS, PROVISIONAL,
    SCHEMA as TWO_MODE_SCHEMA, atomic_json, QuietControl,
)
from r1_15a2_perf_v246 import optional_span
from r1_15a2_assignment_authority_v239 import audit_assignment_scope
from r1_15a2_persistent_path_cache_v248 import (
    PersistentPathCacheManager, STORE_NAME, MANIFEST_NAME,
)


class VisumAdapter(BaseAdapter):
    runtime_backend = "VISUM_COM_V240_TRIAL_ASSIGNMENT"

    def __init__(self, visum, cfg, control=None):
        if cfg.get("production_apply", False):
            raise SupplyContractError("V240_PRODUCTION_APPLY_FORBIDDEN")
        if not cfg.get("trial_calibration", {}).get("enabled", False):
            raise SupplyContractError("V240_EXPLICIT_TRIAL_CALIBRATION_REQUIRED")
        # Keep cfg.apply false: this is an isolated working-copy trial calibrator,
        # not a production release gate. Writes are controlled by the V240
        # controller and are always followed by real recomputation/evaluation.
        if cfg.get("apply") is not False:
            raise SupplyContractError("V240_CFG_APPLY_MUST_REMAIN_FALSE")
        super().__init__(visum, cfg)
        self.control = control or QuietControl()
        self.telemetry = getattr(self.control, "telemetry", None)
        self.cache = None
        self.cache_links = None
        self.cache_snapshot = None
        self.cache_live_snapshot = None
        self.initial_snapshot = None
        self.path_epoch_index = 0
        self.path_epoch_accepts = 0
        self.path_epoch_refresh_counts = {"DEMAND": 0, "SUPPLY": 0}
        self.path_epoch_plateau_verified = None
        self.path_epoch_history = []
        self.persistent_path_cache = PersistentPathCacheManager(cfg, self.control)
        self.persistent_cache_manifest = None
        self.persistent_cache_restore_record = None

    def checkpoint(self, phase, **details):
        try:
            self.control.checkpoint(phase, force=True, **details)
        except TypeError:
            self.control.checkpoint(phase)

    def preflight(self, folder):
        folder = Path(folder)
        self.checkpoint("PREFLIGHT")
        scope = audit_assignment_scope(self.visum)
        rt.write_json(folder / "00_V240_ASSIGNMENT_SCOPE.json", scope)
        if not scope.get("passes") or scope.get("selected_trial_assignment_operations") != [20]:
            raise SupplyContractError("V240_OP20_SCOPE_AUTHORITY_FAILED")
        out = super().preflight(folder)
        # super() does not enforce apply gates because cfg.apply is false; V240
        # explicitly requires the same live TG/procseq/assignment plan quality.
        if not out.get("apply_preflight_passes"):
            raise SupplyContractError("V240_LIVE_RECOMPUTE_PREFLIGHT_FAILED")
        self.initial_snapshot = self.snapshot()
        return out

    def restore(self, *args, **kwargs):
        raise SupplyContractError("V240_LOADVERSION_ROLLBACK_FORBIDDEN")

    def _path_epoch_cfg(self):
        return self.cfg.get("performance", {}).get("path_epochs", {})

    def path_epochs_enabled(self):
        return self._path_epoch_cfg().get("enabled") is True

    def invalidate_cache(self, reason="STATE_CHANGED", clear_proof=False):
        """Hard-close the current epoch.

        Accepted state changes use ``accepted_state_changed`` in V2.4.7 and do
        not call this method.  Keeping the destructive operation explicit avoids
        accidentally retaining a cache after a network/schema drift.
        """
        self.cache_snapshot = None
        self.cache_live_snapshot = None
        self.cache_links = None
        if self.cache is not None:
            try:
                self.cache.close()
            finally:
                self.cache = None
                self.cache_links = None
                self.cache_snapshot = None
                self.cache_live_snapshot = None
        if clear_proof:
            self.supply_path_proof = None

    def _epoch_basis(self):
        if self.cache is None or not self.cache.incidence_ready:
            return None
        return self.cache.path_basis_hash()

    def _epoch_comparison_basis(self):
        if self.cache is None or not self.cache.incidence_ready:
            return None
        method = getattr(self.cache, "path_basis_comparison_hash", None)
        return method() if method is not None else self.cache.path_basis_hash()

    def path_epoch_status(self):
        return {
            "enabled": self.path_epochs_enabled(),
            "epoch": self.path_epoch_index,
            "epoch_origin_state_hash": (self.cache_snapshot or {}).get("state_hash"),
            "live_state_hash": (self.cache_live_snapshot or {}).get("state_hash"),
            "basis_hash": self._epoch_basis(),
            "comparison_basis_hash": self._epoch_comparison_basis(),
            "accepted_state_changes_on_epoch": self.path_epoch_accepts,
            "refresh_counts": dict(self.path_epoch_refresh_counts),
            "plateau_verified": copy.deepcopy(self.path_epoch_plateau_verified),
            "persistent_cache_id": ((getattr(self, "persistent_cache_manifest", None) or {}).get("cache_id")),
            "persistent_cache_dir": ((getattr(self, "persistent_cache_manifest", None) or {}).get("cache_dir")),
            "persistent_cache_restore": copy.deepcopy(getattr(self, "persistent_cache_restore_record", None)),
        }

    def accepted_state_changed(self, snapshot, diag=None, *, reason="ACCEPTED_STATE_CHANGED", phase="DEMAND"):
        """Advance the live accepted state while retaining the frozen path basis."""
        if not self.path_epochs_enabled() or self.cache is None:
            self.invalidate_cache(reason, clear_proof=True)
            return {"retained": False, "reason": reason}
        origin = self.cache_snapshot or {}
        for name in ("fixed_link_hash", "dseg_hash", "operations_hash"):
            if origin.get(name) != snapshot.get(name):
                raise SupplyContractError("PATH_EPOCH_IMMUTABLE_CONTEXT_CHANGED:" + name)
        self.cache_live_snapshot = snapshot
        self.path_epoch_accepts += 1
        self.path_epoch_plateau_verified = None
        self.supply_path_proof = None
        # Current ADDVAL1 values are available in the accepted snapshot; refresh
        # the cheap proposal records without COM route enumeration.
        current = snapshot.get("addval1", {})
        if self.cache_links is not None:
            for key,row in self.cache_links.items():
                text = "|".join(str(int(x)) for x in key)
                if text not in current:
                    raise SupplyContractError("PATH_EPOCH_ADDVAL_KEY_SET_CHANGED")
                row["addval1"] = float(current[text])
        rec = {"retained": True, "reason": reason, "phase": str(phase).upper(),
               "epoch": self.path_epoch_index,
               "epoch_origin_state_hash": origin.get("state_hash"),
               "live_state_hash": snapshot.get("state_hash"),
               "basis_hash": self._epoch_basis(),
               "accepted_state_changes_on_epoch": self.path_epoch_accepts}
        persistent = getattr(self, "persistent_path_cache", None)
        manifest = getattr(self, "persistent_cache_manifest", None)
        if persistent is not None and persistent.enabled and manifest is not None:
            rec["persistent_binding"] = persistent.bind_state(
                snapshot, manifest, reason=reason, phase=phase)
        telemetry = getattr(self, "telemetry", None)
        if telemetry is not None:
            telemetry.event("PATH_EPOCH_RETAINED_AFTER_ACCEPT", **rec)
        return rec

    def assign(self, folder, *, supply_only):
        # Keep the accepted-parent cache open while a candidate is evaluated.
        # A rejected candidate is recomputed back to the exact same accepted state,
        # so the pre-trial cache remains the stronger authority. The controller
        # explicitly invalidates it immediately after an accepted state change.
        return super().assign(folder, supply_only=supply_only)

    def _retire_obsolete_epoch_store(self, store_path, audit_folder):
        """Remove only a superseded local SQLite payload after a verified refresh.

        Hashes, summaries and the accepted .ver checkpoint remain.  Keeping every
        multi-gigabyte route store would be an unbounded disk leak across epochs.
        """
        if not store_path:
            return {"retired": False, "reason": "NO_PREVIOUS_STORE"}
        persistent = getattr(self, "persistent_path_cache", None)
        if persistent is not None and persistent.enabled:
            try:
                if Path(store_path).resolve().is_relative_to(persistent.root.resolve()):
                    return {"retired": False, "reason": "PERSISTENT_CACHE_MANAGER_OWNS_RETENTION",
                            "path": str(store_path)}
            except AttributeError:
                root = str(persistent.root.resolve())
                if str(Path(store_path).resolve()).startswith(root + str(Path('/'))):
                    return {"retired": False, "reason": "PERSISTENT_CACHE_MANAGER_OWNS_RETENTION",
                            "path": str(store_path)}
        cfg = self._path_epoch_cfg()
        if cfg.get("cleanup_obsolete_sqlite_after_verified_refresh") is not True:
            return {"retired": False, "reason": "CLEANUP_DISABLED", "path": str(store_path)}
        if int(cfg.get("retain_sqlite_stores", 1)) != 1:
            raise SupplyContractError("PATH_EPOCH_UNSUPPORTED_SQLITE_RETENTION_POLICY")
        path = Path(store_path)
        if path.name != "TWO_MODE_PATH_STORE.sqlite":
            raise SupplyContractError("PATH_EPOCH_REFUSE_UNEXPECTED_STORE_DELETE")
        removed = []
        for candidate in (path, Path(str(path) + "-journal"), Path(str(path) + "-wal"),
                          Path(str(path) + "-shm")):
            try:
                if candidate.exists():
                    candidate.unlink()
                    removed.append(str(candidate))
            except PermissionError as exc:
                # Cleanup is not a model-correctness gate.  Windows can keep a
                # just-closed SQLite handle alive briefly while an exception
                # stack/cursor is being unwound.  The newly verified epoch must
                # remain usable; defer physical cleanup instead of converting
                # a successful refresh into a calibration failure.
                record = {"retired": False, "store": str(path),
                          "removed": removed,
                          "reason": "DELETE_DEFERRED_WINDOWS_FILE_LOCK",
                          "delete_error": str(exc),
                          "policy": "NONFATAL_CLEANUP_AFTER_NEW_EPOCH_VERIFIED"}
                atomic_json(Path(audit_folder) / "PATH_EPOCH_STORE_RETENTION.json", record)
                return record
            except OSError as exc:
                raise SupplyContractError("PATH_EPOCH_OBSOLETE_STORE_DELETE_FAILED:" + str(exc))
        record = {"retired": True, "store": str(path), "removed": removed,
                  "policy": "RETAIN_CURRENT_SQLITE_ONLY_AFTER_NEW_EPOCH_VERIFIED"}
        atomic_json(Path(audit_folder) / "PATH_EPOCH_STORE_RETENTION.json", record)
        return record

    def _legacy_profile_flow_gate(self, collector):
        rows = []
        for i, profile in enumerate(collector.profiles):
            model = float(profile["model"])
            got = float(collector.flow[i])
            diff = abs(got - model)
            tolerance = max(self.policy.parity_absolute_tolerance,
                            self.policy.parity_relative_tolerance * abs(model))
            rows.append({"profile_index": i, "model": model, "path_flow": got,
                         "absolute_difference": diff, "tolerance": tolerance,
                         "passes": diff <= tolerance})
        if not rows or not all(row["passes"] for row in rows):
            raise SupplyContractError("PERSISTENT_PATH_CACHE_LEGACY_PROFILE_ORDER_OR_FLOW_MISMATCH")
        return {"passes": True, "profile_count": len(rows),
                "max_absolute_difference": max(row["absolute_difference"] for row in rows)}

    def _open_persistent_cache(self, cache_dir, manifest, diag, snapshot, links, settings, seq):
        contract_validation = self.persistent_path_cache.validate_manifest(
            manifest, snapshot, diag["d12"]["rows"], links,
            TWO_MODE_SCHEMA)
        validation = self.persistent_path_cache.validate_store(cache_dir, manifest)
        collector = TwoModeRouteCollector.open_existing(
            diag["d12"]["rows"], self.policy, links,
            Path(cache_dir) / STORE_NAME, settings, self.control,
            duplicate_scope_policy=seq.get(
                "design_only_duplicate_scope_policy",
                "DIAGNOSTIC_EXCLUDE_CONFLICTED_DRIVERS"),
            max_unique_sequences=seq.get("max_unique_sequences", 100000),
            max_pairs_per_market=seq.get("max_pairs_per_market", 64),
            read_only=True, require_profile_metadata=True)
        if collector.path_basis_hash() != manifest.get("path_basis_hash"):
            collector.close()
            raise SupplyContractError("PERSISTENT_PATH_CACHE_BASIS_HASH_MISMATCH")
        if collector.path_basis_comparison_hash() != manifest.get("path_basis_comparison_hash"):
            collector.close()
            raise SupplyContractError("PERSISTENT_PATH_CACHE_COMPARISON_HASH_MISMATCH")
        if collector.path_structure_hash() != manifest.get("path_structure_hash"):
            collector.close()
            raise SupplyContractError("PERSISTENT_PATH_CACHE_STRUCTURE_HASH_MISMATCH")
        self.persistent_path_cache.active_manifest = manifest
        binding = self.persistent_path_cache.bind_state(
            snapshot, manifest, reason="CROSS_RUN_PATH_EPOCH_RESTORED", phase="RESTORE")
        return collector, {
            "status": "PERSISTENT_PATH_EPOCH_RESTORED",
            "cache_id": manifest["cache_id"],
            "cache_dir": manifest["cache_dir"],
            "store_size_bytes": manifest["store_size_bytes"],
            "store_sha256_verified": validation.get("sha256") is not None,
            "binding": binding,
            "legacy_imported_from": manifest.get("legacy_imported_from"),
            "contract_validation": contract_validation,
        }

    def _try_persistent_restore(self, diag, folder, snapshot, links, settings, seq):
        if not self.persistent_path_cache.enabled:
            return None
        candidate = self.persistent_path_cache.find_candidate(snapshot)
        if candidate is not None:
            cache_dir, binding = candidate
            manifest = self.persistent_path_cache._load_manifest(cache_dir)
            try:
                collector, record = self._open_persistent_cache(
                    cache_dir, manifest, diag, snapshot, links, settings, seq)
            except SupplyContractError as exc:
                message = str(exc)
                # A semantically incompatible cache is a performance miss, not a
                # reason to abort a correct calibration. Corruption/integrity/
                # binding failures remain hard errors. The rejected immutable
                # cache is retained for forensic evidence and older releases.
                fallback_policy = self.cfg.get("performance", {}).get(
                    "persistent_path_cache", {}).get(
                    "explicit_predecessor_read_compatibility", {}).get(
                    "incompatible_candidate_policy")
                if (not message.startswith("PERSISTENT_PATH_CACHE_CONTRACT_MISMATCH:") or
                        fallback_policy !=
                        "REJECT_CACHE_AS_PERFORMANCE_MISS_THEN_LEGACY_OR_FRESH_ENUMERATION"):
                    raise
                atomic_json(Path(folder) / "PERSISTENT_PATH_CACHE_REJECTED.json", {
                    "status": "INCOMPATIBLE_PERSISTENT_CACHE_REJECTED",
                    "cache_id": manifest.get("cache_id"),
                    "cache_dir": str(cache_dir),
                    "source_release": manifest.get("release"),
                    "error": message,
                    "fallback": "LEGACY_EXACT_STATE_IMPORT_OR_FRESH_ENUMERATION",
                    "state_hash": snapshot.get("state_hash"),
                })
            else:
                record["matched_by"] = "STATE_BINDING" if binding is not None else "ORIGIN_STATE_HASH"
                atomic_json(Path(folder) / "PERSISTENT_PATH_CACHE_RESTORE.json", record)
                return collector, manifest, record

        # One-time safe import from a complete V2.4.7/V2.4.5 run. Legacy reuse
        # is allowed only for the exact origin state and requires all-profile
        # flow parity, which also proves the stored profile-index order.
        for store in self.persistent_path_cache.legacy_candidates(
                snapshot, TWO_MODE_SCHEMA):
            legacy = None
            try:
                legacy = TwoModeRouteCollector.open_existing(
                    diag["d12"]["rows"], self.policy, links, store, settings,
                    self.control,
                    duplicate_scope_policy=seq.get(
                        "design_only_duplicate_scope_policy",
                        "DIAGNOSTIC_EXCLUDE_CONFLICTED_DRIVERS"),
                    max_unique_sequences=seq.get("max_unique_sequences", 100000),
                    max_pairs_per_market=seq.get("max_pairs_per_market", 64),
                    read_only=True, require_profile_metadata=False)
                if legacy.parent_hash != snapshot.get("state_hash"):
                    legacy.close(); continue
                parity = self._legacy_profile_flow_gate(legacy)
                manifest, publication = self.persistent_path_cache.import_legacy(
                    store, legacy, snapshot, diag["d12"]["rows"], links,
                    source_version_sha256=self.cfg.get("runtime_source_version_sha256"))
                collector, record = self._open_persistent_cache(
                    manifest["cache_dir"], manifest, diag, snapshot, links,
                    settings, seq)
                record.update(matched_by="LEGACY_EXACT_STATE_IMPORT",
                              legacy_profile_flow_gate=parity,
                              publication=publication)
                atomic_json(Path(folder) / "PERSISTENT_PATH_CACHE_RESTORE.json", record)
                return collector, manifest, record
            except SupplyContractError:
                if legacy is not None and not getattr(legacy, '_closed', True):
                    legacy.close()
                continue
        atomic_json(Path(folder) / "PERSISTENT_PATH_CACHE_RESTORE.json", {
            "status": "NO_AUTHORIZED_PERSISTENT_CACHE_MATCH",
            "state_hash": snapshot.get("state_hash"),
        })
        return None

    def _build_cache(self, diag, folder, snapshot, *, build_sequence_evidence=False,
                     allow_persistent_restore=True):
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        obsolete_store = (getattr(self.cache, "route_db_path", None)
                          if self.cache is not None else None)
        self.invalidate_cache("NEW_ACCEPTED_STATE_CACHE", clear_proof=True)
        self.path_epoch_accepts = 0
        self.path_epoch_plateau_verified = None
        links_live = self.read_links()
        links = {k: {a: v for a, v in row.items() if a != "object"}
                 for k, row in links_live.items()}
        del links_live
        settings = dict(DEFAULT_SETTINGS, **self.cfg["two_mode"])
        settings["dseg_path_volume_relative_tolerance"] = self.cfg[
            "dseg_path_volume_relative_tolerance"]
        # The low-level bounded SaveToArray exporter must use the same reviewed
        # transient-only COM policy as diagnostics and zonal transactions.
        settings["com_retry_policy"] = dict(self.cfg.get("com_resilience", {}) or {})
        seq = self.cfg["supply"].get("sequence", {})

        if allow_persistent_restore:
            restored = self._try_persistent_restore(
                diag, folder, snapshot, links, settings, seq)
            if restored is not None:
                collector, manifest, restore_record = restored
                self.path_epoch_index += 1
                self.cache = collector
                self.cache_links = links
                self.cache_snapshot = dict(manifest["origin_snapshot"])
                self.cache_live_snapshot = snapshot
                self.persistent_cache_manifest = manifest
                self.persistent_cache_restore_record = restore_record
                epoch = {
                    "schema": "R1_15A2_PATH_EPOCH_V248",
                    "epoch": self.path_epoch_index,
                    "origin_state_hash": manifest["origin_snapshot"]["state_hash"],
                    "live_state_hash": snapshot["state_hash"],
                    "basis_hash": collector.path_basis_hash(),
                    "comparison_basis_hash": collector.path_basis_comparison_hash(),
                    "structure_hash": collector.path_structure_hash(),
                    "sequence_evidence_ready": False,
                    "persistent_cache_id": manifest["cache_id"],
                    "restored_cross_run": True,
                    "policy": "PERSISTENT_PATH_EPOCH_RESTORED_WITH_HASH_AND_STATE_BINDING",
                }
                self.path_epoch_history.append(epoch)
                atomic_json(folder / "PATH_EPOCH.json", epoch)
                return collector, links, restore_record

        self.path_epoch_index += 1
        self.persistent_cache_manifest = None
        self.persistent_cache_restore_record = None
        staging_dir = None
        if self.persistent_path_cache.enabled:
            staging_dir = self.persistent_path_cache.allocate_staging()
            db_path = staging_dir / STORE_NAME
        else:
            db_path = folder / STORE_NAME
        collector = TwoModeRouteCollector(
            diag["d12"]["rows"], self.policy, snapshot["state_hash"], links,
            db_path, settings, self.control,
            duplicate_scope_policy=seq.get(
                "design_only_duplicate_scope_policy",
                "DIAGNOSTIC_EXCLUDE_CONFLICTED_DRIVERS"),
            max_unique_sequences=seq.get("max_unique_sequences", 100000),
            max_pairs_per_market=seq.get("max_pairs_per_market", 64),
        )
        try:
            atomic_json(folder / "SUPPLY_DUPLICATE_SCOPE_AUDIT.json",
                        collector.duplicate_scope_audit)
            with optional_span(self, "TWO_MODE_PATH_EXPORT",
                               build_sequence_evidence=bool(build_sequence_evidence)):
                export = collect_two_modes(
                    self.visum, collector, self.cfg, folder,
                    build_sequence_evidence=build_sequence_evidence)
            if self.snapshot() != snapshot:
                raise SupplyContractError("V240_STATE_CHANGED_DURING_TWO_MODE_EXPORT")

            persistence = None
            if self.persistent_path_cache.enabled:
                manifest, persistence = self.persistent_path_cache.publish(
                    staging_dir, collector, snapshot, diag["d12"]["rows"], links,
                    sequence_evidence_ready=bool(build_sequence_evidence),
                    source_version_sha256=self.cfg.get(
                        "runtime_source_version_sha256"))
                collector, restore_record = self._open_persistent_cache(
                    manifest["cache_dir"], manifest, diag, snapshot, links,
                    settings, seq)
                self.persistent_cache_manifest = manifest
                self.persistent_cache_restore_record = {
                    "status": "NEW_PERSISTENT_PATH_EPOCH_PUBLISHED",
                    "publication": persistence,
                    "binding": restore_record.get("binding"),
                }
                export = dict(export,
                              persistent_cache_id=manifest["cache_id"],
                              persistent_cache_dir=manifest["cache_dir"],
                              persistent_store_sha256=manifest["store_sha256"])
            self.cache = collector
            self.cache_links = links
            self.cache_snapshot = snapshot
            self.cache_live_snapshot = snapshot
            epoch = {
                "schema": "R1_15A2_PATH_EPOCH_V248",
                "epoch": self.path_epoch_index,
                "origin_state_hash": snapshot["state_hash"],
                "basis_hash": collector.path_basis_hash(),
                "comparison_basis_hash": collector.path_basis_comparison_hash(),
                "structure_hash": collector.path_structure_hash(),
                "sequence_evidence_ready": bool(collector.sequence_ready),
                "persistent_cache_id": ((self.persistent_cache_manifest or {}).get(
                    "cache_id")),
                "restored_cross_run": False,
                "policy": "FREEZE_ENUMERATED_PATH_BASIS_UNTIL_LOCAL_PLATEAU",
            }
            self.path_epoch_history.append(epoch)
            atomic_json(folder / "PATH_EPOCH.json", epoch)
            epoch["obsolete_store_retention"] = self._retire_obsolete_epoch_store(
                obsolete_store, folder)
            atomic_json(folder / "PATH_EPOCH.json", epoch)
            return collector, links, export
        except BaseException:
            try:
                collector.ready = False
                collector.close()
            finally:
                if staging_dir is not None and Path(staging_dir).exists():
                    shutil.rmtree(staging_dir, ignore_errors=True)
            raise

    def _cache_context_compatible(self, snapshot):
        if self.cache is None or not self.cache.incidence_ready or self.cache_snapshot is None:
            return False
        return all(self.cache_snapshot.get(name) == snapshot.get(name)
                   for name in ("fixed_link_hash", "dseg_hash", "operations_hash"))

    def _sync_live_profiles(self, diag, snapshot, *, refresh_drivers):
        if not self._cache_context_compatible(snapshot):
            raise SupplyContractError("PATH_EPOCH_CACHE_CONTEXT_NOT_COMPATIBLE")
        audit = self.cache.rebind_profiles(
            diag["d12"]["rows"], refresh_drivers=refresh_drivers)
        self.cache_live_snapshot = snapshot
        current = snapshot.get("addval1", {})
        for key,row in (self.cache_links or {}).items():
            text = "|".join(str(int(x)) for x in key)
            if text not in current:
                raise SupplyContractError("PATH_EPOCH_ADDVAL_KEY_SET_CHANGED")
            row["addval1"] = float(current[text])
        return audit

    def _live_generation_matrices(self):
        codes = [rt.norm_code(x) for x in self.cfg.get("path_export_dsegs", [])]
        path_cfg = dict(self.cfg, path_export_dsegs=codes)
        rows = rt.selected_passenger_dsegs(self.visum, path_cfg)
        by = {r["norm_code"]:r for r in rows}
        if set(codes) != set(by):
            raise SupplyContractError("PATH_EPOCH_GENERATION_DSEG_SCOPE_CHANGED")
        n = int(self.cfg["expected_zones"])
        out = {}
        for code in codes:
            a = np.asarray(by[code]["object"].ODMatrix.GetValues(), dtype=float)
            if a.shape != (n,n) or not np.isfinite(a).all() or (a < -1e-10).any():
                raise SupplyContractError("PATH_EPOCH_INVALID_LIVE_OD_MATRIX:" + code)
            out[code] = a
        return out

    def supply_design(self, diag, folder, snapshot):
        folder = Path(folder)
        self.checkpoint("SUPPLY_DESIGN_BEGIN")
        if not self._cache_context_compatible(snapshot):
            collector, links, export = self._build_cache(
                diag, folder / "CACHE", snapshot, build_sequence_evidence=True)
        else:
            collector = self.cache
            links = self.cache_links
            profile_audit = self._sync_live_profiles(
                diag, snapshot, refresh_drivers=True)
            atomic_json(folder / "PATH_EPOCH_PROFILE_REBIND.json", profile_audit)
            with optional_span(self, "TWO_MODE_SEQUENCE_EVIDENCE_DEFERRED_BUILD"):
                export = collector.prepare_sequence_evidence()
            atomic_json(folder / "DEFERRED_SEQUENCE_EVIDENCE_SUMMARY.json", export)
        # Profile-flow parity is evidence, not a candidate-selection shortcut.
        rows = []
        for i, row in enumerate(collector.profiles):
            model = float(row["model"])
            diff = abs(collector.flow[i] - model)
            tol = max(self.policy.parity_absolute_tolerance,
                      self.policy.parity_relative_tolerance * abs(model))
            rows.append({"countlocation_no": row.get("countlocation_no", i),
                         "model": model, "path_flow": collector.flow[i],
                         "absolute_difference": diff, "tolerance": tol,
                         "passes": diff <= tol})
        rt.write_csv(folder / "SUPPLY_PROFILE_FLOW_PARITY.csv", rows)
        seq = self.cfg["supply"].get("sequence", {})
        design = propose_sequence_supply(
            collector, links, self.baseline_addval, self.policy,
            sequence_caps=seq.get("sequence_cap_schedule", [8, 4, 2, 1]),
            max_collateral_ratio=seq.get("max_collateral_volume_to_driver_ratio"),
            step_units=seq.get("step_units_schedule", [1]),
        )
        for candidate in design["candidates"]:
            epoch_parent = candidate.get("parent_hash")
            candidate["path_epoch_parent_hash"] = epoch_parent
            candidate["parent_hash"] = snapshot["state_hash"]
            candidate["path_epoch"] = self.path_epoch_index
            candidate["path_basis_hash"] = collector.path_basis_hash()
            candidate["path_basis_comparison_hash"] = collector.path_basis_comparison_hash()
            candidate.update(
                geometry_identity=PROVISIONAL,
                geometry_used_for="CANDIDATE_PROPOSAL_ONLY",
                trial_write_permitted=True,
                production_apply_permitted=False,
                acceptance_authority="FRESH_VISUM_ASSIGNMENT_PLUS_LIVE_12D_11D",
            )
        design.update(
            provisional=True,
            production_apply_permitted=False,
            trial_write_permitted=True,
            geometry_identity=PROVISIONAL,
            pathlink_geometry_full_identity_proven=False,
            duplicate_scope_audit=collector.duplicate_scope_audit,
            path_export_summary=export,
            route_store_file="TWO_MODE_PATH_STORE.sqlite",
            acceptance_authority="FRESH_VISUM_ASSIGNMENT_PLUS_LIVE_12D_11D",
            path_epoch=self.path_epoch_index,
            path_epoch_parent_hash=collector.parent_hash,
            path_basis_hash=collector.path_basis_hash(),
            path_basis_comparison_hash=collector.path_basis_comparison_hash(),
            live_parent_hash=snapshot["state_hash"],
        )
        self.supply_path_proof = {
            "parent_hash": snapshot["state_hash"],
            "assignment_path_hash": design["authority"]["assignment_path_hash"],
            "path_epoch": self.path_epoch_index,
            "path_epoch_parent_hash": collector.parent_hash,
            "path_basis_hash": collector.path_basis_hash(),
            "path_basis_comparison_hash": collector.path_basis_comparison_hash(),
        }
        rt.write_json(folder / "SUPPLY_PATH_SEQUENCE_DESIGN.json", design)
        return design

    def generation_design(self, diag, folder):
        folder = Path(folder)
        snapshot = self.snapshot()
        lazy = self.cfg.get("performance", {}).get(
            "lazy_supply_sequence_evidence", {}).get("enabled") is True
        if not self._cache_context_compatible(snapshot):
            collector, _, _ = self._build_cache(
                diag, folder / "GENERATION_CACHE", snapshot,
                build_sequence_evidence=not lazy)
        else:
            collector = self.cache
            profile_audit = self._sync_live_profiles(
                diag, snapshot, refresh_drivers=False)
            atomic_json(folder / "PATH_EPOCH_PROFILE_REBIND.json", profile_audit)
        live_matrices = self._live_generation_matrices()
        try:
            incidence_export = collector.incidence(
                self.cfg, self.actuatable_zones, live_od_matrices=live_matrices)
        except SupplyContractError as exc:
            if not str(exc).startswith("PATH_EPOCH_NEW_POSITIVE_OD_REQUIRES_REENUMERATION:"):
                raise
            # The frozen basis has no share for a newly positive OD relation.  A
            # refresh is mandatory; continuing would invent a route split.
            collector, _, _ = self._build_cache(
                diag, folder / "FORCED_SUPPORT_REFRESH", snapshot,
                build_sequence_evidence=not lazy,
                allow_persistent_restore=False)
            incidence_export = collector.incidence(
                self.cfg, self.actuatable_zones, live_od_matrices=live_matrices)
        rt.write_json(folder / "TWO_MODE_CACHE_REUSE.json", {
            "cache": collector.route_db_path,
            "path_epoch": self.path_epoch_index,
            "path_epoch_parent_hash": collector.parent_hash,
            "live_parent_hash": snapshot["state_hash"],
            "path_basis_hash": collector.path_basis_hash(),
            "path_basis_comparison_hash": collector.path_basis_comparison_hash(),
            "accepted_state_changes_on_epoch": self.path_epoch_accepts,
            "geometry_identity": PROVISIONAL,
            "geometry_used_for": "GENERATION_CANDIDATE_PROPOSAL_ONLY",
            "acceptance_authority": "FRESH_VISUM_ASSIGNMENT_PLUS_LIVE_12D_11D",
        })
        return base.path_guidance_design(
            self.visum, folder, self.cfg, diag["d12"], self.zones,
            self.actuatable_zones, incidence_and_export=incidence_export,
            progress_callback=lambda phase: self.checkpoint("GENERATION_" + str(phase)),
        )

    def path_epoch_plateau_gate(self, diag, folder, snapshot, *, phase):
        """Re-enumerate only after local exhaustion of the current path basis."""
        phase = str(phase).upper()
        if phase not in ("DEMAND", "SUPPLY"):
            raise SupplyContractError("PATH_EPOCH_UNKNOWN_PHASE:" + phase)
        if not self.path_epochs_enabled():
            return {"enabled": False, "stationarity_confirmed": True,
                    "basis_changed": False, "action": "DISABLED"}
        if self.cache is None:
            raise SupplyContractError("PATH_EPOCH_PLATEAU_WITHOUT_INITIAL_ENUMERATION")
        verified = self.path_epoch_plateau_verified
        if (verified and verified.get("phase") == phase and
                verified.get("state_hash") == snapshot.get("state_hash") and
                verified.get("epoch") == self.path_epoch_index):
            return {"enabled": True, "stationarity_confirmed": True,
                    "basis_changed": False, "action": "ALREADY_VERIFIED",
                    **copy.deepcopy(verified)}
        cfg = self._path_epoch_cfg()
        limit_key = ("max_demand_reenumerations" if phase == "DEMAND"
                     else "max_supply_reenumerations")
        limit = int(cfg.get(limit_key, 4 if phase == "DEMAND" else 8))
        if self.path_epoch_refresh_counts[phase] >= limit:
            raise SupplyContractError("PATH_EPOCH_REENUMERATION_BUDGET_EXHAUSTED:" + phase)
        previous_epoch = self.path_epoch_index
        previous_basis = self._epoch_basis()
        previous_comparison_basis = self._epoch_comparison_basis()
        previous_structure = self.cache.path_structure_hash()
        self.path_epoch_refresh_counts[phase] += 1
        folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
        with optional_span(self, "PATH_EPOCH_REENUMERATION", phase=phase,
                           previous_epoch=previous_epoch):
            build_kwargs = {"build_sequence_evidence": (phase == "SUPPLY")}
            if "allow_persistent_restore" in inspect.signature(self._build_cache).parameters:
                build_kwargs["allow_persistent_restore"] = False
            collector, _, _ = self._build_cache(
                diag, folder / ("EPOCH_%03d" % (previous_epoch + 1)), snapshot,
                **build_kwargs)
        current_basis = collector.path_basis_hash()
        current_comparison_basis = collector.path_basis_comparison_hash()
        current_structure = collector.path_structure_hash()
        changed = current_comparison_basis != previous_comparison_basis
        record = {
            "schema": "R1_15A2_PATH_EPOCH_PLATEAU_GATE_V247",
            "enabled": True, "phase": phase,
            "previous_epoch": previous_epoch, "current_epoch": self.path_epoch_index,
            "state_hash": snapshot["state_hash"],
            "previous_basis_hash": previous_basis,
            "current_basis_hash": current_basis,
            "previous_comparison_basis_hash": previous_comparison_basis,
            "current_comparison_basis_hash": current_comparison_basis,
            "previous_structure_hash": previous_structure,
            "current_structure_hash": current_structure,
            "basis_changed": changed,
            "structure_changed": current_structure != previous_structure,
            "stationarity_confirmed": not changed,
            "action": ("NEW_PATH_BASIS_CONTINUE_CALIBRATION" if changed
                       else "FRESH_ENUMERATION_CONFIRMED_LOCAL_PLATEAU"),
            "refresh_count": self.path_epoch_refresh_counts[phase],
            "refresh_limit": limit,
        }
        if changed:
            self.path_epoch_plateau_verified = None
        else:
            self.path_epoch_plateau_verified = {
                "phase": phase, "state_hash": snapshot["state_hash"],
                "epoch": self.path_epoch_index,
                "basis_hash": current_basis,
                "comparison_basis_hash": current_comparison_basis,
                "structure_hash": current_structure,
            }
        atomic_json(folder / "PATH_EPOCH_PLATEAU_GATE.json", record)
        return record

    def close(self):
        self.invalidate_cache("CLOSE", clear_proof=True)
