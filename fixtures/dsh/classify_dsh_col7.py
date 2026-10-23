#!/usr/bin/env python3
"""classify_dsh_col7.py v0.1 — credit DSH (EigenFlux)

Seven-column discard/index receipt judge. Column 7 = raw.index_attempt.
Batch B (independent of r1–r8) freezes five distinct conclusions that
the first six columns alone cannot separate.

Hard rules (DSH 2026-10-23):
  - audit_retain_s >= hot_ttl_s AND >= longest receipt backfill window
  - pin protects hot bucket only; audit TTL expiry → AUDIT_EXPIRED (not PINNED)
  - hot is diagnostic only; verdict never depends on hot alone
  - receipt null rows MUST NOT be TTL_OK
  - b3/b4 identical on cols 1–6; only col7 (attempt=seq2 vs null) splits
    INDEX_LOST vs NEVER_INDEXED

analyze_only. Stdlib only. No network.
"""
from __future__ import annotations
from typing import Any, Optional


def classify_dsh_col7(row: dict[str, Any]) -> dict[str, Any]:
    """Return {verdict, reason_code, notes}.

    Required keys (may be null): key_hash, epoch, hot, raw, receipt,
    raw.index_attempt. receipt shape when present:
      {ts, reason, signer, relative_ttl?}  — missing any of ts/reason/signer
      → RECEIPT_INCOMPLETE (cannot be TTL_OK).
    """
    hot = row.get("hot")  # diagnostic
    raw = row.get("raw")
    receipt = row.get("receipt")
    attempt = row.get("raw.index_attempt")
    pinned = bool(row.get("pinned") or (isinstance(hot, dict) and hot.get("pin")))

    notes: list[str] = []
    if hot is not None:
        notes.append("hot_present_diagnostic_only")

    # AUDIT_EXPIRED: pinned or not, audit TTL fired, no usable receipt
    if row.get("audit_ttl_expired"):
        return {
            "verdict": "FAIL",
            "reason_code": "AUDIT_EXPIRED",
            "notes": notes + ["legal_audit_expiry_not_pin_anomaly"],
        }

    # PINNED_EVICTED: hot was pinned yet removed; receipt says PINNED_EVICTED
    if (
        pinned
        and isinstance(receipt, dict)
        and receipt.get("reason") == "PINNED_EVICTED"
    ):
        return {
            "verdict": "FAIL",
            "reason_code": "PINNED_EVICTED",
            "notes": notes + ["confirmed_anomaly_hot_pin_still_evicted"],
        }

    # RAW_LOST_AFTER_RECEIPT: raw null but receipt claims TTL_OK-ish presence
    if raw is None and isinstance(receipt, dict) and _receipt_complete(receipt):
        if receipt.get("reason") in ("TTL_OK", "rel+1", "rel+1 TTL") or receipt.get(
            "relative_ttl"
        ) == 1:
            return {
                "verdict": "FAIL",
                "reason_code": "RAW_LOST_AFTER_RECEIPT",
                "notes": notes
                + ["requires_audit_retain_ge_hot_ttl_and_backfill_window"],
            }

    # INDEX_LOST vs NEVER_INDEXED — identical on cols1–6; split on col7
    if hot in (None, False, {}) and raw is not None and receipt is None:
        if attempt is None:
            return {
                "verdict": "FAIL",
                "reason_code": "NEVER_INDEXED",
                "notes": notes + ["col7_null_separates_from_INDEX_LOST"],
            }
        return {
            "verdict": "FAIL",
            "reason_code": "INDEX_LOST",
            "notes": notes + [f"col7_attempt={attempt}"],
        }

    # TTL_OK only when receipt complete AND raw present AND not audit-expired
    if (
        raw is not None
        and isinstance(receipt, dict)
        and _receipt_complete(receipt)
        and not row.get("audit_ttl_expired")
    ):
        if receipt.get("reason") in ("TTL_OK", "rel+1", "rel+1 TTL") or receipt.get(
            "relative_ttl"
        ) == 1:
            return {"verdict": "PASS", "reason_code": "TTL_OK", "notes": notes}

    if isinstance(receipt, dict) and not _receipt_complete(receipt):
        return {
            "verdict": "FAIL",
            "reason_code": "RECEIPT_INCOMPLETE",
            "notes": notes + ["ts_reason_signer_required"],
        }

    return {
        "verdict": "UNKNOWN",
        "reason_code": "UNCLASSIFIED",
        "notes": notes + ["no_rule_fired"],
    }


def _receipt_complete(receipt: dict[str, Any]) -> bool:
    return all(receipt.get(k) not in (None, "") for k in ("ts", "reason", "signer"))


# Batch B frozen rows (DSH) — independent of r1–r8
BATCH_B = [
    {
        "id": "b1",
        "key_hash": "k9c",
        "epoch": 2,
        "hot": {"present": True},
        "raw": {"blob": "x"},
        "receipt": {"ts": 1, "reason": "TTL_OK", "signer": "dsh", "relative_ttl": 1},
        "raw.index_attempt": "seq7",
        "expect": "TTL_OK",
    },
    {
        "id": "b2",
        "key_hash": "k3d",
        "epoch": 6,
        "hot": {"present": True, "pin": True},
        "pinned": True,
        "raw": {"blob": "x"},
        "receipt": {
            "ts": 1,
            "reason": "PINNED_EVICTED",
            "signer": "dsh",
            "relative_ttl": 0,
        },
        "raw.index_attempt": "seq4",
        "expect": "PINNED_EVICTED",
    },
    {
        "id": "b3",
        "key_hash": "k4e",
        "epoch": 1,
        "hot": None,
        "raw": {"blob": "x"},
        "receipt": None,
        "raw.index_attempt": "seq2",
        "expect": "INDEX_LOST",
    },
    {
        "id": "b4",
        "key_hash": "k5f",
        "epoch": 1,
        "hot": None,
        "raw": {"blob": "x"},
        "receipt": None,
        "raw.index_attempt": None,
        "expect": "NEVER_INDEXED",
    },
    {
        "id": "b5",
        "key_hash": "k6g",
        "epoch": 3,
        "hot": {"present": True, "pin": True},
        "pinned": True,
        "raw": {"blob": "x"},
        "receipt": None,
        "audit_ttl_expired": True,
        "raw.index_attempt": "seq1",
        "expect": "AUDIT_EXPIRED",
    },
    {
        "id": "b6",
        "key_hash": "k7h",
        "epoch": 4,
        "hot": {"present": True},
        "raw": None,
        "receipt": {"ts": 1, "reason": "TTL_OK", "signer": "dsh", "relative_ttl": 1},
        "raw.index_attempt": "seq3",
        "expect": "RAW_LOST_AFTER_RECEIPT",
    },
]


def self_check() -> bool:
    ok = True
    for row in BATCH_B:
        got = classify_dsh_col7(row)
        match = got["reason_code"] == row["expect"]
        print(f"{row['id']} expect={row['expect']} got={got['reason_code']} ok={match}")
        ok = ok and match
    # hard invariant: receipt-null must never be TTL_OK
    for row in BATCH_B:
        if row.get("receipt") is None:
            g = classify_dsh_col7(row)
            if g["reason_code"] == "TTL_OK":
                print(f"INVARIANT FAIL: {row['id']} receipt-null → TTL_OK")
                ok = False
    return ok


if __name__ == "__main__":
    import sys

    sys.exit(0 if self_check() else 1)
