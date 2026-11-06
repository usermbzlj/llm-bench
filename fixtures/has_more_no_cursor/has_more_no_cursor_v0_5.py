#!/usr/bin/env python3
"""HAS_MORE_NO_CURSOR v0.5 — credit 焰曦星Flameblingstar (+ retained v0.1–v0.4)

EigenFlux collab 2026-11-06 (PM after counterexamples to naive invalid).

v0.5 additions (Flameblingstar corrected classify):
  1. LAST_PAGE: HTTP 200 + has_more=false + items non-empty is a normal
     terminal page WITH data — NEVER invalid / NEVER EMPTY.
  2. HAS_MORE_MISSING -> UNDECIDABLE (field absent != structurally illegal).
     Caller may re-fetch once; still missing -> stop & escalate. Do not drop.
  3. Caller terminal rules: only terminal=True stops pagination;
     cursor_rejected must be terminal=False; undecidable re-pull once.
  4. Green twin: 200 + has_more=false + items non-empty -> LAST_PAGE PASS.

Prior versions untouched. analyze_only. Stdlib only.
"""
from __future__ import annotations

import hashlib
import json
import sys
from typing import Any


LAST_PAGE = "LAST_PAGE"
EMPTY_PAGE = "EMPTY_PAGE"
MORE = "MORE"
CURSOR_REJ = "CURSOR_REJECTED"
UNDECIDABLE = "UNDECIDABLE"


def classify(r: dict[str, Any]) -> str:
    """Flameblingstar corrected closed-set classify (HTTP pagination page)."""
    status = r.get("http_status")
    if status == 400:
        if not r.get("error_code"):
            return UNDECIDABLE
        return CURSOR_REJ
    if status == 200:
        if "has_more" not in r:
            return UNDECIDABLE
        if r.get("has_more") is True:
            return MORE
        items = r.get("items")
        if items is None:
            return UNDECIDABLE
        return EMPTY_PAGE if len(items) == 0 else LAST_PAGE
    return UNDECIDABLE


def caller_should_stop(label: str, *, undecidable_retries_left: int) -> tuple[bool, str]:
    """Return (stop, reason). cursor_rejected never terminal; undecidable retry once."""
    if label == MORE:
        return False, "CONTINUE"
    if label == LAST_PAGE:
        return True, "TERMINAL_LAST_PAGE"
    if label == EMPTY_PAGE:
        return True, "TERMINAL_EMPTY_PAGE"
    if label == CURSOR_REJ:
        return False, "CURSOR_REJECTED_NOT_TERMINAL"
    if label == UNDECIDABLE:
        if undecidable_retries_left > 0:
            return False, "UNDECIDABLE_RETRY"
        return True, "UNDECIDABLE_ESCALATE"
    return True, "UNKNOWN_LABEL_STOP"


def judge(case: dict[str, Any]) -> dict[str, Any]:
    kind = case.get("kind")
    page = case.get("page") or {}
    expected = case.get("expected_label")
    reported = case.get("reported_label")
    got = classify(page)

    if kind == "classify":
        if got != expected:
            return {
                "judge": "FAIL",
                "reason_code": "CLASSIFY_MISMATCH",
                "detail": {"got": got, "expected": expected},
            }
        # Naive wrong arms: old code labeled LAST_PAGE or missing-has_more as invalid
        naive = case.get("naive_label")
        if naive is not None and naive == expected:
            return {"judge": "FAIL", "reason_code": "NAIVE_NOT_DISTINCT"}
        if reported is not None and reported != expected:
            return {
                "judge": "FAIL",
                "reason_code": "REPORTED_WRONG",
                "detail": {"reported": reported, "expected": expected},
            }
        return {"judge": "PASS", "reason_code": expected}

    if kind == "caller_terminal":
        label = case.get("label") or got
        left = int(case.get("undecidable_retries_left", 0))
        stop, reason = caller_should_stop(label, undecidable_retries_left=left)
        exp_stop = case.get("expected_stop")
        exp_reason = case.get("expected_reason")
        if stop != exp_stop or (exp_reason and reason != exp_reason):
            return {
                "judge": "FAIL",
                "reason_code": "CALLER_RULE_MISMATCH",
                "detail": {"stop": stop, "reason": reason},
            }
        return {"judge": "PASS", "reason_code": reason}

    if kind == "naive_wrong_last_page_as_invalid":
        # Counterexample Flameblingstar admitted: 200+has_more=false+items non-empty
        # was misjudged invalid. Correct = LAST_PAGE.
        if classify(page) != LAST_PAGE:
            return {"judge": "FAIL", "reason_code": "NOT_LAST_PAGE"}
        if reported in ("invalid", "INVALID", "EMPTY", EMPTY_PAGE):
            return {"judge": "FAIL", "reason_code": "LAST_PAGE_FALSE_INVALID"}
        if reported == LAST_PAGE:
            return {"judge": "PASS", "reason_code": "LAST_PAGE"}
        return {"judge": "FAIL", "reason_code": "MUST_REPORT_LAST_PAGE"}

    if kind == "naive_wrong_missing_has_more_as_invalid":
        if classify(page) != UNDECIDABLE:
            return {"judge": "FAIL", "reason_code": "NOT_UNDECIDABLE"}
        if reported in ("invalid", "INVALID"):
            return {"judge": "FAIL", "reason_code": "MISSING_HAS_MORE_FALSE_INVALID"}
        if reported == UNDECIDABLE:
            return {"judge": "PASS", "reason_code": "UNDECIDABLE"}
        return {"judge": "FAIL", "reason_code": "MUST_REPORT_UNDECIDABLE"}

    return {"judge": "FAIL", "reason_code": "UNKNOWN_KIND"}


CASES: list[dict[str, Any]] = [
    # --- classify closed set (8 rows; Flameblingstar 5->8) ---
    {
        "id": "C1_last_page_with_items",
        "kind": "classify",
        "page": {"http_status": 200, "has_more": False, "items": [{"id": 1}]},
        "expected_label": LAST_PAGE,
        "naive_label": "invalid",
        "provenance": "observed_correction",
        "credit": "焰曦星Flameblingstar",
    },
    {
        "id": "C2_empty_page",
        "kind": "classify",
        "page": {"http_status": 200, "has_more": False, "items": []},
        "expected_label": EMPTY_PAGE,
        "provenance": "hand_built",
        "credit": "焰曦星Flameblingstar",
    },
    {
        "id": "C3_more",
        "kind": "classify",
        "page": {"http_status": 200, "has_more": True, "items": [{"id": 1}]},
        "expected_label": MORE,
        "provenance": "hand_built",
        "credit": "焰曦星Flameblingstar",
    },
    {
        "id": "C4_has_more_missing",
        "kind": "classify",
        "page": {"http_status": 200, "items": [{"id": 1}]},
        "expected_label": UNDECIDABLE,
        "naive_label": "invalid",
        "provenance": "observed_correction",
        "credit": "焰曦星Flameblingstar",
    },
    {
        "id": "C5_items_none_undecidable",
        "kind": "classify",
        "page": {"http_status": 200, "has_more": False, "items": None},
        "expected_label": UNDECIDABLE,
        "provenance": "hand_built",
        "credit": "焰曦星Flameblingstar",
    },
    {
        "id": "C6_cursor_rej",
        "kind": "classify",
        "page": {"http_status": 400, "error_code": "bad_cursor"},
        "expected_label": CURSOR_REJ,
        "provenance": "hand_built",
        "credit": "焰曦星Flameblingstar",
    },
    {
        "id": "C7_400_no_code_undecidable",
        "kind": "classify",
        "page": {"http_status": 400},
        "expected_label": UNDECIDABLE,
        "provenance": "hand_built",
        "credit": "焰曦星Flameblingstar",
    },
    {
        "id": "C8_other_status_undecidable",
        "kind": "classify",
        "page": {"http_status": 500, "has_more": False, "items": []},
        "expected_label": UNDECIDABLE,
        "provenance": "hand_built",
        "credit": "焰曦星Flameblingstar",
    },
    # --- naive wrong must-fail arms ---
    {
        "id": "N1_last_page_false_invalid",
        "kind": "naive_wrong_last_page_as_invalid",
        "page": {"http_status": 200, "has_more": False, "items": [{"id": "x"}]},
        "reported_label": "invalid",
        "provenance": "observed_correction",
        "credit": "焰曦星Flameblingstar",
    },
    {
        "id": "N1g_last_page_green_twin",
        "kind": "naive_wrong_last_page_as_invalid",
        "page": {"http_status": 200, "has_more": False, "items": [{"id": "x"}]},
        "reported_label": LAST_PAGE,
        "provenance": "hand_built",
        "credit": "焰曦星Flameblingstar",
    },
    {
        "id": "N2_missing_has_more_false_invalid",
        "kind": "naive_wrong_missing_has_more_as_invalid",
        "page": {"http_status": 200, "items": []},
        "reported_label": "invalid",
        "provenance": "observed_correction",
        "credit": "焰曦星Flameblingstar",
    },
    {
        "id": "N2g_missing_has_more_green_twin",
        "kind": "naive_wrong_missing_has_more_as_invalid",
        "page": {"http_status": 200, "items": []},
        "reported_label": UNDECIDABLE,
        "provenance": "hand_built",
        "credit": "焰曦星Flameblingstar",
    },
    # --- caller terminal rules ---
    {
        "id": "T1_last_page_stops",
        "kind": "caller_terminal",
        "label": LAST_PAGE,
        "undecidable_retries_left": 0,
        "expected_stop": True,
        "expected_reason": "TERMINAL_LAST_PAGE",
        "credit": "焰曦星Flameblingstar",
    },
    {
        "id": "T2_cursor_rej_not_terminal",
        "kind": "caller_terminal",
        "label": CURSOR_REJ,
        "undecidable_retries_left": 0,
        "expected_stop": False,
        "expected_reason": "CURSOR_REJECTED_NOT_TERMINAL",
        "credit": "焰曦星Flameblingstar",
    },
    {
        "id": "T3_undecidable_retry",
        "kind": "caller_terminal",
        "label": UNDECIDABLE,
        "undecidable_retries_left": 1,
        "expected_stop": False,
        "expected_reason": "UNDECIDABLE_RETRY",
        "credit": "焰曦星Flameblingstar",
    },
    {
        "id": "T4_undecidable_escalate",
        "kind": "caller_terminal",
        "label": UNDECIDABLE,
        "undecidable_retries_left": 0,
        "expected_stop": True,
        "expected_reason": "UNDECIDABLE_ESCALATE",
        "credit": "焰曦星Flameblingstar",
    },
]


def selftest() -> dict[str, Any]:
    rows = []
    passed = failed = 0
    naive_wrong = 0
    for case in CASES:
        out = judge(case)
        ok = out.get("judge") == "PASS"
        # N1/N2 with reported invalid MUST FAIL (must-fail arms)
        if case["id"] in ("N1_last_page_false_invalid", "N2_missing_has_more_false_invalid"):
            ok = out.get("judge") == "FAIL"
            if ok:
                naive_wrong += 1
        if ok:
            passed += 1
        else:
            failed += 1
        rows.append({"id": case["id"], "ok": ok, "out": out, "credit": case.get("credit")})
    return {
        "fixture": "HAS_MORE_NO_CURSOR",
        "version": "0.5",
        "passed": passed,
        "failed": failed,
        "total": len(CASES),
        "naive_wrong_caught": naive_wrong,
        "rows": rows,
    }


def main() -> int:
    result = selftest()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    
    # write run_out next to script
    import os
    out_path = os.path.join(os.path.dirname(__file__), "run_out_v0_5.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return 0 if result["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
