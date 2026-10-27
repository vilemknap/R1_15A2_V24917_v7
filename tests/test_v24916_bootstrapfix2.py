from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_launcher(root: Path):
    path = root / "00_0_SPUSTIT_V24916_FRESH0_ISOLATED_ACTIVE_TARGETING.py"
    spec = importlib.util.spec_from_file_location("v24916_bootstrapfix2_launcher_test", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_layout_resolver_does_not_recurse_after_parent_runtime_patch(tmp_path: Path):
    """Regression for the live PARENT_MAIN_FULL recursion seen in Visum.

    _install_runtime replaces parent._stable_project_layout with the isolated
    resolver.  The isolated resolver must still delegate to the frozen original
    parent implementation rather than dereference the now-patched attribute.
    """
    root = Path(__file__).resolve().parents[1]
    launcher = _load_launcher(root)
    source = tmp_path / "ACCEPTED_A_0013.ver"
    source.write_bytes(b"x")

    original_dynamic_attr = launcher.parent._stable_project_layout
    try:
        launcher.parent._stable_project_layout = launcher._isolated_project_layout
        layout = launcher._isolated_project_layout(source)
    finally:
        launcher.parent._stable_project_layout = original_dynamic_attr

    assert Path(layout["project_base"]) == tmp_path
    assert Path(layout["parallel_isolation_workspace"]) == tmp_path / launcher.RUNS_ROOT_NAME
    assert layout["original_project_base_mode"] == "SOURCE_PARENT"


def test_base_layout_is_bound_to_frozen_parent_resolver():
    root = Path(__file__).resolve().parents[1]
    launcher = _load_launcher(root)
    assert launcher._ORIGINAL_PARENT_STABLE_PROJECT_LAYOUT is not launcher._isolated_project_layout
    assert launcher._base_layout.__doc__
    text = (root / "00_0_SPUSTIT_V24916_FRESH0_ISOLATED_ACTIVE_TARGETING.py").read_text(encoding="utf-8")
    assert "return _ORIGINAL_PARENT_STABLE_PROJECT_LAYOUT(source_ver)" in text
