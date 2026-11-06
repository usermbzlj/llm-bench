#!/usr/bin/env python3
"""FALSE_GREEN_SHAPES v0.10

Adds one peer-supplied shape on top of v0.9 (prior files untouched; S7-S21
rows re-run here by import so one command checks S7-S22).

  S22 ROUND_CLEARED_BACKLOG_REMAINS  Current-round pending==0 must not imply
                              historical backlog cleared. Struct:
                                - if remaining_backlog > 0 -> FAIL/BACKLOG_REMAINS
                                  even when round_pending==0 and budget_hit
                                - empty current page (sparse pagination) with
                                  remaining_backlog>0 -> FAIL/BACKLOG_REMAINS
                                - missing remaining_backlog field ->
                                  FAIL/BACKLOG_UNAUDITED
                                - green twin: remaining_backlog==0 and
                                  round_pending==0
                              Credit: 凯瑞's Agent (本轮待处理清零≠历史积压清零;
                              预算上限只结束本轮).

Each shape: must-fail arm (naive wrong) + green twin.
analyze_only. Stdlib only. Run: python3 false_green_shapes_v0_10.py
"""
from __future__ import annotations
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import false_green_shapes_v0_9 as v9


def s22_naive(r):
    # Naive: round_pending==0 (+ optional budget_hit) -> OK / "全量已检查"
    if r.get("round_pending", 1) == 0:
        return "OK"
    return "FAIL"


def s22_struct(r):
    if "remaining_backlog" not in r or r["remaining_backlog"] is None:
        return "FAIL/BACKLOG_UNAUDITED"
    rem = r["remaining_backlog"]
    if not isinstance(rem, (int, float)) or rem < 0:
        return "FAIL/BACKLOG_UNAUDITED"
    if rem > 0:
        return "FAIL/BACKLOG_REMAINS"
    # rem == 0
    if r.get("round_pending", 0) != 0:
        return "FAIL"  # still working current round
    return "OK"


NEW_ROWS = [
  # Observed: round cleared, budget hit, backlog remains
  ("S22-mf-obs", "S22", "observed_shape_desensitized(凯瑞)",
   {"round_pending": 0, "remaining_backlog": 17, "budget_hit": True,
    "claimed": 20, "judged": 20},
   "FAIL/BACKLOG_REMAINS", True),
  # Sparse pagination: empty page but backlog remains
  ("S22-mf-sparse", "S22", "hand_built",
   {"round_pending": 0, "remaining_backlog": 3, "empty_current_page": True,
    "budget_hit": False},
   "FAIL/BACKLOG_REMAINS", True),
  # Missing backlog counter
  ("S22-mf-unaudited", "S22", "hand_built",
   {"round_pending": 0, "budget_hit": True},
   "FAIL/BACKLOG_UNAUDITED", True),
  # Green twin
  ("S22-gt", "S22", "hand_built",
   {"round_pending": 0, "remaining_backlog": 0, "budget_hit": False,
    "claimed": 20, "judged": 20},
   "OK", False),
]

FNS = dict(v9.FNS)
FNS.update({"S22": (s22_naive, s22_struct)})
ROWS = list(v9.ROWS) + NEW_ROWS
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
    new_wrong = sum(1 for r in out if r["shape"] == "S22" and r["naive"] != r["expected"])
    res = {"fixture": "FALSE_GREEN_SHAPES", "version": "0.10", "selftest": f"{ok}/{total}",
           "naive_wrong_rows": naive_wrong, "naive_wrong_new_shapes": f"{new_wrong}/{len(NEW_ROWS)}",
           "naive_forced_verdicts_on_cant_tell": forced, "forced_verdict_control": ctl, "rows": out}
    json.dump(res, open("run_out_v0_10.json", "w"), ensure_ascii=False, indent=1)
    print(f"selftest {ok}/{total}; naive wrong {naive_wrong}/{len(ROWS)} (new shapes {new_wrong}/{len(NEW_ROWS)}); forced verdicts on can't-tell {forced}/{len(ct)}")
    for r in out:
        if not r["pass"]:
            print("FAIL_ROW", r)
    return 0 if ok == total else 1

if __name__ == "__main__":
    sys.exit(main())
