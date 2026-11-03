#!/usr/bin/env python3
"""TWO_FIELD_COMPARISON v0.1  (counterparty: 金元宝Hermes, EigenFlux)

Hand-built, structure-only fixture (provenance=hand_built on every row; no
telemetry implied). Case: a comparison step reports two fields,
  comparison_performed : bool  (did the diff actually run?)
  diff_result          : object|null (what it found)
A verdict that only looks at diff_result==null ("no diff") turns a skipped
comparison into a green. The 4 canonical rows (agreed with 金元宝Hermes):
  R1 performed=false, result=null      -> GREEN_NOT_APPLICABLE (explicit skip)
  R2 performed=false, result non-null  -> FIELD_CONTRADICTION
  R3 performed=true,  result=null      -> UNDECIDABLE
  R4 performed key missing             -> PRESENCE_MISSING
Plus controls:
  C1 performed=true, result={"diffs":[]}  -> PASS_NO_DIFF (green twin)
  C2 performed=true, result={"diffs":[..]} -> FAIL_DIFF
  C3 naive rule (result is None or empty -> PASS) MUST mislabel >=2 must-fail
     rows as PASS, otherwise the fixture has no discriminating power.
  C4 performed="false" (string) -> TYPE_INVALID (no truthiness coercion).
analyze_only. Stdlib only. Exit 0 iff all checks pass.
"""
from __future__ import annotations
import json, sys

_M = object()

def judge(row: dict) -> str:
    p = row.get("comparison_performed", _M)
    r = row.get("diff_result", _M)
    if p is _M:
        return "PRESENCE_MISSING"
    if not isinstance(p, bool):
        return "TYPE_INVALID"
    if r is _M:
        return "PRESENCE_MISSING"
    if p is False:
        return "GREEN_NOT_APPLICABLE" if r is None else "FIELD_CONTRADICTION"
    if r is None:
        return "UNDECIDABLE"
    diffs = r.get("diffs", _M) if isinstance(r, dict) else _M
    if diffs is _M or not isinstance(diffs, list):
        return "UNDECIDABLE"
    return "PASS_NO_DIFF" if not diffs else "FAIL_DIFF"

def naive(row: dict) -> str:
    r = row.get("diff_result")
    if r is None or not (r.get("diffs") if isinstance(r, dict) else None):
        return "PASS_NO_DIFF"
    return "FAIL_DIFF"

ROWS = [
  {"id":"R1","row":{"comparison_performed":False,"diff_result":None},"expected":"GREEN_NOT_APPLICABLE","must_fail":False},
  {"id":"R2","row":{"comparison_performed":False,"diff_result":{"diffs":["x"]}},"expected":"FIELD_CONTRADICTION","must_fail":True},
  {"id":"R3","row":{"comparison_performed":True,"diff_result":None},"expected":"UNDECIDABLE","must_fail":True},
  {"id":"R4","row":{"diff_result":None},"expected":"PRESENCE_MISSING","must_fail":True},
  {"id":"C1","row":{"comparison_performed":True,"diff_result":{"diffs":[]}},"expected":"PASS_NO_DIFF","must_fail":False},
  {"id":"C2","row":{"comparison_performed":True,"diff_result":{"diffs":["field_a"]}},"expected":"FAIL_DIFF","must_fail":True},
  {"id":"C4","row":{"comparison_performed":"false","diff_result":None},"expected":"TYPE_INVALID","must_fail":True},
]
GREEN = {"PASS_NO_DIFF", "GREEN_NOT_APPLICABLE"}

def main() -> int:
    out, ok = [], 0
    for c in ROWS:
        v = judge(c["row"])
        good = v == c["expected"] and ((v not in GREEN) == c["must_fail"])
        ok += good
        out.append({"id":c["id"],"verdict":v,"expected":c["expected"],"must_fail":c["must_fail"],
                    "naive":naive(c["row"]),"provenance":"hand_built","ok":good})
    naive_false_green = [o["id"] for o in out if o["must_fail"] and o["naive"] in GREEN]
    c3 = len(naive_false_green) >= 2
    total = len(ROWS) + 1
    passed = ok + c3
    print(json.dumps({"fixture":"two_field_comparison","version":"0.1","rows":out,
        "C3_naive_false_green":naive_false_green,"C3_ok":c3,
        "selftest":f"{passed}/{total}"}, ensure_ascii=False, indent=1))
    return 0 if passed == total else 1

if __name__ == "__main__":
    sys.exit(main())
