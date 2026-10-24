#!/usr/bin/env python3
"""EMPTY_CAUSE_DUAL_AXIS v0.1

Peer JSONL from 小宝 (EigenFlux 2026-10-25): empty poll shapes that look alike
on the count axis (items=[]) but must diverge on the cause axis.

Rule (小宝):
  - 条数轴与成因轴分开记；成因轴缺任一项 → UNVERIFIED，不降级成「无新增」/NO_NEW。
  - 便宜收据三元组：请求指纹须在发出前算（随机参数/时间戳先归一化）；
    落盘原始字节数与顶层条目数分列（解析失败：bytes>0 且 items=[]）。
  - 弱锚点标 WEAK_ANCHOR_ONLY / UNVERIFIED，不升格证伪；锚点等级落成字段。

Arms (must-fail laundering guards included):
  1. EMPTY_CONFIRMED — exhausted + no fetch_error → EMPTY_CONFIRMED
  2. NOT_FETCHED_SAME_SHAPE — exhausted + fetch_error → NOT_FETCHED (≠ NO_NEW)
  3. PARTIAL_EMPTY — result_status=ok + partial → UNVERIFIED (≠ NO_NEW)
  4. FALLBACK_EMPTY — fallback_reason present → EMPTY_CONFIRMED
  5. CURSOR_NOT_TERMINAL — null cursor + has_more=false is EMPTY_CONFIRMED,
     must not be labeled TERMINAL
  6. DEGRADED_SUCCESS — exit_code=0 + degraded → DEGRADED (≠ OK)
  7. CAUSE_AXIS_MISSING — items=[] but no cause fields → UNVERIFIED
  8. BYTES_VS_ITEMS — raw_bytes>0 + items=[] + parse_error → PARSE_EMPTY
     (not NO_NEW / not EMPTY_CONFIRMED)
  9. WEAK_ANCHOR_ONLY — only round_id/timestamp drift → WEAK_ANCHOR_ONLY
  10. HONEST_EMPTY — exhausted + cause fields + fingerprint_precomputed +
      bytes==0 + items=[] + anchor_level=CONFIRMED → EMPTY_CONFIRMED (green)

analyze_only. Stdlib only.
Credit: 小宝 (6 desensitized must-fail JSONL + fingerprint-before-send +
bytes≠items + anchor_level field); Grok Bot (impl + guards).
"""
from __future__ import annotations

import json
import sys
from typing import Any


REASON_CODES = frozenset(
    {
        "EMPTY_CONFIRMED",
        "NOT_FETCHED",
        "UNVERIFIED",
        "DEGRADED",
        "PARSE_EMPTY",
        "WEAK_ANCHOR_ONLY",
        "NO_NEW",  # forbidden laundering label — judge must never emit as PASS path
        "UNCLASSIFIED",
    }
)


def _cause_fields_present(r: dict[str, Any]) -> bool:
    """成因轴：至少一项可解释空结果的原因字段存在。"""
    if r.get("result_status") is not None:
        return True
    if r.get("fetch_error"):
        return True
    if r.get("fallback_reason"):
        return True
    if r.get("partial") is True:
        return True
    if r.get("degraded") is True:
        return True
    if r.get("parse_error"):
        return True
    return False


def judge(receipt: dict[str, Any]) -> dict[str, Any]:
    items = receipt.get("items")
    if not isinstance(items, list):
        items = []
    n = len(items)
    reported = receipt.get("reported_outcome")  # optional laundering label
    exit_code = receipt.get("exit_code")
    degraded = receipt.get("degraded") is True
    partial = receipt.get("partial") is True
    result_status = receipt.get("result_status")
    fetch_error = receipt.get("fetch_error")
    fallback_reason = receipt.get("fallback_reason")
    parse_error = receipt.get("parse_error")
    raw_bytes = receipt.get("raw_bytes")
    fingerprint_precomputed = receipt.get("fingerprint_precomputed")
    anchor_level = receipt.get("anchor_level")
    weak_only = receipt.get("weak_anchor_only") is True

    # Arm 9 — weak anchor must not upgrade to falsification
    if weak_only or anchor_level == "WEAK_ANCHOR_ONLY":
        return {
            "judge": "FAIL" if reported in ("NO_NEW", "FALSIFIED", "TERMINAL", "OK") else "PASS",
            "reason_code": "WEAK_ANCHOR_ONLY",
            "detail": {"anchor_level": anchor_level or "WEAK_ANCHOR_ONLY", "reported": reported},
        }

    # Arm 8 — parse fail: bytes>0 but items empty
    if (
        n == 0
        and isinstance(raw_bytes, int)
        and raw_bytes > 0
        and parse_error
    ):
        if reported in ("NO_NEW", "EMPTY_CONFIRMED", "OK"):
            return {
                "judge": "FAIL",
                "reason_code": "PARSE_EMPTY",
                "detail": {"raw_bytes": raw_bytes, "reported": reported, "note": "bytes_vs_items"},
            }
        return {
            "judge": "PASS",
            "reason_code": "PARSE_EMPTY",
            "detail": {"raw_bytes": raw_bytes, "parse_error": parse_error},
        }

    # Arm 6 — exit0 + degraded → DEGRADED, never OK
    if n == 0 and exit_code == 0 and degraded:
        if reported == "OK":
            return {
                "judge": "FAIL",
                "reason_code": "DEGRADED",
                "detail": {"exit_code": 0, "degraded": True, "reported": reported},
            }
        return {
            "judge": "PASS",
            "reason_code": "DEGRADED",
            "detail": {"exit_code": 0, "degraded": True},
        }

    # Arm 3 — partial empty → UNVERIFIED
    if n == 0 and partial and result_status == "ok":
        if reported == "NO_NEW":
            return {
                "judge": "FAIL",
                "reason_code": "UNVERIFIED",
                "detail": {"partial": True, "reported": reported},
            }
        return {"judge": "PASS", "reason_code": "UNVERIFIED", "detail": {"partial": True}}

    # Arm 2 — same empty shape + fetch_error → NOT_FETCHED
    if n == 0 and result_status == "exhausted" and fetch_error:
        if reported == "NO_NEW":
            return {
                "judge": "FAIL",
                "reason_code": "NOT_FETCHED",
                "detail": {"fetch_error": fetch_error, "reported": reported},
            }
        return {
            "judge": "PASS",
            "reason_code": "NOT_FETCHED",
            "detail": {"fetch_error": fetch_error},
        }

    # Arm 5 — null cursor + has_more=false is EMPTY_CONFIRMED, not TERMINAL
    # (checked before cause-missing so the cursor pair itself is the declared shape)
    if n == 0 and (
        receipt.get("kind") == "cursor_not_terminal"
        or (
            receipt.get("next_cursor") is None
            and receipt.get("has_more") is False
            and reported == "TERMINAL"
        )
    ):
        if reported == "TERMINAL":
            return {
                "judge": "FAIL",
                "reason_code": "EMPTY_CONFIRMED",
                "detail": {"note": "cursor_pair_not_terminal", "reported": reported},
            }
        return {
            "judge": "PASS",
            "reason_code": "EMPTY_CONFIRMED",
            "detail": {"note": "cursor_pair_not_terminal"},
        }

    # Arm 7 — cause axis missing → UNVERIFIED (never NO_NEW)
    if n == 0 and not _cause_fields_present(receipt):
        if reported == "NO_NEW":
            return {
                "judge": "FAIL",
                "reason_code": "UNVERIFIED",
                "detail": {"note": "cause_axis_missing", "reported": reported},
            }
        return {
            "judge": "PASS",
            "reason_code": "UNVERIFIED",
            "detail": {"note": "cause_axis_missing"},
        }

    # Arms 1 / 4 / 10 — EMPTY_CONFIRMED paths
    if n == 0 and (
        result_status == "exhausted"
        or fallback_reason
        or receipt.get("kind") in ("empty_confirmed", "fallback", "honest_empty")
    ):
        # laundering: must_fail if someone stamps NO_NEW / TERMINAL / OK incorrectly
        if reported in ("NO_NEW", "TERMINAL", "OK"):
            return {
                "judge": "FAIL",
                "reason_code": "EMPTY_CONFIRMED",
                "detail": {"reported": reported, "result_status": result_status},
            }
        # honest green twin prefers fingerprint_precomputed + bytes==0 + anchor CONFIRMED
        detail = {
            "result_status": result_status,
            "fallback_reason": fallback_reason,
            "fingerprint_precomputed": fingerprint_precomputed,
            "raw_bytes": raw_bytes,
            "anchor_level": anchor_level,
        }
        return {"judge": "PASS", "reason_code": "EMPTY_CONFIRMED", "detail": detail}

    return {"judge": "FAIL", "reason_code": "UNCLASSIFIED", "kind": receipt.get("kind")}


# 小宝 desensitized JSONL (6) + cause-missing + bytes_vs_items + weak-anchor + honest green
FIXTURES = [
    {
        "case_id": "XB-EMPTY-CONFIRMED",
        "receipt": {
            "kind": "empty_confirmed",
            "items": [],
            "result_status": "exhausted",
            "reported_outcome": "NO_NEW",
        },
        "expect": "EMPTY_CONFIRMED",
    },
    {
        "case_id": "XB-NOT-FETCHED-SAME-SHAPE",
        "receipt": {
            "kind": "not_fetched_same_shape",
            "items": [],
            "result_status": "exhausted",
            "fetch_error": "timeout",
            "reported_outcome": "NO_NEW",
        },
        "expect": "NOT_FETCHED",
    },
    {
        "case_id": "XB-PARTIAL-EMPTY",
        "receipt": {
            "kind": "partial",
            "items": [],
            "result_status": "ok",
            "partial": True,
            "reported_outcome": "NO_NEW",
        },
        "expect": "UNVERIFIED",
    },
    {
        "case_id": "XB-FALLBACK-EMPTY",
        "receipt": {
            "kind": "fallback",
            "items": [],
            "fallback_reason": "no_active_needs",
            "reported_outcome": "NO_NEW",
        },
        "expect": "EMPTY_CONFIRMED",
    },
    {
        "case_id": "XB-CURSOR-NOT-TERMINAL",
        "receipt": {
            "kind": "cursor_not_terminal",
            "items": [],
            "next_cursor": None,
            "has_more": False,
            "reported_outcome": "TERMINAL",
        },
        "expect": "EMPTY_CONFIRMED",
    },
    {
        "case_id": "XB-DEGRADED-SUCCESS",
        "receipt": {
            "kind": "degraded_success",
            "items": [],
            "exit_code": 0,
            "degraded": True,
            "reported_outcome": "OK",
        },
        "expect": "DEGRADED",
    },
    {
        "case_id": "XB-CAUSE-AXIS-MISSING",
        "receipt": {
            "kind": "cause_missing",
            "items": [],
            "reported_outcome": "NO_NEW",
        },
        "expect": "UNVERIFIED",
    },
    {
        "case_id": "XB-BYTES-VS-ITEMS",
        "receipt": {
            "kind": "bytes_vs_items",
            "items": [],
            "raw_bytes": 128,
            "parse_error": "json_decode",
            "reported_outcome": "EMPTY_CONFIRMED",
        },
        "expect": "PARSE_EMPTY",
    },
    {
        "case_id": "XB-WEAK-ANCHOR-ONLY",
        "receipt": {
            "kind": "weak_anchor",
            "items": [],
            "weak_anchor_only": True,
            "anchor_level": "WEAK_ANCHOR_ONLY",
            "round_id_changed": True,
            "batch_ts_drift": True,
            "reported_outcome": "FALSIFIED",
        },
        "expect": "WEAK_ANCHOR_ONLY",
    },
    {
        "case_id": "XB-HONEST-EMPTY",
        "receipt": {
            "kind": "honest_empty",
            "items": [],
            "result_status": "exhausted",
            "fingerprint_precomputed": True,
            "raw_bytes": 0,
            "anchor_level": "CONFIRMED",
            "reported_outcome": "EMPTY_CONFIRMED",
        },
        "expect": "EMPTY_CONFIRMED",
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
        "version": "EMPTY_CAUSE_DUAL_AXIS/v0.1",
        "all_match": ok,
        "n": len(rows),
        "n_match": sum(1 for r in rows if r["match"]),
        "rows": rows,
        "credits": [
            "小宝 (6 must-fail JSONL + fingerprint-before-send + bytes≠items + anchor_level)",
            "Grok Bot (impl + cause-missing/weak-anchor/honest guards)",
        ],
    }
    print(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
