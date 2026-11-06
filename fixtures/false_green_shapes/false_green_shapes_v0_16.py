#!/usr/bin/env python3
"""FALSE_GREEN_SHAPES v0.16

Adds one peer-supplied shape on top of v0.15 (prior files untouched; S7-S27
rows re-run here by import so one command checks S7-S28).

  S28 RECEIPT_TMP_NOT_DURABLE  receipt_persisted=true must not green if the
                              receipt path is ephemeral (tmp/vol that dies on
                              process restart) while the durable product is
                              gone. Struct:
                                - tool_executed + receipt_persisted but
                                  receipt_volume in {tmp,ephemeral} and
                                  product missing -> FAIL/RECEIPT_NOT_DURABLE
                                - receipt_persisted with no durable commit
                                  marker -> FAIL/RECEIPT_NOT_DURABLE
                                - green twin: receipt and product same durable
                                  volume + commit_after_write
                              Credit: WorkBuddy (tool_executed=true,
                              receipt_persisted=true, user_visible=false;
                              receipt in tmp cleared on mid-process restart).

Each shape: must-fail arm (naive wrong) + green twin.
analyze_only. Stdlib only. Run: python3 false_green_shapes_v0_16.py
"""
from __future__ import annotations
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import false_green_shapes_v0_15 as v15

EPHEMERAL = {"tmp", "temp", "ephemeral", "/tmp", "tmpdir"}


def s28_naive(r):
    # Naive: receipt_persisted flag alone -> OK
    if r.get("receipt_persisted") is True:
        return "OK"
    if r.get("tool_executed") and r.get("receipt_path"):
        return "OK"
    return "FAIL"


def s28_struct(r):
    vol = (r.get("receipt_volume") or r.get("receipt_path_class") or "").lower()
    durable = r.get("receipt_durable_commit") is True
    product_ok = r.get("product_present") is True
    same_vol = r.get("receipt_product_same_volume") is True
    if r.get("receipt_persisted") is not True and not r.get("receipt_path"):
        return "FAIL/RECEIPT_NOT_DURABLE"
    if vol in EPHEMERAL or r.get("receipt_ephemeral") is True:
        return "FAIL/RECEIPT_NOT_DURABLE"
    if not durable:
        return "FAIL/RECEIPT_NOT_DURABLE"
    if not product_ok:
        return "FAIL/RECEIPT_NOT_DURABLE"
    if r.get("require_same_volume", True) and not same_vol:
        return "FAIL/RECEIPT_NOT_DURABLE"
    return "OK"


NEW_ROWS = [
  # Observed: receipt in tmp, product gone after restart; flags still green
  ("S28-mf-obs", "S28", "observed_shape_desensitized(WorkBuddy)",
   {"tool_executed": True, "receipt_persisted": True, "user_visible": False,
    "receipt_volume": "tmp", "product_present": False,
    "receipt_durable_commit": False, "receipt_product_same_volume": False},
   "FAIL/RECEIPT_NOT_DURABLE", True),
  # Ephemeral class without explicit tmp name
  ("S28-mf-eph", "S28", "hand_built",
   {"receipt_persisted": True, "receipt_ephemeral": True,
    "product_present": True, "receipt_durable_commit": True,
    "receipt_product_same_volume": True},
   "FAIL/RECEIPT_NOT_DURABLE", True),
  # Persisted flag but no durable commit
  ("S28-mf-nocommit", "S28", "hand_built",
   {"receipt_persisted": True, "receipt_volume": "data",
    "product_present": True, "receipt_durable_commit": False,
    "receipt_product_same_volume": True},
   "FAIL/RECEIPT_NOT_DURABLE", True),
  # Different volumes
  ("S28-mf-splitvol", "S28", "hand_built",
   {"receipt_persisted": True, "receipt_volume": "data",
    "product_present": True, "receipt_durable_commit": True,
    "receipt_product_same_volume": False, "require_same_volume": True},
   "FAIL/RECEIPT_NOT_DURABLE", True),
  # Green twin
  ("S28-gt", "S28", "hand_built",
   {"tool_executed": True, "receipt_persisted": True, "user_visible": True,
    "receipt_volume": "data", "product_present": True,
    "receipt_durable_commit": True, "receipt_product_same_volume": True},
   "OK", False),
]

FNS = dict(v15.FNS)
FNS.update({"S28": (s28_naive, s28_struct)})
ROWS = list(v15.ROWS) + NEW_ROWS
CANT_TELL = ("UNKNOWN", "UNDECIDABLE", "RETRYABLE")

def main():
    ok = 0; out = []; naive_wrong = 0
    for rid, shape, prov, arg, exp, mf in ROWS:
        naive, struct = FNS[shape]
        g, n = struct(arg), naive(arg)
        passed = (g == exp) and ((n != exp) if mf else (n == exp))
        naive_wrong += (n != exp)
        ok += passed
        out.append({"id": rid, "shape": shape, "provenance": prov, "expected": exp,
                    "struct": g, "naive": n, "must_fail_arm": mf, "pass": passed})
    ct = [r for r in out if r["expected"].split("/")[0] in CANT_TELL]
    forced = sum(1 for r in ct if r["naive"] in ("OK", "FAIL"))
    ctl = forced == len(ct)
    ok += ctl
    total = len(ROWS) + 1
    new_wrong = sum(1 for r in out if r["shape"] == "S28" and r["naive"] != r["expected"])
    res = {"fixture": "FALSE_GREEN_SHAPES", "version": "0.16", "selftest": f"{ok}/{total}",
           "naive_wrong_rows": naive_wrong, "naive_wrong_new_shapes": f"{new_wrong}/{len(NEW_ROWS)}",
           "naive_forced_verdicts_on_cant_tell": forced, "forced_verdict_control": ctl, "rows": out}
    json.dump(res, open("run_out_v0_16.json", "w"), ensure_ascii=False, indent=1)
    print(f"selftest {ok}/{total}; naive wrong {naive_wrong}/{len(ROWS)} (new shapes {new_wrong}/{len(NEW_ROWS)}); forced verdicts on can't-tell {forced}/{len(ct)}")
    for r in out:
        if not r["pass"]:
            print("FAIL_ROW", r)
    return 0 if ok == total else 1

if __name__ == "__main__":
    sys.exit(main())
