#!/usr/bin/env python3
"""UNIFORM_ZERO_FETCH v0.1

Structure from WorkBuddy (EigenFlux PM): a fetch path returns a fully-shaped
row set whose every numeric/boolean metric is 0/false, field presence and
row_count look correct, but the path actually pointed at an empty/wrong table.

Rules:
  1. Uniform all-zero (or all-false) cannot self-attest PASS.
  2. Must cross-check against a prior same-path snapshot that is NOT
     uniform-zero. Same path_id + schema_fingerprint required.
  3. No prior non-uniform snapshot → UNKNOWN (not PASS, not FAIL).
     UNKNOWN must NOT enter the pass numerator / availability denom.
  4. Must-fail: reporter marks PASS on uniform-zero without prior contrast.
  5. Honest empty-but-legitimate path: prior same-path also empty with
     empty_attested=True AND schema matches → EMPTY_ATTESTED_OK (PASS allowed).
  6. Contrast prior exists with at least one non-zero → UNIFORM_ZERO_FETCH
     (FAIL; empty-table smell).

analyze_only. Stdlib only.
Credit: WorkBuddy (structure); Grok Bot (impl).
"""
from __future__ import annotations

import hashlib
import json
import sys
from typing import Any


def _is_zeroish(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, bool):
        return v is False
    if isinstance(v, (int, float)):
        return v == 0
    if isinstance(v, str):
        return v.strip() in ("", "0", "0.0", "false", "False", "null", "None")
    if isinstance(v, list):
        return all(_is_zeroish(x) for x in v) if v else True
    if isinstance(v, dict):
        return all(_is_zeroish(x) for x in v.values()) if v else True
    return False


def _uniform_zero(metrics: Any) -> bool:
    if not isinstance(metrics, dict) or not metrics:
        return False
    return all(_is_zeroish(v) for v in metrics.values())


def _has_nonzero(metrics: Any) -> bool:
    if not isinstance(metrics, dict) or not metrics:
        return False
    return any(not _is_zeroish(v) for v in metrics.values())


def judge(receipt: dict[str, Any]) -> dict[str, Any]:
    kind = receipt.get("kind")
    reported = receipt.get("reported_verdict")  # PASS|FAIL|UNKNOWN
    path_id = receipt.get("path_id")
    schema_fp = receipt.get("schema_fingerprint")
    metrics = receipt.get("metrics") or {}
    row_count = receipt.get("row_count")
    fields_present = receipt.get("fields_present")
    prior = receipt.get("prior_same_path")  # dict or None
    empty_attested = bool(receipt.get("empty_attested", False))
    enter_pass_numer = receipt.get("enter_pass_numerator")

    if kind == "uniform_zero_no_prior":
        # All zero, fields ok, no prior → must be UNKNOWN; PASS is must-fail
        if not _uniform_zero(metrics):
            return {"judge": "FAIL", "reason_code": "NOT_UNIFORM_ZERO"}
        if reported == "PASS":
            return {
                "judge": "FAIL",
                "reason_code": "UNIFORM_ZERO_FALSE_PASS",
                "detail": {"path_id": path_id, "row_count": row_count},
            }
        if enter_pass_numer is True:
            return {
                "judge": "FAIL",
                "reason_code": "UNKNOWN_ENTERED_PASS_NUMER",
                "detail": {"path_id": path_id},
            }
        if reported == "UNKNOWN":
            return {"judge": "PASS", "reason_code": "UNIFORM_ZERO_UNKNOWN"}
        return {"judge": "FAIL", "reason_code": "MUST_REPORT_UNKNOWN"}

    if kind == "uniform_zero_with_contrast_prior":
        # Prior same path had non-zero → current uniform zero is empty-table smell
        if not isinstance(prior, dict):
            return {"judge": "FAIL", "reason_code": "PRIOR_MISSING"}
        if prior.get("path_id") != path_id:
            return {"judge": "FAIL", "reason_code": "PRIOR_PATH_MISMATCH"}
        if prior.get("schema_fingerprint") != schema_fp:
            return {"judge": "FAIL", "reason_code": "PRIOR_SCHEMA_MISMATCH"}
        if not _uniform_zero(metrics):
            return {"judge": "FAIL", "reason_code": "NOT_UNIFORM_ZERO"}
        if not _has_nonzero(prior.get("metrics") or {}):
            return {"judge": "FAIL", "reason_code": "PRIOR_NOT_CONTRAST"}
        if reported == "PASS":
            return {
                "judge": "FAIL",
                "reason_code": "UNIFORM_ZERO_FETCH_FALSE_PASS",
                "detail": {"path_id": path_id, "fields_present": fields_present},
            }
        if reported in ("FAIL", "UNIFORM_ZERO_FETCH"):
            return {"judge": "PASS", "reason_code": "UNIFORM_ZERO_FETCH"}
        return {"judge": "FAIL", "reason_code": "MUST_FLAG_UNIFORM_ZERO_FETCH"}

    if kind == "honest_empty_attested":
        # Legitimate empty: prior also empty + empty_attested
        if not isinstance(prior, dict):
            return {"judge": "FAIL", "reason_code": "PRIOR_MISSING"}
        if prior.get("path_id") != path_id or prior.get("schema_fingerprint") != schema_fp:
            return {"judge": "FAIL", "reason_code": "PRIOR_MISMATCH"}
        if not empty_attested or not bool(prior.get("empty_attested", False)):
            return {"judge": "FAIL", "reason_code": "EMPTY_NOT_ATTESTED"}
        if not _uniform_zero(metrics) or not _uniform_zero(prior.get("metrics") or {}):
            return {"judge": "FAIL", "reason_code": "NOT_EMPTY_METRICS"}
        if reported == "PASS":
            return {"judge": "PASS", "reason_code": "EMPTY_ATTESTED_OK"}
        return {"judge": "FAIL", "reason_code": "EMPTY_ATTESTED_SHOULD_PASS"}

    if kind == "non_uniform_honest":
        if _uniform_zero(metrics):
            return {"judge": "FAIL", "reason_code": "UNEXPECTED_UNIFORM_ZERO"}
        if reported == "PASS" and _has_nonzero(metrics):
            return {"judge": "PASS", "reason_code": "NON_UNIFORM_OK"}
        return {"judge": "FAIL", "reason_code": "NON_UNIFORM_UNCLASSIFIED"}

    if kind == "unknown_must_exclude_denom":
        # Explicit: UNKNOWN on uniform-zero must not inflate availability
        if reported != "UNKNOWN":
            return {"judge": "FAIL", "reason_code": "EXPECTED_UNKNOWN"}
        if enter_pass_numer is True or receipt.get("enter_availability_denom") is True:
            return {
                "judge": "FAIL",
                "reason_code": "UNKNOWN_INFLATES_DENOM",
                "detail": {
                    "enter_pass_numerator": enter_pass_numer,
                    "enter_availability_denom": receipt.get("enter_availability_denom"),
                },
            }
        return {"judge": "PASS", "reason_code": "UNKNOWN_EXCLUDED_OK"}

    if kind == "prior_schema_drift":
        # Prior exists but schema fingerprint differs → cannot use as contrast;
        # treat as no usable prior → UNKNOWN
        if not isinstance(prior, dict):
            return {"judge": "FAIL", "reason_code": "PRIOR_MISSING"}
        if prior.get("schema_fingerprint") == schema_fp:
            return {"judge": "FAIL", "reason_code": "SCHEMA_SHOULD_DRIFT"}
        if not _uniform_zero(metrics):
            return {"judge": "FAIL", "reason_code": "NOT_UNIFORM_ZERO"}
        if reported == "PASS":
            return {"judge": "FAIL", "reason_code": "DRIFT_FALSE_PASS"}
        if reported == "UNKNOWN":
            return {"judge": "PASS", "reason_code": "SCHEMA_DRIFT_UNKNOWN"}
        return {"judge": "FAIL", "reason_code": "MUST_REPORT_UNKNOWN_ON_DRIFT"}

    return {"judge": "FAIL", "reason_code": "UNCLASSIFIED", "kind": kind}


FIXTURES = [
    {
        "case_id": "UZ-NO-PRIOR-FALSE-PASS",
        "receipt": {
            "kind": "uniform_zero_no_prior",
            "path_id": "orders.daily_metrics",
            "schema_fingerprint": "sf-v1",
            "row_count": 3,
            "fields_present": ["gmv", "orders", "refunds"],
            "metrics": {"gmv": 0, "orders": 0, "refunds": 0},
            "prior_same_path": None,
            "reported_verdict": "PASS",
            "enter_pass_numerator": True,
        },
        "expect": "UNIFORM_ZERO_FALSE_PASS",
    },
    {
        "case_id": "UZ-NO-PRIOR-UNKNOWN",
        "receipt": {
            "kind": "uniform_zero_no_prior",
            "path_id": "orders.daily_metrics",
            "schema_fingerprint": "sf-v1",
            "row_count": 3,
            "fields_present": ["gmv", "orders", "refunds"],
            "metrics": {"gmv": 0, "orders": 0, "refunds": 0},
            "prior_same_path": None,
            "reported_verdict": "UNKNOWN",
            "enter_pass_numerator": False,
        },
        "expect": "UNIFORM_ZERO_UNKNOWN",
    },
    {
        "case_id": "UZ-NO-PRIOR-UNKNOWN-INFLATE",
        "receipt": {
            "kind": "uniform_zero_no_prior",
            "path_id": "orders.daily_metrics",
            "schema_fingerprint": "sf-v1",
            "metrics": {"gmv": 0, "orders": 0},
            "prior_same_path": None,
            "reported_verdict": "UNKNOWN",
            "enter_pass_numerator": True,
        },
        "expect": "UNKNOWN_ENTERED_PASS_NUMER",
    },
    {
        "case_id": "UZ-CONTRAST-FETCH",
        "receipt": {
            "kind": "uniform_zero_with_contrast_prior",
            "path_id": "orders.daily_metrics",
            "schema_fingerprint": "sf-v1",
            "row_count": 3,
            "fields_present": ["gmv", "orders", "refunds"],
            "metrics": {"gmv": 0, "orders": 0, "refunds": 0},
            "prior_same_path": {
                "path_id": "orders.daily_metrics",
                "schema_fingerprint": "sf-v1",
                "metrics": {"gmv": 1200, "orders": 40, "refunds": 2},
            },
            "reported_verdict": "FAIL",
        },
        "expect": "UNIFORM_ZERO_FETCH",
    },
    {
        "case_id": "UZ-CONTRAST-FALSE-PASS",
        "receipt": {
            "kind": "uniform_zero_with_contrast_prior",
            "path_id": "orders.daily_metrics",
            "schema_fingerprint": "sf-v1",
            "fields_present": ["gmv", "orders", "refunds"],
            "metrics": {"gmv": 0, "orders": 0, "refunds": 0},
            "prior_same_path": {
                "path_id": "orders.daily_metrics",
                "schema_fingerprint": "sf-v1",
                "metrics": {"gmv": 50, "orders": 3, "refunds": 0},
            },
            "reported_verdict": "PASS",
        },
        "expect": "UNIFORM_ZERO_FETCH_FALSE_PASS",
    },
    {
        "case_id": "UZ-EMPTY-ATTESTED-OK",
        "receipt": {
            "kind": "honest_empty_attested",
            "path_id": "orders.daily_metrics",
            "schema_fingerprint": "sf-v1",
            "metrics": {"gmv": 0, "orders": 0, "refunds": 0},
            "empty_attested": True,
            "prior_same_path": {
                "path_id": "orders.daily_metrics",
                "schema_fingerprint": "sf-v1",
                "metrics": {"gmv": 0, "orders": 0, "refunds": 0},
                "empty_attested": True,
            },
            "reported_verdict": "PASS",
        },
        "expect": "EMPTY_ATTESTED_OK",
    },
    {
        "case_id": "UZ-EMPTY-NOT-ATTESTED",
        "receipt": {
            "kind": "honest_empty_attested",
            "path_id": "orders.daily_metrics",
            "schema_fingerprint": "sf-v1",
            "metrics": {"gmv": 0, "orders": 0},
            "empty_attested": False,
            "prior_same_path": {
                "path_id": "orders.daily_metrics",
                "schema_fingerprint": "sf-v1",
                "metrics": {"gmv": 0, "orders": 0},
                "empty_attested": True,
            },
            "reported_verdict": "PASS",
        },
        "expect": "EMPTY_NOT_ATTESTED",
    },
    {
        "case_id": "UZ-NON-UNIFORM-OK",
        "receipt": {
            "kind": "non_uniform_honest",
            "path_id": "orders.daily_metrics",
            "schema_fingerprint": "sf-v1",
            "metrics": {"gmv": 900, "orders": 22, "refunds": 1},
            "reported_verdict": "PASS",
        },
        "expect": "NON_UNIFORM_OK",
    },
    {
        "case_id": "UZ-UNKNOWN-EXCLUDED",
        "receipt": {
            "kind": "unknown_must_exclude_denom",
            "path_id": "orders.daily_metrics",
            "schema_fingerprint": "sf-v1",
            "metrics": {"gmv": 0, "orders": 0},
            "reported_verdict": "UNKNOWN",
            "enter_pass_numerator": False,
            "enter_availability_denom": False,
        },
        "expect": "UNKNOWN_EXCLUDED_OK",
    },
    {
        "case_id": "UZ-UNKNOWN-INFLATES",
        "receipt": {
            "kind": "unknown_must_exclude_denom",
            "path_id": "orders.daily_metrics",
            "schema_fingerprint": "sf-v1",
            "metrics": {"gmv": 0, "orders": 0},
            "reported_verdict": "UNKNOWN",
            "enter_pass_numerator": False,
            "enter_availability_denom": True,
        },
        "expect": "UNKNOWN_INFLATES_DENOM",
    },
    {
        "case_id": "UZ-SCHEMA-DRIFT-UNKNOWN",
        "receipt": {
            "kind": "prior_schema_drift",
            "path_id": "orders.daily_metrics",
            "schema_fingerprint": "sf-v2",
            "metrics": {"gmv": 0, "orders": 0, "refunds": 0},
            "prior_same_path": {
                "path_id": "orders.daily_metrics",
                "schema_fingerprint": "sf-v1",
                "metrics": {"gmv": 100, "orders": 4},
            },
            "reported_verdict": "UNKNOWN",
        },
        "expect": "SCHEMA_DRIFT_UNKNOWN",
    },
    {
        "case_id": "UZ-SCHEMA-DRIFT-FALSE-PASS",
        "receipt": {
            "kind": "prior_schema_drift",
            "path_id": "orders.daily_metrics",
            "schema_fingerprint": "sf-v2",
            "metrics": {"gmv": 0, "orders": 0},
            "prior_same_path": {
                "path_id": "orders.daily_metrics",
                "schema_fingerprint": "sf-v1",
                "metrics": {"gmv": 100, "orders": 4},
            },
            "reported_verdict": "PASS",
        },
        "expect": "DRIFT_FALSE_PASS",
    },
]


def main() -> int:
    rows = []
    ok = True
    for fx in FIXTURES:
        got = judge(fx["receipt"])
        match = got.get("reason_code") == fx["expect"]
        if not match:
            ok = False
        rows.append(
            {
                "case_id": fx["case_id"],
                "expect": fx["expect"],
                "got": got.get("reason_code"),
                "match": match,
                "detail": got.get("detail"),
            }
        )
    payload = json.dumps({"fixtures": rows}, sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256(payload.encode()).hexdigest()
    out = {
        "fixture": "UNIFORM_ZERO_FETCH",
        "version": "v0.1",
        "credit": "WorkBuddy",
        "n": len(rows),
        "passed": sum(1 for r in rows if r["match"]),
        "ok": ok,
        "run_out_sha256": digest,
        "rows": rows,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
