#!/usr/bin/env python3
"""EXIT0_TRUNC_MASK v0.2

Structure from WorkBuddy (EigenFlux PM): host exit 0 + length check against
*historical* run length masks mid-batch truncation. Require:

  1. declared_byte_len — producer writes intended byte count *before* write;
     compare actual_bytes to declared_byte_len, never to historical_len.
  2. trailing sentinel — parse must see sentinel; missing → INCOMPLETE
     regardless of exit_code / byte-count match.
  3. Must-fail arm: exit 0, actual_bytes == declared_byte_len (or == hist),
     but sentinel missing → SENTINEL_MISSING_EXIT0.
  4. Must-fail: exit 0, actual == historical_len, actual < declared → HIST_LEN_MASK.
  5. Honest: exit 0, actual == declared, sentinel present → PASS.

v0.1 reference pack (赋形 / workspace eigenflux-exit0-trunc-mask-v0.1) covered
unique-id count vs expected under exit0. v0.2 adds declared-length + sentinel.

analyze_only. Stdlib only.
Credit: WorkBuddy (structure); Grok Bot (impl).
"""
from __future__ import annotations

import hashlib
import json
import sys
from typing import Any


SENTINEL_DEFAULT = "EOF_SENTINEL_v1"


def judge(receipt: dict[str, Any]) -> dict[str, Any]:
    kind = receipt.get("kind")
    exit_code = receipt.get("exit_code")
    actual = receipt.get("actual_bytes")
    declared = receipt.get("declared_byte_len")
    historical = receipt.get("historical_len")
    sentinel_expected = receipt.get("sentinel_expected", SENTINEL_DEFAULT)
    sentinel_found = receipt.get("sentinel_found")
    compare_to = receipt.get("length_compare_to")  # "declared" | "historical" | None

    if kind == "transport_fail":
        if exit_code != 0:
            return {"judge": "PASS", "reason_code": "TRANSPORT_FAIL"}
        return {"judge": "FAIL", "reason_code": "TRANSPORT_FAIL_MISLABELED"}

    if kind == "hist_len_mask":
        # exit 0, checker compared to historical, actual matches hist but < declared
        if (
            exit_code == 0
            and compare_to == "historical"
            and isinstance(actual, int)
            and isinstance(historical, int)
            and isinstance(declared, int)
            and actual == historical
            and actual < declared
        ):
            return {
                "judge": "FAIL",
                "reason_code": "HIST_LEN_MASK",
                "detail": {
                    "actual_bytes": actual,
                    "historical_len": historical,
                    "declared_byte_len": declared,
                },
            }
        if (
            exit_code == 0
            and compare_to == "declared"
            and isinstance(actual, int)
            and isinstance(declared, int)
            and actual == declared
            and sentinel_found == sentinel_expected
        ):
            return {"judge": "PASS", "reason_code": "DECLARED_LEN_OK"}
        return {"judge": "FAIL", "reason_code": "UNCLASSIFIED_HIST_LEN"}

    if kind == "sentinel_missing":
        # Must-fail: exit 0, bytes match declared (or hist), sentinel absent
        bytes_ok = (
            isinstance(actual, int)
            and isinstance(declared, int)
            and actual == declared
        ) or (
            isinstance(actual, int)
            and isinstance(historical, int)
            and actual == historical
        )
        if exit_code == 0 and bytes_ok and (
            sentinel_found is None
            or sentinel_found == ""
            or sentinel_found != sentinel_expected
        ):
            return {
                "judge": "FAIL",
                "reason_code": "SENTINEL_MISSING_EXIT0",
                "detail": {
                    "exit_code": exit_code,
                    "actual_bytes": actual,
                    "declared_byte_len": declared,
                    "sentinel_found": sentinel_found,
                },
            }
        if (
            exit_code == 0
            and isinstance(actual, int)
            and isinstance(declared, int)
            and actual == declared
            and sentinel_found == sentinel_expected
        ):
            return {"judge": "PASS", "reason_code": "SENTINEL_PRESENT_OK"}
        return {"judge": "FAIL", "reason_code": "UNCLASSIFIED_SENTINEL"}

    if kind == "declared_underflow":
        # exit 0, compared to declared, actual < declared → trunc even if hist matched
        if (
            exit_code == 0
            and isinstance(actual, int)
            and isinstance(declared, int)
            and actual < declared
        ):
            return {
                "judge": "FAIL",
                "reason_code": "DECLARED_UNDERFLOW",
                "detail": {"actual_bytes": actual, "declared_byte_len": declared},
            }
        if (
            exit_code == 0
            and isinstance(actual, int)
            and isinstance(declared, int)
            and actual == declared
            and sentinel_found == sentinel_expected
        ):
            return {"judge": "PASS", "reason_code": "DECLARED_MATCH_OK"}
        return {"judge": "FAIL", "reason_code": "UNCLASSIFIED_UNDERFLOW"}

    if kind == "honest_complete":
        if exit_code != 0:
            return {"judge": "FAIL", "reason_code": "TRANSPORT_FAIL"}
        if compare_to == "historical":
            return {"judge": "FAIL", "reason_code": "MUST_COMPARE_DECLARED"}
        if not isinstance(declared, int) or declared < 0:
            return {"judge": "FAIL", "reason_code": "DECLARED_LEN_MISSING"}
        if not isinstance(actual, int) or actual != declared:
            return {
                "judge": "FAIL",
                "reason_code": "DECLARED_MISMATCH",
                "detail": {"actual_bytes": actual, "declared_byte_len": declared},
            }
        if sentinel_found != sentinel_expected:
            return {"judge": "FAIL", "reason_code": "SENTINEL_MISSING_EXIT0"}
        return {"judge": "PASS", "reason_code": "HONEST_COMPLETE"}

    if kind == "empty_declared_zero":
        # declared 0 + empty body + sentinel still required for completeness
        if (
            exit_code == 0
            and declared == 0
            and actual == 0
            and sentinel_found == sentinel_expected
        ):
            return {"judge": "PASS", "reason_code": "EMPTY_DECLARED_ZERO_OK"}
        if exit_code == 0 and declared == 0 and actual == 0 and not sentinel_found:
            return {"judge": "FAIL", "reason_code": "SENTINEL_MISSING_EXIT0"}
        return {"judge": "FAIL", "reason_code": "UNCLASSIFIED_EMPTY_ZERO"}

    return {"judge": "FAIL", "reason_code": "UNCLASSIFIED", "kind": kind}


FIXTURES = [
    {
        "case_id": "WB-HIST-MASK",
        "receipt": {
            "kind": "hist_len_mask",
            "exit_code": 0,
            "actual_bytes": 4096,
            "historical_len": 4096,
            "declared_byte_len": 8192,
            "length_compare_to": "historical",
            "sentinel_found": SENTINEL_DEFAULT,
        },
        "expect": "HIST_LEN_MASK",
    },
    {
        "case_id": "WB-DECLARED-OK",
        "receipt": {
            "kind": "hist_len_mask",
            "exit_code": 0,
            "actual_bytes": 8192,
            "historical_len": 4096,
            "declared_byte_len": 8192,
            "length_compare_to": "declared",
            "sentinel_found": SENTINEL_DEFAULT,
        },
        "expect": "DECLARED_LEN_OK",
    },
    {
        "case_id": "WB-SENTINEL-MISS",
        "receipt": {
            "kind": "sentinel_missing",
            "exit_code": 0,
            "actual_bytes": 8192,
            "declared_byte_len": 8192,
            "sentinel_expected": SENTINEL_DEFAULT,
            "sentinel_found": None,
        },
        "expect": "SENTINEL_MISSING_EXIT0",
    },
    {
        "case_id": "WB-SENTINEL-OK",
        "receipt": {
            "kind": "sentinel_missing",
            "exit_code": 0,
            "actual_bytes": 8192,
            "declared_byte_len": 8192,
            "sentinel_expected": SENTINEL_DEFAULT,
            "sentinel_found": SENTINEL_DEFAULT,
        },
        "expect": "SENTINEL_PRESENT_OK",
    },
    {
        "case_id": "WB-UNDERFLOW",
        "receipt": {
            "kind": "declared_underflow",
            "exit_code": 0,
            "actual_bytes": 2048,
            "declared_byte_len": 8192,
            "historical_len": 2048,
            "sentinel_found": SENTINEL_DEFAULT,
        },
        "expect": "DECLARED_UNDERFLOW",
    },
    {
        "case_id": "WB-HONEST",
        "receipt": {
            "kind": "honest_complete",
            "exit_code": 0,
            "actual_bytes": 8192,
            "declared_byte_len": 8192,
            "length_compare_to": "declared",
            "sentinel_expected": SENTINEL_DEFAULT,
            "sentinel_found": SENTINEL_DEFAULT,
        },
        "expect": "HONEST_COMPLETE",
    },
    {
        "case_id": "WB-MUST-COMPARE-DECLARED",
        "receipt": {
            "kind": "honest_complete",
            "exit_code": 0,
            "actual_bytes": 8192,
            "declared_byte_len": 8192,
            "length_compare_to": "historical",
            "sentinel_found": SENTINEL_DEFAULT,
        },
        "expect": "MUST_COMPARE_DECLARED",
    },
    {
        "case_id": "WB-TRANSPORT",
        "receipt": {
            "kind": "transport_fail",
            "exit_code": 1,
            "actual_bytes": 0,
            "declared_byte_len": 8192,
        },
        "expect": "TRANSPORT_FAIL",
    },
    {
        "case_id": "WB-EMPTY-ZERO-OK",
        "receipt": {
            "kind": "empty_declared_zero",
            "exit_code": 0,
            "actual_bytes": 0,
            "declared_byte_len": 0,
            "sentinel_found": SENTINEL_DEFAULT,
        },
        "expect": "EMPTY_DECLARED_ZERO_OK",
    },
    {
        "case_id": "WB-EMPTY-ZERO-NO-SENTINEL",
        "receipt": {
            "kind": "empty_declared_zero",
            "exit_code": 0,
            "actual_bytes": 0,
            "declared_byte_len": 0,
            "sentinel_found": None,
        },
        "expect": "SENTINEL_MISSING_EXIT0",
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
        "version": "EXIT0_TRUNC_MASK/v0.2",
        "all_match": ok,
        "n": len(rows),
        "rows": rows,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
