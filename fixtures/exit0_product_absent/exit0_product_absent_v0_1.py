#!/usr/bin/env python3
"""EXIT0_PRODUCT_ABSENT v0.1

Concrete false-green shapes from hermes-jarvis-v0.1 (EigenFlux 2026-10-24):

  ① reason_code closed set MUST carry a version. Fixture and criteria drift
     independently; if reason_code_version ≠ criteria_version, a must-fail that
     only checks "is red" degenerates → REASON_CODE_VERSION_DRIFT (must-fail).

  ② INCONCLUSIVE / UNPROBED must NOT enter the pass denominator, BUT they MUST
     be counted as n_unprobed in run_out. Marking hard cases unprobed to shrink
     the denom and inflate pass_rate is itself a false green
     → UNPROBED_SHRINKS_DENOM (must-fail). Honest: pass_rate uses only judged
     rows; n_unprobed is reported separately.

  ③ One positive control is not enough. Window must contain ≥1 negative-control
     pair that actually scored differently (pos_score ≠ neg_score). Else the
     whole window is UNVERIFIED, never GREEN → NEG_CTRL_PAIR_MISSING.

  Two real false-green shapes (hermes):
    A. exit_code 0 + receipt.status=success + product_path does not exist
       (not empty file — path absent) → EXIT0_PRODUCT_ABSENT.
    B. empty-array fallback that makes "truly no data" and "fetch failed"
       look identical downstream → EMPTY_ARRAY_FETCH_COLLISION.

analyze_only. Stdlib only.
Credit: hermes-jarvis-v0.1 (three gates + two shapes); Grok Bot (impl).
"""
from __future__ import annotations

import json
import sys
from typing import Any


REASON_CODE_SET_V1 = frozenset(
    {
        "REASON_CODE_VERSION_DRIFT",
        "REASON_CODE_OK",
        "UNPROBED_SHRINKS_DENOM",
        "UNPROBED_HONEST",
        "NEG_CTRL_PAIR_MISSING",
        "NEG_CTRL_PAIR_OK",
        "EXIT0_PRODUCT_ABSENT",
        "EXIT0_PRODUCT_OK",
        "EMPTY_ARRAY_FETCH_COLLISION",
        "EMPTY_ARRAY_DISAMBIGUATED",
        "UNCLASSIFIED",
    }
)


def judge(receipt: dict[str, Any]) -> dict[str, Any]:
    kind = receipt.get("kind")

    if kind == "reason_code_version":
        rc_ver = receipt.get("reason_code_version")
        crit_ver = receipt.get("criteria_version")
        code = receipt.get("reason_code")
        if rc_ver is None or crit_ver is None or rc_ver != crit_ver:
            return {
                "judge": "FAIL",
                "reason_code": "REASON_CODE_VERSION_DRIFT",
                "detail": {
                    "reason_code_version": rc_ver,
                    "criteria_version": crit_ver,
                },
            }
        if code not in REASON_CODE_SET_V1:
            return {"judge": "FAIL", "reason_code": "REASON_CODE_VERSION_DRIFT"}
        return {"judge": "PASS", "reason_code": "REASON_CODE_OK"}

    if kind == "unprobed_denom":
        n_pass = receipt.get("n_pass")
        n_fail = receipt.get("n_fail")
        n_unprobed = receipt.get("n_unprobed")
        n_total = receipt.get("n_total")
        reported_rate = receipt.get("pass_rate")
        unprobed_in_denom = bool(receipt.get("unprobed_in_pass_denom", False))
        # False green: hard cases marked unprobed, denom shrinks, rate looks good
        if (
            isinstance(n_pass, int)
            and isinstance(n_fail, int)
            and isinstance(n_unprobed, int)
            and isinstance(n_total, int)
            and n_unprobed > 0
            and (n_pass + n_fail + n_unprobed) == n_total
        ):
            judged = n_pass + n_fail
            if judged <= 0:
                return {"judge": "FAIL", "reason_code": "UNPROBED_SHRINKS_DENOM"}
            honest_rate = n_pass / judged
            # Shrink attack: treat only judged as denom BUT omit n_unprobed from run_out
            if receipt.get("n_unprobed_reported") is None:
                return {
                    "judge": "FAIL",
                    "reason_code": "UNPROBED_SHRINKS_DENOM",
                    "detail": {"missing": "n_unprobed"},
                }
            # Or: put unprobed into pass denom / hide them from total
            if unprobed_in_denom:
                return {"judge": "FAIL", "reason_code": "UNPROBED_SHRINKS_DENOM"}
            # Or: report pass_rate against (pass+fail) while claiming higher via hiding
            if isinstance(reported_rate, (int, float)) and reported_rate > honest_rate + 1e-9:
                return {
                    "judge": "FAIL",
                    "reason_code": "UNPROBED_SHRINKS_DENOM",
                    "detail": {
                        "reported_pass_rate": reported_rate,
                        "honest_pass_rate": honest_rate,
                    },
                }
            if receipt.get("n_unprobed_reported") == n_unprobed and not unprobed_in_denom:
                return {
                    "judge": "PASS",
                    "reason_code": "UNPROBED_HONEST",
                    "detail": {
                        "pass_rate": honest_rate,
                        "n_unprobed": n_unprobed,
                    },
                }
        return {"judge": "FAIL", "reason_code": "UNCLASSIFIED"}

    if kind == "neg_ctrl_pair":
        pairs = receipt.get("neg_ctrl_pairs") or []
        window_verdict = receipt.get("window_verdict")
        scored_diff = False
        for p in pairs:
            if not isinstance(p, dict):
                continue
            if p.get("pos_score") is None or p.get("neg_score") is None:
                continue
            if p.get("pos_score") != p.get("neg_score"):
                scored_diff = True
                break
        if not scored_diff:
            # whole window must be UNVERIFIED, never GREEN
            if window_verdict in ("GREEN", "PASS", "OK"):
                return {"judge": "FAIL", "reason_code": "NEG_CTRL_PAIR_MISSING"}
            return {"judge": "FAIL", "reason_code": "NEG_CTRL_PAIR_MISSING"}
        if window_verdict in ("GREEN", "PASS", "OK", "VERIFIED"):
            return {"judge": "PASS", "reason_code": "NEG_CTRL_PAIR_OK"}
        return {"judge": "PASS", "reason_code": "NEG_CTRL_PAIR_OK"}

    if kind == "product_absent":
        exit_code = receipt.get("exit_code")
        status = receipt.get("receipt_status")
        path_exists = receipt.get("product_path_exists")
        # Must-fail shape A: exit0 + success + path absent (not empty file)
        if exit_code == 0 and status in ("success", "ok", "SUCCESS", "OK") and path_exists is False:
            return {
                "judge": "FAIL",
                "reason_code": "EXIT0_PRODUCT_ABSENT",
                "detail": {
                    "exit_code": exit_code,
                    "receipt_status": status,
                    "product_path_exists": path_exists,
                },
            }
        if exit_code == 0 and status in ("success", "ok", "SUCCESS", "OK") and path_exists is True:
            return {"judge": "PASS", "reason_code": "EXIT0_PRODUCT_OK"}
        if exit_code != 0:
            return {"judge": "PASS", "reason_code": "EXIT0_PRODUCT_OK"}  # transport fail labeled
        return {"judge": "FAIL", "reason_code": "UNCLASSIFIED"}

    if kind == "empty_array_fallback":
        # Shape B: empty array makes "no data" and "fetch failed" identical
        shape = receipt.get("reported_shape")  # "[]" identical
        true_state = receipt.get("true_state")  # "no_data" | "fetch_failed"
        disambiguator = receipt.get("disambiguator")  # required field e.g. fetch_ok
        if shape == [] or shape == "[]":
            if true_state == "fetch_failed" and disambiguator is None:
                return {
                    "judge": "FAIL",
                    "reason_code": "EMPTY_ARRAY_FETCH_COLLISION",
                    "detail": {"true_state": true_state},
                }
            if true_state == "no_data" and disambiguator == "fetch_ok":
                return {"judge": "PASS", "reason_code": "EMPTY_ARRAY_DISAMBIGUATED"}
            if true_state == "fetch_failed" and disambiguator == "fetch_failed":
                return {"judge": "PASS", "reason_code": "EMPTY_ARRAY_DISAMBIGUATED"}
            if true_state == "no_data" and disambiguator is None:
                # still collision risk — require disambiguator even for no_data
                return {"judge": "FAIL", "reason_code": "EMPTY_ARRAY_FETCH_COLLISION"}
        return {"judge": "FAIL", "reason_code": "UNCLASSIFIED"}

    return {"judge": "FAIL", "reason_code": "UNCLASSIFIED", "kind": kind}


FIXTURES = [
    {
        "case_id": "HJ-RC-DRIFT",
        "receipt": {
            "kind": "reason_code_version",
            "reason_code_version": "rc-v1",
            "criteria_version": "crit-v2",
            "reason_code": "REASON_CODE_OK",
        },
        "expect": "REASON_CODE_VERSION_DRIFT",
    },
    {
        "case_id": "HJ-RC-OK",
        "receipt": {
            "kind": "reason_code_version",
            "reason_code_version": "rc-v1",
            "criteria_version": "rc-v1",
            "reason_code": "REASON_CODE_OK",
        },
        "expect": "REASON_CODE_OK",
    },
    {
        "case_id": "HJ-UNPROBED-SHRINK-MISSING",
        "receipt": {
            "kind": "unprobed_denom",
            "n_pass": 9,
            "n_fail": 1,
            "n_unprobed": 10,
            "n_total": 20,
            "pass_rate": 0.9,
            "n_unprobed_reported": None,
            "unprobed_in_pass_denom": False,
        },
        "expect": "UNPROBED_SHRINKS_DENOM",
    },
    {
        "case_id": "HJ-UNPROBED-IN-DENOM",
        "receipt": {
            "kind": "unprobed_denom",
            "n_pass": 9,
            "n_fail": 1,
            "n_unprobed": 10,
            "n_total": 20,
            "pass_rate": 0.45,
            "n_unprobed_reported": 10,
            "unprobed_in_pass_denom": True,
        },
        "expect": "UNPROBED_SHRINKS_DENOM",
    },
    {
        "case_id": "HJ-UNPROBED-RATE-INFLATE",
        "receipt": {
            "kind": "unprobed_denom",
            "n_pass": 8,
            "n_fail": 2,
            "n_unprobed": 10,
            "n_total": 20,
            "pass_rate": 0.95,
            "n_unprobed_reported": 10,
            "unprobed_in_pass_denom": False,
        },
        "expect": "UNPROBED_SHRINKS_DENOM",
    },
    {
        "case_id": "HJ-UNPROBED-HONEST",
        "receipt": {
            "kind": "unprobed_denom",
            "n_pass": 8,
            "n_fail": 2,
            "n_unprobed": 10,
            "n_total": 20,
            "pass_rate": 0.8,
            "n_unprobed_reported": 10,
            "unprobed_in_pass_denom": False,
        },
        "expect": "UNPROBED_HONEST",
    },
    {
        "case_id": "HJ-NEG-MISSING-GREEN",
        "receipt": {
            "kind": "neg_ctrl_pair",
            "neg_ctrl_pairs": [
                {"pos_score": 1.0, "neg_score": 1.0},
            ],
            "window_verdict": "GREEN",
        },
        "expect": "NEG_CTRL_PAIR_MISSING",
    },
    {
        "case_id": "HJ-NEG-EMPTY-GREEN",
        "receipt": {
            "kind": "neg_ctrl_pair",
            "neg_ctrl_pairs": [],
            "window_verdict": "GREEN",
        },
        "expect": "NEG_CTRL_PAIR_MISSING",
    },
    {
        "case_id": "HJ-NEG-OK",
        "receipt": {
            "kind": "neg_ctrl_pair",
            "neg_ctrl_pairs": [
                {"pos_score": 0.9, "neg_score": 0.1},
            ],
            "window_verdict": "VERIFIED",
        },
        "expect": "NEG_CTRL_PAIR_OK",
    },
    {
        "case_id": "HJ-PRODUCT-ABSENT",
        "receipt": {
            "kind": "product_absent",
            "exit_code": 0,
            "receipt_status": "success",
            "product_path_exists": False,
        },
        "expect": "EXIT0_PRODUCT_ABSENT",
    },
    {
        "case_id": "HJ-PRODUCT-OK",
        "receipt": {
            "kind": "product_absent",
            "exit_code": 0,
            "receipt_status": "success",
            "product_path_exists": True,
        },
        "expect": "EXIT0_PRODUCT_OK",
    },
    {
        "case_id": "HJ-EMPTY-COLLISION",
        "receipt": {
            "kind": "empty_array_fallback",
            "reported_shape": [],
            "true_state": "fetch_failed",
            "disambiguator": None,
        },
        "expect": "EMPTY_ARRAY_FETCH_COLLISION",
    },
    {
        "case_id": "HJ-EMPTY-NO-DATA-NO-DISAMB",
        "receipt": {
            "kind": "empty_array_fallback",
            "reported_shape": [],
            "true_state": "no_data",
            "disambiguator": None,
        },
        "expect": "EMPTY_ARRAY_FETCH_COLLISION",
    },
    {
        "case_id": "HJ-EMPTY-DISAMB-OK",
        "receipt": {
            "kind": "empty_array_fallback",
            "reported_shape": [],
            "true_state": "no_data",
            "disambiguator": "fetch_ok",
        },
        "expect": "EMPTY_ARRAY_DISAMBIGUATED",
    },
    {
        "case_id": "HJ-EMPTY-DISAMB-FAIL",
        "receipt": {
            "kind": "empty_array_fallback",
            "reported_shape": [],
            "true_state": "fetch_failed",
            "disambiguator": "fetch_failed",
        },
        "expect": "EMPTY_ARRAY_DISAMBIGUATED",
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
        "version": "EXIT0_PRODUCT_ABSENT/v0.1",
        "all_match": ok,
        "n": len(rows),
        "rows": rows,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
