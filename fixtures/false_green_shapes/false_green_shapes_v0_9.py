#!/usr/bin/env python3
"""FALSE_GREEN_SHAPES v0.9

Adds one peer-supplied shape on top of v0.8 (prior files untouched; S7-S20
rows re-run here by import so one command checks S7-S21).

  S21 TOOL_DONE_PRE_RECEIPT  Interrupt after tool completion but before
                              receipt persistence. Struct:
                                - tool_executed True alone never green
                                - missing receipt_persisted -> FAIL/EXEC_WITHOUT_RECEIPT
                                - receipt_persisted True but user_visible False
                                  -> FAIL/RECEIPT_WITHOUT_DELIVERY
                                - missing idempotency_key when recovery needed
                                  -> FAIL/IDEMPOTENCY_UNAIDED
                                - green twin: tool+receipt+user_visible+key
                              Credit: 凯瑞's Agent (negctl: 执行后/写回执前中断;
                              工具已执行≠用户已收到).

Each shape: must-fail arm (naive wrong) + green twin.
analyze_only. Stdlib only. Run: python3 false_green_shapes_v0_9.py
"""
from __future__ import annotations
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import false_green_shapes_v0_8 as v8


def s21_naive(r):
    # Naive: tool_executed + exit0 -> OK (collapses delivery)
    if r.get("tool_executed", False) and r.get("exit_code", 0) == 0:
        return "OK"
    return "FAIL"


def s21_struct(r):
    if not r.get("tool_executed", False):
        return "FAIL"
    if not r.get("receipt_persisted", False):
        return "FAIL/EXEC_WITHOUT_RECEIPT"
    if not r.get("user_visible", False):
        return "FAIL/RECEIPT_WITHOUT_DELIVERY"
    key = r.get("idempotency_key")
    if key is None or key == "":
        return "FAIL/IDEMPOTENCY_UNAIDED"
    return "OK"


NEW_ROWS = [
  # Observed shape: tool done, no receipt yet (negctl interrupt)
  ("S21-mf-obs", "S21", "observed_shape_desensitized(凯瑞)",
   {"exit_code": 0, "tool_executed": True, "receipt_persisted": False,
    "user_visible": False, "idempotency_key": "k-1"},
   "FAIL/EXEC_WITHOUT_RECEIPT", True),
  # Receipt written but not user-visible
  ("S21-mf-nodeliver", "S21", "hand_built",
   {"exit_code": 0, "tool_executed": True, "receipt_persisted": True,
    "user_visible": False, "idempotency_key": "k-1"},
   "FAIL/RECEIPT_WITHOUT_DELIVERY", True),
  # Missing idempotency key blocks safe recovery
  ("S21-mf-nokey", "S21", "hand_built",
   {"exit_code": 0, "tool_executed": True, "receipt_persisted": True,
    "user_visible": True, "idempotency_key": None},
   "FAIL/IDEMPOTENCY_UNAIDED", True),
  # Green twin
  ("S21-gt", "S21", "hand_built",
   {"exit_code": 0, "tool_executed": True, "receipt_persisted": True,
    "user_visible": True, "idempotency_key": "k-1"},
   "OK", False),
]

FNS = dict(v8.FNS)
FNS.update({"S21": (s21_naive, s21_struct)})
ROWS = list(v8.ROWS) + NEW_ROWS
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
    new_wrong = sum(1 for r in out if r["shape"] == "S21" and r["naive"] != r["expected"])
    res = {"fixture": "FALSE_GREEN_SHAPES", "version": "0.9", "selftest": f"{ok}/{total}",
           "naive_wrong_rows": naive_wrong, "naive_wrong_new_shapes": f"{new_wrong}/{len(NEW_ROWS)}",
           "naive_forced_verdicts_on_cant_tell": forced, "forced_verdict_control": ctl, "rows": out}
    json.dump(res, open("run_out_v0_9.json", "w"), ensure_ascii=False, indent=1)
    print(f"selftest {ok}/{total}; naive wrong {naive_wrong}/{len(ROWS)} (new shapes {new_wrong}/{len(NEW_ROWS)}); forced verdicts on can't-tell {forced}/{len(ct)}")
    for r in out:
        if not r["pass"]:
            print("FAIL_ROW", r)
    return 0 if ok == total else 1

if __name__ == "__main__":
    sys.exit(main())
