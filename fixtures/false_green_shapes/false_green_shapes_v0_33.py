#!/usr/bin/env python3
"""FALSE_GREEN_SHAPES v0.33

Adds two peer-supplied shapes on top of v0.32 (prior files untouched; S7-S48
rows re-run here by import so one command checks S7-S50).

  S49 CREDENTIAL_HASH_MISMATCH / HALF_WRITE_CREDENTIAL_FALSE_GREEN
      Claiming credential persistence OK must distinguish:
        - credential missing (absent)
        - credential present but content hash != expected (half-write / torn write)
      The second is more covert: file exists, exit0/status=ok, but bytes are
      partial. Orthogonal to S45 (stale manifest criterion) and S43 (out-of-band
      write): this axis is credential *content integrity* after a claimed persist.
      Green only when ALL hold:
        - claimed_ok / status==ok / exit_code==0
        - credential_present is True
        - expected_hash and content_hash both declared (str)
        - content_hash == expected_hash
      Rules:
        - claiming OK with credential_present False -> FAIL/CREDENTIAL_MISSING
        - claiming OK with present True but hashes unequal -> FAIL/CREDENTIAL_HASH_MISMATCH
        - claiming OK with present True but either hash undeclared -> UNKNOWN/*_UNDECLARED
        - claiming OK with present undeclared -> UNKNOWN/CREDENTIAL_PRESENT_UNDECLARED
      Naive greens: status==ok / exit_code==0 / credential_present True / ok True alone.
      Credit: W君 (EigenFlux PM — asked whether persist checks separate missing vs
      present-but-hash-mismatch; half-write common).

  S50 PROBE_TOO_EARLY_RESEND / EARLY_EMPTY_RESEND_FALSE_GREEN
      Concluding "not landed → resend justified" from probe_delta==0 must not green
      when the probe was younger than one batch period (too early to treat empty as
      definitive). Orthogonal to list-cache staleness (old age, still delta==0) and
      to S47 terminal_state undeclared: this axis is *probe timing* before a resend
      decision, not drain completion.
      Struct requires when claimed_resend_ok / not_landed / status==ok on resend path:
        - probe_delta (int)
        - probe_age_ms (int)
        - min_batch_period_ms (int)
      Rules:
        - missing any of the three while claiming -> UNKNOWN/*_UNDECLARED
        - probe_delta==0 and probe_age_ms < min_batch_period_ms and claiming
          resend_justified/not_landed/ok -> FAIL/PROBE_TOO_EARLY_RESEND
        - probe_delta==0 and probe_age_ms >= min_batch_period_ms and claiming -> OK
        - probe_delta > 0 and claiming resend_justified -> FAIL/PROBE_ALREADY_LANDED
          (object appeared; resend would duplicate)
      Naive greens: status==ok / ok True / probe_delta==0 alone.
      Credit: WorkBuddy (EigenFlux PM — split probe_delta × probe_age_ms so
      early-read vs stale-cache are not collapsed; premature resend false-negative).

analyze_only. Stdlib only. Run: python3 false_green_shapes_v0_33.py
"""
from __future__ import annotations
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import false_green_shapes_v0_32 as v32


def s49_naive(r):
    if r.get("exit_code") == 0:
        return "OK"
    if r.get("status") == "ok":
        return "OK"
    if r.get("ok") is True:
        return "OK"
    if r.get("credential_present") is True:
        return "OK"
    return "FAIL"


def s49_struct(r):
    claiming = (
        r.get("exit_code") == 0
        or r.get("status") == "ok"
        or r.get("ok") is True
    )
    if not claiming:
        return "FAIL"
    if "credential_present" not in r:
        return "UNKNOWN/CREDENTIAL_PRESENT_UNDECLARED"
    present = r.get("credential_present")
    if present is False:
        return "FAIL/CREDENTIAL_MISSING"
    if present is not True:
        return "UNKNOWN/CREDENTIAL_PRESENT_NOT_BOOL"
    if "expected_hash" not in r:
        return "UNKNOWN/EXPECTED_HASH_UNDECLARED"
    if "content_hash" not in r:
        return "UNKNOWN/CONTENT_HASH_UNDECLARED"
    exp = r.get("expected_hash")
    got = r.get("content_hash")
    if not isinstance(exp, str) or not isinstance(got, str):
        return "UNKNOWN/HASH_NOT_STR"
    if got != exp:
        return "FAIL/CREDENTIAL_HASH_MISMATCH"
    return "OK"


def s50_naive(r):
    if r.get("status") == "ok":
        return "OK"
    if r.get("ok") is True:
        return "OK"
    if r.get("probe_delta") == 0:
        return "OK"
    if r.get("claimed_resend_ok") is True:
        return "OK"
    return "FAIL"


def s50_struct(r):
    claiming = (
        r.get("status") == "ok"
        or r.get("ok") is True
        or r.get("claimed_resend_ok") is True
        or r.get("not_landed") is True
    )
    if not claiming:
        return "FAIL"
    for k in ("probe_delta", "probe_age_ms", "min_batch_period_ms"):
        if k not in r:
            return f"UNKNOWN/{k.upper()}_UNDECLARED"
    try:
        delta = int(r["probe_delta"])
        age = int(r["probe_age_ms"])
        period = int(r["min_batch_period_ms"])
    except (TypeError, ValueError):
        return "UNKNOWN/PROBE_FIELDS_NOT_INT"
    if period <= 0:
        return "UNKNOWN/MIN_BATCH_PERIOD_INVALID"
    if delta > 0:
        # object appeared; treating as resend-justified is a duplicate hazard
        if r.get("claimed_resend_ok") is True or r.get("not_landed") is True:
            return "FAIL/PROBE_ALREADY_LANDED"
        return "OK"
    # delta == 0 (or negative treated as empty)
    if age < period:
        return "FAIL/PROBE_TOO_EARLY_RESEND"
    return "OK"


NEW_ROWS = [
  ("S49-mf-half-write-hash", "S49", "observed_shape_desensitized(W君)",
   {"arm": "present_but_torn_write",
    "credential_present": True,
    "expected_hash": "abc111",
    "content_hash": "abc11",  # truncated / half-write
    "exit_code": 0, "status": "ok"},
   "FAIL/CREDENTIAL_HASH_MISMATCH", True),
  ("S49-mf-missing-cred", "S49", "hand_built",
   {"credential_present": False, "status": "ok", "exit_code": 0},
   "FAIL/CREDENTIAL_MISSING", True),
  ("S49-gt-hash-match", "S49", "hand_built",
   {"credential_present": True, "expected_hash": "deadbeef",
    "content_hash": "deadbeef", "status": "ok", "exit_code": 0},
   "OK", False),
  ("S49-ct-hash-undeclared", "S49", "observed_shape_desensitized(W君)",
   {"credential_present": True, "status": "ok", "exit_code": 0},
   "UNKNOWN/EXPECTED_HASH_UNDECLARED", True),
  ("S49-ct-present-undeclared", "S49", "hand_built",
   {"status": "ok", "exit_code": 0, "expected_hash": "x", "content_hash": "x"},
   "UNKNOWN/CREDENTIAL_PRESENT_UNDECLARED", True),
  ("S50-mf-too-early-resend", "S50", "observed_shape_desensitized(WorkBuddy)",
   {"arm": "probe_age_below_batch_period",
    "probe_delta": 0, "probe_age_ms": 1200, "min_batch_period_ms": 5000,
    "claimed_resend_ok": True, "not_landed": True, "status": "ok"},
   "FAIL/PROBE_TOO_EARLY_RESEND", True),
  ("S50-mf-already-landed", "S50", "hand_built",
   {"probe_delta": 4, "probe_age_ms": 8000, "min_batch_period_ms": 5000,
    "claimed_resend_ok": True, "status": "ok"},
   "FAIL/PROBE_ALREADY_LANDED", True),
  ("S50-gt-waited-still-empty", "S50", "hand_built",
   {"probe_delta": 0, "probe_age_ms": 6000, "min_batch_period_ms": 5000,
    "claimed_resend_ok": True, "not_landed": True, "status": "ok"},
   "OK", False),
  ("S50-gt-landed-no-resend", "S50", "observed_shape_desensitized(WorkBuddy)",
   {"probe_delta": 4, "probe_age_ms": 3000, "min_batch_period_ms": 5000,
    "status": "ok", "ok": True},
   "OK", False),
  ("S50-ct-age-undeclared", "S50", "hand_built",
   {"probe_delta": 0, "claimed_resend_ok": True, "status": "ok"},
   "UNKNOWN/PROBE_AGE_MS_UNDECLARED", True),
]

FNS = dict(v32.FNS)
FNS.update({"S49": (s49_naive, s49_struct), "S50": (s50_naive, s50_struct)})
ROWS = list(v32.ROWS) + NEW_ROWS
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
    new_wrong = sum(1 for r in out if r["shape"] in ("S49", "S50") and r["naive"] != r["expected"])
    res = {"fixture": "FALSE_GREEN_SHAPES", "version": "0.33", "selftest": f"{ok}/{total}",
           "naive_wrong_rows": naive_wrong, "naive_wrong_new_shapes": f"{new_wrong}/{len(NEW_ROWS)}",
           "naive_forced_verdicts_on_cant_tell": forced, "forced_verdict_control": ctl, "rows": out}
    json.dump(res, open("run_out_v0_33.json", "w"), ensure_ascii=False, indent=1)
    print(f"selftest {ok}/{total}; naive wrong {naive_wrong}/{len(ROWS)} (new shapes {new_wrong}/{len(NEW_ROWS)}); forced verdicts on can't-tell {forced}/{len(ct)}")
    for r in out:
        if not r["pass"]:
            print("FAIL_ROW", r)
    return 0 if ok == total else 1

if __name__ == "__main__":
    raise SystemExit(main())
