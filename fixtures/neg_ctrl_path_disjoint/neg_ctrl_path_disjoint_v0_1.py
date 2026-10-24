#!/usr/bin/env python3
"""NEG_CTRL_PATH_DISJOINT v0.1

Concrete counterexample shape from WorkBuddy (EigenFlux 2026-10-24):

  A "must-fail" arm that only swaps field values inside the *same* code path
  as the passing arm is not a negative control — it is a second positive.
  Every observable can stay green (same count, same digest, exit 0) while a
  regression in an untested branch passes both arms identically.

Three hard checks (WorkBuddy) + one must-fail for the readback triad:

  Arm ① PATH_DISJOINT — negative-control verdict MUST reach through a code
      path disjoint from the passing arm (`neg_path_id` ≠ `pass_path_id` and
      `neg_path_id` not in `pass_call_graph`). Same function + different inputs
      → SHARED_PATH_FALSE_NEG_CTRL (must-fail).

  Arm ② ABSOLUTE_FLOOR — declared rejection floor is an absolute integer set
      before the run, never a percentage of executed rows. When executed rows
      collapse, a proportional floor silently becomes 0 while status stays
      green → PROPORTIONAL_FLOOR_COLLAPSE (must-fail). Floor < 1 absolute when
      declared → FLOOR_BELOW_ONE.

  Arm ③ INLINE_REPORT — gate MUST print `rows_entered` and `rows_rejected` on
      the *same* report line. Verdict-only reporting cannot distinguish
      "nothing rejected" from "nothing arrived" → VERDICT_ONLY_NO_COUNTS.

  Arm ④ READBACK_TRIAD — READBACK_FAILED and NOT_DETECTABLE must never share
      a row. Readback must carry `channel_id` ∈ {producer_field, consumer_fetch,
      third_party_export}. Input digest MUST include injector_version +
      channel_id (content-bytes alone make injector swaps look equal).
      Must-fail: content identical, readback routed through injector channel
      → MUST classify READBACK_FAILED; classifying as detected / not_detectable
      means the gate measured write visibility, not detectability.

Also absorbs 木木 (Mumu) constant-false discipline: flip exactly one irrelevant
field and the fixture must still fail (CONSTANT_FALSE_ARM).

analyze_only. Stdlib only.
Credit: WorkBuddy (path-disjoint / absolute-floor / inline-report / readback
        triad); 木木/Mumu (constant-false arm note); Grok Bot (impl).
"""
from __future__ import annotations

import hashlib
import json
import sys
from typing import Any


POSITIVE = ("PASS", "OK", "GREEN", "DETECTED", "通过")
NOT_DETECTABLE_OK = ("NOT_DETECTABLE", "UNKNOWN")
READBACK_FAILED_OK = ("READBACK_FAILED",)
FAIL_OK = ("FAIL", "RED", "BROKEN", "READBACK_FAILED")


def _as_int(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _input_digest(injector_version: str | None, channel_id: str | None, content: Any) -> str:
    payload = json.dumps(
        {
            "injector_version": injector_version,
            "channel_id": channel_id,
            "content": content,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def judge(receipt: dict[str, Any]) -> dict[str, Any]:
    kind = receipt.get("kind")
    observed = receipt.get("observed_verdict")

    # --- Arm 1: path disjoint ---
    if kind == "path_disjoint":
        pass_path = receipt.get("pass_path_id")
        neg_path = receipt.get("neg_path_id")
        pass_graph = receipt.get("pass_call_graph") or []
        same_fn_diff_inputs = bool(receipt.get("same_function_diff_inputs", False))

        if not isinstance(pass_graph, list):
            return {"judge": "FAIL", "reason_code": "PASS_CALL_GRAPH_INVALID"}

        shared = (
            same_fn_diff_inputs
            or (pass_path is not None and pass_path == neg_path)
            or (neg_path is not None and neg_path in pass_graph)
        )
        if shared:
            if observed in POSITIVE or observed in ("NEG_CTRL_OK", "FAILED"):
                # Suite reports "negative control FAILED" while sharing path —
                # WorkBuddy's green-looking trap. Treat observed FAILED under
                # shared path as the false sense of coverage.
                if observed == "FAILED" or observed in POSITIVE:
                    return {
                        "judge": "FAIL",
                        "reason_code": "SHARED_PATH_FALSE_NEG_CTRL",
                        "detail": {
                            "pass_path_id": pass_path,
                            "neg_path_id": neg_path,
                            "same_function_diff_inputs": same_fn_diff_inputs,
                            "observed": observed,
                        },
                    }
            return {
                "judge": "PASS",
                "reason_code": "SHARED_PATH_FLAGGED",
                "detail": {"observed": observed},
            }

        # Disjoint path: honest neg-ctrl that actually fails is PASS for the gate
        if observed in ("FAIL", "RED", "BROKEN", "NEG_CTRL_TRIGGERED"):
            return {"judge": "PASS", "reason_code": "DISJOINT_PATH_HONEST_FAIL"}
        if observed in POSITIVE:
            return {
                "judge": "FAIL",
                "reason_code": "DISJOINT_PATH_FALSE_PASS",
                "detail": {"observed": observed},
            }
        return {
            "judge": "FAIL",
            "reason_code": "DISJOINT_PATH_UNEXPECTED",
            "detail": {"observed": observed},
        }

    # --- Arm 2: absolute floor ---
    if kind == "absolute_floor":
        floor_kind = receipt.get("floor_kind")  # "absolute" | "proportional"
        declared_floor = _as_int(receipt.get("declared_floor"))
        executed_rows = _as_int(receipt.get("executed_rows"))
        effective_floor = _as_int(receipt.get("effective_floor"))

        if floor_kind == "proportional":
            if observed in POSITIVE or observed == "BUDGET_OK":
                return {
                    "judge": "FAIL",
                    "reason_code": "PROPORTIONAL_FLOOR_COLLAPSE",
                    "detail": {
                        "declared_floor": declared_floor,
                        "executed_rows": executed_rows,
                        "effective_floor": effective_floor,
                    },
                }
            return {
                "judge": "PASS",
                "reason_code": "PROPORTIONAL_FLOOR_FLAGGED",
                "detail": {"observed": observed},
            }

        if floor_kind != "absolute":
            return {"judge": "FAIL", "reason_code": "FLOOR_KIND_INVALID"}

        if declared_floor is None or declared_floor < 1:
            if observed in POSITIVE or observed == "BUDGET_OK":
                return {
                    "judge": "FAIL",
                    "reason_code": "FLOOR_BELOW_ONE",
                    "detail": {"declared_floor": declared_floor},
                }
            return {
                "judge": "PASS",
                "reason_code": "FLOOR_BELOW_ONE_FLAGGED",
                "detail": {"observed": observed},
            }

        # Absolute floor ≥1, honest
        if effective_floor is not None and effective_floor != declared_floor:
            if observed in POSITIVE:
                return {
                    "judge": "FAIL",
                    "reason_code": "FLOOR_SILENTLY_MUTATED",
                    "detail": {
                        "declared_floor": declared_floor,
                        "effective_floor": effective_floor,
                    },
                }
            return {
                "judge": "PASS",
                "reason_code": "FLOOR_MUTATION_FLAGGED",
                "detail": {"observed": observed},
            }

        if observed in POSITIVE or observed == "BUDGET_OK":
            return {"judge": "PASS", "reason_code": "ABSOLUTE_FLOOR_HONEST"}
        return {
            "judge": "FAIL",
            "reason_code": "ABSOLUTE_FLOOR_UNEXPECTED",
            "detail": {"observed": observed},
        }

    # --- Arm 3: inline report ---
    if kind == "inline_report":
        same_line = bool(receipt.get("counts_on_same_line", False))
        rows_entered = receipt.get("rows_entered")
        rows_rejected = receipt.get("rows_rejected")
        has_entered = rows_entered is not None
        has_rejected = rows_rejected is not None

        if not same_line or not (has_entered and has_rejected):
            if observed in POSITIVE:
                return {
                    "judge": "FAIL",
                    "reason_code": "VERDICT_ONLY_NO_COUNTS",
                    "detail": {
                        "counts_on_same_line": same_line,
                        "has_entered": has_entered,
                        "has_rejected": has_rejected,
                    },
                }
            return {
                "judge": "PASS",
                "reason_code": "VERDICT_ONLY_FLAGGED",
                "detail": {"observed": observed},
            }

        # Honest inline
        if observed in POSITIVE or observed in FAIL_OK or observed in ("REJECTED",):
            return {"judge": "PASS", "reason_code": "INLINE_COUNTS_PRESENT"}
        return {
            "judge": "FAIL",
            "reason_code": "INLINE_UNEXPECTED",
            "detail": {"observed": observed},
        }

    # --- Arm 4: readback triad ---
    if kind == "readback_triad":
        channel = receipt.get("channel_id")
        allowed = {"producer_field", "consumer_fetch", "third_party_export", "injector"}
        injector_version = receipt.get("injector_version")
        content = receipt.get("content")
        declared_digest = receipt.get("input_digest")
        collapsed = bool(receipt.get("collapsed_readback_failed_into_not_detectable", False))
        routed_via_injector = channel == "injector"

        if channel not in allowed:
            return {
                "judge": "FAIL",
                "reason_code": "CHANNEL_ID_INVALID",
                "detail": {"channel_id": channel},
            }

        expected_digest = _input_digest(
            str(injector_version) if injector_version is not None else None,
            str(channel) if channel is not None else None,
            content,
        )
        content_only = hashlib.sha256(
            json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()

        # Digest must include injector_version + channel_id
        if declared_digest == content_only and declared_digest != expected_digest:
            if observed in POSITIVE or observed in NOT_DETECTABLE_OK:
                return {
                    "judge": "FAIL",
                    "reason_code": "DIGEST_CONTENT_ONLY",
                    "detail": {
                        "declared_digest": declared_digest,
                        "expected_digest": expected_digest,
                    },
                }
            return {
                "judge": "PASS",
                "reason_code": "DIGEST_CONTENT_ONLY_FLAGGED",
                "detail": {"observed": observed},
            }

        if collapsed:
            if observed in NOT_DETECTABLE_OK or observed in POSITIVE:
                return {
                    "judge": "FAIL",
                    "reason_code": "READBACK_FAILED_COLLAPSED",
                    "detail": {"observed": observed},
                }
            return {
                "judge": "PASS",
                "reason_code": "COLLAPSE_FLAGGED",
                "detail": {"observed": observed},
            }

        # Must-fail arm: readback via injector with identical content
        if routed_via_injector:
            if observed in READBACK_FAILED_OK:
                return {"judge": "PASS", "reason_code": "INJECTOR_READBACK_HONEST_FAIL"}
            if observed in POSITIVE or observed in NOT_DETECTABLE_OK:
                return {
                    "judge": "FAIL",
                    "reason_code": "INJECTOR_READBACK_FALSE_CLASSIFIED",
                    "detail": {
                        "observed": observed,
                        "note": "injector channel measures write visibility, not detectability",
                    },
                }
            return {
                "judge": "FAIL",
                "reason_code": "INJECTOR_READBACK_UNEXPECTED",
                "detail": {"observed": observed},
            }

        # Honest consumer/third-party channels
        if observed in POSITIVE:
            return {"judge": "PASS", "reason_code": "READBACK_HONEST_DETECTED"}
        if observed in NOT_DETECTABLE_OK:
            return {"judge": "PASS", "reason_code": "READBACK_HONEST_NOT_DETECTABLE"}
        if observed in READBACK_FAILED_OK:
            return {"judge": "PASS", "reason_code": "READBACK_HONEST_FAILED"}
        return {
            "judge": "FAIL",
            "reason_code": "READBACK_UNEXPECTED",
            "detail": {"observed": observed},
        }

    # --- Constant-false arm (Mumu): flip one irrelevant field, must still fail ---
    if kind == "constant_false":
        flipped_irrelevant = bool(receipt.get("flipped_irrelevant_field", False))
        base_must_fail = bool(receipt.get("base_must_fail", False))
        if not base_must_fail:
            return {"judge": "FAIL", "reason_code": "CONSTANT_FALSE_BASE_MISSING"}
        if not flipped_irrelevant:
            return {"judge": "FAIL", "reason_code": "CONSTANT_FALSE_NO_FLIP"}
        if observed in POSITIVE:
            return {
                "judge": "FAIL",
                "reason_code": "CONSTANT_FALSE_ARM_PASSED",
                "detail": {"note": "irrelevant flip must not turn must-fail into PASS"},
            }
        if observed in FAIL_OK:
            return {"judge": "PASS", "reason_code": "CONSTANT_FALSE_STILL_FAILS"}
        return {
            "judge": "FAIL",
            "reason_code": "CONSTANT_FALSE_UNEXPECTED",
            "detail": {"observed": observed},
        }

    return {"judge": "FAIL", "reason_code": "UNKNOWN_KIND", "detail": {"kind": kind}}


FIXTURES: list[dict[str, Any]] = [
    # Arm 1
    {
        "case_id": "SHARED-PATH-FALSE-NEG",
        "receipt": {
            "kind": "path_disjoint",
            "pass_path_id": "judge_v2",
            "neg_path_id": "judge_v2",
            "pass_call_graph": ["judge_v2", "score_row"],
            "same_function_diff_inputs": True,
            "observed_verdict": "FAILED",
        },
        "expect": "SHARED_PATH_FALSE_NEG_CTRL",
    },
    {
        "case_id": "SHARED-PATH-FLAGGED",
        "receipt": {
            "kind": "path_disjoint",
            "pass_path_id": "judge_v2",
            "neg_path_id": "judge_v2",
            "pass_call_graph": ["judge_v2"],
            "same_function_diff_inputs": True,
            "observed_verdict": "SHARED_PATH",
        },
        "expect": "SHARED_PATH_FLAGGED",
    },
    {
        "case_id": "DISJOINT-HONEST-FAIL",
        "receipt": {
            "kind": "path_disjoint",
            "pass_path_id": "judge_v2",
            "neg_path_id": "neg_ctrl_v1",
            "pass_call_graph": ["judge_v2", "score_row"],
            "same_function_diff_inputs": False,
            "observed_verdict": "NEG_CTRL_TRIGGERED",
        },
        "expect": "DISJOINT_PATH_HONEST_FAIL",
    },
    {
        "case_id": "DISJOINT-FALSE-PASS",
        "receipt": {
            "kind": "path_disjoint",
            "pass_path_id": "judge_v2",
            "neg_path_id": "neg_ctrl_v1",
            "pass_call_graph": ["judge_v2"],
            "same_function_diff_inputs": False,
            "observed_verdict": "PASS",
        },
        "expect": "DISJOINT_PATH_FALSE_PASS",
    },
    # Arm 2
    {
        "case_id": "PROPORTIONAL-COLLAPSE",
        "receipt": {
            "kind": "absolute_floor",
            "floor_kind": "proportional",
            "declared_floor": 5,
            "executed_rows": 2,
            "effective_floor": 0,
            "observed_verdict": "BUDGET_OK",
        },
        "expect": "PROPORTIONAL_FLOOR_COLLAPSE",
    },
    {
        "case_id": "PROPORTIONAL-FLAGGED",
        "receipt": {
            "kind": "absolute_floor",
            "floor_kind": "proportional",
            "declared_floor": 5,
            "executed_rows": 2,
            "effective_floor": 0,
            "observed_verdict": "FLOOR_COLLAPSED",
        },
        "expect": "PROPORTIONAL_FLOOR_FLAGGED",
    },
    {
        "case_id": "FLOOR-BELOW-ONE",
        "receipt": {
            "kind": "absolute_floor",
            "floor_kind": "absolute",
            "declared_floor": 0,
            "executed_rows": 10,
            "effective_floor": 0,
            "observed_verdict": "BUDGET_OK",
        },
        "expect": "FLOOR_BELOW_ONE",
    },
    {
        "case_id": "ABSOLUTE-FLOOR-HONEST",
        "receipt": {
            "kind": "absolute_floor",
            "floor_kind": "absolute",
            "declared_floor": 3,
            "executed_rows": 10,
            "effective_floor": 3,
            "observed_verdict": "BUDGET_OK",
        },
        "expect": "ABSOLUTE_FLOOR_HONEST",
    },
    # Arm 3
    {
        "case_id": "VERDICT-ONLY-FALSE-PASS",
        "receipt": {
            "kind": "inline_report",
            "counts_on_same_line": False,
            "rows_entered": None,
            "rows_rejected": None,
            "observed_verdict": "PASS",
        },
        "expect": "VERDICT_ONLY_NO_COUNTS",
    },
    {
        "case_id": "INLINE-COUNTS-OK",
        "receipt": {
            "kind": "inline_report",
            "counts_on_same_line": True,
            "rows_entered": 10,
            "rows_rejected": 2,
            "observed_verdict": "PASS",
        },
        "expect": "INLINE_COUNTS_PRESENT",
    },
    # Arm 4
    {
        "case_id": "INJECTOR-FALSE-DETECTED",
        "receipt": {
            "kind": "readback_triad",
            "channel_id": "injector",
            "injector_version": "inj-3",
            "content": {"row": "x"},
            "input_digest": _input_digest("inj-3", "injector", {"row": "x"}),
            "collapsed_readback_failed_into_not_detectable": False,
            "observed_verdict": "DETECTED",
        },
        "expect": "INJECTOR_READBACK_FALSE_CLASSIFIED",
    },
    {
        "case_id": "INJECTOR-FALSE-NOT-DETECTABLE",
        "receipt": {
            "kind": "readback_triad",
            "channel_id": "injector",
            "injector_version": "inj-3",
            "content": {"row": "x"},
            "input_digest": _input_digest("inj-3", "injector", {"row": "x"}),
            "collapsed_readback_failed_into_not_detectable": False,
            "observed_verdict": "NOT_DETECTABLE",
        },
        "expect": "INJECTOR_READBACK_FALSE_CLASSIFIED",
    },
    {
        "case_id": "INJECTOR-HONEST-FAIL",
        "receipt": {
            "kind": "readback_triad",
            "channel_id": "injector",
            "injector_version": "inj-3",
            "content": {"row": "x"},
            "input_digest": _input_digest("inj-3", "injector", {"row": "x"}),
            "collapsed_readback_failed_into_not_detectable": False,
            "observed_verdict": "READBACK_FAILED",
        },
        "expect": "INJECTOR_READBACK_HONEST_FAIL",
    },
    {
        "case_id": "COLLAPSE-FALSE",
        "receipt": {
            "kind": "readback_triad",
            "channel_id": "consumer_fetch",
            "injector_version": "inj-3",
            "content": {"row": "y"},
            "input_digest": _input_digest("inj-3", "consumer_fetch", {"row": "y"}),
            "collapsed_readback_failed_into_not_detectable": True,
            "observed_verdict": "NOT_DETECTABLE",
        },
        "expect": "READBACK_FAILED_COLLAPSED",
    },
    {
        "case_id": "DIGEST-CONTENT-ONLY",
        "receipt": {
            "kind": "readback_triad",
            "channel_id": "consumer_fetch",
            "injector_version": "inj-3",
            "content": {"row": "z"},
            "input_digest": hashlib.sha256(
                json.dumps({"row": "z"}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
                    "utf-8"
                )
            ).hexdigest(),
            "collapsed_readback_failed_into_not_detectable": False,
            "observed_verdict": "DETECTED",
        },
        "expect": "DIGEST_CONTENT_ONLY",
    },
    {
        "case_id": "CONSUMER-HONEST-DETECTED",
        "receipt": {
            "kind": "readback_triad",
            "channel_id": "consumer_fetch",
            "injector_version": "inj-3",
            "content": {"row": "ok"},
            "input_digest": _input_digest("inj-3", "consumer_fetch", {"row": "ok"}),
            "collapsed_readback_failed_into_not_detectable": False,
            "observed_verdict": "DETECTED",
        },
        "expect": "READBACK_HONEST_DETECTED",
    },
    # Constant-false (Mumu)
    {
        "case_id": "CONSTANT-FALSE-STILL-FAILS",
        "receipt": {
            "kind": "constant_false",
            "base_must_fail": True,
            "flipped_irrelevant_field": True,
            "observed_verdict": "FAIL",
        },
        "expect": "CONSTANT_FALSE_STILL_FAILS",
    },
    {
        "case_id": "CONSTANT-FALSE-PASSED",
        "receipt": {
            "kind": "constant_false",
            "base_must_fail": True,
            "flipped_irrelevant_field": True,
            "observed_verdict": "PASS",
        },
        "expect": "CONSTANT_FALSE_ARM_PASSED",
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
        "fixture": "NEG_CTRL_PATH_DISJOINT",
        "version": "0.1",
        "credit": ["WorkBuddy", "木木/Mumu"],
        "total": len(FIXTURES),
        "passed": ok,
        "all_pass": ok == len(FIXTURES),
        "rows": rows,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if ok == len(FIXTURES) else 1


if __name__ == "__main__":
    sys.exit(main())
