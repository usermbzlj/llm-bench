#!/usr/bin/env python3
"""INCONCLUSIVE_BUDGET_EXHAUSTED v0.1

Structure-only fixture. Failure shapes from wshsssssssagent (EigenFlux):
  1. BUDGET_AS_PERMANENT — retry budget exhausted; classifier asserts
     SERVICE_UNAVAILABLE_PERMANENT without external evidence
     (DNS NXDOMAIN / HTTP 410 / provider tombstone).
  2. BUDGET_IN_AVAIL_DENOM — budget-exhaust rows counted in availability
     denominator, pulling the rate down as if the service died.
  3. A_FAMILY_LOOSE — gate has operands but conditions are too loose
     (accepts empty external_evidence as "confirmed").
  4. B_FAMILY_NO_OPERAND — gate returns a verdict while a required
     operand is undefined/null (illegal return; must be structural reject).

Honest path: budget exhaust alone → INCONCLUSIVE_BUDGET_EXHAUSTED,
excluded from availability denom, and only escalate to PERMANENT when
external_evidence_kind ∈ {NXDOMAIN, HTTP_410, PROVIDER_TOMBSTONE}.

Structure source: wshsssssssagent EigenFlux broadcast on retry-budget
misclassification. General fixture; analyze_only. Stdlib only.
"""
from __future__ import annotations

import json
import sys
from typing import Any

PERMANENT_EVIDENCE = frozenset({"NXDOMAIN", "HTTP_410", "PROVIDER_TOMBSTONE"})


def judge(receipt: dict[str, Any]) -> dict[str, Any]:
    kind = receipt.get("kind")

    if kind == "budget_exhaust":
        budget_left = receipt.get("budget_left")
        observed = receipt.get("observed_class")
        # INCONCLUSIVE_BUDGET_EXHAUSTED | SERVICE_UNAVAILABLE_PERMANENT | RETRYING | OK
        evidence = receipt.get("external_evidence_kind")  # None|NXDOMAIN|HTTP_410|PROVIDER_TOMBSTONE|OTHER
        in_denom = receipt.get("counted_in_availability_denom")

        if not isinstance(budget_left, (int, float)):
            return {"judge": "FAIL", "reason_code": "BUDGET_FIELD_INVALID"}
        if budget_left > 0:
            if observed in ("RETRYING", "OK"):
                return {"judge": "PASS", "reason_code": "BUDGET_STILL_OPEN"}
            return {
                "judge": "FAIL",
                "reason_code": "BUDGET_OPEN_UNEXPECTED",
                "detail": {"observed": observed},
            }

        # budget exhausted
        has_perm = evidence in PERMANENT_EVIDENCE
        if has_perm:
            if observed == "SERVICE_UNAVAILABLE_PERMANENT" and in_denom is not True:
                return {"judge": "PASS", "reason_code": "PERMANENT_WITH_EVIDENCE"}
            if observed == "SERVICE_UNAVAILABLE_PERMANENT" and in_denom is True:
                return {"judge": "FAIL", "reason_code": "PERMANENT_IN_AVAIL_DENOM"}
            return {
                "judge": "FAIL",
                "reason_code": "PERMANENT_EVIDENCE_MISLABEL",
                "detail": {"observed": observed, "evidence": evidence},
            }

        # no permanent external evidence
        if observed == "SERVICE_UNAVAILABLE_PERMANENT":
            return {"judge": "FAIL", "reason_code": "BUDGET_AS_PERMANENT"}
        if observed == "INCONCLUSIVE_BUDGET_EXHAUSTED" and in_denom is True:
            return {"judge": "FAIL", "reason_code": "BUDGET_IN_AVAIL_DENOM"}
        if observed == "INCONCLUSIVE_BUDGET_EXHAUSTED" and in_denom is not True:
            return {"judge": "PASS", "reason_code": "HONEST_INCONCLUSIVE"}
        return {
            "judge": "FAIL",
            "reason_code": "BUDGET_EXHAUST_UNEXPECTED",
            "detail": {"observed": observed, "evidence": evidence, "in_denom": in_denom},
        }

    if kind == "gate_family":
        family = receipt.get("family")  # A_LOOSE | B_NO_OPERAND
        operands_defined = receipt.get("operands_defined")
        external_evidence = receipt.get("external_evidence")
        observed = receipt.get("observed_verdict")  # PASS|FAIL|REJECT|INCONCLUSIVE

        if family == "A_LOOSE":
            # operands exist but empty evidence accepted as confirmed PASS
            if operands_defined is True and (external_evidence in (None, "", {})):
                if observed == "PASS":
                    return {"judge": "FAIL", "reason_code": "A_FAMILY_LOOSE"}
                if observed in ("FAIL", "INCONCLUSIVE", "REJECT"):
                    return {"judge": "PASS", "reason_code": "A_LOOSE_CAUGHT"}
            if operands_defined is True and external_evidence not in (None, "", {}):
                if observed == "PASS":
                    return {"judge": "PASS", "reason_code": "A_EVIDENCE_OK"}
            return {
                "judge": "FAIL",
                "reason_code": "A_FAMILY_UNEXPECTED",
                "detail": {"observed": observed, "evidence": external_evidence},
            }

        if family == "B_NO_OPERAND":
            if operands_defined is not True:
                if observed in ("PASS", "FAIL", "INCONCLUSIVE"):
                    return {"judge": "FAIL", "reason_code": "B_FAMILY_NO_OPERAND"}
                if observed == "REJECT":
                    return {"judge": "PASS", "reason_code": "B_STRUCTURAL_REJECT"}
            if operands_defined is True and observed in ("PASS", "FAIL", "INCONCLUSIVE"):
                return {"judge": "PASS", "reason_code": "B_OPERANDS_OK"}
            return {
                "judge": "FAIL",
                "reason_code": "B_FAMILY_UNEXPECTED",
                "detail": {"observed": observed, "operands_defined": operands_defined},
            }

        return {"judge": "FAIL", "reason_code": "FAMILY_UNKNOWN", "family": family}

    if kind == "flip_test":
        before = receipt.get("before_class")
        after = receipt.get("after_class")
        injected = receipt.get("injected")
        if before is None or after is None:
            return {"judge": "FAIL", "reason_code": "FLIP_PAIR_MISSING"}
        if injected != "external_evidence_NXDOMAIN":
            return {"judge": "FAIL", "reason_code": "INJECT_WRONG"}
        if before == after:
            return {"judge": "FAIL", "reason_code": "FLIP_NOT_WIRED"}
        if before == "INCONCLUSIVE_BUDGET_EXHAUSTED" and after == "SERVICE_UNAVAILABLE_PERMANENT":
            return {"judge": "PASS", "reason_code": "FLIP_OK"}
        return {
            "judge": "FAIL",
            "reason_code": "FLIP_UNEXPECTED",
            "detail": {"before": before, "after": after},
        }

    return {"judge": "FAIL", "reason_code": "UNCLASSIFIED", "kind": kind}


FIXTURES = [
    {
        "case_id": "BUDGET-AS-PERMANENT",
        "receipt": {
            "kind": "budget_exhaust",
            "budget_left": 0,
            "external_evidence_kind": None,
            "counted_in_availability_denom": False,
            "observed_class": "SERVICE_UNAVAILABLE_PERMANENT",
            "note": "预算耗尽无外部证据却断言永久不可用",
        },
        "expect": "BUDGET_AS_PERMANENT",
    },
    {
        "case_id": "BUDGET-IN-AVAIL-DENOM",
        "receipt": {
            "kind": "budget_exhaust",
            "budget_left": 0,
            "external_evidence_kind": None,
            "counted_in_availability_denom": True,
            "observed_class": "INCONCLUSIVE_BUDGET_EXHAUSTED",
        },
        "expect": "BUDGET_IN_AVAIL_DENOM",
    },
    {
        "case_id": "HONEST-INCONCLUSIVE",
        "receipt": {
            "kind": "budget_exhaust",
            "budget_left": 0,
            "external_evidence_kind": None,
            "counted_in_availability_denom": False,
            "observed_class": "INCONCLUSIVE_BUDGET_EXHAUSTED",
        },
        "expect": "HONEST_INCONCLUSIVE",
    },
    {
        "case_id": "PERMANENT-WITH-NXDOMAIN",
        "receipt": {
            "kind": "budget_exhaust",
            "budget_left": 0,
            "external_evidence_kind": "NXDOMAIN",
            "counted_in_availability_denom": False,
            "observed_class": "SERVICE_UNAVAILABLE_PERMANENT",
        },
        "expect": "PERMANENT_WITH_EVIDENCE",
    },
    {
        "case_id": "PERMANENT-WITH-HTTP-410",
        "receipt": {
            "kind": "budget_exhaust",
            "budget_left": 0,
            "external_evidence_kind": "HTTP_410",
            "counted_in_availability_denom": False,
            "observed_class": "SERVICE_UNAVAILABLE_PERMANENT",
        },
        "expect": "PERMANENT_WITH_EVIDENCE",
    },
    {
        "case_id": "BUDGET-STILL-OPEN",
        "receipt": {
            "kind": "budget_exhaust",
            "budget_left": 2,
            "external_evidence_kind": None,
            "counted_in_availability_denom": False,
            "observed_class": "RETRYING",
        },
        "expect": "BUDGET_STILL_OPEN",
    },
    {
        "case_id": "A-FAMILY-LOOSE",
        "receipt": {
            "kind": "gate_family",
            "family": "A_LOOSE",
            "operands_defined": True,
            "external_evidence": None,
            "observed_verdict": "PASS",
        },
        "expect": "A_FAMILY_LOOSE",
    },
    {
        "case_id": "A-LOOSE-CAUGHT",
        "receipt": {
            "kind": "gate_family",
            "family": "A_LOOSE",
            "operands_defined": True,
            "external_evidence": None,
            "observed_verdict": "INCONCLUSIVE",
        },
        "expect": "A_LOOSE_CAUGHT",
    },
    {
        "case_id": "B-FAMILY-NO-OPERAND",
        "receipt": {
            "kind": "gate_family",
            "family": "B_NO_OPERAND",
            "operands_defined": False,
            "external_evidence": None,
            "observed_verdict": "PASS",
        },
        "expect": "B_FAMILY_NO_OPERAND",
    },
    {
        "case_id": "B-STRUCTURAL-REJECT",
        "receipt": {
            "kind": "gate_family",
            "family": "B_NO_OPERAND",
            "operands_defined": False,
            "external_evidence": None,
            "observed_verdict": "REJECT",
        },
        "expect": "B_STRUCTURAL_REJECT",
    },
    {
        "case_id": "FLIP-INJECT-NXDOMAIN",
        "receipt": {
            "kind": "flip_test",
            "before_class": "INCONCLUSIVE_BUDGET_EXHAUSTED",
            "after_class": "SERVICE_UNAVAILABLE_PERMANENT",
            "injected": "external_evidence_NXDOMAIN",
        },
        "expect": "FLIP_OK",
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
        "fixture": "INCONCLUSIVE_BUDGET_EXHAUSTED",
        "version": "0.1",
        "total": len(FIXTURES),
        "passed": ok,
        "rows": rows,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if ok == len(FIXTURES) else 1


if __name__ == "__main__":
    sys.exit(main())
