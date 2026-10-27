"""Runtime manifest verifier for the staged V24916/PERF2C overlay."""
from __future__ import annotations
from pathlib import Path
from typing import Any, Mapping
import hashlib, json

MANIFEST_NAME = "V24916_PERF2C_RUNTIME_MANIFEST.json"


def sha256_file(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):
            h.update(chunk)
    return h.hexdigest()


def verify_runtime_manifest(root: Path | str) -> dict[str, Any]:
    root=Path(root)
    manifest=json.loads((root/MANIFEST_NAME).read_text(encoding='utf-8'))
    rows=[]
    for rel, expected in manifest['required_files'].items():
        p=root/rel
        actual=sha256_file(p) if p.is_file() else None
        rows.append({'path':rel,'exists':p.is_file(),'expected':expected,'actual':actual,'passes':actual==expected})
    passes=all(r['passes'] for r in rows)
    return {'schema':'R1_15A2_V24916_PERF2C_RUNTIME_MANIFEST_CHECK_V1','passes':passes,'rows':rows,'release':manifest['release']}
