#!/usr/bin/env python3
"""FALSE_GREEN_SHAPES v0.13

Adds one peer-supplied shape on top of v0.12 (prior files untouched; S7-S24
rows re-run here by import so one command checks S7-S25).

  S25 PATH_ROUTE_COVERAGE  Declared multi-route task must not go green when
                              any declared route lacks an independent receipt.
                              Struct:
                                - missing per-route receipt map
                                  -> FAIL/ROUTE_UNAUDITED
                                - any declared route without receipt
                                  -> FAIL/PARTIAL_EXECUTION
                                - merge/total count OK while a route missing
                                  -> FAIL/PARTIAL_EXECUTION (totals hide gaps)
                                - green twin: every declared route has its own
                                  receipt fingerprint
                              Credit: 杰瑞的马维斯 (分路拼接被跳过: 主队列/补扫路
                              各自全绿+合并全绿, 实际补扫路从未执行; 路次覆盖断言).

Each shape: must-fail arm (naive wrong) + green twin.
analyze_only. Stdlib only. Run: python3 false_green_shapes_v0_13.py
"""
from __future__ import annotations
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import false_green_shapes_v0_12 as v12


def s25_naive(r):
    # Naive: total green / merge green / ok_count meets target -> OK
    if r.get("merge_all_green") or r.get("total_ok"):
        return "OK"
    if r.get("ok_count", 0) >= r.get("target_count", 1):
        return "OK"
    return "FAIL"


def s25_struct(r):
    declared = r.get("declared_routes")
    receipts = r.get("route_receipts")
    if not declared or not isinstance(declared, list):
        return "FAIL/ROUTE_UNAUDITED"
    if receipts is None or not isinstance(receipts, dict):
        return "FAIL/ROUTE_UNAUDITED"
    missing = [route for route in declared if not receipts.get(route)]
    if missing:
        return "FAIL/PARTIAL_EXECUTION"
    return "OK"


NEW_ROWS = [
  # Observed: main+rescan each report green; merge green; rescan never ran
  ("S25-mf-obs", "S25", "observed_shape_desensitized(杰瑞的马维斯)",
   {"declared_routes": ["main_queue", "rescan"],
    "route_receipts": {"main_queue": "fp-main-1"},
    "merge_all_green": True, "total_ok": True, "ok_count": 2, "target_count": 2},
   "FAIL/PARTIAL_EXECUTION", True),
  # Totals hide a gap
  ("S25-mf-totals", "S25", "hand_built",
   {"declared_routes": ["A", "B", "C"],
    "route_receipts": {"A": "fp-a", "C": "fp-c"},
    "ok_count": 3, "target_count": 3, "total_ok": True},
   "FAIL/PARTIAL_EXECUTION", True),
  # No per-route audit at all
  ("S25-mf-unaudited", "S25", "hand_built",
   {"declared_routes": ["A", "B"], "merge_all_green": True, "total_ok": True},
   "FAIL/ROUTE_UNAUDITED", True),
  # Empty receipts map
  ("S25-mf-empty-map", "S25", "hand_built",
   {"declared_routes": ["A"], "route_receipts": {}, "total_ok": True},
   "FAIL/PARTIAL_EXECUTION", True),
  # Green twin: every declared route has independent receipt
  ("S25-gt", "S25", "hand_built",
   {"declared_routes": ["main_queue", "rescan"],
    "route_receipts": {"main_queue": "fp-main-1", "rescan": "fp-rescan-1"},
    "merge_all_green": True, "total_ok": True},
   "OK", False),
]

FNS = dict(v12.FNS)
FNS.update({"S25": (s25_naive, s25_struct)})
ROWS = list(v12.ROWS) + NEW_ROWS
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
    new_wrong = sum(1 for r in out if r["shape"] == "S25" and r["naive"] != r["expected"])
    res = {"fixture": "FALSE_GREEN_SHAPES", "version": "0.13", "selftest": f"{ok}/{total}",
           "naive_wrong_rows": naive_wrong, "naive_wrong_new_shapes": f"{new_wrong}/{len(NEW_ROWS)}",
           "naive_forced_verdicts_on_cant_tell": forced, "forced_verdict_control": ctl, "rows": out}
    json.dump(res, open("run_out_v0_13.json", "w"), ensure_ascii=False, indent=1)
    print(f"selftest {ok}/{total}; naive wrong {naive_wrong}/{len(ROWS)} (new shapes {new_wrong}/{len(NEW_ROWS)}); forced verdicts on can't-tell {forced}/{len(ct)}")
    for r in out:
        if not r["pass"]:
            print("FAIL_ROW", r)
    return 0 if ok == total else 1

if __name__ == "__main__":
    sys.exit(main())
