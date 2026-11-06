#!/usr/bin/env python3
"""FALSE_GREEN_SHAPES v0.11

Adds one peer-supplied shape on top of v0.10 (prior files untouched; S7-S22
rows re-run here by import so one command checks S7-S23).

  S23 VACUOUS_EMPTY_AGGREGATE  Aggregate defaults on empty sets must not
                              read as healthy. Struct:
                                - missing cardinality (n) beside aggregate
                                  -> FAIL/CARDINALITY_UNAUDITED
                                - n==0 with aggregate defaulting to a
                                  "good" value (0 for age/errors/unattributed)
                                  -> FAIL/VACUOUS_HEALTHY
                                - n==0 must not pass threshold gates written
                                  as `age < T` / `errors == 0`
                                - green twin: n>0 and aggregate measured
                              Credit: H (空集聚合默认值伪装成最健康的数;
                              三态 measured/vacuous/unavailable).

Each shape: must-fail arm (naive wrong) + green twin.
analyze_only. Stdlib only. Run: python3 false_green_shapes_v0_11.py
"""
from __future__ import annotations
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import false_green_shapes_v0_10 as v10


def s23_naive(r):
    # Naive: age_ms==0 and errors==0 and unattributed==0 -> OK ("队列清空")
    if r.get("age_ms", 1) == 0 and r.get("errors", 1) == 0 and r.get("unattributed", 1) == 0:
        return "OK"
    return "FAIL"


def s23_struct(r):
    if "n" not in r or r["n"] is None:
        return "FAIL/CARDINALITY_UNAUDITED"
    n = r["n"]
    if not isinstance(n, (int, float)) or n < 0:
        return "FAIL/CARDINALITY_UNAUDITED"
    if n == 0:
        return "FAIL/VACUOUS_HEALTHY"
    # n > 0: measured
    return "OK"


NEW_ROWS = [
  # Observed triad: empty queue looks perfectly healthy
  ("S23-mf-obs", "S23", "observed_shape_desensitized(H)",
   {"age_ms": 0, "errors": 0, "unattributed": 0, "n": 0,
    "threshold_pass_naive": True},
   "FAIL/VACUOUS_HEALTHY", True),
  # Missing cardinality — cannot judge
  ("S23-mf-unaudited", "S23", "hand_built",
   {"age_ms": 0, "errors": 0, "unattributed": 0},
   "FAIL/CARDINALITY_UNAUDITED", True),
  # Threshold gate would pass on vacuous 0
  ("S23-mf-threshold", "S23", "hand_built",
   {"age_ms": 0, "errors": 0, "unattributed": 0, "n": 0,
    "gate": "age_ms < 100"},
   "FAIL/VACUOUS_HEALTHY", True),
  # Green twin: measured empty-of-errors with cardinality
  ("S23-gt", "S23", "hand_built",
   {"age_ms": 0, "errors": 0, "unattributed": 0, "n": 12},
   "OK", False),
]

FNS = dict(v10.FNS)
FNS.update({"S23": (s23_naive, s23_struct)})
ROWS = list(v10.ROWS) + NEW_ROWS
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
    new_wrong = sum(1 for r in out if r["shape"] == "S23" and r["naive"] != r["expected"])
    res = {"fixture": "FALSE_GREEN_SHAPES", "version": "0.11", "selftest": f"{ok}/{total}",
           "naive_wrong_rows": naive_wrong, "naive_wrong_new_shapes": f"{new_wrong}/{len(NEW_ROWS)}",
           "naive_forced_verdicts_on_cant_tell": forced, "forced_verdict_control": ctl, "rows": out}
    json.dump(res, open("run_out_v0_11.json", "w"), ensure_ascii=False, indent=1)
    print(f"selftest {ok}/{total}; naive wrong {naive_wrong}/{len(ROWS)} (new shapes {new_wrong}/{len(NEW_ROWS)}); forced verdicts on can't-tell {forced}/{len(ct)}")
    for r in out:
        if not r["pass"]:
            print("FAIL_ROW", r)
    return 0 if ok == total else 1

if __name__ == "__main__":
    sys.exit(main())
