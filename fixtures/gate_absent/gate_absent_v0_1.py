#!/usr/bin/env python3
"""GATE_ABSENT v0.1

Structure-only fixture. Failure shapes from EigenFlux collab with 小鲸
(zero-error dashboard masks un-executed checks):

Arms:
  ① checklist_pass_without_exec — gate appears on checklist with
     error_count=0 but never appears in execution ledger →
     GATE_ABSENT_FALSE_PASS when reported PASS.
  ② skip_counted_as_pass — execution_state=skipped (or not_run) but
     dashboard folds it into pass_count → SKIP_AS_PASS.
  ③ pending_masked_green — execution_state=pending with zero errors
     reported as overall PASS → PENDING_MASKED_GREEN.
  ④ honest_three_state — executed/skipped/pending each carry distinct
     state labels; PASS only allowed when every checklist gate has an
     executed receipt with matching gate_id → HONEST_THREE_STATE.
  ⑤ exec_ledger_gate_id_required — executed receipt missing gate_id
     cannot authorize PASS (ghost execution) → EXEC_WITHOUT_GATE_ID.

Honest path: three-state log (executed|skipped|pending); PASS only when
all checklist gates are executed with receipts; skipped/pending never
inflate pass_count or zero-error green.

General fixture; analyze_only. Stdlib only.
Credit: 小鲸 (structure); prior owed signal 冷冰冰 / DeepSeek Harness / 木木;
Grok Bot (impl).
"""
from __future__ import annotations

import hashlib
import json
import sys
from typing import Any


def _norm(v: Any) -> str | None:
    if v is None or v == "":
        return None
    return str(v)


def judge(receipt: dict[str, Any]) -> dict[str, Any]:
    kind = receipt.get("kind")
    reported = receipt.get("reported_verdict")  # PASS|FAIL|SKIPPED|PENDING

    if kind == "checklist_pass_without_exec":
        checklist = receipt.get("checklist_gate_ids") or []
        executed = set(receipt.get("executed_gate_ids") or [])
        missing = [g for g in checklist if g not in executed]
        if missing and reported == "PASS":
            return {
                "judge": "FAIL",
                "reason_code": "GATE_ABSENT_FALSE_PASS",
                "detail": {"missing_gate_ids": missing, "error_count": receipt.get("error_count")},
            }
        if missing:
            return {
                "judge": "FAIL",
                "reason_code": "GATE_ABSENT",
                "detail": {"missing_gate_ids": missing},
            }
        if reported in ("PASS", "FAIL"):
            return {"judge": "PASS", "reason_code": "HONEST_ALL_EXECUTED"}
        return {"judge": "FAIL", "reason_code": "REPORTED_VERDICT_MISSING"}

    if kind == "skip_counted_as_pass":
        state = _norm(receipt.get("execution_state"))  # executed|skipped|pending|not_run
        pass_inflated = bool(receipt.get("skip_in_pass_count"))
        if state in ("skipped", "not_run") and (pass_inflated or reported == "PASS"):
            return {
                "judge": "FAIL",
                "reason_code": "SKIP_AS_PASS",
                "detail": {"execution_state": state, "skip_in_pass_count": pass_inflated},
            }
        if state == "skipped" and reported == "SKIPPED":
            return {"judge": "PASS", "reason_code": "HONEST_SKIPPED"}
        if state == "executed" and reported in ("PASS", "FAIL"):
            return {"judge": "PASS", "reason_code": "HONEST_EXECUTED"}
        return {
            "judge": "FAIL",
            "reason_code": "SKIP_STATE_INCONSISTENT",
            "detail": {"execution_state": state, "reported_verdict": reported},
        }

    if kind == "pending_masked_green":
        state = _norm(receipt.get("execution_state"))
        error_count = receipt.get("error_count")
        if state == "pending" and reported == "PASS":
            return {
                "judge": "FAIL",
                "reason_code": "PENDING_MASKED_GREEN",
                "detail": {"execution_state": state, "error_count": error_count},
            }
        if state == "pending" and reported == "PENDING":
            return {"judge": "PASS", "reason_code": "HONEST_PENDING"}
        if state == "executed" and reported in ("PASS", "FAIL"):
            return {"judge": "PASS", "reason_code": "HONEST_EXECUTED"}
        return {
            "judge": "FAIL",
            "reason_code": "PENDING_STATE_INCONSISTENT",
            "detail": {"execution_state": state, "reported_verdict": reported},
        }

    if kind == "honest_three_state":
        checklist = list(receipt.get("checklist_gate_ids") or [])
        ledger = receipt.get("exec_ledger") or []  # [{gate_id, state}]
        by_id = {}
        for row in ledger:
            gid = _norm((row or {}).get("gate_id"))
            st = _norm((row or {}).get("state"))
            if gid:
                by_id[gid] = st
        missing = [g for g in checklist if g not in by_id]
        if missing and reported == "PASS":
            return {
                "judge": "FAIL",
                "reason_code": "GATE_ABSENT_FALSE_PASS",
                "detail": {"missing_gate_ids": missing},
            }
        if missing:
            return {
                "judge": "FAIL",
                "reason_code": "GATE_ABSENT",
                "detail": {"missing_gate_ids": missing},
            }
        # PASS only if every gate is executed
        non_exec = {g: by_id[g] for g in checklist if by_id[g] != "executed"}
        if reported == "PASS" and non_exec:
            return {
                "judge": "FAIL",
                "reason_code": "NON_EXECUTED_IN_PASS",
                "detail": {"non_executed": non_exec},
            }
        # skipped/pending must not appear as PASS labels in ledger
        bad_labels = [
            g for g, st in by_id.items() if st not in ("executed", "skipped", "pending")
        ]
        if bad_labels:
            return {
                "judge": "FAIL",
                "reason_code": "INVALID_STATE_LABEL",
                "detail": {"gate_ids": bad_labels},
            }
        if reported in ("PASS", "FAIL", "SKIPPED", "PENDING"):
            return {"judge": "PASS", "reason_code": "HONEST_THREE_STATE"}
        return {"judge": "FAIL", "reason_code": "REPORTED_VERDICT_MISSING"}

    if kind == "exec_ledger_gate_id_required":
        has_gate_id = _norm(receipt.get("gate_id")) is not None
        if not has_gate_id and reported == "PASS":
            return {
                "judge": "FAIL",
                "reason_code": "EXEC_WITHOUT_GATE_ID_FALSE_PASS",
                "detail": {"gate_id": None},
            }
        if not has_gate_id:
            return {
                "judge": "FAIL",
                "reason_code": "EXEC_WITHOUT_GATE_ID",
                "detail": {"gate_id": None},
            }
        if reported in ("PASS", "FAIL"):
            return {"judge": "PASS", "reason_code": "HONEST_GATE_ID_BOUND"}
        return {"judge": "FAIL", "reason_code": "REPORTED_VERDICT_MISSING"}

    return {"judge": "FAIL", "reason_code": "UNKNOWN_KIND", "detail": {"kind": kind}}


CASES: list[dict[str, Any]] = [
    # --- ① checklist_pass_without_exec ---
    {
        "case_id": "ga-absent-false-pass",
        "kind": "checklist_pass_without_exec",
        "reported_verdict": "PASS",
        "checklist_gate_ids": ["g1", "g2", "g3"],
        "executed_gate_ids": ["g1", "g2"],
        "error_count": 0,
        "expect_judge": "FAIL",
        "expect_reason": "GATE_ABSENT_FALSE_PASS",
    },
    {
        "case_id": "ga-absent-honest-fail",
        "kind": "checklist_pass_without_exec",
        "reported_verdict": "FAIL",
        "checklist_gate_ids": ["g1", "g2", "g3"],
        "executed_gate_ids": ["g1"],
        "error_count": 0,
        "expect_judge": "FAIL",
        "expect_reason": "GATE_ABSENT",
    },
    {
        "case_id": "ga-all-executed-honest",
        "kind": "checklist_pass_without_exec",
        "reported_verdict": "PASS",
        "checklist_gate_ids": ["g1", "g2"],
        "executed_gate_ids": ["g1", "g2"],
        "error_count": 0,
        "expect_judge": "PASS",
        "expect_reason": "HONEST_ALL_EXECUTED",
    },
    # --- ② skip_counted_as_pass ---
    {
        "case_id": "ga-skip-as-pass",
        "kind": "skip_counted_as_pass",
        "reported_verdict": "PASS",
        "execution_state": "skipped",
        "skip_in_pass_count": True,
        "expect_judge": "FAIL",
        "expect_reason": "SKIP_AS_PASS",
    },
    {
        "case_id": "ga-not-run-as-pass",
        "kind": "skip_counted_as_pass",
        "reported_verdict": "PASS",
        "execution_state": "not_run",
        "skip_in_pass_count": False,
        "expect_judge": "FAIL",
        "expect_reason": "SKIP_AS_PASS",
    },
    {
        "case_id": "ga-skip-honest",
        "kind": "skip_counted_as_pass",
        "reported_verdict": "SKIPPED",
        "execution_state": "skipped",
        "skip_in_pass_count": False,
        "expect_judge": "PASS",
        "expect_reason": "HONEST_SKIPPED",
    },
    # --- ③ pending_masked_green ---
    {
        "case_id": "ga-pending-masked-green",
        "kind": "pending_masked_green",
        "reported_verdict": "PASS",
        "execution_state": "pending",
        "error_count": 0,
        "expect_judge": "FAIL",
        "expect_reason": "PENDING_MASKED_GREEN",
    },
    {
        "case_id": "ga-pending-honest",
        "kind": "pending_masked_green",
        "reported_verdict": "PENDING",
        "execution_state": "pending",
        "error_count": 0,
        "expect_judge": "PASS",
        "expect_reason": "HONEST_PENDING",
    },
    {
        "case_id": "ga-pending-executed-honest",
        "kind": "pending_masked_green",
        "reported_verdict": "PASS",
        "execution_state": "executed",
        "error_count": 0,
        "expect_judge": "PASS",
        "expect_reason": "HONEST_EXECUTED",
    },
    # --- ④ honest_three_state ---
    {
        "case_id": "ga-three-state-absent-false-pass",
        "kind": "honest_three_state",
        "reported_verdict": "PASS",
        "checklist_gate_ids": ["a", "b", "c"],
        "exec_ledger": [
            {"gate_id": "a", "state": "executed"},
            {"gate_id": "b", "state": "executed"},
        ],
        "expect_judge": "FAIL",
        "expect_reason": "GATE_ABSENT_FALSE_PASS",
    },
    {
        "case_id": "ga-three-state-skip-in-pass",
        "kind": "honest_three_state",
        "reported_verdict": "PASS",
        "checklist_gate_ids": ["a", "b"],
        "exec_ledger": [
            {"gate_id": "a", "state": "executed"},
            {"gate_id": "b", "state": "skipped"},
        ],
        "expect_judge": "FAIL",
        "expect_reason": "NON_EXECUTED_IN_PASS",
    },
    {
        "case_id": "ga-three-state-honest-all-exec",
        "kind": "honest_three_state",
        "reported_verdict": "PASS",
        "checklist_gate_ids": ["a", "b"],
        "exec_ledger": [
            {"gate_id": "a", "state": "executed"},
            {"gate_id": "b", "state": "executed"},
        ],
        "expect_judge": "PASS",
        "expect_reason": "HONEST_THREE_STATE",
    },
    {
        "case_id": "ga-three-state-honest-mixed-labels",
        "kind": "honest_three_state",
        "reported_verdict": "PENDING",
        "checklist_gate_ids": ["a", "b", "c"],
        "exec_ledger": [
            {"gate_id": "a", "state": "executed"},
            {"gate_id": "b", "state": "skipped"},
            {"gate_id": "c", "state": "pending"},
        ],
        "expect_judge": "PASS",
        "expect_reason": "HONEST_THREE_STATE",
    },
    # --- ⑤ exec_ledger_gate_id_required ---
    {
        "case_id": "ga-exec-no-gate-id-false-pass",
        "kind": "exec_ledger_gate_id_required",
        "reported_verdict": "PASS",
        "gate_id": None,
        "expect_judge": "FAIL",
        "expect_reason": "EXEC_WITHOUT_GATE_ID_FALSE_PASS",
    },
    {
        "case_id": "ga-exec-gate-id-honest",
        "kind": "exec_ledger_gate_id_required",
        "reported_verdict": "PASS",
        "gate_id": "g-42",
        "expect_judge": "PASS",
        "expect_reason": "HONEST_GATE_ID_BOUND",
    },
]


def run_all() -> dict[str, Any]:
    results = []
    passed = 0
    for case in CASES:
        got = judge(case)
        ok = got.get("judge") == case["expect_judge"] and got.get("reason_code") == case["expect_reason"]
        if ok:
            passed += 1
        results.append(
            {
                "case_id": case["case_id"],
                "ok": ok,
                "expect_judge": case["expect_judge"],
                "expect_reason": case["expect_reason"],
                "got": got,
            }
        )
    payload = {
        "fixture": "GATE_ABSENT",
        "version": "v0.1",
        "total": len(CASES),
        "passed": passed,
        "failed": len(CASES) - passed,
        "results": results,
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["sha256"] = hashlib.sha256(blob).hexdigest()
    return payload


def main() -> int:
    out = run_all()
    json.dump(out, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0 if out["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
