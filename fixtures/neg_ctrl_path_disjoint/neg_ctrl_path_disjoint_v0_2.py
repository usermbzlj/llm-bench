#!/usr/bin/env python3
"""NEG_CTRL_PATH_DISJOINT v0.2

Extends v0.1 with EigenFlux inbound 2026-10-24 shapes (analyze_only).

  E) TAIL_FOUR_STATE (credit 木木/Mumu) — trailing-row four states:
     T01 PASS: planned==emitted, tail_bytes>0, offset==emitted_cum_len, sha present
     T02 MISSING_TAIL: emitted short OR tail_bytes==0 / sha null → must-fail
        (tail_bytes=0 means absent; empty string is forbidden — same shape as unwritten)
     T03 TAIL_TRUNCATED_AT_CAP: tail_bytes == declared_cap (equal-to-cap alone;
        truncation vs exact-length are numerically inseparable without planned-side cap)
     T04 CONSTANT_FALSE: mutate one irrelevant field (gate_name) only; if still
        reported PASS while base is must-fail → CONSTANT_FALSE_ARM_PASSED
     Assert rule: tail_start_offset MUST equal emitted-rows cumulative length,
     NOT last-newline position (continuation lines make the latter wrong).

  F) READBACK_PATH_STRUCT (credit WorkBuddy) — structural readback triad:
     R1 full-ok: readback_path + compute_impl independent + writer path-id distinct → PASS
     R2 missing read_path: readback_path null → NEG_CTRL_RED / READ_PATH_ABSENT
     R3 same-source: writer path_id == read_path id → NEG_CTRL_RED / SAME_PATH_HOMOLOGY
     Path id MUST be registered by the fetch side, never self-reported by SUT.
     Green twin INDEPENDENT_DUAL_OK requires all three separations.

Retains all v0.1 arms (path_disjoint / absolute_floor / inline_report /
readback_triad / constant_false).

analyze_only. Stdlib only.
Credit: 木木/Mumu (T01–T04); WorkBuddy (R1–R3 + v0.1 path/floor/inline/readback);
        Grok Bot (impl).
"""
from __future__ import annotations

import hashlib
import json
import sys
from typing import Any


POSITIVE = ("PASS", "OK", "GREEN", "DETECTED", "通过")
NOT_DETECTABLE_OK = ("NOT_DETECTABLE", "UNKNOWN")
READBACK_FAILED_OK = ("READBACK_FAILED",)
FAIL_OK = ("FAIL", "RED", "BROKEN", "READBACK_FAILED", "NEG_CTRL_RED")


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

    # --- Arm 1: path disjoint (v0.1) ---
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

    # --- Arm 2: absolute floor (v0.1) ---
    if kind == "absolute_floor":
        floor_kind = receipt.get("floor_kind")
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

    # --- Arm 3: inline report (v0.1) ---
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

        if observed in POSITIVE or observed in FAIL_OK or observed in ("REJECTED",):
            return {"judge": "PASS", "reason_code": "INLINE_COUNTS_PRESENT"}
        return {
            "judge": "FAIL",
            "reason_code": "INLINE_UNEXPECTED",
            "detail": {"observed": observed},
        }

    # --- Arm 4: readback triad (v0.1) ---
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

    # --- Constant-false arm (v0.1 / Mumu) ---
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

    # --- Arm E: tail four-state (木木 T01–T04) ---
    if kind == "tail_four_state":
        case = receipt.get("case_id") or receipt.get("tail_case")
        planned = _as_int(receipt.get("planned"))
        emitted = _as_int(receipt.get("emitted"))
        tail_offset = _as_int(receipt.get("tail_offset"))
        tail_bytes = receipt.get("tail_bytes")
        # Distinguish 0 (absent) from missing key; empty string forbidden
        if isinstance(tail_bytes, str):
            if tail_bytes == "":
                return {
                    "judge": "FAIL",
                    "reason_code": "TAIL_BYTES_EMPTY_STRING_FORBIDDEN",
                    "detail": {"note": "use 0 for absent, never empty string"},
                }
            tail_bytes_i = _as_int(tail_bytes)
        else:
            tail_bytes_i = _as_int(tail_bytes)
        tail_sha = receipt.get("tail_sha256")
        declared_cap = _as_int(receipt.get("declared_cap"))
        emitted_cum_len = _as_int(receipt.get("emitted_cum_len"))
        offset_basis = receipt.get("offset_basis")  # "emitted_cum_len" | "last_newline"
        mutated = receipt.get("mutated")  # e.g. "gate_name"
        reason = receipt.get("reason")

        # Offset must assert against emitted cumulative length, not last newline
        if offset_basis == "last_newline":
            if observed in POSITIVE:
                return {
                    "judge": "FAIL",
                    "reason_code": "TAIL_OFFSET_LAST_NEWLINE",
                    "detail": {"offset_basis": offset_basis},
                }
            return {
                "judge": "PASS",
                "reason_code": "TAIL_OFFSET_LAST_NEWLINE_FLAGGED",
                "detail": {"observed": observed},
            }

        # T02: missing tail — bytes 0 or sha null / emitted short
        missing = (
            (tail_bytes_i is not None and tail_bytes_i == 0)
            or tail_sha is None
            or (planned is not None and emitted is not None and emitted < planned)
        )
        # T03: equal-to-cap truncation
        at_cap = (
            declared_cap is not None
            and tail_bytes_i is not None
            and tail_bytes_i == declared_cap
            and declared_cap > 0
        )
        # T04: constant-false — mutated irrelevant field but still PASS
        const_false_pass = mutated is not None and observed in POSITIVE

        if const_false_pass or reason == "CONSTANT_FALSE_ARM_PASSED":
            if observed in POSITIVE or reason == "CONSTANT_FALSE_ARM_PASSED":
                # Suite that reports CONSTANT_FALSE_ARM_PASSED as its observed
                # reason while still carrying PASS-shaped fields → gate caught it
                if reason == "CONSTANT_FALSE_ARM_PASSED" and observed in FAIL_OK:
                    return {"judge": "PASS", "reason_code": "CONSTANT_FALSE_TAIL_FLAGGED"}
                if observed in POSITIVE:
                    return {
                        "judge": "FAIL",
                        "reason_code": "CONSTANT_FALSE_ARM_PASSED",
                        "detail": {"mutated": mutated, "observed": observed},
                    }
                return {
                    "judge": "PASS",
                    "reason_code": "CONSTANT_FALSE_TAIL_FLAGGED",
                    "detail": {"observed": observed},
                }

        if at_cap:
            if observed in POSITIVE:
                return {
                    "judge": "FAIL",
                    "reason_code": "TAIL_TRUNCATED_AT_CAP",
                    "detail": {
                        "tail_bytes": tail_bytes_i,
                        "declared_cap": declared_cap,
                    },
                }
            if observed in FAIL_OK or reason == "TAIL_TRUNCATED_AT_CAP":
                return {"judge": "PASS", "reason_code": "TAIL_TRUNCATED_AT_CAP_FLAGGED"}
            return {
                "judge": "FAIL",
                "reason_code": "TAIL_AT_CAP_UNEXPECTED",
                "detail": {"observed": observed, "reason": reason},
            }

        if missing:
            if observed in POSITIVE:
                return {
                    "judge": "FAIL",
                    "reason_code": "MISSING_TAIL",
                    "detail": {
                        "tail_bytes": tail_bytes_i,
                        "tail_sha256": tail_sha,
                        "planned": planned,
                        "emitted": emitted,
                    },
                }
            if observed in FAIL_OK or reason == "MISSING_TAIL":
                return {"judge": "PASS", "reason_code": "MISSING_TAIL_FLAGGED"}
            return {
                "judge": "FAIL",
                "reason_code": "MISSING_TAIL_UNEXPECTED",
                "detail": {"observed": observed, "reason": reason},
            }

        # Honest PASS path (T01): all present, offset matches emitted_cum_len
        offset_ok = (
            tail_offset is not None
            and emitted_cum_len is not None
            and tail_offset == emitted_cum_len
        ) or (
            # allow simplified receipts that omit emitted_cum_len when
            # tail_offset == tail_bytes and counts match (木木 T01 shape)
            planned is not None
            and emitted is not None
            and planned == emitted
            and tail_bytes_i is not None
            and tail_bytes_i > 0
            and tail_sha is not None
            and (emitted_cum_len is None or (tail_offset is not None and tail_offset == emitted_cum_len))
        )
        if offset_ok and observed in POSITIVE:
            return {"judge": "PASS", "reason_code": "TAIL_HONEST_PASS"}
        if offset_ok and observed in FAIL_OK:
            return {
                "judge": "FAIL",
                "reason_code": "TAIL_HONEST_FALSE_FAIL",
                "detail": {"observed": observed},
            }
        return {
            "judge": "FAIL",
            "reason_code": "TAIL_FOUR_STATE_UNEXPECTED",
            "detail": {
                "case": case,
                "observed": observed,
                "reason": reason,
                "offset_ok": offset_ok,
            },
        }

    # --- Arm F: readback path structural (WorkBuddy R1–R3) ---
    if kind == "readback_path_struct":
        readback_path = receipt.get("readback_path")  # e.g. "disk" | None
        compute_impl = receipt.get("compute_impl")  # "independent" | ...
        writer = receipt.get("writer")  # writer path id / role
        writer_path_id = receipt.get("writer_path_id") or writer
        read_path_id = receipt.get("read_path_id") or readback_path
        path_id_source = receipt.get("path_id_source")  # "fetch_side" | "sut_self"
        bytes_n = _as_int(receipt.get("bytes"))
        records = _as_int(receipt.get("records"))

        # Path id must be fetch-side registered
        if path_id_source == "sut_self":
            if observed in POSITIVE:
                return {
                    "judge": "FAIL",
                    "reason_code": "PATH_ID_SUT_SELF_REPORTED",
                    "detail": {"path_id_source": path_id_source},
                }
            return {
                "judge": "PASS",
                "reason_code": "PATH_ID_SUT_SELF_FLAGGED",
                "detail": {"observed": observed},
            }

        # R2: missing read_path
        if readback_path is None or read_path_id is None:
            if observed in POSITIVE:
                return {
                    "judge": "FAIL",
                    "reason_code": "READ_PATH_ABSENT",
                    "detail": {"readback_path": readback_path},
                }
            if observed in FAIL_OK or observed == "NEG_CTRL_RED":
                return {"judge": "PASS", "reason_code": "READ_PATH_ABSENT_FLAGGED"}
            return {
                "judge": "FAIL",
                "reason_code": "READ_PATH_ABSENT_UNEXPECTED",
                "detail": {"observed": observed},
            }

        # R3: same-source homology (writer path == read path)
        if writer_path_id is not None and read_path_id is not None and str(writer_path_id) == str(read_path_id):
            if observed in POSITIVE:
                return {
                    "judge": "FAIL",
                    "reason_code": "SAME_PATH_HOMOLOGY",
                    "detail": {
                        "writer_path_id": writer_path_id,
                        "read_path_id": read_path_id,
                    },
                }
            if observed in FAIL_OK or observed == "NEG_CTRL_RED":
                return {"judge": "PASS", "reason_code": "SAME_PATH_HOMOLOGY_FLAGGED"}
            return {
                "judge": "FAIL",
                "reason_code": "SAME_PATH_HOMOLOGY_UNEXPECTED",
                "detail": {"observed": observed},
            }

        # R1: all three separations
        independent = compute_impl == "independent"
        paths_distinct = str(writer_path_id) != str(read_path_id)
        has_read = readback_path is not None
        if independent and paths_distinct and has_read:
            if observed in POSITIVE:
                return {
                    "judge": "PASS",
                    "reason_code": "INDEPENDENT_DUAL_OK",
                    "detail": {"bytes": bytes_n, "records": records},
                }
            return {
                "judge": "FAIL",
                "reason_code": "INDEPENDENT_DUAL_FALSE_FAIL",
                "detail": {"observed": observed},
            }

        return {
            "judge": "FAIL",
            "reason_code": "READBACK_PATH_STRUCT_UNEXPECTED",
            "detail": {
                "observed": observed,
                "independent": independent,
                "paths_distinct": paths_distinct,
            },
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
    # Constant-false (Mumu v0.1)
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
    # --- v0.2 Arm E: 木木 T01–T04 ---
    {
        "case_id": "T01-TAIL-HONEST-PASS",
        "receipt": {
            "kind": "tail_four_state",
            "case_id": "T01",
            "gate": "count_gate",
            "planned": 40,
            "emitted": 40,
            "tail_offset": 118,
            "tail_bytes": 118,
            "tail_sha256": "ab..",
            "emitted_cum_len": 118,
            "offset_basis": "emitted_cum_len",
            "observed_verdict": "PASS",
        },
        "expect": "TAIL_HONEST_PASS",
    },
    {
        "case_id": "T02-MISSING-TAIL",
        "receipt": {
            "kind": "tail_four_state",
            "case_id": "T02",
            "gate": "count_gate",
            "planned": 40,
            "emitted": 39,
            "tail_offset": 0,
            "tail_bytes": 0,
            "tail_sha256": None,
            "observed_verdict": "FAIL",
            "reason": "MISSING_TAIL",
        },
        "expect": "MISSING_TAIL_FLAGGED",
    },
    {
        "case_id": "T02-MISSING-TAIL-FALSE-PASS",
        "receipt": {
            "kind": "tail_four_state",
            "case_id": "T02b",
            "gate": "count_gate",
            "planned": 40,
            "emitted": 39,
            "tail_offset": 0,
            "tail_bytes": 0,
            "tail_sha256": None,
            "observed_verdict": "PASS",
        },
        "expect": "MISSING_TAIL",
    },
    {
        "case_id": "T02-EMPTY-STRING-FORBIDDEN",
        "receipt": {
            "kind": "tail_four_state",
            "case_id": "T02c",
            "gate": "count_gate",
            "planned": 40,
            "emitted": 40,
            "tail_offset": 0,
            "tail_bytes": "",
            "tail_sha256": None,
            "observed_verdict": "PASS",
        },
        "expect": "TAIL_BYTES_EMPTY_STRING_FORBIDDEN",
    },
    {
        "case_id": "T03-TRUNCATED-AT-CAP",
        "receipt": {
            "kind": "tail_four_state",
            "case_id": "T03",
            "gate": "count_gate",
            "planned": 40,
            "emitted": 40,
            "tail_offset": 118,
            "tail_bytes": 4096,
            "declared_cap": 4096,
            "tail_sha256": "cd..",
            "observed_verdict": "FAIL",
            "reason": "TAIL_TRUNCATED_AT_CAP",
        },
        "expect": "TAIL_TRUNCATED_AT_CAP_FLAGGED",
    },
    {
        "case_id": "T03-AT-CAP-FALSE-PASS",
        "receipt": {
            "kind": "tail_four_state",
            "case_id": "T03b",
            "gate": "count_gate",
            "planned": 40,
            "emitted": 40,
            "tail_offset": 118,
            "tail_bytes": 4096,
            "declared_cap": 4096,
            "tail_sha256": "cd..",
            "observed_verdict": "PASS",
        },
        "expect": "TAIL_TRUNCATED_AT_CAP",
    },
    {
        "case_id": "T04-CONSTANT-FALSE-PASSED",
        "receipt": {
            "kind": "tail_four_state",
            "case_id": "T04",
            "gate": "count_gate",
            "planned": 40,
            "emitted": 40,
            "tail_offset": 118,
            "tail_bytes": 118,
            "tail_sha256": "ab..",
            "emitted_cum_len": 118,
            "mutated": "gate_name",
            "observed_verdict": "PASS",
            "reason": "CONSTANT_FALSE_ARM_PASSED",
        },
        "expect": "CONSTANT_FALSE_ARM_PASSED",
    },
    {
        "case_id": "T04-CONSTANT-FALSE-FLAGGED",
        "receipt": {
            "kind": "tail_four_state",
            "case_id": "T04b",
            "gate": "count_gate",
            "planned": 40,
            "emitted": 40,
            "tail_offset": 118,
            "tail_bytes": 118,
            "tail_sha256": "ab..",
            "emitted_cum_len": 118,
            "mutated": "gate_name",
            "observed_verdict": "FAIL",
            "reason": "CONSTANT_FALSE_ARM_PASSED",
        },
        "expect": "CONSTANT_FALSE_TAIL_FLAGGED",
    },
    {
        "case_id": "TAIL-OFFSET-LAST-NEWLINE",
        "receipt": {
            "kind": "tail_four_state",
            "case_id": "T-off",
            "gate": "count_gate",
            "planned": 40,
            "emitted": 40,
            "tail_offset": 100,
            "tail_bytes": 118,
            "tail_sha256": "ab..",
            "offset_basis": "last_newline",
            "observed_verdict": "PASS",
        },
        "expect": "TAIL_OFFSET_LAST_NEWLINE",
    },
    # --- v0.2 Arm F: WorkBuddy R1–R3 ---
    {
        "case_id": "R1-INDEPENDENT-DUAL-OK",
        "receipt": {
            "kind": "readback_path_struct",
            "readback_path": "disk",
            "read_path_id": "disk",
            "compute_impl": "independent",
            "writer": "batch_driver",
            "writer_path_id": "batch_driver",
            "path_id_source": "fetch_side",
            "bytes": 10402,
            "records": 37,
            "observed_verdict": "PASS",
        },
        "expect": "INDEPENDENT_DUAL_OK",
    },
    {
        "case_id": "R2-READ-PATH-ABSENT",
        "receipt": {
            "kind": "readback_path_struct",
            "readback_path": None,
            "read_path_id": None,
            "compute_impl": "independent",
            "writer": "batch_driver",
            "writer_path_id": "batch_driver",
            "path_id_source": "fetch_side",
            "bytes": 10402,
            "records": 37,
            "observed_verdict": "NEG_CTRL_RED",
        },
        "expect": "READ_PATH_ABSENT_FLAGGED",
    },
    {
        "case_id": "R2-READ-PATH-ABSENT-FALSE-PASS",
        "receipt": {
            "kind": "readback_path_struct",
            "readback_path": None,
            "read_path_id": None,
            "compute_impl": "independent",
            "writer": "batch_driver",
            "writer_path_id": "batch_driver",
            "path_id_source": "fetch_side",
            "bytes": 10402,
            "records": 37,
            "observed_verdict": "PASS",
        },
        "expect": "READ_PATH_ABSENT",
    },
    {
        "case_id": "R3-SAME-PATH-HOMOLOGY",
        "receipt": {
            "kind": "readback_path_struct",
            "readback_path": "disk",
            "read_path_id": "disk",
            "compute_impl": "independent",
            "writer": "disk_writer",
            "writer_path_id": "disk",
            "path_id_source": "fetch_side",
            "observed_verdict": "NEG_CTRL_RED",
        },
        "expect": "SAME_PATH_HOMOLOGY_FLAGGED",
    },
    {
        "case_id": "R3-SAME-PATH-FALSE-PASS",
        "receipt": {
            "kind": "readback_path_struct",
            "readback_path": "disk",
            "read_path_id": "disk",
            "compute_impl": "independent",
            "writer": "disk_writer",
            "writer_path_id": "disk",
            "path_id_source": "fetch_side",
            "observed_verdict": "PASS",
        },
        "expect": "SAME_PATH_HOMOLOGY",
    },
    {
        "case_id": "PATH-ID-SUT-SELF",
        "receipt": {
            "kind": "readback_path_struct",
            "readback_path": "disk",
            "read_path_id": "disk",
            "compute_impl": "independent",
            "writer": "batch_driver",
            "writer_path_id": "batch_driver",
            "path_id_source": "sut_self",
            "observed_verdict": "PASS",
        },
        "expect": "PATH_ID_SUT_SELF_REPORTED",
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
        "version": "0.2",
        "credit": ["木木/Mumu", "WorkBuddy"],
        "total": len(FIXTURES),
        "passed": ok,
        "all_pass": ok == len(FIXTURES),
        "rows": rows,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if ok == len(FIXTURES) else 1


if __name__ == "__main__":
    sys.exit(main())
