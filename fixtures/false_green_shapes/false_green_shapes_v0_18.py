#!/usr/bin/env python3
"""FALSE_GREEN_SHAPES v0.18

Adds one peer-supplied shape on top of v0.17 (prior files untouched; S7-S29
rows re-run here by import so one command checks S7-S30).

  S30 ILLEGAL_ENUM_SILENT_EMPTY  A query with an illegal enum parameter that
                              returns an empty list and no error is
                              indistinguishable from a true empty result on
                              every green dashboard. Naive treats empty as
                              "no data / OK". Struct requires that every enum
                              query first prove the parameter is validated
                              (illegal probe must error); otherwise empty is
                              FAIL/ENUM_UNVALIDATED. Separately, an empty
                              ledger may only claim OBSERVED_ZERO, never
                              ABSENT, without extra evidence.
                              Credit: Hermes (direction=inbound returned []
                              silently; direction=incoming returned 5 pending
                              at the same instant; coverage denom must be
                              expected-objects-per-external-shape, not the
                              already-read set).

Each shape: must-fail arm (naive wrong) + green twin.
analyze_only. Stdlib only. Run: python3 false_green_shapes_v0_18.py
"""
from __future__ import annotations
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import false_green_shapes_v0_17 as v17


def s30_naive(r):
    # Naive: empty list / zero count => OK (no pending / no data)
    items = r.get("items")
    if items is None:
        count = r.get("count")
        if count is None:
            return "FAIL"
        try:
            return "OK" if int(count) == 0 else "OK"
        except (TypeError, ValueError):
            return "FAIL"
    if isinstance(items, list) and len(items) == 0:
        return "OK"
    return "OK"


def s30_struct(r):
    # Enum validation gate
    validated = r.get("enum_validated")
    illegal_probe_errored = r.get("illegal_probe_errored")
    if validated is None and illegal_probe_errored is None:
        return "UNKNOWN/ENUM_VALIDATION_UNDECLARED"
    if validated is False or illegal_probe_errored is False:
        # Empty (or any) result after unvalidated enum is untrusted
        return "FAIL/ENUM_UNVALIDATED"
    # Validated path: empty may only conclude OBSERVED_ZERO, not ABSENT
    items = r.get("items")
    count = r.get("count")
    empty = (isinstance(items, list) and len(items) == 0) or (
        count is not None and int(count) == 0
    )
    if empty:
        conclusion = (r.get("conclusion") or "").upper()
        if conclusion in ("ABSENT", "NONE", "NO_DATA", "DOES_NOT_EXIST"):
            return "FAIL/CONCLUSION_OVERREACH"
        if conclusion in ("OBSERVED_ZERO", "READ_ZERO", ""):
            # Honest empty observation
            return "OK"
        return "FAIL/CONCLUSION_OVERREACH"
    return "OK"


NEW_ROWS = [
  # Observed: illegal enum inbound -> [] no error (false green "no pending")
  ("S30-mf-illegal-empty", "S30", "observed_shape_desensitized(Hermes)",
   {"enum_param": "inbound", "items": [], "error": None,
    "enum_validated": False, "illegal_probe_errored": False,
    "conclusion": "absent"},
   "FAIL/ENUM_UNVALIDATED", True),
  # Same empty with validated=false via probe only
  ("S30-mf-probe-silent", "S30", "hand_built",
   {"enum_param": "inbound", "items": [], "error": None,
    "illegal_probe_errored": False, "conclusion": "observed_zero"},
   "FAIL/ENUM_UNVALIDATED", True),
  # Validated empty but conclusion overreaches to ABSENT
  ("S30-mf-absent-overreach", "S30", "hand_built",
   {"enum_param": "incoming", "items": [], "error": None,
    "enum_validated": True, "illegal_probe_errored": True,
    "conclusion": "absent"},
   "FAIL/CONCLUSION_OVERREACH", True),
  # Undeclared validation -> can't tell
  ("S30-ct-undeclared", "S30", "hand_built",
   {"enum_param": "inbound", "items": [], "error": None},
   "UNKNOWN/ENUM_VALIDATION_UNDECLARED", True),
  # Green: illegal probe errors as required; legal query returns rows
  ("S30-gt-legal-rows", "S30", "observed_shape_desensitized(Hermes)",
   {"enum_param": "incoming", "items": ["a", "b", "c", "d", "e"], "error": None,
    "enum_validated": True, "illegal_probe_errored": True,
    "conclusion": "observed"},
   "OK", False),
  # Green honest zero: validated + OBSERVED_ZERO
  ("S30-gt-honest-zero", "S30", "hand_built",
   {"enum_param": "incoming", "items": [], "error": None,
    "enum_validated": True, "illegal_probe_errored": True,
    "conclusion": "observed_zero"},
   "OK", False),
]

FNS = dict(v17.FNS)
FNS.update({"S30": (s30_naive, s30_struct)})
ROWS = list(v17.ROWS) + NEW_ROWS
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
    new_wrong = sum(1 for r in out if r["shape"] == "S30" and r["naive"] != r["expected"])
    res = {"fixture": "FALSE_GREEN_SHAPES", "version": "0.18", "selftest": f"{ok}/{total}",
           "naive_wrong_rows": naive_wrong, "naive_wrong_new_shapes": f"{new_wrong}/{len(NEW_ROWS)}",
           "naive_forced_verdicts_on_cant_tell": forced, "forced_verdict_control": ctl, "rows": out}
    json.dump(res, open("run_out_v0_18.json", "w"), ensure_ascii=False, indent=1)
    print(f"selftest {ok}/{total}; naive wrong {naive_wrong}/{len(ROWS)} (new shapes {new_wrong}/{len(NEW_ROWS)}); forced verdicts on can't-tell {forced}/{len(ct)}")
    for r in out:
        if not r["pass"]:
            print("FAIL", r["id"], "struct", r["struct"], "naive", r["naive"], "exp", r["expected"])
    if not ctl:
        print("FAIL forced-verdict-control", forced, "of", len(ct))
    sys.exit(0 if ok == total else 1)

if __name__ == "__main__":
    main()
