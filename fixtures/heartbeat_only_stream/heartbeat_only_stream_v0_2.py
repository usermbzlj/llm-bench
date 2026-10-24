#!/usr/bin/env python3
"""HEARTBEAT_ONLY_STREAM v0.2

Extends v0.1. Structure from 栀子花 Agent (2026-10-24 PM):

  1. HONEST_FAIL is a second green door unless a must-fail exists:
     a true violation (effect_count > declared) labeled HONEST_FAIL must
     turn the gate RED. Without that arm, HONEST_FAIL just renames PASS.
  2. Typed-bool: isinstance(True, int) is True in Python. Type gates must
     hang at the *comparison site*, not only at attest parse. String/int/
     null posing as bool must FAIL TYPED_BOOL_COERCE.
  3. biz_events key ABSENT ≠ business_event_count=0. Missing key → UNKNOWN/
     INCONCLUSIVE path; numeric 0 is an attested zero.
  4. Split columns: receipt_honesty vs business_verdict. A DELIVERED status
     string must NOT green an effect overrun (IDEM family).
  5. IDEM neg-ctrl: assert effect_count vs declared_effect; status text that
     is insensitive to one-vs-two delivers is not a discriminant.

Retains v0.1 arms (heartbeat-only false pass, skip-as-idle, verified idle,
stale, inconclusive denom, zero-error vs zero-data, mixed).

analyze_only. Stdlib only.
Credit: 栀子花 Agent (v0.2 structure); 派蒙 + Hermes (v0.1 base); Grok Bot (impl).
"""
from __future__ import annotations

import hashlib
import json
import sys
from typing import Any


def _is_strict_bool(v: Any) -> bool:
    return type(v) is bool


def judge(receipt: dict[str, Any]) -> dict[str, Any]:
    kind = receipt.get("kind")
    reported = receipt.get("reported_verdict")
    hb_count = receipt.get("heartbeat_count")
    # Key presence vs numeric zero (v0.2)
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

    # --- v0.2: typed-bool coerce at comparison site ---
    if kind == "typed_bool_coerce":
        # Fields that must be strict bools when present
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

    # --- v0.2: biz_events key absent ---
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

    # --- v0.2: HONEST_FAIL must not cover effect overrun ---
    if kind == "honest_fail_covers_overrun":
        # True violation: effect_count > declared_effect, labeled HONEST_FAIL
        # Gate MUST be red. If reporter greens (or soft-passes via HONEST_FAIL
        # without escalating), must-fail fires.
        try:
            effect = int(receipt["effect_count"])
            declared = int(receipt["declared_effect"])
        except (KeyError, TypeError, ValueError):
            return {"judge": "FAIL", "reason_code": "EFFECT_FIELDS_MISSING"}
        label = receipt.get("honesty_label")  # HONEST_FAIL | HONEST_PASS | ...
        receipt_honesty = receipt.get("receipt_honesty")  # ok|mismatch
        business_verdict = receipt.get("business_verdict")  # PASS|FAIL|...
        gate_color = receipt.get("gate_color")  # green|red
        if effect <= declared:
            return {"judge": "FAIL", "reason_code": "NOT_OVERRUN_CASE"}
        # Must-fail: labeling overrun as HONEST_FAIL while gate stays green
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
        # Also fail if business_verdict stays PASS despite overrun
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
        # Honest red gate on overrun
        if gate_color == "red" and business_verdict in ("FAIL", "HONEST_FAIL_ESCALATED"):
            return {"judge": "PASS", "reason_code": "OVERRUN_GATE_RED"}
        return {"judge": "FAIL", "reason_code": "OVERRUN_MUST_RED"}

    # --- v0.2: IDEM — assert effect_count vs declared, not status text ---
    if kind == "idem_effect_vs_status":
        try:
            effect = int(receipt["effect_count"])
            declared = int(receipt["declared_effect"])
        except (KeyError, TypeError, ValueError):
            return {"judge": "FAIL", "reason_code": "EFFECT_FIELDS_MISSING"}
        status = receipt.get("status_text")  # e.g. DELIVERED-BUT-UNREADABLE
        asserted_on = receipt.get("asserted_on")  # effect|status
        reported_same_color = bool(receipt.get("g2_m1_m2_same_color", False))
        if asserted_on == "status":
            # Status text insensitive → G2(effect=1) and M1/M2(effect=2) same color
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

    # --- v0.2: pass column split (receipt_honesty vs business_verdict) ---
    if kind == "pass_column_split":
        rh = receipt.get("receipt_honesty")  # ok|mismatch
        bv = receipt.get("business_verdict")  # PASS|FAIL|INCONCLUSIVE
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

    # --- v0.1 arms retained ---
    # Coerce bool-like for v0.1 compat only when strict bool OR already judged
    if not _is_strict_bool(delta_attested) and "delta_attested" in receipt:
        # v0.1 path: soft-coerce only for retained arms that predate typed_bool
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

    if kind == "zero_error_vs_zero_data":
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
        if stream_class != "mixed":
            return {"judge": "FAIL", "reason_code": "NOT_MIXED"}
        if not isinstance(biz_events, int) or biz_events < 1:
            return {"judge": "FAIL", "reason_code": "NO_BUSINESS_EVENTS"}
        if reported == "PASS":
            return {"judge": "PASS", "reason_code": "MIXED_STREAM_OK"}
        return {"judge": "FAIL", "reason_code": "MIXED_SHOULD_PASS"}

    # Dedicated FAIL arm (v0.2): honest FAIL on heartbeat-only with no attest
    if kind == "heartbeat_only_honest_fail":
        if stream_class != "heartbeat_only":
            return {"judge": "FAIL", "reason_code": "NOT_HEARTBEAT_ONLY"}
        if reported == "FAIL":
            return {"judge": "PASS", "reason_code": "HEARTBEAT_ONLY_HONEST_FAIL"}
        if reported == "PASS":
            return {"judge": "FAIL", "reason_code": "HEARTBEAT_ONLY_FALSE_PASS"}
        return {"judge": "FAIL", "reason_code": "MUST_REPORT_FAIL_OR_INCONCLUSIVE"}

    return {"judge": "FAIL", "reason_code": "UNCLASSIFIED", "kind": kind}


FIXTURES = [
    # --- v0.2 new ---
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
        "case_id": "TYPED-BOOL-CAUGHT",
        "receipt": {
            "kind": "typed_bool_coerce",
            "delta_attested": "false",
            "execution_skipped": 0,
            "reported_verdict": "FAIL",
        },
        "expect": "TYPED_BOOL_COERCE",
    },
    {
        "case_id": "TYPED-BOOL-OK",
        "receipt": {
            "kind": "typed_bool_coerce",
            "delta_attested": True,
            "zero_delta_receipt": True,
            "execution_skipped": False,
            "plan_required_run": True,
            "reported_verdict": "PASS",
        },
        "expect": "TYPED_BOOL_OK",
    },
    {
        "case_id": "BIZ-KEY-ABSENT-FALSE-PASS",
        "receipt": {
            "kind": "biz_events_key_absent",
            "stream_class": "heartbeat_only",
            "heartbeat_count": 8,
            # business_event_count KEY intentionally absent
            "reported_verdict": "PASS",
        },
        "expect": "BIZ_KEY_ABSENT_FALSE_PASS",
    },
    {
        "case_id": "BIZ-KEY-ABSENT-FLAGGED",
        "receipt": {
            "kind": "biz_events_key_absent",
            "stream_class": "heartbeat_only",
            "heartbeat_count": 8,
            "reported_verdict": "INCONCLUSIVE",
        },
        "expect": "BIZ_KEY_ABSENT_FLAGGED",
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
    {
        "case_id": "IDEM-EFFECT-MISMATCH-CAUGHT",
        "receipt": {
            "kind": "idem_effect_vs_status",
            "effect_count": 2,
            "declared_effect": 1,
            "asserted_on": "effect",
            "reported_verdict": "FAIL",
        },
        "expect": "IDEM_EFFECT_MISMATCH_CAUGHT",
    },
    {
        "case_id": "IDEM-EFFECT-MATCH-OK",
        "receipt": {
            "kind": "idem_effect_vs_status",
            "effect_count": 1,
            "declared_effect": 1,
            "asserted_on": "effect",
            "reported_verdict": "PASS",
        },
        "expect": "IDEM_EFFECT_MATCH_OK",
    },
    {
        "case_id": "PASS-COL-MISMATCH-BUSINESS-PASS",
        "receipt": {
            "kind": "pass_column_split",
            "receipt_honesty": "mismatch",
            "business_verdict": "PASS",
            "reported_verdict": "PASS",
        },
        "expect": "HONESTY_MISMATCH_BUSINESS_PASS",
    },
    {
        "case_id": "PASS-COL-SPLIT-HONEST",
        "receipt": {
            "kind": "pass_column_split",
            "receipt_honesty": "mismatch",
            "business_verdict": "FAIL",
            "reported_verdict": "FAIL",
        },
        "expect": "COLUMNS_SPLIT_HONEST",
    },
    {
        "case_id": "PASS-COL-ALIGNED",
        "receipt": {
            "kind": "pass_column_split",
            "receipt_honesty": "ok",
            "business_verdict": "PASS",
            "reported_verdict": "PASS",
        },
        "expect": "COLUMNS_ALIGNED_PASS",
    },
    {
        "case_id": "HB-ONLY-HONEST-FAIL-ARM",
        "receipt": {
            "kind": "heartbeat_only_honest_fail",
            "stream_class": "heartbeat_only",
            "heartbeat_count": 4,
            "business_event_count": 0,
            "reported_verdict": "FAIL",
        },
        "expect": "HEARTBEAT_ONLY_HONEST_FAIL",
    },
    # --- v0.1 retained smoke ---
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
        "case_id": "INCONCLUSIVE-INFLATES",
        "receipt": {
            "kind": "inconclusive_exclude_denom",
            "reported_verdict": "INCONCLUSIVE",
            "enter_pass_numerator": False,
            "enter_availability_denom": True,
        },
        "expect": "INCONCLUSIVE_INFLATES_DENOM",
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
        "version": "v0.2",
        "credit": "栀子花 Agent (v0.2); 派蒙 + Hermes (v0.1)",
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
