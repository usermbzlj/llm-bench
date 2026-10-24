#!/usr/bin/env python3
"""WINDOW_PAIRING v0.4 — codebook_tamper_must_red + assertion_strength + identity_bind

Credit signal (EigenFlux 2026-10-24):
  李晨熙: 「不等于 ≠ 等于预注册」断言强度；「先后关系须再问同一次」
          （时序+同一性双约束；跨次拼接攻法）
  沈小楠: COVERAGE-SIGNER-BOUND — 身份维前置；改坏码表判决必须变；
          必失败臂扎在读数侧不在声明侧
  随风绿柳 / aue: gates 三态 Pass/Fail/Absent；unknown 轴保留

v0.3 retained (hollow_pass_repin H1–H7 + triad + vector reason).
v0.4 NEW arms:
  A1 ASSERT_NE_WEAK_FALSE_GREEN     — 「不等于原摘要」被任意副作用满足 → 假绿
  A2 ASSERT_EQ_PREREG_CATCHES       — 「等于预注册注入摘要」定位到具体注入 → 真红
  A3 CODEBOOK_TAMPER_MUST_RED       — 改坏码表任一声明格 → 判决必须变红（自检）
  A4 CODEBOOK_TAMPER_READSIDE       — 必失败臂扎读数侧；声明侧改写不算自证
  A5 CROSS_RUN_TEMPORAL_SPLICE      — 上轮冻结+本轮开始时序成立但跨次 → INCOMPARABLE/FAIL
  A6 IDENTITY_BIND_OK               — probe_instance_id+batch_no 同绑 → PASS
  A7 GATES_TRIAD_ABSENT             — 闸门字段缺席 → ABSENT（≠ FAIL、≠ PASS）
  A8 GATES_TRIAD_FAIL / PASS        — 观测到非法 / 观测到合格
  A9 SAMPLE_SET_ID_ISSUER_NOT_JUDGE — 样本集 id 由签发方写，裁判方不得自填
  A10 STALE_READ_SAME_BATCH         — 过期读须同 batch；跨批旧值 → STALE_CROSS_BATCH
  A11 SECONDARY_CODE_REQUIRED       — 主码不够定位时须带 secondary_codes
  A12 HALF_OPEN_INTERVAL            — [lo, hi) 边界：lo 含 hi 不含
  A13 RATIO_CONSTRAINT              — 比值约束（多数占比下限，非恒等 100%）
  A14 PRIORITY_TABLE                — 多码冲突时按优先级表取最高优先红

analyze_only. Stdlib only.
"""
from __future__ import annotations

import hashlib
import json
import sys
from typing import Any

REUSE_OK = frozenset({"FRESH", "REUSE", "STALE"})
GATE_STATE_OK = frozenset({"PASS", "FAIL", "ABSENT"})
DISPOSITION_OK = frozenset({"UNPROBED", "FAIL", "PASS", "INCOMPARABLE"})


def _norm(v: Any) -> str | None:
    if v is None or v == "":
        return None
    return str(v)


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


# ---------- A1/A2 assertion strength (李晨熙) ----------
def judge_assert_strength(row: dict[str, Any]) -> dict[str, Any]:
    mode = _norm(row.get("assert_mode"))  # NE_WEAK | EQ_PREREG
    original = _norm(row.get("original_digest"))
    current = _norm(row.get("current_digest"))
    prereg_inject = _norm(row.get("preregistered_inject_digest"))
    reported = _norm(row.get("reported_verdict"))

    if mode == "NE_WEAK":
        # 「不等于原摘要」——任意差异都过；副作用半改也会绿
        if original is None or current is None:
            return {
                "disposition": "UNPROBED",
                "reason_code": "ASSERT_DIGEST_ABSENT",
                "enter_pass_denom": False,
            }
        if current != original:
            # Weak assert "passes" (turns red on inequality) — but vendor may
            # claim PASS-on-injection-detected. The BAD case: any side-effect
            # difference is treated as successful injection catch.
            side_effect = bool(row.get("difference_is_side_effect"))
            if side_effect and reported in ("PASS", "CAUGHT"):
                return {
                    "disposition": "FAIL",
                    "reason_code": "ASSERT_NE_WEAK_FALSE_GREEN",
                    "enter_pass_denom": False,
                    "detail": {"note": "≠ excludes only exact-original; side-effect ≠ inject"},
                }
            return {
                "disposition": "PASS",
                "reason_code": "ASSERT_NE_TRIGGERED",
                "enter_pass_denom": True,
            }
        return {
            "disposition": "FAIL",
            "reason_code": "ASSERT_NE_NOT_TRIGGERED",
            "enter_pass_denom": False,
        }

    if mode == "EQ_PREREG":
        # Empty string is an OBSERVED empty digest (cleared), not field-absent.
        current_key = "current_digest" in row
        prereg_key = "preregistered_inject_digest" in row
        if not prereg_key or not current_key:
            return {
                "disposition": "UNPROBED",
                "reason_code": "ASSERT_PREREG_ABSENT",
                "enter_pass_denom": False,
            }
        # Normalize empty → "" sentinel for comparison (observed empty ≠ absent)
        cur_raw = row.get("current_digest")
        preg_raw = row.get("preregistered_inject_digest")
        cur_s = "" if cur_raw is None else str(cur_raw)
        preg_s = "" if preg_raw is None else str(preg_raw)
        if cur_s == preg_s and cur_s != "":
            return {
                "disposition": "PASS",
                "reason_code": "ASSERT_EQ_PREREG_CATCHES",
                "enter_pass_denom": True,
                "detail": {"localized": True},
            }
        # Inject cleared / emptied but claimed as injected
        if row.get("inject_cleared_as_injected") or cur_s == "":
            return {
                "disposition": "FAIL",
                "reason_code": "ASSERT_INJECT_CLEARED_FALSE_INJECTED",
                "enter_pass_denom": False,
            }
        return {
            "disposition": "FAIL",
            "reason_code": "ASSERT_EQ_PREREG_MISS",
            "enter_pass_denom": False,
        }

    return {
        "disposition": "FAIL",
        "reason_code": "ASSERT_MODE_UNKNOWN",
        "enter_pass_denom": False,
    }


# ---------- A3/A4 codebook tamper must-red (李晨熙 + 沈小楠) ----------
def judge_codebook_tamper(row: dict[str, Any]) -> dict[str, Any]:
    """改坏码表即红：tamper any declared cell → verdict MUST change."""
    baseline_verdict = _norm(row.get("baseline_verdict"))
    after_verdict = _norm(row.get("after_tamper_verdict"))
    tamper_side = _norm(row.get("tamper_side"))  # declaration | read
    cell = _norm(row.get("tampered_cell"))

    if baseline_verdict is None or after_verdict is None or cell is None:
        return {
            "disposition": "UNPROBED",
            "reason_code": "CODEBOOK_TAMPER_FIELDS_ABSENT",
            "enter_pass_denom": False,
        }

    # A4: declaration-side-only rewrite does NOT count as self-check
    if tamper_side == "declaration":
        return {
            "disposition": "FAIL",
            "reason_code": "CODEBOOK_TAMPER_DECLARE_SIDE_NOT_SELFCHECK",
            "enter_pass_denom": False,
            "detail": {"cell": cell, "note": "must-fail arm must land on read side"},
        }

    if tamper_side != "read":
        return {
            "disposition": "FAIL",
            "reason_code": "CODEBOOK_TAMPER_SIDE_UNKNOWN",
            "enter_pass_denom": False,
        }

    # A3: after read-side tamper, verdict MUST differ from baseline
    if after_verdict == baseline_verdict:
        return {
            "disposition": "FAIL",
            "reason_code": "CODEBOOK_TAMPER_VERDICT_UNCHANGED",
            "enter_pass_denom": False,
            "detail": {"cell": cell, "verdict": baseline_verdict},
        }
    return {
        "disposition": "PASS",
        "reason_code": "CODEBOOK_TAMPER_MUST_RED",
        "enter_pass_denom": True,
        "detail": {"cell": cell, "before": baseline_verdict, "after": after_verdict},
    }


# ---------- A5/A6 temporal + identity bind (李晨熙) ----------
def judge_temporal_identity(row: dict[str, Any]) -> dict[str, Any]:
    frozen_at = row.get("frozen_at")
    run_started_at = row.get("run_started_at")
    freeze_batch = _norm(row.get("freeze_batch_no"))
    freeze_inst = _norm(row.get("freeze_probe_instance_id"))
    run_batch = _norm(row.get("run_batch_no"))
    run_inst = _norm(row.get("run_probe_instance_id"))

    if frozen_at is None or run_started_at is None:
        return {
            "disposition": "UNPROBED",
            "reason_code": "TEMPORAL_FIELDS_ABSENT",
            "enter_pass_denom": False,
        }

    # Temporal order alone
    order_ok = frozen_at <= run_started_at

    # Identity: same batch + same instance
    same_batch = freeze_batch is not None and freeze_batch == run_batch
    same_inst = freeze_inst is not None and freeze_inst == run_inst
    identity_ok = same_batch and same_inst

    if order_ok and not identity_ok:
        # Classic cross-run splice: timestamps order OK, different run
        return {
            "disposition": "FAIL",
            "reason_code": "CROSS_RUN_TEMPORAL_SPLICE",
            "enter_pass_denom": False,
            "detail": {
                "order_ok": True,
                "freeze_batch": freeze_batch,
                "run_batch": run_batch,
                "freeze_inst": freeze_inst,
                "run_inst": run_inst,
            },
        }

    if not order_ok:
        return {
            "disposition": "FAIL",
            "reason_code": "TEMPORAL_ORDER_VIOLATION",
            "enter_pass_denom": False,
        }

    if identity_ok and order_ok:
        # Writers of time vs batch must be separated (declared)
        time_writer = _norm(row.get("time_writer"))
        batch_writer = _norm(row.get("batch_writer"))
        if time_writer and batch_writer and time_writer == batch_writer:
            return {
                "disposition": "FAIL",
                "reason_code": "TIME_BATCH_WRITER_NOT_SEPARATED",
                "enter_pass_denom": False,
            }
        return {
            "disposition": "PASS",
            "reason_code": "IDENTITY_BIND_OK",
            "enter_pass_denom": True,
        }

    return {
        "disposition": "INCOMPARABLE",
        "reason_code": "TEMPORAL_IDENTITY_INCOMPARABLE",
        "enter_pass_denom": False,
    }


# ---------- A7/A8 gates triad ----------
def judge_gates_triad(row: dict[str, Any]) -> dict[str, Any]:
    if "gate_state" not in row:
        return {
            "disposition": "UNPROBED",
            "reason_code": "GATES_TRIAD_ABSENT",
            "enter_pass_denom": False,
            "gate_form": "ABSENT",
        }
    state = _norm(row.get("gate_state"))
    if state == "ABSENT":
        return {
            "disposition": "UNPROBED",
            "reason_code": "GATES_TRIAD_ABSENT",
            "enter_pass_denom": False,
            "gate_form": "ABSENT",
        }
    if state == "FAIL":
        return {
            "disposition": "FAIL",
            "reason_code": "GATES_TRIAD_FAIL",
            "enter_pass_denom": False,
            "gate_form": "FAIL",
        }
    if state == "PASS":
        return {
            "disposition": "PASS",
            "reason_code": "GATES_TRIAD_PASS",
            "enter_pass_denom": True,
            "gate_form": "PASS",
        }
    return {
        "disposition": "FAIL",
        "reason_code": "GATES_TRIAD_OUT_OF_CLOSET",
        "enter_pass_denom": False,
        "gate_form": state,
    }


# ---------- A9 sample_set_id issuer not judge ----------
def judge_sample_set_issuer(row: dict[str, Any]) -> dict[str, Any]:
    sample_set_id = _norm(row.get("sample_set_id"))
    issuer = _norm(row.get("sample_set_issuer"))
    judge_party = _norm(row.get("judge_party"))
    filled_by = _norm(row.get("sample_set_id_filled_by"))

    if sample_set_id is None:
        return {
            "disposition": "UNPROBED",
            "reason_code": "SAMPLE_SET_ID_ABSENT",
            "enter_pass_denom": False,
        }
    if filled_by == judge_party and judge_party is not None:
        return {
            "disposition": "FAIL",
            "reason_code": "SAMPLE_SET_ID_ISSUER_NOT_JUDGE",
            "enter_pass_denom": False,
            "detail": {"filled_by": filled_by, "issuer": issuer},
        }
    if issuer and filled_by == issuer:
        return {
            "disposition": "PASS",
            "reason_code": "SAMPLE_SET_ID_ISSUER_OK",
            "enter_pass_denom": True,
        }
    return {
        "disposition": "FAIL",
        "reason_code": "SAMPLE_SET_ID_ISSUER_MISMATCH",
        "enter_pass_denom": False,
    }


# ---------- A10 stale read same batch ----------
def judge_stale_read(row: dict[str, Any]) -> dict[str, Any]:
    value_batch = _norm(row.get("value_batch_no"))
    read_batch = _norm(row.get("read_batch_no"))
    is_stale = bool(row.get("value_is_stale"))
    reported = _norm(row.get("reported_verdict"))

    if value_batch is None or read_batch is None:
        return {
            "disposition": "UNPROBED",
            "reason_code": "STALE_READ_BATCH_ABSENT",
            "enter_pass_denom": False,
        }
    if value_batch != read_batch and is_stale:
        if reported in ("PASS", "FRESH", "OK"):
            return {
                "disposition": "FAIL",
                "reason_code": "STALE_CROSS_BATCH_FALSE_FRESH",
                "enter_pass_denom": False,
            }
        return {
            "disposition": "PASS",
            "reason_code": "STALE_CROSS_BATCH_CAUGHT",
            "enter_pass_denom": True,
        }
    if value_batch == read_batch and not is_stale:
        return {
            "disposition": "PASS",
            "reason_code": "STALE_READ_SAME_BATCH_OK",
            "enter_pass_denom": True,
        }
    return {
        "disposition": "FAIL",
        "reason_code": "STALE_READ_INCONSISTENT",
        "enter_pass_denom": False,
    }


# ---------- A11 secondary_codes ----------
def judge_secondary_codes(row: dict[str, Any]) -> dict[str, Any]:
    primary = _norm(row.get("primary_reason_code"))
    secondary = row.get("secondary_codes")
    needs_secondary = bool(row.get("needs_localization"))

    if primary is None:
        return {
            "disposition": "UNPROBED",
            "reason_code": "PRIMARY_CODE_ABSENT",
            "enter_pass_denom": False,
        }
    if needs_secondary:
        if not isinstance(secondary, list) or len(secondary) == 0:
            return {
                "disposition": "FAIL",
                "reason_code": "SECONDARY_CODE_REQUIRED",
                "enter_pass_denom": False,
            }
        return {
            "disposition": "PASS",
            "reason_code": "SECONDARY_CODES_PRESENT",
            "enter_pass_denom": True,
            "detail": {"secondary": secondary},
        }
    return {
        "disposition": "PASS",
        "reason_code": "PRIMARY_SUFFICIENT",
        "enter_pass_denom": True,
    }


# ---------- A12 half-open interval [lo, hi) ----------
def judge_half_open(row: dict[str, Any]) -> dict[str, Any]:
    lo = row.get("lo")
    hi = row.get("hi")
    x = row.get("x")
    reported_in = row.get("reported_in_interval")

    if lo is None or hi is None or x is None or reported_in is None:
        return {
            "disposition": "UNPROBED",
            "reason_code": "HALF_OPEN_FIELDS_ABSENT",
            "enter_pass_denom": False,
        }
    actual_in = lo <= x < hi
    if actual_in != bool(reported_in):
        return {
            "disposition": "FAIL",
            "reason_code": "HALF_OPEN_BOUNDARY_MISMATCH",
            "enter_pass_denom": False,
            "detail": {"lo": lo, "hi": hi, "x": x, "actual_in": actual_in},
        }
    return {
        "disposition": "PASS",
        "reason_code": "HALF_OPEN_INTERVAL_OK",
        "enter_pass_denom": True,
        "detail": {"in": actual_in},
    }


# ---------- A13 ratio constraint (majority floor, not 100%) ----------
def judge_ratio(row: dict[str, Any]) -> dict[str, Any]:
    hits = row.get("hits")
    trials = row.get("trials")
    floor = row.get("majority_floor")  # e.g. 0.7
    claimed_certainty = row.get("claimed_certainty")  # e.g. 1.0

    if hits is None or trials is None or floor is None:
        return {
            "disposition": "UNPROBED",
            "reason_code": "RATIO_FIELDS_ABSENT",
            "enter_pass_denom": False,
        }
    if trials <= 0:
        return {
            "disposition": "FAIL",
            "reason_code": "RATIO_TRIALS_NONPOSITIVE",
            "enter_pass_denom": False,
        }
    ratio = hits / trials
    if claimed_certainty is not None and claimed_certainty >= 1.0 and ratio < 1.0:
        return {
            "disposition": "FAIL",
            "reason_code": "RATIO_CLAIMED_100_BUT_SAMPLE",
            "enter_pass_denom": False,
            "detail": {"ratio": ratio, "floor": floor},
        }
    if ratio < floor:
        return {
            "disposition": "FAIL",
            "reason_code": "RATIO_BELOW_FLOOR",
            "enter_pass_denom": False,
            "detail": {"ratio": ratio, "floor": floor},
        }
    return {
        "disposition": "PASS",
        "reason_code": "RATIO_CONSTRAINT_OK",
        "enter_pass_denom": True,
        "detail": {"ratio": ratio, "floor": floor},
    }


# ---------- A14 priority table ----------
PRIORITY_DEFAULT = {
    "CODEBOOK_TAMPER_VERDICT_UNCHANGED": 100,
    "CROSS_RUN_TEMPORAL_SPLICE": 90,
    "SAMPLE_SET_ID_ISSUER_NOT_JUDGE": 80,
    "ASSERT_NE_WEAK_FALSE_GREEN": 70,
    "STALE_CROSS_BATCH_FALSE_FRESH": 60,
    "GATES_TRIAD_FAIL": 50,
    "SECONDARY_CODE_REQUIRED": 40,
}


def judge_priority(row: dict[str, Any]) -> dict[str, Any]:
    codes = row.get("candidate_reason_codes")
    table = row.get("priority_table") or PRIORITY_DEFAULT
    expected_winner = _norm(row.get("expected_winner"))

    if not isinstance(codes, list) or not codes:
        return {
            "disposition": "UNPROBED",
            "reason_code": "PRIORITY_CANDIDATES_ABSENT",
            "enter_pass_denom": False,
        }
    ranked = sorted(
        codes,
        key=lambda c: (-int(table.get(c, 0)), c),
    )
    winner = ranked[0]
    if expected_winner and winner != expected_winner:
        return {
            "disposition": "FAIL",
            "reason_code": "PRIORITY_TABLE_MISPICK",
            "enter_pass_denom": False,
            "detail": {"got": winner, "expected": expected_winner, "ranked": ranked},
        }
    return {
        "disposition": "PASS",
        "reason_code": "PRIORITY_TABLE_OK",
        "enter_pass_denom": True,
        "detail": {"winner": winner, "ranked": ranked},
    }


DISPATCH = {
    "assert_strength": judge_assert_strength,
    "codebook_tamper": judge_codebook_tamper,
    "temporal_identity": judge_temporal_identity,
    "gates_triad": judge_gates_triad,
    "sample_set_issuer": judge_sample_set_issuer,
    "stale_read": judge_stale_read,
    "secondary_codes": judge_secondary_codes,
    "half_open": judge_half_open,
    "ratio": judge_ratio,
    "priority": judge_priority,
}


CASES: list[dict[str, Any]] = [
    # A1 NE weak false green
    {
        "case_id": "A1_ne_weak_side_effect_false_green",
        "arm": "assert_strength",
        "assert_mode": "NE_WEAK",
        "original_digest": "aaa",
        "current_digest": "aab",  # one-byte side effect
        "difference_is_side_effect": True,
        "reported_verdict": "CAUGHT",
        "expect_disposition": "FAIL",
        "expect_reason": "ASSERT_NE_WEAK_FALSE_GREEN",
    },
    # A2 EQ prereg catches
    {
        "case_id": "A2_eq_prereg_catches_inject",
        "arm": "assert_strength",
        "assert_mode": "EQ_PREREG",
        "original_digest": "aaa",
        "current_digest": "inj01",
        "preregistered_inject_digest": "inj01",
        "expect_disposition": "PASS",
        "expect_reason": "ASSERT_EQ_PREREG_CATCHES",
    },
    # A2b inject cleared treated as injected
    {
        "case_id": "A2b_inject_cleared_as_injected",
        "arm": "assert_strength",
        "assert_mode": "EQ_PREREG",
        "current_digest": "",
        "preregistered_inject_digest": "inj01",
        "inject_cleared_as_injected": True,
        "expect_disposition": "FAIL",
        "expect_reason": "ASSERT_INJECT_CLEARED_FALSE_INJECTED",
    },
    # A3 codebook tamper must red (read side)
    {
        "case_id": "A3_codebook_tamper_must_red",
        "arm": "codebook_tamper",
        "baseline_verdict": "PASS",
        "after_tamper_verdict": "FAIL",
        "tamper_side": "read",
        "tampered_cell": "reason_code_table.ENTRY_X",
        "expect_disposition": "PASS",
        "expect_reason": "CODEBOOK_TAMPER_MUST_RED",
    },
    # A3b unchanged after tamper → FAIL
    {
        "case_id": "A3b_codebook_tamper_verdict_unchanged",
        "arm": "codebook_tamper",
        "baseline_verdict": "PASS",
        "after_tamper_verdict": "PASS",
        "tamper_side": "read",
        "tampered_cell": "reason_code_table.ENTRY_Y",
        "expect_disposition": "FAIL",
        "expect_reason": "CODEBOOK_TAMPER_VERDICT_UNCHANGED",
    },
    # A4 declaration side not self-check
    {
        "case_id": "A4_codebook_tamper_declare_side",
        "arm": "codebook_tamper",
        "baseline_verdict": "PASS",
        "after_tamper_verdict": "FAIL",
        "tamper_side": "declaration",
        "tampered_cell": "META.summary",
        "expect_disposition": "FAIL",
        "expect_reason": "CODEBOOK_TAMPER_DECLARE_SIDE_NOT_SELFCHECK",
    },
    # A5 cross-run temporal splice
    {
        "case_id": "A5_cross_run_temporal_splice",
        "arm": "temporal_identity",
        "frozen_at": 1000,
        "run_started_at": 2000,
        "freeze_batch_no": "B1",
        "freeze_probe_instance_id": "P1",
        "run_batch_no": "B2",
        "run_probe_instance_id": "P2",
        "expect_disposition": "FAIL",
        "expect_reason": "CROSS_RUN_TEMPORAL_SPLICE",
    },
    # A6 identity bind OK with separated writers
    {
        "case_id": "A6_identity_bind_ok",
        "arm": "temporal_identity",
        "frozen_at": 1000,
        "run_started_at": 2000,
        "freeze_batch_no": "B9",
        "freeze_probe_instance_id": "P9",
        "run_batch_no": "B9",
        "run_probe_instance_id": "P9",
        "time_writer": "scheduler",
        "batch_writer": "issuer",
        "expect_disposition": "PASS",
        "expect_reason": "IDENTITY_BIND_OK",
    },
    # A6b same writer → FAIL
    {
        "case_id": "A6b_time_batch_writer_not_separated",
        "arm": "temporal_identity",
        "frozen_at": 1000,
        "run_started_at": 2000,
        "freeze_batch_no": "B9",
        "freeze_probe_instance_id": "P9",
        "run_batch_no": "B9",
        "run_probe_instance_id": "P9",
        "time_writer": "same_party",
        "batch_writer": "same_party",
        "expect_disposition": "FAIL",
        "expect_reason": "TIME_BATCH_WRITER_NOT_SEPARATED",
    },
    # A7 gates absent
    {
        "case_id": "A7_gates_triad_absent",
        "arm": "gates_triad",
        # gate_state key omitted
        "expect_disposition": "UNPROBED",
        "expect_reason": "GATES_TRIAD_ABSENT",
    },
    # A8a FAIL
    {
        "case_id": "A8a_gates_triad_fail",
        "arm": "gates_triad",
        "gate_state": "FAIL",
        "expect_disposition": "FAIL",
        "expect_reason": "GATES_TRIAD_FAIL",
    },
    # A8b PASS
    {
        "case_id": "A8b_gates_triad_pass",
        "arm": "gates_triad",
        "gate_state": "PASS",
        "expect_disposition": "PASS",
        "expect_reason": "GATES_TRIAD_PASS",
    },
    # A9 issuer not judge
    {
        "case_id": "A9_sample_set_id_issuer_not_judge",
        "arm": "sample_set_issuer",
        "sample_set_id": "SS-42",
        "sample_set_issuer": "issuer_A",
        "judge_party": "judge_B",
        "sample_set_id_filled_by": "judge_B",
        "expect_disposition": "FAIL",
        "expect_reason": "SAMPLE_SET_ID_ISSUER_NOT_JUDGE",
    },
    # A9b OK
    {
        "case_id": "A9b_sample_set_id_issuer_ok",
        "arm": "sample_set_issuer",
        "sample_set_id": "SS-42",
        "sample_set_issuer": "issuer_A",
        "judge_party": "judge_B",
        "sample_set_id_filled_by": "issuer_A",
        "expect_disposition": "PASS",
        "expect_reason": "SAMPLE_SET_ID_ISSUER_OK",
    },
    # A10 stale cross batch false fresh
    {
        "case_id": "A10_stale_cross_batch_false_fresh",
        "arm": "stale_read",
        "value_batch_no": "B1",
        "read_batch_no": "B2",
        "value_is_stale": True,
        "reported_verdict": "FRESH",
        "expect_disposition": "FAIL",
        "expect_reason": "STALE_CROSS_BATCH_FALSE_FRESH",
    },
    # A10b same batch OK
    {
        "case_id": "A10b_stale_read_same_batch_ok",
        "arm": "stale_read",
        "value_batch_no": "B3",
        "read_batch_no": "B3",
        "value_is_stale": False,
        "reported_verdict": "OK",
        "expect_disposition": "PASS",
        "expect_reason": "STALE_READ_SAME_BATCH_OK",
    },
    # A11 secondary required
    {
        "case_id": "A11_secondary_code_required",
        "arm": "secondary_codes",
        "primary_reason_code": "EMPTY_GATES_UNOBSERVED",
        "needs_localization": True,
        "secondary_codes": [],
        "expect_disposition": "FAIL",
        "expect_reason": "SECONDARY_CODE_REQUIRED",
    },
    # A11b present
    {
        "case_id": "A11b_secondary_codes_present",
        "arm": "secondary_codes",
        "primary_reason_code": "EMPTY_GATES_UNOBSERVED",
        "needs_localization": True,
        "secondary_codes": ["REUSE_STATE_ABSENT"],
        "expect_disposition": "PASS",
        "expect_reason": "SECONDARY_CODES_PRESENT",
    },
    # A12 half-open: x==hi should be OUT
    {
        "case_id": "A12_half_open_hi_exclusive",
        "arm": "half_open",
        "lo": 0,
        "hi": 10,
        "x": 10,
        "reported_in_interval": True,  # wrong — hi exclusive
        "expect_disposition": "FAIL",
        "expect_reason": "HALF_OPEN_BOUNDARY_MISMATCH",
    },
    # A12b lo inclusive
    {
        "case_id": "A12b_half_open_lo_inclusive",
        "arm": "half_open",
        "lo": 0,
        "hi": 10,
        "x": 0,
        "reported_in_interval": True,
        "expect_disposition": "PASS",
        "expect_reason": "HALF_OPEN_INTERVAL_OK",
    },
    # A13 ratio claimed 100% but sample
    {
        "case_id": "A13_ratio_claimed_100_but_sample",
        "arm": "ratio",
        "hits": 7,
        "trials": 10,
        "majority_floor": 0.7,
        "claimed_certainty": 1.0,
        "expect_disposition": "FAIL",
        "expect_reason": "RATIO_CLAIMED_100_BUT_SAMPLE",
    },
    # A13b OK at floor
    {
        "case_id": "A13b_ratio_constraint_ok",
        "arm": "ratio",
        "hits": 7,
        "trials": 10,
        "majority_floor": 0.7,
        "claimed_certainty": 0.7,
        "expect_disposition": "PASS",
        "expect_reason": "RATIO_CONSTRAINT_OK",
    },
    # A14 priority
    {
        "case_id": "A14_priority_table_ok",
        "arm": "priority",
        "candidate_reason_codes": [
            "GATES_TRIAD_FAIL",
            "CODEBOOK_TAMPER_VERDICT_UNCHANGED",
            "SECONDARY_CODE_REQUIRED",
        ],
        "expected_winner": "CODEBOOK_TAMPER_VERDICT_UNCHANGED",
        "expect_disposition": "PASS",
        "expect_reason": "PRIORITY_TABLE_OK",
    },
]


def batch_digest(rows: list[dict[str, Any]]) -> str:
    tuples = []
    for r in rows:
        tuples.append(
            (
                r["case_id"],
                r["got"]["reason_code"],
                r["expect_reason"],
                r["got"]["disposition"],
            )
        )
    tuples.sort(key=lambda t: t[0])
    canon = json.dumps(tuples, separators=(",", ":")).encode()
    return hashlib.sha256(canon).hexdigest()


def run_all() -> dict[str, Any]:
    results = []
    n_ok = 0
    for case in CASES:
        fn = DISPATCH[case["arm"]]
        got = fn(case)
        ok = (
            got.get("disposition") == case["expect_disposition"]
            and got.get("reason_code") == case["expect_reason"]
        )
        if ok:
            n_ok += 1
        results.append(
            {
                "case_id": case["case_id"],
                "ok": ok,
                "expect_disposition": case["expect_disposition"],
                "expect_reason": case["expect_reason"],
                "got": got,
            }
        )

    codes = [r["got"]["reason_code"] for r in results]
    self_check = {
        "n_cases": len(results) == len(CASES),
        "all_cases_ok": n_ok == len(CASES),
        "has_codebook_tamper_must_red": "CODEBOOK_TAMPER_MUST_RED"
        in {r["got"]["reason_code"] for r in results if r["ok"]},
        "has_cross_run_splice": any(
            r["got"]["reason_code"] == "CROSS_RUN_TEMPORAL_SPLICE" for r in results
        ),
        "has_assert_strength_pair": (
            "ASSERT_NE_WEAK_FALSE_GREEN" in codes and "ASSERT_EQ_PREREG_CATCHES" in codes
        ),
        "gates_three_forms": {"GATES_TRIAD_ABSENT", "GATES_TRIAD_FAIL", "GATES_TRIAD_PASS"}.issubset(
            set(codes)
        ),
    }
    self_check["all_pass"] = all(self_check.values())

    digest = batch_digest(
        [
            {
                "case_id": r["case_id"],
                "got": r["got"],
                "expect_reason": r["expect_reason"],
            }
            for r in results
        ]
    )

    payload = {
        "fixture": "WINDOW_PAIRING",
        "version": "v0.4",
        "variant": "codebook_tamper_must_red",
        "total": len(CASES),
        "passed": n_ok,
        "failed": len(CASES) - n_ok,
        "results": results,
        "self_check": self_check,
        "batch_digest_sha256": digest,
        "credit": [
            "李晨熙 (assert NE≠EQ-prereg; temporal+identity; codebook tamper)",
            "沈小楠 (signer identity-first; must-fail on read side)",
            "随风绿柳 / aue (gates triad + unknown axis)",
            "Grok Bot (impl)",
        ],
        "arms": [
            "ASSERT_NE_WEAK_FALSE_GREEN",
            "ASSERT_EQ_PREREG_CATCHES",
            "CODEBOOK_TAMPER_MUST_RED",
            "CODEBOOK_TAMPER_DECLARE_SIDE_NOT_SELFCHECK",
            "CROSS_RUN_TEMPORAL_SPLICE",
            "IDENTITY_BIND_OK",
            "GATES_TRIAD_{ABSENT,FAIL,PASS}",
            "SAMPLE_SET_ID_ISSUER_NOT_JUDGE",
            "STALE_CROSS_BATCH / SAME_BATCH",
            "SECONDARY_CODE_REQUIRED",
            "HALF_OPEN_INTERVAL",
            "RATIO_CONSTRAINT",
            "PRIORITY_TABLE",
        ],
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["run_out_sha256"] = hashlib.sha256(blob).hexdigest()
    return payload


def main() -> int:
    out = run_all()
    with open(__file__, "rb") as f:
        out["script_sha256"] = hashlib.sha256(f.read()).hexdigest()
    json.dump(out, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    if not out["self_check"]["all_pass"] or out["failed"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
