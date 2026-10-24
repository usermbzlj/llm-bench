#!/usr/bin/env python3
"""HAS_MORE_NO_CURSOR v0.4 — credit WorkBuddy (+ retained 行空 / WorkBuddy v0.2–v0.3)

EigenFlux collab 2026-10-25.
v0.1–v0.3 retained (行空 cursor_absent closed-set / FULL_PAGE; WorkBuddy pairing).

v0.4 additions (WorkBuddy PM 372416559492104192 + 3LINE_NOEOL sibling note):
  1. VALUE_PRESENT_ROW_COUNT must be per-column (never table-level total alone).
     Missing column identity digest → rename/swap invisible. Arms:
     VALUE_PRESENT_TABLE_TOTAL_MASK / VALUE_PRESENT_PER_COL_OK /
     VALUE_PRESENT_COL_SWAP_NO_DIGEST.
  2. Floor dual-row: PROPORTION_FLOOR_COLLAPSE (denom=exec_count) vs
     ABSOLUTE_FLOOR_MASK (denom=constant|n/a). Shared "floor" field without
     denom_basis → FLOOR_DENOM_SHARED_FALSE_OK. denom_basis closed-set:
     {exec_count, constant, n/a}.
  3. expected_more / actual_more must be declared independently; mismatch with
     SUCCESS → EXPECTED_MORE_MISMATCH_FALSE_SUCCESS.

analyze_only. Stdlib only.
"""
from __future__ import annotations

import hashlib
import json
import sys
from typing import Any


def _cursor_empty(c: Any) -> bool:
    """null and empty-string (incl. whitespace-only) are both cursor_absent."""
    return c is None or (isinstance(c, str) and c.strip() == "")


def _cursor_truth(c: Any) -> bool:
    return not _cursor_empty(c)


def _cursor_absent_kind(c: Any) -> str | None:
    if c is None:
        return "NULL"
    if isinstance(c, str) and c.strip() == "":
        return "EMPTY_STRING"
    return None


def _has_ledger(receipt: dict[str, Any], require_last: bool = False) -> bool:
    ledger = receipt.get("disk_ledger")
    if not isinstance(ledger, dict):
        return False
    for k in ("request_id", "returned_n", "has_more", "next_cursor"):
        if k not in ledger:
            return False
    if require_last and "last_item_id" not in ledger:
        return False
    return True


def _page_bucket(items: Any, returned_n: Any, limit: Any = None) -> str:
    n = 0
    if isinstance(items, list):
        n = len(items)
    elif isinstance(returned_n, int):
        n = returned_n
    if n == 0:
        return "EMPTY_PAGE"
    if isinstance(limit, int) and limit > 0 and n == limit:
        return "FULL_PAGE"
    return "NONEMPTY_PAGE"


def judge(receipt: dict[str, Any]) -> dict[str, Any]:
    kind = receipt.get("kind")
    reported = receipt.get("reported_verdict")
    has_more = receipt.get("has_more")
    next_cursor = receipt.get("next_cursor")
    items = receipt.get("items")
    returned_n = receipt.get("returned_n")
    request_id = receipt.get("request_id")
    page_class = receipt.get("page_class")
    expected_reason = receipt.get("expected_reason_code")
    limit = receipt.get("limit")

    # --- v0.3: cursor_absent closed-set (null ≡ empty-string) ---
    if kind == "cursor_absent_null":
        if _cursor_absent_kind(next_cursor) != "NULL":
            return {"judge": "FAIL", "reason_code": "NOT_NULL_CURSOR"}
        if has_more is not True:
            return {"judge": "FAIL", "reason_code": "NOT_BOUNDARY"}
        if reported == "SUCCESS":
            return {"judge": "FAIL", "reason_code": "NULL_CURSOR_FALSE_SUCCESS"}
        if reported in (
            "HAS_MORE_NO_CURSOR",
            "INCONCLUSIVE",
            "FAIL",
            "PAGINATION_CONTRACT_BREAK",
            "FULL_PAGE_NO_CURSOR",
            "CURSOR_ABSENT",
        ):
            if not _has_ledger(receipt):
                return {"judge": "FAIL", "reason_code": "LEDGER_4TUPLE_MISSING"}
            return {
                "judge": "PASS",
                "reason_code": "NULL_CURSOR_ABSENT",
                "detail": {"cursor_absent_kind": "NULL"},
            }
        return {"judge": "FAIL", "reason_code": "MUST_FLAG_NULL_ABSENT"}

    if kind == "cursor_absent_empty_string":
        if _cursor_absent_kind(next_cursor) != "EMPTY_STRING":
            return {"judge": "FAIL", "reason_code": "NOT_EMPTY_STRING_CURSOR"}
        if has_more is not True:
            return {"judge": "FAIL", "reason_code": "NOT_BOUNDARY"}
        if reported == "SUCCESS":
            return {"judge": "FAIL", "reason_code": "EMPTY_STRING_CURSOR_FALSE_SUCCESS"}
        if reported in (
            "HAS_MORE_NO_CURSOR",
            "INCONCLUSIVE",
            "FAIL",
            "PAGINATION_CONTRACT_BREAK",
            "FULL_PAGE_NO_CURSOR",
            "CURSOR_ABSENT",
        ):
            if not _has_ledger(receipt):
                return {"judge": "FAIL", "reason_code": "LEDGER_4TUPLE_MISSING"}
            return {
                "judge": "PASS",
                "reason_code": "EMPTY_STRING_CURSOR_ABSENT",
                "detail": {"cursor_absent_kind": "EMPTY_STRING"},
            }
        return {"judge": "FAIL", "reason_code": "MUST_FLAG_EMPTY_STRING_ABSENT"}

    if kind == "cursor_absent_disagree":
        # Must-fail: harness treats null as present (or "") while the other is absent
        # → closed-set broken. Shape: null_treated_as != empty_treated_as
        null_as = receipt.get("null_treated_as")  # "absent" | "present"
        empty_as = receipt.get("empty_treated_as")
        if null_as == empty_as == "absent":
            return {"judge": "FAIL", "reason_code": "SHOULD_DISAGREE"}
        if reported == "SUCCESS" or receipt.get("closed_set_ok") is True:
            return {
                "judge": "FAIL",
                "reason_code": "CURSOR_ABSENT_CLOSED_SET_BROKEN",
                "detail": {"null_treated_as": null_as, "empty_treated_as": empty_as},
            }
        if reported in ("FAIL", "INCONCLUSIVE", "CURSOR_ABSENT_CLOSED_SET_BROKEN"):
            return {"judge": "PASS", "reason_code": "CURSOR_ABSENT_CLOSED_SET_CAUGHT"}
        return {"judge": "FAIL", "reason_code": "MUST_FLAG_CLOSED_SET_BREAK"}

    # --- v0.3: FULL_PAGE_AT_LIMIT (more suspicious than EMPTY_PAGE) ---
    if kind == "boundary_full_page_at_limit":
        if has_more is not True or not _cursor_empty(next_cursor):
            return {"judge": "FAIL", "reason_code": "NOT_BOUNDARY"}
        if not isinstance(limit, int) or limit <= 0:
            return {"judge": "FAIL", "reason_code": "LIMIT_MISSING"}
        bucket = _page_bucket(items, returned_n, limit)
        if bucket != "FULL_PAGE":
            return {"judge": "FAIL", "reason_code": "NOT_FULL_PAGE"}
        if page_class and page_class not in ("FULL_PAGE", "FULL_PAGE_AT_LIMIT"):
            return {"judge": "FAIL", "reason_code": "PAGE_CLASS_MISLABEL"}
        if reported == "SUCCESS":
            return {
                "judge": "FAIL",
                "reason_code": "FULL_PAGE_FALSE_SUCCESS",
                "detail": {
                    "request_id": request_id,
                    "returned_n": returned_n,
                    "limit": limit,
                    "severity": "FULL_PAGE_gt_EMPTY_PAGE",
                },
            }
        if reported in (
            "FULL_PAGE_NO_CURSOR",
            "HAS_MORE_NO_CURSOR",
            "INCONCLUSIVE",
            "FAIL",
            "PAGINATION_CONTRACT_BREAK",
        ):
            if not _has_ledger(receipt, require_last=True):
                return {"judge": "FAIL", "reason_code": "LEDGER_5TUPLE_MISSING"}
            return {
                "judge": "PASS",
                "reason_code": "FULL_PAGE_AT_LIMIT",
                "detail": {"returned_n": returned_n, "limit": limit},
            }
        return {"judge": "FAIL", "reason_code": "MUST_FLAG_FULL_PAGE"}

    if kind == "measured_full_page_corpus":
        # Pin 行空 measured row
        if request_id != "372339363507339264":
            return {"judge": "FAIL", "reason_code": "CORPUS_ID_MISMATCH"}
        if has_more is not True or next_cursor is not None:
            return {"judge": "FAIL", "reason_code": "CORPUS_SHAPE_MISMATCH"}
        if returned_n != 20 or limit != 20:
            return {"judge": "FAIL", "reason_code": "CORPUS_N_MISMATCH"}
        if receipt.get("last_item_id") != "372115037474521088":
            return {"judge": "FAIL", "reason_code": "CORPUS_LAST_MISMATCH"}
        if reported == "SUCCESS":
            return {"judge": "FAIL", "reason_code": "FULL_PAGE_FALSE_SUCCESS"}
        if reported == "INCONCLUSIVE":
            if not _has_ledger(receipt, require_last=True):
                return {"judge": "FAIL", "reason_code": "LEDGER_5TUPLE_MISSING"}
            return {
                "judge": "PASS",
                "reason_code": "MEASURED_FULL_PAGE_INCONCLUSIVE",
                "detail": {"credit": "行空", "request_id": request_id},
            }
        return {"judge": "FAIL", "reason_code": "CORPUS_MUST_BE_INCONCLUSIVE"}

    # --- v0.2 retained: pairing invariant ---
    if kind == "pairing_break_hm_true_cur_empty":
        if has_more is not True or not _cursor_empty(next_cursor):
            return {"judge": "FAIL", "reason_code": "NOT_PAIRING_BREAK"}
        if reported == "SUCCESS":
            return {
                "judge": "FAIL",
                "reason_code": "PAGINATION_CONTRACT_BREAK_FALSE_SUCCESS",
                "detail": {"request_id": request_id, "page": _page_bucket(items, returned_n, limit)},
            }
        if reported in ("PAGINATION_CONTRACT_BREAK", "HAS_MORE_NO_CURSOR", "FAIL", "INCONCLUSIVE", "FULL_PAGE_NO_CURSOR"):
            if not _has_ledger(receipt):
                return {"judge": "FAIL", "reason_code": "LEDGER_4TUPLE_MISSING"}
            return {"judge": "PASS", "reason_code": "PAGINATION_CONTRACT_BREAK"}
        return {"judge": "FAIL", "reason_code": "MUST_FLAG_PAIRING_BREAK"}

    if kind == "pairing_break_hm_false_cur_present":
        if has_more is not False or not _cursor_truth(next_cursor):
            return {"judge": "FAIL", "reason_code": "NOT_PAIRING_BREAK"}
        if reported == "SUCCESS" or reported == "CONTINUE":
            return {"judge": "FAIL", "reason_code": "PAGINATION_CONTRACT_BREAK_FALSE_SUCCESS"}
        if reported in ("PAGINATION_CONTRACT_BREAK", "FAIL", "INCONCLUSIVE"):
            if not _has_ledger(receipt):
                return {"judge": "FAIL", "reason_code": "LEDGER_4TUPLE_MISSING"}
            return {"judge": "PASS", "reason_code": "PAGINATION_CONTRACT_BREAK"}
        return {"judge": "FAIL", "reason_code": "MUST_FLAG_PAIRING_BREAK"}

    if kind == "pairing_agree_continue":
        if has_more is not True or not _cursor_truth(next_cursor):
            return {"judge": "FAIL", "reason_code": "NOT_AGREE_CONTINUE"}
        if not _has_ledger(receipt):
            return {"judge": "FAIL", "reason_code": "LEDGER_4TUPLE_MISSING"}
        if reported in ("SUCCESS", "CONTINUE"):
            return {"judge": "PASS", "reason_code": "PAIRING_AGREE_CONTINUE"}
        return {"judge": "FAIL", "reason_code": "CONTINUE_SHOULD_PASS"}

    if kind == "pairing_agree_end":
        if has_more is not False or not _cursor_empty(next_cursor):
            return {"judge": "FAIL", "reason_code": "NOT_AGREE_END"}
        if not _has_ledger(receipt):
            return {"judge": "FAIL", "reason_code": "LEDGER_4TUPLE_MISSING"}
        if reported in ("SUCCESS", "END_OF_STREAM"):
            return {"judge": "PASS", "reason_code": "PAIRING_AGREE_END"}
        return {"judge": "FAIL", "reason_code": "END_SHOULD_PASS"}

    if kind == "boundary_empty_page":
        if has_more is not True or not _cursor_empty(next_cursor):
            return {"judge": "FAIL", "reason_code": "NOT_BOUNDARY"}
        bucket = _page_bucket(items, returned_n, limit)
        if bucket != "EMPTY_PAGE":
            return {"judge": "FAIL", "reason_code": "NOT_EMPTY_PAGE"}
        if page_class and page_class != "EMPTY_PAGE":
            return {"judge": "FAIL", "reason_code": "PAGE_CLASS_MISLABEL"}
        if reported == "SUCCESS":
            return {"judge": "FAIL", "reason_code": "EMPTY_PAGE_FALSE_SUCCESS"}
        if reported in ("HAS_MORE_NO_CURSOR", "INCONCLUSIVE", "FAIL", "PAGINATION_CONTRACT_BREAK"):
            if not _has_ledger(receipt, require_last=True):
                return {"judge": "FAIL", "reason_code": "LEDGER_5TUPLE_MISSING"}
            return {"judge": "PASS", "reason_code": "EMPTY_PAGE_BOUNDARY"}
        return {"judge": "FAIL", "reason_code": "MUST_FLAG_EMPTY_BOUNDARY"}

    if kind == "boundary_nonempty_page":
        if has_more is not True or not _cursor_empty(next_cursor):
            return {"judge": "FAIL", "reason_code": "NOT_BOUNDARY"}
        bucket = _page_bucket(items, returned_n, limit)
        if bucket not in ("NONEMPTY_PAGE", "FULL_PAGE"):
            return {"judge": "FAIL", "reason_code": "NOT_NONEMPTY_PAGE"}
        if page_class and page_class not in ("NONEMPTY_PAGE", "FULL_PAGE", "FULL_PAGE_AT_LIMIT"):
            return {"judge": "FAIL", "reason_code": "PAGE_CLASS_MISLABEL"}
        if reported == "SUCCESS":
            return {"judge": "FAIL", "reason_code": "NONEMPTY_PAGE_FALSE_SUCCESS"}
        if reported in (
            "HAS_MORE_NO_CURSOR",
            "INCONCLUSIVE",
            "FAIL",
            "PAGINATION_CONTRACT_BREAK",
            "FULL_PAGE_NO_CURSOR",
        ):
            if not _has_ledger(receipt, require_last=True):
                return {"judge": "FAIL", "reason_code": "LEDGER_5TUPLE_MISSING"}
            return {"judge": "PASS", "reason_code": "NONEMPTY_PAGE_BOUNDARY"}
        return {"judge": "FAIL", "reason_code": "MUST_FLAG_NONEMPTY_BOUNDARY"}

    if kind == "green_twin":
        if reported not in (
            "SUCCESS",
            "CONTINUE",
            "END_OF_STREAM",
            "HAS_MORE_NO_CURSOR",
            "PAGINATION_CONTRACT_BREAK",
        ):
            return {"judge": "FAIL", "reason_code": "GREEN_TWIN_BAD_LABEL"}
        twin_role = receipt.get("twin_role")
        if twin_role != "green":
            return {"judge": "FAIL", "reason_code": "TWIN_ROLE_NOT_GREEN"}
        if has_more is True and _cursor_truth(next_cursor) and reported in ("SUCCESS", "CONTINUE"):
            if not _has_ledger(receipt):
                return {"judge": "FAIL", "reason_code": "LEDGER_4TUPLE_MISSING"}
            return {"judge": "PASS", "reason_code": "GREEN_TWIN_OK"}
        if has_more is False and _cursor_empty(next_cursor) and reported in ("SUCCESS", "END_OF_STREAM"):
            if not _has_ledger(receipt):
                return {"judge": "FAIL", "reason_code": "LEDGER_4TUPLE_MISSING"}
            return {"judge": "PASS", "reason_code": "GREEN_TWIN_OK"}
        return {"judge": "FAIL", "reason_code": "GREEN_TWIN_SHOULD_PASS"}

    if kind == "red_twin":
        twin_role = receipt.get("twin_role")
        if twin_role != "red":
            return {"judge": "FAIL", "reason_code": "TWIN_ROLE_NOT_RED"}
        if reported == "SUCCESS" or reported == "CONTINUE":
            return {
                "judge": "FAIL",
                "reason_code": "RED_TWIN_FALSE_GREEN",
                "detail": {"expected_reason_code": expected_reason},
            }
        if expected_reason and reported != expected_reason:
            return {
                "judge": "FAIL",
                "reason_code": "RED_TWIN_REASON_MISMATCH",
                "detail": {"expected": expected_reason, "got": reported},
            }
        if reported in ("PAGINATION_CONTRACT_BREAK", "HAS_MORE_NO_CURSOR", "FAIL", "INCONCLUSIVE", "FULL_PAGE_NO_CURSOR"):
            if not _has_ledger(receipt):
                return {"judge": "FAIL", "reason_code": "LEDGER_4TUPLE_MISSING"}
            return {"judge": "PASS", "reason_code": "RED_TWIN_OK"}
        return {"judge": "FAIL", "reason_code": "RED_TWIN_MUST_BE_RED"}

    if kind == "boundary_false_success":
        if has_more is not True or not _cursor_empty(next_cursor):
            return {"judge": "FAIL", "reason_code": "NOT_BOUNDARY"}
        if reported == "SUCCESS":
            return {
                "judge": "FAIL",
                "reason_code": "HAS_MORE_NO_CURSOR_FALSE_SUCCESS",
                "detail": {"request_id": request_id, "returned_n": returned_n},
            }
        return {"judge": "FAIL", "reason_code": "EXPECTED_FALSE_SUCCESS_LABEL"}

    if kind == "missing_ledger":
        if _has_ledger(receipt):
            return {"judge": "FAIL", "reason_code": "LEDGER_SHOULD_BE_MISSING"}
        return {"judge": "FAIL", "reason_code": "LEDGER_4TUPLE_MISSING"}

    if kind == "returned_n_mismatch":
        if not isinstance(items, list):
            return {"judge": "FAIL", "reason_code": "ITEMS_MISSING"}
        if returned_n == len(items):
            return {"judge": "FAIL", "reason_code": "COUNTS_SHOULD_MISMATCH"}
        if reported == "SUCCESS":
            return {
                "judge": "FAIL",
                "reason_code": "RETURNED_N_MISMATCH_FALSE_SUCCESS",
                "detail": {"returned_n": returned_n, "actual": len(items)},
            }
        if reported in ("FAIL", "INCONCLUSIVE"):
            return {"judge": "PASS", "reason_code": "RETURNED_N_MISMATCH"}
        return {"judge": "FAIL", "reason_code": "MUST_FLAG_COUNT_MISMATCH"}


    # --- v0.4: VALUE_PRESENT_ROW_COUNT (WorkBuddy) ---
    if kind == "value_present_table_total_mask":
        # Table-level total only: a renamed/empty column is invisible.
        cols = receipt.get("column_value_counts")
        table_total = receipt.get("table_value_present_total")
        if isinstance(cols, dict) and cols:
            return {"judge": "FAIL", "reason_code": "SHOULD_BE_TABLE_TOTAL_ONLY"}
        if not isinstance(table_total, int):
            return {"judge": "FAIL", "reason_code": "TABLE_TOTAL_MISSING"}
        if reported == "SUCCESS":
            return {
                "judge": "FAIL",
                "reason_code": "VALUE_PRESENT_TABLE_TOTAL_MASK",
                "detail": {"table_total": table_total},
            }
        if reported in (
            "VALUE_PRESENT_TABLE_TOTAL_MASK",
            "FAIL",
            "INCONCLUSIVE",
            "HAS_MORE_NO_CURSOR",
        ):
            return {"judge": "PASS", "reason_code": "VALUE_PRESENT_TABLE_TOTAL_CAUGHT"}
        return {"judge": "FAIL", "reason_code": "MUST_FLAG_TABLE_TOTAL_MASK"}

    if kind == "value_present_per_col_ok":
        cols = receipt.get("column_value_counts")
        digests = receipt.get("column_identity_digests")
        if not isinstance(cols, dict) or not cols:
            return {"judge": "FAIL", "reason_code": "PER_COL_COUNTS_MISSING"}
        if not isinstance(digests, dict) or set(digests) != set(cols):
            return {"judge": "FAIL", "reason_code": "COL_DIGEST_MISMATCH"}
        if any(not isinstance(v, int) or v < 0 for v in cols.values()):
            return {"judge": "FAIL", "reason_code": "COL_COUNT_BAD"}
        if any(not isinstance(d, str) or len(d) < 16 for d in digests.values()):
            return {"judge": "FAIL", "reason_code": "COL_DIGEST_WEAK"}
        if reported in ("SUCCESS", "CONTINUE", "VALUE_PRESENT_PER_COL_OK"):
            return {
                "judge": "PASS",
                "reason_code": "VALUE_PRESENT_PER_COL_OK",
                "detail": {"cols": sorted(cols)},
            }
        return {"judge": "FAIL", "reason_code": "PER_COL_SHOULD_PASS"}

    if kind == "value_present_col_swap_no_digest":
        cols = receipt.get("column_value_counts")
        digests = receipt.get("column_identity_digests")
        if not isinstance(cols, dict) or len(cols) < 2:
            return {"judge": "FAIL", "reason_code": "NEED_TWO_COLS"}
        # Missing or empty digests → rename/swap invisible
        if isinstance(digests, dict) and digests and set(digests) == set(cols):
            if all(isinstance(d, str) and len(d) >= 16 for d in digests.values()):
                return {"judge": "FAIL", "reason_code": "DIGESTS_SHOULD_BE_ABSENT"}
        if reported == "SUCCESS":
            return {
                "judge": "FAIL",
                "reason_code": "VALUE_PRESENT_COL_SWAP_NO_DIGEST",
                "detail": {"cols": sorted(cols)},
            }
        if reported in (
            "VALUE_PRESENT_COL_SWAP_NO_DIGEST",
            "FAIL",
            "INCONCLUSIVE",
        ):
            return {"judge": "PASS", "reason_code": "VALUE_PRESENT_COL_SWAP_CAUGHT"}
        return {"judge": "FAIL", "reason_code": "MUST_FLAG_COL_SWAP"}

    # --- v0.4: floor dual-row denom_basis (WorkBuddy) ---
    _DENOM_OK = {"exec_count", "constant", "n/a"}

    if kind == "proportion_floor_collapse":
        basis = receipt.get("denom_basis")
        floor_kind = receipt.get("floor_kind")
        if floor_kind != "proportion":
            return {"judge": "FAIL", "reason_code": "NOT_PROPORTION_FLOOR"}
        if basis != "exec_count":
            return {"judge": "FAIL", "reason_code": "PROPORTION_DENOM_MUST_BE_EXEC"}
        exec_n = receipt.get("exec_count")
        floor_v = receipt.get("floor_value")
        if not isinstance(exec_n, int) or exec_n <= 0:
            return {"judge": "FAIL", "reason_code": "EXEC_COUNT_BAD"}
        if not isinstance(floor_v, (int, float)):
            return {"judge": "FAIL", "reason_code": "FLOOR_VALUE_BAD"}
        # Collapse: tiny exec_n makes proportion floor look "met"
        collapsed = bool(receipt.get("collapsed_by_tiny_exec"))
        if collapsed and reported == "SUCCESS":
            return {
                "judge": "FAIL",
                "reason_code": "PROPORTION_FLOOR_COLLAPSE",
                "detail": {"exec_count": exec_n, "floor_value": floor_v},
            }
        if collapsed and reported in (
            "PROPORTION_FLOOR_COLLAPSE",
            "FAIL",
            "INCONCLUSIVE",
        ):
            return {"judge": "PASS", "reason_code": "PROPORTION_FLOOR_COLLAPSE_CAUGHT"}
        if not collapsed and reported in ("SUCCESS", "CONTINUE", "PROPORTION_FLOOR_OK"):
            return {"judge": "PASS", "reason_code": "PROPORTION_FLOOR_OK"}
        return {"judge": "FAIL", "reason_code": "PROPORTION_FLOOR_UNCLASSIFIED"}

    if kind == "absolute_floor_mask":
        basis = receipt.get("denom_basis")
        floor_kind = receipt.get("floor_kind")
        if floor_kind != "absolute":
            return {"judge": "FAIL", "reason_code": "NOT_ABSOLUTE_FLOOR"}
        if basis not in ("constant", "n/a"):
            return {"judge": "FAIL", "reason_code": "ABSOLUTE_DENOM_MUST_BE_CONST"}
        if reported in ("SUCCESS", "CONTINUE", "ABSOLUTE_FLOOR_OK"):
            return {
                "judge": "PASS",
                "reason_code": "ABSOLUTE_FLOOR_OK",
                "detail": {"denom_basis": basis},
            }
        return {"judge": "FAIL", "reason_code": "ABSOLUTE_FLOOR_SHOULD_PASS"}

    if kind == "floor_denom_shared_false_ok":
        # Both floor rows share one "floor" field → absolute read as proportion
        shared = receipt.get("shared_floor_field")
        prop_basis = receipt.get("proportion_denom_basis")
        abs_basis = receipt.get("absolute_denom_basis")
        if shared is not True:
            return {"judge": "FAIL", "reason_code": "SHOULD_SHARE_FLOOR_FIELD"}
        if prop_basis == abs_basis and prop_basis in _DENOM_OK:
            return {"judge": "FAIL", "reason_code": "SHOULD_DISAGREE_BASIS"}
        if reported == "SUCCESS":
            return {
                "judge": "FAIL",
                "reason_code": "FLOOR_DENOM_SHARED_FALSE_OK",
                "detail": {
                    "proportion_denom_basis": prop_basis,
                    "absolute_denom_basis": abs_basis,
                },
            }
        if reported in (
            "FLOOR_DENOM_SHARED_FALSE_OK",
            "FAIL",
            "INCONCLUSIVE",
        ):
            return {"judge": "PASS", "reason_code": "FLOOR_DENOM_SHARED_CAUGHT"}
        return {"judge": "FAIL", "reason_code": "MUST_FLAG_SHARED_FLOOR"}

    if kind == "expected_more_mismatch":
        expected_more = receipt.get("expected_more")
        actual_more = receipt.get("actual_more")
        if expected_more is None or actual_more is None:
            return {"judge": "FAIL", "reason_code": "MORE_FLAGS_MISSING"}
        if expected_more == actual_more:
            return {"judge": "FAIL", "reason_code": "SHOULD_MISMATCH"}
        if reported == "SUCCESS":
            return {
                "judge": "FAIL",
                "reason_code": "EXPECTED_MORE_MISMATCH_FALSE_SUCCESS",
                "detail": {
                    "expected_more": expected_more,
                    "actual_more": actual_more,
                },
            }
        if reported in (
            "EXPECTED_MORE_MISMATCH",
            "FAIL",
            "INCONCLUSIVE",
            "HAS_MORE_NO_CURSOR",
            "PAGINATION_CONTRACT_BREAK",
        ):
            return {"judge": "PASS", "reason_code": "EXPECTED_MORE_MISMATCH"}
        return {"judge": "FAIL", "reason_code": "MUST_FLAG_MORE_MISMATCH"}


    return {"judge": "FAIL", "reason_code": "UNCLASSIFIED", "kind": kind}


def _ledger(rid: str, n: int, hm: bool, cur: Any, last: Any = None, *, with_last: bool = False) -> dict[str, Any]:
    d: dict[str, Any] = {
        "request_id": rid,
        "returned_n": n,
        "has_more": hm,
        "next_cursor": cur,
    }
    if with_last or last is not None:
        d["last_item_id"] = last
    return d


FIXTURES = [
    # --- v0.3 new ---
    {
        "case_id": "HM3-NULL-CURSOR-ABSENT",
        "receipt": {
            "kind": "cursor_absent_null",
            "request_id": "req-301",
            "returned_n": 20,
            "has_more": True,
            "next_cursor": None,
            "items": [{"id": i} for i in range(20)],
            "disk_ledger": _ledger("req-301", 20, True, None),
            "reported_verdict": "HAS_MORE_NO_CURSOR",
        },
        "expect": "NULL_CURSOR_ABSENT",
    },
    {
        "case_id": "HM3-EMPTY-STRING-CURSOR-ABSENT",
        "receipt": {
            "kind": "cursor_absent_empty_string",
            "request_id": "req-302",
            "returned_n": 20,
            "has_more": True,
            "next_cursor": "",
            "items": [{"id": i} for i in range(20)],
            "disk_ledger": _ledger("req-302", 20, True, ""),
            "reported_verdict": "HAS_MORE_NO_CURSOR",
        },
        "expect": "EMPTY_STRING_CURSOR_ABSENT",
    },
    {
        "case_id": "HM3-NULL-CURSOR-FALSE-OK",
        "receipt": {
            "kind": "cursor_absent_null",
            "request_id": "req-303",
            "returned_n": 20,
            "has_more": True,
            "next_cursor": None,
            "items": [{"id": i} for i in range(20)],
            "disk_ledger": _ledger("req-303", 20, True, None),
            "reported_verdict": "SUCCESS",
        },
        "expect": "NULL_CURSOR_FALSE_SUCCESS",
    },
    {
        "case_id": "HM3-CLOSED-SET-BROKEN",
        "receipt": {
            "kind": "cursor_absent_disagree",
            "null_treated_as": "present",
            "empty_treated_as": "absent",
            "closed_set_ok": True,
            "reported_verdict": "SUCCESS",
        },
        "expect": "CURSOR_ABSENT_CLOSED_SET_BROKEN",
    },
    {
        "case_id": "HM3-CLOSED-SET-CAUGHT",
        "receipt": {
            "kind": "cursor_absent_disagree",
            "null_treated_as": "present",
            "empty_treated_as": "absent",
            "closed_set_ok": False,
            "reported_verdict": "CURSOR_ABSENT_CLOSED_SET_BROKEN",
        },
        "expect": "CURSOR_ABSENT_CLOSED_SET_CAUGHT",
    },
    {
        "case_id": "HM3-FULL-PAGE-AT-LIMIT",
        "receipt": {
            "kind": "boundary_full_page_at_limit",
            "request_id": "req-304",
            "returned_n": 20,
            "limit": 20,
            "has_more": True,
            "next_cursor": None,
            "items": [{"id": i} for i in range(20)],
            "page_class": "FULL_PAGE_AT_LIMIT",
            "disk_ledger": _ledger("req-304", 20, True, None, last="19"),
            "reported_verdict": "FULL_PAGE_NO_CURSOR",
        },
        "expect": "FULL_PAGE_AT_LIMIT",
    },
    {
        "case_id": "HM3-FULL-PAGE-FALSE-OK",
        "receipt": {
            "kind": "boundary_full_page_at_limit",
            "request_id": "req-305",
            "returned_n": 20,
            "limit": 20,
            "has_more": True,
            "next_cursor": None,
            "items": [{"id": i} for i in range(20)],
            "page_class": "FULL_PAGE_AT_LIMIT",
            "disk_ledger": _ledger("req-305", 20, True, None, last="19"),
            "reported_verdict": "SUCCESS",
        },
        "expect": "FULL_PAGE_FALSE_SUCCESS",
    },
    {
        "case_id": "HM3-MEASURED-XINGKONG-372339",
        "receipt": {
            "kind": "measured_full_page_corpus",
            "request_id": "372339363507339264",
            "returned_n": 20,
            "limit": 20,
            "has_more": True,
            "next_cursor": None,
            "last_item_id": "372115037474521088",
            "items": [{"id": i} for i in range(20)],
            "page_class": "FULL_PAGE_AT_LIMIT",
            "disk_ledger": _ledger(
                "372339363507339264", 20, True, None, last="372115037474521088"
            ),
            "reported_verdict": "INCONCLUSIVE",
        },
        "expect": "MEASURED_FULL_PAGE_INCONCLUSIVE",
    },
    # --- v0.2 retained cores (subset) ---
    {
        "case_id": "HM3-PAIR-HMTRUE-CUREMPTY-CAUGHT",
        "receipt": {
            "kind": "pairing_break_hm_true_cur_empty",
            "request_id": "req-306",
            "returned_n": 20,
            "has_more": True,
            "next_cursor": "",
            "items": [{"id": i} for i in range(20)],
            "disk_ledger": _ledger("req-306", 20, True, ""),
            "reported_verdict": "PAGINATION_CONTRACT_BREAK",
        },
        "expect": "PAGINATION_CONTRACT_BREAK",
    },
    {
        "case_id": "HM3-PAIR-AGREE-CONTINUE",
        "receipt": {
            "kind": "pairing_agree_continue",
            "request_id": "req-307",
            "returned_n": 20,
            "has_more": True,
            "next_cursor": "cur-ok",
            "items": [{"id": i} for i in range(20)],
            "disk_ledger": _ledger("req-307", 20, True, "cur-ok"),
            "reported_verdict": "CONTINUE",
        },
        "expect": "PAIRING_AGREE_CONTINUE",
    },
    {
        "case_id": "HM3-EMPTY-PAGE-BOUNDARY",
        "receipt": {
            "kind": "boundary_empty_page",
            "request_id": "req-308",
            "returned_n": 0,
            "limit": 20,
            "has_more": True,
            "next_cursor": None,
            "items": [],
            "page_class": "EMPTY_PAGE",
            "disk_ledger": _ledger("req-308", 0, True, None, last=None, with_last=True),
            "reported_verdict": "HAS_MORE_NO_CURSOR",
        },
        "expect": "EMPTY_PAGE_BOUNDARY",
    },
    {
        "case_id": "HM3-GREEN-TWIN-CONTINUE",
        "receipt": {
            "kind": "green_twin",
            "twin_role": "green",
            "twin_pair_id": "pair-A",
            "request_id": "req-309",
            "returned_n": 20,
            "has_more": True,
            "next_cursor": "cur-ok",
            "items": [{"id": i} for i in range(20)],
            "disk_ledger": _ledger("req-309", 20, True, "cur-ok"),
            "reported_verdict": "CONTINUE",
            "expected_reason_code": "CONTINUE",
        },
        "expect": "GREEN_TWIN_OK",
    },
    {
        "case_id": "HM3-RED-TWIN-CURSOR-DROPPED",
        "receipt": {
            "kind": "red_twin",
            "twin_role": "red",
            "twin_pair_id": "pair-A",
            "request_id": "req-310",
            "returned_n": 20,
            "has_more": True,
            "next_cursor": None,
            "items": [{"id": i} for i in range(20)],
            "disk_ledger": _ledger("req-310", 20, True, None),
            "reported_verdict": "PAGINATION_CONTRACT_BREAK",
            "expected_reason_code": "PAGINATION_CONTRACT_BREAK",
        },
        "expect": "RED_TWIN_OK",
    },
    {
        "case_id": "HM3-BOUNDARY-FALSE-SUCCESS",
        "receipt": {
            "kind": "boundary_false_success",
            "request_id": "req-311",
            "returned_n": 20,
            "has_more": True,
            "next_cursor": None,
            "items": [{"id": i} for i in range(20)],
            "disk_ledger": _ledger("req-311", 20, True, None),
            "reported_verdict": "SUCCESS",
        },
        "expect": "HAS_MORE_NO_CURSOR_FALSE_SUCCESS",
    },
    {
        "case_id": "HM3-MISSING-LEDGER",
        "receipt": {
            "kind": "missing_ledger",
            "request_id": "req-312",
            "returned_n": 20,
            "has_more": True,
            "next_cursor": None,
            "reported_verdict": "HAS_MORE_NO_CURSOR",
        },
        "expect": "LEDGER_4TUPLE_MISSING",
    },
    {
        "case_id": "HM3-RETURNED-N-CAUGHT",
        "receipt": {
            "kind": "returned_n_mismatch",
            "request_id": "req-313",
            "returned_n": 20,
            "has_more": False,
            "next_cursor": None,
            "items": [{"id": i} for i in range(17)],
            "disk_ledger": _ledger("req-313", 20, False, None),
            "reported_verdict": "FAIL",
        },
        "expect": "RETURNED_N_MISMATCH",
    },
    # --- v0.4 new (WorkBuddy) ---
    {
        "case_id": "HM4-VALUE-PRESENT-TABLE-TOTAL-MASK",
        "receipt": {
            "kind": "value_present_table_total_mask",
            "table_value_present_total": 40,
            "column_value_counts": None,
            "reported_verdict": "SUCCESS",
        },
        "expect": "VALUE_PRESENT_TABLE_TOTAL_MASK",
    },
    {
        "case_id": "HM4-VALUE-PRESENT-TABLE-TOTAL-CAUGHT",
        "receipt": {
            "kind": "value_present_table_total_mask",
            "table_value_present_total": 40,
            "column_value_counts": None,
            "reported_verdict": "VALUE_PRESENT_TABLE_TOTAL_MASK",
        },
        "expect": "VALUE_PRESENT_TABLE_TOTAL_CAUGHT",
    },
    {
        "case_id": "HM4-VALUE-PRESENT-PER-COL-OK",
        "receipt": {
            "kind": "value_present_per_col_ok",
            "column_value_counts": {"alpha": 12, "beta": 8},
            "column_identity_digests": {
                "alpha": "a" * 32,
                "beta": "b" * 32,
            },
            "reported_verdict": "SUCCESS",
        },
        "expect": "VALUE_PRESENT_PER_COL_OK",
    },
    {
        "case_id": "HM4-VALUE-PRESENT-COL-SWAP-NO-DIGEST",
        "receipt": {
            "kind": "value_present_col_swap_no_digest",
            "column_value_counts": {"alpha": 12, "beta": 8},
            "column_identity_digests": {},
            "reported_verdict": "SUCCESS",
        },
        "expect": "VALUE_PRESENT_COL_SWAP_NO_DIGEST",
    },
    {
        "case_id": "HM4-VALUE-PRESENT-COL-SWAP-CAUGHT",
        "receipt": {
            "kind": "value_present_col_swap_no_digest",
            "column_value_counts": {"alpha": 12, "beta": 8},
            "column_identity_digests": None,
            "reported_verdict": "VALUE_PRESENT_COL_SWAP_NO_DIGEST",
        },
        "expect": "VALUE_PRESENT_COL_SWAP_CAUGHT",
    },
    {
        "case_id": "HM4-PROPORTION-FLOOR-COLLAPSE",
        "receipt": {
            "kind": "proportion_floor_collapse",
            "floor_kind": "proportion",
            "denom_basis": "exec_count",
            "exec_count": 2,
            "floor_value": 0.5,
            "collapsed_by_tiny_exec": True,
            "reported_verdict": "SUCCESS",
        },
        "expect": "PROPORTION_FLOOR_COLLAPSE",
    },
    {
        "case_id": "HM4-PROPORTION-FLOOR-COLLAPSE-CAUGHT",
        "receipt": {
            "kind": "proportion_floor_collapse",
            "floor_kind": "proportion",
            "denom_basis": "exec_count",
            "exec_count": 2,
            "floor_value": 0.5,
            "collapsed_by_tiny_exec": True,
            "reported_verdict": "PROPORTION_FLOOR_COLLAPSE",
        },
        "expect": "PROPORTION_FLOOR_COLLAPSE_CAUGHT",
    },
    {
        "case_id": "HM4-ABSOLUTE-FLOOR-OK",
        "receipt": {
            "kind": "absolute_floor_mask",
            "floor_kind": "absolute",
            "denom_basis": "constant",
            "floor_value": 5,
            "reported_verdict": "SUCCESS",
        },
        "expect": "ABSOLUTE_FLOOR_OK",
    },
    {
        "case_id": "HM4-FLOOR-DENOM-SHARED-FALSE-OK",
        "receipt": {
            "kind": "floor_denom_shared_false_ok",
            "shared_floor_field": True,
            "proportion_denom_basis": "exec_count",
            "absolute_denom_basis": None,
            "reported_verdict": "SUCCESS",
        },
        "expect": "FLOOR_DENOM_SHARED_FALSE_OK",
    },
    {
        "case_id": "HM4-FLOOR-DENOM-SHARED-CAUGHT",
        "receipt": {
            "kind": "floor_denom_shared_false_ok",
            "shared_floor_field": True,
            "proportion_denom_basis": "exec_count",
            "absolute_denom_basis": "n/a",
            "reported_verdict": "FLOOR_DENOM_SHARED_FALSE_OK",
        },
        "expect": "FLOOR_DENOM_SHARED_CAUGHT",
    },
    {
        "case_id": "HM4-EXPECTED-MORE-MISMATCH-FALSE-OK",
        "receipt": {
            "kind": "expected_more_mismatch",
            "expected_more": True,
            "actual_more": False,
            "reported_verdict": "SUCCESS",
        },
        "expect": "EXPECTED_MORE_MISMATCH_FALSE_SUCCESS",
    },
    {
        "case_id": "HM4-EXPECTED-MORE-MISMATCH-CAUGHT",
        "receipt": {
            "kind": "expected_more_mismatch",
            "expected_more": True,
            "actual_more": False,
            "reported_verdict": "EXPECTED_MORE_MISMATCH",
        },
        "expect": "EXPECTED_MORE_MISMATCH",
    },
]


PASS_EXPECTS = {
    "NULL_CURSOR_ABSENT",
    "EMPTY_STRING_CURSOR_ABSENT",
    "CURSOR_ABSENT_CLOSED_SET_CAUGHT",
    "FULL_PAGE_AT_LIMIT",
    "MEASURED_FULL_PAGE_INCONCLUSIVE",
    "PAGINATION_CONTRACT_BREAK",
    "PAIRING_AGREE_CONTINUE",
    "PAIRING_AGREE_END",
    "EMPTY_PAGE_BOUNDARY",
    "NONEMPTY_PAGE_BOUNDARY",
    "GREEN_TWIN_OK",
    "RED_TWIN_OK",
    "RETURNED_N_MISMATCH",
    "VALUE_PRESENT_TABLE_TOTAL_CAUGHT",
    "VALUE_PRESENT_PER_COL_OK",
    "VALUE_PRESENT_COL_SWAP_CAUGHT",
    "PROPORTION_FLOOR_COLLAPSE_CAUGHT",
    "ABSOLUTE_FLOOR_OK",
    "FLOOR_DENOM_SHARED_CAUGHT",
    "EXPECTED_MORE_MISMATCH",
}


def selftest() -> dict[str, Any]:
    results = []
    for fx in FIXTURES:
        got = judge(fx["receipt"])
        ok = got.get("reason_code") == fx["expect"]
        if fx["expect"] in PASS_EXPECTS:
            ok = ok and got.get("judge") == "PASS"
        else:
            ok = ok and got.get("judge") == "FAIL"
        results.append(
            {
                "case_id": fx["case_id"],
                "expect": fx["expect"],
                "got": got,
                "pass": ok,
            }
        )
    passed = sum(1 for r in results if r["pass"])
    canon = json.dumps(
        [{"case_id": f["case_id"], "expect": f["expect"]} for f in FIXTURES],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    total = hashlib.sha256(canon.encode("utf-8")).hexdigest()
    return {
        "fixture": "HAS_MORE_NO_CURSOR",
        "version": "v0.4",
        "credit": ["WorkBuddy", "行空"],
        "rows": len(results),
        "passed": passed,
        "all_pass": passed == len(results),
        "pack_total_sha256": total,
        "results": results,
    }


def main() -> int:
    out = selftest()
    text = json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True)
    print(text)
    with open(__file__, "rb") as f:
        script_sha = hashlib.sha256(f.read()).hexdigest()
    run_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    meta = {
        "script_sha256": script_sha,
        "run_out_sha256": run_sha,
        "passed": f"{out['passed']}/{out['rows']}",
        "pack_total_sha256": out["pack_total_sha256"],
    }
    print("META " + json.dumps(meta), file=sys.stderr)
    return 0 if out["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
