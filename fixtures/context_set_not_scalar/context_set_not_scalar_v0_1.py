#!/usr/bin/env python3
"""CONTEXT_SET_NOT_SCALAR v0.1

Structure-only fixture. Detects columns long assumed to be a single scalar
per epoch that silently become a set (cardinality > 1) without an error —
because uniqueness was never asserted.

Structure source: Jerry / Vermillion (EigenFlux). General fixture; no personal
attribution in rows. analyze_only. Stdlib only.
"""
from __future__ import annotations

import json
import sys
from typing import Any


def judge(receipt: dict[str, Any]) -> dict[str, Any]:
    kind = receipt.get("kind")

    if kind == "epoch_column":
        col = receipt.get("column")
        values = receipt.get("observed_values")
        asserted_unique = receipt.get("asserted_unique")
        reported_ok = receipt.get("reported_ok")

        if not isinstance(col, str) or not col:
            return {"judge": "FAIL", "reason_code": "COLUMN_MISSING"}
        if not isinstance(values, list):
            return {"judge": "FAIL", "reason_code": "VALUES_MISSING"}

        # Normalize to a set of stable string keys for cardinality
        uniq: set[str] = set()
        for v in values:
            if v is None:
                uniq.add("__null__")
            elif isinstance(v, (str, int, float, bool)):
                uniq.add(f"{type(v).__name__}:{v}")
            else:
                uniq.add(json.dumps(v, sort_keys=True, ensure_ascii=False))

        card = len(uniq)

        # Planted negative: cardinality > 1, never asserted unique, still reported OK
        if card > 1 and asserted_unique is not True and reported_ok is True:
            return {
                "judge": "FAIL",
                "reason_code": "CONTEXT_SET_NOT_SCALAR",
                "detail": {"column": col, "cardinality": card},
            }

        # Explicit uniqueness gate present and violated → must not report OK
        if card > 1 and asserted_unique is True and reported_ok is True:
            return {
                "judge": "FAIL",
                "reason_code": "UNIQUENESS_GATE_BYPASSED",
                "detail": {"column": col, "cardinality": card},
            }

        # Gate present, violation detected, report not OK → PASS
        if card > 1 and asserted_unique is True and reported_ok is False:
            return {"judge": "PASS", "reason_code": "UNIQUENESS_GATE_FIRED"}

        # True scalar (card == 1), reported OK → PASS
        if card == 1 and reported_ok is True:
            return {"judge": "PASS", "reason_code": "SCALAR_OK"}

        # Empty observation
        if card == 0:
            return {"judge": "FAIL", "reason_code": "EMPTY_OBSERVATION"}

        return {"judge": "PASS", "reason_code": "EPOCH_COLUMN_OK"}

    if kind == "multi_epoch_scan":
        epochs = receipt.get("epochs") or []
        if not isinstance(epochs, list) or not epochs:
            return {"judge": "FAIL", "reason_code": "EPOCHS_MISSING"}
        hits = []
        for ep in epochs:
            if not isinstance(ep, dict):
                continue
            vals = ep.get("observed_values")
            if not isinstance(vals, list):
                continue
            uniq = {json.dumps(v, sort_keys=True, default=str) for v in vals}
            if len(uniq) > 1 and ep.get("asserted_unique") is not True:
                hits.append(ep.get("epoch_id"))
        if hits and receipt.get("scan_reported_anomaly") is not True:
            return {
                "judge": "FAIL",
                "reason_code": "CONTEXT_SET_NOT_SCALAR",
                "detail": {"hit_epochs": hits},
            }
        if hits and receipt.get("scan_reported_anomaly") is True:
            return {"judge": "PASS", "reason_code": "SCAN_ANOMALY_FLAGGED"}
        return {"judge": "PASS", "reason_code": "SCAN_CLEAN"}

    return {"judge": "FAIL", "reason_code": "UNCLASSIFIED", "kind": kind}


FIXTURES = [
    {
        "case_id": "SET-SILENT-OK",
        "receipt": {
            "kind": "epoch_column",
            "column": "context_id",
            "observed_values": ["ctx_A_nineteen", "ctx_A_nineteen", "ctx_B_one"],
            "asserted_unique": False,
            "reported_ok": True,
        },
        "expect": "CONTEXT_SET_NOT_SCALAR",
    },
    {
        "case_id": "SET-TWO-DISTINCT",
        "receipt": {
            "kind": "epoch_column",
            "column": "context_id",
            "observed_values": ["ctx_X", "ctx_Y"],
            "asserted_unique": False,
            "reported_ok": True,
        },
        "expect": "CONTEXT_SET_NOT_SCALAR",
    },
    {
        "case_id": "SCALAR-OK",
        "receipt": {
            "kind": "epoch_column",
            "column": "context_id",
            "observed_values": ["ctx_only"] * 19,
            "asserted_unique": False,
            "reported_ok": True,
        },
        "expect": "SCALAR_OK",
    },
    {
        "case_id": "GATE-FIRED-OK",
        "receipt": {
            "kind": "epoch_column",
            "column": "context_id",
            "observed_values": ["a", "b"],
            "asserted_unique": True,
            "reported_ok": False,
        },
        "expect": "UNIQUENESS_GATE_FIRED",
    },
    {
        "case_id": "GATE-BYPASSED",
        "receipt": {
            "kind": "epoch_column",
            "column": "context_id",
            "observed_values": ["a", "b"],
            "asserted_unique": True,
            "reported_ok": True,
        },
        "expect": "UNIQUENESS_GATE_BYPASSED",
    },
    {
        "case_id": "EMPTY-OBS",
        "receipt": {
            "kind": "epoch_column",
            "column": "context_id",
            "observed_values": [],
            "asserted_unique": True,
            "reported_ok": False,
        },
        "expect": "EMPTY_OBSERVATION",
    },
    {
        "case_id": "SCAN-SILENT-HIT",
        "receipt": {
            "kind": "multi_epoch_scan",
            "epochs": [
                {
                    "epoch_id": "e1",
                    "observed_values": ["only"],
                    "asserted_unique": False,
                },
                {
                    "epoch_id": "e2",
                    "observed_values": ["p", "q"],
                    "asserted_unique": False,
                },
            ],
            "scan_reported_anomaly": False,
        },
        "expect": "CONTEXT_SET_NOT_SCALAR",
    },
    {
        "case_id": "SCAN-FLAGGED-OK",
        "receipt": {
            "kind": "multi_epoch_scan",
            "epochs": [
                {
                    "epoch_id": "e2",
                    "observed_values": ["p", "q"],
                    "asserted_unique": False,
                }
            ],
            "scan_reported_anomaly": True,
        },
        "expect": "SCAN_ANOMALY_FLAGGED",
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
        "version": "CONTEXT_SET_NOT_SCALAR/v0.1",
        "all_match": ok,
        "n": len(rows),
        "rows": rows,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
