#!/usr/bin/env python3
"""WINDOW_PAIRING v0.3 — hollow_pass_repin

Structure from 李晨熙 (EigenFlux 2026-10-24 hollow_pass_repin_v1 PM):
7 hollow_pass rows that v0.1 falsely marked PASS HONEST_* must be re-pinned
to UNPROBED or FAIL — never PASS. Core iron rules:

  1. UNPROBED = arm/cell never observed (field absent / empty set / defaulted)
     → 可判, but NOT in pass denom, NOT in independent evidence pool
  2. FAIL = observed illegal value (closed-set violation)
  3. PASS = genuinely observed qualified value
  4. Field-absent vs field-present-at-default MUST be distinct reason_codes
     (未观测 ≠ 观测到默认值); dispositions diverge (补观测 vs 改判据)
  5. Vector-level reason_code required in META (arm-layer coarse code alone
     cannot do expected⊆errors containment against fine codes)
  6. run_out triad binding in preimage (not META side-note):
     input_window_id + normalization_rule_version + criteria_version
     — side-notes can be filled post-hoc without re-run; preimage cannot
  7. NOT_COMPARABLE (forced / not_translatable) excluded from both pass and
     diff denoms, but counted in a dedicated ledger cell

Seven hollow rows (vendor_arm / expected_code / disposition):
  H1 write_at_key_fetch empty windows → EMPTY_WINDOW_SET_UNOBSERVED / UNPROBED
  H2 write_at_key_fetch fields absent → WINDOW_FIELDS_ABSENT / UNPROBED
  H3 unpaired_parallel empty list → UNPAIRED_LIST_EMPTY / UNPROBED
  H4 unpaired_parallel no list field → UNPAIRED_LIST_ABSENT / UNPROBED
  H5 stale_three_gate all defaults → GATE_VALUES_DEFAULTED_NOT_OBSERVED / UNPROBED
  H6 stale_three_gate unknown reuse → REUSE_STATE_OUT_OF_CLOSET / FAIL
  H7 stale_three_gate missing reuse → REUSE_STATE_ABSENT / UNPROBED

Self-check (李晨熙 6-item): 7 rows / codes mutually distinct / zero PASS /
UNPROBED not in pass denom / disposition closed {UNPROBED,FAIL} / exactly 1 FAIL.

Families: empty-payload-observed (6 codes) | closed-set-violation (1 code).

analyze_only. Stdlib only.
Credit: 李晨熙 (hollow_pass_repin_v1 shape + 7-row table + iron rules);
        Grok Bot (impl).
"""
from __future__ import annotations

import hashlib
import json
import sys
from typing import Any

REUSE_OK = frozenset({"FRESH", "REUSE", "STALE"})
DISPOSITION_OK = frozenset({"UNPROBED", "FAIL", "PASS"})
GATE_NAMES = ("ttl", "downstream_confirm", "reuse_state")
TRIAD_KEYS = ("input_window_id", "normalization_rule_version", "criteria_version")


def _norm(v: Any) -> str | None:
    if v is None or v == "":
        return None
    return str(v)


def _defaulted(v: Any, default: Any) -> bool:
    """True when field is present AND equal to its declared default."""
    return v is not None and v == default


def judge_hollow(row: dict[str, Any]) -> dict[str, Any]:
    """Judge one hollow_pass row. Returns disposition + reason_code."""
    arm = _norm(row.get("vendor_arm"))
    reported = _norm(row.get("reported_verdict"))  # vendor's original PASS claim

    # --- H1/H2: write_at_key_fetch ---
    if arm == "write_at_key_fetch":
        # Distinguish: fields absent vs fields present-as-empty-set
        writes_key = "writes" in row
        reads_key = "reads" in row
        if not writes_key and not reads_key:
            return {
                "disposition": "UNPROBED",
                "reason_code": "WINDOW_FIELDS_ABSENT",
                "enter_pass_denom": False,
                "enter_evidence_pool": False,
            }
        writes = row.get("writes")
        reads = row.get("reads")
        # Present and empty set → EMPTY_WINDOW_SET_UNOBSERVED
        if writes_key and reads_key and writes == [] and reads == []:
            return {
                "disposition": "UNPROBED",
                "reason_code": "EMPTY_WINDOW_SET_UNOBSERVED",
                "enter_pass_denom": False,
                "enter_evidence_pool": False,
            }
        # One side absent while other present → still fields-absent family
        if not writes_key or not reads_key:
            return {
                "disposition": "UNPROBED",
                "reason_code": "WINDOW_FIELDS_ABSENT",
                "enter_pass_denom": False,
                "enter_evidence_pool": False,
            }
        # Honest paired case (not hollow)
        if reported in ("PASS", "FAIL"):
            return {
                "disposition": "PASS",
                "reason_code": "HONEST_PAIRING",
                "enter_pass_denom": True,
                "enter_evidence_pool": True,
            }
        return {
            "disposition": "FAIL",
            "reason_code": "REPORTED_VERDICT_MISSING",
            "enter_pass_denom": False,
            "enter_evidence_pool": False,
        }

    # --- H3/H4: unpaired_parallel ---
    if arm == "unpaired_parallel":
        if "unpaired_list" not in row:
            return {
                "disposition": "UNPROBED",
                "reason_code": "UNPAIRED_LIST_ABSENT",
                "enter_pass_denom": False,
                "enter_evidence_pool": False,
            }
        ul = row.get("unpaired_list")
        if ul == [] or ul == {}:
            return {
                "disposition": "UNPROBED",
                "reason_code": "UNPAIRED_LIST_EMPTY",
                "enter_pass_denom": False,
                "enter_evidence_pool": False,
            }
        if reported in ("PASS", "FAIL"):
            return {
                "disposition": "PASS",
                "reason_code": "HONEST_UNPAIRED_PARALLEL",
                "enter_pass_denom": True,
                "enter_evidence_pool": True,
            }
        return {
            "disposition": "FAIL",
            "reason_code": "REPORTED_VERDICT_MISSING",
            "enter_pass_denom": False,
            "enter_evidence_pool": False,
        }

    # --- H5/H6/H7: stale_three_gate ---
    if arm == "stale_three_gate":
        gates = row.get("gates")
        # Whole gates object absent
        if "gates" not in row or gates is None:
            return {
                "disposition": "UNPROBED",
                "reason_code": "GATE_VALUES_DEFAULTED_NOT_OBSERVED",
                "enter_pass_denom": False,
                "enter_evidence_pool": False,
                "detail": {"why": "gates_object_absent"},
            }
        if not isinstance(gates, dict):
            return {
                "disposition": "FAIL",
                "reason_code": "GATES_SHAPE_INVALID",
                "enter_pass_denom": False,
                "enter_evidence_pool": False,
            }

        defaults = row.get("gate_defaults") or {
            "ttl": 0,
            "downstream_confirm": False,
            "reuse_state": "FRESH",
        }

        # Per-gate: absent vs defaulted vs observed
        reuse_present = "reuse_state" in gates
        reuse_val = _norm(gates.get("reuse_state")) if reuse_present else None

        # H7: reuse_state field absent (other gates may be present)
        if not reuse_present:
            return {
                "disposition": "UNPROBED",
                "reason_code": "REUSE_STATE_ABSENT",
                "enter_pass_denom": False,
                "enter_evidence_pool": False,
                "detail": {
                    "present_gates": sorted(gates.keys()),
                    "note": "arm-layer EMPTY_GATES_UNOBSERVED is coarse; this code localizes to reuse_state",
                },
            }

        # H6: reuse_state present but out of closed set → FAIL (observed illegal)
        if reuse_val not in REUSE_OK:
            return {
                "disposition": "FAIL",
                "reason_code": "REUSE_STATE_OUT_OF_CLOSET",
                "enter_pass_denom": False,
                "enter_evidence_pool": True,  # observed illegal is evidence
                "detail": {"reuse_state": reuse_val},
            }

        # H5: all three gates present AND equal to defaults → DEFAULTED_NOT_OBSERVED
        # (distinct from absent!)
        all_defaulted = True
        for g in GATE_NAMES:
            if g not in gates:
                all_defaulted = False
                break
            if not _defaulted(gates.get(g), defaults.get(g)):
                all_defaulted = False
                break
        if all_defaulted:
            return {
                "disposition": "UNPROBED",
                "reason_code": "GATE_VALUES_DEFAULTED_NOT_OBSERVED",
                "enter_pass_denom": False,
                "enter_evidence_pool": False,
                "detail": {"defaults": defaults},
            }

        # Honest observed non-default clear
        if reported in ("PASS", "FAIL"):
            return {
                "disposition": "PASS",
                "reason_code": "HONEST_STALE_CLEAR",
                "enter_pass_denom": True,
                "enter_evidence_pool": True,
            }
        return {
            "disposition": "FAIL",
            "reason_code": "REPORTED_VERDICT_MISSING",
            "enter_pass_denom": False,
            "enter_evidence_pool": False,
        }

    return {
        "disposition": "FAIL",
        "reason_code": "UNKNOWN_VENDOR_ARM",
        "enter_pass_denom": False,
        "enter_evidence_pool": False,
    }


def check_run_out_triad(meta: dict[str, Any]) -> dict[str, Any]:
    """run_out triad must bind in preimage, not META side-note."""
    preimage = meta.get("preimage_binding") or {}
    side = meta.get("side_notes") or {}
    missing = [k for k in TRIAD_KEYS if _norm(preimage.get(k)) is None]
    if missing:
        # If only in side_notes → reject (fillable post-hoc without re-run)
        in_side = [k for k in missing if _norm(side.get(k)) is not None]
        return {
            "ok": False,
            "reason_code": "RUN_OUT_TRIAD_NOT_IN_PREIMAGE",
            "missing_preimage": missing,
            "present_only_as_side_note": in_side,
        }
    return {
        "ok": True,
        "reason_code": "RUN_OUT_TRIAD_BOUND",
        "triad": {k: preimage[k] for k in TRIAD_KEYS},
    }


def check_vector_reason_meta(meta: dict[str, Any]) -> dict[str, Any]:
    """Vector-level reason_code table required; arm-layer alone insufficient."""
    table = meta.get("reason_code_table")
    granularity = _norm(meta.get("reason_code_granularity"))
    if not isinstance(table, dict) or not table:
        return {"ok": False, "reason_code": "REASON_CODE_TABLE_ABSENT"}
    if granularity != "vector-level":
        return {
            "ok": False,
            "reason_code": "REASON_CODE_ARM_LAYER_ONLY",
            "detail": {
                "granularity": granularity,
                "note": "arm-layer codes cannot do expected⊆errors vs fine codes",
            },
        }
    return {"ok": True, "reason_code": "VECTOR_REASON_META_OK", "n_codes": len(table)}


def check_not_comparable_ledger(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """NOT_COMPARABLE excluded from pass+diff denoms but must have a count cell."""
    nc = [r for r in rows if r.get("axis_alignment") == "not_translatable"]
    return {
        "not_comparable_count": len(nc),
        "in_pass_denom": False,
        "in_diff_denom": False,
        "ledger_cell_present": True,
        "reason_code": "NOT_COMPARABLE_LEDGERED",
    }


# --- Seven hollow rows from 李晨熙 hollow_pass_repin_v1 ---
HOLLOW_CASES: list[dict[str, Any]] = [
    {
        "case_id": "H1_arm1_write_at_key_fetch_both_empty",
        "vendor_arm": "write_at_key_fetch",
        "reported_verdict": "PASS",
        "writes": [],
        "reads": [],
        "expect_disposition": "UNPROBED",
        "expect_reason": "EMPTY_WINDOW_SET_UNOBSERVED",
    },
    {
        "case_id": "H2_arm1_write_at_key_fetch_fields_absent",
        "vendor_arm": "write_at_key_fetch",
        "reported_verdict": "PASS",
        # writes/reads keys deliberately omitted
        "expect_disposition": "UNPROBED",
        "expect_reason": "WINDOW_FIELDS_ABSENT",
    },
    {
        "case_id": "H3_arm4_unpaired_parallel_empty_windows",
        "vendor_arm": "unpaired_parallel",
        "reported_verdict": "PASS",
        "unpaired_list": [],
        "expect_disposition": "UNPROBED",
        "expect_reason": "UNPAIRED_LIST_EMPTY",
    },
    {
        "case_id": "H4_arm4_unpaired_parallel_no_list_field",
        "vendor_arm": "unpaired_parallel",
        "reported_verdict": "PASS",
        # unpaired_list key deliberately omitted
        "expect_disposition": "UNPROBED",
        "expect_reason": "UNPAIRED_LIST_ABSENT",
    },
    {
        "case_id": "H5_arm5_stale_three_gate_all_defaults",
        "vendor_arm": "stale_three_gate",
        "reported_verdict": "PASS",
        "gates": {"ttl": 0, "downstream_confirm": False, "reuse_state": "FRESH"},
        "gate_defaults": {"ttl": 0, "downstream_confirm": False, "reuse_state": "FRESH"},
        "expect_disposition": "UNPROBED",
        "expect_reason": "GATE_VALUES_DEFAULTED_NOT_OBSERVED",
    },
    {
        "case_id": "H6_arm5_stale_three_gate_unknown_reuse_state",
        "vendor_arm": "stale_three_gate",
        "reported_verdict": "PASS",
        "gates": {"ttl": 30, "downstream_confirm": True, "reuse_state": "CACHED"},
        "gate_defaults": {"ttl": 0, "downstream_confirm": False, "reuse_state": "FRESH"},
        "expect_disposition": "FAIL",
        "expect_reason": "REUSE_STATE_OUT_OF_CLOSET",
    },
    {
        "case_id": "H7_arm5_stale_three_gate_missing_reuse_state",
        "vendor_arm": "stale_three_gate",
        "reported_verdict": "PASS",
        "gates": {"ttl": 30, "downstream_confirm": True},  # reuse_state absent
        "gate_defaults": {"ttl": 0, "downstream_confirm": False, "reuse_state": "FRESH"},
        "expect_disposition": "UNPROBED",
        "expect_reason": "REUSE_STATE_ABSENT",
    },
]

# META / triad / vector-reason control cases
META_CASES: list[dict[str, Any]] = [
    {
        "case_id": "M1_triad_only_in_side_note",
        "kind": "run_out_triad",
        "meta": {
            "preimage_binding": {},
            "side_notes": {
                "input_window_id": "win-9",
                "normalization_rule_version": "nr-1.0",
                "criteria_version": "crit-2",
            },
        },
        "expect_ok": False,
        "expect_reason": "RUN_OUT_TRIAD_NOT_IN_PREIMAGE",
    },
    {
        "case_id": "M2_triad_bound_in_preimage",
        "kind": "run_out_triad",
        "meta": {
            "preimage_binding": {
                "input_window_id": "win-9",
                "normalization_rule_version": "nr-1.0",
                "criteria_version": "crit-2",
            },
            "side_notes": {},
        },
        "expect_ok": True,
        "expect_reason": "RUN_OUT_TRIAD_BOUND",
    },
    {
        "case_id": "M3_reason_arm_layer_only",
        "kind": "vector_reason_meta",
        "meta": {
            "reason_code_granularity": "arm-layer",
            "reason_code_table": {"EMPTY_GATES_UNOBSERVED": "arm5"},
        },
        "expect_ok": False,
        "expect_reason": "REASON_CODE_ARM_LAYER_ONLY",
    },
    {
        "case_id": "M4_reason_vector_level_ok",
        "kind": "vector_reason_meta",
        "meta": {
            "reason_code_granularity": "vector-level",
            "reason_code_table": {
                "EMPTY_WINDOW_SET_UNOBSERVED": "H1",
                "WINDOW_FIELDS_ABSENT": "H2",
                "UNPAIRED_LIST_EMPTY": "H3",
                "UNPAIRED_LIST_ABSENT": "H4",
                "GATE_VALUES_DEFAULTED_NOT_OBSERVED": "H5",
                "REUSE_STATE_OUT_OF_CLOSET": "H6",
                "REUSE_STATE_ABSENT": "H7",
            },
        },
        "expect_ok": True,
        "expect_reason": "VECTOR_REASON_META_OK",
    },
]


def batch_digest(rows: list[dict[str, Any]]) -> str:
    """李晨熙 preimage: (case_id, reason_code, expected_code, verdict) sorted by case_id."""
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
    canon = json.dumps(tuples, sort_keys=False, separators=(",", ":")).encode()
    return hashlib.sha256(canon).hexdigest()


def run_all() -> dict[str, Any]:
    hollow_results = []
    hollow_ok = 0
    for case in HOLLOW_CASES:
        got = judge_hollow(case)
        ok = (
            got.get("disposition") == case["expect_disposition"]
            and got.get("reason_code") == case["expect_reason"]
        )
        if ok:
            hollow_ok += 1
        hollow_results.append(
            {
                "case_id": case["case_id"],
                "ok": ok,
                "expect_disposition": case["expect_disposition"],
                "expect_reason": case["expect_reason"],
                "got": got,
            }
        )

    # Self-check (李晨熙 6-item)
    codes = [r["got"]["reason_code"] for r in hollow_results]
    dispositions = [r["got"]["disposition"] for r in hollow_results]
    pass_in_denom = [
        r["case_id"]
        for r in hollow_results
        if r["got"].get("enter_pass_denom")
    ]
    self_check = {
        "n_rows": len(hollow_results) == 7,
        "codes_mutually_distinct": len(set(codes)) == len(codes),
        "zero_pass_rows": all(d != "PASS" for d in dispositions),
        "unprobed_not_in_pass_denom": len(pass_in_denom) == 0,
        "disposition_closed": all(d in {"UNPROBED", "FAIL"} for d in dispositions),
        "exactly_one_fail": dispositions.count("FAIL") == 1,
    }
    self_check["all_pass"] = all(self_check.values())

    meta_results = []
    meta_ok = 0
    for case in META_CASES:
        if case["kind"] == "run_out_triad":
            got = check_run_out_triad(case["meta"])
        else:
            got = check_vector_reason_meta(case["meta"])
        ok = got.get("ok") == case["expect_ok"] and got.get("reason_code") == case[
            "expect_reason"
        ]
        if ok:
            meta_ok += 1
        meta_results.append(
            {
                "case_id": case["case_id"],
                "ok": ok,
                "expect_ok": case["expect_ok"],
                "expect_reason": case["expect_reason"],
                "got": got,
            }
        )

    nc_ledger = check_not_comparable_ledger(
        [
            {"axis_alignment": "same"},
            {"axis_alignment": "not_translatable"},
            {"axis_alignment": "not_translatable"},
        ]
    )

    digest = batch_digest(
        [
            {
                "case_id": r["case_id"],
                "got": r["got"],
                "expect_reason": r["expect_reason"],
            }
            for r in hollow_results
        ]
    )

    total = len(HOLLOW_CASES) + len(META_CASES)
    passed = hollow_ok + meta_ok
    payload = {
        "fixture": "WINDOW_PAIRING",
        "version": "v0.3",
        "variant": "hollow_pass_repin",
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "hollow_results": hollow_results,
        "meta_results": meta_results,
        "self_check": self_check,
        "not_comparable_ledger": nc_ledger,
        "batch_digest_sha256": digest,
        "families": {
            "empty-payload-observed": [
                "EMPTY_WINDOW_SET_UNOBSERVED",
                "WINDOW_FIELDS_ABSENT",
                "UNPAIRED_LIST_EMPTY",
                "UNPAIRED_LIST_ABSENT",
                "GATE_VALUES_DEFAULTED_NOT_OBSERVED",
                "REUSE_STATE_ABSENT",
            ],
            "closed-set-violation": ["REUSE_STATE_OUT_OF_CLOSET"],
        },
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
    # Require self_check + all cases
    if not out["self_check"]["all_pass"]:
        return 2
    return 0 if out["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
