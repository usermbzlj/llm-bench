#!/usr/bin/env python3
"""DUP_SUM_GREEN v0.1

Structure-only fixture. Detects conservation gates that stay green under
duplicate rows because every bucket doubles with the total — sum(bucket)
== total still holds, so the ledger looks identical to a clean run.

Four machine-checkable rules (from 木木 / Mumu structure, EigenFlux):
  1. A sum-conservation gate alone is NOT sufficient; a distinct-key gate
     on the natural key (e.g. (day, round)) must also exist.
  2. When the distinct-key gate is absent, the verdict is GATE_ABSENT —
     never PASS. "No gate ran" ≠ "gate passed".
  3. Injecting the distinct-key gate on the same duplicated input MUST
     flip PASS → FAIL; if it does not flip, the gate was never wired.
  4. A clean input (no duplicates) with both gates present must PASS.

Structure source: 木木 (Mumu) DUP-GREEN-01 (EigenFlux). General fixture;
no personal attribution in rows. analyze_only. Stdlib only.
"""
from __future__ import annotations

import json
import sys
from typing import Any


def _row_keys(rows: list[dict[str, Any]], key_fields: list[str]) -> list[tuple]:
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        out.append(tuple(r.get(f) for f in key_fields))
    return out


def judge(receipt: dict[str, Any]) -> dict[str, Any]:
    kind = receipt.get("kind")

    if kind == "dup_sum":
        rows = receipt.get("rows")
        key_fields = receipt.get("key_fields") or ["day", "round"]
        buckets = receipt.get("buckets")  # {name: sum}
        total = receipt.get("total")
        observed = receipt.get("observed_verdict")  # PASS|FAIL|GATE_ABSENT
        gates = receipt.get("gates") or []
        # gates is list of {"name":..., "present": bool, "verdict": ...}

        if not isinstance(rows, list) or not rows:
            return {"judge": "FAIL", "reason_code": "ROWS_MISSING"}
        if not isinstance(buckets, dict) or total is None:
            return {"judge": "FAIL", "reason_code": "BUCKETS_MISSING"}

        keys = _row_keys(rows, list(key_fields))
        n_rows = len(keys)
        n_distinct = len(set(keys))
        has_dup = n_distinct < n_rows

        bucket_sum = sum(buckets.values()) if buckets else None
        sum_ok = bucket_sum == total

        gate_names = {g.get("name") for g in gates if isinstance(g, dict)}
        distinct_gate = next(
            (g for g in gates if isinstance(g, dict) and g.get("name") == "distinct_key"),
            None,
        )
        sum_gate = next(
            (g for g in gates if isinstance(g, dict) and g.get("name") == "sum_conservation"),
            None,
        )

        distinct_present = bool(distinct_gate and distinct_gate.get("present"))
        sum_present = bool(sum_gate and sum_gate.get("present"))

        # Planted: duplicates + only sum gate → observed PASS (false green)
        if has_dup and sum_ok and sum_present and not distinct_present:
            if observed == "PASS":
                return {
                    "judge": "FAIL",
                    "reason_code": "DUP_SUM_GREEN",
                    "detail": {
                        "n_rows": n_rows,
                        "n_distinct": n_distinct,
                        "bucket_sum": bucket_sum,
                        "total": total,
                    },
                }
            if observed == "GATE_ABSENT":
                return {"judge": "PASS", "reason_code": "GATE_ABSENT_OK"}
            return {
                "judge": "FAIL",
                "reason_code": "DUP_SUM_GREEN",
                "detail": {"observed": observed},
            }

        # Distinct gate present + duplicates → must FAIL
        if has_dup and distinct_present:
            dv = distinct_gate.get("verdict") if distinct_gate else None
            if dv == "FAIL" and observed == "FAIL":
                return {"judge": "PASS", "reason_code": "DISTINCT_CATCHES_DUP"}
            if observed == "PASS":
                return {
                    "judge": "FAIL",
                    "reason_code": "DISTINCT_NOT_WIRED",
                    "detail": {"distinct_verdict": dv},
                }
            return {"judge": "PASS", "reason_code": "DISTINCT_CATCHES_DUP"}

        # Clean input, both gates present
        if not has_dup and sum_present and distinct_present and sum_ok:
            if observed == "PASS":
                return {"judge": "PASS", "reason_code": "CLEAN_BOTH_GATES_OK"}
            return {
                "judge": "FAIL",
                "reason_code": "CLEAN_SHOULD_PASS",
                "detail": {"observed": observed},
            }

        return {"judge": "PASS", "reason_code": "DUP_SUM_OK"}

    if kind == "flip_test":
        before = receipt.get("before_verdict")
        after = receipt.get("after_verdict")
        injected = receipt.get("injected_gate")
        if before is None or after is None:
            return {"judge": "FAIL", "reason_code": "FLIP_PAIR_MISSING"}
        if injected != "distinct_key":
            return {"judge": "FAIL", "reason_code": "INJECT_GATE_WRONG"}
        if before == after:
            return {
                "judge": "FAIL",
                "reason_code": "FLIP_NOT_WIRED",
                "detail": {"injected": injected},
            }
        if before == "PASS" and after == "FAIL":
            return {"judge": "PASS", "reason_code": "FLIP_OK"}
        return {
            "judge": "FAIL",
            "reason_code": "FLIP_UNEXPECTED",
            "detail": {"before": before, "after": after},
        }

    if kind == "gate_absent":
        # Third column: missing gate must be GATE_ABSENT, not PASS
        gate_name = receipt.get("gate_name")
        present = receipt.get("gate_present")
        observed = receipt.get("observed_verdict")
        if gate_name != "distinct_key":
            return {"judge": "FAIL", "reason_code": "GATE_NAME_UNEXPECTED"}
        if present is True:
            return {"judge": "FAIL", "reason_code": "GATE_CLAIMED_PRESENT"}
        if observed == "PASS":
            return {
                "judge": "FAIL",
                "reason_code": "ABSENT_MARKED_PASS",
                "detail": {"gate": gate_name},
            }
        if observed == "GATE_ABSENT":
            return {"judge": "PASS", "reason_code": "GATE_ABSENT_OK"}
        return {
            "judge": "FAIL",
            "reason_code": "ABSENT_MARKED_OTHER",
            "detail": {"observed": observed},
        }

    return {"judge": "FAIL", "reason_code": "UNCLASSIFIED", "kind": kind}


_DUP_ROWS = [
    {"day": "d1", "round": 7, "bucket": "A", "n": 3},
    {"day": "d1", "round": 7, "bucket": "A", "n": 3},  # duplicate
    {"day": "d1", "round": 8, "bucket": "B", "n": 2},
    {"day": "d1", "round": 8, "bucket": "B", "n": 2},  # duplicate
]
# After doubling: A=6, B=4, total=10 — sum conserved
_DUP_BUCKETS = {"A": 6, "B": 4}
_DUP_TOTAL = 10

_CLEAN_ROWS = [
    {"day": "d1", "round": 7, "bucket": "A", "n": 3},
    {"day": "d1", "round": 8, "bucket": "B", "n": 2},
]
_CLEAN_BUCKETS = {"A": 3, "B": 2}
_CLEAN_TOTAL = 5


FIXTURES = [
    {
        "case_id": "DUP-GREEN-01",
        "receipt": {
            "kind": "dup_sum",
            "rows": _DUP_ROWS,
            "key_fields": ["day", "round"],
            "buckets": _DUP_BUCKETS,
            "total": _DUP_TOTAL,
            "observed_verdict": "PASS",
            "gates": [
                {"name": "sum_conservation", "present": True, "verdict": "PASS"},
            ],
            "note": "每一项翻倍，sum==total 仍绿",
        },
        "expect": "DUP_SUM_GREEN",
    },
    {
        "case_id": "DUP-GATE-ABSENT-OK",
        "receipt": {
            "kind": "dup_sum",
            "rows": _DUP_ROWS,
            "key_fields": ["day", "round"],
            "buckets": _DUP_BUCKETS,
            "total": _DUP_TOTAL,
            "observed_verdict": "GATE_ABSENT",
            "gates": [
                {"name": "sum_conservation", "present": True, "verdict": "PASS"},
            ],
            "note": "缺 distinct 门 → GATE_ABSENT，不记 PASS",
        },
        "expect": "GATE_ABSENT_OK",
    },
    {
        "case_id": "DISTINCT-CATCHES-DUP",
        "receipt": {
            "kind": "dup_sum",
            "rows": _DUP_ROWS,
            "key_fields": ["day", "round"],
            "buckets": _DUP_BUCKETS,
            "total": _DUP_TOTAL,
            "observed_verdict": "FAIL",
            "gates": [
                {"name": "sum_conservation", "present": True, "verdict": "PASS"},
                {"name": "distinct_key", "present": True, "verdict": "FAIL"},
            ],
        },
        "expect": "DISTINCT_CATCHES_DUP",
    },
    {
        "case_id": "DISTINCT-NOT-WIRED",
        "receipt": {
            "kind": "dup_sum",
            "rows": _DUP_ROWS,
            "key_fields": ["day", "round"],
            "buckets": _DUP_BUCKETS,
            "total": _DUP_TOTAL,
            "observed_verdict": "PASS",
            "gates": [
                {"name": "sum_conservation", "present": True, "verdict": "PASS"},
                {"name": "distinct_key", "present": True, "verdict": "PASS"},
            ],
            "note": "声称有 distinct 门但仍 PASS → 未真正接线",
        },
        "expect": "DISTINCT_NOT_WIRED",
    },
    {
        "case_id": "CLEAN-BOTH-GATES-OK",
        "receipt": {
            "kind": "dup_sum",
            "rows": _CLEAN_ROWS,
            "key_fields": ["day", "round"],
            "buckets": _CLEAN_BUCKETS,
            "total": _CLEAN_TOTAL,
            "observed_verdict": "PASS",
            "gates": [
                {"name": "sum_conservation", "present": True, "verdict": "PASS"},
                {"name": "distinct_key", "present": True, "verdict": "PASS"},
            ],
        },
        "expect": "CLEAN_BOTH_GATES_OK",
    },
    {
        "case_id": "FLIP-OK",
        "receipt": {
            "kind": "flip_test",
            "injected_gate": "distinct_key",
            "before_verdict": "PASS",
            "after_verdict": "FAIL",
        },
        "expect": "FLIP_OK",
    },
    {
        "case_id": "FLIP-NOT-WIRED",
        "receipt": {
            "kind": "flip_test",
            "injected_gate": "distinct_key",
            "before_verdict": "PASS",
            "after_verdict": "PASS",
        },
        "expect": "FLIP_NOT_WIRED",
    },
    {
        "case_id": "ABSENT-MARKED-PASS",
        "receipt": {
            "kind": "gate_absent",
            "gate_name": "distinct_key",
            "gate_present": False,
            "observed_verdict": "PASS",
        },
        "expect": "ABSENT_MARKED_PASS",
    },
    {
        "case_id": "GATE-ABSENT-COL-OK",
        "receipt": {
            "kind": "gate_absent",
            "gate_name": "distinct_key",
            "gate_present": False,
            "observed_verdict": "GATE_ABSENT",
        },
        "expect": "GATE_ABSENT_OK",
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
        "version": "DUP_SUM_GREEN/v0.1",
        "all_match": ok,
        "n": len(rows),
        "rows": rows,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
