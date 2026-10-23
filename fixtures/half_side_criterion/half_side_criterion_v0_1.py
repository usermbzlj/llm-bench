#!/usr/bin/env python3
"""HALF_SIDE_CRITERION v0.1

Structure-only fixture. Detects threshold / interval checks that implement
only one side of a bounded condition — the missing side silently accepts,
and the ledger looks identical to "both sides checked and passed".

Four machine-checkable rules (from WorkBuddy structure, EigenFlux):
  1. Interval criteria must list lower and upper independently; a missing
     side is NOT_CHECKED, never silently true.
  2. abs / sign-eating transforms must keep a separate sign column.
  3. Boundary points (eq lower, eq upper, interior) each need a row.
  4. Completing the missing side on the same input must flip the verdict;
     if it does not flip, the added side was never wired in.

Structure source: WorkBuddy (EigenFlux). General fixture; no personal
attribution in rows. analyze_only. Stdlib only.
"""
from __future__ import annotations

import json
import sys
from typing import Any


def _has_lower(expr: str) -> bool:
    e = expr.replace(" ", "")
    # lower bound present: 0<=d, d>=0, -N<=d, etc. or explicit 0<=d<th
    if "abs(" in e.lower():
        return False  # abs eats sign; treat as no directional lower
    return (
        "<=" in e
        and not e.startswith("d<")
        and not e.startswith("d<=")
        or e.startswith("0<=")
        or "d>=" in e
        or ">=d" in e
        or (e.count("<") >= 2)  # a<d<b style
        or (e.count("<=") >= 2)
        or ("<" in e and e.index("<") > 0 and not e.startswith("d"))
    )


def _lower_wired(expr: str) -> bool:
    """True iff expression encodes a real lower bound on d (not only upper)."""
    e = expr.replace(" ", "").lower()
    if "abs(" in e:
        return False
    # forms: 0<=d<T, 0<=d<=T, L<=d<T, L<=d<=T, d>=L, d>L
    if e.startswith("0<=") or e.startswith("0<"):
        return True
    if "<=d<" in e or "<=d<=" in e or "<d<" in e or "<d<=" in e:
        return True
    if e.startswith("d>=") or e.startswith("d>"):
        return True
    # bare upper-only: d<T or d<=T
    if e.startswith("d<") or e.startswith("d<="):
        return False
    return False


def _upper_wired(expr: str) -> bool:
    e = expr.replace(" ", "").lower()
    if "abs(" in e:
        # abs(d)<T is an upper on magnitude, count as upper present
        return "<" in e or "<=" in e
    if e.startswith("d<") or e.startswith("d<="):
        return True
    if "d<" in e or "d<=" in e:
        return True
    if e.endswith(">") or ">=d" in e:
        return False
    return "<" in e


def judge(receipt: dict[str, Any]) -> dict[str, Any]:
    kind = receipt.get("kind")

    if kind == "interval_side":
        expr = receipt.get("expr")
        d = receipt.get("d")
        side = receipt.get("side")  # lower|upper|sign|boundary
        reported = receipt.get("verdict")  # FRESH|NOT_FRESH|NEGATIVE|...
        lower_checked = receipt.get("lower_checked")
        upper_checked = receipt.get("upper_checked")
        sign_column = receipt.get("sign_column")
        flip_after_complete = receipt.get("flip_after_complete")

        if not isinstance(expr, str) or not expr:
            return {"judge": "FAIL", "reason_code": "EXPR_MISSING"}
        if not isinstance(d, (int, float)):
            return {"judge": "FAIL", "reason_code": "D_MISSING"}

        lower_ok = _lower_wired(expr) if lower_checked is None else bool(lower_checked)
        upper_ok = _upper_wired(expr) if upper_checked is None else bool(upper_checked)

        # Planted: upper-only expr, negative d, still reported FRESH
        if side == "lower" and not lower_ok and d < 0 and reported == "FRESH":
            return {
                "judge": "FAIL",
                "reason_code": "HALF_SIDE_CRITERION",
                "detail": {"missing": "lower", "d": d, "expr": expr},
            }

        # Completing lower flips FRESH → NOT_FRESH
        if side == "lower" and lower_ok and d < 0 and reported == "NOT_FRESH":
            if flip_after_complete is False:
                return {"judge": "FAIL", "reason_code": "FLIP_NOT_WIRED"}
            return {"judge": "PASS", "reason_code": "LOWER_FLIP_OK"}

        # Sign column required when abs used
        if side == "sign":
            uses_abs = "abs(" in expr.replace(" ", "").lower()
            if uses_abs and sign_column is None and reported != "NEGATIVE":
                return {"judge": "FAIL", "reason_code": "SIGN_COLUMN_EATEN"}
            if d < 0 and reported == "NEGATIVE" and sign_column == "NEGATIVE":
                return {"judge": "PASS", "reason_code": "SIGN_COLUMN_OK"}
            if d < 0 and sign_column is None:
                return {"judge": "FAIL", "reason_code": "SIGN_COLUMN_EATEN"}
            return {"judge": "PASS", "reason_code": "SIGN_OK"}

        # Boundary triad: eq_lower, eq_upper, interior
        if side == "boundary":
            points = receipt.get("boundary_points")
            if not isinstance(points, list):
                return {"judge": "FAIL", "reason_code": "BOUNDARY_POINTS_MISSING"}
            needed = {"eq_lower", "eq_upper", "interior"}
            have = {p.get("point") for p in points if isinstance(p, dict)}
            missing = needed - have
            if missing:
                return {
                    "judge": "FAIL",
                    "reason_code": "HALF_SIDE_BOUNDARY",
                    "detail": {"missing_points": sorted(missing)},
                }
            return {"judge": "PASS", "reason_code": "BOUNDARY_TRIAD_OK"}

        # Both sides wired, positive d inside → FRESH ok
        if lower_ok and upper_ok and 0 <= d and reported == "FRESH":
            return {"judge": "PASS", "reason_code": "BOTH_SIDES_OK"}

        # Upper missing
        if not upper_ok and reported == "FRESH":
            return {
                "judge": "FAIL",
                "reason_code": "HALF_SIDE_CRITERION",
                "detail": {"missing": "upper", "d": d, "expr": expr},
            }

        return {"judge": "PASS", "reason_code": "INTERVAL_OK"}

    if kind == "flip_test":
        before = receipt.get("before_verdict")
        after = receipt.get("after_verdict")
        completed_side = receipt.get("completed_side")
        if before is None or after is None:
            return {"judge": "FAIL", "reason_code": "FLIP_PAIR_MISSING"}
        if before == after:
            return {
                "judge": "FAIL",
                "reason_code": "FLIP_NOT_WIRED",
                "detail": {"completed_side": completed_side},
            }
        return {"judge": "PASS", "reason_code": "FLIP_OK"}

    return {"judge": "FAIL", "reason_code": "UNCLASSIFIED", "kind": kind}


FIXTURES = [
    {
        "case_id": "LOWER-MISSING-NEG-D",
        "receipt": {
            "kind": "interval_side",
            "rule": "freshness",
            "side": "lower",
            "expr": "d<21600",
            "d": -91,
            "verdict": "FRESH",
            "lower_checked": False,
            "upper_checked": True,
            "note": "下界未实现",
        },
        "expect": "HALF_SIDE_CRITERION",
    },
    {
        "case_id": "LOWER-COMPLETED-FLIP",
        "receipt": {
            "kind": "interval_side",
            "rule": "freshness",
            "side": "lower",
            "expr": "0<=d<21600",
            "d": -91,
            "verdict": "NOT_FRESH",
            "lower_checked": True,
            "upper_checked": True,
            "flip_after_complete": True,
            "note": "补下界后翻面",
        },
        "expect": "LOWER_FLIP_OK",
    },
    {
        "case_id": "SIGN-COLUMN-OK",
        "receipt": {
            "kind": "interval_side",
            "rule": "freshness",
            "side": "sign",
            "expr": "sign(d)",
            "d": -91,
            "verdict": "NEGATIVE",
            "sign_column": "NEGATIVE",
            "note": "符号单独成列",
        },
        "expect": "SIGN_COLUMN_OK",
    },
    {
        "case_id": "SIGN-EATEN-BY-ABS",
        "receipt": {
            "kind": "interval_side",
            "rule": "freshness",
            "side": "sign",
            "expr": "abs(d)<21600",
            "d": -91,
            "verdict": "FRESH",
            "sign_column": None,
        },
        "expect": "SIGN_COLUMN_EATEN",
    },
    {
        "case_id": "BOUNDARY-TRIAD-OK",
        "receipt": {
            "kind": "interval_side",
            "side": "boundary",
            "expr": "0<=d<21600",
            "d": 0,
            "verdict": "FRESH",
            "boundary_points": [
                {"point": "eq_lower", "d": 0, "verdict": "FRESH"},
                {"point": "eq_upper", "d": 21600, "verdict": "NOT_FRESH"},
                {"point": "interior", "d": 100, "verdict": "FRESH"},
            ],
        },
        "expect": "BOUNDARY_TRIAD_OK",
    },
    {
        "case_id": "BOUNDARY-MISSING-EQ-UPPER",
        "receipt": {
            "kind": "interval_side",
            "side": "boundary",
            "expr": "0<=d<21600",
            "d": 0,
            "verdict": "FRESH",
            "boundary_points": [
                {"point": "eq_lower", "d": 0, "verdict": "FRESH"},
                {"point": "interior", "d": 100, "verdict": "FRESH"},
            ],
        },
        "expect": "HALF_SIDE_BOUNDARY",
    },
    {
        "case_id": "FLIP-OK",
        "receipt": {
            "kind": "flip_test",
            "completed_side": "lower",
            "before_verdict": "FRESH",
            "after_verdict": "NOT_FRESH",
        },
        "expect": "FLIP_OK",
    },
    {
        "case_id": "FLIP-NOT-WIRED",
        "receipt": {
            "kind": "flip_test",
            "completed_side": "lower",
            "before_verdict": "FRESH",
            "after_verdict": "FRESH",
        },
        "expect": "FLIP_NOT_WIRED",
    },
    {
        "case_id": "BOTH-SIDES-POS-OK",
        "receipt": {
            "kind": "interval_side",
            "side": "lower",
            "expr": "0<=d<21600",
            "d": 100,
            "verdict": "FRESH",
            "lower_checked": True,
            "upper_checked": True,
        },
        "expect": "BOTH_SIDES_OK",
    },
]


def main() -> int:
    rows = []
    ok = True
    for fx in FIXTURES:
        got = judge(fx["receipt"])
        match = got.get("reason_code") == fx["expect"]
        ok = ok and match
        rows.append(
            {
                "case_id": fx["case_id"],
                "expect": fx["expect"],
                "got": got.get("reason_code"),
                "match": match,
                "judge": got,
            }
        )
    out = {
        "version": "HALF_SIDE_CRITERION/v0.1",
        "all_match": ok,
        "n": len(rows),
        "rows": rows,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
