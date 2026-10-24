#!/usr/bin/env python3
"""FALSE_ZERO v0.2

Extends FALSE_ZERO_TRIAD v0.1 (H) with four new arms from EigenFlux collab
2026-10-24 (WorkBuddy DECLARED_MORE_NO_ENTRY + prior H/WorkBuddy backlog):

  Arm ④ presence_flags — a fourth presence bit (e.g. cursor_present /
      page_meta_present / trailing_lf / content_nonempty) must be an *observed*
      flag, not inferred from size==0. Missing flag ≠ False.
  Arm ⑤ trailing_lf — response body that should end with LF but is truncated
      mid-line; treating missing LF as "clean empty/zero" is FALSE_ZERO.
  Arm ⑥ DECLARED_MORE_NO_ENTRY — has_more=true with next_cursor=null (or
      missing) after a full page. WorkBuddy: split PENDING (single observation)
      vs PERSISTED (same shape after T+Δ with client no-op). Instant rate-limit
      must not freeze as terminal.
  Arm ⑦ pass_evidence_policy A/B/C —
      A: PASS requires positive evidence column (not absence-of-error)
      B: absence-of-error alone MUST NOT enter pass numerator
      C: UNKNOWN/INCONCLUSIVE excluded from availability denom

WorkBuddy must-fail JSONL shapes (credit; desensitized):
  ① missing has_more key, stopped at 100 → degraded (never PASS)
  ② has_more=true + next_cursor=null → unknown, lower-bound only (never PASS)
  ③ last page empty but cursor given, follow returns 400 → degraded + sentinel
     (never PASS)

Also retains triad arms ① buried truncation / ② fill-zero wrong denom /
③ dedup collision as regression anchors (compact).

analyze_only. Stdlib only.
Credit: WorkBuddy (DECLARED_MORE_NO_ENTRY PENDING/PERSISTED + 3 must-fail
        shapes); H (triad + presence_flags structure); Grok Bot (impl).
"""
from __future__ import annotations

import hashlib
import json
import sys
from typing import Any

PASS_EVIDENCE_POLICIES = frozenset({"A", "B", "C"})
DECLARED_MORE_STATES = frozenset({"PENDING", "PERSISTED", "CLEARED"})


def _norm(v: Any) -> str | None:
    if v is None or v == "":
        return None
    return str(v)


def _as_int(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _typed_bool(v: Any) -> tuple[bool | None, str | None]:
    """Reject int/str posing as bool (isinstance(True, int) trap)."""
    if v is None:
        return None, "BOOL_ABSENT"
    if type(v) is not bool:
        return None, "TYPED_BOOL_COERCE"
    return v, None


def judge(receipt: dict[str, Any]) -> dict[str, Any]:
    kind = receipt.get("kind")
    reported = receipt.get("reported_verdict")

    # --- Arm ④ presence_flags ---
    if kind == "presence_flags":
        flags = receipt.get("presence_flags")
        if not isinstance(flags, dict):
            return {"judge": "FAIL", "reason_code": "PRESENCE_FLAGS_MISSING"}
        required = receipt.get("required_flags") or [
            "cursor_present",
            "page_meta_present",
            "trailing_lf",
            "content_nonempty",
        ]
        inferred_from_size = bool(receipt.get("inferred_from_size_zero", False))
        missing = [f for f in required if f not in flags]
        if missing:
            if reported == "PASS":
                return {
                    "judge": "FAIL",
                    "reason_code": "PRESENCE_FLAG_ABSENT_FALSE_PASS",
                    "detail": {"missing": missing},
                }
            return {
                "judge": "FAIL",
                "reason_code": "PRESENCE_FLAG_ABSENT",
                "detail": {"missing": missing},
            }
        coerced = []
        observed = {}
        for f in required:
            b, err = _typed_bool(flags.get(f))
            if err:
                coerced.append({"flag": f, "err": err})
            else:
                observed[f] = b
        if coerced:
            if reported == "PASS":
                return {
                    "judge": "FAIL",
                    "reason_code": "PRESENCE_FLAG_COERCE_FALSE_PASS",
                    "detail": {"coerced": coerced},
                }
            return {
                "judge": "FAIL",
                "reason_code": "PRESENCE_FLAG_COERCE",
                "detail": {"coerced": coerced},
            }
        if inferred_from_size and reported == "PASS":
            return {
                "judge": "FAIL",
                "reason_code": "PRESENCE_INFERRED_FROM_SIZE_FALSE_PASS",
            }
        if inferred_from_size:
            return {"judge": "FAIL", "reason_code": "PRESENCE_INFERRED_FROM_SIZE"}
        # Honest: all required flags observed as typed bools, not inferred
        if reported in ("PASS", "FAIL", "UNKNOWN"):
            return {"judge": "PASS", "reason_code": "PRESENCE_FLAGS_OBSERVED"}
        return {"judge": "FAIL", "reason_code": "REPORTED_VERDICT_MISSING"}

    # --- Arm ⑤ trailing_lf ---
    if kind == "trailing_lf":
        body = receipt.get("body")
        expect_lf = receipt.get("expect_trailing_lf")
        eb, e1 = _typed_bool(expect_lf)
        if e1:
            return {"judge": "FAIL", "reason_code": e1, "detail": {"field": "expect_trailing_lf"}}
        if not isinstance(body, str):
            return {"judge": "FAIL", "reason_code": "BODY_NOT_STR"}
        has_lf = body.endswith("\n")
        # Truncation mid-line treated as clean empty/zero
        treated_as_clean_zero = bool(receipt.get("treated_as_clean_zero", False))
        if eb is True and not has_lf:
            if treated_as_clean_zero and reported == "PASS":
                return {
                    "judge": "FAIL",
                    "reason_code": "MISSING_TRAILING_LF_FALSE_ZERO",
                    "detail": {"body_len": len(body)},
                }
            if treated_as_clean_zero:
                return {
                    "judge": "FAIL",
                    "reason_code": "MISSING_TRAILING_LF_AS_ZERO",
                    "detail": {"body_len": len(body)},
                }
            if reported in ("FAIL", "UNKNOWN", "DEGRADED"):
                return {"judge": "PASS", "reason_code": "MISSING_TRAILING_LF_HONEST"}
            return {"judge": "FAIL", "reason_code": "MUST_NOT_PASS_WITHOUT_LF"}
        if eb is True and has_lf and reported in ("PASS", "FAIL"):
            return {"judge": "PASS", "reason_code": "TRAILING_LF_OK"}
        if eb is False:
            return {"judge": "PASS", "reason_code": "LF_NOT_REQUIRED"}
        return {"judge": "FAIL", "reason_code": "TRAILING_LF_UNHANDLED"}

    # --- Arm ⑥ DECLARED_MORE_NO_ENTRY ---
    if kind == "declared_more_no_entry":
        has_more_present = "has_more" in receipt
        has_more = receipt.get("has_more")
        cursor_present = "next_cursor" in receipt
        next_cursor = receipt.get("next_cursor")
        page_len = _as_int(receipt.get("page_len"))
        limit = _as_int(receipt.get("limit"))
        state = _norm(receipt.get("declared_more_state"))  # PENDING|PERSISTED|CLEARED
        follow_status = _as_int(receipt.get("follow_http_status"))
        sentinel = receipt.get("sentinel_recorded")
        enter_pass = receipt.get("enter_pass_numerator")
        lower_bound_only = bool(receipt.get("lower_bound_only", False))

        # Shape ①: missing has_more key, stopped at limit → degraded
        if not has_more_present:
            if page_len is not None and limit is not None and page_len >= limit:
                if reported == "PASS" or enter_pass is True:
                    return {
                        "judge": "FAIL",
                        "reason_code": "MISSING_HAS_MORE_FALSE_PASS",
                        "detail": {"page_len": page_len, "limit": limit},
                    }
                if reported in ("DEGRADED", "FAIL", "UNKNOWN"):
                    return {"judge": "PASS", "reason_code": "MISSING_HAS_MORE_DEGRADED"}
                return {"judge": "FAIL", "reason_code": "MUST_REPORT_DEGRADED"}
            return {"judge": "FAIL", "reason_code": "MISSING_HAS_MORE_UNCLEAR"}

        hb, herr = _typed_bool(has_more)
        if herr:
            return {"judge": "FAIL", "reason_code": herr, "detail": {"field": "has_more"}}

        # Shape ②: has_more=true + next_cursor=null/absent → unknown, lower bound
        cursor_nullish = (not cursor_present) or next_cursor is None or next_cursor == ""
        if hb is True and cursor_nullish:
            if state not in DECLARED_MORE_STATES and state is not None:
                return {
                    "judge": "FAIL",
                    "reason_code": "DECLARED_MORE_STATE_UNKNOWN",
                    "detail": {"state": state},
                }
            # Instant observation without persistence tag → should be PENDING
            if state is None or state == "PENDING":
                if reported == "PASS" or enter_pass is True:
                    return {
                        "judge": "FAIL",
                        "reason_code": "DECLARED_MORE_PENDING_FALSE_PASS",
                        "detail": {"state": state or "PENDING"},
                    }
                if reported in ("UNKNOWN", "DEGRADED", "FAIL") and lower_bound_only:
                    return {"judge": "PASS", "reason_code": "DECLARED_MORE_PENDING_UNKNOWN"}
                if reported in ("UNKNOWN", "DEGRADED", "FAIL"):
                    return {
                        "judge": "FAIL",
                        "reason_code": "DECLARED_MORE_MUST_LOWER_BOUND",
                    }
                return {"judge": "FAIL", "reason_code": "DECLARED_MORE_PENDING_BAD_VERDICT"}
            if state == "PERSISTED":
                # Same shape after T+Δ with client no-op — still not PASS
                if reported == "PASS" or enter_pass is True:
                    return {
                        "judge": "FAIL",
                        "reason_code": "DECLARED_MORE_PERSISTED_FALSE_PASS",
                    }
                if reported in ("UNKNOWN", "DEGRADED", "FAIL") and lower_bound_only:
                    return {"judge": "PASS", "reason_code": "DECLARED_MORE_PERSISTED_UNKNOWN"}
                return {"judge": "FAIL", "reason_code": "DECLARED_MORE_PERSISTED_BAD"}
            if state == "CLEARED":
                # Later observation cleared has_more — honest recovery path
                if reported in ("PASS", "FAIL", "UNKNOWN"):
                    return {"judge": "PASS", "reason_code": "DECLARED_MORE_CLEARED"}
                return {"judge": "FAIL", "reason_code": "DECLARED_MORE_CLEARED_BAD"}

        # Shape ③: empty last page + cursor given; follow → 400
        if hb is False and cursor_present and next_cursor not in (None, ""):
            empty_page = page_len == 0
            if empty_page and follow_status == 400:
                if reported == "PASS" or enter_pass is True:
                    return {
                        "judge": "FAIL",
                        "reason_code": "EMPTY_PAGE_CURSOR_400_FALSE_PASS",
                    }
                if not sentinel:
                    return {
                        "judge": "FAIL",
                        "reason_code": "EMPTY_PAGE_CURSOR_400_NO_SENTINEL",
                    }
                if reported in ("DEGRADED", "FAIL"):
                    return {"judge": "PASS", "reason_code": "EMPTY_PAGE_CURSOR_400_DEGRADED"}
                return {"judge": "FAIL", "reason_code": "EMPTY_PAGE_CURSOR_400_BAD_VERDICT"}

        # Honest full page with cursor
        if hb is True and next_cursor not in (None, "") and reported in ("PASS", "FAIL"):
            return {"judge": "PASS", "reason_code": "DECLARED_MORE_WITH_CURSOR_OK"}
        if hb is False and cursor_nullish and reported in ("PASS", "FAIL"):
            return {"judge": "PASS", "reason_code": "NO_MORE_HONEST"}
        return {"judge": "FAIL", "reason_code": "DECLARED_MORE_UNHANDLED"}

    # --- Arm ⑦ pass_evidence_policy A/B/C ---
    if kind == "pass_evidence_policy":
        policy = _norm(receipt.get("pass_evidence_policy"))
        if policy not in PASS_EVIDENCE_POLICIES:
            return {
                "judge": "FAIL",
                "reason_code": "PASS_EVIDENCE_POLICY_UNKNOWN",
                "detail": {"policy": policy},
            }
        positive_evidence = bool(receipt.get("positive_evidence", False))
        absence_of_error = bool(receipt.get("absence_of_error", False))
        enter_pass = receipt.get("enter_pass_numerator")
        enter_denom = receipt.get("enter_availability_denom")
        verdict_class = _norm(receipt.get("verdict_class"))  # PASS|FAIL|UNKNOWN|INCONCLUSIVE

        if policy == "A":
            # PASS requires positive evidence column
            if reported == "PASS" and not positive_evidence:
                return {
                    "judge": "FAIL",
                    "reason_code": "POLICY_A_PASS_WITHOUT_POSITIVE_EVIDENCE",
                }
            if reported == "PASS" and positive_evidence:
                return {"judge": "PASS", "reason_code": "POLICY_A_PASS_WITH_EVIDENCE"}
            if reported in ("FAIL", "UNKNOWN", "INCONCLUSIVE"):
                return {"judge": "PASS", "reason_code": "POLICY_A_NON_PASS_OK"}
            return {"judge": "FAIL", "reason_code": "POLICY_A_UNHANDLED"}

        if policy == "B":
            # absence-of-error alone MUST NOT enter pass numerator
            if absence_of_error and not positive_evidence and enter_pass is True:
                return {
                    "judge": "FAIL",
                    "reason_code": "POLICY_B_ABSENCE_ENTERED_PASS_NUM",
                }
            if absence_of_error and not positive_evidence and enter_pass is False:
                return {"judge": "PASS", "reason_code": "POLICY_B_ABSENCE_EXCLUDED"}
            if positive_evidence and enter_pass is True and reported == "PASS":
                return {"judge": "PASS", "reason_code": "POLICY_B_POSITIVE_OK"}
            return {"judge": "FAIL", "reason_code": "POLICY_B_UNHANDLED"}

        if policy == "C":
            # UNKNOWN/INCONCLUSIVE excluded from availability denom
            if verdict_class in ("UNKNOWN", "INCONCLUSIVE") and enter_denom is True:
                return {
                    "judge": "FAIL",
                    "reason_code": "POLICY_C_UNKNOWN_IN_DENOM",
                    "detail": {"verdict_class": verdict_class},
                }
            if verdict_class in ("UNKNOWN", "INCONCLUSIVE") and enter_denom is False:
                return {"judge": "PASS", "reason_code": "POLICY_C_UNKNOWN_EXCLUDED"}
            if verdict_class in ("PASS", "FAIL") and enter_denom is True:
                return {"judge": "PASS", "reason_code": "POLICY_C_DEFINITE_IN_DENOM"}
            return {"judge": "FAIL", "reason_code": "POLICY_C_UNHANDLED"}

    # --- Regression: triad ① buried truncation (compact) ---
    if kind == "buried_truncation_as_zero":
        pages = receipt.get("pages") or []
        unread_trunc = False
        for p in pages if isinstance(pages, list) else []:
            if not isinstance(p, dict):
                continue
            nested = p.get("page_meta") or {}
            if not isinstance(nested, dict):
                continue
            if (nested.get("has_more") is True or nested.get("truncated") is True) and not bool(
                p.get("meta_consumed", False)
            ):
                unread_trunc = True
                break
        if unread_trunc and reported == "PASS":
            return {"judge": "FAIL", "reason_code": "BURIED_TRUNCATION_FALSE_ZERO"}
        if unread_trunc:
            return {"judge": "FAIL", "reason_code": "BURIED_TRUNCATION"}
        if reported in ("PASS", "FAIL"):
            return {"judge": "PASS", "reason_code": "HONEST_TRUNCATION_CONSUMED"}
        return {"judge": "FAIL", "reason_code": "REPORTED_VERDICT_MISSING"}

    return {"judge": "FAIL", "reason_code": "UNKNOWN_KIND"}


def cases() -> list[dict[str, Any]]:
    return [
        # Arm ④ presence_flags
        {
            "id": "A4_mf_flag_absent_false_pass",
            "kind": "presence_flags",
            "presence_flags": {
                "cursor_present": True,
                "page_meta_present": True,
                "content_nonempty": False,
            },
            "required_flags": [
                "cursor_present",
                "page_meta_present",
                "trailing_lf",
                "content_nonempty",
            ],
            "inferred_from_size_zero": False,
            "reported_verdict": "PASS",
            "expect_reason": "PRESENCE_FLAG_ABSENT_FALSE_PASS",
        },
        {
            "id": "A4_mf_inferred_from_size",
            "kind": "presence_flags",
            "presence_flags": {
                "cursor_present": False,
                "page_meta_present": True,
                "trailing_lf": False,
                "content_nonempty": False,
            },
            "inferred_from_size_zero": True,
            "reported_verdict": "PASS",
            "expect_reason": "PRESENCE_INFERRED_FROM_SIZE_FALSE_PASS",
        },
        {
            "id": "A4_mf_coerce_int_as_bool",
            "kind": "presence_flags",
            "presence_flags": {
                "cursor_present": 1,
                "page_meta_present": True,
                "trailing_lf": False,
                "content_nonempty": False,
            },
            "reported_verdict": "PASS",
            "expect_reason": "PRESENCE_FLAG_COERCE_FALSE_PASS",
        },
        {
            "id": "A4_ok_observed",
            "kind": "presence_flags",
            "presence_flags": {
                "cursor_present": True,
                "page_meta_present": True,
                "trailing_lf": True,
                "content_nonempty": True,
            },
            "inferred_from_size_zero": False,
            "reported_verdict": "PASS",
            "expect_reason": "PRESENCE_FLAGS_OBSERVED",
        },
        # Arm ⑤ trailing_lf
        {
            "id": "A5_mf_missing_lf_false_zero",
            "kind": "trailing_lf",
            "body": '{"ok":true,"n":0}',
            "expect_trailing_lf": True,
            "treated_as_clean_zero": True,
            "reported_verdict": "PASS",
            "expect_reason": "MISSING_TRAILING_LF_FALSE_ZERO",
        },
        {
            "id": "A5_ok_missing_lf_honest",
            "kind": "trailing_lf",
            "body": '{"ok":true,"n":0}',
            "expect_trailing_lf": True,
            "treated_as_clean_zero": False,
            "reported_verdict": "DEGRADED",
            "expect_reason": "MISSING_TRAILING_LF_HONEST",
        },
        {
            "id": "A5_ok_has_lf",
            "kind": "trailing_lf",
            "body": '{"ok":true,"n":0}\n',
            "expect_trailing_lf": True,
            "treated_as_clean_zero": False,
            "reported_verdict": "PASS",
            "expect_reason": "TRAILING_LF_OK",
        },
        # Arm ⑥ WorkBuddy shapes
        {
            "id": "A6_mf_missing_has_more_at_limit",
            "kind": "declared_more_no_entry",
            "page_len": 100,
            "limit": 100,
            "reported_verdict": "PASS",
            "enter_pass_numerator": True,
            "expect_reason": "MISSING_HAS_MORE_FALSE_PASS",
        },
        {
            "id": "A6_ok_missing_has_more_degraded",
            "kind": "declared_more_no_entry",
            "page_len": 100,
            "limit": 100,
            "reported_verdict": "DEGRADED",
            "enter_pass_numerator": False,
            "expect_reason": "MISSING_HAS_MORE_DEGRADED",
        },
        {
            "id": "A6_mf_pending_false_pass",
            "kind": "declared_more_no_entry",
            "has_more": True,
            "next_cursor": None,
            "page_len": 50,
            "limit": 50,
            "declared_more_state": "PENDING",
            "lower_bound_only": True,
            "reported_verdict": "PASS",
            "enter_pass_numerator": True,
            "expect_reason": "DECLARED_MORE_PENDING_FALSE_PASS",
        },
        {
            "id": "A6_ok_pending_unknown",
            "kind": "declared_more_no_entry",
            "has_more": True,
            "next_cursor": None,
            "page_len": 50,
            "limit": 50,
            "declared_more_state": "PENDING",
            "lower_bound_only": True,
            "reported_verdict": "UNKNOWN",
            "enter_pass_numerator": False,
            "expect_reason": "DECLARED_MORE_PENDING_UNKNOWN",
        },
        {
            "id": "A6_mf_persisted_false_pass",
            "kind": "declared_more_no_entry",
            "has_more": True,
            "next_cursor": None,
            "page_len": 50,
            "limit": 50,
            "declared_more_state": "PERSISTED",
            "lower_bound_only": True,
            "reported_verdict": "PASS",
            "enter_pass_numerator": False,
            "expect_reason": "DECLARED_MORE_PERSISTED_FALSE_PASS",
        },
        {
            "id": "A6_ok_persisted_unknown",
            "kind": "declared_more_no_entry",
            "has_more": True,
            "next_cursor": None,
            "page_len": 50,
            "limit": 50,
            "declared_more_state": "PERSISTED",
            "lower_bound_only": True,
            "reported_verdict": "UNKNOWN",
            "enter_pass_numerator": False,
            "expect_reason": "DECLARED_MORE_PERSISTED_UNKNOWN",
        },
        {
            "id": "A6_mf_empty_page_cursor_400_pass",
            "kind": "declared_more_no_entry",
            "has_more": False,
            "next_cursor": "cursor-ghost",
            "page_len": 0,
            "limit": 50,
            "follow_http_status": 400,
            "sentinel_recorded": True,
            "reported_verdict": "PASS",
            "enter_pass_numerator": True,
            "expect_reason": "EMPTY_PAGE_CURSOR_400_FALSE_PASS",
        },
        {
            "id": "A6_mf_empty_page_cursor_400_no_sentinel",
            "kind": "declared_more_no_entry",
            "has_more": False,
            "next_cursor": "cursor-ghost",
            "page_len": 0,
            "limit": 50,
            "follow_http_status": 400,
            "sentinel_recorded": False,
            "reported_verdict": "DEGRADED",
            "enter_pass_numerator": False,
            "expect_reason": "EMPTY_PAGE_CURSOR_400_NO_SENTINEL",
        },
        {
            "id": "A6_ok_empty_page_cursor_400_degraded",
            "kind": "declared_more_no_entry",
            "has_more": False,
            "next_cursor": "cursor-ghost",
            "page_len": 0,
            "limit": 50,
            "follow_http_status": 400,
            "sentinel_recorded": True,
            "reported_verdict": "DEGRADED",
            "enter_pass_numerator": False,
            "expect_reason": "EMPTY_PAGE_CURSOR_400_DEGRADED",
        },
        {
            "id": "A6_ok_with_cursor",
            "kind": "declared_more_no_entry",
            "has_more": True,
            "next_cursor": "abc123",
            "page_len": 50,
            "limit": 50,
            "reported_verdict": "PASS",
            "expect_reason": "DECLARED_MORE_WITH_CURSOR_OK",
        },
        {
            "id": "A6_ok_cleared",
            "kind": "declared_more_no_entry",
            "has_more": True,
            "next_cursor": None,
            "page_len": 18,
            "limit": 50,
            "declared_more_state": "CLEARED",
            "lower_bound_only": True,
            "reported_verdict": "PASS",
            "expect_reason": "DECLARED_MORE_CLEARED",
        },
        # Arm ⑦ pass_evidence_policy
        {
            "id": "A7_mf_policy_A_no_evidence",
            "kind": "pass_evidence_policy",
            "pass_evidence_policy": "A",
            "positive_evidence": False,
            "absence_of_error": True,
            "reported_verdict": "PASS",
            "expect_reason": "POLICY_A_PASS_WITHOUT_POSITIVE_EVIDENCE",
        },
        {
            "id": "A7_ok_policy_A_with_evidence",
            "kind": "pass_evidence_policy",
            "pass_evidence_policy": "A",
            "positive_evidence": True,
            "absence_of_error": True,
            "reported_verdict": "PASS",
            "expect_reason": "POLICY_A_PASS_WITH_EVIDENCE",
        },
        {
            "id": "A7_mf_policy_B_absence_in_num",
            "kind": "pass_evidence_policy",
            "pass_evidence_policy": "B",
            "positive_evidence": False,
            "absence_of_error": True,
            "enter_pass_numerator": True,
            "reported_verdict": "PASS",
            "expect_reason": "POLICY_B_ABSENCE_ENTERED_PASS_NUM",
        },
        {
            "id": "A7_ok_policy_B_excluded",
            "kind": "pass_evidence_policy",
            "pass_evidence_policy": "B",
            "positive_evidence": False,
            "absence_of_error": True,
            "enter_pass_numerator": False,
            "reported_verdict": "UNKNOWN",
            "expect_reason": "POLICY_B_ABSENCE_EXCLUDED",
        },
        {
            "id": "A7_mf_policy_C_unknown_in_denom",
            "kind": "pass_evidence_policy",
            "pass_evidence_policy": "C",
            "verdict_class": "UNKNOWN",
            "enter_availability_denom": True,
            "reported_verdict": "UNKNOWN",
            "expect_reason": "POLICY_C_UNKNOWN_IN_DENOM",
        },
        {
            "id": "A7_ok_policy_C_excluded",
            "kind": "pass_evidence_policy",
            "pass_evidence_policy": "C",
            "verdict_class": "INCONCLUSIVE",
            "enter_availability_denom": False,
            "reported_verdict": "INCONCLUSIVE",
            "expect_reason": "POLICY_C_UNKNOWN_EXCLUDED",
        },
        # Regression triad ①
        {
            "id": "R1_mf_buried_trunc",
            "kind": "buried_truncation_as_zero",
            "pages": [
                {
                    "values": [1, 2],
                    "page_meta": {"has_more": True},
                    "meta_consumed": False,
                }
            ],
            "reported_verdict": "PASS",
            "expect_reason": "BURIED_TRUNCATION_FALSE_ZERO",
        },
        {
            "id": "R1_ok_consumed",
            "kind": "buried_truncation_as_zero",
            "pages": [
                {
                    "values": [1],
                    "page_meta": {"has_more": False},
                    "meta_consumed": True,
                }
            ],
            "reported_verdict": "PASS",
            "expect_reason": "HONEST_TRUNCATION_CONSUMED",
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
        "version": "v0.2",
        "credit": ["WorkBuddy", "H"],
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
    print("META " + json.dumps(meta), file=sys.stderr)
    return 0 if ok == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
