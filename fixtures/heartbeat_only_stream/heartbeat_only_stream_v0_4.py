#!/usr/bin/env python3
"""HEARTBEAT_ONLY_STREAM v0.4

Extends v0.3. Structure from 栀子花 Agent (2026-10-24 PM single-field-diff JSONL):

  Closed reason_code set (must-fail single-field-diff):
    KEY_ABSENT
    HB_COUNT_EMPTY_STRING   # "" sibling of KEY_ABSENT — existence dim first
    HB_COUNT_EMPTY_OBJECT   # {}
    AT_UNIT_CONTRADICTS_WIDTH  # explicit "s" + 13-digit ms timestamp
    DUPLICATE_KEY_TEXT_ONLY    # {"at":…,"at":…} same-value dup — raw-text arm only

  Hard rules from 栀子花:
  1. Existence-before-value: value-only compare collapses "" vs absent into
     NULL/STRING_ZERO; comparator MUST check key presence first.
  2. Negative control: value_only_collapses_empty_vs_absent=True must RED.
  3. at_unit explicit: unit="s" + 13-digit epoch_ms ⇒ AT_UNIT_CONTRADICTS_WIDTH.
  4. Duplicate same-value keys: parsed object delta=0; only raw-text arm
     (key occurrence count 1→2) can catch DUPLICATE_KEY_TEXT_ONLY. Harness
     without a raw-text arm can never fabricate this case.

Retains v0.3 typed NO_HEARTBEAT / zero-delta / mustfail protocol / v0.2 arms.
analyze_only. Stdlib only.
Credit: 栀子花 Agent (v0.4 KEY_ABSENT empty-string sibling + existence-first
        + at_unit explicit + DUPLICATE_KEY_TEXT_ONLY raw arm);
        栀子花 (v0.3); 郑珺的hermes (zero-delta); 派蒙+Hermes (v0.1); Grok Bot.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from typing import Any


def _is_strict_bool(v: Any) -> bool:
    return type(v) is bool


def _is_strict_int(v: Any) -> bool:
    return type(v) is int and not isinstance(v, bool)


def classify_hb_count(receipt: dict[str, Any]) -> dict[str, Any] | None:
    if receipt.get("kind") != "no_heartbeat_typed":
        return None
    reported = receipt.get("reported_verdict")
    key_present = "heartbeat_count" in receipt
    raw = receipt.get("heartbeat_count") if key_present else None

    if key_present and raw is None:
        code = "HB_COUNT_NULL"
    elif key_present and isinstance(raw, str):
        if raw == "":
            code = "HB_COUNT_EMPTY_STRING"
        elif raw == "0":
            code = "HB_COUNT_STRING_ZERO"
        else:
            code = "HB_COUNT_STRING_OTHER"
    elif key_present and isinstance(raw, dict) and raw == {}:
        code = "HB_COUNT_EMPTY_OBJECT"
    elif key_present and isinstance(raw, float):
        code = "HB_COUNT_FLOAT_COERCE"
    elif key_present and _is_strict_int(raw) and raw < 0:
        code = "HB_COUNT_NEGATIVE"
    elif key_present and _is_strict_int(raw) and raw == 0:
        code = "HB_COUNT_INT_ZERO"
    elif not key_present:
        code = "HB_COUNT_KEY_ABSENT"
    elif key_present and _is_strict_int(raw) and raw > 0:
        return {"judge": "FAIL", "reason_code": "NOT_NO_HEARTBEAT_CASE"}
    else:
        code = "HB_COUNT_UNTYPED"

    collapsed = receipt.get("impl_reason_code")
    if collapsed == "NO_HEARTBEAT":
        return {
            "judge": "FAIL",
            "reason_code": "NO_HEARTBEAT_COLLAPSED",
            "detail": {"expected_distinct": code, "impl_reason_code": collapsed, "raw": raw},
        }
    if reported in ("FAIL", "INCONCLUSIVE", "UNKNOWN") or receipt.get("impl_reason_code") == code:
        return {"judge": "PASS", "reason_code": code, "detail": {"raw": raw, "key_present": key_present}}
    if reported == "PASS":
        return {
            "judge": "FAIL",
            "reason_code": "NO_HEARTBEAT_TYPED_FALSE_PASS",
            "detail": {"expected_code": code, "raw": raw},
        }
    return {"judge": "PASS", "reason_code": code, "detail": {"raw": raw}}


def classify_existence_before_value(receipt: dict[str, Any]) -> dict[str, Any] | None:
    """v0.4: KEY_ABSENT vs EMPTY_STRING must not collapse under value-only compare."""
    if receipt.get("kind") != "existence_before_value":
        return None
    reported = receipt.get("reported_verdict")
    twin_key_present = bool(receipt.get("twin_key_present"))
    mutant_key_present = bool(receipt.get("mutant_key_present"))
    twin_val = receipt.get("twin_val")
    mutant_val = receipt.get("mutant_val")
    value_only = bool(receipt.get("value_only_collapses_empty_vs_absent", False))
    impl_code = receipt.get("impl_reason_code")

    # Canonical distinct codes
    if not mutant_key_present:
        expected = "KEY_ABSENT"
    elif mutant_key_present and mutant_val == "":
        expected = "HB_COUNT_EMPTY_STRING"
    elif mutant_key_present and mutant_val == {}:
        expected = "HB_COUNT_EMPTY_OBJECT"
    else:
        return {"judge": "FAIL", "reason_code": "NOT_EXISTENCE_BOUNDARY"}

    if value_only and reported == "PASS":
        # Collapsed empty vs absent by comparing values only
        return {
            "judge": "FAIL",
            "reason_code": "VALUE_ONLY_COLLAPSES_EMPTY_VS_ABSENT",
            "detail": {
                "expected": expected,
                "twin_key_present": twin_key_present,
                "mutant_key_present": mutant_key_present,
                "twin_val": twin_val,
                "mutant_val": mutant_val,
            },
        }
    if impl_code == expected and reported in ("FAIL", "INCONCLUSIVE"):
        return {"judge": "PASS", "reason_code": expected, "detail": {"existence_first": True}}
    if reported == "PASS":
        return {
            "judge": "FAIL",
            "reason_code": "EXISTENCE_DIM_FALSE_PASS",
            "detail": {"expected": expected, "impl_reason_code": impl_code},
        }
    if impl_code and impl_code != expected:
        return {
            "judge": "FAIL",
            "reason_code": "EXISTENCE_REASON_MISMATCH",
            "detail": {"expected": expected, "got": impl_code},
        }
    return {"judge": "PASS", "reason_code": expected}


def classify_at_unit(receipt: dict[str, Any]) -> dict[str, Any] | None:
    """v0.4: explicit at_unit must contradict width. unit='s' + 13-digit ms → RED."""
    if receipt.get("kind") != "at_unit_width":
        return None
    reported = receipt.get("reported_verdict")
    at_unit = receipt.get("at_unit")  # "s" | "ms" | None
    at_raw = receipt.get("at_raw")  # string or int
    impl_code = receipt.get("impl_reason_code")

    digits = None
    if isinstance(at_raw, str) and at_raw.isdigit():
        digits = len(at_raw)
    elif _is_strict_int(at_raw) and at_raw >= 0:
        digits = len(str(at_raw))

    contradicts = at_unit == "s" and digits == 13
    if contradicts:
        expected = "AT_UNIT_CONTRADICTS_WIDTH"
        if reported == "PASS":
            return {
                "judge": "FAIL",
                "reason_code": "AT_UNIT_FALSE_PASS",
                "detail": {"at_unit": at_unit, "digits": digits},
            }
        if impl_code == expected or reported in ("FAIL", "INCONCLUSIVE"):
            return {"judge": "PASS", "reason_code": expected, "detail": {"at_unit": at_unit, "digits": digits}}
        return {
            "judge": "FAIL",
            "reason_code": "AT_UNIT_REASON_MISMATCH",
            "detail": {"expected": expected, "got": impl_code},
        }
    # Consistent unit/width
    if at_unit == "ms" and digits == 13:
        return {"judge": "PASS", "reason_code": "AT_UNIT_WIDTH_OK", "detail": {"at_unit": at_unit, "digits": digits}}
    if at_unit == "s" and digits == 10:
        return {"judge": "PASS", "reason_code": "AT_UNIT_WIDTH_OK", "detail": {"at_unit": at_unit, "digits": digits}}
    if reported == "PASS" and at_unit is None and digits == 13:
        # Implicit unit with ms-width — force explicit
        return {
            "judge": "FAIL",
            "reason_code": "AT_UNIT_IMPLICIT",
            "detail": {"digits": digits},
        }
    return {"judge": "PASS", "reason_code": "AT_UNIT_UNCLASSIFIED", "detail": {"at_unit": at_unit, "digits": digits}}


_KEY_OCCURRENCE_RE = re.compile(r'"([^"\\]+)"\s*:')


def count_key_occurrences(raw_text: str, key: str) -> int:
    return sum(1 for m in _KEY_OCCURRENCE_RE.finditer(raw_text) if m.group(1) == key)


def classify_duplicate_key_text(receipt: dict[str, Any]) -> dict[str, Any] | None:
    """v0.4: same-value duplicate keys only visible on raw-text arm."""
    if receipt.get("kind") != "duplicate_key_text":
        return None
    reported = receipt.get("reported_verdict")
    twin_raw = receipt.get("twin_raw") or ""
    mutant_raw = receipt.get("mutant_raw") or ""
    changed_key = receipt.get("changed_key") or "at"
    parse_only = bool(receipt.get("parse_only_harness", False))
    impl_code = receipt.get("impl_reason_code")

    twin_n = count_key_occurrences(twin_raw, changed_key)
    mutant_n = count_key_occurrences(mutant_raw, changed_key)

    # Parsed-object delta: same-value dup → 0 difference
    try:
        twin_obj = json.loads(twin_raw) if twin_raw else {}
        mutant_obj = json.loads(mutant_raw) if mutant_raw else {}
        parsed_delta = twin_obj != mutant_obj
    except json.JSONDecodeError:
        parsed_delta = True  # malformed — not this arm

    if mutant_n > twin_n and not parsed_delta:
        expected = "DUPLICATE_KEY_TEXT_ONLY"
        if parse_only and reported == "PASS":
            return {
                "judge": "FAIL",
                "reason_code": "PARSE_ONLY_MISSES_DUP_KEY",
                "detail": {"twin_n": twin_n, "mutant_n": mutant_n, "parsed_delta": parsed_delta},
            }
        if impl_code == expected or reported in ("FAIL", "INCONCLUSIVE"):
            return {
                "judge": "PASS",
                "reason_code": expected,
                "detail": {"twin_n": twin_n, "mutant_n": mutant_n, "raw_arm": True},
            }
        if reported == "PASS":
            return {
                "judge": "FAIL",
                "reason_code": "DUP_KEY_FALSE_PASS",
                "detail": {"twin_n": twin_n, "mutant_n": mutant_n},
            }
        return {
            "judge": "FAIL",
            "reason_code": "DUP_KEY_REASON_MISMATCH",
            "detail": {"expected": expected, "got": impl_code},
        }
    return {"judge": "FAIL", "reason_code": "NOT_DUP_KEY_CASE", "detail": {"twin_n": twin_n, "mutant_n": mutant_n}}


def classify_zero_delta_source(receipt: dict[str, Any]) -> dict[str, Any] | None:
    if receipt.get("kind") != "zero_delta_evidence_source":
        return None
    reported = receipt.get("reported_verdict")
    frame_present = receipt.get("frame_present")
    payload_bytes = receipt.get("payload_bytes")
    evidence_source = receipt.get("evidence_source")
    final_byte_count = receipt.get("final_byte_count")
    only_compared_bytes = bool(receipt.get("only_compared_final_bytes", False))

    if frame_present is False:
        distinct = "FRAME_ABSENT"
    elif frame_present is True and payload_bytes == 0:
        distinct = "FRAME_EMPTY_PAYLOAD"
    else:
        return {"judge": "FAIL", "reason_code": "NOT_ZERO_DELTA_BOUNDARY"}

    if only_compared_bytes and reported == "PASS":
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
    if reported in ("FAIL", "INCONCLUSIVE") or receipt.get("impl_reason_code") == distinct:
        return {"judge": "PASS", "reason_code": distinct, "detail": {"evidence_source": evidence_source}}
    if reported == "PASS" and distinct == "FRAME_EMPTY_PAYLOAD" and evidence_source in ("counter", "seq", "ts"):
        return {"judge": "PASS", "reason_code": "FRAME_EMPTY_ATTESTED", "detail": {"evidence_source": evidence_source}}
    return {"judge": "FAIL", "reason_code": "ZERO_DELTA_UNCLASSIFIED", "detail": {"distinct": distinct}}


def judge(receipt: dict[str, Any]) -> dict[str, Any]:
    kind = receipt.get("kind")
    reported = receipt.get("reported_verdict")

    for fn in (
        classify_hb_count,
        classify_existence_before_value,
        classify_at_unit,
        classify_duplicate_key_text,
        classify_zero_delta_source,
    ):
        hit = fn(receipt)
        if hit is not None:
            return hit

    if kind == "mustfail_single_field":
        got_code = receipt.get("impl_reason_code")
        expected = receipt.get("expected_reason_code")
        gate_color = receipt.get("gate_color")
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
            return {"judge": "PASS", "reason_code": "TYPED_BOOL_FLAGGED", "detail": {"suspects": suspects}}
        return {"judge": "PASS", "reason_code": "TYPED_BOOL_OK"}

    if kind == "biz_events_key_absent":
        if "business_event_count" not in receipt:
            if reported == "PASS":
                return {"judge": "FAIL", "reason_code": "BIZ_KEY_ABSENT_FALSE_PASS"}
            return {"judge": "PASS", "reason_code": "BIZ_KEY_ABSENT_FLAGGED"}
        return {"judge": "FAIL", "reason_code": "MUST_FLAG_BIZ_KEY_ABSENT"}

    if kind == "honest_fail_covers_overrun":
        effect = receipt.get("effect_count")
        declared = receipt.get("declared_effect")
        honesty = receipt.get("honesty_label")
        gate = receipt.get("gate_color")
        overrun = _is_strict_int(effect) and _is_strict_int(declared) and effect > declared
        if overrun and honesty == "HONEST_FAIL" and gate == "green" and reported == "PASS":
            return {"judge": "FAIL", "reason_code": "HONEST_FAIL_COVERS_OVERRUN"}
        if overrun and gate == "red" and reported == "FAIL":
            return {"judge": "PASS", "reason_code": "OVERRUN_GATE_RED"}
        return {"judge": "FAIL", "reason_code": "OVERRUN_UNCLASSIFIED"}

    if kind == "heartbeat_only_false_pass":
        if (
            receipt.get("stream_class") == "heartbeat_only"
            and receipt.get("business_event_count") == 0
            and not receipt.get("delta_attested")
            and not receipt.get("zero_delta_receipt")
            and reported == "PASS"
        ):
            return {"judge": "FAIL", "reason_code": "HEARTBEAT_ONLY_FALSE_PASS"}
        if reported in ("INCONCLUSIVE", "FAIL", "UNKNOWN"):
            return {"judge": "PASS", "reason_code": "HEARTBEAT_ONLY_FLAGGED"}
        return {"judge": "FAIL", "reason_code": "HEARTBEAT_ONLY_UNCLASSIFIED"}

    if kind == "verified_idle_zero_delta":
        if (
            receipt.get("delta_attested") is True
            and receipt.get("zero_delta_receipt") is True
            and receipt.get("window_ok") is True
            and receipt.get("execution_skipped") is False
            and reported == "PASS"
        ):
            return {"judge": "PASS", "reason_code": "VERIFIED_IDLE"}
        return {"judge": "FAIL", "reason_code": "NOT_VERIFIED_IDLE"}

    if kind == "idem_effect_vs_status":
        effect = receipt.get("effect_count")
        declared = receipt.get("declared_effect")
        if (
            _is_strict_int(effect)
            and _is_strict_int(declared)
            and effect > declared
            and receipt.get("asserted_on") == "status"
            and receipt.get("g2_m1_m2_same_color")
            and reported == "PASS"
        ):
            return {"judge": "FAIL", "reason_code": "IDEM_STATUS_FALSE_GREEN"}
        return {"judge": "PASS", "reason_code": "IDEM_OK"}

    return {"judge": "FAIL", "reason_code": "UNKNOWN_KIND", "detail": {"kind": kind}}


_GREEN_TWIN = {
    "kind": "heartbeat_only_false_pass",
    "stream_class": "heartbeat_only",
    "heartbeat_count": 12,
    "business_event_count": 0,
    "delta_attested": False,
    "zero_delta_receipt": False,
    "reported_verdict": "INCONCLUSIVE",
}

_TWIN_RAW = '{"at":1761292800123,"at_unit":"ms","heartbeat_count":12}'
_MUTANT_DUP = '{"at":1761292800123,"at":1761292800123,"at_unit":"ms","heartbeat_count":12}'


FIXTURES = [
    # --- v0.4 new: existence-before-value ---
    {
        "case_id": "KEY-ABSENT-EXISTENCE-FIRST",
        "receipt": {
            "kind": "existence_before_value",
            "twin_key_present": True,
            "mutant_key_present": False,
            "twin_val": 12,
            "mutant_val": None,
            "value_only_collapses_empty_vs_absent": False,
            "impl_reason_code": "KEY_ABSENT",
            "reported_verdict": "FAIL",
        },
        "expect": "KEY_ABSENT",
    },
    {
        "case_id": "HB-COUNT-EMPTY-STRING",
        "receipt": {
            "kind": "existence_before_value",
            "twin_key_present": True,
            "mutant_key_present": True,
            "twin_val": 12,
            "mutant_val": "",
            "value_only_collapses_empty_vs_absent": False,
            "impl_reason_code": "HB_COUNT_EMPTY_STRING",
            "reported_verdict": "FAIL",
        },
        "expect": "HB_COUNT_EMPTY_STRING",
    },
    {
        "case_id": "HB-COUNT-EMPTY-OBJECT",
        "receipt": {
            "kind": "existence_before_value",
            "twin_key_present": True,
            "mutant_key_present": True,
            "twin_val": 12,
            "mutant_val": {},
            "value_only_collapses_empty_vs_absent": False,
            "impl_reason_code": "HB_COUNT_EMPTY_OBJECT",
            "reported_verdict": "FAIL",
        },
        "expect": "HB_COUNT_EMPTY_OBJECT",
    },
    {
        "case_id": "VALUE-ONLY-COLLAPSES-EMPTY-VS-ABSENT",
        "receipt": {
            "kind": "existence_before_value",
            "twin_key_present": True,
            "mutant_key_present": False,
            "twin_val": "",
            "mutant_val": None,
            "value_only_collapses_empty_vs_absent": True,
            "impl_reason_code": "HB_COUNT_NULL",
            "reported_verdict": "PASS",
        },
        "expect": "VALUE_ONLY_COLLAPSES_EMPTY_VS_ABSENT",
    },
    # --- v0.4: at_unit explicit ---
    {
        "case_id": "AT-UNIT-CONTRADICTS-WIDTH",
        "receipt": {
            "kind": "at_unit_width",
            "at_unit": "s",
            "at_raw": "1761292800123",
            "impl_reason_code": "AT_UNIT_CONTRADICTS_WIDTH",
            "reported_verdict": "FAIL",
        },
        "expect": "AT_UNIT_CONTRADICTS_WIDTH",
    },
    {
        "case_id": "AT-UNIT-WIDTH-OK-MS",
        "receipt": {
            "kind": "at_unit_width",
            "at_unit": "ms",
            "at_raw": "1761292800123",
            "reported_verdict": "PASS",
        },
        "expect": "AT_UNIT_WIDTH_OK",
    },
    {
        "case_id": "AT-UNIT-FALSE-PASS",
        "receipt": {
            "kind": "at_unit_width",
            "at_unit": "s",
            "at_raw": 1761292800123,
            "impl_reason_code": "OK",
            "reported_verdict": "PASS",
        },
        "expect": "AT_UNIT_FALSE_PASS",
    },
    {
        "case_id": "AT-UNIT-IMPLICIT",
        "receipt": {
            "kind": "at_unit_width",
            "at_unit": None,
            "at_raw": "1761292800123",
            "reported_verdict": "PASS",
        },
        "expect": "AT_UNIT_IMPLICIT",
    },
    # --- v0.4: duplicate key raw-text arm ---
    {
        "case_id": "DUPLICATE-KEY-TEXT-ONLY",
        "receipt": {
            "kind": "duplicate_key_text",
            "twin_raw": _TWIN_RAW,
            "mutant_raw": _MUTANT_DUP,
            "changed_key": "at",
            "parse_only_harness": False,
            "impl_reason_code": "DUPLICATE_KEY_TEXT_ONLY",
            "reported_verdict": "FAIL",
        },
        "expect": "DUPLICATE_KEY_TEXT_ONLY",
    },
    {
        "case_id": "PARSE-ONLY-MISSES-DUP-KEY",
        "receipt": {
            "kind": "duplicate_key_text",
            "twin_raw": _TWIN_RAW,
            "mutant_raw": _MUTANT_DUP,
            "changed_key": "at",
            "parse_only_harness": True,
            "impl_reason_code": "OK",
            "reported_verdict": "PASS",
        },
        "expect": "PARSE_ONLY_MISSES_DUP_KEY",
    },
    # --- v0.4 also via typed path: empty string / empty object ---
    {
        "case_id": "HB-COUNT-EMPTY-STRING-TYPED",
        "receipt": {
            "kind": "no_heartbeat_typed",
            "heartbeat_count": "",
            "impl_reason_code": "HB_COUNT_EMPTY_STRING",
            "reported_verdict": "FAIL",
        },
        "expect": "HB_COUNT_EMPTY_STRING",
    },
    {
        "case_id": "HB-COUNT-EMPTY-OBJECT-TYPED",
        "receipt": {
            "kind": "no_heartbeat_typed",
            "heartbeat_count": {},
            "impl_reason_code": "HB_COUNT_EMPTY_OBJECT",
            "reported_verdict": "FAIL",
        },
        "expect": "HB_COUNT_EMPTY_OBJECT",
    },
    # --- v0.3 retained: typed NO_HEARTBEAT smoke ---
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
        "case_id": "HB-COUNT-KEY-ABSENT",
        "receipt": {
            "kind": "no_heartbeat_typed",
            "impl_reason_code": "HB_COUNT_KEY_ABSENT",
            "reported_verdict": "INCONCLUSIVE",
        },
        "expect": "HB_COUNT_KEY_ABSENT",
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
    # --- v0.3: zero-delta ---
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
    # --- v0.3: must-fail protocol ---
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
        "version": "v0.4",
        "credit": "栀子花 Agent (v0.4 KEY_ABSENT empty-string sibling + existence-first + at_unit + DUPLICATE_KEY_TEXT_ONLY); 栀子花 (v0.3); 郑珺的hermes; 派蒙+Hermes (v0.1)",
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
