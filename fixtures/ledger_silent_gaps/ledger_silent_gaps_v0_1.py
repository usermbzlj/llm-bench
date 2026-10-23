#!/usr/bin/env python3
"""LEDGER_SILENT_GAPS v0.1

Credit:
  - Jerry — three reproducible ledger-gap samples + coverage-incomputable
  - MiniMax Code — trunc pre-frame vs post-frame; parseable ≠ semantic-complete
  - 沈小楠 — retry lineage pointer must be written by the retry initiator

Detects ledger shapes that stay green under naive checks:
  1. MID_TRUNC_EXIT0 — exit 0, head+tail present, mid missing N rows
  2. SELF_NUM_COLLISION — self-id delta==1 still holds under missed+collided ids
  3. SEGMENT_STOP_AS_DISCOVERY — measurement stop shrinks segments; same ledger shape as "new segment"
  4. COVERAGE_INCOMPUTABLE — numerator countable, denominator drifted; must not emit a fake rate
  5. TRUNC_FRAME_PHASE — half-line (pre-frame) vs in-frame trunc need distinct reason codes
  6. PARSEABLE_NOT_COMPLETE — parseable alone must not imply semantic_complete
  7. RETRY_POINTER_WRITER — lineage pointer authored by retried peer is weak; initiator must write it

analyze_only. Stdlib only.
"""
from __future__ import annotations

import json
import sys
from typing import Any


def judge(receipt: dict[str, Any]) -> dict[str, Any]:
    kind = receipt.get("kind")

    if kind == "mid_trunc":
        exit_code = receipt.get("exit_code")
        head_ok = bool(receipt.get("head_present"))
        tail_ok = bool(receipt.get("tail_present"))
        expected_n = receipt.get("expected_rows")
        actual_n = receipt.get("actual_rows")
        mid_gap = receipt.get("mid_gap_rows")
        if (
            exit_code == 0
            and head_ok
            and tail_ok
            and isinstance(expected_n, int)
            and isinstance(actual_n, int)
            and actual_n < expected_n
            and (mid_gap is None or mid_gap == 0)
        ):
            return {
                "judge": "FAIL",
                "reason_code": "MID_TRUNC_EXIT0",
                "detail": {"expected_rows": expected_n, "actual_rows": actual_n},
            }
        if (
            exit_code == 0
            and head_ok
            and tail_ok
            and isinstance(mid_gap, int)
            and mid_gap > 0
            and actual_n + mid_gap == expected_n
        ):
            return {"judge": "PASS", "reason_code": "MID_GAP_DECLARED"}
        return {"judge": "FAIL", "reason_code": "UNCLASSIFIED_MID_TRUNC"}

    if kind == "self_num":
        rows = receipt.get("rows") or []
        ids = [r.get("self_id") for r in rows if isinstance(r, dict)]
        if len(ids) != len(set(ids)):
            # consecutive delta may still be 1 locally while global collision exists
            return {"judge": "FAIL", "reason_code": "SELF_NUM_COLLISION"}
        deltas_ok = all(
            isinstance(a, int) and isinstance(b, int) and (b - a) == 1
            for a, b in zip(ids, ids[1:])
        )
        if deltas_ok and len(ids) >= 2:
            return {"judge": "PASS", "reason_code": "SELF_NUM_MONOTONE"}
        return {"judge": "FAIL", "reason_code": "SELF_NUM_GAP"}

    if kind == "segment":
        labeled = receipt.get("label")  # "new_segment" | "segment_stop" | other
        seg_prev = receipt.get("segment_count_prev")
        seg_now = receipt.get("segment_count")
        measured_stop = bool(receipt.get("measurement_stopped"))
        if (
            labeled == "new_segment"
            and measured_stop
            and isinstance(seg_prev, int)
            and isinstance(seg_now, int)
            and seg_now < seg_prev
        ):
            return {"judge": "FAIL", "reason_code": "SEGMENT_STOP_AS_DISCOVERY"}
        if labeled == "segment_stop" and measured_stop:
            return {"judge": "PASS", "reason_code": "SEGMENT_STOP_DECLARED"}
        if labeled == "new_segment" and not measured_stop and seg_now == (seg_prev or 0) + 1:
            return {"judge": "PASS", "reason_code": "NEW_SEGMENT_OK"}
        return {"judge": "FAIL", "reason_code": "UNCLASSIFIED_SEGMENT"}

    if kind == "coverage":
        num = receipt.get("numerator")
        denom = receipt.get("denominator")
        denom_prev = receipt.get("denominator_prev")
        rate = receipt.get("coverage_rate")
        incomputable = bool(receipt.get("coverage_incomputable"))
        denom_drift = (
            isinstance(denom, (int, float))
            and isinstance(denom_prev, (int, float))
            and denom != denom_prev
        )
        if denom_drift and rate is not None and not incomputable:
            return {
                "judge": "FAIL",
                "reason_code": "COVERAGE_FAKE_RATE",
                "detail": {"numerator": num, "denominator": denom, "denominator_prev": denom_prev},
            }
        if denom_drift and incomputable and rate is None:
            return {"judge": "PASS", "reason_code": "COVERAGE_INCOMPUTABLE"}
        if not denom_drift and isinstance(rate, (int, float)):
            return {"judge": "PASS", "reason_code": "COVERAGE_OK"}
        return {"judge": "FAIL", "reason_code": "UNCLASSIFIED_COVERAGE"}

    if kind == "trunc_frame":
        phase = receipt.get("frame_phase")  # "pre_frame" | "post_frame"
        parseable = bool(receipt.get("parseable"))
        semantic_complete = receipt.get("semantic_complete")
        if phase == "pre_frame":
            code = "TRUNC_PRE_FRAME"
        elif phase == "post_frame":
            code = "TRUNC_POST_FRAME"
        else:
            return {"judge": "FAIL", "reason_code": "TRUNC_FRAME_PHASE_MISSING"}
        if parseable and semantic_complete is True:
            # parseable must not silently imply semantic complete without an explicit flag
            if receipt.get("semantic_complete_declared") is not True:
                return {"judge": "FAIL", "reason_code": "PARSEABLE_NOT_COMPLETE"}
        if parseable and semantic_complete is False and receipt.get("semantic_complete_declared") is True:
            return {"judge": "PASS", "reason_code": code + "_DECLARED"}
        if parseable and semantic_complete is True and receipt.get("semantic_complete_declared") is True:
            return {"judge": "PASS", "reason_code": "TRUNC_SEMANTIC_OK"}
        return {"judge": "PASS", "reason_code": code + "_DECLARED"}

    if kind == "retry_pointer":
        pointer_writer = receipt.get("lineage_pointer_writer")  # "initiator" | "retried_peer"
        first_fail_id = receipt.get("first_fail_attempt_id")
        new_attempt_id = receipt.get("new_attempt_id")
        first_fail_immutable = bool(receipt.get("first_fail_immutable"))
        if pointer_writer == "retried_peer":
            return {"judge": "FAIL", "reason_code": "RETRY_POINTER_PEER_WRITTEN"}
        if pointer_writer != "initiator":
            return {"judge": "FAIL", "reason_code": "RETRY_POINTER_WRITER_MISSING"}
        if not first_fail_id or not new_attempt_id or first_fail_id == new_attempt_id:
            return {"judge": "FAIL", "reason_code": "RETRY_POINTER_NO_FIRST_FAIL"}
        if not first_fail_immutable:
            return {"judge": "FAIL", "reason_code": "RETRY_FIRST_FAIL_MUTABLE"}
        return {"judge": "PASS", "reason_code": "RETRY_POINTER_INITIATOR_OK"}

    return {"judge": "FAIL", "reason_code": "UNCLASSIFIED", "kind": kind}


FIXTURES = [
    {
        "case_id": "JERRY-MID-GREEN",
        "receipt": {
            "kind": "mid_trunc",
            "exit_code": 0,
            "head_present": True,
            "tail_present": True,
            "expected_rows": 20,
            "actual_rows": 17,
            "mid_gap_rows": 0,
        },
        "expect": "MID_TRUNC_EXIT0",
    },
    {
        "case_id": "JERRY-MID-DECLARED",
        "receipt": {
            "kind": "mid_trunc",
            "exit_code": 0,
            "head_present": True,
            "tail_present": True,
            "expected_rows": 20,
            "actual_rows": 17,
            "mid_gap_rows": 3,
        },
        "expect": "MID_GAP_DECLARED",
    },
    {
        "case_id": "JERRY-SELF-COLLIDE",
        "receipt": {
            "kind": "self_num",
            "rows": [
                {"self_id": 1},
                {"self_id": 2},
                {"self_id": 2},  # collision after missed log
                {"self_id": 3},
            ],
        },
        "expect": "SELF_NUM_COLLISION",
    },
    {
        "case_id": "JERRY-SELF-OK",
        "receipt": {
            "kind": "self_num",
            "rows": [{"self_id": 10}, {"self_id": 11}, {"self_id": 12}],
        },
        "expect": "SELF_NUM_MONOTONE",
    },
    {
        "case_id": "JERRY-SEG-STOP-AS-NEW",
        "receipt": {
            "kind": "segment",
            "label": "new_segment",
            "measurement_stopped": True,
            "segment_count_prev": 5,
            "segment_count": 4,
        },
        "expect": "SEGMENT_STOP_AS_DISCOVERY",
    },
    {
        "case_id": "JERRY-SEG-STOP-DECLARED",
        "receipt": {
            "kind": "segment",
            "label": "segment_stop",
            "measurement_stopped": True,
            "segment_count_prev": 5,
            "segment_count": 4,
        },
        "expect": "SEGMENT_STOP_DECLARED",
    },
    {
        "case_id": "JERRY-COV-FAKE",
        "receipt": {
            "kind": "coverage",
            "numerator": 3,
            "denominator": 14,
            "denominator_prev": 10,
            "coverage_rate": 0.214,
            "coverage_incomputable": False,
        },
        "expect": "COVERAGE_FAKE_RATE",
    },
    {
        "case_id": "JERRY-COV-INCOMP",
        "receipt": {
            "kind": "coverage",
            "numerator": 0,
            "denominator": 14,
            "denominator_prev": 10,
            "coverage_rate": None,
            "coverage_incomputable": True,
        },
        "expect": "COVERAGE_INCOMPUTABLE",
    },
    {
        "case_id": "MM-TRUNC-PRE",
        "receipt": {
            "kind": "trunc_frame",
            "frame_phase": "pre_frame",
            "parseable": True,
            "semantic_complete": False,
            "semantic_complete_declared": True,
        },
        "expect": "TRUNC_PRE_FRAME_DECLARED",
    },
    {
        "case_id": "MM-PARSEABLE-LIE",
        "receipt": {
            "kind": "trunc_frame",
            "frame_phase": "post_frame",
            "parseable": True,
            "semantic_complete": True,
            "semantic_complete_declared": False,
        },
        "expect": "PARSEABLE_NOT_COMPLETE",
    },
    {
        "case_id": "SHEN-PEER-POINTER",
        "receipt": {
            "kind": "retry_pointer",
            "lineage_pointer_writer": "retried_peer",
            "first_fail_attempt_id": "a1",
            "new_attempt_id": "a2",
            "first_fail_immutable": True,
        },
        "expect": "RETRY_POINTER_PEER_WRITTEN",
    },
    {
        "case_id": "SHEN-INITIATOR-OK",
        "receipt": {
            "kind": "retry_pointer",
            "lineage_pointer_writer": "initiator",
            "first_fail_attempt_id": "a1",
            "new_attempt_id": "a2",
            "first_fail_immutable": True,
        },
        "expect": "RETRY_POINTER_INITIATOR_OK",
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
    out = {"version": "LEDGER_SILENT_GAPS/v0.1", "all_match": ok, "n": len(rows), "rows": rows}
    print(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
