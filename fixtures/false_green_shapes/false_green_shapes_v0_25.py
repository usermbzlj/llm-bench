#!/usr/bin/env python3
"""FALSE_GREEN_SHAPES v0.25

Adds one peer-supplied shape on top of v0.24 (prior files untouched; S7-S36
rows re-run here by import so one command checks S7-S37).

  S37 NON_IDEMPOTENT_REPLAY  Retry/backfill paths that assume "same key =
                              overwrite" must not green-wash when the API is
                              actually append-once-per-call. Naive treats
                              (retry_ok OR write_ack OR status==ok OR
                               idempotency_key_present OR backfill_ok OR
                               assumed_overwrite) as OK.
                              Struct:
                                - write_semantics undeclared while retrying ->
                                  UNKNOWN/WRITE_SEMANTICS_UNDECLARED
                                - duplicate_check undeclared after retry ->
                                  UNKNOWN/DEDUP_UNDECLARED
                                - write_semantics==append AND retry/backfill
                                  without dedupe_receipt ->
                                  FAIL/NON_IDEMPOTENT_REPLAY
                                - assumed_overwrite True while semantics are
                                  append -> FAIL/NON_IDEMPOTENT_REPLAY
                                - duplicate_rows_observed True after retry ->
                                  FAIL/NON_IDEMPOTENT_REPLAY
                                - write_semantics==overwrite AND
                                  idempotent_key_verified -> OK
                                - write_semantics==append AND
                                  dedupe_receipt True AND no duplicate rows ->
                                  OK
                              Credit: June (EigenFlux broadcast —
                              响应层超时后整批重发；误以为同键覆盖，
                              实际按次追加；同一署名两行进总分，账面更好看；
                              重试前须实测写入语义，补绿时必须判重复写入).

Each shape: must-fail arm (naive wrong) + green twin.
analyze_only. Stdlib only. Run: python3 false_green_shapes_v0_25.py
"""
from __future__ import annotations
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import false_green_shapes_v0_24 as v24


def s37_naive(r):
    if r.get("retry_ok") is True:
        return "OK"
    if r.get("backfill_ok") is True:
        return "OK"
    if r.get("write_ack") is True:
        return "OK"
    if r.get("status") == "ok":
        return "OK"
    if r.get("idempotency_key_present") is True:
        return "OK"
    if r.get("assumed_overwrite") is True:
        return "OK"
    return "FAIL"


def s37_struct(r):
    retrying = (
        r.get("retry_attempted") is True
        or r.get("backfill_ok") is True
        or r.get("retry_ok") is True
        or r.get("assumed_overwrite") is True
    )

    if retrying and "write_semantics" not in r:
        return "UNKNOWN/WRITE_SEMANTICS_UNDECLARED"

    sem = r.get("write_semantics")

    if retrying and "dedupe_receipt" not in r and "duplicate_rows_observed" not in r:
        if sem != "overwrite" or r.get("idempotent_key_verified") is not True:
            return "UNKNOWN/DEDUP_UNDECLARED"

    if r.get("duplicate_rows_observed") is True:
        return "FAIL/NON_IDEMPOTENT_REPLAY"

    if sem == "append":
        if retrying and r.get("dedupe_receipt") is not True:
            return "FAIL/NON_IDEMPOTENT_REPLAY"
        if r.get("assumed_overwrite") is True:
            return "FAIL/NON_IDEMPOTENT_REPLAY"
        if r.get("dedupe_receipt") is True and r.get("duplicate_rows_observed") is not True:
            return "OK"
        return "FAIL/NON_IDEMPOTENT_REPLAY"

    if sem == "overwrite":
        if r.get("idempotent_key_verified") is True:
            return "OK"
        if retrying and r.get("idempotent_key_verified") is not True:
            return "UNKNOWN/DEDUP_UNDECLARED"
        return "OK"

    if retrying:
        return "UNKNOWN/WRITE_SEMANTICS_UNDECLARED"

    return "FAIL"


NEW_ROWS = [
  ("S37-mf-append-assumed-overwrite", "S37", "observed_shape_desensitized(June)",
   {"retry_attempted": True, "retry_ok": True, "write_ack": True, "status": "ok",
    "assumed_overwrite": True, "write_semantics": "append",
    "idempotency_key_present": True, "duplicate_rows_observed": True,
    "dedupe_receipt": False, "score_inflated": True},
   "FAIL/NON_IDEMPOTENT_REPLAY", True),
  ("S37-mf-append-no-dedupe", "S37", "hand_built",
   {"retry_attempted": True, "backfill_ok": True, "write_semantics": "append",
    "dedupe_receipt": False, "duplicate_rows_observed": False},
   "FAIL/NON_IDEMPOTENT_REPLAY", True),
  ("S37-mf-assumed-overwrite-flag", "S37", "hand_built",
   {"assumed_overwrite": True, "write_semantics": "append",
    "idempotency_key_present": True, "dedupe_receipt": False,
    "duplicate_rows_observed": False},
   "FAIL/NON_IDEMPOTENT_REPLAY", True),
  ("S37-ct-semantics-undeclared", "S37", "hand_built",
   {"retry_attempted": True, "retry_ok": True, "write_ack": True},
   "UNKNOWN/WRITE_SEMANTICS_UNDECLARED", True),
  ("S37-ct-dedup-undeclared", "S37", "hand_built",
   {"retry_attempted": True, "write_semantics": "overwrite",
    "idempotency_key_present": True},
   "UNKNOWN/DEDUP_UNDECLARED", True),
  ("S37-gt-overwrite-verified", "S37", "hand_built",
   {"retry_attempted": True, "write_semantics": "overwrite",
    "idempotent_key_verified": True, "idempotency_key_present": True,
    "write_ack": True, "status": "ok"},
   "OK", False),
  ("S37-gt-append-deduped", "S37", "hand_built",
   {"retry_attempted": True, "write_semantics": "append",
    "dedupe_receipt": True, "duplicate_rows_observed": False,
    "write_ack": True},
   "OK", False),
]


FNS = dict(v24.FNS)
FNS.update({"S37": (s37_naive, s37_struct)})
ROWS = list(v24.ROWS) + NEW_ROWS
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
    new_wrong = sum(1 for r in out if r["shape"] == "S37" and r["naive"] != r["expected"])
    res = {"fixture": "FALSE_GREEN_SHAPES", "version": "0.25", "selftest": f"{ok}/{total}",
           "naive_wrong_rows": naive_wrong, "naive_wrong_new_shapes": f"{new_wrong}/{len(NEW_ROWS)}",
           "naive_forced_verdicts_on_cant_tell": forced, "forced_verdict_control": ctl, "rows": out}
    json.dump(res, open("run_out_v0_25.json", "w"), ensure_ascii=False, indent=1)
    print(f"selftest {ok}/{total}; naive wrong {naive_wrong}/{len(ROWS)} (new shapes {new_wrong}/{len(NEW_ROWS)}); forced verdicts on can't-tell {forced}/{len(ct)}")
    for r in out:
        if not r["pass"]:
            print("FAIL_ROW", r)
    return 0 if ok == total else 1

if __name__ == "__main__":
    raise SystemExit(main())
