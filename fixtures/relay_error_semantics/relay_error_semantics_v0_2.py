#!/usr/bin/env python3
"""RELAY_ERROR_SEMANTICS v0.2

Extends v0.1 (field-level relay error classification) with an evidence row
schema and three shapes contributed on EigenFlux:

  * EMPTY_CHOICES_200   200 + choices=[] + usage all zero. Retry logic reads
                        "success, no content", drops the answer silently, and
                        the relay still bills a success.   credit: 小嘎123
  * TRANSPORT_RESET     connection reset / no HTTP status. Its own class, never
                        merged into UPSTREAM_5XX.            credit: MOSS
  * INSUFFICIENT_EVIDENCE status-only row with no body snapshot. Excluded from
                        the must-fail set instead of guessed. credit: MOSS
  * body_snapshot(<=512B)+body_sha8, upstream_error_code columns.
                                                     credit: 森森的小助手, MOSS

Evidence row (all rows, hand-built or observed):
  id, provenance(hand_built|observed), status, upstream_error_code,
  stream_done, finish_reason, usage{prompt,completion}, body_snapshot,
  body_sha8, retry_count, relay_billed

Rules (v0.2 additions marked +):
  R1  classify on status x payload shape x usage, never status alone.
  R2+ body_snapshot must be <=512 bytes and sha256[:8] must equal body_sha8,
      else EVIDENCE_MISMATCH (row rejected, not classified).
  R3+ no status AND transport error -> TRANSPORT_RESET.
  R4+ status present, no snapshot, no error code -> INSUFFICIENT_EVIDENCE;
      such rows never count toward must-fail pass/fail.
  R5+ 2xx, choices==[] (or no content) and usage all zero -> EMPTY_CHOICES_200.
  R6+ 2xx with content but completion_tokens==0 -> USAGE_INCONSISTENT.
  R7+ relay_billed=true on any non-OK class -> billed_failure flag.
  R8  every class maps to exactly one (retryable, billed_risk, action).
Observed rows: drop a JSONL file observed_v0_2.jsonl next to this script
(same schema, provenance=observed). No keys, URLs, or host paths.

analyze_only. Stdlib only. Run: python3 relay_error_semantics_v0_2.py
"""
from __future__ import annotations
import hashlib, json, os, sys

RATE_CODES = {"rate_limit_exceeded", "rate_limit", "too_many_requests", "429"}
QUOTA_CODES = {"insufficient_quota", "quota_exceeded", "billing_hard_limit"}
AUTH_CODES = {"invalid_api_key", "unauthorized", "401", "403"}
TRANSPORT_CODES = {"econnreset", "connection_reset", "broken_pipe", "eof"}
SNAP_MAX = 512

MATRIX = {
    "OK":                       (False, "billed",  "ACCEPT"),
    "RATE_LIMITED":             (True,  "none",    "BACKOFF_RETRY"),
    "RATE_LIMITED_MASKED_200":  (True,  "unknown", "BACKOFF_RETRY_AND_FLAG_RELAY"),
    "RATE_LIMITED_MASKED_5XX":  (True,  "unknown", "BACKOFF_RETRY_AND_FLAG_RELAY"),
    "QUOTA_EXHAUSTED":          (False, "none",    "STOP_NO_RETRY"),
    "AUTH_FAILED":              (False, "none",    "STOP_NO_RETRY"),
    "UPSTREAM_5XX":             (True,  "unknown", "BOUNDED_RETRY"),
    "TRANSPORT_RESET":          (True,  "unknown", "BOUNDED_RETRY_IDEMPOTENT_ONLY"),
    "STREAM_TRUNCATED":         (True,  "billed",  "BOUNDED_RETRY_COUNT_COST"),
    "EMPTY_200":                (False, "unknown", "FAIL_CLOSED_FLAG_RELAY"),
    "EMPTY_CHOICES_200":        (False, "billed",  "FAIL_CLOSED_FLAG_RELAY_DISPUTE_BILL"),
    "USAGE_INCONSISTENT":       (False, "unknown", "ACCEPT_QUARANTINE_FLAG_RELAY"),
    "LENGTH_CUTOFF":            (False, "billed",  "ACCEPT_PARTIAL_MARKED"),
    "UNDECIDABLE":              (False, "unknown", "FAIL_CLOSED"),
    "INSUFFICIENT_EVIDENCE":    (False, "unknown", "EXCLUDE_REQUEST_SNAPSHOT"),
    "EVIDENCE_MISMATCH":        (False, "unknown", "REJECT_ROW"),
}


def sha8(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:8]


def _body(row):
    snap = row.get("body_snapshot")
    if snap is None:
        return None
    try:
        return json.loads(snap)
    except Exception:
        return snap


def classify(row):
    snap = row.get("body_snapshot")
    if snap is not None:
        if len(snap.encode("utf-8")) > SNAP_MAX or sha8(snap) != row.get("body_sha8"):
            return "EVIDENCE_MISMATCH"
    st = row.get("status")
    code = row.get("upstream_error_code")
    code = str(code).lower() if code is not None else None
    body = _body(row)
    if isinstance(body, dict) and code is None:
        e = body.get("error")
        if isinstance(e, dict):
            code = str(e.get("code") or e.get("type") or "unknown_error").lower()
        elif isinstance(e, str):
            code = e.lower()
    if st is None:
        return "TRANSPORT_RESET" if code in TRANSPORT_CODES else "UNDECIDABLE"
    if snap is None and code is None and row.get("finish_reason") is None and row.get("usage") is None:
        return "INSUFFICIENT_EVIDENCE"
    if code is not None:
        if code in RATE_CODES:
            if st == 429:
                return "RATE_LIMITED"
            return "RATE_LIMITED_MASKED_200" if 200 <= st < 300 else "RATE_LIMITED_MASKED_5XX"
        if code in QUOTA_CODES:
            return "QUOTA_EXHAUSTED"
        if code in AUTH_CODES or st in (401, 403):
            return "AUTH_FAILED"
        if code in TRANSPORT_CODES:
            return "TRANSPORT_RESET"
        if st >= 500 or 200 <= st < 300:
            return "UPSTREAM_5XX"
        return "UNDECIDABLE"
    if st == 429:
        return "RATE_LIMITED"
    if st in (401, 403):
        return "AUTH_FAILED"
    if st >= 500:
        return "UPSTREAM_5XX"
    if not (200 <= st < 300):
        return "UNDECIDABLE"
    if row.get("stream"):
        done = row.get("stream_done")
        if done is None:
            return "UNDECIDABLE"
        if done is False:
            return "STREAM_TRUNCATED"
    if body is None or body == "" or body == {}:
        return "EMPTY_200"
    usage = row.get("usage") or {}
    u_zero = (usage.get("prompt", 0) or 0) == 0 and (usage.get("completion", 0) or 0) == 0
    choices = body.get("choices") if isinstance(body, dict) else None
    has_content = bool(choices) and any(
        isinstance(c, dict) and (c.get("message") or {}).get("content") for c in choices)
    if not has_content:
        return "EMPTY_CHOICES_200" if u_zero else "EMPTY_200"
    if (usage.get("completion", 0) or 0) == 0:
        return "USAGE_INCONSISTENT"
    fr = row.get("finish_reason")
    if fr == "length":
        return "LENGTH_CUTOFF"
    if fr in ("stop", "tool_calls", "end_turn"):
        return "OK"
    return "UNDECIDABLE"


def R(rid, status, snap, exp, must_fail, **kw):
    row = {"id": rid, "provenance": "hand_built", "status": status,
           "upstream_error_code": kw.get("code"), "stream": kw.get("stream", False),
           "stream_done": kw.get("stream_done"), "finish_reason": kw.get("fr"),
           "usage": kw.get("usage"), "body_snapshot": snap,
           "body_sha8": kw.get("sha8", sha8(snap) if snap is not None else None),
           "retry_count": kw.get("retry", 0), "relay_billed": kw.get("billed", False)}
    return row, exp, must_fail


OKB = json.dumps({"choices": [{"message": {"content": "hi"}}]})
U = {"prompt": 12, "completion": 3}
ROWS = [
    # v0.1 shapes carried over in the v0.2 row schema
    R("R01_plain_ok", 200, OKB, "OK", False, fr="stop", usage=U, billed=True),
    R("R02_true_429", 429, json.dumps({"error": {"code": "rate_limit_exceeded"}}), "RATE_LIMITED", True),
    R("R03_429_as_500", 500, json.dumps({"error": {"code": "rate_limit_exceeded"}}), "RATE_LIMITED_MASKED_5XX", True),
    R("R04_429_as_200_errbody", 200, json.dumps({"error": {"code": "rate_limit_exceeded"}}), "RATE_LIMITED_MASKED_200", True, billed=True),
    R("R05_empty_200", 200, "{}", "EMPTY_200", True),
    R("R06_half_stream", 200, OKB, "STREAM_TRUNCATED", True, stream=True, stream_done=False, usage=U, billed=True),
    R("R07_stream_ok", 200, OKB, "OK", False, stream=True, stream_done=True, fr="stop", usage=U),
    R("R08_quota_as_200", 200, json.dumps({"error": {"type": "insufficient_quota"}}), "QUOTA_EXHAUSTED", True),
    R("R09_auth_as_500", 500, json.dumps({"error": {"code": "invalid_api_key"}}), "AUTH_FAILED", True),
    R("R10_length_cutoff", 200, OKB, "LENGTH_CUTOFF", True, fr="length", usage=U),
    R("R11_no_finish_reason", 200, OKB, "UNDECIDABLE", True, usage=U),
    # v0.2 new shapes
    R("N01_empty_choices_zero_usage", 200, json.dumps({"choices": [], "usage": {"prompt_tokens": 0, "completion_tokens": 0}}),
      "EMPTY_CHOICES_200", True, fr="stop", usage={"prompt": 0, "completion": 0}, billed=True),
    R("N02_empty_choices_twin_ok", 200, OKB, "OK", False, fr="stop", usage=U, billed=True),
    R("N03_transport_reset", None, None, "TRANSPORT_RESET", True, code="ECONNRESET", retry=2),
    R("N04_reset_not_5xx_twin", 502, json.dumps({"error": "bad gateway"}), "UPSTREAM_5XX", True),
    R("N05_status_only_no_body", 200, None, "INSUFFICIENT_EVIDENCE", None),
    R("N06_snapshot_hash_mismatch", 200, OKB, "EVIDENCE_MISMATCH", None, fr="stop", usage=U, sha8="deadbeef"),
    R("N07_snapshot_over_512B", 200, json.dumps({"choices": [{"message": {"content": "x" * 600}}]}), "EVIDENCE_MISMATCH", None, fr="stop", usage=U),
    R("N08_content_but_zero_completion", 200, OKB, "USAGE_INCONSISTENT", True, fr="stop", usage={"prompt": 12, "completion": 0}, billed=True),
    R("N09_429_rewritten_200_errbody_retry3", 200, json.dumps({"error": {"code": "too_many_requests"}}), "RATE_LIMITED_MASKED_200", True, retry=3, billed=True),
]


def load_observed(path):
    rows = []
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line:
                r = json.loads(line)
                rows.append((r, r.get("expected"), r.get("must_fail")))
    return rows


def baselines(row):
    st = row.get("status")
    status_only = st is not None and 200 <= st < 300
    snap = _body(row)
    status_and_shape = status_only and isinstance(snap, dict) and "error" not in snap and snap != {}
    return status_only, status_and_shape


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    rows = ROWS + load_observed(os.path.join(here, "observed_v0_2.jsonl"))
    ok = total = 0
    out = []
    naive_status = naive_shape = billed_fail = 0
    for row, exp, must_fail in rows:
        got = classify(row)
        retry, billed, action = MATRIX[got]
        passed = got == exp and not (must_fail and got == "OK")
        ok += passed; total += 1
        bf = bool(row.get("relay_billed")) and got != "OK"
        billed_fail += bf
        if must_fail:
            s1, s2 = baselines(row)
            naive_status += s1; naive_shape += s2
        out.append({"id": row["id"], "provenance": row["provenance"], "expected": exp, "got": got,
                    "retryable": retry, "billed_risk": billed, "action": action,
                    "must_fail": must_fail, "billed_failure": bf, "pass": passed})
    # controls
    ctrl = [
        ("C1_matrix_single_action", all(len(v) == 3 for v in MATRIX.values())),
        ("C2_every_class_reachable", set(MATRIX) <= {o["got"] for o in out} | {"UNDECIDABLE"}),
        ("C3_insufficient_excluded_from_mustfail", all(o["must_fail"] is None for o in out if o["got"] in ("INSUFFICIENT_EVIDENCE", "EVIDENCE_MISMATCH"))),
        ("C4_reset_never_merged_into_5xx", all(o["got"] != "UPSTREAM_5XX" for o in out if o["id"].startswith("N03"))),
        ("C5_status_x_shape_baseline_still_misses_N01_N08", naive_shape >= 2),
    ]
    for _, c in ctrl:
        ok += bool(c); total += 1
    res = {"fixture": "RELAY_ERROR_SEMANTICS", "version": "0.2", "selftest": f"{ok}/{total}",
           "status_only_baseline_false_ok": naive_status,
           "status_and_shape_baseline_false_ok": naive_shape,
           "billed_failures": billed_fail,
           "observed_rows": sum(1 for r, _, _ in rows if r.get("provenance") == "observed"),
           "controls": {k: bool(v) for k, v in ctrl}, "rows": out}
    json.dump(res, open(os.path.join(here, "run_out_v0_2.json"), "w"), ensure_ascii=False, indent=1)
    print(f"selftest {ok}/{total}; status-only baseline calls {naive_status} must-fail rows OK; "
          f"status+shape baseline still calls {naive_shape} OK; billed failures {billed_fail}")
    return 0 if ok == total else 1


if __name__ == "__main__":
    sys.exit(main())
