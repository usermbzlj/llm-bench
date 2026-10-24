#!/usr/bin/env python3
"""LEDGER_SILENT_GAPS v0.2

Extends v0.1 with empty-payload negative controls and execution_receipt gates.

Credit (structure / observations):
  - 李晨熙 — LEDGER blind-run: T5 explicit semantic_complete;
    M1–M7 empty-payload neg-ctrl; registry denom + measurement_stopped
    (prior cycle notes 2026-10-24 ~06:32 CST; hollow_pass cluster)
  - 贺水仙 — empty-batch-incomplete: empty batch must not silent-complete
  - 东湖小C — execution_receipt as first-class attestation
  - Tree — exec_receipt.request_id must be written by the executed step
    (scheduler-authored loses queue time); artifact_complete needs
    declared vs actual for TRUNCATED; cross_round_reconcile key must
    carry generation_rule_version (THIS cycle PM)

Arms added in v0.2:
  T5  semantic_complete_explicit — parseable alone must NOT imply
      semantic_complete; missing/False + reported PASS → hollow pass
  M1  empty_rows_pass — rows=[] + reported PASS
  M2  empty_batch_incomplete — batch empty + batch_complete=True
  M3  null_payload_rate — payload null/absent + coverage_rate emitted
  M4  empty_events_paired — events=[] yet pair_ok reported PASS
  M5  registry_denom_zero — denom=0, measurement_stopped=False, rate>0
  M6  empty_receipt_exit0 — no execution_receipt, exit_code=0, PASS
  M7  empty_keys_green — unique_keys=0 with expected_rows>0 + PASS
  ER1 request_id_writer — writer must be executed_step, not scheduler
  ER2 artifact_trunc_dual — TRUNCATED needs declared_bytes + actual_bytes
  ER3 cross_round_rule_ver — reconcile key must include generation_rule_version

analyze_only. Stdlib only.
"""
from __future__ import annotations

import hashlib
import json
import sys
from typing import Any


def judge(receipt: dict[str, Any]) -> dict[str, Any]:
    kind = receipt.get("kind")
    reported = receipt.get("reported_verdict")  # PASS|FAIL|INCONCLUSIVE|None

    # --- T5: explicit semantic_complete ---
    if kind == "semantic_complete_explicit":
        parseable = bool(receipt.get("parseable"))
        sc = receipt.get("semantic_complete")
        sc_declared = receipt.get("semantic_complete_declared")
        if parseable and sc is None and reported == "PASS":
            return {
                "judge": "FAIL",
                "reason_code": "T5_SEMANTIC_COMPLETE_MISSING_HOLLOW_PASS",
                "detail": {"parseable": parseable, "semantic_complete": sc},
            }
        if parseable and sc is False and sc_declared is not True and reported == "PASS":
            return {
                "judge": "FAIL",
                "reason_code": "T5_PARSEABLE_IMPLIED_COMPLETE_FALSE_PASS",
            }
        if parseable and sc is True and sc_declared is True:
            if reported in ("PASS", "FAIL"):
                return {"judge": "PASS", "reason_code": "T5_SEMANTIC_COMPLETE_EXPLICIT"}
            return {"judge": "FAIL", "reason_code": "REPORTED_VERDICT_MISSING"}
        if parseable and sc is False and sc_declared is True:
            return {"judge": "PASS", "reason_code": "T5_INCOMPLETE_DECLARED"}
        return {"judge": "FAIL", "reason_code": "T5_UNCLASSIFIED"}

    # --- M1: empty rows + PASS ---
    if kind == "empty_rows_pass":
        rows = receipt.get("rows")
        if rows == [] and reported == "PASS":
            return {"judge": "FAIL", "reason_code": "M1_EMPTY_ROWS_FALSE_PASS"}
        if rows == [] and reported in ("FAIL", "INCONCLUSIVE"):
            return {"judge": "PASS", "reason_code": "M1_EMPTY_ROWS_DECLARED"}
        if isinstance(rows, list) and len(rows) > 0 and reported in ("PASS", "FAIL"):
            return {"judge": "PASS", "reason_code": "M1_ROWS_PRESENT"}
        return {"judge": "FAIL", "reason_code": "M1_UNCLASSIFIED"}

    # --- M2: empty-batch-incomplete (贺水仙) ---
    if kind == "empty_batch_incomplete":
        batch = receipt.get("batch")
        complete = bool(receipt.get("batch_complete", False))
        empty = batch in ([], None, {}, "")
        if empty and complete and reported == "PASS":
            return {"judge": "FAIL", "reason_code": "M2_EMPTY_BATCH_COMPLETE_FALSE_PASS"}
        if empty and complete:
            return {"judge": "FAIL", "reason_code": "M2_EMPTY_BATCH_INCOMPLETE"}
        if empty and not complete and reported in ("FAIL", "INCONCLUSIVE"):
            return {"judge": "PASS", "reason_code": "M2_EMPTY_BATCH_NOT_COMPLETE"}
        if not empty and complete and reported in ("PASS", "FAIL"):
            return {"judge": "PASS", "reason_code": "M2_BATCH_OK"}
        return {"judge": "FAIL", "reason_code": "M2_UNCLASSIFIED"}

    # --- M3: null payload emitting a rate ---
    if kind == "null_payload_rate":
        payload = receipt.get("payload")
        rate = receipt.get("coverage_rate")
        nullish = payload is None or payload == {} or payload == []
        if nullish and rate is not None and reported == "PASS":
            return {
                "judge": "FAIL",
                "reason_code": "M3_NULL_PAYLOAD_RATE_FALSE_PASS",
                "detail": {"coverage_rate": rate},
            }
        if nullish and rate is not None:
            return {"judge": "FAIL", "reason_code": "M3_NULL_PAYLOAD_RATE"}
        if nullish and rate is None and reported in ("FAIL", "INCONCLUSIVE"):
            return {"judge": "PASS", "reason_code": "M3_NULL_PAYLOAD_NO_RATE"}
        if not nullish and isinstance(rate, (int, float)):
            return {"judge": "PASS", "reason_code": "M3_PAYLOAD_RATE_OK"}
        return {"judge": "FAIL", "reason_code": "M3_UNCLASSIFIED"}

    # --- M4: empty events yet pair reported OK ---
    if kind == "empty_events_paired":
        events = receipt.get("events")
        pair_ok = bool(receipt.get("pair_ok", False))
        if events == [] and pair_ok and reported == "PASS":
            return {"judge": "FAIL", "reason_code": "M4_EMPTY_EVENTS_PAIR_FALSE_PASS"}
        if events == [] and pair_ok:
            return {"judge": "FAIL", "reason_code": "M4_EMPTY_EVENTS_PAIR"}
        if events == [] and not pair_ok and reported in ("FAIL", "INCONCLUSIVE"):
            return {"judge": "PASS", "reason_code": "M4_EMPTY_EVENTS_UNPAIRED"}
        if isinstance(events, list) and len(events) > 0 and pair_ok:
            return {"judge": "PASS", "reason_code": "M4_EVENTS_PAIRED_OK"}
        return {"judge": "FAIL", "reason_code": "M4_UNCLASSIFIED"}

    # --- M5: registry denom=0, measurement not stopped, fake rate ---
    if kind == "registry_denom_zero":
        denom = receipt.get("registry_denominator")
        stopped = bool(receipt.get("measurement_stopped", False))
        rate = receipt.get("coverage_rate")
        if denom == 0 and not stopped and rate is not None and float(rate) > 0 and reported == "PASS":
            return {
                "judge": "FAIL",
                "reason_code": "M5_DENOM_ZERO_RATE_FALSE_PASS",
                "detail": {"registry_denominator": denom, "coverage_rate": rate},
            }
        if denom == 0 and not stopped and rate is not None and float(rate) > 0:
            return {"judge": "FAIL", "reason_code": "M5_DENOM_ZERO_RATE"}
        if denom == 0 and stopped and rate is None:
            return {"judge": "PASS", "reason_code": "M5_DENOM_ZERO_STOPPED"}
        if isinstance(denom, int) and denom > 0 and isinstance(rate, (int, float)):
            return {"judge": "PASS", "reason_code": "M5_DENOM_OK"}
        return {"judge": "FAIL", "reason_code": "M5_UNCLASSIFIED"}

    # --- M6: empty execution_receipt + exit 0 PASS ---
    if kind == "empty_receipt_exit0":
        er = receipt.get("execution_receipt")
        exit_code = receipt.get("exit_code")
        empty_er = er in (None, {}, [])
        if empty_er and exit_code == 0 and reported == "PASS":
            return {"judge": "FAIL", "reason_code": "M6_EMPTY_RECEIPT_EXIT0_FALSE_PASS"}
        if empty_er and exit_code == 0 and reported in ("FAIL", "INCONCLUSIVE"):
            return {"judge": "PASS", "reason_code": "M6_EMPTY_RECEIPT_DECLARED"}
        if isinstance(er, dict) and er.get("request_id") and exit_code == 0:
            return {"judge": "PASS", "reason_code": "M6_RECEIPT_PRESENT"}
        return {"judge": "FAIL", "reason_code": "M6_UNCLASSIFIED"}

    # --- M7: unique_keys=0 with expected_rows>0 + PASS ---
    if kind == "empty_keys_green":
        uniq = receipt.get("unique_keys")
        expected = receipt.get("expected_rows")
        if uniq == 0 and isinstance(expected, int) and expected > 0 and reported == "PASS":
            return {
                "judge": "FAIL",
                "reason_code": "M7_EMPTY_KEYS_FALSE_PASS",
                "detail": {"unique_keys": uniq, "expected_rows": expected},
            }
        if uniq == 0 and isinstance(expected, int) and expected > 0:
            return {"judge": "FAIL", "reason_code": "M7_EMPTY_KEYS"}
        if isinstance(uniq, int) and uniq > 0 and isinstance(expected, int) and expected > 0:
            return {"judge": "PASS", "reason_code": "M7_KEYS_OK"}
        return {"judge": "FAIL", "reason_code": "M7_UNCLASSIFIED"}

    # --- ER1: request_id writer (Tree / 东湖小C) ---
    if kind == "request_id_writer":
        writer = receipt.get("request_id_writer")  # executed_step | scheduler
        rid = receipt.get("request_id")
        if not rid:
            return {"judge": "FAIL", "reason_code": "ER1_REQUEST_ID_MISSING"}
        if writer == "scheduler" and reported == "PASS":
            return {"judge": "FAIL", "reason_code": "ER1_SCHEDULER_WRITTEN_FALSE_PASS"}
        if writer == "scheduler":
            return {"judge": "FAIL", "reason_code": "ER1_SCHEDULER_WRITTEN"}
        if writer == "executed_step":
            return {"judge": "PASS", "reason_code": "ER1_EXECUTED_STEP_OK"}
        return {"judge": "FAIL", "reason_code": "ER1_WRITER_MISSING"}

    # --- ER2: artifact_complete TRUNCATED dual fields ---
    if kind == "artifact_trunc_dual":
        status = receipt.get("artifact_status")  # COMPLETE|TRUNCATED|ABSENT
        declared = receipt.get("declared_bytes")
        actual = receipt.get("actual_bytes")
        if status == "TRUNCATED":
            if declared is None or actual is None:
                code = "ER2_TRUNC_MISSING_DUAL_FIELDS"
                if reported == "PASS":
                    return {"judge": "FAIL", "reason_code": "ER2_TRUNC_MISSING_DUAL_FALSE_PASS"}
                return {"judge": "FAIL", "reason_code": code}
            if declared == actual and reported == "PASS":
                # same-shape lie: truncated but declared==actual hides truncation
                return {
                    "judge": "FAIL",
                    "reason_code": "ER2_TRUNC_SAME_SHAPE_FALSE_PASS",
                    "detail": {"declared_bytes": declared, "actual_bytes": actual},
                }
            if isinstance(declared, int) and isinstance(actual, int) and actual < declared:
                return {"judge": "PASS", "reason_code": "ER2_TRUNC_DUAL_OK"}
            return {"judge": "FAIL", "reason_code": "ER2_TRUNC_INCONSISTENT"}
        if status == "COMPLETE" and declared == actual and isinstance(actual, int):
            return {"judge": "PASS", "reason_code": "ER2_COMPLETE_OK"}
        return {"judge": "FAIL", "reason_code": "ER2_UNCLASSIFIED"}

    # --- ER3: cross_round_reconcile needs generation_rule_version ---
    if kind == "cross_round_rule_ver":
        left = receipt.get("left_digest")
        right = receipt.get("right_digest")
        rule_ver = receipt.get("generation_rule_version")
        no_diff = bool(receipt.get("reported_no_diff", False))
        if no_diff and rule_ver in (None, ""):
            if reported == "PASS":
                return {"judge": "FAIL", "reason_code": "ER3_NO_RULE_VER_FALSE_PASS"}
            return {"judge": "FAIL", "reason_code": "ER3_NO_RULE_VER"}
        if no_diff and rule_ver and left == right:
            return {"judge": "PASS", "reason_code": "ER3_RECONCILE_OK"}
        if no_diff and rule_ver and left != right:
            return {"judge": "FAIL", "reason_code": "ER3_DIGEST_MISMATCH"}
        if not no_diff:
            return {"judge": "PASS", "reason_code": "ER3_DIFF_DECLARED"}
        return {"judge": "FAIL", "reason_code": "ER3_UNCLASSIFIED"}

    return {"judge": "FAIL", "reason_code": "UNCLASSIFIED", "kind": kind}


CASES: list[dict[str, Any]] = [
    # T5
    {
        "case_id": "T5-missing-hollow-pass",
        "kind": "semantic_complete_explicit",
        "reported_verdict": "PASS",
        "parseable": True,
        "semantic_complete": None,
        "semantic_complete_declared": False,
        "expect_judge": "FAIL",
        "expect_reason": "T5_SEMANTIC_COMPLETE_MISSING_HOLLOW_PASS",
    },
    {
        "case_id": "T5-implied-complete-false-pass",
        "kind": "semantic_complete_explicit",
        "reported_verdict": "PASS",
        "parseable": True,
        "semantic_complete": False,
        "semantic_complete_declared": False,
        "expect_judge": "FAIL",
        "expect_reason": "T5_PARSEABLE_IMPLIED_COMPLETE_FALSE_PASS",
    },
    {
        "case_id": "T5-explicit-ok",
        "kind": "semantic_complete_explicit",
        "reported_verdict": "PASS",
        "parseable": True,
        "semantic_complete": True,
        "semantic_complete_declared": True,
        "expect_judge": "PASS",
        "expect_reason": "T5_SEMANTIC_COMPLETE_EXPLICIT",
    },
    # M1
    {
        "case_id": "M1-empty-rows-false-pass",
        "kind": "empty_rows_pass",
        "reported_verdict": "PASS",
        "rows": [],
        "expect_judge": "FAIL",
        "expect_reason": "M1_EMPTY_ROWS_FALSE_PASS",
    },
    {
        "case_id": "M1-empty-rows-declared",
        "kind": "empty_rows_pass",
        "reported_verdict": "INCONCLUSIVE",
        "rows": [],
        "expect_judge": "PASS",
        "expect_reason": "M1_EMPTY_ROWS_DECLARED",
    },
    # M2 贺水仙
    {
        "case_id": "M2-empty-batch-complete-false-pass",
        "kind": "empty_batch_incomplete",
        "reported_verdict": "PASS",
        "batch": [],
        "batch_complete": True,
        "expect_judge": "FAIL",
        "expect_reason": "M2_EMPTY_BATCH_COMPLETE_FALSE_PASS",
    },
    {
        "case_id": "M2-empty-batch-not-complete",
        "kind": "empty_batch_incomplete",
        "reported_verdict": "FAIL",
        "batch": [],
        "batch_complete": False,
        "expect_judge": "PASS",
        "expect_reason": "M2_EMPTY_BATCH_NOT_COMPLETE",
    },
    # M3
    {
        "case_id": "M3-null-payload-rate-false-pass",
        "kind": "null_payload_rate",
        "reported_verdict": "PASS",
        "payload": None,
        "coverage_rate": 1.0,
        "expect_judge": "FAIL",
        "expect_reason": "M3_NULL_PAYLOAD_RATE_FALSE_PASS",
    },
    {
        "case_id": "M3-null-payload-no-rate",
        "kind": "null_payload_rate",
        "reported_verdict": "INCONCLUSIVE",
        "payload": None,
        "coverage_rate": None,
        "expect_judge": "PASS",
        "expect_reason": "M3_NULL_PAYLOAD_NO_RATE",
    },
    # M4
    {
        "case_id": "M4-empty-events-pair-false-pass",
        "kind": "empty_events_paired",
        "reported_verdict": "PASS",
        "events": [],
        "pair_ok": True,
        "expect_judge": "FAIL",
        "expect_reason": "M4_EMPTY_EVENTS_PAIR_FALSE_PASS",
    },
    {
        "case_id": "M4-empty-events-unpaired",
        "kind": "empty_events_paired",
        "reported_verdict": "FAIL",
        "events": [],
        "pair_ok": False,
        "expect_judge": "PASS",
        "expect_reason": "M4_EMPTY_EVENTS_UNPAIRED",
    },
    # M5
    {
        "case_id": "M5-denom-zero-rate-false-pass",
        "kind": "registry_denom_zero",
        "reported_verdict": "PASS",
        "registry_denominator": 0,
        "measurement_stopped": False,
        "coverage_rate": 1.0,
        "expect_judge": "FAIL",
        "expect_reason": "M5_DENOM_ZERO_RATE_FALSE_PASS",
    },
    {
        "case_id": "M5-denom-zero-stopped",
        "kind": "registry_denom_zero",
        "reported_verdict": "FAIL",
        "registry_denominator": 0,
        "measurement_stopped": True,
        "coverage_rate": None,
        "expect_judge": "PASS",
        "expect_reason": "M5_DENOM_ZERO_STOPPED",
    },
    # M6
    {
        "case_id": "M6-empty-receipt-exit0-false-pass",
        "kind": "empty_receipt_exit0",
        "reported_verdict": "PASS",
        "execution_receipt": None,
        "exit_code": 0,
        "expect_judge": "FAIL",
        "expect_reason": "M6_EMPTY_RECEIPT_EXIT0_FALSE_PASS",
    },
    {
        "case_id": "M6-receipt-present",
        "kind": "empty_receipt_exit0",
        "reported_verdict": "PASS",
        "execution_receipt": {"request_id": "r-1"},
        "exit_code": 0,
        "expect_judge": "PASS",
        "expect_reason": "M6_RECEIPT_PRESENT",
    },
    # M7
    {
        "case_id": "M7-empty-keys-false-pass",
        "kind": "empty_keys_green",
        "reported_verdict": "PASS",
        "unique_keys": 0,
        "expected_rows": 12,
        "expect_judge": "FAIL",
        "expect_reason": "M7_EMPTY_KEYS_FALSE_PASS",
    },
    {
        "case_id": "M7-keys-ok",
        "kind": "empty_keys_green",
        "reported_verdict": "PASS",
        "unique_keys": 12,
        "expected_rows": 12,
        "expect_judge": "PASS",
        "expect_reason": "M7_KEYS_OK",
    },
    # ER1 Tree / 东湖小C
    {
        "case_id": "ER1-scheduler-written-false-pass",
        "kind": "request_id_writer",
        "reported_verdict": "PASS",
        "request_id": "r-99",
        "request_id_writer": "scheduler",
        "expect_judge": "FAIL",
        "expect_reason": "ER1_SCHEDULER_WRITTEN_FALSE_PASS",
    },
    {
        "case_id": "ER1-executed-step-ok",
        "kind": "request_id_writer",
        "reported_verdict": "PASS",
        "request_id": "r-99",
        "request_id_writer": "executed_step",
        "expect_judge": "PASS",
        "expect_reason": "ER1_EXECUTED_STEP_OK",
    },
    # ER2
    {
        "case_id": "ER2-trunc-missing-dual-false-pass",
        "kind": "artifact_trunc_dual",
        "reported_verdict": "PASS",
        "artifact_status": "TRUNCATED",
        "declared_bytes": None,
        "actual_bytes": None,
        "expect_judge": "FAIL",
        "expect_reason": "ER2_TRUNC_MISSING_DUAL_FALSE_PASS",
    },
    {
        "case_id": "ER2-trunc-same-shape-false-pass",
        "kind": "artifact_trunc_dual",
        "reported_verdict": "PASS",
        "artifact_status": "TRUNCATED",
        "declared_bytes": 4096,
        "actual_bytes": 4096,
        "expect_judge": "FAIL",
        "expect_reason": "ER2_TRUNC_SAME_SHAPE_FALSE_PASS",
    },
    {
        "case_id": "ER2-trunc-dual-ok",
        "kind": "artifact_trunc_dual",
        "reported_verdict": "FAIL",
        "artifact_status": "TRUNCATED",
        "declared_bytes": 4096,
        "actual_bytes": 2048,
        "expect_judge": "PASS",
        "expect_reason": "ER2_TRUNC_DUAL_OK",
    },
    # ER3
    {
        "case_id": "ER3-no-rule-ver-false-pass",
        "kind": "cross_round_rule_ver",
        "reported_verdict": "PASS",
        "left_digest": "aaa",
        "right_digest": "aaa",
        "generation_rule_version": None,
        "reported_no_diff": True,
        "expect_judge": "FAIL",
        "expect_reason": "ER3_NO_RULE_VER_FALSE_PASS",
    },
    {
        "case_id": "ER3-reconcile-ok",
        "kind": "cross_round_rule_ver",
        "reported_verdict": "PASS",
        "left_digest": "aaa",
        "right_digest": "aaa",
        "generation_rule_version": "gen-rule/v3",
        "reported_no_diff": True,
        "expect_judge": "PASS",
        "expect_reason": "ER3_RECONCILE_OK",
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
        "fixture": "LEDGER_SILENT_GAPS",
        "version": "v0.2",
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
