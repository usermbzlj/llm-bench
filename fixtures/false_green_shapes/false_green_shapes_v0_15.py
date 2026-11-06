#!/usr/bin/env python3
"""FALSE_GREEN_SHAPES v0.15

Adds one peer-supplied shape on top of v0.14 (prior files untouched; S7-S26
rows re-run here by import so one command checks S7-S27).

  S27 WRITEBACK_ID_NUMERIC_REWRITE  Receipt/object IDs that survive a numeric
                              JSON/float round-trip can silently rewrite trailing
                              digits while row counts still match — naive green.
                              Struct:
                                - missing submitted/receipt id pair
                                  -> FAIL/ID_PAIR_MISSING
                                - numeric equality (or count-only) while
                                  character string differs
                                  -> FAIL/ID_NUMERIC_REWRITE
                                - green twin: character-identical id strings
                              Credit: Hermes (19-digit decimal ids with
                              mod 64 == 0; after numeric type pass trailing
                              digits rewrite; count still matches; require
                              id_string_equal). Owed earlier as
                              WRITEBACK_ID_NUMERIC_REWRITE (Noteknot).

Each shape: must-fail arm (naive wrong) + green twin.
analyze_only. Stdlib only. Run: python3 false_green_shapes_v0_15.py
"""
from __future__ import annotations
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import false_green_shapes_v0_14 as v14


def _as_num(x):
    try:
        return int(float(str(x)))
    except (TypeError, ValueError):
        return None


def s27_naive(r):
    # Naive: count match OR numeric id equality -> OK
    pairs = r.get("id_pairs")
    if pairs:
        if r.get("count_match", True):
            # Prefer numeric compare when both sides coerce
            ok = True
            for a, b in pairs:
                na, nb = _as_num(a), _as_num(b)
                if na is None or nb is None or na != nb:
                    ok = False
                    break
            if ok:
                return "OK"
        if len(pairs) == r.get("expected_count", len(pairs)):
            return "OK"
    if r.get("submitted_count") == r.get("receipt_count"):
        return "OK"
    return "FAIL"


def s27_struct(r):
    pairs = r.get("id_pairs")
    if not pairs:
        a, b = r.get("submitted_id"), r.get("receipt_id")
        if a is None or b is None:
            return "FAIL/ID_PAIR_MISSING"
        pairs = [(a, b)]
    for a, b in pairs:
        if a is None or b is None:
            return "FAIL/ID_PAIR_MISSING"
        sa, sb = str(a), str(b)
        if sa != sb:
            na, nb = _as_num(a), _as_num(b)
            if na is not None and nb is not None and na == nb:
                return "FAIL/ID_NUMERIC_REWRITE"
            return "FAIL/ID_NUMERIC_REWRITE"
    return "OK"


NEW_ROWS = [
  # Observed: 19-digit ids rewritten after numeric pass; counts still match
  ("S27-mf-obs", "S27", "observed_shape_desensitized(Hermes)",
   {"count_match": True, "expected_count": 2,
    "id_pairs": [
      ("9223372036854775808", "9223372036854775800"),
      ("9223372036854775872", "9223372036854775800"),
    ]},
   "FAIL/ID_NUMERIC_REWRITE", True),
  # Single pair form
  ("S27-mf-single", "S27", "hand_built",
   {"submitted_id": "1000000000000000064", "receipt_id": "1000000000000000000",
    "count_match": True},
   "FAIL/ID_NUMERIC_REWRITE", True),
  # Missing pair
  ("S27-mf-missing", "S27", "hand_built",
   {"submitted_count": 1, "receipt_count": 1},
   "FAIL/ID_PAIR_MISSING", True),
  # Count-only naive green with rewrite
  ("S27-mf-count", "S27", "hand_built",
   {"submitted_count": 3, "receipt_count": 3, "count_match": True,
    "id_pairs": [("64", "0")]},
   "FAIL/ID_NUMERIC_REWRITE", True),
  # Green twin: character-identical strings
  ("S27-gt", "S27", "hand_built",
   {"count_match": True,
    "id_pairs": [
      ("9223372036854775808", "9223372036854775808"),
      ("1000000000000000064", "1000000000000000064"),
    ]},
   "OK", False),
]

FNS = dict(v14.FNS)
FNS.update({"S27": (s27_naive, s27_struct)})
ROWS = list(v14.ROWS) + NEW_ROWS
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
    new_wrong = sum(1 for r in out if r["shape"] == "S27" and r["naive"] != r["expected"])
    res = {"fixture": "FALSE_GREEN_SHAPES", "version": "0.15", "selftest": f"{ok}/{total}",
           "naive_wrong_rows": naive_wrong, "naive_wrong_new_shapes": f"{new_wrong}/{len(NEW_ROWS)}",
           "naive_forced_verdicts_on_cant_tell": forced, "forced_verdict_control": ctl, "rows": out}
    json.dump(res, open("run_out_v0_15.json", "w"), ensure_ascii=False, indent=1)
    print(f"selftest {ok}/{total}; naive wrong {naive_wrong}/{len(ROWS)} (new shapes {new_wrong}/{len(NEW_ROWS)}); forced verdicts on can't-tell {forced}/{len(ct)}")
    for r in out:
        if not r["pass"]:
            print("FAIL_ROW", r)
    return 0 if ok == total else 1

if __name__ == "__main__":
    sys.exit(main())
