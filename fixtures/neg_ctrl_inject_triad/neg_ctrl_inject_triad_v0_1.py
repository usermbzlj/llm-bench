#!/usr/bin/env python3
"""NEG_CTRL_INJECT_TRIAD v0.1

Structure from 随风绿柳 (EigenFlux): heartbeat "green" is the easiest self-deception.
Three gates must hold together before a window counts as valid evidence:

  1. NEG_CTRL_INJECT — negative-control inject_count must be >0 in the window.
     inject_count==0 → label UNVERIFIED; never mix into PASS/通过 reporting.
  2. WRITE_VERIFY_SEPARATION — writer endpoint only emits epoch + expected_rows
     + term_cursor; verifier holds no write capability. Append-acked-but-not-
     landed (writer_ack=true, landed_rows < expected_rows) must surface as
     MISSING_ROWS, not human log-diving.
  3. APPEND_MUST_FAIL — append action itself needs a must-fail arm: deliberately
     drop the last line and the gate MUST turn red. Zero-rows and green looking
     identical in observation is the hardest self-check cell.

Orthogonal pitfall (same author): retry-refill disguises truncation as complete
→ insist single-fetch; missing anchor → UNKNOWN (neither FAIL nor PASS denom).

analyze_only. Stdlib only.
Credit: 随风绿柳 (structure); Grok Bot (impl).
"""
from __future__ import annotations

import json
import sys
from typing import Any


POSITIVE = ("PASS", "OK", "GREEN", "通过")
UNVERIFIED_OK = ("UNVERIFIED", "UNKNOWN")
FAIL_OK = ("FAIL", "RED", "MISSING_ROWS", "BROKEN")


def judge(receipt: dict[str, Any]) -> dict[str, Any]:
    kind = receipt.get("kind")
    observed = receipt.get("observed_verdict")

    # --- Arm 1: zero inject must not report PASS ---
    if kind == "neg_ctrl_inject":
        inject_count = receipt.get("inject_count")
        if not isinstance(inject_count, int) or inject_count < 0:
            return {"judge": "FAIL", "reason_code": "INJECT_COUNT_INVALID"}
        if inject_count == 0:
            if observed in POSITIVE:
                return {
                    "judge": "FAIL",
                    "reason_code": "ZERO_INJECT_FALSE_PASS",
                    "detail": {"inject_count": 0, "observed": observed},
                }
            if observed in UNVERIFIED_OK:
                return {
                    "judge": "PASS",
                    "reason_code": "ZERO_INJECT_HONEST_UNVERIFIED",
                    "detail": {"inject_count": 0, "observed": observed},
                }
            if observed in FAIL_OK:
                return {
                    "judge": "FAIL",
                    "reason_code": "ZERO_INJECT_FALSE_FAIL",
                    "detail": {
                        "note": "zero inject is UNVERIFIED, not FAIL",
                        "observed": observed,
                    },
                }
            return {
                "judge": "FAIL",
                "reason_code": "ZERO_INJECT_UNEXPECTED",
                "detail": {"observed": observed},
            }
        # inject_count > 0: gate actually ran
        if observed in POSITIVE:
            return {"judge": "PASS", "reason_code": "INJECT_PRESENT_HONEST_PASS"}
        if observed in FAIL_OK:
            return {"judge": "PASS", "reason_code": "INJECT_PRESENT_HONEST_FAIL"}
        if observed in UNVERIFIED_OK:
            return {
                "judge": "FAIL",
                "reason_code": "INJECT_PRESENT_FALSE_UNVERIFIED",
                "detail": {"inject_count": inject_count},
            }
        return {
            "judge": "FAIL",
            "reason_code": "INJECT_PRESENT_UNEXPECTED",
            "detail": {"observed": observed},
        }

    # --- Arm 2: write/verify separation ---
    if kind == "write_verify_separation":
        writer_has_write = bool(receipt.get("writer_has_write", False))
        verifier_has_write = bool(receipt.get("verifier_has_write", False))
        writer_fields = receipt.get("writer_fields") or []
        writer_ack = bool(receipt.get("writer_ack", False))
        expected_rows = receipt.get("expected_rows")
        landed_rows = receipt.get("landed_rows")
        epoch = receipt.get("epoch")
        term_cursor = receipt.get("term_cursor")

        if verifier_has_write:
            if observed in POSITIVE:
                return {
                    "judge": "FAIL",
                    "reason_code": "VERIFIER_HAS_WRITE_FALSE_PASS",
                    "detail": {"verifier_has_write": True},
                }
            return {
                "judge": "PASS",
                "reason_code": "VERIFIER_HAS_WRITE_FLAGGED",
                "detail": {"observed": observed},
            }

        required = {"epoch", "expected_rows", "term_cursor"}
        if not isinstance(writer_fields, list):
            return {"judge": "FAIL", "reason_code": "WRITER_FIELDS_INVALID"}
        field_set = set(writer_fields)
        if writer_has_write and not required.issubset(field_set):
            if observed in POSITIVE:
                return {
                    "judge": "FAIL",
                    "reason_code": "WRITER_FIELDS_INCOMPLETE_FALSE_PASS",
                    "detail": {"missing": sorted(required - field_set)},
                }
            return {
                "judge": "PASS",
                "reason_code": "WRITER_FIELDS_INCOMPLETE_FLAGGED",
            }

        # append-acked-but-not-landed
        try:
            exp = int(expected_rows) if expected_rows is not None else None
            land = int(landed_rows) if landed_rows is not None else None
        except (TypeError, ValueError):
            return {"judge": "FAIL", "reason_code": "ROW_COUNTS_NON_INT"}

        if writer_ack and exp is not None and land is not None and land < exp:
            if observed in POSITIVE:
                return {
                    "judge": "FAIL",
                    "reason_code": "APPEND_ACK_NOT_LANDED_FALSE_PASS",
                    "detail": {"expected_rows": exp, "landed_rows": land},
                }
            if observed in ("MISSING_ROWS", "FAIL", "RED", "BROKEN"):
                return {
                    "judge": "PASS",
                    "reason_code": "APPEND_ACK_NOT_LANDED_HONEST",
                    "detail": {"expected_rows": exp, "landed_rows": land},
                }
            return {
                "judge": "FAIL",
                "reason_code": "APPEND_ACK_NOT_LANDED_UNEXPECTED",
                "detail": {"observed": observed},
            }

        # honest separated path
        if (
            writer_has_write
            and not verifier_has_write
            and required.issubset(field_set)
            and epoch is not None
            and term_cursor is not None
            and exp is not None
            and land is not None
            and land == exp
            and observed in POSITIVE
        ):
            return {"judge": "PASS", "reason_code": "WRITE_VERIFY_HONEST_PASS"}

        if observed in FAIL_OK and land is not None and exp is not None and land != exp:
            return {"judge": "PASS", "reason_code": "WRITE_VERIFY_HONEST_FAIL"}

        return {
            "judge": "FAIL",
            "reason_code": "WRITE_VERIFY_UNCLASSIFIED",
            "detail": {"observed": observed, "expected_rows": exp, "landed_rows": land},
        }

    # --- Arm 3: append must-fail (drop last line) ---
    if kind == "append_must_fail":
        deliberate_drop_last = bool(receipt.get("deliberate_drop_last", False))
        append_rows_written = receipt.get("append_rows_written")
        append_rows_expected = receipt.get("append_rows_expected")
        try:
            written = int(append_rows_written) if append_rows_written is not None else None
            expected = int(append_rows_expected) if append_rows_expected is not None else None
        except (TypeError, ValueError):
            return {"judge": "FAIL", "reason_code": "APPEND_COUNTS_NON_INT"}

        if deliberate_drop_last:
            # must turn red
            if observed in POSITIVE:
                return {
                    "judge": "FAIL",
                    "reason_code": "DROP_LAST_FALSE_PASS",
                    "detail": {
                        "written": written,
                        "expected": expected,
                        "observed": observed,
                    },
                }
            if observed in FAIL_OK:
                return {
                    "judge": "PASS",
                    "reason_code": "DROP_LAST_HONEST_FAIL",
                    "detail": {"written": written, "expected": expected},
                }
            return {
                "judge": "FAIL",
                "reason_code": "DROP_LAST_UNEXPECTED",
                "detail": {"observed": observed},
            }

        # no deliberate drop: honest append
        if (
            written is not None
            and expected is not None
            and written == expected
            and observed in POSITIVE
        ):
            return {"judge": "PASS", "reason_code": "APPEND_HONEST_PASS"}
        if written is not None and expected is not None and written != expected:
            if observed in FAIL_OK:
                return {"judge": "PASS", "reason_code": "APPEND_HONEST_MISMATCH_FAIL"}
            if observed in POSITIVE:
                return {
                    "judge": "FAIL",
                    "reason_code": "APPEND_MISMATCH_FALSE_PASS",
                    "detail": {"written": written, "expected": expected},
                }
        return {
            "judge": "FAIL",
            "reason_code": "APPEND_UNCLASSIFIED",
            "detail": {"observed": observed},
        }

    # --- Orthogonal: single-fetch / missing anchor ---
    if kind == "single_fetch_anchor":
        fetch_attempts = receipt.get("fetch_attempts")
        anchor_present = receipt.get("anchor_present")
        retry_refilled = bool(receipt.get("retry_refilled", False))
        try:
            attempts = int(fetch_attempts) if fetch_attempts is not None else None
        except (TypeError, ValueError):
            return {"judge": "FAIL", "reason_code": "FETCH_ATTEMPTS_NON_INT"}

        if anchor_present is False:
            if observed in ("UNKNOWN",):
                return {"judge": "PASS", "reason_code": "MISSING_ANCHOR_HONEST_UNKNOWN"}
            if observed in POSITIVE or observed in FAIL_OK:
                return {
                    "judge": "FAIL",
                    "reason_code": "MISSING_ANCHOR_FALSE_CLASSIFIED",
                    "detail": {"observed": observed},
                }
            return {
                "judge": "FAIL",
                "reason_code": "MISSING_ANCHOR_UNEXPECTED",
                "detail": {"observed": observed},
            }

        if retry_refilled or (attempts is not None and attempts > 1):
            if observed in POSITIVE:
                return {
                    "judge": "FAIL",
                    "reason_code": "RETRY_REFILL_FALSE_COMPLETE",
                    "detail": {"fetch_attempts": attempts, "retry_refilled": retry_refilled},
                }
            return {
                "judge": "PASS",
                "reason_code": "RETRY_REFILL_FLAGGED",
                "detail": {"observed": observed},
            }

        if attempts == 1 and anchor_present is True and observed in POSITIVE:
            return {"judge": "PASS", "reason_code": "SINGLE_FETCH_HONEST_PASS"}
        if attempts == 1 and observed in FAIL_OK:
            return {"judge": "PASS", "reason_code": "SINGLE_FETCH_HONEST_FAIL"}
        return {
            "judge": "FAIL",
            "reason_code": "SINGLE_FETCH_UNCLASSIFIED",
            "detail": {"observed": observed, "fetch_attempts": attempts},
        }

    return {"judge": "FAIL", "reason_code": "UNCLASSIFIED", "detail": {"kind": kind}}


FIXTURES = [
    # Arm 1
    {
        "case_id": "ZERO-INJECT-FALSE-PASS",
        "receipt": {
            "kind": "neg_ctrl_inject",
            "inject_count": 0,
            "observed_verdict": "PASS",
        },
        "expect": "ZERO_INJECT_FALSE_PASS",
    },
    {
        "case_id": "ZERO-INJECT-FALSE-OK",
        "receipt": {
            "kind": "neg_ctrl_inject",
            "inject_count": 0,
            "observed_verdict": "OK",
        },
        "expect": "ZERO_INJECT_FALSE_PASS",
    },
    {
        "case_id": "ZERO-INJECT-HONEST-UNVERIFIED",
        "receipt": {
            "kind": "neg_ctrl_inject",
            "inject_count": 0,
            "observed_verdict": "UNVERIFIED",
        },
        "expect": "ZERO_INJECT_HONEST_UNVERIFIED",
    },
    {
        "case_id": "ZERO-INJECT-FALSE-FAIL",
        "receipt": {
            "kind": "neg_ctrl_inject",
            "inject_count": 0,
            "observed_verdict": "FAIL",
            "note": "zero inject is UNVERIFIED not FAIL",
        },
        "expect": "ZERO_INJECT_FALSE_FAIL",
    },
    {
        "case_id": "INJECT-PRESENT-PASS",
        "receipt": {
            "kind": "neg_ctrl_inject",
            "inject_count": 3,
            "observed_verdict": "PASS",
        },
        "expect": "INJECT_PRESENT_HONEST_PASS",
    },
    {
        "case_id": "INJECT-PRESENT-FALSE-UNVERIFIED",
        "receipt": {
            "kind": "neg_ctrl_inject",
            "inject_count": 2,
            "observed_verdict": "UNVERIFIED",
        },
        "expect": "INJECT_PRESENT_FALSE_UNVERIFIED",
    },
    # Arm 2
    {
        "case_id": "VERIFIER-HAS-WRITE-FALSE-PASS",
        "receipt": {
            "kind": "write_verify_separation",
            "writer_has_write": True,
            "verifier_has_write": True,
            "writer_fields": ["epoch", "expected_rows", "term_cursor"],
            "writer_ack": True,
            "expected_rows": 10,
            "landed_rows": 10,
            "epoch": 7,
            "term_cursor": "c10",
            "observed_verdict": "PASS",
        },
        "expect": "VERIFIER_HAS_WRITE_FALSE_PASS",
    },
    {
        "case_id": "APPEND-ACK-NOT-LANDED-FALSE-PASS",
        "receipt": {
            "kind": "write_verify_separation",
            "writer_has_write": True,
            "verifier_has_write": False,
            "writer_fields": ["epoch", "expected_rows", "term_cursor"],
            "writer_ack": True,
            "expected_rows": 10,
            "landed_rows": 7,
            "epoch": 7,
            "term_cursor": "c10",
            "observed_verdict": "PASS",
        },
        "expect": "APPEND_ACK_NOT_LANDED_FALSE_PASS",
    },
    {
        "case_id": "APPEND-ACK-NOT-LANDED-HONEST",
        "receipt": {
            "kind": "write_verify_separation",
            "writer_has_write": True,
            "verifier_has_write": False,
            "writer_fields": ["epoch", "expected_rows", "term_cursor"],
            "writer_ack": True,
            "expected_rows": 10,
            "landed_rows": 7,
            "epoch": 7,
            "term_cursor": "c10",
            "observed_verdict": "MISSING_ROWS",
        },
        "expect": "APPEND_ACK_NOT_LANDED_HONEST",
    },
    {
        "case_id": "WRITE-VERIFY-HONEST-PASS",
        "receipt": {
            "kind": "write_verify_separation",
            "writer_has_write": True,
            "verifier_has_write": False,
            "writer_fields": ["epoch", "expected_rows", "term_cursor"],
            "writer_ack": True,
            "expected_rows": 10,
            "landed_rows": 10,
            "epoch": 7,
            "term_cursor": "c10",
            "observed_verdict": "PASS",
        },
        "expect": "WRITE_VERIFY_HONEST_PASS",
    },
    {
        "case_id": "WRITER-FIELDS-INCOMPLETE-FALSE-PASS",
        "receipt": {
            "kind": "write_verify_separation",
            "writer_has_write": True,
            "verifier_has_write": False,
            "writer_fields": ["expected_rows"],
            "writer_ack": True,
            "expected_rows": 5,
            "landed_rows": 5,
            "observed_verdict": "PASS",
        },
        "expect": "WRITER_FIELDS_INCOMPLETE_FALSE_PASS",
    },
    # Arm 3
    {
        "case_id": "DROP-LAST-FALSE-PASS",
        "receipt": {
            "kind": "append_must_fail",
            "deliberate_drop_last": True,
            "append_rows_written": 9,
            "append_rows_expected": 10,
            "observed_verdict": "PASS",
        },
        "expect": "DROP_LAST_FALSE_PASS",
    },
    {
        "case_id": "DROP-LAST-HONEST-FAIL",
        "receipt": {
            "kind": "append_must_fail",
            "deliberate_drop_last": True,
            "append_rows_written": 9,
            "append_rows_expected": 10,
            "observed_verdict": "FAIL",
        },
        "expect": "DROP_LAST_HONEST_FAIL",
    },
    {
        "case_id": "APPEND-HONEST-PASS",
        "receipt": {
            "kind": "append_must_fail",
            "deliberate_drop_last": False,
            "append_rows_written": 10,
            "append_rows_expected": 10,
            "observed_verdict": "PASS",
        },
        "expect": "APPEND_HONEST_PASS",
    },
    # Orthogonal single-fetch / anchor
    {
        "case_id": "MISSING-ANCHOR-HONEST-UNKNOWN",
        "receipt": {
            "kind": "single_fetch_anchor",
            "fetch_attempts": 1,
            "anchor_present": False,
            "retry_refilled": False,
            "observed_verdict": "UNKNOWN",
        },
        "expect": "MISSING_ANCHOR_HONEST_UNKNOWN",
    },
    {
        "case_id": "MISSING-ANCHOR-FALSE-PASS",
        "receipt": {
            "kind": "single_fetch_anchor",
            "fetch_attempts": 1,
            "anchor_present": False,
            "retry_refilled": False,
            "observed_verdict": "PASS",
        },
        "expect": "MISSING_ANCHOR_FALSE_CLASSIFIED",
    },
    {
        "case_id": "RETRY-REFILL-FALSE-COMPLETE",
        "receipt": {
            "kind": "single_fetch_anchor",
            "fetch_attempts": 3,
            "anchor_present": True,
            "retry_refilled": True,
            "observed_verdict": "PASS",
        },
        "expect": "RETRY_REFILL_FALSE_COMPLETE",
    },
    {
        "case_id": "SINGLE-FETCH-HONEST-PASS",
        "receipt": {
            "kind": "single_fetch_anchor",
            "fetch_attempts": 1,
            "anchor_present": True,
            "retry_refilled": False,
            "observed_verdict": "PASS",
        },
        "expect": "SINGLE_FETCH_HONEST_PASS",
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
        "fixture": "NEG_CTRL_INJECT_TRIAD",
        "version": "0.1",
        "total": len(FIXTURES),
        "passed": ok,
        "rows": rows,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if ok == len(FIXTURES) else 1


if __name__ == "__main__":
    sys.exit(main())
