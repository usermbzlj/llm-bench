#!/usr/bin/env python3
"""FALSE_ZERO v0.5

Extends FALSE_ZERO v0.4 with EigenFlux inbound 2026-10-24 desensitized shapes
(analyze_only; no invented peer JSONL beyond the shapes below).

  A) FALSE_GREEN_TRANSPORT (credit WorkBuddy)
     Desensitized L2: host_departure=TLS handshake timeout (during write/send);
     readback_effect=stdout prints success + exit 0, but server history has no
     matching msg_id (4 fails then 5th lands).
     Rule: stdout+exit are NOT trusted; only server readback is authority;
     resend with same content is idempotent (new msg_id, no duplicate).
     Must-fail when reported_verdict=PASS / enter_pass while
     server_readback_present=false and exit_code=0 and stdout_looks_green=true.
     Honest catch: reported FAIL/FALSE_GREEN_TRANSPORT/DEGRADED.
     Honest PASS: server_readback_present=true with matching msg_id + exit 0.

  B) SKIP_GREEN_NO_RECEIPT (credit Talaria)
     cls SKIP: planned_items from planner (out-of-loop), executed=0, exit_code=0,
     report=green, evidence scheduler_receipt=absent → must-fail
     NOT_FIRED / SKIP_GREEN_NO_RECEIPT when reported PASS.
     Criterion is the combo (no execution receipt AND report green), NOT
     executed==0 alone (true-zero results also have 0).
     planned_items and executed MUST be separate columns (merging = self-proof).

  C) SELF_REFUTED_EXPECTATION (credit Talaria)
     expected_digest_source == validator_source (same run_id) → must not enter
     pass denominator → EXPECTATION_SAME_AS_SUBJECT / SELF_REFUTED when
     reported PASS. Honest: sources differ → may PASS.

  D) RAN_WITH_RECEIPT positive control (credit Talaria)
     executed==planned, scheduler_receipt present (sha placeholder),
     report green → honest PASS path.

Retains all v0.4 arms + regression anchors (小清新 presence_flags /
郑珺 SKIPPED_TASK_ZERO_ERROR / H+WorkBuddy dedup+read_source anchors).

New reason codes (must-fail when reported_verdict wrongly PASS):
  FALSE_GREEN_TRANSPORT
  SKIP_GREEN_NO_RECEIPT
  SELF_REFUTED_EXPECTATION

analyze_only. Stdlib only.
Credit: WorkBuddy (FALSE_GREEN_TRANSPORT); Talaria (SKIP_GREEN_NO_RECEIPT +
        SELF_REFUTED_EXPECTATION + RAN_WITH_RECEIPT); 小清新 | 郑珺 (v0.4
        anchors retained); Grok Bot (impl).
"""
from __future__ import annotations

import hashlib
import json
import sys
from typing import Any


def _norm(v: Any) -> str | None:
    if v is None or v == "":
        return None
    return str(v)


def _as_int(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _as_float(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _key_state(obj: dict[str, Any], key: str) -> str:
    """Return 'absent' | 'null' | 'present' for a required key."""
    if key not in obj:
        return "absent"
    if obj[key] is None:
        return "null"
    return "present"


def judge(receipt: dict[str, Any]) -> dict[str, Any]:
    kind = receipt.get("kind")
    reported = receipt.get("reported_verdict")
    observed_reason = _norm(receipt.get("observed_reason_code"))
    arm_executed = receipt.get("arm_executed")
    n_unprobed = _as_int(receipt.get("n_unprobed"))
    n_executed = _as_int(receipt.get("n_executed"))
    enter_pass = receipt.get("enter_pass_numerator")
    # Counts that treat unprobed / skipped as numeric 0
    counted_as_zero = bool(receipt.get("counted_unprobed_as_zero", False)) or bool(
        receipt.get("counted_skipped_as_zero", False)
    )

    # ------------------------------------------------------------------
    # Shared guard: NOT_YET_RUN / empty-observed must never score as PASS
    # or as numeric 0 in counts; n_unprobed must be reported separately.
    # ------------------------------------------------------------------
    if kind in (
        "presence_flag",
        "denominator",
        "key_absent",
        "declared_null",
        "partial_reason",
        "presence_propagate",
        "not_yet_run",
        "arm_skipped",
        "skipped_task_zero_error",
    ):
        # Constructed / not-run path
        if observed_reason == "NOT_YET_RUN" or (
            receipt.get("observed") in (None, "", {}, [])
            and receipt.get("constructed") is True
        ):
            if reported == "PASS" or enter_pass is True or counted_as_zero:
                return {
                    "judge": "FAIL",
                    "reason_code": "NOT_YET_RUN_AS_PASS",
                    "detail": {
                        "observed_reason_code": observed_reason,
                        "reported_verdict": reported,
                        "n_unprobed": n_unprobed,
                    },
                }
            # Honest NOT_YET_RUN: n_unprobed ≥ 1, no PASS, no numeric 0 fold
            if (n_unprobed or 0) >= 1 and reported not in ("PASS",):
                # Still fall through to kind-specific checks for the *expected*
                # structural failure class, but never invent PASS/FAIL success.
                pass

        # arm_executed=false must not enter pass numerator / shrink denom
        if arm_executed is False:
            if reported == "PASS" or enter_pass is True:
                # Prefer more specific arm reason below; ARM_SKIPPED is the
                # generic catch when kind is arm_skipped or no more-specific hit.
                if kind == "arm_skipped" or receipt.get("force_arm_skipped_code"):
                    return {
                        "judge": "FAIL",
                        "reason_code": "ARM_SKIPPED_COUNTED_AS_ZERO",
                        "detail": {"arm_executed": False, "enter_pass": enter_pass},
                    }

    # --- Arm: PRESENCE_FLAG_NOT_HONORED (小清新 fz-001) ---
    if kind == "presence_flag":
        presence_declared_by = _norm(receipt.get("presence_declared_by"))
        presence_reason = _norm(receipt.get("presence_reason"))
        reader_treated_complete = bool(receipt.get("reader_treated_complete", False))
        if presence_declared_by is not None or presence_reason is not None:
            # Honest catch first: reader ignored presence but reported FAIL/DEGRADED
            if reported in ("FAIL", "PRESENCE_FLAG_NOT_HONORED", "DEGRADED"):
                return {"judge": "PASS", "reason_code": "PRESENCE_FLAG_CAUGHT"}
            if observed_reason == "NOT_YET_RUN" and (n_unprobed or 0) >= 1:
                return {"judge": "PASS", "reason_code": "PRESENCE_FLAG_UNPROBED"}
            if reader_treated_complete or reported == "PASS":
                return {
                    "judge": "FAIL",
                    "reason_code": "PRESENCE_FLAG_NOT_HONORED",
                    "detail": {
                        "presence_declared_by": presence_declared_by,
                        "presence_reason": presence_reason,
                        "arm_executed": arm_executed,
                    },
                }
        return {"judge": "FAIL", "reason_code": "PRESENCE_FLAG_UNHANDLED"}

    # --- Arm: DENOMINATOR_UNANCHORED (小清新 fz-002) ---
    if kind == "denominator":
        expected_rows = receipt.get("expected_rows")
        expected_rows_absent = expected_rows is None or (
            isinstance(expected_rows, (list, dict, str)) and len(expected_rows) == 0
        )
        denom_adjusted = bool(receipt.get("denominator_adjusted", False))
        if expected_rows_absent and not denom_adjusted:
            if reported == "PASS" or enter_pass is True:
                return {
                    "judge": "FAIL",
                    "reason_code": "DENOMINATOR_UNANCHORED",
                    "detail": {
                        "expected_rows": expected_rows,
                        "arm_executed": arm_executed,
                    },
                }
            if reported in ("FAIL", "DENOMINATOR_UNANCHORED", "DEGRADED"):
                return {"judge": "PASS", "reason_code": "DENOMINATOR_CAUGHT"}
            if observed_reason == "NOT_YET_RUN" and (n_unprobed or 0) >= 1:
                return {"judge": "PASS", "reason_code": "DENOMINATOR_UNPROBED"}
        if not expected_rows_absent and denom_adjusted and reported in ("PASS", "FAIL"):
            return {"judge": "PASS", "reason_code": "DENOMINATOR_ANCHORED"}
        return {"judge": "FAIL", "reason_code": "DENOMINATOR_UNHANDLED"}

    # --- Arm: KEY_ABSENT (小清新 fz-003) ---
    if kind == "key_absent":
        payload = receipt.get("payload")
        required_key = _norm(receipt.get("required_key")) or "value"
        if not isinstance(payload, dict):
            return {"judge": "FAIL", "reason_code": "PAYLOAD_MISSING"}
        state = _key_state(payload, required_key)
        if state == "absent":
            if reported == "PASS" or enter_pass is True or counted_as_zero:
                # Wrongly scoring absent-as-pass / as zero
                if observed_reason == "NOT_YET_RUN" or receipt.get("constructed"):
                    return {
                        "judge": "FAIL",
                        "reason_code": "NOT_YET_RUN_AS_PASS",
                        "detail": {"key": required_key, "state": state},
                    }
                return {
                    "judge": "FAIL",
                    "reason_code": "KEY_ABSENT",
                    "detail": {"key": required_key},
                }
            if reported in ("FAIL", "KEY_ABSENT") or observed_reason == "NOT_YET_RUN":
                # Honest: surface KEY_ABSENT class, or leave as NOT_YET_RUN
                if observed_reason == "NOT_YET_RUN" and (n_unprobed or 0) >= 1:
                    return {
                        "judge": "PASS",
                        "reason_code": "KEY_ABSENT_UNPROBED",
                        "detail": {"key": required_key},
                    }
                return {"judge": "PASS", "reason_code": "KEY_ABSENT_CAUGHT"}
        return {"judge": "FAIL", "reason_code": "KEY_ABSENT_UNHANDLED", "detail": {"state": state}}

    # --- Arm: DECLARED_NULL_MUST_BE_DISTINCT_FROM_UNDECLARED (小清新 fz-004) ---
    if kind == "declared_null":
        payload = receipt.get("payload")
        required_key = _norm(receipt.get("required_key")) or "value"
        if not isinstance(payload, dict):
            return {"judge": "FAIL", "reason_code": "PAYLOAD_MISSING"}
        state = _key_state(payload, required_key)
        class_reported = _norm(receipt.get("null_vs_absent_class"))
        # Classes must be distinct: 'declared_null' vs 'key_absent'
        collapsed = bool(receipt.get("collapsed_null_and_absent", False))
        presence_declared_by = _norm(receipt.get("presence_declared_by"))
        presence_reason = _norm(receipt.get("presence_reason"))
        if state == "null" and (
            collapsed
            or class_reported in (None, "key_absent", "absent", "undeclared")
            or (presence_declared_by is not None and class_reported != "declared_null")
        ):
            if reported == "PASS" or enter_pass is True:
                return {
                    "judge": "FAIL",
                    "reason_code": "DECLARED_NULL_MUST_BE_DISTINCT_FROM_UNDECLARED",
                    "detail": {
                        "state": state,
                        "null_vs_absent_class": class_reported,
                        "presence_declared_by": presence_declared_by,
                        "presence_reason": presence_reason,
                    },
                }
            if reported in (
                "FAIL",
                "DECLARED_NULL_MUST_BE_DISTINCT_FROM_UNDECLARED",
                "DEGRADED",
            ):
                return {"judge": "PASS", "reason_code": "DECLARED_NULL_CAUGHT"}
            if observed_reason == "NOT_YET_RUN" and (n_unprobed or 0) >= 1:
                return {"judge": "PASS", "reason_code": "DECLARED_NULL_UNPROBED"}
        if state == "null" and class_reported == "declared_null" and not collapsed:
            if reported in ("PASS", "FAIL"):
                return {"judge": "PASS", "reason_code": "DECLARED_NULL_DISTINCT"}
        return {"judge": "FAIL", "reason_code": "DECLARED_NULL_UNHANDLED", "detail": {"state": state}}

    # --- Arm: PARTIAL_REASON_MISSING (小清新 fz-005) ---
    if kind == "partial_reason":
        partial_declared = bool(receipt.get("partial_declared", False))
        partial_reasons = receipt.get("partial_reasons")
        reasons_absent = partial_reasons is None or (
            isinstance(partial_reasons, (list, dict, str)) and len(partial_reasons) == 0
        )
        if partial_declared and reasons_absent:
            if reported == "PASS" or enter_pass is True:
                return {
                    "judge": "FAIL",
                    "reason_code": "PARTIAL_REASON_MISSING",
                    "detail": {"partial_declared": True, "partial_reasons": partial_reasons},
                }
            if reported in ("FAIL", "PARTIAL_REASON_MISSING", "DEGRADED"):
                return {"judge": "PASS", "reason_code": "PARTIAL_REASON_CAUGHT"}
            if observed_reason == "NOT_YET_RUN" and (n_unprobed or 0) >= 1:
                return {"judge": "PASS", "reason_code": "PARTIAL_REASON_UNPROBED"}
        if partial_declared and not reasons_absent and reported in ("PASS", "FAIL"):
            return {"judge": "PASS", "reason_code": "PARTIAL_REASON_PRESENT"}
        return {"judge": "FAIL", "reason_code": "PARTIAL_REASON_UNHANDLED"}

    # --- Arm: DECLARED_PRESENCE_NOT_PROPAGATED (小清新 fz-006) ---
    if kind == "presence_propagate":
        upstream_declared = bool(receipt.get("upstream_presence_declared", False))
        downstream_present = receipt.get("downstream_presence")
        downstream_absent = downstream_present in (None, False, "", {}, [])
        if upstream_declared and downstream_absent:
            if reported == "PASS" or enter_pass is True:
                return {
                    "judge": "FAIL",
                    "reason_code": "DECLARED_PRESENCE_NOT_PROPAGATED",
                    "detail": {
                        "upstream_presence_declared": True,
                        "downstream_presence": downstream_present,
                    },
                }
            if reported in (
                "FAIL",
                "DECLARED_PRESENCE_NOT_PROPAGATED",
                "DEGRADED",
            ):
                return {"judge": "PASS", "reason_code": "PRESENCE_PROPAGATE_CAUGHT"}
            if observed_reason == "NOT_YET_RUN" and (n_unprobed or 0) >= 1:
                return {"judge": "PASS", "reason_code": "PRESENCE_PROPAGATE_UNPROBED"}
        if upstream_declared and not downstream_absent and reported in ("PASS", "FAIL"):
            return {"judge": "PASS", "reason_code": "PRESENCE_PROPAGATED"}
        return {"judge": "FAIL", "reason_code": "PRESENCE_PROPAGATE_UNHANDLED"}

    # --- Arm: NOT_YET_RUN_AS_PASS (generic constructed) ---
    if kind == "not_yet_run":
        if observed_reason == "NOT_YET_RUN" or receipt.get("observed") in (None, "", {}, []):
            if reported == "PASS" or enter_pass is True or counted_as_zero:
                return {
                    "judge": "FAIL",
                    "reason_code": "NOT_YET_RUN_AS_PASS",
                    "detail": {
                        "n_unprobed": n_unprobed,
                        "counted_as_zero": counted_as_zero,
                    },
                }
            if (n_unprobed or 0) >= 1 and reported not in ("PASS",):
                return {"judge": "PASS", "reason_code": "NOT_YET_RUN_HONEST"}
        return {"judge": "FAIL", "reason_code": "NOT_YET_RUN_UNHANDLED"}

    # --- Arm: ARM_SKIPPED_COUNTED_AS_ZERO (口径 1) ---
    if kind == "arm_skipped":
        if arm_executed is False:
            if reported == "PASS" or enter_pass is True or counted_as_zero:
                return {
                    "judge": "FAIL",
                    "reason_code": "ARM_SKIPPED_COUNTED_AS_ZERO",
                    "detail": {
                        "arm_executed": False,
                        "enter_pass_numerator": enter_pass,
                        "counted_skipped_as_zero": counted_as_zero,
                    },
                }
            if reported in ("FAIL", "SKIPPED", "ARM_SKIPPED", "DEGRADED", "UNKNOWN"):
                return {"judge": "PASS", "reason_code": "ARM_SKIPPED_CAUGHT"}
        if arm_executed is True and reported in ("PASS", "FAIL"):
            return {"judge": "PASS", "reason_code": "ARM_EXECUTED_OK"}
        return {"judge": "FAIL", "reason_code": "ARM_SKIPPED_UNHANDLED"}

    # --- Arm: SKIPPED_TASK_ZERO_ERROR (郑珺的hermes) ---
    if kind == "skipped_task_zero_error":
        error_rate = _as_float(receipt.get("error_rate"))
        # n_executed==0 + error_rate==0 + reported PASS → FALSE_ZERO
        if (n_executed or 0) == 0 and error_rate is not None and error_rate == 0.0:
            if reported == "PASS" or enter_pass is True:
                return {
                    "judge": "FAIL",
                    "reason_code": "SKIPPED_TASK_ZERO_ERROR",
                    "detail": {
                        "n_executed": n_executed,
                        "error_rate": error_rate,
                        "note": "pipeline health must use task-completion denominator",
                    },
                }
            if reported in (
                "FAIL",
                "SKIPPED_TASK_ZERO_ERROR",
                "ERROR_RATE_WITHOUT_EXEC",
                "DEGRADED",
                "UNKNOWN",
            ):
                return {"judge": "PASS", "reason_code": "SKIPPED_TASK_CAUGHT"}
        # Honest: n_executed>0 with real errors
        if (n_executed or 0) > 0 and error_rate is not None and error_rate > 0.0:
            if reported in ("PASS", "FAIL"):
                return {"judge": "PASS", "reason_code": "ERROR_RATE_HONEST"}
        # Honest: n_executed>0 and error_rate==0 with real execution
        if (n_executed or 0) > 0 and error_rate == 0.0 and reported == "PASS":
            return {"judge": "PASS", "reason_code": "ZERO_ERROR_WITH_EXEC"}
        return {
            "judge": "FAIL",
            "reason_code": "SKIPPED_TASK_UNHANDLED",
            "detail": {"n_executed": n_executed, "error_rate": error_rate},
        }

    # --- Arm: FALSE_GREEN_TRANSPORT (WorkBuddy) ---
    if kind == "false_green_transport":
        exit_code = _as_int(receipt.get("exit_code"))
        stdout_looks_green = bool(receipt.get("stdout_looks_green", False))
        server_readback_present = bool(receipt.get("server_readback_present", False))
        msg_id_match = bool(receipt.get("msg_id_match", False))
        host_departure = _norm(receipt.get("host_departure"))
        # Must-fail: green stdout+exit0 but no server readback authority
        if (
            (exit_code == 0)
            and stdout_looks_green
            and (not server_readback_present)
        ):
            if reported == "PASS" or enter_pass is True:
                return {
                    "judge": "FAIL",
                    "reason_code": "FALSE_GREEN_TRANSPORT",
                    "detail": {
                        "exit_code": exit_code,
                        "stdout_looks_green": stdout_looks_green,
                        "server_readback_present": False,
                        "host_departure": host_departure,
                        "note": "stdout+exit not trusted; only server readback is authority",
                    },
                }
            if reported in (
                "FAIL",
                "FALSE_GREEN_TRANSPORT",
                "DEGRADED",
            ):
                return {"judge": "PASS", "reason_code": "FALSE_GREEN_TRANSPORT_CAUGHT"}
        # Honest PASS: server readback present with matching msg_id + exit 0
        if (
            server_readback_present
            and msg_id_match
            and (exit_code == 0)
            and reported == "PASS"
        ):
            return {"judge": "PASS", "reason_code": "FALSE_GREEN_TRANSPORT_HONEST_PASS"}
        return {
            "judge": "FAIL",
            "reason_code": "FALSE_GREEN_TRANSPORT_UNHANDLED",
            "detail": {
                "exit_code": exit_code,
                "server_readback_present": server_readback_present,
                "msg_id_match": msg_id_match,
            },
        }

    # --- Arm: SKIP_GREEN_NO_RECEIPT (Talaria) ---
    if kind == "skip_green_no_receipt":
        # planned_items and executed MUST be separate columns
        planned_items = receipt.get("planned_items")
        executed = _as_int(receipt.get("executed"))
        exit_code = _as_int(receipt.get("exit_code"))
        report_green = bool(receipt.get("report_green", False))
        scheduler_receipt = receipt.get("scheduler_receipt")
        receipt_absent = scheduler_receipt in (None, "", {}, [], "absent")
        # merged columns = self-proof failure signal (optional field)
        columns_merged = bool(receipt.get("planned_executed_merged", False))
        if columns_merged:
            if reported == "PASS" or enter_pass is True:
                return {
                    "judge": "FAIL",
                    "reason_code": "SKIP_GREEN_NO_RECEIPT",
                    "detail": {"note": "planned_items and executed must be separate columns"},
                }
        # Criterion: combo (no receipt AND report green) — NOT executed==0 alone
        planned_n = 0
        if isinstance(planned_items, list):
            planned_n = len(planned_items)
        elif isinstance(planned_items, int):
            planned_n = planned_items
        elif planned_items not in (None, ""):
            try:
                planned_n = int(planned_items)
            except (TypeError, ValueError):
                planned_n = 1 if planned_items else 0
        if receipt_absent and report_green and (exit_code == 0):
            if reported == "PASS" or enter_pass is True:
                return {
                    "judge": "FAIL",
                    "reason_code": "SKIP_GREEN_NO_RECEIPT",
                    "detail": {
                        "planned_items": planned_n,
                        "executed": executed,
                        "scheduler_receipt": "absent",
                        "report_green": True,
                        "note": "combo(no receipt AND green); executed==0 alone is not enough",
                    },
                }
            if reported in (
                "FAIL",
                "SKIP_GREEN_NO_RECEIPT",
                "NOT_FIRED",
                "DEGRADED",
            ):
                return {"judge": "PASS", "reason_code": "SKIP_GREEN_NO_RECEIPT_CAUGHT"}
        return {
            "judge": "FAIL",
            "reason_code": "SKIP_GREEN_NO_RECEIPT_UNHANDLED",
            "detail": {
                "executed": executed,
                "receipt_absent": receipt_absent,
                "report_green": report_green,
            },
        }

    # --- Arm: SELF_REFUTED_EXPECTATION (Talaria) ---
    if kind == "self_refuted_expectation":
        expected_digest_source = _norm(receipt.get("expected_digest_source"))
        validator_source = _norm(receipt.get("validator_source"))
        run_id_expected = _norm(receipt.get("expected_run_id"))
        run_id_validator = _norm(receipt.get("validator_run_id"))
        same_source = (
            expected_digest_source is not None
            and validator_source is not None
            and expected_digest_source == validator_source
        )
        same_run = (
            run_id_expected is not None
            and run_id_validator is not None
            and run_id_expected == run_id_validator
        )
        # same run_id OR identical source string → self-refuted
        if same_source or same_run:
            if reported == "PASS" or enter_pass is True:
                return {
                    "judge": "FAIL",
                    "reason_code": "SELF_REFUTED_EXPECTATION",
                    "detail": {
                        "expected_digest_source": expected_digest_source,
                        "validator_source": validator_source,
                        "expected_run_id": run_id_expected,
                        "validator_run_id": run_id_validator,
                        "alias": "EXPECTATION_SAME_AS_SUBJECT",
                    },
                }
            if reported in (
                "FAIL",
                "SELF_REFUTED_EXPECTATION",
                "EXPECTATION_SAME_AS_SUBJECT",
                "SELF_REFUTED",
                "DEGRADED",
            ):
                return {"judge": "PASS", "reason_code": "SELF_REFUTED_CAUGHT"}
        # Honest: sources differ → may PASS
        if (
            expected_digest_source is not None
            and validator_source is not None
            and expected_digest_source != validator_source
            and not same_run
            and reported in ("PASS", "FAIL")
        ):
            return {"judge": "PASS", "reason_code": "EXPECTATION_INDEPENDENT"}
        return {
            "judge": "FAIL",
            "reason_code": "SELF_REFUTED_UNHANDLED",
            "detail": {
                "expected_digest_source": expected_digest_source,
                "validator_source": validator_source,
            },
        }

    # --- Arm: RAN_WITH_RECEIPT positive control (Talaria) ---
    if kind == "ran_with_receipt":
        planned_items = receipt.get("planned_items")
        executed = _as_int(receipt.get("executed"))
        scheduler_receipt = receipt.get("scheduler_receipt")
        report_green = bool(receipt.get("report_green", False))
        receipt_present = scheduler_receipt not in (None, "", {}, [], "absent")
        planned_n = 0
        if isinstance(planned_items, list):
            planned_n = len(planned_items)
        elif isinstance(planned_items, int):
            planned_n = planned_items
        elif planned_items not in (None, ""):
            try:
                planned_n = int(planned_items)
            except (TypeError, ValueError):
                planned_n = 0
        if (
            receipt_present
            and executed is not None
            and executed == planned_n
            and planned_n > 0
            and report_green
            and reported == "PASS"
        ):
            return {"judge": "PASS", "reason_code": "RAN_WITH_RECEIPT"}
        return {
            "judge": "FAIL",
            "reason_code": "RAN_WITH_RECEIPT_UNHANDLED",
            "detail": {
                "planned": planned_n,
                "executed": executed,
                "receipt_present": receipt_present,
            },
        }

    # --- Regression anchors from v0.3 (compact) ---
    if kind == "dedup_collision_anchor":
        # Compact: same key + different fp merged-to-1 + PASS → FALSE_ZERO
        declared = _as_int(receipt.get("declared"))
        merge_predicate = _norm(receipt.get("merge_predicate"))
        if declared == 1 or merge_predicate == "key_only":
            if reported == "PASS":
                return {
                    "judge": "FAIL",
                    "reason_code": "DEDUP_COLLISION_MERGED_FALSE_ZERO",
                }
        if declared == 2 and merge_predicate == "dual_key" and reported == "PASS":
            return {"judge": "PASS", "reason_code": "DEDUP_COLLISION_KEPT"}
        return {"judge": "FAIL", "reason_code": "DEDUP_ANCHOR_UNHANDLED"}

    if kind == "read_source_mixup_anchor":
        count_source = _norm(receipt.get("count_source"))
        assert_source = _norm(receipt.get("assert_source"))
        if count_source is not None and assert_source is not None and count_source != assert_source:
            if reported == "PASS" or enter_pass is True:
                return {
                    "judge": "FAIL",
                    "reason_code": "READ_SOURCE_MIXUP_FALSE_ZERO",
                    "detail": {
                        "count_source": count_source,
                        "assert_source": assert_source,
                    },
                }
            if reported in ("FAIL", "READ_SOURCE_MIXUP", "DEGRADED"):
                return {"judge": "PASS", "reason_code": "READ_SOURCE_MIXUP_CAUGHT"}
        if count_source == assert_source and reported in ("PASS", "FAIL"):
            return {"judge": "PASS", "reason_code": "READ_SOURCE_ALIGNED"}
        return {"judge": "FAIL", "reason_code": "READ_SOURCE_ANCHOR_UNHANDLED"}

    return {"judge": "FAIL", "reason_code": "UNKNOWN_KIND"}


def cases() -> list[dict[str, Any]]:
    return [
        # ----- 小清新 fz-001 PRESENCE_FLAG_NOT_HONORED (real, arm skipped) -----
        {
            "id": "fz001_mf_presence_flag_not_honored",
            "kind": "presence_flag",
            "presence_declared_by": "upstream_discovery_block",
            "presence_reason": "history_truncated+scan_budget",
            "reader_treated_complete": True,
            "arm_executed": False,
            "reported_verdict": "PASS",
            "expect_reason": "PRESENCE_FLAG_NOT_HONORED",
        },
        {
            "id": "fz001_ok_presence_flag_caught",
            "kind": "presence_flag",
            "presence_declared_by": "upstream_discovery_block",
            "presence_reason": "history_truncated+scan_budget",
            "reader_treated_complete": True,
            "arm_executed": True,
            "reported_verdict": "FAIL",
            "expect_reason": "PRESENCE_FLAG_CAUGHT",
        },
        # ----- 小清新 fz-002 DENOMINATOR_UNANCHORED (real, arm skipped) -----
        {
            "id": "fz002_mf_denominator_unanchored",
            "kind": "denominator",
            "expected_rows": None,
            "denominator_adjusted": False,
            "arm_executed": False,
            "reported_verdict": "PASS",
            "expect_reason": "DENOMINATOR_UNANCHORED",
        },
        {
            "id": "fz002_ok_denominator_caught",
            "kind": "denominator",
            "expected_rows": [],
            "denominator_adjusted": False,
            "arm_executed": True,
            "reported_verdict": "DENOMINATOR_UNANCHORED",
            "expect_reason": "DENOMINATOR_CAUGHT",
        },
        # ----- 小清新 fz-003 KEY_ABSENT (constructed NOT_YET_RUN) -----
        {
            "id": "fz003_mf_key_absent_scored_pass",
            "kind": "key_absent",
            "payload": {"other": 1},
            "required_key": "value",
            "constructed": True,
            "observed": None,
            "observed_reason_code": "NOT_YET_RUN",
            "n_unprobed": 0,
            "reported_verdict": "PASS",
            "expect_reason": "NOT_YET_RUN_AS_PASS",
        },
        {
            "id": "fz003_ok_key_absent_unprobed",
            "kind": "key_absent",
            "payload": {"other": 1},
            "required_key": "value",
            "constructed": True,
            "observed": None,
            "observed_reason_code": "NOT_YET_RUN",
            "n_unprobed": 1,
            "reported_verdict": "NOT_YET_RUN",
            "expect_reason": "KEY_ABSENT_UNPROBED",
        },
        # ----- 小清新 fz-004 DECLARED_NULL vs UNDECLARED -----
        {
            "id": "fz004_mf_declared_null_collapsed",
            "kind": "declared_null",
            "payload": {"value": None},
            "required_key": "value",
            "null_vs_absent_class": "key_absent",
            "collapsed_null_and_absent": True,
            "presence_declared_by": "upstream_row",
            "presence_reason": "value_is_null_but_key_present",
            "constructed": True,
            "observed_reason_code": "NOT_YET_RUN",
            "n_unprobed": 0,
            "reported_verdict": "PASS",
            "expect_reason": "NOT_YET_RUN_AS_PASS",
        },
        {
            "id": "fz004_mf_declared_null_distinct_class",
            "kind": "declared_null",
            "payload": {"value": None},
            "required_key": "value",
            "null_vs_absent_class": "undeclared",
            "collapsed_null_and_absent": False,
            "presence_declared_by": "upstream_row",
            "presence_reason": "value_is_null_but_key_present",
            "arm_executed": True,
            "reported_verdict": "PASS",
            "expect_reason": "DECLARED_NULL_MUST_BE_DISTINCT_FROM_UNDECLARED",
        },
        {
            "id": "fz004_ok_declared_null_unprobed",
            "kind": "declared_null",
            "payload": {"value": None},
            "required_key": "value",
            "null_vs_absent_class": "key_absent",
            "collapsed_null_and_absent": True,
            "presence_declared_by": "upstream_row",
            "presence_reason": "value_is_null_but_key_present",
            "constructed": True,
            "observed_reason_code": "NOT_YET_RUN",
            "n_unprobed": 1,
            "reported_verdict": "NOT_YET_RUN",
            "expect_reason": "DECLARED_NULL_UNPROBED",
        },
        # ----- 小清新 fz-005 PARTIAL_REASON_MISSING -----
        {
            "id": "fz005_mf_partial_reason_missing",
            "kind": "partial_reason",
            "partial_declared": True,
            "partial_reasons": None,
            "arm_executed": True,
            "reported_verdict": "PASS",
            "expect_reason": "PARTIAL_REASON_MISSING",
        },
        {
            "id": "fz005_ok_partial_reason_unprobed",
            "kind": "partial_reason",
            "partial_declared": True,
            "partial_reasons": [],
            "constructed": True,
            "observed_reason_code": "NOT_YET_RUN",
            "n_unprobed": 1,
            "reported_verdict": "NOT_YET_RUN",
            "expect_reason": "PARTIAL_REASON_UNPROBED",
        },
        # ----- 小清新 fz-006 DECLARED_PRESENCE_NOT_PROPAGATED -----
        {
            "id": "fz006_mf_presence_not_propagated",
            "kind": "presence_propagate",
            "upstream_presence_declared": True,
            "downstream_presence": None,
            "arm_executed": True,
            "reported_verdict": "PASS",
            "expect_reason": "DECLARED_PRESENCE_NOT_PROPAGATED",
        },
        {
            "id": "fz006_ok_presence_propagate_unprobed",
            "kind": "presence_propagate",
            "upstream_presence_declared": True,
            "downstream_presence": None,
            "constructed": True,
            "observed_reason_code": "NOT_YET_RUN",
            "n_unprobed": 1,
            "reported_verdict": "NOT_YET_RUN",
            "expect_reason": "PRESENCE_PROPAGATE_UNPROBED",
        },
        # ----- NOT_YET_RUN_AS_PASS generic + honest -----
        {
            "id": "A_mf_not_yet_run_as_pass",
            "kind": "not_yet_run",
            "observed": None,
            "observed_reason_code": "NOT_YET_RUN",
            "n_unprobed": 0,
            "counted_unprobed_as_zero": True,
            "reported_verdict": "PASS",
            "expect_reason": "NOT_YET_RUN_AS_PASS",
        },
        {
            "id": "A_ok_not_yet_run_honest",
            "kind": "not_yet_run",
            "observed": None,
            "observed_reason_code": "NOT_YET_RUN",
            "n_unprobed": 1,
            "counted_unprobed_as_zero": False,
            "reported_verdict": "NOT_YET_RUN",
            "expect_reason": "NOT_YET_RUN_HONEST",
        },
        # ----- ARM_SKIPPED_COUNTED_AS_ZERO -----
        {
            "id": "B_mf_arm_skipped_counted_as_zero",
            "kind": "arm_skipped",
            "arm_executed": False,
            "enter_pass_numerator": True,
            "counted_skipped_as_zero": True,
            "reported_verdict": "PASS",
            "expect_reason": "ARM_SKIPPED_COUNTED_AS_ZERO",
        },
        {
            "id": "B_ok_arm_skipped_caught",
            "kind": "arm_skipped",
            "arm_executed": False,
            "enter_pass_numerator": False,
            "counted_skipped_as_zero": False,
            "reported_verdict": "SKIPPED",
            "expect_reason": "ARM_SKIPPED_CAUGHT",
        },
        # ----- 郑珺 SKIPPED_TASK_ZERO_ERROR -----
        {
            "id": "C_mf_skipped_task_zero_error",
            "kind": "skipped_task_zero_error",
            "n_executed": 0,
            "error_rate": 0.0,
            "reported_verdict": "PASS",
            "expect_reason": "SKIPPED_TASK_ZERO_ERROR",
        },
        {
            "id": "C_ok_skipped_task_caught",
            "kind": "skipped_task_zero_error",
            "n_executed": 0,
            "error_rate": 0.0,
            "reported_verdict": "ERROR_RATE_WITHOUT_EXEC",
            "expect_reason": "SKIPPED_TASK_CAUGHT",
        },
        {
            "id": "C_ok_error_rate_honest",
            "kind": "skipped_task_zero_error",
            "n_executed": 10,
            "error_rate": 0.2,
            "reported_verdict": "FAIL",
            "expect_reason": "ERROR_RATE_HONEST",
        },
        {
            "id": "C_ok_zero_error_with_exec",
            "kind": "skipped_task_zero_error",
            "n_executed": 5,
            "error_rate": 0.0,
            "reported_verdict": "PASS",
            "expect_reason": "ZERO_ERROR_WITH_EXEC",
        },
        # ----- v0.3 regression anchors (compact) -----
        {
            "id": "R_mf_dedup_collision_anchor",
            "kind": "dedup_collision_anchor",
            "declared": 1,
            "merge_predicate": "key_only",
            "reported_verdict": "PASS",
            "expect_reason": "DEDUP_COLLISION_MERGED_FALSE_ZERO",
        },
        {
            "id": "R_mf_read_source_mixup_anchor",
            "kind": "read_source_mixup_anchor",
            "count_source": "fetch",
            "assert_source": "history",
            "enter_pass_numerator": True,
            "reported_verdict": "PASS",
            "expect_reason": "READ_SOURCE_MIXUP_FALSE_ZERO",
        },
        # ----- A FALSE_GREEN_TRANSPORT (WorkBuddy) -----
        {
            "id": "A_mf_false_green_transport",
            "kind": "false_green_transport",
            "host_departure": "TLS handshake timeout",
            "exit_code": 0,
            "stdout_looks_green": True,
            "server_readback_present": False,
            "msg_id_match": False,
            "reported_verdict": "PASS",
            "expect_reason": "FALSE_GREEN_TRANSPORT",
        },
        {
            "id": "A_ok_false_green_transport_caught",
            "kind": "false_green_transport",
            "host_departure": "TLS handshake timeout",
            "exit_code": 0,
            "stdout_looks_green": True,
            "server_readback_present": False,
            "msg_id_match": False,
            "reported_verdict": "FALSE_GREEN_TRANSPORT",
            "expect_reason": "FALSE_GREEN_TRANSPORT_CAUGHT",
        },
        {
            "id": "A_ok_false_green_transport_honest_pass",
            "kind": "false_green_transport",
            "host_departure": None,
            "exit_code": 0,
            "stdout_looks_green": True,
            "server_readback_present": True,
            "msg_id_match": True,
            "reported_verdict": "PASS",
            "expect_reason": "FALSE_GREEN_TRANSPORT_HONEST_PASS",
        },
        # ----- B SKIP_GREEN_NO_RECEIPT (Talaria) -----
        {
            "id": "B_mf_skip_green_no_receipt",
            "kind": "skip_green_no_receipt",
            "planned_items": ["task_a", "task_b", "task_c"],
            "executed": 0,
            "exit_code": 0,
            "report_green": True,
            "scheduler_receipt": "absent",
            "reported_verdict": "PASS",
            "expect_reason": "SKIP_GREEN_NO_RECEIPT",
        },
        {
            "id": "B_ok_skip_green_no_receipt_caught",
            "kind": "skip_green_no_receipt",
            "planned_items": ["task_a", "task_b"],
            "executed": 0,
            "exit_code": 0,
            "report_green": True,
            "scheduler_receipt": None,
            "reported_verdict": "NOT_FIRED",
            "expect_reason": "SKIP_GREEN_NO_RECEIPT_CAUGHT",
        },
        # ----- C SELF_REFUTED_EXPECTATION (Talaria) -----
        {
            "id": "C_mf_self_refuted_expectation",
            "kind": "self_refuted_expectation",
            "expected_digest_source": "run_42_subject",
            "validator_source": "run_42_subject",
            "expected_run_id": "run_42",
            "validator_run_id": "run_42",
            "reported_verdict": "PASS",
            "expect_reason": "SELF_REFUTED_EXPECTATION",
        },
        {
            "id": "C_ok_expectation_independent",
            "kind": "self_refuted_expectation",
            "expected_digest_source": "golden_fixture_v1",
            "validator_source": "subject_run_99",
            "expected_run_id": "golden",
            "validator_run_id": "run_99",
            "reported_verdict": "PASS",
            "expect_reason": "EXPECTATION_INDEPENDENT",
        },
        # ----- D RAN_WITH_RECEIPT positive control (Talaria) -----
        {
            "id": "D_ok_ran_with_receipt",
            "kind": "ran_with_receipt",
            "planned_items": ["t1", "t2", "t3"],
            "executed": 3,
            "scheduler_receipt": "sha256:deadbeefcafebabe000000000000000000000000000000000000000000000000",
            "report_green": True,
            "reported_verdict": "PASS",
            "expect_reason": "RAN_WITH_RECEIPT",
        },
    ]


def main() -> int:
    rows = []
    ok = 0
    for c in cases():
        expect = c.get("expect_reason")
        payload = {k: v for k, v in c.items() if k not in ("id", "expect_reason")}
        result = judge(payload)
        passed = result.get("reason_code") == expect
        if passed:
            ok += 1
        rows.append(
            {
                "id": c["id"],
                "expect_reason": expect,
                "got": result,
                "pass": passed,
            }
        )
    out = {
        "fixture": "FALSE_ZERO",
        "version": "v0.5",
        "credit": ["WorkBuddy", "Talaria", "小清新", "郑珺的hermes"],
        "rows": len(rows),
        "passed": ok,
        "all_pass": ok == len(rows),
        "results": rows,
    }
    text = json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True)
    print(text)
    with open(__file__, "rb") as f:
        script_sha = hashlib.sha256(f.read()).hexdigest()
    run_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    meta = {
        "script_sha256": script_sha,
        "run_out_sha256": run_sha,
        "passed": f"{ok}/{len(rows)}",
    }
    print("META " + json.dumps(meta, ensure_ascii=False), file=sys.stderr)
    return 0 if ok == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
