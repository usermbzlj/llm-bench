#!/usr/bin/env python3
"""GHOST_ID_IN_DENOM v0.1

Structure-only fixture. Failure shapes from EigenFlux collab with 沈小楠
(three systematic metric biases) and 小巴 (ghost-id-in-denominator debt):

Arms:
  ① unclassified_renamed_into_bucket — UNCLASSIFIED / unknown errors are
     relabeled into a known green bucket so they inflate pass_count →
     UNCLASSIFIED_RELABEL_FALSE_PASS.
  ② planned_excluded_from_denom — IDs that were planned but never executed
     (or below threshold) are silently dropped from the denominator while
     pass_count stays on the shrunk base → DENOM_SHIFT_GHOST.
  ③ ghost_id_in_pass_set — IDs appear in pass_ids / denom_ids that never
     appear in planned_ids nor executed_ids → GHOST_ID_IN_DENOM.
  ④ self_attest_as_verify — producer self-signs success with no independent
     observer receipt → SELF_ATTEST_FALSE_PASS.
  ⑤ honest_planned_executed_denom — planned set is the only legal denom
     base; executed receipts required for PASS numer; UNCLASSIFIED stays
     UNCLASSIFIED; verify_source != producer → HONEST_PLANNED_EXECUTED.

Honest path: denom_ids ⊆ planned_ids; pass_ids ⊆ executed_ids ⊆ planned_ids;
no UNCLASSIFIED→known remaps; independent verify_source.

General fixture; analyze_only. Stdlib only.
Credit: 沈小楠 (structure); 小巴 (denom debt signal); Grok Bot (impl).
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


def _id_set(xs: Any) -> set[str]:
    out: set[str] = set()
    if not isinstance(xs, list):
        return out
    for x in xs:
        n = _norm(x)
        if n:
            out.add(n)
    return out


def judge(receipt: dict[str, Any]) -> dict[str, Any]:
    kind = receipt.get("kind")
    reported = receipt.get("reported_verdict")  # PASS|FAIL|UNCLASSIFIED

    if kind == "unclassified_renamed_into_bucket":
        raw = _norm(receipt.get("raw_error_class"))  # UNCLASSIFIED|UNKNOWN|...
        mapped = _norm(receipt.get("mapped_bucket"))  # success|ok|pass|...
        green_buckets = {"success", "ok", "pass", "green", "available"}
        if raw in ("UNCLASSIFIED", "UNKNOWN", "unclassified", "unknown") and (
            mapped in green_buckets or reported == "PASS"
        ):
            return {
                "judge": "FAIL",
                "reason_code": "UNCLASSIFIED_RELABEL_FALSE_PASS",
                "detail": {"raw_error_class": raw, "mapped_bucket": mapped},
            }
        if raw in ("UNCLASSIFIED", "UNKNOWN", "unclassified", "unknown") and reported == "UNCLASSIFIED":
            return {"judge": "PASS", "reason_code": "HONEST_UNCLASSIFIED_KEPT"}
        if raw not in ("UNCLASSIFIED", "UNKNOWN", "unclassified", "unknown") and reported in (
            "PASS",
            "FAIL",
            "UNCLASSIFIED",
        ):
            return {"judge": "PASS", "reason_code": "HONEST_CLASSIFIED"}
        return {
            "judge": "FAIL",
            "reason_code": "RELABEL_STATE_INCONSISTENT",
            "detail": {"raw_error_class": raw, "mapped_bucket": mapped, "reported_verdict": reported},
        }

    if kind == "planned_excluded_from_denom":
        planned = _id_set(receipt.get("planned_ids"))
        denom = _id_set(receipt.get("denom_ids"))
        executed = _id_set(receipt.get("executed_ids"))
        excluded = planned - denom
        # Below-threshold / not-executed planned IDs silently removed from denom.
        if excluded and reported == "PASS":
            return {
                "judge": "FAIL",
                "reason_code": "DENOM_SHIFT_GHOST",
                "detail": {
                    "excluded_from_denom": sorted(excluded),
                    "planned_n": len(planned),
                    "denom_n": len(denom),
                    "executed_n": len(executed),
                },
            }
        if excluded:
            return {
                "judge": "FAIL",
                "reason_code": "DENOM_SHIFT",
                "detail": {"excluded_from_denom": sorted(excluded)},
            }
        if planned and denom == planned and reported in ("PASS", "FAIL"):
            return {"judge": "PASS", "reason_code": "HONEST_DENOM_EQ_PLANNED"}
        if not planned:
            return {"judge": "FAIL", "reason_code": "PLANNED_EMPTY"}
        return {
            "judge": "FAIL",
            "reason_code": "DENOM_STATE_INCONSISTENT",
            "detail": {"planned_n": len(planned), "denom_n": len(denom)},
        }

    if kind == "ghost_id_in_pass_set":
        planned = _id_set(receipt.get("planned_ids"))
        executed = _id_set(receipt.get("executed_ids"))
        denom = _id_set(receipt.get("denom_ids"))
        pass_ids = _id_set(receipt.get("pass_ids"))
        legal = planned | executed
        ghosts_denom = denom - legal
        ghosts_pass = pass_ids - legal
        ghosts = ghosts_denom | ghosts_pass
        if ghosts and reported == "PASS":
            return {
                "judge": "FAIL",
                "reason_code": "GHOST_ID_IN_DENOM",
                "detail": {
                    "ghost_in_denom": sorted(ghosts_denom),
                    "ghost_in_pass": sorted(ghosts_pass),
                },
            }
        if ghosts:
            return {
                "judge": "FAIL",
                "reason_code": "GHOST_ID_PRESENT",
                "detail": {
                    "ghost_in_denom": sorted(ghosts_denom),
                    "ghost_in_pass": sorted(ghosts_pass),
                },
            }
        if pass_ids and not pass_ids.issubset(executed):
            return {
                "judge": "FAIL",
                "reason_code": "PASS_NOT_SUBSET_EXECUTED",
                "detail": {"orphan_pass": sorted(pass_ids - executed)},
            }
        if reported in ("PASS", "FAIL") and not ghosts:
            return {"judge": "PASS", "reason_code": "HONEST_NO_GHOST"}
        return {"judge": "FAIL", "reason_code": "REPORTED_VERDICT_MISSING"}

    if kind == "self_attest_as_verify":
        producer = _norm(receipt.get("producer_id"))
        verify_source = _norm(receipt.get("verify_source"))
        independent = bool(receipt.get("independent_observer", False))
        if reported == "PASS" and (
            not independent or verify_source is None or (producer and verify_source == producer)
        ):
            return {
                "judge": "FAIL",
                "reason_code": "SELF_ATTEST_FALSE_PASS",
                "detail": {
                    "producer_id": producer,
                    "verify_source": verify_source,
                    "independent_observer": independent,
                },
            }
        if independent and verify_source and verify_source != producer and reported in ("PASS", "FAIL"):
            return {"judge": "PASS", "reason_code": "HONEST_INDEPENDENT_VERIFY"}
        return {
            "judge": "FAIL",
            "reason_code": "VERIFY_STATE_INCONSISTENT",
            "detail": {
                "producer_id": producer,
                "verify_source": verify_source,
                "independent_observer": independent,
                "reported_verdict": reported,
            },
        }

    if kind == "honest_planned_executed_denom":
        planned = _id_set(receipt.get("planned_ids"))
        executed = _id_set(receipt.get("executed_ids"))
        denom = _id_set(receipt.get("denom_ids"))
        pass_ids = _id_set(receipt.get("pass_ids"))
        producer = _norm(receipt.get("producer_id"))
        verify_source = _norm(receipt.get("verify_source"))
        remaps = receipt.get("error_remaps") or []
        bad_remap = False
        for row in remaps:
            if not isinstance(row, dict):
                continue
            raw = _norm(row.get("raw"))
            mapped = _norm(row.get("mapped"))
            if raw in ("UNCLASSIFIED", "UNKNOWN") and mapped in ("success", "ok", "pass", "green"):
                bad_remap = True
                break
        if bad_remap and reported == "PASS":
            return {"judge": "FAIL", "reason_code": "UNCLASSIFIED_RELABEL_FALSE_PASS"}
        if denom != planned:
            return {
                "judge": "FAIL",
                "reason_code": "DENOM_SHIFT_GHOST" if reported == "PASS" else "DENOM_SHIFT",
                "detail": {"planned": sorted(planned), "denom": sorted(denom)},
            }
        if not executed.issubset(planned):
            return {
                "judge": "FAIL",
                "reason_code": "EXECUTED_OUTSIDE_PLANNED",
                "detail": {"orphan_exec": sorted(executed - planned)},
            }
        if not pass_ids.issubset(executed):
            return {
                "judge": "FAIL",
                "reason_code": "GHOST_ID_IN_DENOM" if reported == "PASS" else "PASS_NOT_SUBSET_EXECUTED",
                "detail": {"orphan_pass": sorted(pass_ids - executed)},
            }
        if reported == "PASS" and (not verify_source or verify_source == producer):
            return {"judge": "FAIL", "reason_code": "SELF_ATTEST_FALSE_PASS"}
        if reported in ("PASS", "FAIL", "UNCLASSIFIED"):
            return {"judge": "PASS", "reason_code": "HONEST_PLANNED_EXECUTED"}
        return {"judge": "FAIL", "reason_code": "REPORTED_VERDICT_MISSING"}

    return {"judge": "FAIL", "reason_code": "UNKNOWN_KIND", "detail": {"kind": kind}}


CASES: list[dict[str, Any]] = [
    # --- ① unclassified_renamed_into_bucket ---
    {
        "case_id": "gid-relabel-unclassified-to-ok",
        "kind": "unclassified_renamed_into_bucket",
        "reported_verdict": "PASS",
        "raw_error_class": "UNCLASSIFIED",
        "mapped_bucket": "ok",
        "expect_judge": "FAIL",
        "expect_reason": "UNCLASSIFIED_RELABEL_FALSE_PASS",
    },
    {
        "case_id": "gid-relabel-unknown-to-success",
        "kind": "unclassified_renamed_into_bucket",
        "reported_verdict": "PASS",
        "raw_error_class": "UNKNOWN",
        "mapped_bucket": "success",
        "expect_judge": "FAIL",
        "expect_reason": "UNCLASSIFIED_RELABEL_FALSE_PASS",
    },
    {
        "case_id": "gid-relabel-honest-kept",
        "kind": "unclassified_renamed_into_bucket",
        "reported_verdict": "UNCLASSIFIED",
        "raw_error_class": "UNCLASSIFIED",
        "mapped_bucket": "UNCLASSIFIED",
        "expect_judge": "PASS",
        "expect_reason": "HONEST_UNCLASSIFIED_KEPT",
    },
    {
        "case_id": "gid-relabel-honest-classified",
        "kind": "unclassified_renamed_into_bucket",
        "reported_verdict": "FAIL",
        "raw_error_class": "TIMEOUT",
        "mapped_bucket": "timeout",
        "expect_judge": "PASS",
        "expect_reason": "HONEST_CLASSIFIED",
    },
    # --- ② planned_excluded_from_denom ---
    {
        "case_id": "gid-denom-drop-unexecuted",
        "kind": "planned_excluded_from_denom",
        "reported_verdict": "PASS",
        "planned_ids": ["a", "b", "c"],
        "denom_ids": ["a", "b"],
        "executed_ids": ["a", "b"],
        "expect_judge": "FAIL",
        "expect_reason": "DENOM_SHIFT_GHOST",
    },
    {
        "case_id": "gid-denom-drop-below-threshold",
        "kind": "planned_excluded_from_denom",
        "reported_verdict": "PASS",
        "planned_ids": ["p1", "p2", "p3", "p4"],
        "denom_ids": ["p1", "p2"],
        "executed_ids": ["p1"],
        "expect_judge": "FAIL",
        "expect_reason": "DENOM_SHIFT_GHOST",
    },
    {
        "case_id": "gid-denom-honest-eq-planned",
        "kind": "planned_excluded_from_denom",
        "reported_verdict": "PASS",
        "planned_ids": ["a", "b", "c"],
        "denom_ids": ["a", "b", "c"],
        "executed_ids": ["a", "b"],
        "expect_judge": "PASS",
        "expect_reason": "HONEST_DENOM_EQ_PLANNED",
    },
    # --- ③ ghost_id_in_pass_set ---
    {
        "case_id": "gid-ghost-in-denom",
        "kind": "ghost_id_in_pass_set",
        "reported_verdict": "PASS",
        "planned_ids": ["a", "b"],
        "executed_ids": ["a", "b"],
        "denom_ids": ["a", "b", "ghost-x"],
        "pass_ids": ["a", "b"],
        "expect_judge": "FAIL",
        "expect_reason": "GHOST_ID_IN_DENOM",
    },
    {
        "case_id": "gid-ghost-in-pass",
        "kind": "ghost_id_in_pass_set",
        "reported_verdict": "PASS",
        "planned_ids": ["a", "b"],
        "executed_ids": ["a"],
        "denom_ids": ["a", "b"],
        "pass_ids": ["a", "phantom"],
        "expect_judge": "FAIL",
        "expect_reason": "GHOST_ID_IN_DENOM",
    },
    {
        "case_id": "gid-ghost-honest",
        "kind": "ghost_id_in_pass_set",
        "reported_verdict": "PASS",
        "planned_ids": ["a", "b"],
        "executed_ids": ["a", "b"],
        "denom_ids": ["a", "b"],
        "pass_ids": ["a"],
        "expect_judge": "PASS",
        "expect_reason": "HONEST_NO_GHOST",
    },
    # --- ④ self_attest_as_verify ---
    {
        "case_id": "gid-self-attest-same-id",
        "kind": "self_attest_as_verify",
        "reported_verdict": "PASS",
        "producer_id": "svc-A",
        "verify_source": "svc-A",
        "independent_observer": False,
        "expect_judge": "FAIL",
        "expect_reason": "SELF_ATTEST_FALSE_PASS",
    },
    {
        "case_id": "gid-self-attest-no-observer",
        "kind": "self_attest_as_verify",
        "reported_verdict": "PASS",
        "producer_id": "svc-A",
        "verify_source": "svc-A-monitor",
        "independent_observer": False,
        "expect_judge": "FAIL",
        "expect_reason": "SELF_ATTEST_FALSE_PASS",
    },
    {
        "case_id": "gid-self-attest-honest",
        "kind": "self_attest_as_verify",
        "reported_verdict": "PASS",
        "producer_id": "svc-A",
        "verify_source": "observer-B",
        "independent_observer": True,
        "expect_judge": "PASS",
        "expect_reason": "HONEST_INDEPENDENT_VERIFY",
    },
    # --- ⑤ honest_planned_executed_denom ---
    {
        "case_id": "gid-combo-relabel-false-pass",
        "kind": "honest_planned_executed_denom",
        "reported_verdict": "PASS",
        "planned_ids": ["a", "b"],
        "executed_ids": ["a", "b"],
        "denom_ids": ["a", "b"],
        "pass_ids": ["a", "b"],
        "producer_id": "p",
        "verify_source": "obs",
        "error_remaps": [{"raw": "UNCLASSIFIED", "mapped": "ok"}],
        "expect_judge": "FAIL",
        "expect_reason": "UNCLASSIFIED_RELABEL_FALSE_PASS",
    },
    {
        "case_id": "gid-combo-honest",
        "kind": "honest_planned_executed_denom",
        "reported_verdict": "PASS",
        "planned_ids": ["a", "b", "c"],
        "executed_ids": ["a", "b"],
        "denom_ids": ["a", "b", "c"],
        "pass_ids": ["a"],
        "producer_id": "producer-1",
        "verify_source": "observer-9",
        "error_remaps": [{"raw": "TIMEOUT", "mapped": "timeout"}],
        "expect_judge": "PASS",
        "expect_reason": "HONEST_PLANNED_EXECUTED",
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
        "fixture": "GHOST_ID_IN_DENOM",
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
