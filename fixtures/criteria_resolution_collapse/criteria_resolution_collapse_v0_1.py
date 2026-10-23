#!/usr/bin/env python3
"""CRITERIA_RESOLUTION_COLLAPSE v0.1

Structure-only fixture. Detects false "change ineffective" conclusions when
two arms share a constant verdict source (criteria lose resolution), and
rejects unsigned "incomparable" buckets that are not split into
semantic_equivalence vs resolution_insufficient with a positive-control read.

Structure source: 吴总 (EigenFlux). General fixture; no personal attribution in rows.
analyze_only. Stdlib only.
"""
from __future__ import annotations

import json
import sys
from typing import Any


ALLOWED_INCOMPARABLE = {"semantic_equivalence", "resolution_insufficient"}


def judge(receipt: dict[str, Any]) -> dict[str, Any]:
    kind = receipt.get("kind")

    if kind == "ab_compare":
        arms = receipt.get("arms") or []
        if not isinstance(arms, list) or len(arms) != 2:
            return {"judge": "FAIL", "reason_code": "ARMS_MISSING"}
        a, b = arms[0], arms[1]
        if not isinstance(a, dict) or not isinstance(b, dict):
            return {"judge": "FAIL", "reason_code": "ARMS_MISSING"}

        va = a.get("verdict_value")
        vb = b.get("verdict_value")
        sa = a.get("verdict_source_id")
        sb = b.get("verdict_source_id")
        report = receipt.get("report_conclusion")

        # Shared constant source + identical constant verdicts + "change ineffective"
        # is the planted negative control: resolution collapsed, not semantic equivalence.
        if (
            sa is not None
            and sa == sb
            and a.get("verdict_is_constant") is True
            and b.get("verdict_is_constant") is True
            and va == vb
            and report == "change_ineffective"
        ):
            return {
                "judge": "FAIL",
                "reason_code": "CRITERIA_RESOLUTION_COLLAPSE",
                "detail": {
                    "shared_source_id": sa,
                    "constant_verdict": va,
                },
            }

        # After sample swap arms become distinguishable under live criteria
        if receipt.get("after_sample_swap") is True and va != vb and sa != sb:
            return {"judge": "PASS", "reason_code": "RESOLUTION_RECOVERED"}

        # Distinct live sources with variance → OK to conclude effect/no-effect
        if (
            sa != sb
            and a.get("verdict_is_constant") is False
            and b.get("verdict_is_constant") is False
            and report in ("effect_detected", "no_effect_after_swap", "change_ineffective")
        ):
            return {"judge": "PASS", "reason_code": "RESOLUTION_PRESENT"}

        return {"judge": "PASS", "reason_code": "AB_COMPARE_OK"}

    if kind == "incomparable_claim":
        claim = receipt.get("claim_type")
        pos = receipt.get("positive_control")

        # Unsigned single bucket "incomparable" is not a signable conclusion type
        if claim == "incomparable":
            return {"judge": "FAIL", "reason_code": "INCOMPARABLE_NOT_SPLIT"}

        if claim not in ALLOWED_INCOMPARABLE:
            return {"judge": "FAIL", "reason_code": "INCOMPARABLE_UNKNOWN_TYPE"}

        # Every incomparable cell must attach a positive-control reading
        if not isinstance(pos, dict) or pos.get("reading") is None:
            return {"judge": "FAIL", "reason_code": "INCOMPARABLE_UNFALSIFIABLE"}

        # Opposite dispositions: semantic_eq expects pos shows same; resolution_insufficient
        # expects pos shows arms CAN differ under a resolving criterion.
        if claim == "semantic_equivalence":
            if pos.get("arms_distinguishable") is True:
                return {"judge": "FAIL", "reason_code": "SEMANTIC_EQ_POS_CONTRADICTS"}
            return {"judge": "PASS", "reason_code": "SEMANTIC_EQ_GATED"}

        if claim == "resolution_insufficient":
            if pos.get("arms_distinguishable") is not True:
                return {"judge": "FAIL", "reason_code": "RESOLUTION_CLAIM_NO_POS_DISTINGUISH"}
            return {"judge": "PASS", "reason_code": "RESOLUTION_INSUFFICIENT_GATED"}

        return {"judge": "FAIL", "reason_code": "UNCLASSIFIED"}

    return {"judge": "FAIL", "reason_code": "UNCLASSIFIED", "kind": kind}


FIXTURES = [
    {
        "case_id": "COLLAPSE-SHARED-CONSTANT",
        "receipt": {
            "kind": "ab_compare",
            "arms": [
                {
                    "arm_id": "A",
                    "verdict_value": "CONST_X",
                    "verdict_is_constant": True,
                    "verdict_source_id": "shared_const_src",
                },
                {
                    "arm_id": "B",
                    "verdict_value": "CONST_X",
                    "verdict_is_constant": True,
                    "verdict_source_id": "shared_const_src",
                },
            ],
            "report_conclusion": "change_ineffective",
        },
        "expect": "CRITERIA_RESOLUTION_COLLAPSE",
    },
    {
        "case_id": "LIVE-DISTINCT-SOURCES-OK",
        "receipt": {
            "kind": "ab_compare",
            "arms": [
                {
                    "arm_id": "A",
                    "verdict_value": "pass",
                    "verdict_is_constant": False,
                    "verdict_source_id": "crit_v2_a",
                },
                {
                    "arm_id": "B",
                    "verdict_value": "pass",
                    "verdict_is_constant": False,
                    "verdict_source_id": "crit_v2_b",
                },
            ],
            "report_conclusion": "change_ineffective",
        },
        "expect": "RESOLUTION_PRESENT",
    },
    {
        "case_id": "AFTER-SWAP-DISTINGUISHABLE",
        "receipt": {
            "kind": "ab_compare",
            "after_sample_swap": True,
            "arms": [
                {
                    "arm_id": "A",
                    "verdict_value": "pass",
                    "verdict_is_constant": False,
                    "verdict_source_id": "crit_live",
                },
                {
                    "arm_id": "B",
                    "verdict_value": "fail",
                    "verdict_is_constant": False,
                    "verdict_source_id": "crit_live_b",
                },
            ],
            "report_conclusion": "effect_detected",
        },
        "expect": "RESOLUTION_RECOVERED",
    },
    {
        "case_id": "INCOMPARABLE-UNSIGNED-BUCKET",
        "receipt": {
            "kind": "incomparable_claim",
            "claim_type": "incomparable",
            "positive_control": {"reading": 1.0, "arms_distinguishable": True},
        },
        "expect": "INCOMPARABLE_NOT_SPLIT",
    },
    {
        "case_id": "INCOMPARABLE-NO-POS-CONTROL",
        "receipt": {
            "kind": "incomparable_claim",
            "claim_type": "resolution_insufficient",
            "positive_control": None,
        },
        "expect": "INCOMPARABLE_UNFALSIFIABLE",
    },
    {
        "case_id": "RESOLUTION-INSUFFICIENT-GATED-OK",
        "receipt": {
            "kind": "incomparable_claim",
            "claim_type": "resolution_insufficient",
            "positive_control": {"reading": 0.92, "arms_distinguishable": True},
        },
        "expect": "RESOLUTION_INSUFFICIENT_GATED",
    },
    {
        "case_id": "SEMANTIC-EQ-GATED-OK",
        "receipt": {
            "kind": "incomparable_claim",
            "claim_type": "semantic_equivalence",
            "positive_control": {"reading": 0.91, "arms_distinguishable": False},
        },
        "expect": "SEMANTIC_EQ_GATED",
    },
    {
        "case_id": "SEMANTIC-EQ-POS-CONTRADICTS",
        "receipt": {
            "kind": "incomparable_claim",
            "claim_type": "semantic_equivalence",
            "positive_control": {"reading": 0.5, "arms_distinguishable": True},
        },
        "expect": "SEMANTIC_EQ_POS_CONTRADICTS",
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
        "version": "CRITERIA_RESOLUTION_COLLAPSE/v0.1",
        "all_match": ok,
        "n": len(rows),
        "rows": rows,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
