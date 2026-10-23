#!/usr/bin/env python3
"""TRUNC_CACHE_READONLY v0.1

Structure-only fixture. Failure shapes from EigenFlux collab with 茶包
(unattended Agent loop truncated-output recovery):

Arms:
  ① cache_readonly_restore — recovery MUST NOT write back into the cache.
     A restore that mutates cache + reported PASS is CACHE_WRITEBACK_FALSE_PASS.
  ② batch_id_mutual_check — cache filename stamp_batch_id and content
     batch_id must match; mismatch → NOT_COMPARABLE (never take as fresh).
  ③ cache_expired_unobservable — retention-cleaned cache for a pending
     batch upgrades to PERMANENTLY_UNOBSERVABLE; defaulting success is
     CACHE_EXPIRED_FALSE_PASS.
  ④ pending_on_batch_not_cursor — pending reasons live on the batch
     (truncation and empty-return may coexist); watermark marks the last
     batch with confirmed content; recovery re-scans from watermark, not
     from cursor alone. Cursor-as-pending-boundary + PASS → WATERMARK_SKIP.
  ⑤ replay_separate_path — replay receipts MUST be issued on a path
     distinct from the original issuer, and MUST cite original_receipt_id
     + reason_code + fence. Same-hand re-sign is REPLAY_BACKDOOR.

Honest path: restore is read-only, batch ids match, expired → unobservable
(not PASS), pending on batch with watermark boundary, replay on separate
path citing original → PASS allowed.

General fixture; analyze_only. Stdlib only.
Credit: 茶包 (structure); Grok Bot (impl).
"""
from __future__ import annotations

import hashlib
import json
import sys
from typing import Any


def _norm(v: Any) -> str | None:
    if v is None or v == "":
        return None
    return str(v)


def judge(receipt: dict[str, Any]) -> dict[str, Any]:
    kind = receipt.get("kind")
    reported = receipt.get("reported_verdict")  # PASS|FAIL|UNOBSERVABLE|NOT_COMPARABLE

    if kind == "cache_readonly_restore":
        wrote_back = bool(receipt.get("restore_wrote_cache"))
        if wrote_back and reported == "PASS":
            return {
                "judge": "FAIL",
                "reason_code": "CACHE_WRITEBACK_FALSE_PASS",
                "detail": {"restore_wrote_cache": True},
            }
        if wrote_back:
            return {
                "judge": "FAIL",
                "reason_code": "CACHE_WRITEBACK",
                "detail": {"restore_wrote_cache": True},
            }
        if reported in ("PASS", "FAIL"):
            return {"judge": "PASS", "reason_code": "HONEST_CACHE_READONLY"}
        return {"judge": "FAIL", "reason_code": "REPORTED_VERDICT_MISSING"}

    if kind == "batch_id_mutual_check":
        stamp = _norm(receipt.get("stamp_batch_id"))
        content = _norm(receipt.get("content_batch_id"))
        if stamp is None or content is None:
            return {"judge": "FAIL", "reason_code": "BATCH_ID_ABSENT"}
        mismatch = stamp != content
        if mismatch and reported == "PASS":
            return {
                "judge": "FAIL",
                "reason_code": "BATCH_ID_MISMATCH_FALSE_PASS",
                "detail": {"stamp_batch_id": stamp, "content_batch_id": content},
            }
        if mismatch:
            if reported == "NOT_COMPARABLE":
                return {"judge": "PASS", "reason_code": "HONEST_NOT_COMPARABLE"}
            return {
                "judge": "FAIL",
                "reason_code": "BATCH_ID_MISMATCH",
                "detail": {"stamp_batch_id": stamp, "content_batch_id": content},
            }
        if reported in ("PASS", "FAIL"):
            return {"judge": "PASS", "reason_code": "HONEST_BATCH_ID_MATCH"}
        return {"judge": "FAIL", "reason_code": "REPORTED_VERDICT_MISSING"}

    if kind == "cache_expired_unobservable":
        expired = bool(receipt.get("cache_expired"))
        pending = bool(receipt.get("batch_pending"))
        if expired and pending and reported == "PASS":
            return {
                "judge": "FAIL",
                "reason_code": "CACHE_EXPIRED_FALSE_PASS",
                "detail": {"cache_expired": True, "batch_pending": True},
            }
        if expired and pending:
            if reported == "UNOBSERVABLE":
                return {"judge": "PASS", "reason_code": "HONEST_PERMANENTLY_UNOBSERVABLE"}
            return {
                "judge": "FAIL",
                "reason_code": "CACHE_EXPIRED_NOT_ESCALATED",
                "detail": {"reported_verdict": reported},
            }
        if reported in ("PASS", "FAIL", "UNOBSERVABLE"):
            return {"judge": "PASS", "reason_code": "HONEST_CACHE_STATE"}
        return {"judge": "FAIL", "reason_code": "REPORTED_VERDICT_MISSING"}

    if kind == "pending_on_batch_not_cursor":
        pending_on = _norm(receipt.get("pending_anchor"))  # batch|cursor
        has_watermark = _norm(receipt.get("watermark_batch_id")) is not None
        recover_bound = _norm(receipt.get("recover_bound"))  # watermark|cursor
        if pending_on == "cursor" and reported == "PASS":
            return {
                "judge": "FAIL",
                "reason_code": "PENDING_ON_CURSOR_FALSE_PASS",
                "detail": {"pending_anchor": pending_on},
            }
        if pending_on != "batch":
            return {
                "judge": "FAIL",
                "reason_code": "PENDING_ANCHOR_NOT_BATCH",
                "detail": {"pending_anchor": pending_on},
            }
        if not has_watermark:
            return {"judge": "FAIL", "reason_code": "WATERMARK_ABSENT"}
        if recover_bound != "watermark" and reported == "PASS":
            return {
                "judge": "FAIL",
                "reason_code": "WATERMARK_SKIP_FALSE_PASS",
                "detail": {"recover_bound": recover_bound},
            }
        if recover_bound != "watermark":
            return {
                "judge": "FAIL",
                "reason_code": "WATERMARK_SKIP",
                "detail": {"recover_bound": recover_bound},
            }
        if reported in ("PASS", "FAIL"):
            return {"judge": "PASS", "reason_code": "HONEST_WATERMARK_BOUND"}
        return {"judge": "FAIL", "reason_code": "REPORTED_VERDICT_MISSING"}

    if kind == "replay_separate_path":
        same_hand = bool(receipt.get("replay_same_issuer"))
        orig = _norm(receipt.get("original_receipt_id"))
        reason = _norm(receipt.get("replay_reason_code"))
        fence = _norm(receipt.get("replay_fence"))
        cites = orig is not None and reason is not None and fence is not None
        if same_hand and reported == "PASS":
            return {
                "judge": "FAIL",
                "reason_code": "REPLAY_BACKDOOR_FALSE_PASS",
                "detail": {"replay_same_issuer": True},
            }
        if same_hand:
            return {
                "judge": "FAIL",
                "reason_code": "REPLAY_BACKDOOR",
                "detail": {"replay_same_issuer": True},
            }
        if not cites and reported == "PASS":
            return {
                "judge": "FAIL",
                "reason_code": "REPLAY_UNCITED_FALSE_PASS",
                "detail": {
                    "original_receipt_id": orig,
                    "replay_reason_code": reason,
                    "replay_fence": fence,
                },
            }
        if not cites:
            return {
                "judge": "FAIL",
                "reason_code": "REPLAY_UNCITED",
                "detail": {
                    "original_receipt_id": orig,
                    "replay_reason_code": reason,
                    "replay_fence": fence,
                },
            }
        if reported in ("PASS", "FAIL"):
            return {"judge": "PASS", "reason_code": "HONEST_REPLAY_SEPARATE"}
        return {"judge": "FAIL", "reason_code": "REPORTED_VERDICT_MISSING"}

    return {"judge": "FAIL", "reason_code": "UNKNOWN_KIND", "detail": {"kind": kind}}


CASES: list[dict[str, Any]] = [
    # --- ① cache_readonly_restore ---
    {
        "case_id": "tcr-writeback-false-pass",
        "kind": "cache_readonly_restore",
        "reported_verdict": "PASS",
        "restore_wrote_cache": True,
        "expect_judge": "FAIL",
        "expect_reason": "CACHE_WRITEBACK_FALSE_PASS",
    },
    {
        "case_id": "tcr-writeback-honest-fail",
        "kind": "cache_readonly_restore",
        "reported_verdict": "FAIL",
        "restore_wrote_cache": True,
        "expect_judge": "FAIL",
        "expect_reason": "CACHE_WRITEBACK",
    },
    {
        "case_id": "tcr-readonly-honest-pass",
        "kind": "cache_readonly_restore",
        "reported_verdict": "PASS",
        "restore_wrote_cache": False,
        "expect_judge": "PASS",
        "expect_reason": "HONEST_CACHE_READONLY",
    },
    # --- ② batch_id_mutual_check ---
    {
        "case_id": "tcr-batch-mismatch-false-pass",
        "kind": "batch_id_mutual_check",
        "reported_verdict": "PASS",
        "stamp_batch_id": "b-100",
        "content_batch_id": "b-101",
        "expect_judge": "FAIL",
        "expect_reason": "BATCH_ID_MISMATCH_FALSE_PASS",
    },
    {
        "case_id": "tcr-batch-mismatch-honest-nc",
        "kind": "batch_id_mutual_check",
        "reported_verdict": "NOT_COMPARABLE",
        "stamp_batch_id": "b-100",
        "content_batch_id": "b-101",
        "expect_judge": "PASS",
        "expect_reason": "HONEST_NOT_COMPARABLE",
    },
    {
        "case_id": "tcr-batch-match-honest",
        "kind": "batch_id_mutual_check",
        "reported_verdict": "PASS",
        "stamp_batch_id": "b-100",
        "content_batch_id": "b-100",
        "expect_judge": "PASS",
        "expect_reason": "HONEST_BATCH_ID_MATCH",
    },
    # --- ③ cache_expired_unobservable ---
    {
        "case_id": "tcr-expired-false-pass",
        "kind": "cache_expired_unobservable",
        "reported_verdict": "PASS",
        "cache_expired": True,
        "batch_pending": True,
        "expect_judge": "FAIL",
        "expect_reason": "CACHE_EXPIRED_FALSE_PASS",
    },
    {
        "case_id": "tcr-expired-honest-unobs",
        "kind": "cache_expired_unobservable",
        "reported_verdict": "UNOBSERVABLE",
        "cache_expired": True,
        "batch_pending": True,
        "expect_judge": "PASS",
        "expect_reason": "HONEST_PERMANENTLY_UNOBSERVABLE",
    },
    {
        "case_id": "tcr-fresh-honest-pass",
        "kind": "cache_expired_unobservable",
        "reported_verdict": "PASS",
        "cache_expired": False,
        "batch_pending": False,
        "expect_judge": "PASS",
        "expect_reason": "HONEST_CACHE_STATE",
    },
    # --- ④ pending_on_batch_not_cursor ---
    {
        "case_id": "tcr-pending-cursor-false-pass",
        "kind": "pending_on_batch_not_cursor",
        "reported_verdict": "PASS",
        "pending_anchor": "cursor",
        "watermark_batch_id": "b-50",
        "recover_bound": "cursor",
        "expect_judge": "FAIL",
        "expect_reason": "PENDING_ON_CURSOR_FALSE_PASS",
    },
    {
        "case_id": "tcr-watermark-skip-false-pass",
        "kind": "pending_on_batch_not_cursor",
        "reported_verdict": "PASS",
        "pending_anchor": "batch",
        "watermark_batch_id": "b-50",
        "recover_bound": "cursor",
        "expect_judge": "FAIL",
        "expect_reason": "WATERMARK_SKIP_FALSE_PASS",
    },
    {
        "case_id": "tcr-watermark-honest",
        "kind": "pending_on_batch_not_cursor",
        "reported_verdict": "PASS",
        "pending_anchor": "batch",
        "watermark_batch_id": "b-50",
        "recover_bound": "watermark",
        "expect_judge": "PASS",
        "expect_reason": "HONEST_WATERMARK_BOUND",
    },
    # --- ⑤ replay_separate_path ---
    {
        "case_id": "tcr-replay-backdoor-false-pass",
        "kind": "replay_separate_path",
        "reported_verdict": "PASS",
        "replay_same_issuer": True,
        "original_receipt_id": "r-1",
        "replay_reason_code": "TRUNC_RECOVERY",
        "replay_fence": "f-9",
        "expect_judge": "FAIL",
        "expect_reason": "REPLAY_BACKDOOR_FALSE_PASS",
    },
    {
        "case_id": "tcr-replay-uncited-false-pass",
        "kind": "replay_separate_path",
        "reported_verdict": "PASS",
        "replay_same_issuer": False,
        "original_receipt_id": None,
        "replay_reason_code": "TRUNC_RECOVERY",
        "replay_fence": "f-9",
        "expect_judge": "FAIL",
        "expect_reason": "REPLAY_UNCITED_FALSE_PASS",
    },
    {
        "case_id": "tcr-replay-honest-separate",
        "kind": "replay_separate_path",
        "reported_verdict": "PASS",
        "replay_same_issuer": False,
        "original_receipt_id": "r-1",
        "replay_reason_code": "TRUNC_RECOVERY",
        "replay_fence": "f-9",
        "expect_judge": "PASS",
        "expect_reason": "HONEST_REPLAY_SEPARATE",
    },
]


def run_all() -> dict[str, Any]:
    results = []
    passed = 0
    for case in CASES:
        got = judge(case)
        ok = got.get("judge") == case["expect_judge"] and got.get("reason_code") == case["expect_reason"]
        if ok:
            passed += 1
        results.append(
            {
                "case_id": case["case_id"],
                "ok": ok,
                "expect_judge": case["expect_judge"],
                "expect_reason": case["expect_reason"],
                "got": got,
            }
        )
    payload = {
        "fixture": "TRUNC_CACHE_READONLY",
        "version": "v0.1",
        "total": len(CASES),
        "passed": passed,
        "failed": len(CASES) - passed,
        "results": results,
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["sha256"] = hashlib.sha256(blob).hexdigest()
    return payload


def main() -> int:
    out = run_all()
    json.dump(out, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0 if out["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
