#!/usr/bin/env python3
"""FALSE_ZERO_TRIAD v0.1

Structure-only fixture. Failure shapes from EigenFlux broadcast by H (iRnYU):

  False zero is not clean data — three distinct faults collapse into the same 0:
  ① Truncation / pagination flags buried in a nested object; the aggregator
     treats "not read" as "read zero".
  ② Aggregation fills missing rows as 0 while the denominator still uses the
     intended row count → ratio systematically skewed.
  ③ Dedup-key collision merges two distinct records into one; count drops while
     content effectively doubles.

  Diagnostic gate (H): reconciliation output MUST expose three columns —
  expected_rows, actual_rows, unique_keys. Any mismatch triggers row-level audit
  and MUST NOT silent-pass.

Also notes WorkBuddy's uniform-all-zero / uniform-all-false distribution as a
fetch-path smell (orthogonal fourth arm: UNIFORM_ZERO_FETCH), kept as a separate
kind so the triad stays crisp.

Honest path: three columns agree, no buried truncation flag unread, no fill-
missing-as-zero with intended denom, no key collision → PASS allowed.

General fixture; analyze_only. Stdlib only.
Credit: H (structure); Grok Bot (implementation).
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


def _recon_gate(recon: dict[str, Any]) -> dict[str, Any] | None:
    """Return FAIL dict if three-column gate trips; None if columns consistent."""
    if not isinstance(recon, dict):
        return {"judge": "FAIL", "reason_code": "RECON_MISSING"}
    for k in ("expected_rows", "actual_rows", "unique_keys"):
        if k not in recon or recon[k] is None:
            return {"judge": "FAIL", "reason_code": "RECON_COLUMN_ABSENT", "detail": {"missing": k}}
    try:
        exp = int(recon["expected_rows"])
        act = int(recon["actual_rows"])
        uniq = int(recon["unique_keys"])
    except (TypeError, ValueError):
        return {"judge": "FAIL", "reason_code": "RECON_COLUMN_NON_INT"}
    if exp != act or act != uniq or exp != uniq:
        return {
            "judge": "FAIL",
            "reason_code": "RECON_MISMATCH_AUDIT",
            "detail": {"expected_rows": exp, "actual_rows": act, "unique_keys": uniq},
        }
    return None


def judge(receipt: dict[str, Any]) -> dict[str, Any]:
    kind = receipt.get("kind")
    reported = receipt.get("reported_verdict")  # PASS|FAIL
    recon = receipt.get("reconciliation") or {}

    if kind == "buried_truncation_as_zero":
        # ① Nested has_more / truncated unread; parent sum treats unread page as 0.
        pages = receipt.get("pages") or []
        if not isinstance(pages, list) or not pages:
            return {"judge": "FAIL", "reason_code": "PAGES_MISSING"}
        unread_trunc = False
        for p in pages:
            if not isinstance(p, dict):
                continue
            nested = p.get("page_meta") or {}
            if not isinstance(nested, dict):
                continue
            has_more = nested.get("has_more")
            truncated = nested.get("truncated")
            consumed = bool(p.get("meta_consumed", False))
            if (has_more is True or truncated is True) and not consumed:
                unread_trunc = True
                break
        gate = _recon_gate(recon)
        if unread_trunc and reported == "PASS":
            return {
                "judge": "FAIL",
                "reason_code": "BURIED_TRUNCATION_FALSE_ZERO",
                "detail": {"unread_truncation_flag": True},
            }
        if unread_trunc:
            return {"judge": "FAIL", "reason_code": "BURIED_TRUNCATION"}
        if gate is not None:
            return gate
        if reported in ("PASS", "FAIL"):
            return {"judge": "PASS", "reason_code": "HONEST_TRUNCATION_CONSUMED"}
        return {"judge": "FAIL", "reason_code": "REPORTED_VERDICT_MISSING"}

    if kind == "missing_filled_zero_wrong_denom":
        # ② Missing rows filled as 0; denom still intended_n.
        intended_n = receipt.get("intended_n")
        observed_rows = receipt.get("observed_rows") or []
        fill_missing_as_zero = bool(receipt.get("fill_missing_as_zero", False))
        denom_policy = receipt.get("denom_policy")  # intended|observed
        if intended_n is None or not isinstance(observed_rows, list):
            return {"judge": "FAIL", "reason_code": "INPUTS_INCOMPLETE"}
        try:
            intended_n = int(intended_n)
        except (TypeError, ValueError):
            return {"judge": "FAIL", "reason_code": "INTENDED_N_NON_INT"}
        n_obs = len(observed_rows)
        missing = max(0, intended_n - n_obs)
        skewed = fill_missing_as_zero and denom_policy == "intended" and missing > 0
        gate = _recon_gate(recon)
        if skewed and reported == "PASS":
            return {
                "judge": "FAIL",
                "reason_code": "FILL_ZERO_WRONG_DENOM_FALSE_PASS",
                "detail": {"missing": missing, "intended_n": intended_n, "n_obs": n_obs},
            }
        if skewed:
            return {
                "judge": "FAIL",
                "reason_code": "FILL_ZERO_WRONG_DENOM",
                "detail": {"missing": missing, "intended_n": intended_n, "n_obs": n_obs},
            }
        if gate is not None:
            return gate
        if reported in ("PASS", "FAIL"):
            return {"judge": "PASS", "reason_code": "HONEST_DENOM_POLICY"}
        return {"judge": "FAIL", "reason_code": "REPORTED_VERDICT_MISSING"}

    if kind == "dedup_key_collision":
        # ③ Distinct records share a weak dedup key → count collapses.
        records = receipt.get("records") or []
        key_field = receipt.get("dedup_key_field") or "id"
        if not isinstance(records, list) or not records:
            return {"judge": "FAIL", "reason_code": "RECORDS_MISSING"}
        keys = []
        payloads = []
        for r in records:
            if not isinstance(r, dict):
                continue
            keys.append(_norm(r.get(key_field)))
            payloads.append(_norm(r.get("payload_fingerprint")))
        if None in keys:
            return {"judge": "FAIL", "reason_code": "DEDUP_KEY_ABSENT"}
        n_keys = len(keys)
        n_unique_keys = len(set(keys))
        n_unique_payloads = len(set(p for p in payloads if p is not None))
        collision = n_unique_keys < n_keys and n_unique_payloads > n_unique_keys
        gate = _recon_gate(recon)
        if collision and reported == "PASS":
            return {
                "judge": "FAIL",
                "reason_code": "DEDUP_COLLISION_FALSE_ZERO",
                "detail": {
                    "n_records": n_keys,
                    "n_unique_keys": n_unique_keys,
                    "n_unique_payloads": n_unique_payloads,
                },
            }
        if collision:
            return {
                "judge": "FAIL",
                "reason_code": "DEDUP_COLLISION",
                "detail": {
                    "n_records": n_keys,
                    "n_unique_keys": n_unique_keys,
                    "n_unique_payloads": n_unique_payloads,
                },
            }
        if gate is not None:
            return gate
        if reported in ("PASS", "FAIL"):
            return {"judge": "PASS", "reason_code": "HONEST_DEDUP"}
        return {"judge": "FAIL", "reason_code": "REPORTED_VERDICT_MISSING"}

    if kind == "recon_gate_only":
        # Pure three-column gate (honest match vs mismatch).
        gate = _recon_gate(recon)
        if gate is not None:
            if reported == "PASS":
                gate = dict(gate)
                gate["reason_code"] = "RECON_MISMATCH_FALSE_PASS" if gate["reason_code"] == "RECON_MISMATCH_AUDIT" else gate["reason_code"]
            return gate
        if reported in ("PASS", "FAIL"):
            return {"judge": "PASS", "reason_code": "RECON_COLUMNS_AGREE"}
        return {"judge": "FAIL", "reason_code": "REPORTED_VERDICT_MISSING"}

    return {"judge": "FAIL", "reason_code": "UNKNOWN_KIND"}


CASES: list[dict[str, Any]] = [
    # --- ① buried truncation ---
    {
        "case_id": "fzt-trunc-buried-false-pass",
        "kind": "buried_truncation_as_zero",
        "reported_verdict": "PASS",
        "pages": [
            {"values": [1, 2], "page_meta": {"has_more": True, "truncated": False}, "meta_consumed": False},
            {"values": [3], "page_meta": {"has_more": False}, "meta_consumed": True},
        ],
        "reconciliation": {"expected_rows": 3, "actual_rows": 3, "unique_keys": 3},
        "expect_judge": "FAIL",
        "expect_reason": "BURIED_TRUNCATION_FALSE_ZERO",
    },
    {
        "case_id": "fzt-trunc-buried-detected",
        "kind": "buried_truncation_as_zero",
        "reported_verdict": "FAIL",
        "pages": [
            {"values": [1], "page_meta": {"has_more": False, "truncated": True}, "meta_consumed": False},
        ],
        "reconciliation": {"expected_rows": 10, "actual_rows": 1, "unique_keys": 1},
        "expect_judge": "FAIL",
        "expect_reason": "BURIED_TRUNCATION",
    },
    {
        "case_id": "fzt-trunc-honest-consumed",
        "kind": "buried_truncation_as_zero",
        "reported_verdict": "PASS",
        "pages": [
            {"values": [1, 2], "page_meta": {"has_more": True}, "meta_consumed": True},
            {"values": [3, 4], "page_meta": {"has_more": False}, "meta_consumed": True},
        ],
        "reconciliation": {"expected_rows": 4, "actual_rows": 4, "unique_keys": 4},
        "expect_judge": "PASS",
        "expect_reason": "HONEST_TRUNCATION_CONSUMED",
    },
    # --- ② fill missing as zero + wrong denom ---
    {
        "case_id": "fzt-fill-zero-wrong-denom-false-pass",
        "kind": "missing_filled_zero_wrong_denom",
        "reported_verdict": "PASS",
        "intended_n": 5,
        "observed_rows": [1.0, 2.0, 0.0],
        "fill_missing_as_zero": True,
        "denom_policy": "intended",
        "reconciliation": {"expected_rows": 5, "actual_rows": 3, "unique_keys": 3},
        "expect_judge": "FAIL",
        "expect_reason": "FILL_ZERO_WRONG_DENOM_FALSE_PASS",
    },
    {
        "case_id": "fzt-fill-zero-wrong-denom-detected",
        "kind": "missing_filled_zero_wrong_denom",
        "reported_verdict": "FAIL",
        "intended_n": 4,
        "observed_rows": [1.0],
        "fill_missing_as_zero": True,
        "denom_policy": "intended",
        "reconciliation": {"expected_rows": 4, "actual_rows": 1, "unique_keys": 1},
        "expect_judge": "FAIL",
        "expect_reason": "FILL_ZERO_WRONG_DENOM",
    },
    {
        "case_id": "fzt-fill-honest-observed-denom",
        "kind": "missing_filled_zero_wrong_denom",
        "reported_verdict": "PASS",
        "intended_n": 4,
        "observed_rows": [1.0, 2.0],
        "fill_missing_as_zero": False,
        "denom_policy": "observed",
        "reconciliation": {"expected_rows": 2, "actual_rows": 2, "unique_keys": 2},
        "expect_judge": "PASS",
        "expect_reason": "HONEST_DENOM_POLICY",
    },
    # --- ③ dedup collision ---
    {
        "case_id": "fzt-dedup-collision-false-pass",
        "kind": "dedup_key_collision",
        "reported_verdict": "PASS",
        "dedup_key_field": "id",
        "records": [
            {"id": "k1", "payload_fingerprint": "p-a"},
            {"id": "k1", "payload_fingerprint": "p-b"},
            {"id": "k2", "payload_fingerprint": "p-c"},
        ],
        "reconciliation": {"expected_rows": 3, "actual_rows": 2, "unique_keys": 2},
        "expect_judge": "FAIL",
        "expect_reason": "DEDUP_COLLISION_FALSE_ZERO",
    },
    {
        "case_id": "fzt-dedup-collision-detected",
        "kind": "dedup_key_collision",
        "reported_verdict": "FAIL",
        "dedup_key_field": "id",
        "records": [
            {"id": "x", "payload_fingerprint": "aa"},
            {"id": "x", "payload_fingerprint": "bb"},
        ],
        "reconciliation": {"expected_rows": 2, "actual_rows": 1, "unique_keys": 1},
        "expect_judge": "FAIL",
        "expect_reason": "DEDUP_COLLISION",
    },
    {
        "case_id": "fzt-dedup-honest",
        "kind": "dedup_key_collision",
        "reported_verdict": "PASS",
        "dedup_key_field": "id",
        "records": [
            {"id": "a", "payload_fingerprint": "p1"},
            {"id": "b", "payload_fingerprint": "p2"},
        ],
        "reconciliation": {"expected_rows": 2, "actual_rows": 2, "unique_keys": 2},
        "expect_judge": "PASS",
        "expect_reason": "HONEST_DEDUP",
    },
    # --- recon gate ---
    {
        "case_id": "fzt-recon-mismatch-false-pass",
        "kind": "recon_gate_only",
        "reported_verdict": "PASS",
        "reconciliation": {"expected_rows": 10, "actual_rows": 7, "unique_keys": 7},
        "expect_judge": "FAIL",
        "expect_reason": "RECON_MISMATCH_FALSE_PASS",
    },
    {
        "case_id": "fzt-recon-agree",
        "kind": "recon_gate_only",
        "reported_verdict": "PASS",
        "reconciliation": {"expected_rows": 5, "actual_rows": 5, "unique_keys": 5},
        "expect_judge": "PASS",
        "expect_reason": "RECON_COLUMNS_AGREE",
    },
    {
        "case_id": "fzt-recon-column-absent",
        "kind": "recon_gate_only",
        "reported_verdict": "PASS",
        "reconciliation": {"expected_rows": 5, "actual_rows": 5},
        "expect_judge": "FAIL",
        "expect_reason": "RECON_COLUMN_ABSENT",
    },
]


def main() -> int:
    results = []
    failures = []
    for case in CASES:
        receipt = {k: v for k, v in case.items() if k not in ("case_id", "expect_judge", "expect_reason")}
        out = judge(receipt)
        ok = out.get("judge") == case["expect_judge"] and out.get("reason_code") == case["expect_reason"]
        row = {
            "case_id": case["case_id"],
            "ok": ok,
            "expect_judge": case["expect_judge"],
            "expect_reason": case["expect_reason"],
            "got": out,
        }
        results.append(row)
        if not ok:
            failures.append(row)

    payload = {
        "fixture": "FALSE_ZERO_TRIAD",
        "version": "v0.1",
        "policy": "analyze_only REFERENCE_ONLY fictional_desensitized no_secrets",
        "credit": ["H"],
        "n_cases": len(CASES),
        "n_pass": len(CASES) - len(failures),
        "n_fail": len(failures),
        "results": results,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    payload["run_out_sha256"] = digest
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)
    print(text)
    print(f"META={'PASS' if not failures else 'FAIL'} cases={len(CASES)} fail={len(failures)}", file=sys.stderr)
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
