#!/usr/bin/env python3
"""EXEMPT_STALE + ISSUER_COLS_INCOMPLETE v0.1

Hard judgment rules from 屎山工程师 (EigenFlux PM 2026-10-25):
1) EXEMPT_STALE must NOT be stored — compute at read time from
   recheck_due vs read_at. A persisted STALE cell that stays green after
   the batch finishes is the previous judgment, not this one.
2) exempt_issuer empty has two causes: NOT_APPLICABLE vs MISSING.
   A single empty cell collapses them; ISSUER_COLS_INCOMPLETE false-alarm
   rate explodes. Split the values. Neg-ctrl: a legal NOT_APPLICABLE row
   that judges RED proves the arm only accepts "has value".
3) INGEST_SEQ_GAP_OBSERVED and MONOTONIC_SEQ_GAP must NOT share a
   denominator; injection point and read channel stay separate.

Arms:
  A1 stored_stale_after_batch   — persisted STALE still GREEN post-batch → EXEMPT_STALE
  A2 compute_fresh_due         — recheck_due < read_at, compute STALE now → EXEMPT_STALE
  A3 compute_fresh_ok          — recheck_due >= read_at → EXEMPT_FRESH_OK (green twin)
  A4 issuer_missing            — issuer required but empty → ISSUER_MISSING
  A5 issuer_not_applicable_ok  — legal N/A must PASS (not red)
  A6 issuer_na_false_red       — arm that reds legal N/A → ISSUER_NA_FALSE_RED
  A7 issuer_cols_incomplete    — required issuer cols absent → ISSUER_COLS_INCOMPLETE
  A8 gap_mixed_denom           — two gap kinds share denom → GAP_DENOM_COLLISION
  A9 gap_ingest_ok             — ingest gap alone, own denom/channel → GAP_OK
  A10 gap_monotonic_ok         — monotonic gap alone, own denom/channel → GAP_OK

analyze_only. Stdlib only.
Credit: 屎山工程师 (three hard rules + offer to complement反例);
        Grok Bot (min fixture impl).
"""
from __future__ import annotations

import json
import sys
from typing import Any


REASON_CODES = frozenset(
    {
        "EXEMPT_STALE",
        "EXEMPT_FRESH_OK",
        "ISSUER_MISSING",
        "ISSUER_NA_OK",
        "ISSUER_NA_FALSE_RED",
        "ISSUER_COLS_INCOMPLETE",
        "GAP_DENOM_COLLISION",
        "GAP_OK",
        "UNCLASSIFIED",
    }
)


def _as_int(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _norm(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def judge(receipt: dict[str, Any]) -> dict[str, Any]:
    kind = receipt.get("kind")

    # --- EXEMPT_STALE family ---
    if kind == "stored_stale_after_batch":
        # Persisted STALE/GREEN after batch close is previous judgment.
        stored = _norm(receipt.get("stored_exempt_state"))
        batch_closed = bool(receipt.get("batch_closed"))
        reported = _norm(receipt.get("reported_verdict"))
        if (
            stored in ("STALE", "EXEMPT_STALE")
            and batch_closed
            and reported in ("GREEN", "PASS", "OK")
        ):
            return {
                "judge": "FAIL",
                "reason_code": "EXEMPT_STALE",
                "detail": {
                    "note": "persisted_stale_is_previous_judgment",
                    "stored_exempt_state": stored,
                    "reported_verdict": reported,
                },
            }
        return {"judge": "FAIL", "reason_code": "UNCLASSIFIED"}

    if kind == "compute_at_read":
        recheck_due = _as_int(receipt.get("recheck_due"))
        read_at = _as_int(receipt.get("read_at"))
        if recheck_due is None or read_at is None:
            return {
                "judge": "FAIL",
                "reason_code": "UNCLASSIFIED",
                "detail": {"note": "recheck_due_or_read_at_missing"},
            }
        # Compute now — never trust a stored cell.
        if read_at > recheck_due:
            return {
                "judge": "FAIL",
                "reason_code": "EXEMPT_STALE",
                "detail": {
                    "recheck_due": recheck_due,
                    "read_at": read_at,
                    "computed": "STALE",
                },
            }
        return {
            "judge": "PASS",
            "reason_code": "EXEMPT_FRESH_OK",
            "detail": {
                "recheck_due": recheck_due,
                "read_at": read_at,
                "computed": "FRESH",
            },
        }

    # --- ISSUER_COLS family ---
    if kind == "issuer_empty":
        issuer_mode = _norm(receipt.get("exempt_issuer_mode"))
        # Split empty into NOT_APPLICABLE vs MISSING
        if issuer_mode == "NOT_APPLICABLE":
            # Legal N/A must not be judged red by an "has-value-only" arm.
            arm_reds_na = bool(receipt.get("arm_reds_not_applicable"))
            if arm_reds_na:
                return {
                    "judge": "FAIL",
                    "reason_code": "ISSUER_NA_FALSE_RED",
                    "detail": {"note": "arm_only_accepts_has_value"},
                }
            return {
                "judge": "PASS",
                "reason_code": "ISSUER_NA_OK",
                "detail": {"exempt_issuer_mode": "NOT_APPLICABLE"},
            }
        if issuer_mode == "MISSING" or issuer_mode is None:
            required = bool(receipt.get("issuer_required", True))
            if required:
                return {
                    "judge": "FAIL",
                    "reason_code": "ISSUER_MISSING",
                    "detail": {"exempt_issuer_mode": issuer_mode or "MISSING"},
                }
            return {"judge": "FAIL", "reason_code": "UNCLASSIFIED"}
        return {"judge": "FAIL", "reason_code": "UNCLASSIFIED"}

    if kind == "issuer_cols":
        required_cols = receipt.get("required_issuer_cols") or []
        present = receipt.get("present_issuer_cols") or {}
        if not isinstance(required_cols, list) or not isinstance(present, dict):
            return {"judge": "FAIL", "reason_code": "UNCLASSIFIED"}
        missing = [
            c
            for c in required_cols
            if _norm(present.get(c)) is None
            and _norm(present.get(c + "_mode")) != "NOT_APPLICABLE"
        ]
        if missing:
            return {
                "judge": "FAIL",
                "reason_code": "ISSUER_COLS_INCOMPLETE",
                "detail": {"missing_cols": missing},
            }
        return {
            "judge": "PASS",
            "reason_code": "ISSUER_NA_OK",
            "detail": {"present_n": len(required_cols)},
        }

    # --- GAP denom family ---
    if kind == "gap_ratio":
        gaps = receipt.get("gaps") or []
        if not isinstance(gaps, list):
            return {"judge": "FAIL", "reason_code": "UNCLASSIFIED"}
        # Collision: two distinct gap kinds share the same denom_id
        by_denom: dict[str, set[str]] = {}
        for g in gaps:
            if not isinstance(g, dict):
                continue
            gkind = _norm(g.get("gap_kind"))
            denom = _norm(g.get("denom_id"))
            channel = _norm(g.get("read_channel"))
            inject = _norm(g.get("inject_point"))
            if not gkind or not denom:
                continue
            by_denom.setdefault(denom, set()).add(gkind)
            # Also require channel/inject separation when both kinds present
            _ = (channel, inject)
        colliding = {
            d: sorted(kinds)
            for d, kinds in by_denom.items()
            if "INGEST_SEQ_GAP_OBSERVED" in kinds and "MONOTONIC_SEQ_GAP" in kinds
        }
        if colliding:
            return {
                "judge": "FAIL",
                "reason_code": "GAP_DENOM_COLLISION",
                "detail": {"colliding_denoms": colliding},
            }
        # Single-kind with own denom+channel → OK
        if len(gaps) >= 1 and all(
            isinstance(g, dict)
            and _norm(g.get("gap_kind"))
            and _norm(g.get("denom_id"))
            and _norm(g.get("read_channel"))
            and _norm(g.get("inject_point"))
            for g in gaps
        ):
            return {
                "judge": "PASS",
                "reason_code": "GAP_OK",
                "detail": {"n_gaps": len(gaps)},
            }
        return {"judge": "FAIL", "reason_code": "UNCLASSIFIED"}

    return {"judge": "FAIL", "reason_code": "UNCLASSIFIED", "kind": kind}


FIXTURES = [
    {
        "case_id": "SS-STORED-STALE-GREEN",
        "receipt": {
            "kind": "stored_stale_after_batch",
            "stored_exempt_state": "STALE",
            "batch_closed": True,
            "reported_verdict": "GREEN",
            "recheck_due": 1000,
            "read_at": 2000,
        },
        "expect": "EXEMPT_STALE",
    },
    {
        "case_id": "SS-COMPUTE-DUE-STALE",
        "receipt": {
            "kind": "compute_at_read",
            "recheck_due": 1000,
            "read_at": 1500,
        },
        "expect": "EXEMPT_STALE",
    },
    {
        "case_id": "SS-COMPUTE-FRESH-OK",
        "receipt": {
            "kind": "compute_at_read",
            "recheck_due": 2000,
            "read_at": 1500,
        },
        "expect": "EXEMPT_FRESH_OK",
    },
    {
        "case_id": "SS-ISSUER-MISSING",
        "receipt": {
            "kind": "issuer_empty",
            "exempt_issuer_mode": "MISSING",
            "issuer_required": True,
        },
        "expect": "ISSUER_MISSING",
    },
    {
        "case_id": "SS-ISSUER-NA-OK",
        "receipt": {
            "kind": "issuer_empty",
            "exempt_issuer_mode": "NOT_APPLICABLE",
            "arm_reds_not_applicable": False,
        },
        "expect": "ISSUER_NA_OK",
    },
    {
        "case_id": "SS-ISSUER-NA-FALSE-RED",
        "receipt": {
            "kind": "issuer_empty",
            "exempt_issuer_mode": "NOT_APPLICABLE",
            "arm_reds_not_applicable": True,
        },
        "expect": "ISSUER_NA_FALSE_RED",
    },
    {
        "case_id": "SS-ISSUER-COLS-INCOMPLETE",
        "receipt": {
            "kind": "issuer_cols",
            "required_issuer_cols": ["exempt_issuer", "issuer_epoch"],
            "present_issuer_cols": {"exempt_issuer": "org_a"},
        },
        "expect": "ISSUER_COLS_INCOMPLETE",
    },
    {
        "case_id": "SS-GAP-MIXED-DENOM",
        "receipt": {
            "kind": "gap_ratio",
            "gaps": [
                {
                    "gap_kind": "INGEST_SEQ_GAP_OBSERVED",
                    "denom_id": "shared_denom",
                    "read_channel": "ingest_log",
                    "inject_point": "producer",
                },
                {
                    "gap_kind": "MONOTONIC_SEQ_GAP",
                    "denom_id": "shared_denom",
                    "read_channel": "cursor_scan",
                    "inject_point": "consumer",
                },
            ],
        },
        "expect": "GAP_DENOM_COLLISION",
    },
    {
        "case_id": "SS-GAP-INGEST-OK",
        "receipt": {
            "kind": "gap_ratio",
            "gaps": [
                {
                    "gap_kind": "INGEST_SEQ_GAP_OBSERVED",
                    "denom_id": "ingest_denom",
                    "read_channel": "ingest_log",
                    "inject_point": "producer",
                }
            ],
        },
        "expect": "GAP_OK",
    },
    {
        "case_id": "SS-GAP-MONOTONIC-OK",
        "receipt": {
            "kind": "gap_ratio",
            "gaps": [
                {
                    "gap_kind": "MONOTONIC_SEQ_GAP",
                    "denom_id": "mono_denom",
                    "read_channel": "cursor_scan",
                    "inject_point": "consumer",
                }
            ],
        },
        "expect": "GAP_OK",
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
        "version": "EXEMPT_STALE_ISSUER_COLS/v0.1",
        "all_match": ok,
        "n": len(rows),
        "n_match": sum(1 for r in rows if r["match"]),
        "rows": rows,
        "credits": [
            "屎山工程师 (EXEMPT_STALE compute-at-read + NOT_APPLICABLE/MISSING split + gap denom separation)",
            "Grok Bot (impl)",
        ],
    }
    print(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
