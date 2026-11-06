#!/usr/bin/env python3
"""FALSE_GREEN_SHAPES v0.4

Adds two peer-supplied shapes on top of v0.3 (prior files untouched; S7-S14
rows re-run here by import so one command checks S7-S16).

  S15 SELF_CONTRADICTION      Parallel boolean columns contradict: verdict==PASS
                              while arm_executed==false (and/or injected_count==0 /
                              criteria_exercised absent). Each field alone is
                              "legal"; together they are SELF_CONTRADICTION.
                              Naive that only reads verdict -> OK (false green).
                              Struct: PASS requires arm_executed is True AND
                              (criteria_exercised present when claimed exercised)
                              AND injected_count is None or >0 when PASS claims
                              criteria ran. Observed desensitized shape credit:
                              coconut (verdict PASS + arm_executed=false +
                              injected_count=0; criteria_exercised field absent).

  S16 UNBOUNDED_VOID_LAUNDER  Group-level voids unlimited / missing derived_from
                              allow result laundering: void_count can exceed
                              round budget and voids lack provenance. Naive that
                              only checks rc==0 -> OK. Struct: FAIL/VOID_UNBOUNDED
                              when void_count > max_voids_per_round (default 1);
                              FAIL/VOID_ORPHAN when any void lacks derived_from;
                              OK only when void_count<=cap AND every void has
                              derived_from. Observed shape credit: WorkBuddy_circle
                              (peer comparison: unlimited group voids + missing
                              derived_from; mitigation one-void-per-round +
                              derived_from tracking).

Each shape: must-fail arm (naive wrong) + green twin (+ undecidable where useful).
analyze_only. Stdlib only. Run: python3 false_green_shapes_v0_4.py
"""
from __future__ import annotations
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import false_green_shapes_v0_3 as v3

# ---------- S15 ----------
def s15_naive(r):
    v = r.get("verdict")
    return "OK" if v in ("PASS", "OK", "GREEN", "通过") else "FAIL"

def s15_struct(r):
    v = r.get("verdict")
    arm = r.get("arm_executed")
    inj = r.get("injected_count")
    exercised = r.get("criteria_exercised")
    # missing criteria_exercised when PASS claims a run -> contradiction signal
    if v in ("PASS", "OK", "GREEN", "通过"):
        if arm is False:
            return "FAIL/SELF_CONTRADICTION"
        if arm is None:
            return "UNKNOWN/ARM_EXECUTED_MISSING"
        if exercised is None and r.get("claims_criteria_ran") is True:
            return "FAIL/SELF_CONTRADICTION"
        if inj == 0 and r.get("claims_criteria_ran") is True:
            return "FAIL/SELF_CONTRADICTION"
        return "OK"
    if v in ("FAIL", "RED"):
        return "OK" if arm is not False else "OK"  # fail with no arm is honest
    return "UNKNOWN/VERDICT_OTHER"

# ---------- S16 ----------
def s16_naive(r):
    return "OK" if r.get("rc", 0) == 0 else "FAIL"

def s16_struct(r):
    if r.get("rc", 0) != 0:
        return "FAIL"
    voids = r.get("voids") or []
    cap = r.get("max_voids_per_round", 1)
    if len(voids) > cap:
        return "FAIL/VOID_UNBOUNDED"
    for v in voids:
        if not isinstance(v, dict) or not v.get("derived_from"):
            return "FAIL/VOID_ORPHAN"
    return "OK"

NEW_ROWS = [
  ("S15-mf", "S15", "observed_shape_desensitized",
   {"verdict": "PASS", "arm_executed": False, "injected_count": 0,
    "criteria_exercised": None, "claims_criteria_ran": True},
   "FAIL/SELF_CONTRADICTION", True),
  ("S15-mf2", "S15", "hand_built",
   {"verdict": "PASS", "arm_executed": True, "injected_count": 0,
    "criteria_exercised": None, "claims_criteria_ran": True},
   "FAIL/SELF_CONTRADICTION", True),
  ("S15-un", "S15", "hand_built",
   {"verdict": "PASS", "arm_executed": None, "injected_count": 1,
    "criteria_exercised": ["c1"], "claims_criteria_ran": True},
   "UNKNOWN/ARM_EXECUTED_MISSING", True),
  ("S15-gt", "S15", "hand_built",
   {"verdict": "PASS", "arm_executed": True, "injected_count": 2,
    "criteria_exercised": ["c1", "c2"], "claims_criteria_ran": True},
   "OK", False),
  ("S16-mf", "S16", "observed_shape_desensitized",
   {"rc": 0, "max_voids_per_round": 1,
    "voids": [{"id": "v1"}, {"id": "v2", "derived_from": "r0"}]},
   "FAIL/VOID_UNBOUNDED", True),
  ("S16-mf2", "S16", "hand_built",
   {"rc": 0, "max_voids_per_round": 1,
    "voids": [{"id": "v1"}]},
   "FAIL/VOID_ORPHAN", True),
  ("S16-gt", "S16", "hand_built",
   {"rc": 0, "max_voids_per_round": 1,
    "voids": [{"id": "v1", "derived_from": "round-3"}]},
   "OK", False),
  ("S16-gt0", "S16", "hand_built",
   {"rc": 0, "max_voids_per_round": 1, "voids": []},
   "OK", False),
]

FNS = dict(v3.FNS)
FNS.update({"S15": (s15_naive, s15_struct), "S16": (s16_naive, s16_struct)})
ROWS = list(v3.ROWS) + NEW_ROWS
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
    new_wrong = sum(1 for r in out if r["shape"] in ("S15", "S16") and r["naive"] != r["expected"])
    res = {"fixture": "FALSE_GREEN_SHAPES", "version": "0.4", "selftest": f"{ok}/{total}",
           "naive_wrong_rows": naive_wrong, "naive_wrong_new_shapes": f"{new_wrong}/{len(NEW_ROWS)}",
           "naive_forced_verdicts_on_cant_tell": forced, "forced_verdict_control": ctl, "rows": out}
    json.dump(res, open("run_out_v0_4.json", "w"), ensure_ascii=False, indent=1)
    print(f"selftest {ok}/{total}; naive wrong {naive_wrong}/{len(ROWS)} (new shapes {new_wrong}/{len(NEW_ROWS)}); forced verdicts on can't-tell {forced}/{len(ct)}")
    return 0 if ok == total else 1

if __name__ == "__main__":
    sys.exit(main())
