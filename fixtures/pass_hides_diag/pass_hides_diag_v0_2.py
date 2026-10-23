#!/usr/bin/env python3
"""PASS_HIDES_DIAG v0.2 — credit 木木 (v0.1) + WorkBuddy (cache window / silent relaxation)

v0.1 rules retained:
  1. PASS path MUST materialize the same diagnostic keys as FAIL.
  2. provenance channel independent of pass/fail.
  3. Negative control: strip diag → PASS must become FAIL.

v0.2 additions (WorkBuddy PM + silent-relaxation broadcast):
  4. CACHE_WINDOW_RELATIVE — record max-age as relative delta
     (probe_exec_ms - cache_write_ms), never absolute wall timestamps.
  5. PASS_HIDES_CACHE_WINDOW — PASS without cache_age_ms on a cache-sensitive
     probe is FAIL (false-green attribution requires a concrete window).
  6. SILENT_RELAXATION — if threshold_version bumps with a lowered numeric
     threshold and no explicit relax_reason, FAIL (pass-rate inflation gate).

analyze_only. Stdlib only.
"""
from __future__ import annotations
import json, sys
from typing import Any

REQUIRED_DIAG_KEYS = ("diag_code", "diag_detail", "provenance_ref")


def judge(receipt: dict[str, Any]) -> dict[str, Any]:
    verdict = receipt.get("verdict")
    keys_present = all(k in receipt for k in REQUIRED_DIAG_KEYS)
    provenance = receipt.get("provenance_ref")
    provenance_ok = isinstance(provenance, str) and len(provenance) > 0

    # v0.2: silent relaxation — lowered threshold without reason
    thr = receipt.get("threshold")
    thr_prev = receipt.get("threshold_prev")
    thr_ver = receipt.get("threshold_version")
    relax_reason = receipt.get("relax_reason")
    if (
        isinstance(thr, (int, float))
        and isinstance(thr_prev, (int, float))
        and thr < thr_prev
        and thr_ver
        and not relax_reason
    ):
        return {
            "judge": "FAIL",
            "reason_code": "SILENT_RELAXATION",
            "detail": {"threshold": thr, "threshold_prev": thr_prev, "threshold_version": thr_ver},
        }

    # v0.2: cache-sensitive PASS must carry relative window
    cache_sensitive = bool(receipt.get("cache_sensitive"))
    if verdict == "PASS" and cache_sensitive:
        age = receipt.get("cache_age_ms")
        if not isinstance(age, (int, float)) or age < 0:
            return {
                "judge": "FAIL",
                "reason_code": "PASS_HIDES_CACHE_WINDOW",
                "missing": ["cache_age_ms"],
            }
        # reject absolute wall-clock pair as sole window
        if "cache_write_wall" in receipt or "probe_exec_wall" in receipt:
            if "cache_age_ms" not in receipt:
                return {
                    "judge": "FAIL",
                    "reason_code": "CACHE_WINDOW_NOT_RELATIVE",
                }

    if verdict == "PASS" and not keys_present:
        return {
            "judge": "FAIL",
            "reason_code": "PASS_HIDES_DIAG",
            "missing": [k for k in REQUIRED_DIAG_KEYS if k not in receipt],
        }
    if verdict == "PASS" and not provenance_ok:
        return {
            "judge": "FAIL",
            "reason_code": "PASS_PROVENANCE_MISSING",
            "missing": ["provenance_ref"],
        }
    if verdict == "PASS" and keys_present and provenance_ok:
        return {"judge": "PASS", "reason_code": "DIAG_SURFACE_OK"}
    if verdict == "FAIL" and keys_present:
        return {"judge": "PASS", "reason_code": "FAIL_WITH_DIAG"}
    return {"judge": "FAIL", "reason_code": "UNCLASSIFIED", "verdict": verdict}


FIXTURES = [
    {
        "case_id": "MS-PASS-FULL",
        "receipt": {
            "verdict": "PASS",
            "diag_code": "",
            "diag_detail": None,
            "provenance_ref": "ci:run/123#job/456",
        },
        "expect_reason": "DIAG_SURFACE_OK",
    },
    {
        "case_id": "MS-PASS-NO-DIAG",
        "receipt": {"verdict": "PASS", "ok": True},
        "expect_reason": "PASS_HIDES_DIAG",
    },
    {
        "case_id": "MS-PASS-STRIPPED",
        "receipt": {"verdict": "PASS", "provenance_ref": "ci:run/123#job/456"},
        "expect_reason": "PASS_HIDES_DIAG",
    },
    {
        "case_id": "MS-FAIL-WITH-DIAG",
        "receipt": {
            "verdict": "FAIL",
            "diag_code": "ASSERT_X",
            "diag_detail": "expected 1 got 0",
            "provenance_ref": "ci:run/124#job/1",
        },
        "expect_reason": "FAIL_WITH_DIAG",
    },
    {
        "case_id": "MS-PASS-CACHE-NO-AGE",
        "receipt": {
            "verdict": "PASS",
            "diag_code": "",
            "diag_detail": None,
            "provenance_ref": "ci:run/200#job/1",
            "cache_sensitive": True,
        },
        "expect_reason": "PASS_HIDES_CACHE_WINDOW",
    },
    {
        "case_id": "MS-PASS-CACHE-RELATIVE",
        "receipt": {
            "verdict": "PASS",
            "diag_code": "",
            "diag_detail": None,
            "provenance_ref": "ci:run/201#job/1",
            "cache_sensitive": True,
            "cache_age_ms": 1200,
        },
        "expect_reason": "DIAG_SURFACE_OK",
    },
    {
        "case_id": "MS-SILENT-RELAX",
        "receipt": {
            "verdict": "PASS",
            "diag_code": "",
            "diag_detail": None,
            "provenance_ref": "ci:run/300#job/1",
            "threshold": 0.7,
            "threshold_prev": 0.9,
            "threshold_version": "v1.2",
        },
        "expect_reason": "SILENT_RELAXATION",
    },
    {
        "case_id": "MS-EXPLICIT-RELAX",
        "receipt": {
            "verdict": "PASS",
            "diag_code": "",
            "diag_detail": None,
            "provenance_ref": "ci:run/301#job/1",
            "threshold": 0.7,
            "threshold_prev": 0.9,
            "threshold_version": "v1.2",
            "relax_reason": "documented: noise floor recalibrated 2026-10-23",
        },
        "expect_reason": "DIAG_SURFACE_OK",
    },
]


def main() -> int:
    rows = []
    ok = True
    for fx in FIXTURES:
        got = judge(fx["receipt"])
        pass_row = got.get("reason_code") == fx["expect_reason"]
        ok = ok and pass_row
        rows.append(
            {
                "case_id": fx["case_id"],
                "expect": fx["expect_reason"],
                "got": got.get("reason_code"),
                "match": pass_row,
                "judge": got,
            }
        )
    out = {"version": "PASS_HIDES_DIAG/v0.2", "all_match": ok, "rows": rows}
    print(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
