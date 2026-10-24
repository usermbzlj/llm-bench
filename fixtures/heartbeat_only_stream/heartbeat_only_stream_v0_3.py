#!/usr/bin/env python3
"""HEARTBEAT_ONLY_STREAM v0.3

Extends v0.2. Structure from 栀子花 Agent (2026-10-24 PM) + 郑珺的hermes:

  1. NO_HEARTBEAT typed split (0 vs absent is not enough):
     heartbeat_count as "0"(str) / null / -1 / 1e0(float) MUST map to
     four distinct named exits. Collapsing all into NO_HEARTBEAT means
     the split lives only at parse layer, not comparison layer.
  2. must-fail JSONL protocol: each must-fail sample is a single-field
     diff from a known-green twin; assert BOTH (a) must red and
     (b) expected reason_code. Red-only lets parse/shape errors borrow red.
  3. HONEST_FAIL from audited-party input: true violation + HONEST_FAIL
     label must stay red (retain OVERRUN_MUST_RED / HONEST_FAIL_COVERS_OVERRUN).
  4. Zero-delta attestation source split (郑珺):
     "frame present, empty payload" vs "frame itself missing" must not
     collapse into the same PASS when the checker only compares final
     byte counts. Require explicit evidence_source ∈ {counter, seq, ts}.

Retains v0.2 arms (typed-bool, biz_key absent, IDEM, pass-column split,
overrun, heartbeat-only false pass, skip-as-idle, verified idle, etc.).

analyze_only. Stdlib only.
Credit: 栀子花 Agent (v0.3 typed NO_HEARTBEAT + must-fail single-field);
        郑珺的hermes (zero-delta evidence_source split);
        栀子花 (v0.2); 派蒙 + Hermes (v0.1); Grok Bot (impl).
"""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from typing import Any


def _is_strict_bool(v: Any) -> bool:
    return type(v) is bool


def _is_strict_int(v: Any) -> bool:
    return type(v) is int and not isinstance(v, bool)


def classify_hb_count(receipt: dict[str, Any]) -> dict[str, Any] | None:
    """Typed NO_HEARTBEAT split. Returns a result dict if this arm applies."""
    if receipt.get("kind") != "no_heartbeat_typed":
        return None
    reported = receipt.get("reported_verdict")
    key_present = "heartbeat_count" in receipt
    raw = receipt.get("heartbeat_count") if key_present else None

    # Four typed exits — MUST be mutually distinct reason_codes
    if key_present and raw is None:
        code = "HB_COUNT_NULL"
    elif key_present and isinstance(raw, str):
        code = "HB_COUNT_STRING_ZERO" if raw == "0" else "HB_COUNT_STRING_OTHER"
    elif key_present and isinstance(raw, float):
        code = "HB_COUNT_FLOAT_COERCE"
    elif key_present and _is_strict_int(raw) and raw < 0:
        code = "HB_COUNT_NEGATIVE"
    elif key_present and _is_strict_int(raw) and raw == 0:
        code = "HB_COUNT_INT_ZERO"
    elif not key_present:
        code = "HB_COUNT_KEY_ABSENT"
    elif key_present and _is_strict_int(raw) and raw > 0:
        # Positive strict int is not a NO_HEARTBEAT case
        return {"judge": "FAIL", "reason_code": "NOT_NO_HEARTBEAT_CASE"}
    else:
        code = "HB_COUNT_UNTYPED"

    # If implementation collapsed everything to generic NO_HEARTBEAT → fail the gate
    collapsed = receipt.get("impl_reason_code")
    if collapsed == "NO_HEARTBEAT":
        return {
            "judge": "FAIL",
            "reason_code": "NO_HEARTBEAT_COLLAPSED",
            "detail": {"expected_distinct": code, "impl_reason_code": collapsed, "raw": raw},
        }
    # Honest typed exit
    if reported in ("FAIL", "INCONCLUSIVE", "UNKNOWN") or receipt.get("impl_reason_code") == code:
        return {"judge": "PASS", "reason_code": code, "detail": {"raw": raw, "key_present": key_present}}
    if reported == "PASS":
        return {
            "judge": "FAIL",
            "reason_code": "NO_HEARTBEAT_TYPED_FALSE_PASS",
            "detail": {"expected_code": code, "raw": raw},
        }
    return {"judge": "PASS", "reason_code": code, "detail": {"raw": raw}}


def classify_zero_delta_source(receipt: dict[str, Any]) -> dict[str, Any] | None:
    if receipt.get("kind") != "zero_delta_evidence_source":
        return None
    reported = receipt.get("reported_verdict")
    frame_present = receipt.get("frame_present")
    payload_bytes = receipt.get("payload_bytes")
    evidence_source = receipt.get("evidence_source")  # counter|seq|ts
    final_byte_count = receipt.get("final_byte_count")
    only_compared_bytes = bool(receipt.get("only_compared_final_bytes", False))

    # Frame missing vs empty payload
    if frame_present is False:
        distinct = "FRAME_ABSENT"
    elif frame_present is True and payload_bytes == 0:
        distinct = "FRAME_EMPTY_PAYLOAD"
    else:
        return {"judge": "FAIL", "reason_code": "NOT_ZERO_DELTA_BOUNDARY"}

    if only_compared_bytes and reported == "PASS":
        # Collapsed the two into same PASS via byte-count-only check
        return {
            "judge": "FAIL",
            "reason_code": "ZERO_DELTA_SOURCE_COLLAPSED",
            "detail": {
                "distinct_should_be": distinct,
                "final_byte_count": final_byte_count,
                "evidence_source": evidence_source,
            },
        }
    if evidence_source not in ("counter", "seq", "ts"):
        if reported == "PASS":
            return {
                "judge": "FAIL",
                "reason_code": "ZERO_DELTA_NO_EVIDENCE_SOURCE",
                "detail": {"evidence_source": evidence_source},
            }
        return {"judge": "PASS", "reason_code": "ZERO_DELTA_SOURCE_FLAGGED"}
    # Honest distinct exit with attested source
    if reported in ("FAIL", "INCONCLUSIVE") or receipt.get("impl_reason_code") == distinct:
        return {"judge": "PASS", "reason_code": distinct, "detail": {"evidence_source": evidence_source}}
    if reported == "PASS" and distinct == "FRAME_EMPTY_PAYLOAD" and evidence_source in ("counter", "seq", "ts"):
        # Empty payload with attested zero-delta source can be verified idle — not this arm's false-pass
        return {"judge": "PASS", "reason_code": "FRAME_EMPTY_ATTESTED", "detail": {"evidence_source": evidence_source}}
    return {"judge": "FAIL", "reason_code": "ZERO_DELTA_UNCLASSIFIED", "detail": {"distinct": distinct}}


def judge(receipt: dict[str, Any]) -> dict[str, Any]:
    kind = receipt.get("kind")
    reported = receipt.get("reported_verdict")
    hb_count = receipt.get("heartbeat_count")
    biz_key_present = "business_event_count" in receipt
    biz_events = receipt.get("business_event_count") if biz_key_present else None
    delta_attested = receipt.get("delta_attested", False)
    zero_delta_receipt = receipt.get("zero_delta_receipt", False)
    skipped = receipt.get("execution_skipped", False)
    plan_required = receipt.get("plan_required_run", False)
    window_ok = receipt.get("window_ok")
    hb_missing = bool(receipt.get("heartbeat_missing_in_window", False))
    enter_pass = receipt.get("enter_pass_numerator")
    enter_denom = receipt.get("enter_availability_denom")
    stream_class = receipt.get("stream_class")

    typed = classify_hb_count(receipt)
    if typed is not None:
        return typed
    zsrc = classify_zero_delta_source(receipt)
    if zsrc is not None:
        return zsrc

    # --- v0.3: must-fail single-field-diff protocol ---
    if kind == "mustfail_single_field":
        # Protocol checker: twin_green + mutated field → must match expected_reason
        # and judge must be FAIL (red). Red-only without reason_code match → fail.
        got_code = receipt.get("impl_reason_code")
        expected = receipt.get("expected_reason_code")
        gate_color = receipt.get("gate_color")  # red|green
        mutated_field = receipt.get("mutated_field")
        if not expected or not mutated_field:
            return {"judge": "FAIL", "reason_code": "MUSTFAIL_PROTOCOL_INCOMPLETE"}
        if gate_color != "red":
            return {
                "judge": "FAIL",
                "reason_code": "MUSTFAIL_NOT_RED",
                "detail": {"mutated_field": mutated_field, "gate_color": gate_color},
            }
        if got_code != expected:
            return {
                "judge": "FAIL",
                "reason_code": "MUSTFAIL_REASON_MISMATCH",
                "detail": {"expected": expected, "got": got_code, "mutated_field": mutated_field},
            }
        return {
            "judge": "PASS",
            "reason_code": "MUSTFAIL_SINGLE_FIELD_OK",
            "detail": {"mutated_field": mutated_field, "expected_reason_code": expected},
        }

    # --- v0.2: typed-bool coerce at comparison site ---
    if kind == "typed_bool_coerce":
        suspects = []
        for key in ("delta_attested", "zero_delta_receipt", "execution_skipped", "plan_required_run"):
            if key not in receipt:
                continue
            if not _is_strict_bool(receipt[key]):
                suspects.append({"key": key, "type": type(receipt[key]).__name__, "value": receipt[key]})
        if suspects:
            if reported == "PASS":
                return {
                    "judge": "FAIL",
                    "reason_code": "TYPED_BOOL_COERCE_FALSE_PASS",
                    "detail": {"suspects": suspects},
                }
            return {
                "judge": "FAIL",
                "reason_code": "TYPED_BOOL_COERCE",
                "detail": {"suspects": suspects},
            }
        if reported == "PASS":
            return {"judge": "PASS", "reason_code": "TYPED_BOOL_OK"}
        return {"judge": "FAIL", "reason_code": "TYPED_BOOL_SHOULD_PASS"}

    if kind == "biz_events_key_absent":
        if biz_key_present:
            return {"judge": "FAIL", "reason_code": "KEY_UNEXPECTEDLY_PRESENT"}
        if stream_class != "heartbeat_only":
            return {"judge": "FAIL", "reason_code": "NOT_HEARTBEAT_ONLY"}
        if reported == "PASS":
            return {
                "judge": "FAIL",
                "reason_code": "BIZ_KEY_ABSENT_FALSE_PASS",
                "detail": {"business_event_count_key_present": False},
            }
        if reported in ("INCONCLUSIVE", "UNKNOWN", "FAIL"):
            return {"judge": "PASS", "reason_code": "BIZ_KEY_ABSENT_FLAGGED"}
        return {"judge": "FAIL", "reason_code": "MUST_FLAG_BIZ_KEY_ABSENT"}

    if kind == "honest_fail_covers_overrun":
        try:
            effect = int(receipt["effect_count"])
            declared = int(receipt["declared_effect"])
        except (KeyError, TypeError, ValueError):
            return {"judge": "FAIL", "reason_code": "EFFECT_FIELDS_MISSING"}
        label = receipt.get("honesty_label")
        business_verdict = receipt.get("business_verdict")
        gate_color = receipt.get("gate_color")
        if effect <= declared:
            return {"judge": "FAIL", "reason_code": "NOT_OVERRUN_CASE"}
        if label == "HONEST_FAIL" and gate_color == "green":
            return {
                "judge": "FAIL",
                "reason_code": "HONEST_FAIL_COVERS_OVERRUN",
                "detail": {
                    "effect_count": effect,
                    "declared_effect": declared,
                    "honesty_label": label,
                    "gate_color": gate_color,
                },
            }
        if business_verdict == "PASS":
            return {
                "judge": "FAIL",
                "reason_code": "HONEST_FAIL_COVERS_OVERRUN",
                "detail": {
                    "effect_count": effect,
                    "declared_effect": declared,
                    "business_verdict": business_verdict,
                },
            }
        if gate_color == "red" and business_verdict in ("FAIL", "HONEST_FAIL_ESCALATED"):
            return {"judge": "PASS", "reason_code": "OVERRUN_GATE_RED"}
        return {"judge": "FAIL", "reason_code": "OVERRUN_MUST_RED"}

    if kind == "idem_effect_vs_status":
        try:
            effect = int(receipt["effect_count"])
            declared = int(receipt["declared_effect"])
        except (KeyError, TypeError, ValueError):
            return {"judge": "FAIL", "reason_code": "EFFECT_FIELDS_MISSING"}
        status = receipt.get("status_text")
        asserted_on = receipt.get("asserted_on")
        reported_same_color = bool(receipt.get("g2_m1_m2_same_color", False))
        if asserted_on == "status":
            if reported_same_color and reported == "PASS":
                return {
                    "judge": "FAIL",
                    "reason_code": "IDEM_STATUS_FALSE_GREEN",
                    "detail": {"status_text": status, "asserted_on": asserted_on},
                }
            return {
                "judge": "FAIL",
                "reason_code": "IDEM_MUST_ASSERT_EFFECT",
                "detail": {"asserted_on": asserted_on, "effect_count": effect, "declared_effect": declared},
            }
        if asserted_on == "effect":
            if effect != declared:
                if reported == "PASS":
                    return {"judge": "FAIL", "reason_code": "IDEM_EFFECT_MISMATCH_FALSE_PASS"}
                return {"judge": "PASS", "reason_code": "IDEM_EFFECT_MISMATCH_CAUGHT"}
            if reported == "PASS":
                return {"judge": "PASS", "reason_code": "IDEM_EFFECT_MATCH_OK"}
            return {"judge": "FAIL", "reason_code": "IDEM_MATCH_SHOULD_PASS"}
        return {"judge": "FAIL", "reason_code": "ASSERTED_ON_UNKNOWN"}

    if kind == "pass_column_split":
        rh = receipt.get("receipt_honesty")
        bv = receipt.get("business_verdict")
        if rh == "mismatch" and bv == "PASS":
            return {
                "judge": "FAIL",
                "reason_code": "HONESTY_MISMATCH_BUSINESS_PASS",
                "detail": {"receipt_honesty": rh, "business_verdict": bv},
            }
        if rh == "ok" and bv == "PASS":
            return {"judge": "PASS", "reason_code": "COLUMNS_ALIGNED_PASS"}
        if rh == "mismatch" and bv in ("FAIL", "INCONCLUSIVE"):
            return {"judge": "PASS", "reason_code": "COLUMNS_SPLIT_HONEST"}
        return {"judge": "FAIL", "reason_code": "COLUMN_SPLIT_UNCLASSIFIED"}

    if not _is_strict_bool(delta_attested) and "delta_attested" in receipt:
        delta_attested = bool(delta_attested)
    else:
        delta_attested = bool(delta_attested) if "delta_attested" in receipt else False
    if not _is_strict_bool(zero_delta_receipt) and "zero_delta_receipt" in receipt:
        zero_delta_receipt = bool(zero_delta_receipt)
    else:
        zero_delta_receipt = bool(zero_delta_receipt) if "zero_delta_receipt" in receipt else False
    skipped = bool(skipped) if "execution_skipped" in receipt else False
    plan_required = bool(plan_required) if "plan_required_run" in receipt else False

    if kind == "heartbeat_only_false_pass":
        if stream_class != "heartbeat_only":
            return {"judge": "FAIL", "reason_code": "NOT_HEARTBEAT_ONLY"}
        if not _is_strict_int(hb_count) or hb_count < 1:
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

    if kind == "heartbeat_only_honest_fail":
        if stream_class != "heartbeat_only":
            return {"judge": "FAIL", "reason_code": "NOT_HEARTBEAT_ONLY"}
        if reported == "FAIL":
            return {"judge": "PASS", "reason_code": "HEARTBEAT_ONLY_HONEST_FAIL"}
        if reported == "PASS":
            return {"judge": "FAIL", "reason_code": "HEARTBEAT_ONLY_FALSE_PASS"}
        return {"judge": "FAIL", "reason_code": "MUST_REPORT_FAIL_OR_INCONCLUSIVE"}

    return {"judge": "FAIL", "reason_code": "UNCLASSIFIED", "kind": kind}


# Green twin for must-fail single-field protocol
_GREEN_TWIN = {
    "kind": "heartbeat_only_false_pass",
    "stream_class": "heartbeat_only",
    "heartbeat_count": 12,
    "business_event_count": 0,
    "delta_attested": False,
    "zero_delta_receipt": False,
    "reported_verdict": "INCONCLUSIVE",
}


FIXTURES = [
    # --- v0.3 new: typed NO_HEARTBEAT ---
    {
        "case_id": "HB-COUNT-STRING-ZERO",
        "receipt": {
            "kind": "no_heartbeat_typed",
            "heartbeat_count": "0",
            "impl_reason_code": "HB_COUNT_STRING_ZERO",
            "reported_verdict": "FAIL",
        },
        "expect": "HB_COUNT_STRING_ZERO",
    },
    {
        "case_id": "HB-COUNT-NULL",
        "receipt": {
            "kind": "no_heartbeat_typed",
            "heartbeat_count": None,
            "impl_reason_code": "HB_COUNT_NULL",
            "reported_verdict": "FAIL",
        },
        "expect": "HB_COUNT_NULL",
    },
    {
        "case_id": "HB-COUNT-NEGATIVE",
        "receipt": {
            "kind": "no_heartbeat_typed",
            "heartbeat_count": -1,
            "impl_reason_code": "HB_COUNT_NEGATIVE",
            "reported_verdict": "FAIL",
        },
        "expect": "HB_COUNT_NEGATIVE",
    },
    {
        "case_id": "HB-COUNT-FLOAT-COERCE",
        "receipt": {
            "kind": "no_heartbeat_typed",
            "heartbeat_count": 1.0,
            "impl_reason_code": "HB_COUNT_FLOAT_COERCE",
            "reported_verdict": "FAIL",
        },
        "expect": "HB_COUNT_FLOAT_COERCE",
    },
    {
        "case_id": "HB-COUNT-COLLAPSED-NO-HEARTBEAT",
        "receipt": {
            "kind": "no_heartbeat_typed",
            "heartbeat_count": "0",
            "impl_reason_code": "NO_HEARTBEAT",
            "reported_verdict": "FAIL",
        },
        "expect": "NO_HEARTBEAT_COLLAPSED",
    },
    {
        "case_id": "HB-COUNT-KEY-ABSENT",
        "receipt": {
            "kind": "no_heartbeat_typed",
            # heartbeat_count key absent
            "impl_reason_code": "HB_COUNT_KEY_ABSENT",
            "reported_verdict": "INCONCLUSIVE",
        },
        "expect": "HB_COUNT_KEY_ABSENT",
    },
    # --- v0.3: zero-delta evidence source ---
    {
        "case_id": "FRAME-ABSENT-COLLAPSED",
        "receipt": {
            "kind": "zero_delta_evidence_source",
            "frame_present": False,
            "payload_bytes": 0,
            "final_byte_count": 0,
            "only_compared_final_bytes": True,
            "evidence_source": None,
            "reported_verdict": "PASS",
        },
        "expect": "ZERO_DELTA_SOURCE_COLLAPSED",
    },
    {
        "case_id": "FRAME-EMPTY-PAYLOAD-DISTINCT",
        "receipt": {
            "kind": "zero_delta_evidence_source",
            "frame_present": True,
            "payload_bytes": 0,
            "final_byte_count": 0,
            "only_compared_final_bytes": False,
            "evidence_source": "seq",
            "impl_reason_code": "FRAME_EMPTY_PAYLOAD",
            "reported_verdict": "FAIL",
        },
        "expect": "FRAME_EMPTY_PAYLOAD",
    },
    {
        "case_id": "FRAME-ABSENT-DISTINCT",
        "receipt": {
            "kind": "zero_delta_evidence_source",
            "frame_present": False,
            "payload_bytes": None,
            "final_byte_count": 0,
            "only_compared_final_bytes": False,
            "evidence_source": "counter",
            "impl_reason_code": "FRAME_ABSENT",
            "reported_verdict": "FAIL",
        },
        "expect": "FRAME_ABSENT",
    },
    {
        "case_id": "ZERO-DELTA-NO-EVIDENCE-SOURCE",
        "receipt": {
            "kind": "zero_delta_evidence_source",
            "frame_present": True,
            "payload_bytes": 0,
            "only_compared_final_bytes": False,
            "evidence_source": None,
            "reported_verdict": "PASS",
        },
        "expect": "ZERO_DELTA_NO_EVIDENCE_SOURCE",
    },
    # --- v0.3: must-fail single-field protocol ---
    {
        "case_id": "MUSTFAIL-SINGLE-FIELD-OK",
        "receipt": {
            "kind": "mustfail_single_field",
            "mutated_field": "reported_verdict",
            "expected_reason_code": "HEARTBEAT_ONLY_FALSE_PASS",
            "impl_reason_code": "HEARTBEAT_ONLY_FALSE_PASS",
            "gate_color": "red",
            "twin_green": _GREEN_TWIN,
        },
        "expect": "MUSTFAIL_SINGLE_FIELD_OK",
    },
    {
        "case_id": "MUSTFAIL-REASON-MISMATCH",
        "receipt": {
            "kind": "mustfail_single_field",
            "mutated_field": "reported_verdict",
            "expected_reason_code": "HEARTBEAT_ONLY_FALSE_PASS",
            "impl_reason_code": "PARSE_ERROR",  # red via shape, wrong code
            "gate_color": "red",
        },
        "expect": "MUSTFAIL_REASON_MISMATCH",
    },
    {
        "case_id": "MUSTFAIL-NOT-RED",
        "receipt": {
            "kind": "mustfail_single_field",
            "mutated_field": "business_event_count",
            "expected_reason_code": "HAS_BUSINESS_EVENTS",
            "impl_reason_code": "HAS_BUSINESS_EVENTS",
            "gate_color": "green",
        },
        "expect": "MUSTFAIL_NOT_RED",
    },
    # --- v0.2 retained smoke ---
    {
        "case_id": "TYPED-BOOL-STR-FALSE-PASS",
        "receipt": {
            "kind": "typed_bool_coerce",
            "delta_attested": "true",
            "zero_delta_receipt": 1,
            "reported_verdict": "PASS",
        },
        "expect": "TYPED_BOOL_COERCE_FALSE_PASS",
    },
    {
        "case_id": "BIZ-KEY-ABSENT-FALSE-PASS",
        "receipt": {
            "kind": "biz_events_key_absent",
            "stream_class": "heartbeat_only",
            "heartbeat_count": 8,
            "reported_verdict": "PASS",
        },
        "expect": "BIZ_KEY_ABSENT_FALSE_PASS",
    },
    {
        "case_id": "HONEST-FAIL-COVERS-OVERRUN",
        "receipt": {
            "kind": "honest_fail_covers_overrun",
            "effect_count": 2,
            "declared_effect": 1,
            "honesty_label": "HONEST_FAIL",
            "receipt_honesty": "ok",
            "business_verdict": "PASS",
            "gate_color": "green",
            "reported_verdict": "PASS",
        },
        "expect": "HONEST_FAIL_COVERS_OVERRUN",
    },
    {
        "case_id": "OVERRUN-GATE-RED",
        "receipt": {
            "kind": "honest_fail_covers_overrun",
            "effect_count": 2,
            "declared_effect": 1,
            "honesty_label": "HONEST_FAIL",
            "receipt_honesty": "mismatch",
            "business_verdict": "FAIL",
            "gate_color": "red",
            "reported_verdict": "FAIL",
        },
        "expect": "OVERRUN_GATE_RED",
    },
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
        "case_id": "IDEM-STATUS-FALSE-GREEN",
        "receipt": {
            "kind": "idem_effect_vs_status",
            "effect_count": 2,
            "declared_effect": 1,
            "status_text": "DELIVERED-BUT-UNREADABLE",
            "asserted_on": "status",
            "g2_m1_m2_same_color": True,
            "reported_verdict": "PASS",
        },
        "expect": "IDEM_STATUS_FALSE_GREEN",
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
        "version": "v0.3",
        "credit": "栀子花 Agent (v0.3 typed NO_HEARTBEAT + must-fail single-field); 郑珺的hermes (zero-delta source); 栀子花 (v0.2); 派蒙+Hermes (v0.1)",
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
