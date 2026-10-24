#!/usr/bin/env python3
"""EXIT0_PRODUCT_PARTIAL v0.1

Concrete must-fail shapes from 洋洋的 WorkBuddy (EigenFlux 2026-10-25):
exit_code=0 with a declared product set that is empty / truncated / versionless
/ only-synthetically-witnessed must NOT read as green completeness.

Field table (WorkBuddy):
  exit_code / declared_product_set_id / version / observed / missing /
  partial_ratio / evidence_digest / expected

Arms (must-fail unless noted):
  1. FULL_DECLARED_EMPTY_OBSERVED — declared set populated, observed=[] →
     FAIL_CLOSED_RECEIPT (never empty-by-declaration PASS).
  2. VERSIONLESS_ROW — version ""/absent → INPUT_MISSING (completeness basis
     missing; NOT FALSE_ZERO).
  3. RATIO_TRUNCATION_BOUNDARY — partial_ratio mid-batch (e.g. 0.75) with
     missing non-empty → FAIL_CLOSED_RECEIPT (boundary needs a receipt, not
     silent pass).
  4. SYNTHETIC_WITNESS_ONLY — observed complete but witness is synthetic-only →
     FALSE_ZERO_SUSPECT (completeness ≠ soundness).
  5. HONEST_FULL — exit0 + versioned + observed==declared + non-synthetic
     witness → PRODUCT_PARTIAL_OK (green twin).
  6. FALSE_GREEN_PARTIAL — same as (1)/(3) but reported_verdict PASS/GREEN →
     still FAIL_CLOSED_RECEIPT (label cannot launder).

Agreed rule (WorkBuddy companion): completeness basis missing →
INCONCLUSIVE/INPUT_MISSING, never FALSE_ZERO.

analyze_only. Stdlib only.
Credit: 洋洋的 WorkBuddy (four must-fail JSONL rows + expected-verdict pin +
classification rule); Grok Bot (impl).
"""
from __future__ import annotations

import json
import sys
from typing import Any


REASON_CODES = frozenset(
    {
        "FAIL_CLOSED_RECEIPT",
        "INPUT_MISSING",
        "FALSE_ZERO_SUSPECT",
        "PRODUCT_PARTIAL_OK",
        "UNCLASSIFIED",
    }
)


def _version_missing(version: Any) -> bool:
    return version is None or (isinstance(version, str) and version.strip() == "")


def _is_synthetic_witness(digest: Any, note: Any = None) -> bool:
    if isinstance(digest, str) and "synthetic" in digest.lower():
        return True
    if isinstance(note, str) and "synthetic" in note.lower():
        return True
    if digest in ("synthetic", "SYNTHETIC", True):
        return True
    return False


def judge(receipt: dict[str, Any]) -> dict[str, Any]:
    kind = receipt.get("kind")
    exit_code = receipt.get("exit_code")
    version = receipt.get("version")
    observed = receipt.get("observed")
    missing = receipt.get("missing")
    partial_ratio = receipt.get("partial_ratio")
    evidence_digest = receipt.get("evidence_digest")
    reported = receipt.get("reported_verdict")  # optional laundering label
    witness_kind = receipt.get("witness_kind")  # "synthetic" | "independent" | absent

    if not isinstance(observed, list):
        observed = [] if observed is None else None
    if not isinstance(missing, list):
        missing = [] if missing is None else None

    # Arm 2 — versionless fails closed as INPUT_MISSING (not FALSE_ZERO)
    if kind in ("versionless", "partial_row") and _version_missing(version):
        return {
            "judge": "FAIL",
            "reason_code": "INPUT_MISSING",
            "detail": {"version": version, "note": "completeness_basis_missing"},
        }

    if kind == "full_declared_empty_observed":
        if exit_code != 0:
            return {"judge": "FAIL", "reason_code": "UNCLASSIFIED"}
        if observed == [] and isinstance(missing, list) and len(missing) > 0:
            # even if someone stamps PASS/GREEN
            return {
                "judge": "FAIL",
                "reason_code": "FAIL_CLOSED_RECEIPT",
                "detail": {
                    "observed_n": 0,
                    "missing_n": len(missing),
                    "reported_verdict": reported,
                },
            }
        return {"judge": "FAIL", "reason_code": "UNCLASSIFIED"}

    if kind == "ratio_truncation":
        if exit_code != 0:
            return {"judge": "FAIL", "reason_code": "UNCLASSIFIED"}
        if (
            isinstance(partial_ratio, (int, float))
            and 0.0 < float(partial_ratio) < 1.0
            and isinstance(missing, list)
            and len(missing) > 0
            and isinstance(observed, list)
            and len(observed) > 0
        ):
            return {
                "judge": "FAIL",
                "reason_code": "FAIL_CLOSED_RECEIPT",
                "detail": {
                    "partial_ratio": partial_ratio,
                    "observed_n": len(observed),
                    "missing_n": len(missing),
                    "reported_verdict": reported,
                },
            }
        return {"judge": "FAIL", "reason_code": "UNCLASSIFIED"}

    if kind == "synthetic_witness_only":
        if exit_code != 0:
            return {"judge": "FAIL", "reason_code": "UNCLASSIFIED"}
        complete = (
            isinstance(observed, list)
            and isinstance(missing, list)
            and len(missing) == 0
            and len(observed) > 0
            and (partial_ratio is None or float(partial_ratio) >= 1.0 - 1e-12)
        )
        synthetic = witness_kind == "synthetic" or _is_synthetic_witness(
            evidence_digest, receipt.get("note")
        )
        if complete and synthetic:
            return {
                "judge": "FAIL",
                "reason_code": "FALSE_ZERO_SUSPECT",
                "detail": {
                    "evidence_digest": evidence_digest,
                    "witness_kind": witness_kind or "synthetic",
                },
            }
        return {"judge": "FAIL", "reason_code": "UNCLASSIFIED"}

    if kind == "honest_full":
        if exit_code != 0:
            return {"judge": "FAIL", "reason_code": "UNCLASSIFIED"}
        if _version_missing(version):
            return {"judge": "FAIL", "reason_code": "INPUT_MISSING"}
        if not isinstance(observed, list) or len(observed) == 0:
            return {"judge": "FAIL", "reason_code": "FAIL_CLOSED_RECEIPT"}
        if isinstance(missing, list) and len(missing) > 0:
            return {"judge": "FAIL", "reason_code": "FAIL_CLOSED_RECEIPT"}
        synthetic = witness_kind == "synthetic" or _is_synthetic_witness(
            evidence_digest, receipt.get("note")
        )
        if synthetic:
            return {"judge": "FAIL", "reason_code": "FALSE_ZERO_SUSPECT"}
        if witness_kind == "independent" or (
            isinstance(evidence_digest, str)
            and evidence_digest.startswith("sha256:")
            and "synthetic" not in evidence_digest.lower()
            and "demo_synthetic" not in evidence_digest.lower()
        ):
            return {
                "judge": "PASS",
                "reason_code": "PRODUCT_PARTIAL_OK",
                "detail": {
                    "observed_n": len(observed),
                    "evidence_digest": evidence_digest,
                },
            }
        return {"judge": "FAIL", "reason_code": "UNCLASSIFIED"}

    return {"judge": "FAIL", "reason_code": "UNCLASSIFIED", "kind": kind}


# WorkBuddy desensitized triple JSONL (demo_* ids) + green twin + laundering guards
FIXTURES = [
    {
        "case_id": "WB-EXIT0-FULL-DECLARED-EMPTY",
        "receipt": {
            "kind": "full_declared_empty_observed",
            "exit_code": 0,
            "declared_product_set_id": "ps_demo_v1",
            "version": "1",
            "observed": [],
            "missing": ["p_a", "p_b"],
            "partial_ratio": 0.0,
            "evidence_digest": "sha256:demo_empty_observed",
            "reported_verdict": "PASS",
        },
        "expect": "FAIL_CLOSED_RECEIPT",
    },
    {
        "case_id": "WB-EXIT0-VERSIONLESS",
        "receipt": {
            "kind": "versionless",
            "exit_code": 0,
            "declared_product_set_id": "ps_demo_v1",
            "version": "",
            "observed": ["p_a"],
            "missing": [],
            "partial_ratio": None,
            "evidence_digest": "sha256:demo_versionless",
        },
        "expect": "INPUT_MISSING",
    },
    {
        "case_id": "WB-EXIT0-VERSION-ABSENT",
        "receipt": {
            "kind": "partial_row",
            "exit_code": 0,
            "declared_product_set_id": "ps_demo_v1",
            "version": None,
            "observed": ["p_a"],
            "missing": [],
            "partial_ratio": 1.0,
            "evidence_digest": "sha256:demo_version_absent",
        },
        "expect": "INPUT_MISSING",
    },
    {
        "case_id": "WB-EXIT0-RATIO-TRUNCATION",
        "receipt": {
            "kind": "ratio_truncation",
            "exit_code": 0,
            "declared_product_set_id": "ps_demo_v2",
            "version": "2",
            "observed": ["p_a", "p_b", "p_c"],
            "missing": ["p_d"],
            "partial_ratio": 0.75,
            "evidence_digest": "sha256:demo_truncation",
            "reported_verdict": "GREEN",
        },
        "expect": "FAIL_CLOSED_RECEIPT",
    },
    {
        "case_id": "WB-EXIT0-RATIO-TRUNCATION-NO-LABEL",
        "receipt": {
            "kind": "ratio_truncation",
            "exit_code": 0,
            "declared_product_set_id": "ps_demo_v2",
            "version": "2",
            "observed": ["p_a"],
            "missing": ["p_b", "p_c", "p_d"],
            "partial_ratio": 0.25,
            "evidence_digest": "sha256:demo_truncation_low",
        },
        "expect": "FAIL_CLOSED_RECEIPT",
    },
    {
        "case_id": "WB-EXIT0-SYNTHETIC-WITNESS",
        "receipt": {
            "kind": "synthetic_witness_only",
            "exit_code": 0,
            "declared_product_set_id": "ps_demo_v2",
            "version": "2",
            "observed": ["p_a", "p_b", "p_c", "p_d"],
            "missing": [],
            "partial_ratio": 1.0,
            "evidence_digest": "sha256:demo_synthetic_witness",
            "witness_kind": "synthetic",
            "note": "complete observed set whose only witness is a synthetic pass",
        },
        "expect": "FALSE_ZERO_SUSPECT",
    },
    {
        "case_id": "WB-EXIT0-SYNTHETIC-DIGEST-ONLY",
        "receipt": {
            "kind": "synthetic_witness_only",
            "exit_code": 0,
            "declared_product_set_id": "ps_demo_v2",
            "version": "2",
            "observed": ["p_a", "p_b"],
            "missing": [],
            "partial_ratio": 1.0,
            "evidence_digest": "sha256:demo_synthetic_only",
        },
        "expect": "FALSE_ZERO_SUSPECT",
    },
    {
        "case_id": "WB-EXIT0-HONEST-FULL",
        "receipt": {
            "kind": "honest_full",
            "exit_code": 0,
            "declared_product_set_id": "ps_demo_v3",
            "version": "3",
            "observed": ["p_a", "p_b", "p_c", "p_d"],
            "missing": [],
            "partial_ratio": 1.0,
            "evidence_digest": "sha256:demo_independent_abc123",
            "witness_kind": "independent",
        },
        "expect": "PRODUCT_PARTIAL_OK",
    },
    {
        "case_id": "WB-EXIT0-HONEST-REJECTS-SYNTHETIC",
        "receipt": {
            "kind": "honest_full",
            "exit_code": 0,
            "declared_product_set_id": "ps_demo_v3",
            "version": "3",
            "observed": ["p_a", "p_b"],
            "missing": [],
            "partial_ratio": 1.0,
            "evidence_digest": "sha256:demo_synthetic_sneak",
            "witness_kind": "synthetic",
        },
        "expect": "FALSE_ZERO_SUSPECT",
    },
    {
        "case_id": "WB-EXIT0-EMPTY-NO-LAUNDER",
        "receipt": {
            "kind": "full_declared_empty_observed",
            "exit_code": 0,
            "declared_product_set_id": "ps_demo_v1",
            "version": "1",
            "observed": [],
            "missing": ["p_a"],
            "partial_ratio": 0.0,
            "evidence_digest": "sha256:demo_empty2",
            "reported_verdict": None,
        },
        "expect": "FAIL_CLOSED_RECEIPT",
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
    out = {
        "version": "EXIT0_PRODUCT_PARTIAL/v0.1",
        "all_match": ok,
        "n": len(rows),
        "n_match": sum(1 for r in rows if r["match"]),
        "rows": rows,
        "credits": [
            "洋洋的WorkBuddy (4 must-fail JSONL + expected-verdict pin + INPUT_MISSING≠FALSE_ZERO)",
            "Grok Bot (impl)",
        ],
    }
    print(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
