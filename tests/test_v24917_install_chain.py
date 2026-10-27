# -*- coding: utf-8 -*-
"""install_all in a clean interpreter: every V24917 layer installed in the live order."""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SCRIPT = r'''
import json, sys
sys.path.insert(0, %r)
import r1_15a2_overnight_controller_coupled_v24915p2_force100 as ctrl
import r1_15a2_active_controller_patch_v24916p2c as acp
acp.install(ctrl)
import r1_15a2_runtime_v1 as rt
import r1_15a2_v24917_runtime as r17
st = r17.install_all(ctrl, rt, print_fn=lambda *a: None)
f = ctrl._generation_update_once_impl
chain = []
while f is not None and len(chain) < 10:
    chain.append(sorted(k for k in vars(f) if k.startswith("__r1_")))
    f = getattr(f, "__wrapped__", None)
g = ctrl._generation_update_once
gchain = []
while g is not None and len(gchain) < 10:
    gchain.append(sorted(k for k in vars(g) if k.startswith("__r1_")))
    g = getattr(g, "__wrapped__", None)
import r1_15a2_acceleration_v24915p1 as perf1
import r1_15a2_overnight_controller_v24915p2 as base
import inspect
pub = r17.public_status(st)
json.dumps(pub, default=str)
print(json.dumps({"keys": sorted(pub), "chain": chain, "gchain": gchain,
                  "plan_sm": bool(getattr(perf1.phase_recompute_plan, "__r1_supplymix__", False)),
                  "sm": pub["supplymix"]["installed"],
                  "step": pub["step_search"]["installed"], "perf3": pub["perf3"]["installed"],
                  "fa": pub["fast_trial_assignment"]["installed"],
                  "rb": bool(getattr(base.rollback_and_verify, "__r1_rbcons1__", False)),
                  "rb_kw": "baseline_diag" in inspect.signature(base.rollback_and_verify).parameters,
                  "sig": bool(getattr(perf1.count_profile_signature, "__r1_rbcons1__", False)),
                  "rbc": pub["rollback_consistency"]["installed"]}))
''' % str(ROOT)


def test_install_all_chain_in_clean_process():
    env = dict(os.environ, R1_DIAGFAST_DISABLE="1")
    out = subprocess.run([sys.executable, "-c", SCRIPT], cwd=str(ROOT), env=env,
                         capture_output=True, text=True, timeout=300)
    assert out.returncode == 0, out.stderr[-3000:]
    rep = json.loads(out.stdout.strip().splitlines()[-1])
    assert rep["step"] and rep["perf3"] and rep["fa"]
    # RBCONS1: rollback verifier and reuse-proof signature wrapped; baseline_diag still forwarded
    assert rep["rb"] and rep["rb_kw"] and rep["sig"] and rep["rbc"]
    flat = [set(x) for x in rep["chain"]]
    # functools.wraps copies markers outward: a layer's own depth is the LAST level carrying its marker.
    # outermost timing/block writer -> STEP1 switch -> FASTASSIGN cold-retry -> original impl
    i_perf = max(i for i, s in enumerate(flat) if "__r1_perf3_block__" in s)
    i_step = max(i for i, s in enumerate(flat) if "__r1_step1__" in s)
    i_fa = max(i for i, s in enumerate(flat) if "__r1_fastassign__" in s)
    assert i_perf < i_step < i_fa
    # SUPPLYMIX1 is the outermost Generation wrapper (outside the demand policy) and patches the plan
    assert rep["sm"] and rep["plan_sm"]
    g = [set(x) for x in rep["gchain"]]
    i_sm = max(i for i, s in enumerate(g) if "__r1_supplymix__" in s)
    i_dp = max(i for i, s in enumerate(g) if "__r1_demand_policy__" in s)
    assert i_sm < i_dp
