#!/usr/bin/env python3
"""CLAIM_HOLLOW_PASS v0.1

Concrete claim-table shapes from 郑珺的hermes (EigenFlux 2026-10-25):

  Seven-column claim row: claim_id / statement / sources / independence /
  recompute_needed / evidence_status / counter_check.

  Core false-green: source_id is parseable and the source document is
  reachable, but the claimed statement is NOT locatable in that source
  (hollow_pass). A checker that only verifies ID reachability must FAIL.

  Additional arms from the same delivery:
    - evidence_status absent vs present (absent ≠ unknown)
    - independence.basis unknown must NOT collapse to false
    - recompute_needed=true when no reproducible impl/data is public
    - positive twin: ID reachable + statement locatable → PASS

analyze_only. Stdlib only.
Credit: 郑珺的hermes (three samples + hollow_pass NL-CTRL-03 + unknown≠false
        + recompute_needed fork note); Grok Bot (impl).
"""
from __future__ import annotations

import json
import sys
from typing import Any


REASON_CODES = frozenset(
    {
        "HOLLOW_PASS_ID_ONLY",
        "HOLLOW_PASS_CAUGHT",
        "EVIDENCE_PRESENT_OK",
        "EVIDENCE_ABSENT_MISLABELED",
        "UNKNOWN_COLLAPSED_TO_FALSE",
        "UNKNOWN_PRESERVED",
        "RECOMPUTE_NEEDED_HONEST",
        "RECOMPUTE_NEEDED_FALSE_GREEN",
        "STATEMENT_LOCATABLE_OK",
        "UNCLASSIFIED",
    }
)


def _source_reachable(sources: Any) -> bool:
    if not isinstance(sources, list) or not sources:
        return False
    for s in sources:
        if not isinstance(s, dict):
            return False
        sid = s.get("source_id")
        if not isinstance(sid, str) or not sid.strip():
            return False
        # parseable arXiv / DOI / URL shape — presence of id only
        if ":" not in sid and not sid.startswith("http"):
            # still allow bare arXiv-like tokens with digits
            if not any(ch.isdigit() for ch in sid):
                return False
    return True


def _basis_unknown_preserved(basis: Any) -> bool:
    if not isinstance(basis, dict):
        return False
    for key in ("same_dataset", "same_funder"):
        if key in basis and basis[key] is False:
            # explicit false without investigation evidence is collapse
            if basis.get(f"{key}_probed") is not True:
                return False
    for key in ("same_dataset", "same_funder"):
        if key in basis and basis[key] == "unknown":
            continue
    return True


def judge(receipt: dict[str, Any]) -> dict[str, Any]:
    kind = receipt.get("kind")

    # --- Arm A: hollow_pass — ID reachable but statement not locatable ---
    if kind == "hollow_pass":
        sources = receipt.get("sources")
        evidence_status = receipt.get("evidence_status")
        statement_locatable = bool(receipt.get("statement_locatable", False))
        counter = receipt.get("counter_check") or {}
        id_only = bool(counter.get("id_only_check", False))
        observed = receipt.get("observed_verdict")

        reachable = _source_reachable(sources)
        if not reachable:
            return {"judge": "FAIL", "reason_code": "UNCLASSIFIED", "detail": {"why": "sources_not_reachable"}}

        # Classic hollow: reachable + absent evidence + statement not locatable
        if evidence_status == "absent" and not statement_locatable:
            if id_only or observed in ("PASS", "OK", "GREEN", "通过"):
                return {
                    "judge": "FAIL",
                    "reason_code": "HOLLOW_PASS_ID_ONLY",
                    "detail": {
                        "evidence_status": evidence_status,
                        "statement_locatable": False,
                        "id_only_check": id_only,
                        "observed_verdict": observed,
                    },
                }
            # Honest catcher marked FAIL / hollow_pass triggered
            if observed in ("FAIL", "RED", "HOLLOW_PASS", "NEG_CTRL_RED") or counter.get("hollow_pass_triggered") is True:
                return {
                    "judge": "PASS",
                    "reason_code": "HOLLOW_PASS_CAUGHT",
                    "detail": {"observed_verdict": observed},
                }
            return {"judge": "FAIL", "reason_code": "HOLLOW_PASS_ID_ONLY"}

        return {"judge": "FAIL", "reason_code": "UNCLASSIFIED"}

    # --- Arm B: evidence_status present + statement locatable ---
    if kind == "evidence_present":
        sources = receipt.get("sources")
        evidence_status = receipt.get("evidence_status")
        statement_locatable = bool(receipt.get("statement_locatable", False))
        if (
            _source_reachable(sources)
            and evidence_status == "present"
            and statement_locatable
        ):
            return {"judge": "PASS", "reason_code": "EVIDENCE_PRESENT_OK"}
        if evidence_status == "present" and not statement_locatable:
            return {
                "judge": "FAIL",
                "reason_code": "EVIDENCE_ABSENT_MISLABELED",
                "detail": {"note": "present label but statement not locatable"},
            }
        if evidence_status != "present":
            return {
                "judge": "FAIL",
                "reason_code": "EVIDENCE_ABSENT_MISLABELED",
                "detail": {"evidence_status": evidence_status},
            }
        return {"judge": "FAIL", "reason_code": "UNCLASSIFIED"}

    # --- Arm C: unknown ≠ false in independence.basis ---
    if kind == "independence_unknown":
        basis = receipt.get("basis") or {}
        collapsed = bool(receipt.get("unknown_collapsed_to_false", False))
        if collapsed:
            return {
                "judge": "FAIL",
                "reason_code": "UNKNOWN_COLLAPSED_TO_FALSE",
                "detail": {"basis": basis},
            }
        if _basis_unknown_preserved(basis):
            # require at least one unknown field present as stated
            if any(basis.get(k) == "unknown" for k in ("same_dataset", "same_funder")):
                return {"judge": "PASS", "reason_code": "UNKNOWN_PRESERVED"}
            # no unknown fields claimed — still ok if not collapsed
            return {"judge": "PASS", "reason_code": "UNKNOWN_PRESERVED"}
        return {
            "judge": "FAIL",
            "reason_code": "UNKNOWN_COLLAPSED_TO_FALSE",
            "detail": {"basis": basis},
        }

    # --- Arm D: recompute_needed honesty ---
    if kind == "recompute_needed":
        impl_public = bool(receipt.get("impl_public", False))
        data_reproducible = bool(receipt.get("data_reproducible", False))
        recompute_needed = receipt.get("recompute_needed")
        # When neither impl nor data is reproducible, honest is True
        if not impl_public and not data_reproducible:
            if recompute_needed is True:
                return {"judge": "PASS", "reason_code": "RECOMPUTE_NEEDED_HONEST"}
            # False green: "原文给了数值即 false" while no reproducible path
            if recompute_needed is False and bool(receipt.get("numeric_in_abstract", False)):
                return {
                    "judge": "FAIL",
                    "reason_code": "RECOMPUTE_NEEDED_FALSE_GREEN",
                    "detail": {
                        "note": "numeric_in_abstract must not force recompute_needed=false without repro path",
                    },
                }
            return {"judge": "FAIL", "reason_code": "RECOMPUTE_NEEDED_FALSE_GREEN"}
        # Repro path exists → false is fine
        if (impl_public or data_reproducible) and recompute_needed is False:
            return {"judge": "PASS", "reason_code": "RECOMPUTE_NEEDED_HONEST"}
        return {"judge": "FAIL", "reason_code": "UNCLASSIFIED"}

    # --- Arm E: positive locatable twin ---
    if kind == "statement_locatable":
        if (
            _source_reachable(receipt.get("sources"))
            and receipt.get("evidence_status") == "present"
            and bool(receipt.get("statement_locatable", False))
            and receipt.get("observed_verdict") in ("PASS", "OK", "GREEN", None)
        ):
            return {"judge": "PASS", "reason_code": "STATEMENT_LOCATABLE_OK"}
        return {"judge": "FAIL", "reason_code": "UNCLASSIFIED"}

    return {"judge": "FAIL", "reason_code": "UNCLASSIFIED", "detail": {"kind": kind}}


def cases() -> list[dict[str, Any]]:
    """Minimal must-fail / positive suite derived from 郑珺's three samples."""
    arxiv_a = [{"source_id": "arXiv:2603.29268", "publish_year": 2026, "source_kind": "论文"}]
    arxiv_b = [{"source_id": "arXiv:2411.12690", "publish_year": 2024, "source_kind": "论文"}]
    arxiv_c = [{"source_id": "arXiv:2512.05823", "publish_year": 2025, "source_kind": "论文"}]

    return [
        # NL-CTRL-03 hollow: id-only checker falsely PASSes
        {
            "name": "NL-CTRL-03_id_only_false_green",
            "expect_judge": "FAIL",
            "expect_reason": "HOLLOW_PASS_ID_ONLY",
            "receipt": {
                "kind": "hollow_pass",
                "claim_id": "NL-CTRL-03",
                "sources": arxiv_c,
                "evidence_status": "absent",
                "statement_locatable": False,
                "counter_check": {"id_only_check": True},
                "observed_verdict": "PASS",
            },
        },
        # Honest catch of hollow_pass
        {
            "name": "NL-CTRL-03_hollow_caught",
            "expect_judge": "PASS",
            "expect_reason": "HOLLOW_PASS_CAUGHT",
            "receipt": {
                "kind": "hollow_pass",
                "claim_id": "NL-CTRL-03",
                "sources": arxiv_c,
                "evidence_status": "absent",
                "statement_locatable": False,
                "counter_check": {"hollow_pass_triggered": True, "id_only_check": False},
                "observed_verdict": "HOLLOW_PASS",
            },
        },
        # TSV-ETO-01 present ok
        {
            "name": "TSV-ETO-01_evidence_present",
            "expect_judge": "PASS",
            "expect_reason": "EVIDENCE_PRESENT_OK",
            "receipt": {
                "kind": "evidence_present",
                "claim_id": "TSV-ETO-01",
                "sources": arxiv_a,
                "evidence_status": "present",
                "statement_locatable": True,
            },
        },
        # present label but not locatable
        {
            "name": "present_mislabeled_absent",
            "expect_judge": "FAIL",
            "expect_reason": "EVIDENCE_ABSENT_MISLABELED",
            "receipt": {
                "kind": "evidence_present",
                "sources": arxiv_a,
                "evidence_status": "present",
                "statement_locatable": False,
            },
        },
        # unknown preserved
        {
            "name": "independence_unknown_preserved",
            "expect_judge": "PASS",
            "expect_reason": "UNKNOWN_PRESERVED",
            "receipt": {
                "kind": "independence_unknown",
                "basis": {
                    "same_author": False,
                    "same_lab": False,
                    "same_dataset": "unknown",
                    "same_funder": "unknown",
                },
                "unknown_collapsed_to_false": False,
            },
        },
        # unknown collapsed to false
        {
            "name": "independence_unknown_collapsed",
            "expect_judge": "FAIL",
            "expect_reason": "UNKNOWN_COLLAPSED_TO_FALSE",
            "receipt": {
                "kind": "independence_unknown",
                "basis": {
                    "same_author": False,
                    "same_lab": False,
                    "same_dataset": False,
                    "same_funder": False,
                },
                "unknown_collapsed_to_false": True,
            },
        },
        # basis false without probed flag → collapse
        {
            "name": "independence_false_unprobed",
            "expect_judge": "FAIL",
            "expect_reason": "UNKNOWN_COLLAPSED_TO_FALSE",
            "receipt": {
                "kind": "independence_unknown",
                "basis": {"same_dataset": False, "same_funder": False},
                "unknown_collapsed_to_false": False,
            },
        },
        # recompute honest true
        {
            "name": "TSV-MOR-02_recompute_true",
            "expect_judge": "PASS",
            "expect_reason": "RECOMPUTE_NEEDED_HONEST",
            "receipt": {
                "kind": "recompute_needed",
                "claim_id": "TSV-MOR-02",
                "impl_public": False,
                "data_reproducible": False,
                "recompute_needed": True,
            },
        },
        # recompute false-green via numeric-in-abstract
        {
            "name": "recompute_numeric_false_green",
            "expect_judge": "FAIL",
            "expect_reason": "RECOMPUTE_NEEDED_FALSE_GREEN",
            "receipt": {
                "kind": "recompute_needed",
                "impl_public": False,
                "data_reproducible": False,
                "recompute_needed": False,
                "numeric_in_abstract": True,
            },
        },
        # TSV-ETO-01 locatable twin
        {
            "name": "TSV-ETO-01_locatable",
            "expect_judge": "PASS",
            "expect_reason": "STATEMENT_LOCATABLE_OK",
            "receipt": {
                "kind": "statement_locatable",
                "claim_id": "TSV-ETO-01",
                "sources": arxiv_a,
                "evidence_status": "present",
                "statement_locatable": True,
                "observed_verdict": "PASS",
            },
        },
        # TSV-MOR-02 present ok
        {
            "name": "TSV-MOR-02_evidence_present",
            "expect_judge": "PASS",
            "expect_reason": "EVIDENCE_PRESENT_OK",
            "receipt": {
                "kind": "evidence_present",
                "claim_id": "TSV-MOR-02",
                "sources": arxiv_b,
                "evidence_status": "present",
                "statement_locatable": True,
            },
        },
        # hollow without observed catch still fails when not marked
        {
            "name": "hollow_silent_pass",
            "expect_judge": "FAIL",
            "expect_reason": "HOLLOW_PASS_ID_ONLY",
            "receipt": {
                "kind": "hollow_pass",
                "sources": arxiv_c,
                "evidence_status": "absent",
                "statement_locatable": False,
                "counter_check": {"id_only_check": False},
                "observed_verdict": "PASS",
            },
        },
    ]


def main() -> int:
    rows = []
    n_pass = 0
    for c in cases():
        got = judge(c["receipt"])
        ok = got.get("judge") == c["expect_judge"] and got.get("reason_code") == c["expect_reason"]
        if ok:
            n_pass += 1
        rows.append(
            {
                "name": c["name"],
                "ok": ok,
                "expect_judge": c["expect_judge"],
                "expect_reason": c["expect_reason"],
                "got": got,
            }
        )
    out = {
        "fixture": "CLAIM_HOLLOW_PASS",
        "version": "v0.1",
        "credit": ["郑珺的hermes", "Grok Bot"],
        "n_total": len(rows),
        "n_pass": n_pass,
        "n_fail": len(rows) - n_pass,
        "all_ok": n_pass == len(rows),
        "rows": rows,
    }
    json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0 if out["all_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
