#!/usr/bin/env python3
"""CRITERIA_VERSION_BATCH v0.1

Structure-only fixture. Failure shape from 随风绿柳 (EigenFlux PM):

  Input  = same batch of results already judged PASS under criterion rev A
  Op     = upgrade criterion body to rev B (change one rule), but the
           receipt still stamps rev A's batch_id / criteria_version
  Expect = FAIL on batch_id ↔ criteria_body_digest mismatch
           (not PASS)
  Observed false-green = product metadata only records runtime_version,
           never the criterion-body digest, so the ledger still reads PASS
  Evidence = product metadata version + batch fields
  Version anchor = sha256(criterion_body) + batch_id

Also: a reverse/negative arm that is judged SKIP must be listed
separately from PASS — skipped ≠ executed-pass.

Honest path: receipt carries criteria_body_digest matching the body
actually used for the batch, and batch_id is bound to that digest.

Structure source: 随风绿柳 EigenFlux PM (CRITERIA_VERSION_BATCH 负控行).
General fixture; analyze_only. Stdlib only.
"""
from __future__ import annotations

import hashlib
import json
import sys
from typing import Any


def _digest(body: Any) -> str | None:
    if body is None:
        return None
    if isinstance(body, (bytes, bytearray)):
        raw = bytes(body)
    elif isinstance(body, str):
        raw = body.encode("utf-8")
    else:
        raw = json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def judge(receipt: dict[str, Any]) -> dict[str, Any]:
    kind = receipt.get("kind")

    if kind == "batch_resettle":
        # Re-settle a prior PASS batch after a criterion body change.
        prior_batch_id = receipt.get("prior_batch_id")
        stamped_batch_id = receipt.get("stamped_batch_id")
        stamped_criteria_version = receipt.get("stamped_criteria_version")
        runtime_version = receipt.get("runtime_version")
        criteria_body_rev_a = receipt.get("criteria_body_rev_a")
        criteria_body_rev_b = receipt.get("criteria_body_rev_b")
        stamped_criteria_digest = receipt.get("stamped_criteria_digest")
        reported_verdict = receipt.get("reported_verdict")  # PASS|FAIL|SKIP|...
        body_changed = receipt.get("criteria_body_changed")

        if prior_batch_id is None or stamped_batch_id is None:
            return {"judge": "FAIL", "reason_code": "BATCH_ID_MISSING"}
        if criteria_body_rev_a is None or criteria_body_rev_b is None:
            return {"judge": "FAIL", "reason_code": "CRITERIA_BODY_MISSING"}

        dig_a = _digest(criteria_body_rev_a)
        dig_b = _digest(criteria_body_rev_b)
        if dig_a is None or dig_b is None:
            return {"judge": "FAIL", "reason_code": "CRITERIA_DIGEST_UNCOMPUTABLE"}

        actually_changed = dig_a != dig_b
        if body_changed is True and not actually_changed:
            return {"judge": "FAIL", "reason_code": "BODY_CHANGED_FLAG_LIE"}
        if body_changed is False and actually_changed:
            return {"judge": "FAIL", "reason_code": "BODY_CHANGED_FLAG_LIE"}

        # False-green family 1: only runtime_version present, no body digest
        if stamped_criteria_digest in (None, "") and runtime_version not in (None, ""):
            if actually_changed and reported_verdict == "PASS":
                return {
                    "judge": "FAIL",
                    "reason_code": "RUNTIME_VERSION_ONLY_FALSE_GREEN",
                    "detail": {
                        "runtime_version": runtime_version,
                        "dig_a": dig_a,
                        "dig_b": dig_b,
                    },
                }
            if actually_changed:
                return {"judge": "FAIL", "reason_code": "RUNTIME_VERSION_ONLY"}

        # False-green family 2: stamp still says rev A after body → B
        stamp_stuck_on_a = (
            stamped_batch_id == prior_batch_id
            and stamped_criteria_version == receipt.get("criteria_version_rev_a")
            and actually_changed
        )
        if stamp_stuck_on_a:
            if stamped_criteria_digest in (None, "", dig_a) and reported_verdict == "PASS":
                return {
                    "judge": "FAIL",
                    "reason_code": "BATCH_CRITERIA_MISMATCH",
                    "detail": {
                        "stamped_batch_id": stamped_batch_id,
                        "stamped_criteria_version": stamped_criteria_version,
                        "dig_a": dig_a,
                        "dig_b": dig_b,
                    },
                }
            if stamped_criteria_digest == dig_a and actually_changed:
                return {"judge": "FAIL", "reason_code": "BATCH_CRITERIA_MISMATCH"}

        # Honest path: digest matches body actually used (rev B), batch rebound
        if (
            actually_changed
            and stamped_criteria_digest == dig_b
            and stamped_batch_id != prior_batch_id
            and stamped_criteria_version == receipt.get("criteria_version_rev_b")
        ):
            if reported_verdict in ("PASS", "FAIL"):
                return {"judge": "PASS", "reason_code": "HONEST_BATCH_REBIND"}
            if reported_verdict == "SKIP":
                return {"judge": "FAIL", "reason_code": "SKIP_NOT_EXECUTED"}
            return {"judge": "FAIL", "reason_code": "VERDICT_UNEXPECTED"}

        # Body unchanged, stamp consistent
        if (
            not actually_changed
            and stamped_criteria_digest in (dig_a, dig_b)
            and stamped_batch_id == prior_batch_id
        ):
            return {"judge": "PASS", "reason_code": "UNCHANGED_CONSISTENT"}

        return {
            "judge": "FAIL",
            "reason_code": "BATCH_RESETTLE_UNCLASSIFIED",
            "detail": {
                "actually_changed": actually_changed,
                "stamped_criteria_digest": stamped_criteria_digest,
                "reported_verdict": reported_verdict,
            },
        }

    if kind == "skip_vs_pass_split":
        # Reverse/negative arm must not collapse SKIP into PASS.
        arms = receipt.get("arms")
        if not isinstance(arms, list) or not arms:
            return {"judge": "FAIL", "reason_code": "ARMS_MISSING"}
        pass_ids = []
        skip_ids = []
        for arm in arms:
            if not isinstance(arm, dict):
                return {"judge": "FAIL", "reason_code": "ARM_SHAPE_INVALID"}
            aid = arm.get("arm_id")
            v = arm.get("verdict")
            if v == "PASS":
                pass_ids.append(aid)
            elif v == "SKIP":
                skip_ids.append(aid)
            elif v in ("FAIL", "UNKNOWN"):
                continue
            else:
                return {"judge": "FAIL", "reason_code": "VERDICT_UNKNOWN", "verdict": v}
        # Collapse detector: ledger reports all_pass while any SKIP exists
        ledger_all_pass = receipt.get("ledger_all_pass")
        if ledger_all_pass is True and skip_ids:
            return {
                "judge": "FAIL",
                "reason_code": "SKIP_COLLAPSED_INTO_PASS",
                "detail": {"skip_ids": skip_ids, "pass_ids": pass_ids},
            }
        # Honest: SKIP listed in its own column/count
        skip_count_field = receipt.get("skip_count")
        if skip_ids:
            if skip_count_field != len(skip_ids):
                return {
                    "judge": "FAIL",
                    "reason_code": "SKIP_NOT_SEPARATED",
                    "detail": {"skip_ids": skip_ids, "skip_count": skip_count_field},
                }
            return {"judge": "PASS", "reason_code": "SKIP_SEPARATED"}
        return {"judge": "PASS", "reason_code": "NO_SKIP_ARMS"}

    if kind == "version_anchor":
        # Anchor = sha256(criterion_body) + batch_id must both be present.
        body = receipt.get("criteria_body")
        batch_id = receipt.get("batch_id")
        anchor = receipt.get("version_anchor")
        if body is None or batch_id in (None, ""):
            return {"judge": "FAIL", "reason_code": "ANCHOR_INPUT_MISSING"}
        dig = _digest(body)
        expected = f"{dig}+{batch_id}"
        if anchor in (None, ""):
            return {"judge": "FAIL", "reason_code": "ANCHOR_MISSING"}
        if anchor != expected:
            return {
                "judge": "FAIL",
                "reason_code": "ANCHOR_MISMATCH",
                "detail": {"expected": expected, "got": anchor},
            }
        return {"judge": "PASS", "reason_code": "ANCHOR_OK"}

    return {"judge": "FAIL", "reason_code": "UNCLASSIFIED", "kind": kind}


# Synthetic criterion bodies (rev A → rev B changes one rule text).
BODY_A = {
    "version": "rev_A",
    "rules": ["R1: denom excludes exhausted", "R2: skip != pass"],
}
BODY_B = {
    "version": "rev_B",
    "rules": ["R1: denom excludes exhausted", "R2: skip != pass", "R3: batch binds digest"],
}
DIG_A = _digest(BODY_A)
DIG_B = _digest(BODY_B)


FIXTURES = [
    {
        "case_id": "FALSE-GREEN-STAMP-STUCK-ON-A",
        "receipt": {
            "kind": "batch_resettle",
            "prior_batch_id": "batch-20261023-A",
            "stamped_batch_id": "batch-20261023-A",
            "stamped_criteria_version": "rev_A",
            "criteria_version_rev_a": "rev_A",
            "criteria_version_rev_b": "rev_B",
            "runtime_version": "runtime-1.2.3",
            "criteria_body_rev_a": BODY_A,
            "criteria_body_rev_b": BODY_B,
            "criteria_body_changed": True,
            "stamped_criteria_digest": DIG_A,
            "reported_verdict": "PASS",
            "note": "判据升到 B，回执仍写 A 的批号 → 应 FAIL",
        },
        "expect": "BATCH_CRITERIA_MISMATCH",
    },
    {
        "case_id": "FALSE-GREEN-RUNTIME-VERSION-ONLY",
        "receipt": {
            "kind": "batch_resettle",
            "prior_batch_id": "batch-20261023-A",
            "stamped_batch_id": "batch-20261023-A",
            "stamped_criteria_version": "rev_A",
            "criteria_version_rev_a": "rev_A",
            "criteria_version_rev_b": "rev_B",
            "runtime_version": "runtime-1.2.3",
            "criteria_body_rev_a": BODY_A,
            "criteria_body_rev_b": BODY_B,
            "criteria_body_changed": True,
            "stamped_criteria_digest": None,
            "reported_verdict": "PASS",
            "note": "元数据只记 runtime_version，不记判据正文摘要",
        },
        "expect": "RUNTIME_VERSION_ONLY_FALSE_GREEN",
    },
    {
        "case_id": "HONEST-BATCH-REBIND",
        "receipt": {
            "kind": "batch_resettle",
            "prior_batch_id": "batch-20261023-A",
            "stamped_batch_id": "batch-20261024-B",
            "stamped_criteria_version": "rev_B",
            "criteria_version_rev_a": "rev_A",
            "criteria_version_rev_b": "rev_B",
            "runtime_version": "runtime-1.2.3",
            "criteria_body_rev_a": BODY_A,
            "criteria_body_rev_b": BODY_B,
            "criteria_body_changed": True,
            "stamped_criteria_digest": DIG_B,
            "reported_verdict": "FAIL",
            "note": "批号与正文摘要一并重绑，诚实重结算",
        },
        "expect": "HONEST_BATCH_REBIND",
    },
    {
        "case_id": "UNCHANGED-CONSISTENT",
        "receipt": {
            "kind": "batch_resettle",
            "prior_batch_id": "batch-20261023-A",
            "stamped_batch_id": "batch-20261023-A",
            "stamped_criteria_version": "rev_A",
            "criteria_version_rev_a": "rev_A",
            "criteria_version_rev_b": "rev_A",
            "runtime_version": "runtime-1.2.3",
            "criteria_body_rev_a": BODY_A,
            "criteria_body_rev_b": BODY_A,
            "criteria_body_changed": False,
            "stamped_criteria_digest": DIG_A,
            "reported_verdict": "PASS",
        },
        "expect": "UNCHANGED_CONSISTENT",
    },
    {
        "case_id": "SKIP-COLLAPSED-INTO-PASS",
        "receipt": {
            "kind": "skip_vs_pass_split",
            "arms": [
                {"arm_id": "forward", "verdict": "PASS"},
                {"arm_id": "reverse", "verdict": "SKIP"},
            ],
            "ledger_all_pass": True,
            "skip_count": 0,
            "note": "反向夹具被 SKIP 却记成全 PASS",
        },
        "expect": "SKIP_COLLAPSED_INTO_PASS",
    },
    {
        "case_id": "SKIP-SEPARATED",
        "receipt": {
            "kind": "skip_vs_pass_split",
            "arms": [
                {"arm_id": "forward", "verdict": "PASS"},
                {"arm_id": "reverse", "verdict": "SKIP"},
            ],
            "ledger_all_pass": False,
            "skip_count": 1,
        },
        "expect": "SKIP_SEPARATED",
    },
    {
        "case_id": "ANCHOR-OK",
        "receipt": {
            "kind": "version_anchor",
            "criteria_body": BODY_B,
            "batch_id": "batch-20261024-B",
            "version_anchor": f"{DIG_B}+batch-20261024-B",
        },
        "expect": "ANCHOR_OK",
    },
    {
        "case_id": "ANCHOR-MISSING",
        "receipt": {
            "kind": "version_anchor",
            "criteria_body": BODY_B,
            "batch_id": "batch-20261024-B",
            "version_anchor": None,
        },
        "expect": "ANCHOR_MISSING",
    },
    {
        "case_id": "ANCHOR-MISMATCH",
        "receipt": {
            "kind": "version_anchor",
            "criteria_body": BODY_B,
            "batch_id": "batch-20261024-B",
            "version_anchor": f"{DIG_A}+batch-20261023-A",
        },
        "expect": "ANCHOR_MISMATCH",
    },
    {
        "case_id": "BODY-CHANGED-FLAG-LIE",
        "receipt": {
            "kind": "batch_resettle",
            "prior_batch_id": "batch-20261023-A",
            "stamped_batch_id": "batch-20261023-A",
            "stamped_criteria_version": "rev_A",
            "criteria_version_rev_a": "rev_A",
            "criteria_version_rev_b": "rev_B",
            "runtime_version": "runtime-1.2.3",
            "criteria_body_rev_a": BODY_A,
            "criteria_body_rev_b": BODY_B,
            "criteria_body_changed": False,
            "stamped_criteria_digest": DIG_A,
            "reported_verdict": "PASS",
        },
        "expect": "BODY_CHANGED_FLAG_LIE",
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
        "fixture": "CRITERIA_VERSION_BATCH",
        "version": "0.1",
        "credit": "随风绿柳",
        "total": len(FIXTURES),
        "passed": ok,
        "dig_a": DIG_A,
        "dig_b": DIG_B,
        "rows": rows,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if ok == len(FIXTURES) else 1


if __name__ == "__main__":
    sys.exit(main())
