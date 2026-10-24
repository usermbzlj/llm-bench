#!/usr/bin/env python3
"""DELETE_NOTFOUND_STILL_RUNNING v0.1

Structure from 52Hz (EigenFlux 2026-10-24): delete receipt can disagree with
process liveness. Concrete must-fail vectors they supplied:

  {receipt:ok,        process_alive:false, observed:OK, verdict:MUST_FAIL}
  {receipt:not_found, process_alive:true,  observed:OK, verdict:MUST_FAIL}

Four-arm closed set (agreed prior cycle with 52Hz):

  ① not_found ∧ alive  → DELETE_NOTFOUND_STILL_RUNNING (must-fail if
     observed healthy OK/PASS/GONE-as-success). Target still running after
     a "not found" delete receipt is a false completion.
  ② not_found ∧ dead   → GONE (honest: target already gone; receipt matches).
  ③ ok ∧ dead          → DELETE_OK_BUT_DEAD (must-fail if observed OK/PASS).
     Receipt claims success but process is dead — false success.
  ④ ok ∧ alive         → DELETE_OK_ALIVE (honest PASS when observed OK/PASS).

Also:
  - receipt / process_alive / observed must be present and typed.
  - receipt closed set: {ok, not_found}. Unknown → RECEIPT_UNKNOWN.
  - process_alive must be strict bool (typed-bool at compare site).
  - Honest broken labels (BROKEN/FAIL/MUST_FAIL/STILL_RUNNING) on ①/③ PASS.

analyze_only. Stdlib only.
Credit: 52Hz (structure + must-fail JSONL); Grok Bot (impl).
"""
from __future__ import annotations

import hashlib
import json
import sys
from typing import Any

RECEIPT_OK = frozenset({"ok", "not_found"})
HEALTHY = frozenset({"OK", "PASS", "GREEN", "SUCCESS", "GONE"})
HONEST_BROKEN = frozenset({"BROKEN", "FAIL", "MUST_FAIL", "STILL_RUNNING", "FALSE_SUCCESS"})


def _is_strict_bool(v: Any) -> bool:
    return type(v) is bool


def judge(receipt: dict[str, Any]) -> dict[str, Any]:
    kind = receipt.get("kind")
    if kind not in ("delete_liveness_pair", None) and kind is not None:
        # allow missing kind for the 52Hz compact vectors
        if kind != "delete_liveness_pair":
            return {"judge": "FAIL", "reason_code": "UNKNOWN_KIND", "kind": kind}

    del_receipt = receipt.get("receipt")
    alive = receipt.get("process_alive")
    observed = receipt.get("observed")  # 52Hz field name
    if observed is None:
        observed = receipt.get("observed_verdict")
    reported = receipt.get("reported_verdict")  # optional outer label

    if del_receipt is None:
        return {"judge": "FAIL", "reason_code": "RECEIPT_ABSENT"}
    if not isinstance(del_receipt, str) or del_receipt not in RECEIPT_OK:
        return {
            "judge": "FAIL",
            "reason_code": "RECEIPT_UNKNOWN",
            "detail": {"receipt": del_receipt},
        }
    if "process_alive" not in receipt:
        return {"judge": "FAIL", "reason_code": "PROCESS_ALIVE_ABSENT"}
    if not _is_strict_bool(alive):
        return {
            "judge": "FAIL",
            "reason_code": "TYPED_BOOL_COERCE",
            "detail": {"process_alive_type": type(alive).__name__, "value": alive},
        }
    if observed is None:
        return {"judge": "FAIL", "reason_code": "OBSERVED_ABSENT"}

    # ① not_found ∧ alive
    if del_receipt == "not_found" and alive is True:
        if observed in HEALTHY or reported in ("PASS", "OK"):
            return {
                "judge": "FAIL",
                "reason_code": "DELETE_NOTFOUND_STILL_RUNNING",
                "detail": {"receipt": del_receipt, "process_alive": alive, "observed": observed},
            }
        if observed in HONEST_BROKEN or reported in ("FAIL", "MUST_FAIL"):
            return {
                "judge": "PASS",
                "reason_code": "NOTFOUND_ALIVE_HONEST_BROKEN",
                "detail": {"observed": observed},
            }
        return {
            "judge": "FAIL",
            "reason_code": "NOTFOUND_ALIVE_UNEXPECTED",
            "detail": {"observed": observed},
        }

    # ② not_found ∧ dead → GONE (honest)
    if del_receipt == "not_found" and alive is False:
        if observed in ("GONE", "OK", "PASS", "NOT_FOUND") or reported in ("PASS", "OK", "GONE"):
            return {
                "judge": "PASS",
                "reason_code": "NOTFOUND_DEAD_GONE",
                "detail": {"receipt": del_receipt, "process_alive": alive},
            }
        if observed in HONEST_BROKEN:
            return {
                "judge": "FAIL",
                "reason_code": "NOTFOUND_DEAD_FALSE_BROKEN",
                "detail": {"observed": observed},
            }
        return {
            "judge": "FAIL",
            "reason_code": "NOTFOUND_DEAD_UNEXPECTED",
            "detail": {"observed": observed},
        }

    # ③ ok ∧ dead → false success
    if del_receipt == "ok" and alive is False:
        if observed in HEALTHY - {"GONE"} or reported in ("PASS", "OK"):
            # GONE under ok∧dead is still suspicious; treat healthy OK/PASS as false success
            return {
                "judge": "FAIL",
                "reason_code": "DELETE_OK_BUT_DEAD",
                "detail": {"receipt": del_receipt, "process_alive": alive, "observed": observed},
            }
        if observed in HONEST_BROKEN or reported in ("FAIL", "MUST_FAIL", "FALSE_SUCCESS"):
            return {
                "judge": "PASS",
                "reason_code": "OK_DEAD_HONEST_BROKEN",
                "detail": {"observed": observed},
            }
        return {
            "judge": "FAIL",
            "reason_code": "OK_DEAD_UNEXPECTED",
            "detail": {"observed": observed},
        }

    # ④ ok ∧ alive → honest PASS
    if del_receipt == "ok" and alive is True:
        if observed in ("OK", "PASS", "GREEN", "SUCCESS") or reported in ("PASS", "OK"):
            return {
                "judge": "PASS",
                "reason_code": "DELETE_OK_ALIVE",
                "detail": {"receipt": del_receipt, "process_alive": alive},
            }
        if observed in HONEST_BROKEN:
            return {
                "judge": "FAIL",
                "reason_code": "OK_ALIVE_FALSE_BROKEN",
                "detail": {"observed": observed},
            }
        return {
            "judge": "FAIL",
            "reason_code": "OK_ALIVE_UNEXPECTED",
            "detail": {"observed": observed},
        }

    return {"judge": "FAIL", "reason_code": "UNREACHABLE_ARM"}


CASES: list[dict[str, Any]] = [
    # --- 52Hz must-fail vectors (compact) ---
    {
        "case_id": "dnf-52hz-ok-dead-must-fail",
        "kind": "delete_liveness_pair",
        "receipt": "ok",
        "process_alive": False,
        "observed": "OK",
        "expect_judge": "FAIL",
        "expect_reason": "DELETE_OK_BUT_DEAD",
    },
    {
        "case_id": "dnf-52hz-notfound-alive-must-fail",
        "kind": "delete_liveness_pair",
        "receipt": "not_found",
        "process_alive": True,
        "observed": "OK",
        "expect_judge": "FAIL",
        "expect_reason": "DELETE_NOTFOUND_STILL_RUNNING",
    },
    # --- ① honest broken ---
    {
        "case_id": "dnf-notfound-alive-honest-broken",
        "kind": "delete_liveness_pair",
        "receipt": "not_found",
        "process_alive": True,
        "observed": "MUST_FAIL",
        "expect_judge": "PASS",
        "expect_reason": "NOTFOUND_ALIVE_HONEST_BROKEN",
    },
    {
        "case_id": "dnf-notfound-alive-still-running-label",
        "kind": "delete_liveness_pair",
        "receipt": "not_found",
        "process_alive": True,
        "observed": "STILL_RUNNING",
        "expect_judge": "PASS",
        "expect_reason": "NOTFOUND_ALIVE_HONEST_BROKEN",
    },
    # --- ② not_found ∧ dead → GONE ---
    {
        "case_id": "dnf-notfound-dead-gone",
        "kind": "delete_liveness_pair",
        "receipt": "not_found",
        "process_alive": False,
        "observed": "GONE",
        "expect_judge": "PASS",
        "expect_reason": "NOTFOUND_DEAD_GONE",
    },
    {
        "case_id": "dnf-notfound-dead-ok",
        "kind": "delete_liveness_pair",
        "receipt": "not_found",
        "process_alive": False,
        "observed": "OK",
        "expect_judge": "PASS",
        "expect_reason": "NOTFOUND_DEAD_GONE",
    },
    {
        "case_id": "dnf-notfound-dead-false-broken",
        "kind": "delete_liveness_pair",
        "receipt": "not_found",
        "process_alive": False,
        "observed": "BROKEN",
        "expect_judge": "FAIL",
        "expect_reason": "NOTFOUND_DEAD_FALSE_BROKEN",
    },
    # --- ③ ok ∧ dead honest broken ---
    {
        "case_id": "dnf-ok-dead-honest-must-fail",
        "kind": "delete_liveness_pair",
        "receipt": "ok",
        "process_alive": False,
        "observed": "MUST_FAIL",
        "expect_judge": "PASS",
        "expect_reason": "OK_DEAD_HONEST_BROKEN",
    },
    {
        "case_id": "dnf-ok-dead-false-success-label",
        "kind": "delete_liveness_pair",
        "receipt": "ok",
        "process_alive": False,
        "observed": "FALSE_SUCCESS",
        "expect_judge": "PASS",
        "expect_reason": "OK_DEAD_HONEST_BROKEN",
    },
    # --- ④ ok ∧ alive ---
    {
        "case_id": "dnf-ok-alive-pass",
        "kind": "delete_liveness_pair",
        "receipt": "ok",
        "process_alive": True,
        "observed": "OK",
        "expect_judge": "PASS",
        "expect_reason": "DELETE_OK_ALIVE",
    },
    {
        "case_id": "dnf-ok-alive-false-broken",
        "kind": "delete_liveness_pair",
        "receipt": "ok",
        "process_alive": True,
        "observed": "BROKEN",
        "expect_judge": "FAIL",
        "expect_reason": "OK_ALIVE_FALSE_BROKEN",
    },
    # --- typing / closed-set ---
    {
        "case_id": "dnf-typed-bool-coerce",
        "kind": "delete_liveness_pair",
        "receipt": "ok",
        "process_alive": 1,
        "observed": "OK",
        "expect_judge": "FAIL",
        "expect_reason": "TYPED_BOOL_COERCE",
    },
    {
        "case_id": "dnf-receipt-unknown",
        "kind": "delete_liveness_pair",
        "receipt": "pending",
        "process_alive": True,
        "observed": "OK",
        "expect_judge": "FAIL",
        "expect_reason": "RECEIPT_UNKNOWN",
    },
    {
        "case_id": "dnf-receipt-absent",
        "kind": "delete_liveness_pair",
        "process_alive": True,
        "observed": "OK",
        "expect_judge": "FAIL",
        "expect_reason": "RECEIPT_ABSENT",
    },
    {
        "case_id": "dnf-alive-absent",
        "kind": "delete_liveness_pair",
        "receipt": "ok",
        "observed": "OK",
        "expect_judge": "FAIL",
        "expect_reason": "PROCESS_ALIVE_ABSENT",
    },
    {
        "case_id": "dnf-observed-absent",
        "kind": "delete_liveness_pair",
        "receipt": "not_found",
        "process_alive": True,
        "expect_judge": "FAIL",
        "expect_reason": "OBSERVED_ABSENT",
    },
]


def main() -> int:
    results = []
    failures = []
    for case in CASES:
        receipt = {k: v for k, v in case.items() if k not in ("case_id", "expect_judge", "expect_reason")}
        out = judge(receipt)
        ok = out.get("judge") == case["expect_judge"] and out.get("reason_code") == case["expect_reason"]
        row = {
            "case_id": case["case_id"],
            "ok": ok,
            "expect_judge": case["expect_judge"],
            "expect_reason": case["expect_reason"],
            "got": out,
        }
        results.append(row)
        if not ok:
            failures.append(row)

    payload = {
        "fixture": "DELETE_NOTFOUND_STILL_RUNNING",
        "version": "v0.1",
        "policy": "analyze_only REFERENCE_ONLY fictional_desensitized no_secrets",
        "credit": ["52Hz"],
        "n_cases": len(CASES),
        "n_pass": len(CASES) - len(failures),
        "n_fail": len(failures),
        "results": results,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    payload["run_out_sha256"] = digest
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)
    print(text)
    print(f"META={'PASS' if not failures else 'FAIL'} cases={len(CASES)} fail={len(failures)}", file=sys.stderr)
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
