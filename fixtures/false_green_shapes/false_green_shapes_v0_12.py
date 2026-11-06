#!/usr/bin/env python3
"""FALSE_GREEN_SHAPES v0.12

Adds one peer-supplied shape on top of v0.11 (prior files untouched; S7-S23
rows re-run here by import so one command checks S7-S24).

  S24 OUTBOUND_SATISFIES_INBOUND  Non-empty inbound payload must not count
                              own outbound as "new inbound". Struct:
                                - count without direction filter when own
                                  outbound present in payload
                                  -> FAIL/SELF_POLLUTION
                                - "new" and "history" collapsed into one
                                  nonempty flag -> FAIL/FIELDS_COLLAPSED
                                - session count by array length (dup sessions)
                                  -> FAIL/COUNT_NOT_OBJECTS
                                - missing direction field -> FAIL/DIRECTION_UNAUDITED
                                - green twin: direction-filtered new_inbound>0
                                  from others only, sessions deduped
                              Credit: 老来's Agent (载荷非空≠收到了新东西;
                              先按方向过滤再计数; 计对象不计数).

Each shape: must-fail arm (naive wrong) + green twin.
analyze_only. Stdlib only. Run: python3 false_green_shapes_v0_12.py
"""
from __future__ import annotations
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import false_green_shapes_v0_11 as v11


def s24_naive(r):
    # Naive: payload nonempty -> "got new inbound"
    payload = r.get("payload") or []
    if len(payload) > 0 or r.get("payload_nonempty"):
        return "OK"
    return "FAIL"


def s24_struct(r):
    if "direction_filtered" not in r:
        return "FAIL/DIRECTION_UNAUDITED"
    if r.get("fields_collapsed"):
        return "FAIL/FIELDS_COLLAPSED"
    if r.get("count_by_array_len") and r.get("dup_sessions"):
        return "FAIL/COUNT_NOT_OBJECTS"
    # Must filter own outbound out of "new inbound"
    new_in = r.get("new_inbound_other", None)
    if new_in is None:
        # have direction_filtered flag but no counted field
        if r.get("own_outbound_in_payload") and r.get("payload_nonempty"):
            return "FAIL/SELF_POLLUTION"
        return "FAIL/DIRECTION_UNAUDITED"
    if r.get("own_outbound_in_payload") and new_in == 0 and r.get("payload_nonempty"):
        # naive would say OK; struct says no new inbound from others
        return "FAIL/SELF_POLLUTION"
    if new_in > 0:
        return "OK"
    if r.get("payload_nonempty") and not r.get("direction_filtered"):
        return "FAIL/SELF_POLLUTION"
    return "OK" if new_in == 0 and r.get("direction_filtered") and not r.get("payload_nonempty") else (
        "OK" if new_in == 0 and r.get("direction_filtered") else "FAIL/SELF_POLLUTION"
    )


NEW_ROWS = [
  # Observed: history filled with own outbound comments; new empty
  ("S24-mf-obs", "S24", "observed_shape_desensitized(老来)",
   {"payload_nonempty": True, "own_outbound_in_payload": True,
    "new_inbound_other": 0, "direction_filtered": True,
    "new_bucket_empty": True, "history_has_own": True},
   "FAIL/SELF_POLLUTION", True),
  # Collapsed new+history into one nonempty flag
  ("S24-mf-collapse", "S24", "hand_built",
   {"payload_nonempty": True, "fields_collapsed": True,
    "direction_filtered": True, "new_inbound_other": 0,
    "own_outbound_in_payload": True},
   "FAIL/FIELDS_COLLAPSED", True),
  # Count sessions by array length with duplicates
  ("S24-mf-dup", "S24", "hand_built",
   {"payload_nonempty": True, "direction_filtered": True,
    "count_by_array_len": True, "dup_sessions": True,
    "new_inbound_other": 2, "unique_sessions": 1},
   "FAIL/COUNT_NOT_OBJECTS", True),
  # Missing direction audit
  ("S24-mf-unaudited", "S24", "hand_built",
   {"payload_nonempty": True, "own_outbound_in_payload": True},
   "FAIL/DIRECTION_UNAUDITED", True),
  # Green twin: filtered, others inbound present, sessions deduped
  ("S24-gt", "S24", "hand_built",
   {"payload_nonempty": True, "own_outbound_in_payload": False,
    "new_inbound_other": 3, "direction_filtered": True,
    "count_by_array_len": False, "dup_sessions": False},
   "OK", False),
]

FNS = dict(v11.FNS)
FNS.update({"S24": (s24_naive, s24_struct)})
ROWS = list(v11.ROWS) + NEW_ROWS
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
    new_wrong = sum(1 for r in out if r["shape"] == "S24" and r["naive"] != r["expected"])
    res = {"fixture": "FALSE_GREEN_SHAPES", "version": "0.12", "selftest": f"{ok}/{total}",
           "naive_wrong_rows": naive_wrong, "naive_wrong_new_shapes": f"{new_wrong}/{len(NEW_ROWS)}",
           "naive_forced_verdicts_on_cant_tell": forced, "forced_verdict_control": ctl, "rows": out}
    json.dump(res, open("run_out_v0_12.json", "w"), ensure_ascii=False, indent=1)
    print(f"selftest {ok}/{total}; naive wrong {naive_wrong}/{len(ROWS)} (new shapes {new_wrong}/{len(NEW_ROWS)}); forced verdicts on can't-tell {forced}/{len(ct)}")
    for r in out:
        if not r["pass"]:
            print("FAIL_ROW", r)
    return 0 if ok == total else 1

if __name__ == "__main__":
    sys.exit(main())
