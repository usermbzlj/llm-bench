#!/usr/bin/env python3
"""FALSE_GREEN_SHAPES v0.3

Adds three peer-supplied shapes on top of v0.2 (v0.1/v0.2 files untouched; S7-S11
rows re-run here by import so one command checks S7-S14).

  S12 RULE_SOURCE_REV_STALE   content_hash matches but the rule source was read at an
                              old revision. OK requires content_hash == expected AND
                              seen_rev == current_rev. Hash ok + rev behind -> UNKNOWN
                              (never green). Observed desensitized row credit: MOSS
                              (gate doc seen at v6.8, once passed as green = historical misjudge).
  S13 PARTIAL_SILENT_SKIP     server accepts the batch, processed_count matches the
                              submitted count, but skipped_count>0 / skipped_reasons carry
                              "unknown item". Count-green, attribution broken. OK requires
                              skipped_count == 0 AND submitted id set == on-disk id set.
                              Id not in on-disk set -> FAIL/LOCAL_ID_TYPO (fix locally,
                              no rerun); transport failure -> RETRYABLE. Three states, never
                              merged. Observed row credit: 青藤 (1 digit typo in 20 ids ->
                              processed 19 + skipped 1, no batch error).
  S14 FROZEN_RULE_EXIT0       compat/rule check reports false (incompatible) for >=2 rounds
                              while the business stage still exits 0 and the cycle closes.
                              exit 0 under a failing rule gate -> FAIL/RULE_GATE_IGNORED;
                              1 round -> UNKNOWN (could be CDN lag window). Observed row
                              credit: ZCode (contract 1.0.6 vs CDN 1.0.5, two rounds false, exit 0).

Each shape: must-fail arm (naive rule provably wrong) + green twin.
analyze_only. Stdlib only. Run: python3 false_green_shapes_v0_3.py
"""
from __future__ import annotations
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import false_green_shapes_v0_2 as v2

# ---------- S12 ----------
def s12_naive(r):
    return "OK" if r["content_hash"] == r["expected_hash"] else "FAIL"

def s12_struct(r):
    if r["content_hash"] != r["expected_hash"]:
        return "FAIL"
    if r.get("seen_rev") is None or r.get("current_rev") is None:
        return "UNKNOWN/REV_MISSING"
    return "OK" if r["seen_rev"] == r["current_rev"] else "UNKNOWN/RULE_SOURCE_REV_STALE"

# ---------- S13 ----------
def s13_naive(r):
    return "OK" if r.get("transport_ok") and r["processed_count"] + r.get("skipped_count", 0) == len(r["submitted_ids"]) else "FAIL"

def s13_struct(r):
    if not r.get("transport_ok"):
        return "RETRYABLE/TRANSPORT"
    stray = set(r["submitted_ids"]) - set(r["disk_ids"])
    if stray:
        return "FAIL/LOCAL_ID_TYPO"
    if r.get("skipped_count", 0) > 0:
        return "FAIL/PARTIAL_SILENT_SKIP"
    return "OK"

# ---------- S14 ----------
def s14_naive(r):
    return "OK" if r["rc"] == 0 else "FAIL"

def s14_struct(r):
    if r["rc"] != 0:
        return "FAIL"
    fails = r.get("rule_check_false_rounds", 0)
    if fails >= 2:
        return "FAIL/RULE_GATE_IGNORED"
    if fails == 1:
        return "UNKNOWN/RULE_GATE_ONE_ROUND"
    return "OK"

ids20 = [f"37{6000000 + i:07d}" for i in range(20)]
typo = ids20[:19] + [ids20[19][:-2] + "91"]  # hand-typed id error (…019 -> …091, not in on-disk set)

NEW_ROWS = [
  ("S12-mf", "S12", "observed_shape_desensitized", {"content_hash": "h1", "expected_hash": "h1", "seen_rev": "v6.8", "current_rev": "v7"}, "UNKNOWN/RULE_SOURCE_REV_STALE", True),
  ("S12-un", "S12", "hand_built", {"content_hash": "h1", "expected_hash": "h1", "seen_rev": None, "current_rev": "v7"}, "UNKNOWN/REV_MISSING", True),
  ("S12-gt", "S12", "hand_built", {"content_hash": "h1", "expected_hash": "h1", "seen_rev": "v7", "current_rev": "v7"}, "OK", False),
  ("S13-mf", "S13", "observed_shape_desensitized", {"transport_ok": True, "submitted_ids": typo, "disk_ids": ids20, "processed_count": 19, "skipped_count": 1}, "FAIL/LOCAL_ID_TYPO", True),
  ("S13-mf2","S13", "hand_built", {"transport_ok": True, "submitted_ids": ids20, "disk_ids": ids20, "processed_count": 19, "skipped_count": 1}, "FAIL/PARTIAL_SILENT_SKIP", True),
  ("S13-tr", "S13", "hand_built", {"transport_ok": False, "submitted_ids": ids20, "disk_ids": ids20, "processed_count": 0, "skipped_count": 0}, "RETRYABLE/TRANSPORT", True),
  ("S13-gt", "S13", "hand_built", {"transport_ok": True, "submitted_ids": ids20, "disk_ids": ids20, "processed_count": 20, "skipped_count": 0}, "OK", False),
  ("S14-mf", "S14", "observed_shape_desensitized", {"rc": 0, "rule_check_false_rounds": 2}, "FAIL/RULE_GATE_IGNORED", True),
  ("S14-un", "S14", "hand_built", {"rc": 0, "rule_check_false_rounds": 1}, "UNKNOWN/RULE_GATE_ONE_ROUND", True),
  ("S14-gt", "S14", "hand_built", {"rc": 0, "rule_check_false_rounds": 0}, "OK", False),
]

FNS = dict(v2.FNS)
FNS.update({"S12": (s12_naive, s12_struct), "S13": (s13_naive, s13_struct), "S14": (s14_naive, s14_struct)})
ROWS = list(v2.ROWS) + NEW_ROWS
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
    new_wrong = sum(1 for r in out if r["shape"] in ("S12", "S13", "S14") and r["naive"] != r["expected"])
    res = {"fixture": "FALSE_GREEN_SHAPES", "version": "0.3", "selftest": f"{ok}/{total}",
           "naive_wrong_rows": naive_wrong, "naive_wrong_new_shapes": f"{new_wrong}/{len(NEW_ROWS)}",
           "naive_forced_verdicts_on_cant_tell": forced, "forced_verdict_control": ctl, "rows": out}
    json.dump(res, open("run_out_v0_3.json", "w"), ensure_ascii=False, indent=1)
    print(f"selftest {ok}/{total}; naive wrong {naive_wrong}/{len(ROWS)} (new shapes {new_wrong}/{len(NEW_ROWS)}); forced verdicts on can't-tell {forced}/{len(ct)}")
    return 0 if ok == total else 1

if __name__ == "__main__":
    sys.exit(main())
