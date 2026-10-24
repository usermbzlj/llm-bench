#!/usr/bin/env python3
"""ZERO_BYTE_FALSE_NONZERO v0.1

Structure from 52Hz (EigenFlux): stdout_bytes=0 with reported_rows>0 must
not render as a healthy non-empty result. Concrete arms they supplied:

  {stdout_bytes:0, reported_rows:1, verdict:BROKEN}   # must-fail shape
  {stdout_bytes:12, reported_rows:1, verdict:OK}      # honest non-empty

Rules:
  1. ZERO_BYTE_FALSE_NONZERO — bytes==0 AND rows>0 AND observed in
     (OK, PASS, NON_EMPTY, GREEN) → must-fail. Empty payload cannot
     justify a positive row count.
  2. ZERO_BYTE_HONEST_BROKEN — bytes==0 AND rows>0 AND observed=BROKEN
     (or EMPTY_CONFLICT / FAIL) → PASS (classifier named the conflict).
  3. HONEST_NONEMPTY — bytes>0 AND rows>0 AND observed=OK → PASS.
  4. HONEST_EMPTY — bytes==0 AND rows==0 AND observed in (OK, EMPTY, PASS)
     → PASS (true empty is allowed when rows also zero).
  5. ROWS_WITHOUT_BYTES_MISLABEL — bytes==0 AND rows>0 labeled EMPTY
     (hiding the row/bytes conflict) → must-fail as FALSE_EMPTY_LABEL.
  6. BYTES_WITHOUT_ROWS — bytes>0 AND rows==0 AND observed=OK → must-fail
     BYTES_WITHOUT_ROWS (symmetric false non-zero on the other axis).

analyze_only. Stdlib only.
Credit: 52Hz (structure + must-fail JSONL); Grok Bot (impl).
"""
from __future__ import annotations

import json
import sys
from typing import Any


def judge(receipt: dict[str, Any]) -> dict[str, Any]:
    kind = receipt.get("kind")
    if kind != "byte_row_pair":
        return {"judge": "FAIL", "reason_code": "UNCLASSIFIED", "kind": kind}

    bytes_v = receipt.get("stdout_bytes")
    rows = receipt.get("reported_rows")
    observed = receipt.get("observed_verdict")
    # OK | PASS | BROKEN | EMPTY | EMPTY_CONFLICT | FAIL | NON_EMPTY | GREEN

    if not isinstance(bytes_v, int) or bytes_v < 0:
        return {"judge": "FAIL", "reason_code": "BYTES_INVALID"}
    if not isinstance(rows, int) or rows < 0:
        return {"judge": "FAIL", "reason_code": "ROWS_INVALID"}

    positive_ok = observed in ("OK", "PASS", "NON_EMPTY", "GREEN")
    broken_ok = observed in ("BROKEN", "EMPTY_CONFLICT", "FAIL")

    # Arm 1/2: zero bytes + positive rows
    if bytes_v == 0 and rows > 0:
        if positive_ok:
            return {
                "judge": "FAIL",
                "reason_code": "ZERO_BYTE_FALSE_NONZERO",
                "detail": {"stdout_bytes": bytes_v, "reported_rows": rows, "observed": observed},
            }
        if observed == "EMPTY":
            return {
                "judge": "FAIL",
                "reason_code": "FALSE_EMPTY_LABEL",
                "detail": {"note": "rows>0 conflict hidden under EMPTY", "reported_rows": rows},
            }
        if broken_ok:
            return {
                "judge": "PASS",
                "reason_code": "ZERO_BYTE_HONEST_BROKEN",
                "detail": {"stdout_bytes": bytes_v, "reported_rows": rows, "observed": observed},
            }
        return {
            "judge": "FAIL",
            "reason_code": "ZERO_BYTE_UNEXPECTED",
            "detail": {"observed": observed},
        }

    # Arm 3: honest non-empty
    if bytes_v > 0 and rows > 0:
        if positive_ok:
            return {"judge": "PASS", "reason_code": "HONEST_NONEMPTY"}
        if broken_ok:
            return {
                "judge": "FAIL",
                "reason_code": "NONEMPTY_FALSE_BROKEN",
                "detail": {"observed": observed},
            }
        return {
            "judge": "FAIL",
            "reason_code": "NONEMPTY_UNEXPECTED",
            "detail": {"observed": observed},
        }

    # Arm 4: honest empty (both zero)
    if bytes_v == 0 and rows == 0:
        if observed in ("OK", "EMPTY", "PASS"):
            return {"judge": "PASS", "reason_code": "HONEST_EMPTY"}
        if broken_ok:
            return {
                "judge": "FAIL",
                "reason_code": "EMPTY_FALSE_BROKEN",
                "detail": {"observed": observed},
            }
        return {
            "judge": "FAIL",
            "reason_code": "EMPTY_UNEXPECTED",
            "detail": {"observed": observed},
        }

    # Arm 6: bytes without rows
    if bytes_v > 0 and rows == 0:
        if positive_ok:
            return {
                "judge": "FAIL",
                "reason_code": "BYTES_WITHOUT_ROWS",
                "detail": {"stdout_bytes": bytes_v, "reported_rows": rows},
            }
        if broken_ok or observed == "EMPTY":
            return {"judge": "PASS", "reason_code": "HONEST_BYTES_WITHOUT_ROWS_FLAGGED"}
        return {
            "judge": "FAIL",
            "reason_code": "BYTES_WITHOUT_ROWS_UNEXPECTED",
            "detail": {"observed": observed},
        }

    return {"judge": "FAIL", "reason_code": "UNCLASSIFIED_PAIR"}


FIXTURES = [
    {
        "case_id": "52HZ-ZERO-BYTE-FALSE-NONZERO",
        "receipt": {
            "kind": "byte_row_pair",
            "stdout_bytes": 0,
            "reported_rows": 1,
            "observed_verdict": "OK",
            "note": "52Hz must-fail JSONL: bytes=0 rows=1 verdict should be BROKEN",
        },
        "expect": "ZERO_BYTE_FALSE_NONZERO",
    },
    {
        "case_id": "52HZ-ZERO-BYTE-PASS-MISLABEL",
        "receipt": {
            "kind": "byte_row_pair",
            "stdout_bytes": 0,
            "reported_rows": 1,
            "observed_verdict": "PASS",
        },
        "expect": "ZERO_BYTE_FALSE_NONZERO",
    },
    {
        "case_id": "52HZ-HONEST-BROKEN",
        "receipt": {
            "kind": "byte_row_pair",
            "stdout_bytes": 0,
            "reported_rows": 1,
            "observed_verdict": "BROKEN",
            "note": "52Hz supplied shape with correct verdict",
        },
        "expect": "ZERO_BYTE_HONEST_BROKEN",
    },
    {
        "case_id": "FALSE-EMPTY-LABEL",
        "receipt": {
            "kind": "byte_row_pair",
            "stdout_bytes": 0,
            "reported_rows": 3,
            "observed_verdict": "EMPTY",
        },
        "expect": "FALSE_EMPTY_LABEL",
    },
    {
        "case_id": "52HZ-HONEST-NONEMPTY",
        "receipt": {
            "kind": "byte_row_pair",
            "stdout_bytes": 12,
            "reported_rows": 1,
            "observed_verdict": "OK",
            "note": "52Hz positive control",
        },
        "expect": "HONEST_NONEMPTY",
    },
    {
        "case_id": "HONEST-NONEMPTY-LARGER",
        "receipt": {
            "kind": "byte_row_pair",
            "stdout_bytes": 4096,
            "reported_rows": 40,
            "observed_verdict": "OK",
        },
        "expect": "HONEST_NONEMPTY",
    },
    {
        "case_id": "NONEMPTY-FALSE-BROKEN",
        "receipt": {
            "kind": "byte_row_pair",
            "stdout_bytes": 12,
            "reported_rows": 1,
            "observed_verdict": "BROKEN",
        },
        "expect": "NONEMPTY_FALSE_BROKEN",
    },
    {
        "case_id": "HONEST-EMPTY",
        "receipt": {
            "kind": "byte_row_pair",
            "stdout_bytes": 0,
            "reported_rows": 0,
            "observed_verdict": "EMPTY",
        },
        "expect": "HONEST_EMPTY",
    },
    {
        "case_id": "HONEST-EMPTY-OK",
        "receipt": {
            "kind": "byte_row_pair",
            "stdout_bytes": 0,
            "reported_rows": 0,
            "observed_verdict": "OK",
        },
        "expect": "HONEST_EMPTY",
    },
    {
        "case_id": "BYTES-WITHOUT-ROWS",
        "receipt": {
            "kind": "byte_row_pair",
            "stdout_bytes": 64,
            "reported_rows": 0,
            "observed_verdict": "OK",
        },
        "expect": "BYTES_WITHOUT_ROWS",
    },
    {
        "case_id": "HONEST-BYTES-WITHOUT-ROWS-FLAGGED",
        "receipt": {
            "kind": "byte_row_pair",
            "stdout_bytes": 64,
            "reported_rows": 0,
            "observed_verdict": "BROKEN",
        },
        "expect": "HONEST_BYTES_WITHOUT_ROWS_FLAGGED",
    },
    {
        "case_id": "ZERO-BYTE-GREEN-MISLABEL",
        "receipt": {
            "kind": "byte_row_pair",
            "stdout_bytes": 0,
            "reported_rows": 2,
            "observed_verdict": "GREEN",
        },
        "expect": "ZERO_BYTE_FALSE_NONZERO",
    },
]


def main() -> int:
    rows = []
    ok = 0
    for fx in FIXTURES:
        got = judge(fx["receipt"])
        reason = got.get("reason_code")
        passed = reason == fx["expect"]
        if passed:
            ok += 1
        rows.append(
            {
                "case_id": fx["case_id"],
                "expect": fx["expect"],
                "got": reason,
                "judge": got.get("judge"),
                "pass": passed,
                "detail": got.get("detail"),
            }
        )
    out = {
        "fixture": "ZERO_BYTE_FALSE_NONZERO",
        "version": "0.1",
        "total": len(FIXTURES),
        "passed": ok,
        "rows": rows,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if ok == len(FIXTURES) else 1


if __name__ == "__main__":
    sys.exit(main())
