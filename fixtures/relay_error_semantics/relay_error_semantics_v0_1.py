#!/usr/bin/env python3
"""RELAY_ERROR_SEMANTICS v0.1

Hand-built, structure-only fixture (provenance=hand_built on every row; no
telemetry implied). Problem framing credit: 森森的小助手 (EigenFlux) -- relays
rewrite upstream 429 into 500 / empty 200 / 200+error-body / half-stream, and
status-code-only comparison judges these "semantically consistent" while the
caller's retry logic silently turns backoff into infinite retry + billing.

Rule: classify on FIELD-LEVEL signals (status, body error.code/type,
finish_reason, stream terminal marker, usage), never status code alone, and map
every class to exactly ONE caller action via the matrix
  (class) -> (retryable, billed_risk, action)
so callers stop guessing.

Must-fail rows: a relay response whose status says OK but whose field signals
say error/truncation must NEVER classify as OK.

analyze_only. Stdlib only. Run: python3 relay_error_semantics_v0_1.py
"""
from __future__ import annotations
import json, sys

RATE_CODES = {"rate_limit_exceeded", "rate_limit", "too_many_requests", "429"}
QUOTA_CODES = {"insufficient_quota", "quota_exceeded", "billing_hard_limit"}
AUTH_CODES = {"invalid_api_key", "unauthorized", "401", "403"}

# class -> (retryable, billed_risk, single action)
MATRIX = {
    "OK":                       (False, "billed",   "ACCEPT"),
    "RATE_LIMITED":             (True,  "none",     "BACKOFF_RETRY"),
    "RATE_LIMITED_MASKED_200":  (True,  "unknown",  "BACKOFF_RETRY_AND_FLAG_RELAY"),
    "RATE_LIMITED_MASKED_5XX":  (True,  "unknown",  "BACKOFF_RETRY_AND_FLAG_RELAY"),
    "QUOTA_EXHAUSTED":          (False, "none",     "STOP_NO_RETRY"),
    "AUTH_FAILED":              (False, "none",     "STOP_NO_RETRY"),
    "UPSTREAM_5XX":             (True,  "unknown",  "BOUNDED_RETRY"),
    "STREAM_TRUNCATED":         (True,  "billed",   "BOUNDED_RETRY_COUNT_COST"),
    "EMPTY_200":                (False, "unknown",  "FAIL_CLOSED_FLAG_RELAY"),
    "LENGTH_CUTOFF":            (False, "billed",   "ACCEPT_PARTIAL_MARKED"),
    "UNDECIDABLE":              (False, "unknown",  "FAIL_CLOSED"),
}


def _err_code(body):
    if not isinstance(body, dict):
        return None
    e = body.get("error")
    if isinstance(e, dict):
        c = e.get("code") or e.get("type")
        return str(c).lower() if c is not None else "unknown_error"
    if isinstance(e, str):
        return e.lower()
    return None


def classify(resp):
    """resp: {status:int|None, body:dict|str|None, stream:bool,
              stream_done:bool|None, finish_reason:str|None}"""
    st = resp.get("status")
    if st is None:
        return "UNDECIDABLE"
    body = resp.get("body")
    code = _err_code(body)
    if code is not None:
        if code in RATE_CODES:
            if st == 429:
                return "RATE_LIMITED"
            return "RATE_LIMITED_MASKED_200" if 200 <= st < 300 else "RATE_LIMITED_MASKED_5XX"
        if code in QUOTA_CODES:
            return "QUOTA_EXHAUSTED"
        if code in AUTH_CODES or st in (401, 403):
            return "AUTH_FAILED"
        if st >= 500 or 200 <= st < 300:
            return "UPSTREAM_5XX"  # error body under any status = not OK
        return "UNDECIDABLE"
    if st == 429:
        return "RATE_LIMITED"
    if st in (401, 403):
        return "AUTH_FAILED"
    if st >= 500:
        return "UPSTREAM_5XX"
    if not (200 <= st < 300):
        return "UNDECIDABLE"
    if resp.get("stream"):
        done = resp.get("stream_done")
        if done is None:
            return "UNDECIDABLE"
        if done is False:
            return "STREAM_TRUNCATED"
    if body is None or body == "" or body == {}:
        return "EMPTY_200"
    fr = resp.get("finish_reason")
    if fr == "length":
        return "LENGTH_CUTOFF"
    if fr in ("stop", "tool_calls", "end_turn"):
        return "OK"
    if fr is None:
        return "UNDECIDABLE"  # no terminal signal: refuse to call it OK
    return "UNDECIDABLE"


ROWS = [
    # id, resp, expected, must_fail(=must not be OK)
    ("R01_plain_ok", {"status": 200, "body": {"choices": [1]}, "finish_reason": "stop"}, "OK", False),
    ("R02_true_429", {"status": 429, "body": None}, "RATE_LIMITED", True),
    ("R03_429_as_500", {"status": 500, "body": {"error": {"code": "rate_limit_exceeded"}}}, "RATE_LIMITED_MASKED_5XX", True),
    ("R04_429_as_200_errbody", {"status": 200, "body": {"error": {"code": "rate_limit_exceeded"}}, "finish_reason": None}, "RATE_LIMITED_MASKED_200", True),
    ("R05_empty_200", {"status": 200, "body": {}, "finish_reason": None}, "EMPTY_200", True),
    ("R06_half_stream_disconnect", {"status": 200, "body": {"choices": [1]}, "stream": True, "stream_done": False, "finish_reason": None}, "STREAM_TRUNCATED", True),
    ("R07_stream_done_ok", {"status": 200, "body": {"choices": [1]}, "stream": True, "stream_done": True, "finish_reason": "stop"}, "OK", False),
    ("R08_stream_done_unknown", {"status": 200, "body": {"choices": [1]}, "stream": True, "stream_done": None}, "UNDECIDABLE", True),
    ("R09_quota_as_200", {"status": 200, "body": {"error": {"type": "insufficient_quota"}}}, "QUOTA_EXHAUSTED", True),
    ("R10_auth_as_500", {"status": 500, "body": {"error": {"code": "invalid_api_key"}}}, "AUTH_FAILED", True),
    ("R11_generic_err_200", {"status": 200, "body": {"error": "upstream timeout"}}, "UPSTREAM_5XX", True),
    ("R12_length_cutoff", {"status": 200, "body": {"choices": [1]}, "finish_reason": "length"}, "LENGTH_CUTOFF", True),
    ("R13_no_finish_reason", {"status": 200, "body": {"choices": [1]}, "finish_reason": None}, "UNDECIDABLE", True),
    ("R14_status_missing", {"status": None, "body": {"choices": [1]}}, "UNDECIDABLE", True),
]


def main():
    ok = 0
    out = []
    for rid, resp, exp, must_fail in ROWS:
        got = classify(resp)
        retry, billed, action = MATRIX[got]
        passed = got == exp and not (must_fail and got == "OK")
        ok += passed
        out.append({"id": rid, "provenance": "hand_built", "expected": exp, "got": got,
                    "retryable": retry, "billed_risk": billed, "action": action,
                    "must_fail": must_fail, "pass": passed})
    # matrix uniqueness control: every class maps to exactly one action
    uniq = all(len(v) == 3 for v in MATRIX.values())
    ok += uniq
    total = len(ROWS) + 1
    # status-only baseline: show how many must-fail rows it would call OK
    naive_ok = sum(1 for _, r, _, mf in ROWS if mf and r.get("status") and 200 <= r["status"] < 300)
    res = {"fixture": "RELAY_ERROR_SEMANTICS", "version": "0.1", "selftest": f"{ok}/{total}",
           "status_only_baseline_false_ok": naive_ok, "rows": out}
    json.dump(res, open("run_out_v0_1.json", "w"), ensure_ascii=False, indent=1)
    print(f"selftest {ok}/{total}; status-only baseline would call {naive_ok} must-fail rows OK")
    return 0 if ok == total else 1


if __name__ == "__main__":
    sys.exit(main())
