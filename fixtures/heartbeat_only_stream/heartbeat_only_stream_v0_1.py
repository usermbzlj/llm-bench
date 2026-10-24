#!/usr/bin/env python3
"""HEARTBEAT_ONLY_STREAM v0.1

Structure from:
  - 派蒙 — heartbeat observability; INCONCLUSIVE as a distinct verdict column
    (not folded into PASS/FAIL); must-fail when silent skip greens
  - Hermes — explicit zero-delta persistence as positive control
    (skip ≠ verified idle)
  - wwwwwlmr的废物龙虾 / Marvis — distinguish zero-error from zero-data;
    plan snapshot + execution report must separate skipped vs unattested

Rules:
  1. A stream that only carries heartbeat/liveness ticks cannot self-attest
     business PASS. Heartbeat presence ≠ work attested.
  2. Explicit zero-delta MUST be persisted (delta_attested=True +
     zero_delta_receipt present). Silent absence of deltas is NOT idle.
  3. Skipped execution (plan said run, executor skipped) must NOT render as
     PASS / idle. Distinct from verified_idle.
  4. Missing heartbeat inside the expected window → STALE_OR_SILENT (FAIL),
     not PASS.
  5. INCONCLUSIVE when heartbeat exists but attestation incomplete; must be
     its own reported_verdict (派蒙口径); must NOT enter pass numerator /
     availability denom.
  6. Must-fail: reporter marks PASS when only heartbeats arrived and business
     stream was never attested (HEARTBEAT_ONLY_FALSE_PASS).
  7. Positive control (Hermes): explicit zero-delta receipt with
     delta_attested=True and window_ok → PASS (VERIFIED_IDLE) allowed.

analyze_only. Stdlib only.
Credit: 派蒙 (structure) + Hermes (zero-delta正控); Grok Bot (impl).
"""
from __future__ import annotations

import hashlib
import json
import sys
from typing import Any


def judge(receipt: dict[str, Any]) -> dict[str, Any]:
    kind = receipt.get("kind")
    reported = receipt.get("reported_verdict")  # PASS|FAIL|INCONCLUSIVE|UNKNOWN
    hb_count = receipt.get("heartbeat_count")
    biz_events = receipt.get("business_event_count")
    delta_attested = bool(receipt.get("delta_attested", False))
    zero_delta_receipt = bool(receipt.get("zero_delta_receipt", False))
    skipped = bool(receipt.get("execution_skipped", False))
    plan_required = bool(receipt.get("plan_required_run", False))
    window_ok = receipt.get("window_ok")  # True|False|None
    hb_missing = bool(receipt.get("heartbeat_missing_in_window", False))
    enter_pass = receipt.get("enter_pass_numerator")
    enter_denom = receipt.get("enter_availability_denom")
    stream_class = receipt.get("stream_class")  # heartbeat_only|mixed|business

    if kind == "heartbeat_only_false_pass":
        # Only heartbeats, no business attestation, reporter says PASS
        if stream_class != "heartbeat_only":
            return {"judge": "FAIL", "reason_code": "NOT_HEARTBEAT_ONLY"}
        if not isinstance(hb_count, int) or hb_count < 1:
            return {"judge": "FAIL", "reason_code": "NO_HEARTBEAT"}
        if isinstance(biz_events, int) and biz_events > 0:
            return {"judge": "FAIL", "reason_code": "HAS_BUSINESS_EVENTS"}
        if delta_attested or zero_delta_receipt:
            return {"judge": "FAIL", "reason_code": "UNEXPECTED_DELTA_ATTEST"}
        if reported == "PASS":
            return {
                "judge": "FAIL",
                "reason_code": "HEARTBEAT_ONLY_FALSE_PASS",
                "detail": {"heartbeat_count": hb_count, "business_event_count": biz_events},
            }
        if reported == "INCONCLUSIVE":
            return {"judge": "PASS", "reason_code": "HEARTBEAT_ONLY_INCONCLUSIVE"}
        return {"judge": "FAIL", "reason_code": "MUST_REPORT_INCONCLUSIVE_OR_FAIL"}

    if kind == "skipped_as_idle":
        # Plan required a run; executor skipped; dashboard greens as idle/PASS
        if not plan_required or not skipped:
            return {"judge": "FAIL", "reason_code": "NOT_SKIPPED_CASE"}
        if reported == "PASS":
            return {
                "judge": "FAIL",
                "reason_code": "SKIP_AS_IDLE_FALSE_PASS",
                "detail": {"plan_required_run": plan_required, "execution_skipped": skipped},
            }
        if reported in ("FAIL", "INCONCLUSIVE"):
            return {"judge": "PASS", "reason_code": "SKIP_NOT_IDLE"}
        return {"judge": "FAIL", "reason_code": "MUST_FLAG_SKIP"}

    if kind == "verified_idle_zero_delta":
        # Hermes正控: explicit zero-delta persisted + window ok
        if not delta_attested or not zero_delta_receipt:
            return {"judge": "FAIL", "reason_code": "ZERO_DELTA_NOT_ATTESTED"}
        if window_ok is not True:
            return {"judge": "FAIL", "reason_code": "WINDOW_NOT_OK"}
        if skipped:
            return {"judge": "FAIL", "reason_code": "SKIP_NOT_VERIFIED_IDLE"}
        if reported == "PASS":
            return {"judge": "PASS", "reason_code": "VERIFIED_IDLE"}
        return {"judge": "FAIL", "reason_code": "VERIFIED_IDLE_SHOULD_PASS"}

    if kind == "stale_silent":
        # Heartbeat missing inside expected window → must FAIL STALE, not PASS
        if not hb_missing:
            return {"judge": "FAIL", "reason_code": "NOT_MISSING_HB"}
        if window_ok is not False:
            return {"judge": "FAIL", "reason_code": "WINDOW_SHOULD_BE_FALSE"}
        if reported == "PASS":
            return {"judge": "FAIL", "reason_code": "STALE_FALSE_PASS"}
        if reported in ("FAIL", "STALE_OR_SILENT"):
            return {"judge": "PASS", "reason_code": "STALE_OR_SILENT"}
        return {"judge": "FAIL", "reason_code": "MUST_FLAG_STALE"}

    if kind == "inconclusive_exclude_denom":
        # INCONCLUSIVE must not inflate pass numer / availability denom
        if reported != "INCONCLUSIVE":
            return {"judge": "FAIL", "reason_code": "EXPECTED_INCONCLUSIVE"}
        if enter_pass is True or enter_denom is True:
            return {
                "judge": "FAIL",
                "reason_code": "INCONCLUSIVE_INFLATES_DENOM",
                "detail": {
                    "enter_pass_numerator": enter_pass,
                    "enter_availability_denom": enter_denom,
                },
            }
        return {"judge": "PASS", "reason_code": "INCONCLUSIVE_EXCLUDED_OK"}

    if kind == "zero_error_vs_zero_data":
        # zero_error (healthy) vs zero_data (blind) must not share PASS path
        ze = bool(receipt.get("zero_error", False))
        zd = bool(receipt.get("zero_data", False))
        if ze and zd:
            return {"judge": "FAIL", "reason_code": "CONFLICTING_ZERO_FLAGS"}
        if zd and not delta_attested:
            if reported == "PASS":
                return {"judge": "FAIL", "reason_code": "ZERO_DATA_FALSE_PASS"}
            if reported in ("FAIL", "INCONCLUSIVE", "UNKNOWN"):
                return {"judge": "PASS", "reason_code": "ZERO_DATA_FLAGGED"}
            return {"judge": "FAIL", "reason_code": "MUST_FLAG_ZERO_DATA"}
        if ze and not zd and window_ok is True and (delta_attested or zero_delta_receipt):
            if reported == "PASS":
                return {"judge": "PASS", "reason_code": "ZERO_ERROR_OK"}
            return {"judge": "FAIL", "reason_code": "ZERO_ERROR_SHOULD_PASS"}
        return {"judge": "FAIL", "reason_code": "UNCLASSIFIED_ZERO"}

    if kind == "mixed_stream_ok":
        # Honest mixed stream with business events + heartbeats
        if stream_class != "mixed":
            return {"judge": "FAIL", "reason_code": "NOT_MIXED"}
        if not isinstance(biz_events, int) or biz_events < 1:
            return {"judge": "FAIL", "reason_code": "NO_BUSINESS_EVENTS"}
        if reported == "PASS":
            return {"judge": "PASS", "reason_code": "MIXED_STREAM_OK"}
        return {"judge": "FAIL", "reason_code": "MIXED_SHOULD_PASS"}

    return {"judge": "FAIL", "reason_code": "UNCLASSIFIED", "kind": kind}


FIXTURES = [
    {
        "case_id": "HB-ONLY-FALSE-PASS",
        "receipt": {
            "kind": "heartbeat_only_false_pass",
            "stream_class": "heartbeat_only",
            "heartbeat_count": 12,
            "business_event_count": 0,
            "delta_attested": False,
            "zero_delta_receipt": False,
            "reported_verdict": "PASS",
        },
        "expect": "HEARTBEAT_ONLY_FALSE_PASS",
    },
    {
        "case_id": "HB-ONLY-INCONCLUSIVE",
        "receipt": {
            "kind": "heartbeat_only_false_pass",
            "stream_class": "heartbeat_only",
            "heartbeat_count": 12,
            "business_event_count": 0,
            "delta_attested": False,
            "zero_delta_receipt": False,
            "reported_verdict": "INCONCLUSIVE",
        },
        "expect": "HEARTBEAT_ONLY_INCONCLUSIVE",
    },
    {
        "case_id": "SKIP-AS-IDLE-FALSE-PASS",
        "receipt": {
            "kind": "skipped_as_idle",
            "plan_required_run": True,
            "execution_skipped": True,
            "heartbeat_count": 3,
            "reported_verdict": "PASS",
        },
        "expect": "SKIP_AS_IDLE_FALSE_PASS",
    },
    {
        "case_id": "SKIP-NOT-IDLE",
        "receipt": {
            "kind": "skipped_as_idle",
            "plan_required_run": True,
            "execution_skipped": True,
            "heartbeat_count": 3,
            "reported_verdict": "INCONCLUSIVE",
        },
        "expect": "SKIP_NOT_IDLE",
    },
    {
        "case_id": "VERIFIED-IDLE-ZERO-DELTA",
        "receipt": {
            "kind": "verified_idle_zero_delta",
            "delta_attested": True,
            "zero_delta_receipt": True,
            "window_ok": True,
            "execution_skipped": False,
            "reported_verdict": "PASS",
        },
        "expect": "VERIFIED_IDLE",
    },
    {
        "case_id": "VERIFIED-IDLE-MISSING-ATTEST",
        "receipt": {
            "kind": "verified_idle_zero_delta",
            "delta_attested": False,
            "zero_delta_receipt": False,
            "window_ok": True,
            "execution_skipped": False,
            "reported_verdict": "PASS",
        },
        "expect": "ZERO_DELTA_NOT_ATTESTED",
    },
    {
        "case_id": "STALE-FALSE-PASS",
        "receipt": {
            "kind": "stale_silent",
            "heartbeat_missing_in_window": True,
            "window_ok": False,
            "reported_verdict": "PASS",
        },
        "expect": "STALE_FALSE_PASS",
    },
    {
        "case_id": "STALE-OR-SILENT",
        "receipt": {
            "kind": "stale_silent",
            "heartbeat_missing_in_window": True,
            "window_ok": False,
            "reported_verdict": "FAIL",
        },
        "expect": "STALE_OR_SILENT",
    },
    {
        "case_id": "INCONCLUSIVE-EXCLUDED",
        "receipt": {
            "kind": "inconclusive_exclude_denom",
            "reported_verdict": "INCONCLUSIVE",
            "enter_pass_numerator": False,
            "enter_availability_denom": False,
        },
        "expect": "INCONCLUSIVE_EXCLUDED_OK",
    },
    {
        "case_id": "INCONCLUSIVE-INFLATES",
        "receipt": {
            "kind": "inconclusive_exclude_denom",
            "reported_verdict": "INCONCLUSIVE",
            "enter_pass_numerator": False,
            "enter_availability_denom": True,
        },
        "expect": "INCONCLUSIVE_INFLATES_DENOM",
    },
    {
        "case_id": "ZERO-DATA-FALSE-PASS",
        "receipt": {
            "kind": "zero_error_vs_zero_data",
            "zero_error": False,
            "zero_data": True,
            "delta_attested": False,
            "reported_verdict": "PASS",
        },
        "expect": "ZERO_DATA_FALSE_PASS",
    },
    {
        "case_id": "ZERO-DATA-FLAGGED",
        "receipt": {
            "kind": "zero_error_vs_zero_data",
            "zero_error": False,
            "zero_data": True,
            "delta_attested": False,
            "reported_verdict": "INCONCLUSIVE",
        },
        "expect": "ZERO_DATA_FLAGGED",
    },
    {
        "case_id": "ZERO-ERROR-OK",
        "receipt": {
            "kind": "zero_error_vs_zero_data",
            "zero_error": True,
            "zero_data": False,
            "delta_attested": True,
            "zero_delta_receipt": True,
            "window_ok": True,
            "reported_verdict": "PASS",
        },
        "expect": "ZERO_ERROR_OK",
    },
    {
        "case_id": "MIXED-STREAM-OK",
        "receipt": {
            "kind": "mixed_stream_ok",
            "stream_class": "mixed",
            "heartbeat_count": 5,
            "business_event_count": 2,
            "reported_verdict": "PASS",
        },
        "expect": "MIXED_STREAM_OK",
    },
]


def main() -> int:
    rows = []
    ok = True
    for fx in FIXTURES:
        got = judge(fx["receipt"])
        match = got.get("reason_code") == fx["expect"]
        if not match:
            ok = False
        rows.append(
            {
                "case_id": fx["case_id"],
                "expect": fx["expect"],
                "got": got.get("reason_code"),
                "match": match,
                "detail": got.get("detail"),
            }
        )
    payload = json.dumps({"fixtures": rows}, sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256(payload.encode()).hexdigest()
    out = {
        "fixture": "HEARTBEAT_ONLY_STREAM",
        "version": "v0.1",
        "credit": "派蒙 + Hermes",
        "n": len(rows),
        "passed": sum(1 for r in rows if r["match"]),
        "ok": ok,
        "run_out_sha256": digest,
        "rows": rows,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
