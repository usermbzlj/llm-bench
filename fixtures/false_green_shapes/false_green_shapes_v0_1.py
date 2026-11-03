#!/usr/bin/env python3
"""FALSE_GREEN_SHAPES v0.1

Hand-built, structure-only fixture (provenance=hand_built; no telemetry implied).
Shape credit: WorkBuddy-月光羽 (EigenFlux) -- three false-green / false-red shapes
taken from their own run ledger:

  S1 TEXT_MATCH_VERDICT   success decided by grepping output for "failed".
                          A successful payload that merely CONTAINS the word is
                          discarded and re-polled (false red -> duplicate side effect).
                          Structured criterion: rc==0 AND parseable JSON AND
                          expected id present.
  S2 COUNT_EQ_HIDES_IDSET 5 vs 5 passes while the id sets are disjoint.
                          Criterion: set equality on ids, never count equality.
  S3 RETRY_UNDERCOUNT     failed_then_retry = n_attempts - 1 silently assumes
                          the last attempt succeeded; when all attempts fail the
                          error count is undercounted by one.
                          Criterion: failures = attempts - (1 if final_ok else 0).

Each shape has a must-fail arm (naive rule gives the wrong verdict) and a green
twin (both rules agree), so the fixture proves the naive rule is wrong, not just
different. analyze_only. Stdlib only. Run: python3 false_green_shapes_v0_1.py
"""
from __future__ import annotations
import json, sys

# ---------- S1: verdict from text vs structure ----------
def s1_naive(rc, out, expect_id):
    return "FAIL" if "failed" in out.lower() else ("OK" if rc == 0 else "FAIL")

def s1_struct(rc, out, expect_id):
    if rc != 0:
        return "FAIL"
    try:
        obj = json.loads(out)
    except Exception:
        return "UNDECIDABLE"
    ids = {str(x.get("id")) for x in obj.get("items", [])} if isinstance(obj, dict) else set()
    return "OK" if expect_id in ids else "FAIL"

# ---------- S2: count vs id-set ----------
def s2_naive(recorded, target):
    return "OK" if len(recorded) == len(target) else "FAIL"

def s2_struct(recorded, target):
    return "OK" if set(recorded) == set(target) else "FAIL"

# ---------- S3: retry accounting ----------
def s3_naive(attempts, final_ok):
    return attempts - 1                      # assumes last attempt succeeded

def s3_struct(attempts, final_ok):
    return attempts - (0 if not final_ok else 1)

ROWS = [
  # id, shape, args, expected_struct, naive_wrong(bool) -> must-fail arm when True
  ("S1-mf", "S1", (0, json.dumps({"items": [{"id": "42", "title": "why retries failed silently"}]}), "42"), "OK", True),
  ("S1-gt", "S1", (0, json.dumps({"items": [{"id": "42", "title": "relay notes"}]}), "42"), "OK", False),
  ("S1-rc", "S1", (2, "error: request failed", "42"), "FAIL", False),
  ("S1-un", "S1", (0, "not json at all", "42"), "UNDECIDABLE", True),
  ("S2-mf", "S2", (["a1","a2","a3","a4","a5"], ["b1","b2","b3","b4","b5"]), "FAIL", True),
  ("S2-gt", "S2", (["a1","a2","a3","a4","a5"], ["a5","a4","a3","a2","a1"]), "OK", False),
  ("S2-sz", "S2", (["a1","a2","a3","a4","a5"], ["a1","a2","a3","a4","a5","a6"]), "FAIL", False),
  ("S3-mf", "S3", (3, False), 3, True),
  ("S3-gt", "S3", (3, True), 2, False),
  ("S3-one", "S3", (1, True), 0, False),
]

def main():
    fns = {"S1": (s1_naive, s1_struct), "S2": (s2_naive, s2_struct), "S3": (s3_naive, s3_struct)}
    ok = 0; out = []; naive_wrong = 0
    for rid, shape, args, exp, mf in ROWS:
        naive, struct = fns[shape]
        g, n = struct(*args), naive(*args)
        # must-fail arm passes only when struct is right AND naive is provably wrong
        passed = (g == exp) and ((n != exp) if mf else (n == exp))
        naive_wrong += (n != exp)
        ok += passed
        out.append({"id": rid, "shape": shape, "provenance": "hand_built", "expected": exp,
                    "struct": g, "naive": n, "must_fail_arm": mf, "pass": passed})
    # S3 aggregate control: 16 calls, 3 all-fail -> naive under-counts by exactly 3
    batch = [(1, True)] * 10 + [(2, True)] * 3 + [(3, False)] * 3
    agg_ok = sum(s3_struct(*b) for b in batch) - sum(s3_naive(*b) for b in batch) == 3
    ok += agg_ok
    total = len(ROWS) + 1
    res = {"fixture": "FALSE_GREEN_SHAPES", "version": "0.1", "selftest": f"{ok}/{total}",
           "naive_wrong_rows": naive_wrong, "s3_aggregate_undercount_control": agg_ok, "rows": out}
    json.dump(res, open("run_out_v0_1.json", "w"), ensure_ascii=False, indent=1)
    print(f"selftest {ok}/{total}; naive rules wrong on {naive_wrong} rows")
    return 0 if ok == total else 1

if __name__ == "__main__":
    sys.exit(main())
