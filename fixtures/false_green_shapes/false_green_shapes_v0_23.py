#!/usr/bin/env python3
"""FALSE_GREEN_SHAPES v0.23

Adds one peer-supplied shape on top of v0.22 (prior files untouched; S7-S34
rows re-run here by import so one command checks S7-S35).

  S35 ACCEPTED_WRONG_FIELD_IGNORED  A batch write that returns transport
                              "accepted" / processed_count==n while using the
                              wrong field name (e.g. `rating` instead of
                              `score`) must not green-wash when readback shows
                              no semantic change. Naive treats
                              (status==accepted OR processed_count==n) as OK.
                              Struct:
                                - write_field_name undeclared ->
                                  UNKNOWN/FIELD_NAME_UNDECLARED
                                - expected_field_name undeclared ->
                                  UNKNOWN/EXPECTED_FIELD_UNDECLARED
                                - readback_score missing while claiming
                                  accepted -> UNKNOWN/READBACK_MISSING
                                - write_field_name != expected_field_name
                                  AND status accepted AND readback unchanged
                                  (equal to pre_score) ->
                                  FAIL/ACCEPTED_WRONG_FIELD_IGNORED
                                - write_field correct AND readback matches
                                  intended_score -> OK
                                - status not accepted -> FAIL/WRITE_REJECTED
                              Credit: 小巴助手 (EigenFlux PM — batch POST
                              /items/feedback with field `rating` → 21/21
                              accepted; GET readback my_score all 0; fix to
                              `score` then 3/3 consistent. Also noted
                              jq .data.accepted misread — real shape is
                              processed_count + results[].status).

Each shape: must-fail arm (naive wrong) + green twin.
analyze_only. Stdlib only. Run: python3 false_green_shapes_v0_23.py
"""
from __future__ import annotations
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import false_green_shapes_v0_22 as v22


def s35_naive(r):
    # Naive: transport green => OK
    if r.get("status") == "accepted":
        return "OK"
    pc = r.get("processed_count")
    n = r.get("batch_n")
    if pc is not None and n is not None and pc == n:
        return "OK"
    if r.get("results_all_accepted") is True:
        return "OK"
    return "FAIL"


def s35_struct(r):
    wfn = r.get("write_field_name")
    efn = r.get("expected_field_name")
    if wfn is None:
        return "UNKNOWN/FIELD_NAME_UNDECLARED"
    if efn is None:
        return "UNKNOWN/EXPECTED_FIELD_UNDECLARED"

    status = r.get("status")
    if status is None and r.get("results_all_accepted") is True:
        status = "accepted"

    rb = r.get("readback_score")
    if status == "accepted" and rb is None and r.get("readback_claimed") is not False:
        # claiming acceptance without a readback observation
        if r.get("skip_readback") is True:
            return "UNKNOWN/READBACK_MISSING"
        if "readback_score" not in r:
            return "UNKNOWN/READBACK_MISSING"

    if status not in ("accepted", None) and status != "accepted":
        if status in ("rejected", "error", "failed"):
            return "FAIL/WRITE_REJECTED"

    pre = r.get("pre_score")
    intended = r.get("intended_score")

    if wfn != efn:
        if status == "accepted" or r.get("results_all_accepted") is True:
            # unchanged readback relative to pre => silent ignore
            if rb is not None and pre is not None and rb == pre:
                return "FAIL/ACCEPTED_WRONG_FIELD_IGNORED"
            if rb is not None and intended is not None and rb != intended:
                return "FAIL/ACCEPTED_WRONG_FIELD_IGNORED"
            if r.get("readback_unchanged") is True:
                return "FAIL/ACCEPTED_WRONG_FIELD_IGNORED"
            return "FAIL/ACCEPTED_WRONG_FIELD_IGNORED"
        return "FAIL/WRITE_REJECTED"

    # correct field name
    if status == "accepted" or r.get("results_all_accepted") is True:
        if rb is not None and intended is not None and rb == intended:
            return "OK"
        if rb is not None and intended is not None and rb != intended:
            return "FAIL/ACCEPTED_WRONG_FIELD_IGNORED"
        if r.get("skip_readback") is True:
            return "UNKNOWN/READBACK_MISSING"
        return "OK"

    return "FAIL/WRITE_REJECTED"


NEW_ROWS = [
  # Observed: wrong field `rating`, all accepted, readback still 0
  ("S35-mf-rating-vs-score", "S35", "observed_shape_desensitized(XiaoBa)",
   {"write_field_name": "rating", "expected_field_name": "score",
    "status": "accepted", "processed_count": 21, "batch_n": 21,
    "results_all_accepted": True, "pre_score": 0, "intended_score": 2,
    "readback_score": 0, "readback_unchanged": True},
   "FAIL/ACCEPTED_WRONG_FIELD_IGNORED", True),
  # Field name undeclared
  ("S35-ct-field-undeclared", "S35", "hand_built",
   {"expected_field_name": "score", "status": "accepted",
    "processed_count": 3, "batch_n": 3, "pre_score": 0,
    "intended_score": 1, "readback_score": 0},
   "UNKNOWN/FIELD_NAME_UNDECLARED", True),
  # Expected field undeclared
  ("S35-ct-expected-undeclared", "S35", "hand_built",
   {"write_field_name": "score", "status": "accepted",
    "pre_score": 0, "intended_score": 1, "readback_score": 1},
   "UNKNOWN/EXPECTED_FIELD_UNDECLARED", True),
  # Accepted but no readback
  ("S35-ct-readback-missing", "S35", "hand_built",
   {"write_field_name": "score", "expected_field_name": "score",
    "status": "accepted", "skip_readback": True, "intended_score": 2},
   "UNKNOWN/READBACK_MISSING", True),
  # Wrong field, accepted, readback unchanged via flag
  ("S35-mf-alias-silent", "S35", "hand_built",
   {"write_field_name": "stars", "expected_field_name": "score",
    "status": "accepted", "results_all_accepted": True,
    "pre_score": 0, "intended_score": 1, "readback_unchanged": True,
    "readback_score": 0},
   "FAIL/ACCEPTED_WRONG_FIELD_IGNORED", True),
  # Green: correct field, readback matches
  ("S35-gt-score-readback", "S35", "hand_built",
   {"write_field_name": "score", "expected_field_name": "score",
    "status": "accepted", "processed_count": 3, "batch_n": 3,
    "pre_score": 0, "intended_score": 2, "readback_score": 2},
   "OK", False),
  # Green: correct field Chinese alias normalized equal
  ("S35-gt-same-field", "S35", "hand_built",
   {"write_field_name": "score", "expected_field_name": "score",
    "status": "accepted", "results_all_accepted": True,
    "pre_score": 1, "intended_score": 1, "readback_score": 1},
   "OK", False),
]

FNS = dict(v22.FNS)
FNS.update({"S35": (s35_naive, s35_struct)})
ROWS = list(v22.ROWS) + NEW_ROWS
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
    new_wrong = sum(1 for r in out if r["shape"] == "S35" and r["naive"] != r["expected"])
    res = {"fixture": "FALSE_GREEN_SHAPES", "version": "0.23", "selftest": f"{ok}/{total}",
           "naive_wrong_rows": naive_wrong, "naive_wrong_new_shapes": f"{new_wrong}/{len(NEW_ROWS)}",
           "naive_forced_verdicts_on_cant_tell": forced, "forced_verdict_control": ctl, "rows": out}
    json.dump(res, open("run_out_v0_23.json", "w"), ensure_ascii=False, indent=1)
    print(f"selftest {ok}/{total}; naive wrong {naive_wrong}/{len(ROWS)} (new shapes {new_wrong}/{len(NEW_ROWS)}); forced verdicts on can't-tell {forced}/{len(ct)}")
    for r in out:
        if not r["pass"]:
            print("FAIL", r["id"], "struct", r["struct"], "naive", r["naive"], "exp", r["expected"])
    if not ctl:
        print("FAIL forced-verdict-control", forced, "of", len(ct))
    sys.exit(0 if ok == total else 1)

if __name__ == "__main__":
    main()
