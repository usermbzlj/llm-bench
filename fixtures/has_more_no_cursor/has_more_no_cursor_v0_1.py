#!/usr/bin/env python3
"""HAS_MORE_NO_CURSOR v0.1 — credit 行空

EigenFlux collab 2026-10-24. 行空 broadcast: pagination boundary where
API returns has_more=true with next_cursor=null — neither success nor
clean end-of-stream. Also notes PowerShell 5.1 silently stripping JSON
double-quotes as a related false-normal risk.

Hard rules (行空 + llm-bench owed HAS_MORE_NO_CURSOR):
  1. has_more=true ∧ next_cursor in (null,"",absent) MUST NOT be SUCCESS.
     Correct labels: INCONCLUSIVE | FAIL | HAS_MORE_NO_CURSOR.
  2. Disk ledger MUST record request_id, returned_n, has_more, next_cursor
     as an explicit 4-tuple before any SUCCESS claim.
  3. returned_n MUST equal len(items) when items present; mismatch → FAIL.
  4. has_more=false ∧ next_cursor null/empty → END_OF_STREAM (SUCCESS ok).
  5. has_more=true ∧ non-empty next_cursor → CONTINUE (SUCCESS ok if page ok).
  6. JSON_QUOTE_STRIP: parse failure after quote-strip must not become
     empty-page SUCCESS (treat as PARSE_FAIL).

analyze_only. Stdlib only.
"""
from __future__ import annotations

import hashlib
import json
import sys
from typing import Any


def _cursor_empty(c: Any) -> bool:
    return c is None or (isinstance(c, str) and c.strip() == "")


def _has_ledger(receipt: dict[str, Any]) -> bool:
    ledger = receipt.get("disk_ledger")
    if not isinstance(ledger, dict):
        return False
    for k in ("request_id", "returned_n", "has_more", "next_cursor"):
        if k not in ledger:
            return False
    return True


def judge(receipt: dict[str, Any]) -> dict[str, Any]:
    kind = receipt.get("kind")
    reported = receipt.get("reported_verdict")  # SUCCESS|FAIL|INCONCLUSIVE|HAS_MORE_NO_CURSOR|PARSE_FAIL|END_OF_STREAM|CONTINUE
    has_more = receipt.get("has_more")
    next_cursor = receipt.get("next_cursor")
    items = receipt.get("items")
    returned_n = receipt.get("returned_n")
    request_id = receipt.get("request_id")

    if kind == "boundary_false_success":
        # Classic must-fail: has_more=true, cursor empty, marked SUCCESS
        if has_more is not True or not _cursor_empty(next_cursor):
            return {"judge": "FAIL", "reason_code": "NOT_BOUNDARY"}
        if reported == "SUCCESS":
            return {
                "judge": "FAIL",
                "reason_code": "HAS_MORE_NO_CURSOR_FALSE_SUCCESS",
                "detail": {"request_id": request_id, "returned_n": returned_n},
            }
        return {"judge": "FAIL", "reason_code": "EXPECTED_FALSE_SUCCESS_LABEL"}

    if kind == "boundary_honest":
        if has_more is not True or not _cursor_empty(next_cursor):
            return {"judge": "FAIL", "reason_code": "NOT_BOUNDARY"}
        if reported in ("INCONCLUSIVE", "FAIL", "HAS_MORE_NO_CURSOR"):
            if not _has_ledger(receipt):
                return {"judge": "FAIL", "reason_code": "LEDGER_4TUPLE_MISSING"}
            return {"judge": "PASS", "reason_code": "HAS_MORE_NO_CURSOR"}
        if reported == "SUCCESS":
            return {"judge": "FAIL", "reason_code": "HAS_MORE_NO_CURSOR_FALSE_SUCCESS"}
        return {"judge": "FAIL", "reason_code": "MUST_FLAG_BOUNDARY"}

    if kind == "end_of_stream":
        if has_more is not False or not _cursor_empty(next_cursor):
            return {"judge": "FAIL", "reason_code": "NOT_END_OF_STREAM"}
        if not _has_ledger(receipt):
            return {"judge": "FAIL", "reason_code": "LEDGER_4TUPLE_MISSING"}
        if reported in ("SUCCESS", "END_OF_STREAM"):
            return {"judge": "PASS", "reason_code": "END_OF_STREAM"}
        return {"judge": "FAIL", "reason_code": "END_SHOULD_PASS"}

    if kind == "continue_ok":
        if has_more is not True or _cursor_empty(next_cursor):
            return {"judge": "FAIL", "reason_code": "NOT_CONTINUE"}
        if not _has_ledger(receipt):
            return {"judge": "FAIL", "reason_code": "LEDGER_4TUPLE_MISSING"}
        if reported in ("SUCCESS", "CONTINUE"):
            return {"judge": "PASS", "reason_code": "CONTINUE_OK"}
        return {"judge": "FAIL", "reason_code": "CONTINUE_SHOULD_PASS"}

    if kind == "missing_ledger":
        # Even honest boundary without 4-tuple disk ledger is FAIL
        if _has_ledger(receipt):
            return {"judge": "FAIL", "reason_code": "LEDGER_SHOULD_BE_MISSING"}
        if reported in ("SUCCESS", "INCONCLUSIVE", "HAS_MORE_NO_CURSOR", "FAIL"):
            return {"judge": "FAIL", "reason_code": "LEDGER_4TUPLE_MISSING"}
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

    if kind == "json_quote_strip":
        # PowerShell 5.1 stripped quotes → parse_error; must not be empty SUCCESS
        parse_error = bool(receipt.get("parse_error"))
        empty_items = items == [] or items is None
        if not parse_error:
            return {"judge": "FAIL", "reason_code": "EXPECT_PARSE_ERROR"}
        if reported == "SUCCESS" and empty_items:
            return {"judge": "FAIL", "reason_code": "QUOTE_STRIP_FALSE_EMPTY_SUCCESS"}
        if reported in ("PARSE_FAIL", "FAIL", "INCONCLUSIVE"):
            return {"judge": "PASS", "reason_code": "JSON_QUOTE_STRIP"}
        return {"judge": "FAIL", "reason_code": "MUST_FLAG_PARSE_FAIL"}

    return {"judge": "FAIL", "reason_code": "UNCLASSIFIED", "kind": kind}


def _ledger(rid: str, n: int, hm: bool, cur: Any) -> dict[str, Any]:
    return {
        "request_id": rid,
        "returned_n": n,
        "has_more": hm,
        "next_cursor": cur,
    }


FIXTURES = [
    {
        "case_id": "HM-BOUNDARY-FALSE-SUCCESS",
        "receipt": {
            "kind": "boundary_false_success",
            "request_id": "req-001",
            "returned_n": 20,
            "has_more": True,
            "next_cursor": None,
            "items": [{"id": i} for i in range(20)],
            "disk_ledger": _ledger("req-001", 20, True, None),
            "reported_verdict": "SUCCESS",
        },
        "expect": "HAS_MORE_NO_CURSOR_FALSE_SUCCESS",
    },
    {
        "case_id": "HM-BOUNDARY-HONEST",
        "receipt": {
            "kind": "boundary_honest",
            "request_id": "req-002",
            "returned_n": 20,
            "has_more": True,
            "next_cursor": "",
            "items": [{"id": i} for i in range(20)],
            "disk_ledger": _ledger("req-002", 20, True, ""),
            "reported_verdict": "HAS_MORE_NO_CURSOR",
        },
        "expect": "HAS_MORE_NO_CURSOR",
    },
    {
        "case_id": "HM-BOUNDARY-INCONCLUSIVE",
        "receipt": {
            "kind": "boundary_honest",
            "request_id": "req-003",
            "returned_n": 20,
            "has_more": True,
            "next_cursor": None,
            "disk_ledger": _ledger("req-003", 20, True, None),
            "reported_verdict": "INCONCLUSIVE",
        },
        "expect": "HAS_MORE_NO_CURSOR",
    },
    {
        "case_id": "HM-END-OF-STREAM",
        "receipt": {
            "kind": "end_of_stream",
            "request_id": "req-004",
            "returned_n": 7,
            "has_more": False,
            "next_cursor": None,
            "items": [{"id": i} for i in range(7)],
            "disk_ledger": _ledger("req-004", 7, False, None),
            "reported_verdict": "END_OF_STREAM",
        },
        "expect": "END_OF_STREAM",
    },
    {
        "case_id": "HM-CONTINUE-OK",
        "receipt": {
            "kind": "continue_ok",
            "request_id": "req-005",
            "returned_n": 20,
            "has_more": True,
            "next_cursor": "cur-abc",
            "items": [{"id": i} for i in range(20)],
            "disk_ledger": _ledger("req-005", 20, True, "cur-abc"),
            "reported_verdict": "CONTINUE",
        },
        "expect": "CONTINUE_OK",
    },
    {
        "case_id": "HM-MISSING-LEDGER",
        "receipt": {
            "kind": "missing_ledger",
            "request_id": "req-006",
            "returned_n": 20,
            "has_more": True,
            "next_cursor": None,
            "reported_verdict": "HAS_MORE_NO_CURSOR",
            # no disk_ledger
        },
        "expect": "LEDGER_4TUPLE_MISSING",
    },
    {
        "case_id": "HM-RETURNED-N-MISMATCH",
        "receipt": {
            "kind": "returned_n_mismatch",
            "request_id": "req-007",
            "returned_n": 20,
            "has_more": False,
            "next_cursor": None,
            "items": [{"id": i} for i in range(17)],
            "disk_ledger": _ledger("req-007", 20, False, None),
            "reported_verdict": "SUCCESS",
        },
        "expect": "RETURNED_N_MISMATCH_FALSE_SUCCESS",
    },
    {
        "case_id": "HM-RETURNED-N-CAUGHT",
        "receipt": {
            "kind": "returned_n_mismatch",
            "request_id": "req-008",
            "returned_n": 20,
            "has_more": False,
            "next_cursor": None,
            "items": [{"id": i} for i in range(17)],
            "disk_ledger": _ledger("req-008", 20, False, None),
            "reported_verdict": "FAIL",
        },
        "expect": "RETURNED_N_MISMATCH",
    },
    {
        "case_id": "HM-JSON-QUOTE-STRIP-FALSE-OK",
        "receipt": {
            "kind": "json_quote_strip",
            "request_id": "req-009",
            "parse_error": True,
            "items": [],
            "has_more": False,
            "next_cursor": None,
            "returned_n": 0,
            "reported_verdict": "SUCCESS",
        },
        "expect": "QUOTE_STRIP_FALSE_EMPTY_SUCCESS",
    },
    {
        "case_id": "HM-JSON-QUOTE-STRIP-CAUGHT",
        "receipt": {
            "kind": "json_quote_strip",
            "request_id": "req-010",
            "parse_error": True,
            "items": [],
            "has_more": False,
            "next_cursor": None,
            "returned_n": 0,
            "reported_verdict": "PARSE_FAIL",
        },
        "expect": "JSON_QUOTE_STRIP",
    },
]


def selftest() -> dict[str, Any]:
    results = []
    for fx in FIXTURES:
        got = judge(fx["receipt"])
        ok = got.get("reason_code") == fx["expect"]
        # For PASS arms, also require judge==PASS
        if fx["expect"] in (
            "HAS_MORE_NO_CURSOR",
            "END_OF_STREAM",
            "CONTINUE_OK",
            "RETURNED_N_MISMATCH",
            "JSON_QUOTE_STRIP",
        ):
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
    # digest over case_ids + expect
    canon = json.dumps(
        [{"case_id": f["case_id"], "expect": f["expect"]} for f in FIXTURES],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    total = hashlib.sha256(canon.encode("utf-8")).hexdigest()
    return {
        "fixture": "HAS_MORE_NO_CURSOR",
        "version": "v0.1",
        "credit": ["行空"],
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
