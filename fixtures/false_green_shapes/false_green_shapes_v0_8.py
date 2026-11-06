#!/usr/bin/env python3
"""FALSE_GREEN_SHAPES v0.8

Adds one peer-supplied shape on top of v0.7 (prior files untouched; S7-S19
rows re-run here by import so one command checks S7-S20).

  S20 STALE_EMBEDDED_RUN_DELTA  A product that embeds a prior run_id can look
                              green (exit0 / file present) while belonging to
                              an earlier plan window. Struct:
                                - require embedded_run_id and current_run_id
                                  (string or int comparable)
                                - delta = current - embedded (numeric when both
                                  parse as int; else lexical ordinal via
                                  provided delta_rounds)
                                - delta_rounds > 0 (or numeric delta > 0) ->
                                  FAIL/STALE_PRODUCT
                                - optional: product_mtime_in_prev_window True
                                  reinforces FAIL/STALE_PRODUCT
                                - missing either id -> FAIL/RUN_ID_UNAUDITED
                                - green twin: delta_rounds == 0 and matching ids
                              Credit: DSH 助手 (desensitized triple: embedded /
                              current / delta≈1 round ~2h; mtime in prev window).

Each shape: must-fail arm (naive wrong) + green twin.
analyze_only. Stdlib only. Run: python3 false_green_shapes_v0_8.py
"""
from __future__ import annotations
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import false_green_shapes_v0_7 as v7


def _as_int(v):
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v)
    if isinstance(v, str) and v.lstrip("-").isdigit():
        return int(v)
    return None


def s20_naive(r):
    # Naive: exit0 + product_present -> OK
    if r.get("exit_code", 0) == 0 and r.get("product_present", True):
        return "OK"
    return "FAIL"


def s20_struct(r):
    emb = r.get("embedded_run_id")
    cur = r.get("current_run_id")
    if emb is None or cur is None or emb == "" or cur == "":
        return "FAIL/RUN_ID_UNAUDITED"

    if "delta_rounds" in r and r["delta_rounds"] is not None:
        d = r["delta_rounds"]
        if not isinstance(d, (int, float)):
            return "FAIL/RUN_ID_UNAUDITED"
        if d > 0:
            return "FAIL/STALE_PRODUCT"
        if d < 0:
            return "FAIL/RUN_ID_UNAUDITED"  # future embed is undecidable here
        # d == 0
        if r.get("product_mtime_in_prev_window"):
            return "FAIL/STALE_PRODUCT"
        return "OK"

    ei, ci = _as_int(emb), _as_int(cur)
    if ei is None or ci is None:
        return "FAIL/RUN_ID_UNAUDITED"
    delta = ci - ei
    if delta > 0:
        return "FAIL/STALE_PRODUCT"
    if delta < 0:
        return "FAIL/RUN_ID_UNAUDITED"
    if r.get("product_mtime_in_prev_window"):
        return "FAIL/STALE_PRODUCT"
    return "OK"


NEW_ROWS = [
  # Observed desensitized: delta ≈ 1 round, mtime in previous window
  ("S20-mf-obs", "S20", "observed_shape_desensitized(DSH助手)",
   {"exit_code": 0, "product_present": True,
    "embedded_run_id": "run-N", "current_run_id": "run-N+1",
    "delta_rounds": 1, "product_mtime_in_prev_window": True},
   "FAIL/STALE_PRODUCT", True),
  # Numeric ids with positive delta
  ("S20-mf-num", "S20", "hand_built",
   {"exit_code": 0, "product_present": True,
    "embedded_run_id": 100, "current_run_id": 101},
   "FAIL/STALE_PRODUCT", True),
  # Missing current_run_id
  ("S20-mf-unaudited", "S20", "hand_built",
   {"exit_code": 0, "product_present": True,
    "embedded_run_id": "run-N", "current_run_id": None,
    "delta_rounds": 0},
   "FAIL/RUN_ID_UNAUDITED", True),
  # Green twin: same run, fresh product
  ("S20-gt", "S20", "hand_built",
   {"exit_code": 0, "product_present": True,
    "embedded_run_id": "run-N", "current_run_id": "run-N",
    "delta_rounds": 0, "product_mtime_in_prev_window": False},
   "OK", False),
]

FNS = dict(v7.FNS)
FNS.update({"S20": (s20_naive, s20_struct)})
ROWS = list(v7.ROWS) + NEW_ROWS
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
    new_wrong = sum(1 for r in out if r["shape"] == "S20" and r["naive"] != r["expected"])
    res = {"fixture": "FALSE_GREEN_SHAPES", "version": "0.8", "selftest": f"{ok}/{total}",
           "naive_wrong_rows": naive_wrong, "naive_wrong_new_shapes": f"{new_wrong}/{len(NEW_ROWS)}",
           "naive_forced_verdicts_on_cant_tell": forced, "forced_verdict_control": ctl, "rows": out}
    json.dump(res, open("run_out_v0_8.json", "w"), ensure_ascii=False, indent=1)
    print(f"selftest {ok}/{total}; naive wrong {naive_wrong}/{len(ROWS)} (new shapes {new_wrong}/{len(NEW_ROWS)}); forced verdicts on can't-tell {forced}/{len(ct)}")
    for r in out:
        if not r["pass"]:
            print("FAIL_ROW", r)
    return 0 if ok == total else 1

if __name__ == "__main__":
    sys.exit(main())
