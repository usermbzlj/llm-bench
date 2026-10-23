#!/usr/bin/env python3
"""DOUBLE_MISSING_PASS v0.1

Structure-only fixture. Three failure shapes from wshsssssssagent (EigenFlux):
  1. DOUBLE_MISSING_PASS — both fingerprint tags absent; naive equality
     treats missing==missing as consistent and reports PASS.
  2. COOLDOWN_WRONG_ANCHOR — retry cooldown keyed off last_request_at
     instead of last_success_at, inventing artificial delay.
  3. REKEY_MISCLASSIFIED — subject_key rotated while content_digest stable,
     but classifier labels OBJECT_CHANGED without an explicit rekey_flag.

Eight-state observational grid (minimal):
  content_same × subject_key_same × rekey_flag ∈ {0,1} → expected class
  in {UNCHANGED, REKEYED, OBJECT_CHANGED, INVALID}.

Structure source: wshsssssssagent EigenFlux broadcast on service-side
retry/comparison debugging. General fixture; no personal attribution in
rows. analyze_only. Stdlib only.
"""
from __future__ import annotations

import json
import sys
from typing import Any


def _absent(v: Any) -> bool:
    return v is None or v == "" or v == {}


def judge(receipt: dict[str, Any]) -> dict[str, Any]:
    kind = receipt.get("kind")

    if kind == "fingerprint_pair":
        left = receipt.get("left_fp")
        right = receipt.get("right_fp")
        naive_equal = receipt.get("naive_equal")
        observed = receipt.get("observed_verdict")  # PASS|FAIL|UNOBSERVED

        both_absent = _absent(left) and _absent(right)
        if both_absent:
            if naive_equal is True and observed == "PASS":
                return {"judge": "FAIL", "reason_code": "DOUBLE_MISSING_PASS"}
            if observed in ("UNOBSERVED", "FAIL") and naive_equal is not True:
                return {"judge": "PASS", "reason_code": "HONEST_DOUBLE_ABSENT"}
            if observed == "UNOBSERVED":
                return {"judge": "PASS", "reason_code": "HONEST_UNOBSERVED"}
            return {
                "judge": "FAIL",
                "reason_code": "ABSENT_UNEXPECTED",
                "detail": {"naive_equal": naive_equal, "observed": observed},
            }

        # At least one present
        if _absent(left) or _absent(right):
            if observed == "PASS" and naive_equal is True:
                return {"judge": "FAIL", "reason_code": "ONE_SIDE_ABSENT_PASS"}
            if observed in ("FAIL", "UNOBSERVED"):
                return {"judge": "PASS", "reason_code": "ONE_SIDE_ABSENT_CAUGHT"}
            return {"judge": "FAIL", "reason_code": "ONE_SIDE_UNEXPECTED"}

        equal = left == right
        if equal and observed == "PASS" and naive_equal is True:
            return {"judge": "PASS", "reason_code": "BOTH_PRESENT_MATCH"}
        if (not equal) and observed == "FAIL":
            return {"judge": "PASS", "reason_code": "BOTH_PRESENT_MISMATCH"}
        return {
            "judge": "FAIL",
            "reason_code": "PAIR_UNEXPECTED",
            "detail": {"equal": equal, "observed": observed},
        }

    if kind == "cooldown_anchor":
        anchor = receipt.get("cooldown_anchor")  # last_request_at|last_success_at
        last_req = receipt.get("last_request_at")
        last_ok = receipt.get("last_success_at")
        delayed = receipt.get("retry_delayed")
        observed = receipt.get("observed_verdict")

        if not isinstance(last_req, (int, float)) or not isinstance(last_ok, (int, float)):
            return {"judge": "FAIL", "reason_code": "TS_INVALID"}
        if anchor == "last_request_at" and last_ok < last_req and delayed is True:
            if observed == "PASS":
                return {"judge": "FAIL", "reason_code": "COOLDOWN_WRONG_ANCHOR"}
            if observed == "FAIL":
                return {"judge": "PASS", "reason_code": "WRONG_ANCHOR_CAUGHT"}
        if anchor == "last_success_at" and observed == "PASS":
            return {"judge": "PASS", "reason_code": "COOLDOWN_OK"}
        return {
            "judge": "FAIL",
            "reason_code": "COOLDOWN_UNEXPECTED",
            "detail": {"anchor": anchor, "observed": observed},
        }

    if kind == "rekey_grid":
        digest_before = receipt.get("digest_before")
        digest_after = receipt.get("digest_after")
        key_before = receipt.get("subject_key_before")
        key_after = receipt.get("subject_key_after")
        rekey_flag = receipt.get("rekey_flag")
        observed_class = receipt.get("observed_class")
        # UNCHANGED | REKEYED | OBJECT_CHANGED | INVALID

        if not all(isinstance(x, str) and x for x in (digest_before, digest_after, key_before, key_after)):
            return {"judge": "FAIL", "reason_code": "GRID_FIELDS_INVALID"}

        content_same = digest_before == digest_after
        key_same = key_before == key_after

        if content_same and key_same:
            expect = "UNCHANGED"
        elif content_same and not key_same:
            expect = "REKEYED" if rekey_flag is True else None  # must declare
        elif (not content_same) and key_same:
            expect = "OBJECT_CHANGED"
        else:
            expect = "OBJECT_CHANGED"  # both changed — still object change

        if content_same and not key_same and rekey_flag is not True:
            if observed_class == "OBJECT_CHANGED":
                return {"judge": "FAIL", "reason_code": "REKEY_MISCLASSIFIED"}
            if observed_class == "REKEYED":
                return {"judge": "FAIL", "reason_code": "REKEY_FLAG_MISSING"}
            if observed_class == "INVALID":
                return {"judge": "PASS", "reason_code": "REKEY_HONEST_INVALID"}
            return {
                "judge": "FAIL",
                "reason_code": "REKEY_UNEXPECTED",
                "detail": {"observed_class": observed_class},
            }

        if expect and observed_class == expect:
            return {"judge": "PASS", "reason_code": "GRID_OK", "detail": {"class": expect}}
        return {
            "judge": "FAIL",
            "reason_code": "GRID_MISMATCH",
            "detail": {"expect": expect, "observed": observed_class},
        }

    if kind == "flip_test":
        before = receipt.get("before_verdict")
        after = receipt.get("after_verdict")
        injected = receipt.get("injected")
        if before is None or after is None:
            return {"judge": "FAIL", "reason_code": "FLIP_PAIR_MISSING"}
        if injected != "both_fingerprints_present":
            return {"judge": "FAIL", "reason_code": "INJECT_WRONG"}
        if before == after:
            return {"judge": "FAIL", "reason_code": "FLIP_NOT_WIRED"}
        if before == "PASS" and after in ("FAIL", "UNOBSERVED"):
            return {"judge": "PASS", "reason_code": "FLIP_OK"}
        return {
            "judge": "FAIL",
            "reason_code": "FLIP_UNEXPECTED",
            "detail": {"before": before, "after": after},
        }

    return {"judge": "FAIL", "reason_code": "UNCLASSIFIED", "kind": kind}


FIXTURES = [
    {
        "case_id": "DOUBLE-MISSING-FALSE-PASS",
        "receipt": {
            "kind": "fingerprint_pair",
            "left_fp": None,
            "right_fp": None,
            "naive_equal": True,
            "observed_verdict": "PASS",
            "note": "两侧 fingerprint 皆缺，朴素相等仍报 PASS",
        },
        "expect": "DOUBLE_MISSING_PASS",
    },
    {
        "case_id": "HONEST-DOUBLE-ABSENT",
        "receipt": {
            "kind": "fingerprint_pair",
            "left_fp": None,
            "right_fp": None,
            "naive_equal": False,
            "observed_verdict": "UNOBSERVED",
        },
        "expect": "HONEST_DOUBLE_ABSENT",
    },
    {
        "case_id": "BOTH-PRESENT-MATCH",
        "receipt": {
            "kind": "fingerprint_pair",
            "left_fp": "sha256:aaaa",
            "right_fp": "sha256:aaaa",
            "naive_equal": True,
            "observed_verdict": "PASS",
        },
        "expect": "BOTH_PRESENT_MATCH",
    },
    {
        "case_id": "BOTH-PRESENT-MISMATCH",
        "receipt": {
            "kind": "fingerprint_pair",
            "left_fp": "sha256:aaaa",
            "right_fp": "sha256:bbbb",
            "naive_equal": False,
            "observed_verdict": "FAIL",
        },
        "expect": "BOTH_PRESENT_MISMATCH",
    },
    {
        "case_id": "COOLDOWN-WRONG-ANCHOR",
        "receipt": {
            "kind": "cooldown_anchor",
            "cooldown_anchor": "last_request_at",
            "last_request_at": 1000,
            "last_success_at": 100,
            "retry_delayed": True,
            "observed_verdict": "PASS",
        },
        "expect": "COOLDOWN_WRONG_ANCHOR",
    },
    {
        "case_id": "COOLDOWN-OK",
        "receipt": {
            "kind": "cooldown_anchor",
            "cooldown_anchor": "last_success_at",
            "last_request_at": 1000,
            "last_success_at": 100,
            "retry_delayed": False,
            "observed_verdict": "PASS",
        },
        "expect": "COOLDOWN_OK",
    },
    {
        "case_id": "REKEY-MISCLASSIFIED",
        "receipt": {
            "kind": "rekey_grid",
            "digest_before": "d1",
            "digest_after": "d1",
            "subject_key_before": "k1",
            "subject_key_after": "k2",
            "rekey_flag": False,
            "observed_class": "OBJECT_CHANGED",
        },
        "expect": "REKEY_MISCLASSIFIED",
    },
    {
        "case_id": "REKEY-OK",
        "receipt": {
            "kind": "rekey_grid",
            "digest_before": "d1",
            "digest_after": "d1",
            "subject_key_before": "k1",
            "subject_key_after": "k2",
            "rekey_flag": True,
            "observed_class": "REKEYED",
        },
        "expect": "GRID_OK",
    },
    {
        "case_id": "OBJECT-CHANGED-OK",
        "receipt": {
            "kind": "rekey_grid",
            "digest_before": "d1",
            "digest_after": "d2",
            "subject_key_before": "k1",
            "subject_key_after": "k1",
            "rekey_flag": False,
            "observed_class": "OBJECT_CHANGED",
        },
        "expect": "GRID_OK",
    },
    {
        "case_id": "FLIP-ABSENT-TO-PRESENT",
        "receipt": {
            "kind": "flip_test",
            "before_verdict": "PASS",
            "after_verdict": "UNOBSERVED",
            "injected": "both_fingerprints_present",
        },
        "expect": "FLIP_OK",
    },
]


def main() -> int:
    rows = []
    ok = 0
    for fx in FIXTURES:
        got = judge(fx["receipt"])
        reason = got.get("reason_code")
        passed = reason == fx["expect"] and got.get("judge") in ("PASS", "FAIL")
        # For expect codes that are failure detections, judge is FAIL but case passes
        if fx["expect"] in {
            "DOUBLE_MISSING_PASS",
            "COOLDOWN_WRONG_ANCHOR",
            "REKEY_MISCLASSIFIED",
            "REKEY_FLAG_MISSING",
            "ONE_SIDE_ABSENT_PASS",
            "ABSENT_UNEXPECTED",
            "FLIP_NOT_WIRED",
        }:
            passed = reason == fx["expect"]
        else:
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
        "fixture": "DOUBLE_MISSING_PASS",
        "version": "0.1",
        "total": len(FIXTURES),
        "passed": ok,
        "rows": rows,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if ok == len(FIXTURES) else 1


if __name__ == "__main__":
    sys.exit(main())
