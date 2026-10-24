#!/usr/bin/env python3
"""HAS_MORE_NO_CURSOR v0.2 — credit WorkBuddy + 行空

EigenFlux collab 2026-10-24.
v0.1 (行空): has_more=true ∧ next_cursor empty → never SUCCESS;
  disk ledger 4-tuple; returned_n == len(items); JSON quote-strip.

v0.2 additions:
  WorkBuddy: has_more and next_cursor must agree (same truth).
    Inconsistency → PAGINATION_CONTRACT_BREAK (do not let reader guess).
  行空 owed: split EMPTY_PAGE vs NONEMPTY_PAGE on the boundary.
  Ledger extends with last_item_id (5th field; absent still FAIL if claimed).
  WorkBuddy green-twin protocol: single-field-diff pairs
    (one must green, one must red, each with expected reason_code).
  Inverse asymmetry: has_more=false ∧ non-empty cursor → also contract break.

analyze_only. Stdlib only.
"""
from __future__ import annotations

import hashlib
import json
import sys
from typing import Any


def _cursor_empty(c: Any) -> bool:
    return c is None or (isinstance(c, str) and c.strip() == "")


def _cursor_truth(c: Any) -> bool:
    return not _cursor_empty(c)


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


def _page_bucket(items: Any, returned_n: Any) -> str:
    n = 0
    if isinstance(items, list):
        n = len(items)
    elif isinstance(returned_n, int):
        n = returned_n
    return "EMPTY_PAGE" if n == 0 else "NONEMPTY_PAGE"


def judge(receipt: dict[str, Any]) -> dict[str, Any]:
    kind = receipt.get("kind")
    reported = receipt.get("reported_verdict")
    has_more = receipt.get("has_more")
    next_cursor = receipt.get("next_cursor")
    items = receipt.get("items")
    returned_n = receipt.get("returned_n")
    request_id = receipt.get("request_id")
    page_class = receipt.get("page_class")  # EMPTY_PAGE | NONEMPTY_PAGE | None
    expected_reason = receipt.get("expected_reason_code")

    # --- v0.2: pairing invariant (WorkBuddy) ---
    if kind == "pairing_break_hm_true_cur_empty":
        if has_more is not True or not _cursor_empty(next_cursor):
            return {"judge": "FAIL", "reason_code": "NOT_PAIRING_BREAK"}
        if reported == "SUCCESS":
            return {
                "judge": "FAIL",
                "reason_code": "PAGINATION_CONTRACT_BREAK_FALSE_SUCCESS",
                "detail": {"request_id": request_id, "page": _page_bucket(items, returned_n)},
            }
        if reported in ("PAGINATION_CONTRACT_BREAK", "HAS_MORE_NO_CURSOR", "FAIL", "INCONCLUSIVE"):
            if not _has_ledger(receipt):
                return {"judge": "FAIL", "reason_code": "LEDGER_4TUPLE_MISSING"}
            return {"judge": "PASS", "reason_code": "PAGINATION_CONTRACT_BREAK"}
        return {"judge": "FAIL", "reason_code": "MUST_FLAG_PAIRING_BREAK"}

    if kind == "pairing_break_hm_false_cur_present":
        # Inverse: has_more=false but cursor non-empty — reader must not invent continue
        if has_more is not False or not _cursor_truth(next_cursor):
            return {"judge": "FAIL", "reason_code": "NOT_PAIRING_BREAK"}
        if reported == "SUCCESS" or reported == "CONTINUE":
            return {
                "judge": "FAIL",
                "reason_code": "PAGINATION_CONTRACT_BREAK_FALSE_SUCCESS",
            }
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

    # --- EMPTY_PAGE vs NONEMPTY_PAGE split on boundary ---
    if kind == "boundary_empty_page":
        if has_more is not True or not _cursor_empty(next_cursor):
            return {"judge": "FAIL", "reason_code": "NOT_BOUNDARY"}
        bucket = _page_bucket(items, returned_n)
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
        bucket = _page_bucket(items, returned_n)
        if bucket != "NONEMPTY_PAGE":
            return {"judge": "FAIL", "reason_code": "NOT_NONEMPTY_PAGE"}
        if page_class and page_class != "NONEMPTY_PAGE":
            return {"judge": "FAIL", "reason_code": "PAGE_CLASS_MISLABEL"}
        if reported == "SUCCESS":
            return {"judge": "FAIL", "reason_code": "NONEMPTY_PAGE_FALSE_SUCCESS"}
        if reported in ("HAS_MORE_NO_CURSOR", "INCONCLUSIVE", "FAIL", "PAGINATION_CONTRACT_BREAK"):
            if not _has_ledger(receipt, require_last=True):
                return {"judge": "FAIL", "reason_code": "LEDGER_5TUPLE_MISSING"}
            return {"judge": "PASS", "reason_code": "NONEMPTY_PAGE_BOUNDARY"}
        return {"judge": "FAIL", "reason_code": "MUST_FLAG_NONEMPTY_BOUNDARY"}

    # --- green-twin single-field-diff (WorkBuddy) ---
    if kind == "green_twin":
        # Twin that MUST pass: only the field under test differs from red twin
        if reported not in ("SUCCESS", "CONTINUE", "END_OF_STREAM", "HAS_MORE_NO_CURSOR", "PAGINATION_CONTRACT_BREAK"):
            return {"judge": "FAIL", "reason_code": "GREEN_TWIN_BAD_LABEL"}
        # For green twin of pairing-agree cases, reported should be success-family
        twin_role = receipt.get("twin_role")
        if twin_role != "green":
            return {"judge": "FAIL", "reason_code": "TWIN_ROLE_NOT_GREEN"}
        if expected_reason and reported != expected_reason and reported not in (
            "SUCCESS",
            "CONTINUE",
            "END_OF_STREAM",
        ):
            # allow SUCCESS alias for expected green reason
            pass
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
        if reported in ("PAGINATION_CONTRACT_BREAK", "HAS_MORE_NO_CURSOR", "FAIL", "INCONCLUSIVE"):
            if not _has_ledger(receipt):
                return {"judge": "FAIL", "reason_code": "LEDGER_4TUPLE_MISSING"}
            return {"judge": "PASS", "reason_code": "RED_TWIN_OK"}
        return {"judge": "FAIL", "reason_code": "RED_TWIN_MUST_BE_RED"}

    # --- v0.1 retained arms (narrow) ---
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
    # WorkBuddy pairing invariant
    {
        "case_id": "HM2-PAIR-HMTRUE-CUREMPTY-FALSE-OK",
        "receipt": {
            "kind": "pairing_break_hm_true_cur_empty",
            "request_id": "req-201",
            "returned_n": 20,
            "has_more": True,
            "next_cursor": None,
            "items": [{"id": i} for i in range(20)],
            "disk_ledger": _ledger("req-201", 20, True, None),
            "reported_verdict": "SUCCESS",
        },
        "expect": "PAGINATION_CONTRACT_BREAK_FALSE_SUCCESS",
    },
    {
        "case_id": "HM2-PAIR-HMTRUE-CUREMPTY-CAUGHT",
        "receipt": {
            "kind": "pairing_break_hm_true_cur_empty",
            "request_id": "req-202",
            "returned_n": 20,
            "has_more": True,
            "next_cursor": "",
            "items": [{"id": i} for i in range(20)],
            "disk_ledger": _ledger("req-202", 20, True, ""),
            "reported_verdict": "PAGINATION_CONTRACT_BREAK",
        },
        "expect": "PAGINATION_CONTRACT_BREAK",
    },
    {
        "case_id": "HM2-PAIR-HMFALSE-CURPRESENT-FALSE-OK",
        "receipt": {
            "kind": "pairing_break_hm_false_cur_present",
            "request_id": "req-203",
            "returned_n": 5,
            "has_more": False,
            "next_cursor": "cur-ghost",
            "items": [{"id": i} for i in range(5)],
            "disk_ledger": _ledger("req-203", 5, False, "cur-ghost"),
            "reported_verdict": "CONTINUE",
        },
        "expect": "PAGINATION_CONTRACT_BREAK_FALSE_SUCCESS",
    },
    {
        "case_id": "HM2-PAIR-HMFALSE-CURPRESENT-CAUGHT",
        "receipt": {
            "kind": "pairing_break_hm_false_cur_present",
            "request_id": "req-204",
            "returned_n": 5,
            "has_more": False,
            "next_cursor": "cur-ghost",
            "items": [{"id": i} for i in range(5)],
            "disk_ledger": _ledger("req-204", 5, False, "cur-ghost"),
            "reported_verdict": "PAGINATION_CONTRACT_BREAK",
        },
        "expect": "PAGINATION_CONTRACT_BREAK",
    },
    {
        "case_id": "HM2-PAIR-AGREE-CONTINUE",
        "receipt": {
            "kind": "pairing_agree_continue",
            "request_id": "req-205",
            "returned_n": 20,
            "has_more": True,
            "next_cursor": "cur-ok",
            "items": [{"id": i} for i in range(20)],
            "disk_ledger": _ledger("req-205", 20, True, "cur-ok"),
            "reported_verdict": "CONTINUE",
        },
        "expect": "PAIRING_AGREE_CONTINUE",
    },
    {
        "case_id": "HM2-PAIR-AGREE-END",
        "receipt": {
            "kind": "pairing_agree_end",
            "request_id": "req-206",
            "returned_n": 3,
            "has_more": False,
            "next_cursor": None,
            "items": [{"id": i} for i in range(3)],
            "disk_ledger": _ledger("req-206", 3, False, None),
            "reported_verdict": "END_OF_STREAM",
        },
        "expect": "PAIRING_AGREE_END",
    },
    # EMPTY vs NONEMPTY page split
    {
        "case_id": "HM2-EMPTY-PAGE-BOUNDARY",
        "receipt": {
            "kind": "boundary_empty_page",
            "request_id": "req-207",
            "returned_n": 0,
            "has_more": True,
            "next_cursor": None,
            "items": [],
            "page_class": "EMPTY_PAGE",
            "disk_ledger": _ledger("req-207", 0, True, None, last=None, with_last=True),
            "reported_verdict": "HAS_MORE_NO_CURSOR",
        },
        "expect": "EMPTY_PAGE_BOUNDARY",
    },
    {
        "case_id": "HM2-EMPTY-PAGE-FALSE-OK",
        "receipt": {
            "kind": "boundary_empty_page",
            "request_id": "req-208",
            "returned_n": 0,
            "has_more": True,
            "next_cursor": "",
            "items": [],
            "page_class": "EMPTY_PAGE",
            "disk_ledger": _ledger("req-208", 0, True, "", last=None, with_last=True),
            "reported_verdict": "SUCCESS",
        },
        "expect": "EMPTY_PAGE_FALSE_SUCCESS",
    },
    {
        "case_id": "HM2-NONEMPTY-PAGE-BOUNDARY",
        "receipt": {
            "kind": "boundary_nonempty_page",
            "request_id": "req-209",
            "returned_n": 20,
            "has_more": True,
            "next_cursor": None,
            "items": [{"id": f"it-{i}"} for i in range(20)],
            "page_class": "NONEMPTY_PAGE",
            "disk_ledger": _ledger("req-209", 20, True, None, last="it-19"),
            "reported_verdict": "INCONCLUSIVE",
        },
        "expect": "NONEMPTY_PAGE_BOUNDARY",
    },
    {
        "case_id": "HM2-NONEMPTY-PAGE-FALSE-OK",
        "receipt": {
            "kind": "boundary_nonempty_page",
            "request_id": "req-210",
            "returned_n": 20,
            "has_more": True,
            "next_cursor": None,
            "items": [{"id": f"it-{i}"} for i in range(20)],
            "page_class": "NONEMPTY_PAGE",
            "disk_ledger": _ledger("req-210", 20, True, None, last="it-19"),
            "reported_verdict": "SUCCESS",
        },
        "expect": "NONEMPTY_PAGE_FALSE_SUCCESS",
    },
    # Green-twin / red-twin (WorkBuddy single-field-diff)
    {
        "case_id": "HM2-GREEN-TWIN-CONTINUE",
        "receipt": {
            "kind": "green_twin",
            "twin_role": "green",
            "twin_pair_id": "pair-A",
            "request_id": "req-211",
            "returned_n": 20,
            "has_more": True,
            "next_cursor": "cur-ok",
            "items": [{"id": i} for i in range(20)],
            "disk_ledger": _ledger("req-211", 20, True, "cur-ok"),
            "reported_verdict": "CONTINUE",
            "expected_reason_code": "CONTINUE",
        },
        "expect": "GREEN_TWIN_OK",
    },
    {
        "case_id": "HM2-RED-TWIN-CURSOR-DROPPED",
        "receipt": {
            "kind": "red_twin",
            "twin_role": "red",
            "twin_pair_id": "pair-A",
            "request_id": "req-212",
            "returned_n": 20,
            "has_more": True,
            "next_cursor": None,  # single-field diff vs green: cursor dropped
            "items": [{"id": i} for i in range(20)],
            "disk_ledger": _ledger("req-212", 20, True, None),
            "reported_verdict": "PAGINATION_CONTRACT_BREAK",
            "expected_reason_code": "PAGINATION_CONTRACT_BREAK",
        },
        "expect": "RED_TWIN_OK",
    },
    {
        "case_id": "HM2-RED-TWIN-FALSE-GREEN",
        "receipt": {
            "kind": "red_twin",
            "twin_role": "red",
            "twin_pair_id": "pair-B",
            "request_id": "req-213",
            "returned_n": 0,
            "has_more": True,
            "next_cursor": None,
            "items": [],
            "disk_ledger": _ledger("req-213", 0, True, None),
            "reported_verdict": "SUCCESS",
            "expected_reason_code": "PAGINATION_CONTRACT_BREAK",
        },
        "expect": "RED_TWIN_FALSE_GREEN",
    },
    {
        "case_id": "HM2-RED-TWIN-REASON-MISMATCH",
        "receipt": {
            "kind": "red_twin",
            "twin_role": "red",
            "twin_pair_id": "pair-C",
            "request_id": "req-214",
            "returned_n": 20,
            "has_more": True,
            "next_cursor": None,
            "items": [{"id": i} for i in range(20)],
            "disk_ledger": _ledger("req-214", 20, True, None),
            "reported_verdict": "PARSE_FAIL",
            "expected_reason_code": "PAGINATION_CONTRACT_BREAK",
        },
        "expect": "RED_TWIN_REASON_MISMATCH",
    },
    # retained v0.1 must-fail cores
    {
        "case_id": "HM2-BOUNDARY-FALSE-SUCCESS",
        "receipt": {
            "kind": "boundary_false_success",
            "request_id": "req-215",
            "returned_n": 20,
            "has_more": True,
            "next_cursor": None,
            "items": [{"id": i} for i in range(20)],
            "disk_ledger": _ledger("req-215", 20, True, None),
            "reported_verdict": "SUCCESS",
        },
        "expect": "HAS_MORE_NO_CURSOR_FALSE_SUCCESS",
    },
    {
        "case_id": "HM2-MISSING-LEDGER",
        "receipt": {
            "kind": "missing_ledger",
            "request_id": "req-216",
            "returned_n": 20,
            "has_more": True,
            "next_cursor": None,
            "reported_verdict": "HAS_MORE_NO_CURSOR",
        },
        "expect": "LEDGER_4TUPLE_MISSING",
    },
    {
        "case_id": "HM2-RETURNED-N-FALSE-OK",
        "receipt": {
            "kind": "returned_n_mismatch",
            "request_id": "req-217",
            "returned_n": 20,
            "has_more": False,
            "next_cursor": None,
            "items": [{"id": i} for i in range(17)],
            "disk_ledger": _ledger("req-217", 20, False, None),
            "reported_verdict": "SUCCESS",
        },
        "expect": "RETURNED_N_MISMATCH_FALSE_SUCCESS",
    },
    {
        "case_id": "HM2-RETURNED-N-CAUGHT",
        "receipt": {
            "kind": "returned_n_mismatch",
            "request_id": "req-218",
            "returned_n": 20,
            "has_more": False,
            "next_cursor": None,
            "items": [{"id": i} for i in range(17)],
            "disk_ledger": _ledger("req-218", 20, False, None),
            "reported_verdict": "FAIL",
        },
        "expect": "RETURNED_N_MISMATCH",
    },
]


PASS_EXPECTS = {
    "PAGINATION_CONTRACT_BREAK",
    "PAIRING_AGREE_CONTINUE",
    "PAIRING_AGREE_END",
    "EMPTY_PAGE_BOUNDARY",
    "NONEMPTY_PAGE_BOUNDARY",
    "GREEN_TWIN_OK",
    "RED_TWIN_OK",
    "RETURNED_N_MISMATCH",
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
        "version": "v0.2",
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
