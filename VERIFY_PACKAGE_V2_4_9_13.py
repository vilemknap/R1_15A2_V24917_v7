# -*- coding: utf-8 -*-
"""Independent verifier for R1 15A2 V2.4.9.13."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    manifest_path = ROOT / 'MANIFEST_V24913.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    failures = []
    for row in manifest['files']:
        path = ROOT / row['path']
        if not path.is_file():
            failures.append({'path': row['path'], 'reason': 'MISSING'})
            continue
        if path.stat().st_size != row['size']:
            failures.append({'path': row['path'], 'reason': 'SIZE_MISMATCH'})
            continue
        if sha(path) != row['sha256']:
            failures.append({'path': row['path'], 'reason': 'SHA256_MISMATCH'})
    launcher = ROOT / 'R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_13.py'
    spec = importlib.util.spec_from_file_location('v24913_package_launcher', launcher)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    cfg = module.load_config()
    from r1_15a2_safety_v24913 import validate_v24913_config, validate_v24913_runtime_bundle
    config_report = validate_v24913_config(cfg, ROOT)
    runtime_report = validate_v24913_runtime_bundle(cfg, ROOT)
    report = {
        'schema': 'R1_15A2_V24913_INDEPENDENT_PACKAGE_VERIFIER_V1',
        'passes': not failures and config_report.get('passes') is True and runtime_report.get('passes') is True,
        'manifest_files': len(manifest['files']),
        'manifest_failures': failures,
        'config_validation': config_report,
        'runtime_validation': runtime_report,
        'real_visum_supply_tested': False,
        'production_ready': False,
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if not report['passes']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
