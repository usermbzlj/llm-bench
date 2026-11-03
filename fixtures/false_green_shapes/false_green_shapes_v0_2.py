#!/usr/bin/env python3
"""FALSE_GREEN_SHAPES v0.2

Adds five shapes to v0.1 (S1-S3 unchanged, v0.1 file untouched; S4-S6 numbers
stay reserved -- those shapes landed in exit0_product_absent / not_applicable_as_zero).

  S7  END_REASON_NOT_EXHAUSTED  rc=0 partial pull. A pull is complete only when
                                end_reason == "exhausted" AND has_more is False.
                                rc=0 + has_more/cursor left / end_reason=limit|timeout
                                -> UNDECIDABLE (never OK).  Shape credit: 郑珺的hermes.
  S8  SHAPE_DRIFT_UNVERSIONED   receipt key-set changed vs the pinned shape while
                                schema_version did not move -> UNKNOWN/SHAPE_DRIFT_UNVERSIONED;
                                key-set changed AND version bumped -> evaluate normally;
                                member missing from pinned key-set -> KEYSET_MEMBER_DRIFT.
                                Shape credit: K.
  S9  OK_FIELD_DEGRADED         top-level ok=true only proves "process alive". OK requires
                                the declared business path (>=1 source with usable>0).
                                ok=true + every usable source == 0 -> FAIL/OK_FIELD_DEGRADED;
                                business path absent -> UNKNOWN.  Observed shape (desensitized,
                                contributor-supplied) credit: 小白龙.
  S10 SELFTEST_GREEN_EVAL_ZERO  rc=0 + selftest all-pass + report generated is NOT a run:
                                requests_sent==0 or import/transport exception on every item
                                -> FAIL/EVAL_NEVER_EXECUTED. Selftest green and accuracy 0
                                are both true; they measure different things.
                                Observed row credit: 小白龙.
  S11 COVERAGE_COUNT_NOT_SPAN   "7/7 copies" is a count, not coverage. Requires
                                expected_span: newest_age <= max_age AND max adjacent gap
                                <= max_gap, else FAIL/COVERAGE_GAP. Missing timestamps ->
                                UNKNOWN (count may not self-attest coverage).
                                Observed row credit: 小白龙 (5d17h gap behind 7/7 ok=true).

Each shape: must-fail arm (naive rule provably wrong) + green twin (both agree).
analyze_only. Stdlib only. Run: python3 false_green_shapes_v0_2.py
"""
from __future__ import annotations
import json, sys

H = 3600

# ---------- S7 ----------
def s7_naive(r):
    return "OK" if r["rc"] == 0 else "FAIL"

def s7_struct(r):
    if r["rc"] != 0:
        return "FAIL"
    if r.get("end_reason") == "exhausted" and r.get("has_more") is False:
        return "OK"
    return "UNDECIDABLE"

# ---------- S8 ----------
def s8_naive(r):
    return "OK" if r["status"] == "done" else "FAIL"

def s8_struct(r):
    pinned, keys = set(r["pinned_keys"]), set(r["keys"])
    if keys != pinned:
        if r["schema_version"] == r["pinned_version"]:
            return "UNKNOWN/KEYSET_MEMBER_DRIFT" if pinned - keys else "UNKNOWN/SHAPE_DRIFT_UNVERSIONED"
    return "OK" if r["status"] == "done" else "FAIL"

# ---------- S9 ----------
def s9_naive(b):
    return "OK" if b.get("ok") is True else "FAIL"

def s9_struct(b):
    if b.get("ok") is not True:
        return "FAIL"
    usable = b.get("usable")            # declared business path: {source: usable_count}
    if not isinstance(usable, dict) or not usable:
        return "UNKNOWN"
    return "OK" if any(v > 0 for v in usable.values()) else "FAIL/OK_FIELD_DEGRADED"

# ---------- S10 ----------
def s10_naive(r):
    return "OK" if r["rc"] == 0 and r["selftest_pass"] == r["selftest_total"] and r["report"] else "FAIL"

def s10_struct(r):
    if r["rc"] != 0:
        return "FAIL"
    if r.get("requests_sent", 0) == 0 or r.get("item_exceptions", 0) >= r.get("items", 0) > 0:
        return "FAIL/EVAL_NEVER_EXECUTED"
    return "OK"

# ---------- S11 ----------
def s11_naive(r):
    return "OK" if r["have"] >= r["expected_count"] else "FAIL"

def s11_struct(r):
    if r["have"] < r["expected_count"]:
        return "FAIL"
    ts = r.get("ts")
    if not ts or len(ts) < r["have"]:
        return "UNKNOWN"
    ts = sorted(ts)
    gaps = [b - a for a, b in zip(ts, ts[1:])]
    if r["now"] - ts[-1] > r["max_age_s"] or (gaps and max(gaps) > r["max_gap_s"]):
        return "FAIL/COVERAGE_GAP"
    return "OK"

D = 24 * H
daily = [i * D for i in range(7)]
gappy = [0, D, 2 * D, 3 * D, 3 * D + 5 * D + 17 * H, 9 * D, 10 * D]   # 5d17h hole
PK = ["id", "status", "bytes", "ts"]

ROWS = [
  # id, shape, provenance, arg, expected, must_fail_arm
  ("S7-mf",  "S7", "hand_built", {"rc": 0, "end_reason": "limit", "has_more": True}, "UNDECIDABLE", True),
  ("S7-mf2", "S7", "hand_built", {"rc": 0, "end_reason": "exhausted", "has_more": True}, "UNDECIDABLE", True),
  ("S7-gt",  "S7", "hand_built", {"rc": 0, "end_reason": "exhausted", "has_more": False}, "OK", False),
  ("S7-rc",  "S7", "hand_built", {"rc": 1, "end_reason": "timeout", "has_more": True}, "FAIL", False),
  ("S8-mf",  "S8", "hand_built", {"pinned_keys": PK, "keys": PK + ["delivered_delta"], "schema_version": 3, "pinned_version": 3, "status": "done"}, "UNKNOWN/SHAPE_DRIFT_UNVERSIONED", True),
  ("S8-mf2", "S8", "hand_built", {"pinned_keys": PK, "keys": ["id", "status", "ts"], "schema_version": 3, "pinned_version": 3, "status": "done"}, "UNKNOWN/KEYSET_MEMBER_DRIFT", True),
  ("S8-gt",  "S8", "hand_built", {"pinned_keys": PK, "keys": PK + ["delivered_delta"], "schema_version": 4, "pinned_version": 3, "status": "done"}, "OK", False),
  ("S8-gt2", "S8", "hand_built", {"pinned_keys": PK, "keys": PK, "schema_version": 3, "pinned_version": 3, "status": "done"}, "OK", False),
  ("S9-mf",  "S9", "observed_shape_desensitized", {"ok": True, "port": 0, "sources": ["s1", "s2"], "usable": {"s1": 0, "s2": 0}}, "FAIL/OK_FIELD_DEGRADED", True),
  ("S9-un",  "S9", "hand_built", {"ok": True, "port": 0, "sources": ["s1"]}, "UNKNOWN", True),
  ("S9-gt",  "S9", "hand_built", {"ok": True, "usable": {"s1": 0, "s2": 3}}, "OK", False),
  ("S10-mf", "S10", "observed_shape_desensitized", {"rc": 0, "selftest_pass": 27, "selftest_total": 27, "report": True, "items": 40, "requests_sent": 0, "item_exceptions": 80}, "FAIL/EVAL_NEVER_EXECUTED", True),
  ("S10-gt", "S10", "hand_built", {"rc": 0, "selftest_pass": 27, "selftest_total": 27, "report": True, "items": 40, "requests_sent": 40, "item_exceptions": 0}, "OK", False),
  ("S11-mf", "S11", "observed_shape_desensitized", {"have": 7, "expected_count": 7, "ts": gappy, "now": 10 * D + H, "max_age_s": 2 * D, "max_gap_s": 2 * D}, "FAIL/COVERAGE_GAP", True),
  ("S11-un", "S11", "hand_built", {"have": 7, "expected_count": 7, "ts": None, "now": 0, "max_age_s": 2 * D, "max_gap_s": 2 * D}, "UNKNOWN", True),
  ("S11-gt", "S11", "hand_built", {"have": 7, "expected_count": 7, "ts": daily, "now": 6 * D + H, "max_age_s": 2 * D, "max_gap_s": 2 * D}, "OK", False),
  ("S11-sh", "S11", "hand_built", {"have": 6, "expected_count": 7, "ts": daily[:6], "now": 6 * D, "max_age_s": 2 * D, "max_gap_s": 2 * D}, "FAIL", False),
]

FNS = {"S7": (s7_naive, s7_struct), "S8": (s8_naive, s8_struct), "S9": (s9_naive, s9_struct),
       "S10": (s10_naive, s10_struct), "S11": (s11_naive, s11_struct)}

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
    # control: naive never emits UNKNOWN/UNDECIDABLE -> every "can't tell" row is a forced verdict
    forced = sum(1 for r in out if r["expected"].split("/")[0] in ("UNKNOWN", "UNDECIDABLE")
                 and r["naive"] in ("OK", "FAIL"))
    ctl = forced == sum(1 for r in out if r["expected"].split("/")[0] in ("UNKNOWN", "UNDECIDABLE"))
    ok += ctl
    total = len(ROWS) + 1
    res = {"fixture": "FALSE_GREEN_SHAPES", "version": "0.2", "selftest": f"{ok}/{total}",
           "naive_wrong_rows": naive_wrong, "naive_forced_verdicts_on_unknown": forced,
           "forced_verdict_control": ctl, "rows": out}
    json.dump(res, open("run_out_v0_2.json", "w"), ensure_ascii=False, indent=1)
    print(f"selftest {ok}/{total}; naive rules wrong on {naive_wrong}/{len(ROWS)} rows; forced verdicts on unknown {forced}")
    return 0 if ok == total else 1

if __name__ == "__main__":
    sys.exit(main())
