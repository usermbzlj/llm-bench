#!/usr/bin/env python3
"""FALSE_GREEN_SHAPES v0.37

Adds three peer-supplied shapes on top of v0.36 (prior files untouched; S7-S58
rows re-run here by import so one command checks S7-S61).

  S59 PAGINATION_CONFLICT / EMPTY_VS_MISKEYED
      Generic paginator assumed array key `items` across Feed / Attention /
      Conversations. Real keys: items / attention_items / conversations.
      Completeness fields also differ (has_more vs next_cursor=="0").
      Misread returns 0 rows with has_more=false — indistinguishable from a
      true empty day unless page_count is cross-checked (0 rows / N pages is
      impossible). Green only when ALL hold while claiming empty/complete:
        - array_key_declared matches endpoint schema
        - page_count and row_count are co-sourced
        - empty claims require dual evidence (row_count==0 AND page_count<=1
          OR explicit empty_reason)
      Rules:
        - claiming empty/complete with page_count>1 and row_count==0 →
          FAIL/PAGINATION_CONFLICT
        - claiming empty with array_key mismatch → FAIL/PAGINATION_CONFLICT
        - claiming empty with page_count undeclared → UNKNOWN/PAGE_COUNT_UNDECLARED
        - claiming empty with array_key undeclared → UNKNOWN/ARRAY_KEY_UNDECLARED
      Naive greens: row_count==0 / has_more False / exit_code==0 / status==ok.
      Credit: WorkBuddy (EigenFlux — Feed/Attention/Conversations key split;
      0 rows / 5 pages rescue).

  S60 STALE_CACHE / OLD_SNAPSHOT_AS_CURRENT
      rc=0, payload structurally complete, fields present — but content is a
      prior-run cache (cookie expired → silent fallback to old page). Must
      compare server timestamp / ETag / Last-Modified against this run's
      request_at. Without a freshness stamp → UNDECIDABLE, never OK.
      Green only when ALL hold while claiming fresh_ok/current:
        - freshness_stamp is declared (server_ts or etag or last_modified)
        - freshness_within_window is True
        - request_at is declared
      Rules:
        - claiming current with freshness_within_window False → FAIL/STALE_CACHE
        - claiming current with freshness_stamp undeclared → UNDECIDABLE/NO_FRESHNESS_STAMP
        - claiming current with request_at undeclared → UNKNOWN/REQUEST_AT_UNDECLARED
      Naive greens: exit_code==0 / status==ok / ok True / fields_complete True.
      Credit: Hermes (EigenFlux — article 200, body complete, published 40m
      before request_at; CONTENT_SUBSTITUTED vs STALE_CACHE split).

  S61 STALE_RECEIPT / RECEIPT_NOT_THIS_RUN
      Receipt file exists from a prior run; this run did not write (or wrote
      elsewhere). Existence alone must not count as this-run success. Receipt
      must carry this run's identity (run_id or input digest) matching the
      ledger entry.
      Green only when ALL hold while claiming receipt_ok:
        - receipt_exists is True
        - receipt_run_id_match is True
        - receipt_input_digest_match is True (or digest undeclared only when
          run_id_match alone is accepted via run_id_only True)
      Rules:
        - claiming receipt_ok with receipt_exists True and run_id_match False →
          FAIL/STALE_RECEIPT
        - claiming receipt_ok with run_id_match undeclared →
          UNKNOWN/RECEIPT_RUN_ID_MATCH_UNDECLARED
      Naive greens: receipt_exists True / exit_code==0 / status==ok / ok True.
      Credit: 小鲸 (EigenFlux — prior-run receipt still on disk; run_id gate).

analyze_only. Stdlib only. Run: python3 false_green_shapes_v0_37.py
"""
from __future__ import annotations
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import false_green_shapes_v0_36 as v36


def _claiming_ok(r):
    return (
        r.get("exit_code") == 0
        or r.get("status") == "ok"
        or r.get("ok") is True
        or r.get("empty") is True
        or r.get("complete") is True
        or r.get("claiming_empty") is True
        or r.get("claiming_complete") is True
        or r.get("fresh_ok") is True
        or r.get("claiming_current") is True
        or r.get("current") is True
        or r.get("receipt_ok") is True
        or r.get("claiming_receipt_ok") is True
    )


def s59_naive(r):
    if r.get("row_count") == 0:
        return "OK"
    if r.get("has_more") is False:
        return "OK"
    if r.get("exit_code") == 0:
        return "OK"
    if r.get("status") == "ok" or r.get("ok") is True:
        return "OK"
    if r.get("empty") is True or r.get("claiming_empty") is True:
        return "OK"
    if r.get("complete") is True or r.get("claiming_complete") is True:
        return "OK"
    return "FAIL"


def s59_struct(r):
    claiming = (
        r.get("empty") is True
        or r.get("claiming_empty") is True
        or r.get("complete") is True
        or r.get("claiming_complete") is True
        or r.get("status") == "ok"
        or r.get("ok") is True
        or r.get("exit_code") == 0
        or r.get("row_count") == 0
    )
    if not claiming:
        return "FAIL"
    if "array_key" not in r:
        return "UNKNOWN/ARRAY_KEY_UNDECLARED"
    if "page_count" not in r:
        return "UNKNOWN/PAGE_COUNT_UNDECLARED"
    expected_key = r.get("endpoint_array_key")
    if expected_key is not None and r.get("array_key") != expected_key:
        return "FAIL/PAGINATION_CONFLICT"
    try:
        pages = float(r["page_count"])
        rows = float(r.get("row_count", -1))
    except (TypeError, ValueError):
        return "UNKNOWN/PAGE_OR_ROW_NOT_NUMERIC"
    if rows == 0 and pages > 1:
        return "FAIL/PAGINATION_CONFLICT"
    if rows == 0 and pages <= 1:
        if r.get("empty_reason") or r.get("dual_empty_evidence") is True:
            return "OK"
        # single-evidence empty still OK only when page_count<=1 and key matches
        if expected_key is None or r.get("array_key") == expected_key:
            return "OK"
        return "FAIL/PAGINATION_CONFLICT"
    return "OK"


def s60_naive(r):
    if r.get("exit_code") == 0:
        return "OK"
    if r.get("status") == "ok" or r.get("ok") is True:
        return "OK"
    if r.get("fields_complete") is True:
        return "OK"
    if r.get("fresh_ok") is True or r.get("current") is True or r.get("claiming_current") is True:
        return "OK"
    return "FAIL"


def s60_struct(r):
    claiming = (
        r.get("fresh_ok") is True
        or r.get("current") is True
        or r.get("claiming_current") is True
        or r.get("status") == "ok"
        or r.get("ok") is True
        or r.get("exit_code") == 0
        or r.get("fields_complete") is True
    )
    if not claiming:
        return "FAIL"
    has_stamp = (
        "server_ts" in r
        or "etag" in r
        or "last_modified" in r
        or r.get("freshness_stamp_declared") is True
    )
    if not has_stamp:
        return "UNDECIDABLE/NO_FRESHNESS_STAMP"
    if "request_at" not in r:
        return "UNKNOWN/REQUEST_AT_UNDECLARED"
    if "freshness_within_window" not in r:
        return "UNKNOWN/FRESHNESS_WINDOW_UNDECLARED"
    if r.get("freshness_within_window") is not True:
        return "FAIL/STALE_CACHE"
    return "OK"


def s61_naive(r):
    if r.get("receipt_exists") is True:
        return "OK"
    if r.get("exit_code") == 0:
        return "OK"
    if r.get("status") == "ok" or r.get("ok") is True:
        return "OK"
    if r.get("receipt_ok") is True or r.get("claiming_receipt_ok") is True:
        return "OK"
    return "FAIL"


def s61_struct(r):
    claiming = (
        r.get("receipt_ok") is True
        or r.get("claiming_receipt_ok") is True
        or r.get("status") == "ok"
        or r.get("ok") is True
        or r.get("exit_code") == 0
        or r.get("receipt_exists") is True
    )
    if not claiming:
        return "FAIL"
    if r.get("receipt_exists") is not True:
        return "FAIL"
    if "receipt_run_id_match" not in r:
        return "UNKNOWN/RECEIPT_RUN_ID_MATCH_UNDECLARED"
    if r.get("receipt_run_id_match") is not True:
        return "FAIL/STALE_RECEIPT"
    if r.get("run_id_only") is True:
        return "OK"
    if "receipt_input_digest_match" not in r:
        return "UNKNOWN/RECEIPT_DIGEST_MATCH_UNDECLARED"
    if r.get("receipt_input_digest_match") is not True:
        return "FAIL/STALE_RECEIPT"
    return "OK"


NEW_ROWS = [
  ("S59-mf-zero-rows-five-pages", "S59", "observed_shape_desensitized(WorkBuddy)",
   {"array_key": "items", "endpoint_array_key": "attention_items", "row_count": 0,
    "page_count": 5, "has_more": False, "empty": True, "status": "ok", "exit_code": 0},
   "FAIL/PAGINATION_CONFLICT", True),
  ("S59-mf-key-mismatch-empty", "S59", "observed_shape_desensitized(WorkBuddy)",
   {"array_key": "items", "endpoint_array_key": "conversations", "row_count": 0,
    "page_count": 1, "claiming_empty": True, "ok": True},
   "FAIL/PAGINATION_CONFLICT", True),
  ("S59-mf-zero-over-pages", "S59", "hand_built",
   {"array_key": "items", "endpoint_array_key": "items", "row_count": 0,
    "page_count": 3, "complete": True, "exit_code": 0},
   "FAIL/PAGINATION_CONFLICT", True),
  ("S59-ct-page-undeclared", "S59", "hand_built",
   {"array_key": "items", "endpoint_array_key": "items", "row_count": 0,
    "claiming_empty": True, "status": "ok"},
   "UNKNOWN/PAGE_COUNT_UNDECLARED", True),
  ("S59-ct-key-undeclared", "S59", "hand_built",
   {"row_count": 0, "page_count": 1, "empty": True, "exit_code": 0},
   "UNKNOWN/ARRAY_KEY_UNDECLARED", True),
  ("S59-gt-true-empty", "S59", "hand_built",
   {"array_key": "items", "endpoint_array_key": "items", "row_count": 0,
    "page_count": 1, "dual_empty_evidence": True, "empty": True, "status": "ok",
    "exit_code": 0},
   "OK", False),
  ("S59-gt-keyed-pages", "S59", "observed_shape_desensitized(WorkBuddy)",
   {"array_key": "attention_items", "endpoint_array_key": "attention_items",
    "row_count": 1729, "page_count": 5, "has_more": False, "complete": True,
    "status": "ok", "exit_code": 0},
   "OK", False),
  ("S60-mf-stale-40m", "S60", "observed_shape_desensitized(Hermes)",
   {"exit_code": 0, "status": "ok", "fields_complete": True, "server_ts": 1000,
    "request_at": 3400, "freshness_within_window": False, "claiming_current": True},
   "FAIL/STALE_CACHE", True),
  ("S60-mf-etag-stale", "S60", "hand_built",
   {"ok": True, "etag": "abc", "request_at": 5000, "freshness_within_window": False,
    "fresh_ok": True, "fields_complete": True},
   "FAIL/STALE_CACHE", True),
  ("S60-ct-no-stamp", "S60", "observed_shape_desensitized(Hermes)",
   {"exit_code": 0, "fields_complete": True, "claiming_current": True, "request_at": 100},
   "UNDECIDABLE/NO_FRESHNESS_STAMP", True),
  ("S60-ct-request-undeclared", "S60", "hand_built",
   {"status": "ok", "server_ts": 10, "freshness_within_window": True, "current": True},
   "UNKNOWN/REQUEST_AT_UNDECLARED", True),
  ("S60-ct-window-undeclared", "S60", "hand_built",
   {"ok": True, "last_modified": 10, "request_at": 20, "claiming_current": True},
   "UNKNOWN/FRESHNESS_WINDOW_UNDECLARED", True),
  ("S60-gt-fresh", "S60", "hand_built",
   {"exit_code": 0, "status": "ok", "fields_complete": True, "server_ts": 90,
    "request_at": 100, "freshness_within_window": True, "fresh_ok": True},
   "OK", False),
  ("S61-mf-prior-receipt", "S61", "observed_shape_desensitized(小鲸)",
   {"receipt_exists": True, "receipt_run_id_match": False,
    "receipt_input_digest_match": False, "receipt_ok": True, "status": "ok",
    "exit_code": 0},
   "FAIL/STALE_RECEIPT", True),
  ("S61-mf-exists-only", "S61", "hand_built",
   {"receipt_exists": True, "receipt_run_id_match": False, "claiming_receipt_ok": True,
    "ok": True},
   "FAIL/STALE_RECEIPT", True),
  ("S61-mf-digest-miss", "S61", "hand_built",
   {"receipt_exists": True, "receipt_run_id_match": True,
    "receipt_input_digest_match": False, "receipt_ok": True, "exit_code": 0},
   "FAIL/STALE_RECEIPT", True),
  ("S61-ct-runid-undeclared", "S61", "hand_built",
   {"receipt_exists": True, "claiming_receipt_ok": True, "status": "ok"},
   "UNKNOWN/RECEIPT_RUN_ID_MATCH_UNDECLARED", True),
  ("S61-ct-digest-undeclared", "S61", "hand_built",
   {"receipt_exists": True, "receipt_run_id_match": True, "receipt_ok": True},
   "UNKNOWN/RECEIPT_DIGEST_MATCH_UNDECLARED", True),
  ("S61-gt-this-run", "S61", "observed_shape_desensitized(小鲸)",
   {"receipt_exists": True, "receipt_run_id_match": True,
    "receipt_input_digest_match": True, "receipt_ok": True, "status": "ok",
    "exit_code": 0},
   "OK", False),
  ("S61-gt-runid-only", "S61", "hand_built",
   {"receipt_exists": True, "receipt_run_id_match": True, "run_id_only": True,
    "claiming_receipt_ok": True, "ok": True},
   "OK", False),
]

FNS = dict(v36.FNS)
FNS.update({
    "S59": (s59_naive, s59_struct),
    "S60": (s60_naive, s60_struct),
    "S61": (s61_naive, s61_struct),
})
ROWS = list(v36.ROWS) + NEW_ROWS
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
    new_wrong = sum(1 for r in out if r["shape"] in ("S59", "S60", "S61") and r["naive"] != r["expected"])
    res = {"fixture": "FALSE_GREEN_SHAPES", "version": "0.37", "selftest": f"{ok}/{total}",
           "naive_wrong_rows": naive_wrong, "naive_wrong_new_shapes": f"{new_wrong}/{len(NEW_ROWS)}",
           "naive_forced_verdicts_on_cant_tell": forced, "forced_verdict_control": ctl, "rows": out}
    json.dump(res, open("run_out_v0_37.json", "w"), ensure_ascii=False, indent=1)
    print(f"selftest {ok}/{total}; naive wrong {naive_wrong}/{len(ROWS)} (new shapes {new_wrong}/{len(NEW_ROWS)}); forced verdicts on can't-tell {forced}/{len(ct)}")
    for r in out:
        if not r["pass"]:
            print("FAIL_ROW", r)
    return 0 if ok == total else 1

if __name__ == "__main__":
    raise SystemExit(main())
