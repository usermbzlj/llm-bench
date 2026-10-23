#!/usr/bin/env python3
"""CRITERIA_LAG_UNAUTH v0.1

Structure-only fixture (no real artifacts). Detects silent pass-rate inflation
when a stale criteria_version row is settled into the same batch denominator
as the batch-key version without being marked stale / excluded.

Companion gate: ARRIVAL_ASSERT_MUST_FAIL — the "reached criteria" assertion
must itself have a must-fail sample, or admission silently collapses.

analyze_only. Stdlib only.
"""
from __future__ import annotations

import json
import sys
from typing import Any


def judge(receipt: dict[str, Any]) -> dict[str, Any]:
    kind = receipt.get("kind")

    if kind == "criteria_lag_batch":
        batch_criteria = receipt.get("batch_criteria_version")
        rows = receipt.get("rows") or []
        if not isinstance(rows, list) or len(rows) < 2:
            return {"judge": "FAIL", "reason_code": "BATCH_ROWS_MISSING"}
        if batch_criteria is None:
            return {"judge": "FAIL", "reason_code": "BATCH_CRITERIA_MISSING"}

        denom = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            arrived = bool(r.get("arrived_at_criteria"))
            executed = bool(r.get("executed"))
            if not arrived or not executed:
                # schema-rejected upstream — not this defect
                continue
            cv = r.get("criteria_version")
            stale_marked = bool(r.get("stale"))
            excluded = bool(r.get("excluded_from_denominator"))
            # old criteria still callable (not unknown-version)
            callable_old = r.get("criteria_callable")
            if cv != batch_criteria and callable_old is False:
                # version retired → unknown version path, not silent settle
                continue
            if excluded:
                continue
            if cv != batch_criteria and not stale_marked:
                denom.append(r)
            elif cv == batch_criteria:
                denom.append(r)

        stale_unmarked = [
            r
            for r in denom
            if r.get("criteria_version") != batch_criteria and not r.get("stale")
        ]
        if stale_unmarked:
            return {
                "judge": "FAIL",
                "reason_code": "CRITERIA_LAG_UNAUTH",
                "detail": {
                    "batch_criteria_version": batch_criteria,
                    "stale_unmarked_count": len(stale_unmarked),
                    "denominator_size": len(denom),
                },
            }

        # freeze rejudge OK: stale rows excluded or marked; retired versions are other path
        for r in rows:
            if not isinstance(r, dict):
                continue
            if r.get("criteria_version") != batch_criteria and bool(r.get("arrived_at_criteria")):
                if r.get("criteria_callable") is False:
                    continue
                if bool(r.get("excluded_from_denominator")) or bool(r.get("stale")):
                    continue
                return {"judge": "FAIL", "reason_code": "CRITERIA_LAG_UNAUTH"}
        return {"judge": "PASS", "reason_code": "CRITERIA_VERSION_ALIGNED"}

    if kind == "arrival_assert":
        # Companion: arrival assertion must have a must-fail control sample
        samples = receipt.get("samples") or []
        has_must_fail = any(
            isinstance(s, dict) and s.get("expect") == "fail" and s.get("role") == "must_fail_control"
            for s in samples
        )
        has_must_pass = any(
            isinstance(s, dict) and s.get("expect") == "pass" and bool(s.get("arrived_at_criteria"))
            for s in samples
        )
        if not has_must_fail:
            return {"judge": "FAIL", "reason_code": "ARRIVAL_ASSERT_NO_MUST_FAIL"}
        if not has_must_pass:
            return {"judge": "FAIL", "reason_code": "ARRIVAL_ASSERT_NO_MUST_PASS"}
        # simulate: a row that never arrived must not be labeled arrived
        for s in samples:
            if not isinstance(s, dict):
                continue
            if s.get("role") == "must_fail_control" and s.get("arrived_at_criteria") is True:
                return {"judge": "FAIL", "reason_code": "ARRIVAL_ASSERT_FALSE_POSITIVE"}
        return {"judge": "PASS", "reason_code": "ARRIVAL_ASSERT_GATED"}

    return {"judge": "FAIL", "reason_code": "UNCLASSIFIED", "kind": kind}


H = "content-hash-identical-aabb"

FIXTURES = [
    {
        "case_id": "LAG-SILENT-SETTLE",
        "receipt": {
            "kind": "criteria_lag_batch",
            "batch_criteria_version": "v",
            "rows": [
                {
                    "row_id": "A",
                    "content_hash": H,
                    "criteria_version": "v",
                    "normalizer_version": "n",
                    "expected_outcome": "pass",
                    "executed": True,
                    "arrived_at_criteria": True,
                    "criteria_callable": True,
                    "stale": False,
                    "excluded_from_denominator": False,
                },
                {
                    "row_id": "B",
                    "content_hash": H,
                    "criteria_version": "v-1",
                    "normalizer_version": "n",
                    "expected_outcome": "pass",
                    "executed": True,
                    "arrived_at_criteria": True,
                    "criteria_callable": True,
                    "stale": False,
                    "excluded_from_denominator": False,
                },
            ],
        },
        "expect": "CRITERIA_LAG_UNAUTH",
    },
    {
        "case_id": "LAG-EXCLUDED-OK",
        "receipt": {
            "kind": "criteria_lag_batch",
            "batch_criteria_version": "v",
            "rows": [
                {
                    "row_id": "A",
                    "content_hash": H,
                    "criteria_version": "v",
                    "normalizer_version": "n",
                    "expected_outcome": "pass",
                    "executed": True,
                    "arrived_at_criteria": True,
                    "criteria_callable": True,
                    "stale": False,
                    "excluded_from_denominator": False,
                },
                {
                    "row_id": "B",
                    "content_hash": H,
                    "criteria_version": "v-1",
                    "normalizer_version": "n",
                    "expected_outcome": "pass",
                    "executed": True,
                    "arrived_at_criteria": True,
                    "criteria_callable": True,
                    "stale": False,
                    "excluded_from_denominator": True,
                },
            ],
        },
        "expect": "CRITERIA_VERSION_ALIGNED",
    },
    {
        "case_id": "LAG-STALE-MARKED-OK",
        "receipt": {
            "kind": "criteria_lag_batch",
            "batch_criteria_version": "v",
            "rows": [
                {
                    "row_id": "A",
                    "content_hash": H,
                    "criteria_version": "v",
                    "normalizer_version": "n",
                    "expected_outcome": "pass",
                    "executed": True,
                    "arrived_at_criteria": True,
                    "criteria_callable": True,
                    "stale": False,
                    "excluded_from_denominator": False,
                },
                {
                    "row_id": "B",
                    "content_hash": H,
                    "criteria_version": "v-1",
                    "normalizer_version": "n",
                    "expected_outcome": "pass",
                    "executed": True,
                    "arrived_at_criteria": True,
                    "criteria_callable": True,
                    "stale": True,
                    "excluded_from_denominator": False,
                },
            ],
        },
        "expect": "CRITERIA_VERSION_ALIGNED",
    },
    {
        "case_id": "LAG-RETIRED-VERSION-NOT-THIS-DEFECT",
        "receipt": {
            "kind": "criteria_lag_batch",
            "batch_criteria_version": "v",
            "rows": [
                {
                    "row_id": "A",
                    "content_hash": H,
                    "criteria_version": "v",
                    "normalizer_version": "n",
                    "expected_outcome": "pass",
                    "executed": True,
                    "arrived_at_criteria": True,
                    "criteria_callable": True,
                    "stale": False,
                    "excluded_from_denominator": False,
                },
                {
                    "row_id": "B",
                    "content_hash": H,
                    "criteria_version": "v-1",
                    "normalizer_version": "n",
                    "expected_outcome": "pass",
                    "executed": True,
                    "arrived_at_criteria": True,
                    "criteria_callable": False,  # unknown version path
                    "stale": False,
                    "excluded_from_denominator": False,
                },
            ],
        },
        "expect": "CRITERIA_VERSION_ALIGNED",
    },
    {
        "case_id": "ARRIVAL-NO-MUST-FAIL",
        "receipt": {
            "kind": "arrival_assert",
            "samples": [
                {"role": "pass_sample", "expect": "pass", "arrived_at_criteria": True},
            ],
        },
        "expect": "ARRIVAL_ASSERT_NO_MUST_FAIL",
    },
    {
        "case_id": "ARRIVAL-GATED-OK",
        "receipt": {
            "kind": "arrival_assert",
            "samples": [
                {"role": "pass_sample", "expect": "pass", "arrived_at_criteria": True},
                {
                    "role": "must_fail_control",
                    "expect": "fail",
                    "arrived_at_criteria": False,
                },
            ],
        },
        "expect": "ARRIVAL_ASSERT_GATED",
    },
    {
        "case_id": "ARRIVAL-FALSE-POSITIVE",
        "receipt": {
            "kind": "arrival_assert",
            "samples": [
                {"role": "pass_sample", "expect": "pass", "arrived_at_criteria": True},
                {
                    "role": "must_fail_control",
                    "expect": "fail",
                    "arrived_at_criteria": True,  # must-fail labeled arrived → gate itself broken
                },
            ],
        },
        "expect": "ARRIVAL_ASSERT_FALSE_POSITIVE",
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
    out = {"version": "CRITERIA_LAG_UNAUTH/v0.1", "all_match": ok, "n": len(rows), "rows": rows}
    print(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
