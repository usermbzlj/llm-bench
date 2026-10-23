#!/usr/bin/env python3
"""WIDTH_SQRTN_ATTRIBUTION v0.1

Structure-only fixture. Failure shapes from wshsssssssagent (EigenFlux):
  Measured Wilson/normal CI width for Bernoulli p (percent points):
    n-sweep @ p=0.5:
      n=10  → width 52.7%  width×√n ≈ 166.6
      n=50  → width 26.7%  width×√n ≈ 188.9
      n=200 → width 13.7%  width×√n ≈ 194.1
    p-sweep @ n=50:
      p=0.50 → 26.7%
      p=0.90 → 17.0%
      p=0.98 → 10.1%

False green family: attributing a narrower interval to "more samples"
when (a) p also moved, or (b) width×√n did not stay roughly stable
across an n-sweep at fixed p, or (c) the report mixes n-sweep and
p-sweep rows without a group tag so the confound is invisible.

Honest path: label group ∈ {n_sweep, p_sweep}; for n_sweep hold p
fixed and require width×√n within a relative band; never claim
"sample-size alone" when group is p_sweep or when p differs across
compared rows.

Structure source: wshsssssssagent EigenFlux PM with measured table +
JSONL shape {p, n, width, width_sqrt_n, group}. General fixture;
analyze_only. Stdlib only.
"""
from __future__ import annotations

import json
import math
import sys
from typing import Any


def _f(x: Any) -> float | None:
    if isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return float(x)
    return None


def judge(receipt: dict[str, Any]) -> dict[str, Any]:
    kind = receipt.get("kind")

    if kind == "attribution_claim":
        # Compare two rows + a claimed cause.
        a = receipt.get("row_a") or {}
        b = receipt.get("row_b") or {}
        claim = receipt.get("claimed_cause")
        # claimed_cause ∈ {
        #   SAMPLE_SIZE_ALONE, P_CHANGED, MIXED_UNLABELED, HONEST_N_SCALING
        # }
        group_a = a.get("group")
        group_b = b.get("group")
        p_a, p_b = _f(a.get("p")), _f(b.get("p"))
        n_a, n_b = _f(a.get("n")), _f(b.get("n"))
        w_a, w_b = _f(a.get("width")), _f(b.get("width"))
        ws_a, ws_b = _f(a.get("width_sqrt_n")), _f(b.get("width_sqrt_n"))

        if None in (p_a, p_b, n_a, n_b, w_a, w_b):
            return {"judge": "FAIL", "reason_code": "ROW_FIELDS_MISSING"}

        # Recompute width×√n if omitted
        if ws_a is None:
            ws_a = w_a * math.sqrt(n_a)
        if ws_b is None:
            ws_b = w_b * math.sqrt(n_b)

        unlabeled = group_a in (None, "") or group_b in (None, "")
        p_differs = abs(p_a - p_b) > 1e-9
        n_differs = abs(n_a - n_b) > 1e-9
        both_n_sweep = group_a == "n_sweep" and group_b == "n_sweep"
        both_p_sweep = group_a == "p_sweep" and group_b == "p_sweep"

        if claim == "SAMPLE_SIZE_ALONE":
            # False if p moved, or groups are p_sweep, or unlabeled mix
            if unlabeled:
                return {"judge": "FAIL", "reason_code": "MISSING_GROUP"}
            if both_p_sweep or p_differs:
                return {"judge": "FAIL", "reason_code": "P_CONFOUND"}
            if both_n_sweep and (not p_differs) and n_differs:
                # Check width×√n stability (relative band 25%)
                mid = 0.5 * (ws_a + ws_b)
                if mid <= 0:
                    return {"judge": "FAIL", "reason_code": "WIDTH_SQRTN_INVALID"}
                rel = abs(ws_a - ws_b) / mid
                if rel > 0.25:
                    return {"judge": "FAIL", "reason_code": "WIDTH_SQRTN_UNSTABLE"}
                return {"judge": "PASS", "reason_code": "HONEST_N_SCALING"}
            return {
                "judge": "FAIL",
                "reason_code": "SAMPLE_SIZE_CLAIM_UNEXPECTED",
                "detail": {"group_a": group_a, "group_b": group_b},
            }

        if claim == "P_CHANGED":
            if unlabeled:
                return {"judge": "FAIL", "reason_code": "MISSING_GROUP"}
            if both_p_sweep and p_differs and (not n_differs):
                return {"judge": "PASS", "reason_code": "HONEST_P_ATTRIBUTION"}
            if p_differs and n_differs:
                # mixed confound acknowledged
                return {"judge": "PASS", "reason_code": "HONEST_MIXED_ACK"}
            if not p_differs:
                return {"judge": "FAIL", "reason_code": "P_CLAIM_WITHOUT_P_DIFF"}
            return {
                "judge": "FAIL",
                "reason_code": "P_CLAIM_UNEXPECTED",
                "detail": {"group_a": group_a, "group_b": group_b},
            }

        if claim == "MIXED_UNLABELED":
            # Reporter left groups blank while comparing across axes
            if unlabeled and p_differs and n_differs:
                return {"judge": "FAIL", "reason_code": "MISSING_GROUP"}
            if unlabeled:
                return {"judge": "FAIL", "reason_code": "MISSING_GROUP"}
            return {"judge": "PASS", "reason_code": "GROUPS_PRESENT"}

        if claim == "HONEST_N_SCALING":
            if not both_n_sweep or p_differs or not n_differs:
                return {"judge": "FAIL", "reason_code": "HONEST_N_PRECONDITION"}
            mid = 0.5 * (ws_a + ws_b)
            if mid <= 0:
                return {"judge": "FAIL", "reason_code": "WIDTH_SQRTN_INVALID"}
            rel = abs(ws_a - ws_b) / mid
            if rel > 0.25:
                return {"judge": "FAIL", "reason_code": "WIDTH_SQRTN_UNSTABLE"}
            return {"judge": "PASS", "reason_code": "HONEST_N_SCALING"}

        return {"judge": "FAIL", "reason_code": "CLAIM_UNKNOWN", "claim": claim}

    if kind == "jsonl_row":
        # Single-row schema gate for the exchange format wsh proposed.
        p, n, w = _f(receipt.get("p")), _f(receipt.get("n")), _f(receipt.get("width"))
        ws = _f(receipt.get("width_sqrt_n"))
        group = receipt.get("group")
        if None in (p, n, w):
            return {"judge": "FAIL", "reason_code": "ROW_FIELDS_MISSING"}
        if group not in ("n_sweep", "p_sweep"):
            return {"judge": "FAIL", "reason_code": "MISSING_GROUP"}
        if not (0.0 < p < 1.0) or n <= 0 or w < 0:
            return {"judge": "FAIL", "reason_code": "ROW_VALUE_INVALID"}
        expected_ws = w * math.sqrt(n)
        if ws is None:
            return {"judge": "FAIL", "reason_code": "WIDTH_SQRTN_MISSING"}
        if abs(ws - expected_ws) > max(0.5, 0.02 * expected_ws):
            return {
                "judge": "FAIL",
                "reason_code": "WIDTH_SQRTN_MISMATCH",
                "detail": {"expected": expected_ws, "got": ws},
            }
        return {"judge": "PASS", "reason_code": "JSONL_ROW_OK"}

    if kind == "false_green_narrative":
        # Narrative that cites only n while table shows p moved.
        narrative = receipt.get("narrative_cause")
        table_p_unique = receipt.get("table_distinct_p_count")
        table_n_unique = receipt.get("table_distinct_n_count")
        if not isinstance(table_p_unique, int) or not isinstance(table_n_unique, int):
            return {"judge": "FAIL", "reason_code": "TABLE_META_MISSING"}
        if narrative == "MORE_SAMPLES":
            if table_p_unique > 1:
                return {"judge": "FAIL", "reason_code": "P_CONFOUND"}
            if table_n_unique > 1 and table_p_unique == 1:
                return {"judge": "PASS", "reason_code": "N_ONLY_TABLE_OK"}
            return {"judge": "FAIL", "reason_code": "NARRATIVE_UNEXPECTED"}
        if narrative == "P_AND_N_SEPARATED":
            if table_p_unique >= 1 and table_n_unique >= 1:
                return {"judge": "PASS", "reason_code": "GROUPS_SEPARATED"}
            return {"judge": "FAIL", "reason_code": "SEPARATION_INCOMPLETE"}
        return {"judge": "FAIL", "reason_code": "NARRATIVE_UNKNOWN"}

    return {"judge": "FAIL", "reason_code": "UNCLASSIFIED", "kind": kind}


# Reference rows from wshsssssssagent measured table (percent width).
WSH_N10 = {"p": 0.5, "n": 10, "width": 52.7, "width_sqrt_n": 166.6, "group": "n_sweep"}
WSH_N50 = {"p": 0.5, "n": 50, "width": 26.7, "width_sqrt_n": 188.9, "group": "n_sweep"}
WSH_N200 = {"p": 0.5, "n": 200, "width": 13.7, "width_sqrt_n": 194.1, "group": "n_sweep"}
WSH_P50 = {"p": 0.5, "n": 50, "width": 26.7, "width_sqrt_n": 188.9, "group": "p_sweep"}
WSH_P90 = {"p": 0.9, "n": 50, "width": 17.0, "width_sqrt_n": 120.2, "group": "p_sweep"}
WSH_P98 = {"p": 0.98, "n": 50, "width": 10.1, "width_sqrt_n": 71.4, "group": "p_sweep"}


FIXTURES = [
    {
        "case_id": "FALSE-SAMPLE-SIZE-WHEN-P-MOVED",
        "receipt": {
            "kind": "attribution_claim",
            "row_a": {**WSH_N10, "group": "p_sweep"},
            "row_b": WSH_P98,
            "claimed_cause": "SAMPLE_SIZE_ALONE",
            "note": "n 与 p 同时变，却声称只因样本变多",
        },
        "expect": "P_CONFOUND",
    },
    {
        "case_id": "FALSE-SAMPLE-SIZE-UNLABELED",
        "receipt": {
            "kind": "attribution_claim",
            "row_a": {"p": 0.5, "n": 10, "width": 52.7, "width_sqrt_n": 166.6, "group": None},
            "row_b": {"p": 0.98, "n": 50, "width": 10.1, "width_sqrt_n": 71.4, "group": None},
            "claimed_cause": "SAMPLE_SIZE_ALONE",
        },
        "expect": "MISSING_GROUP",
    },
    {
        "case_id": "HONEST-N-SWEEP-10-vs-200",
        "receipt": {
            "kind": "attribution_claim",
            "row_a": WSH_N10,
            "row_b": WSH_N200,
            "claimed_cause": "HONEST_N_SCALING",
        },
        "expect": "HONEST_N_SCALING",
    },
    {
        "case_id": "HONEST-P-SWEEP-ATTRIBUTION",
        "receipt": {
            "kind": "attribution_claim",
            "row_a": WSH_P50,
            "row_b": WSH_P98,
            "claimed_cause": "P_CHANGED",
        },
        "expect": "HONEST_P_ATTRIBUTION",
    },
    {
        "case_id": "MIXED-UNLABELED-CAUGHT",
        "receipt": {
            "kind": "attribution_claim",
            "row_a": {"p": 0.5, "n": 10, "width": 52.7, "group": ""},
            "row_b": {"p": 0.98, "n": 200, "width": 5.0, "group": ""},
            "claimed_cause": "MIXED_UNLABELED",
        },
        "expect": "MISSING_GROUP",
    },
    {
        "case_id": "JSONL-ROW-OK-N50",
        "receipt": {"kind": "jsonl_row", **WSH_N50},
        "expect": "JSONL_ROW_OK",
    },
    {
        "case_id": "JSONL-ROW-MISSING-GROUP",
        "receipt": {
            "kind": "jsonl_row",
            "p": 0.5,
            "n": 50,
            "width": 26.7,
            "width_sqrt_n": 188.9,
            "group": None,
        },
        "expect": "MISSING_GROUP",
    },
    {
        "case_id": "JSONL-ROW-SQRTN-MISMATCH",
        "receipt": {
            "kind": "jsonl_row",
            "p": 0.5,
            "n": 50,
            "width": 26.7,
            "width_sqrt_n": 10.0,
            "group": "n_sweep",
        },
        "expect": "WIDTH_SQRTN_MISMATCH",
    },
    {
        "case_id": "NARRATIVE-MORE-SAMPLES-BUT-P-MOVED",
        "receipt": {
            "kind": "false_green_narrative",
            "narrative_cause": "MORE_SAMPLES",
            "table_distinct_p_count": 3,
            "table_distinct_n_count": 1,
            "note": "单给 p-sweep 却写「区间窄=样本多」",
        },
        "expect": "P_CONFOUND",
    },
    {
        "case_id": "NARRATIVE-GROUPS-SEPARATED",
        "receipt": {
            "kind": "false_green_narrative",
            "narrative_cause": "P_AND_N_SEPARATED",
            "table_distinct_p_count": 3,
            "table_distinct_n_count": 3,
        },
        "expect": "GROUPS_SEPARATED",
    },
    {
        "case_id": "SAMPLE-SIZE-CLAIM-ON-HONEST-N",
        "receipt": {
            "kind": "attribution_claim",
            "row_a": WSH_N50,
            "row_b": WSH_N200,
            "claimed_cause": "SAMPLE_SIZE_ALONE",
        },
        "expect": "HONEST_N_SCALING",
    },
]


def main() -> int:
    rows = []
    ok = 0
    for fx in FIXTURES:
        got = judge(fx["receipt"])
        reason = got.get("reason_code")
        passed = reason == fx["expect"]
        if passed:
            ok += 1
        rows.append(
            {
                "case_id": fx["case_id"],
                "expect": fx["expect"],
                "got": reason,
                "judge": got.get("judge"),
                "pass": passed,
                "detail": got.get("detail"),
            }
        )
    out = {
        "fixture": "WIDTH_SQRTN_ATTRIBUTION",
        "version": "0.1",
        "credit": "wshsssssssagent",
        "total": len(FIXTURES),
        "passed": ok,
        "rows": rows,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if ok == len(FIXTURES) else 1


if __name__ == "__main__":
    sys.exit(main())
