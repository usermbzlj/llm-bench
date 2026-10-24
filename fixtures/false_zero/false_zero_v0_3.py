#!/usr/bin/env python3
"""FALSE_ZERO v0.3

Extends FALSE_ZERO v0.2 with EigenFlux collab 2026-10-24 inbound:

  Arm ⑧ dedup_collision (credit H) — merge only on (key, fingerprint) dual
      equality. Three must-fail / control shapes from H's synthetic samples:
        ① same key, different fingerprint → MUST keep both (declared=2);
           merge-to-1 is FALSE_ZERO.
        ② same key + same fingerprint → MUST merge (declared=1, merged_count=1);
           reporting 2 means dedup degraded to no-op / key-only inverted.
        ③ same key, semantically equal but byte-different (trailing LF) with
           different fingerprints → BYTES_MOVED: keep both digests visible;
           do NOT bump collision_count or merged_count; must not silent-PASS.
      Rules (H):
        - merge predicate is (key, fingerprint) equality, never key-then-payload-
          similarity (silent wash of distinct events).
        - merged_count and collision_count are independent columns; never
          derive via declared − actual (truncation shares that arithmetic).
        - BYTES_MOVED is its own visible counter, not folded into PASS.

  Arm ⑨ read_source_mixup (credit WorkBuddy) — fetch≠history. Counting from
      the live fetch stream while asserting against a history/cache source
      (or vice versa) without an explicit read_source tag is FALSE_ZERO.
      Distinct-id set from source A must not be used as presence evidence for
      source B. Bounded-drain style: counts must ride with the distinct-id set
      of the *same* read_source.

analyze_only. Stdlib only.
Credit: H (dedup collision triad + merge rules); WorkBuddy (fetch≠history /
        READ_SOURCE_MIXUP); Grok Bot (impl).
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


def _as_int(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _dedup_stats(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Apply (key, fingerprint) dual-key merge; surface BYTES_MOVED separately."""
    # presence keyed by (key, fingerprint)
    presence: dict[tuple[str, str], dict[str, Any]] = {}
    merged_count = 0
    collision_count = 0  # same key, different fingerprint (kept as distinct)
    bytes_moved = 0
    bytes_moved_digests: list[str] = []
    # Track payloads per key to detect byte-moved pairs
    by_key: dict[str, list[dict[str, Any]]] = {}

    for e in entries:
        if not isinstance(e, dict):
            continue
        key = _norm(e.get("key"))
        fp = _norm(e.get("fingerprint"))
        payload = e.get("payload")
        if key is None or fp is None:
            continue
        pair = (key, fp)
        by_key.setdefault(key, []).append(e)
        if pair in presence:
            merged_count += 1
        else:
            presence[pair] = e

    # collision: same key appears under ≥2 distinct fingerprints
    for key, group in by_key.items():
        fps = { _norm(g.get("fingerprint")) for g in group }
        fps.discard(None)
        if len(fps) >= 2:
            # Each extra fingerprint beyond the first is a collision unit
            collision_count += len(fps) - 1
            # BYTES_MOVED: same semantic payload bytes differing only by trailing
            # whitespace/LF across different fingerprints under one key
            payloads = []
            for g in group:
                p = g.get("payload")
                if isinstance(p, str):
                    payloads.append(( _norm(g.get("fingerprint")), p))
            # Compare stripped equality with raw inequality
            for i in range(len(payloads)):
                for j in range(i + 1, len(payloads)):
                    fpa, pa = payloads[i]
                    fpb, pb = payloads[j]
                    if fpa == fpb:
                        continue
                    if pa != pb and pa.strip() == pb.strip():
                        bytes_moved += 1
                        for d in (fpa, fpb):
                            if d and d not in bytes_moved_digests:
                                bytes_moved_digests.append(d)

    return {
        "declared": len(presence),
        "merged_count": merged_count,
        "collision_count": collision_count,
        "bytes_moved": bytes_moved,
        "bytes_moved_digests": bytes_moved_digests,
    }


def judge(receipt: dict[str, Any]) -> dict[str, Any]:
    kind = receipt.get("kind")
    reported = receipt.get("reported_verdict")

    # --- Arm ⑧ dedup_collision (H) ---
    if kind == "dedup_collision":
        entries = receipt.get("entries")
        if not isinstance(entries, list):
            return {"judge": "FAIL", "reason_code": "ENTRIES_MISSING"}
        # Guard first: never derive counts via declared − actual (truncation
        # shares that arithmetic and would disguise merge as clean).
        derived_via_diff = bool(receipt.get("derived_via_declared_minus_actual", False))
        if derived_via_diff and reported == "PASS":
            return {"judge": "FAIL", "reason_code": "DERIVED_VIA_DIFF_FALSE_ZERO"}
        if derived_via_diff:
            return {"judge": "FAIL", "reason_code": "DERIVED_VIA_DIFF"}
        stats = _dedup_stats(entries)
        declared = _as_int(receipt.get("declared"))
        merged_count = _as_int(receipt.get("merged_count"))
        collision_count = _as_int(receipt.get("collision_count"))
        bytes_moved = _as_int(receipt.get("bytes_moved"))
        merge_pred = _norm(receipt.get("merge_predicate"))  # dual_key|key_only|payload_sim

        expect = _norm(receipt.get("expect_shape"))
        # ① same key different fp → keep both
        if expect == "same_key_diff_fp":
            if stats["declared"] != 2 or stats["collision_count"] < 1:
                return {
                    "judge": "FAIL",
                    "reason_code": "ORACLE_SHAPE_MISMATCH",
                    "detail": stats,
                }
            if declared == 1 or (merge_pred in ("key_only", "payload_sim")):
                if reported == "PASS":
                    return {
                        "judge": "FAIL",
                        "reason_code": "DEDUP_COLLISION_MERGED_FALSE_ZERO",
                        "detail": {"declared": declared, "oracle": stats},
                    }
                return {
                    "judge": "FAIL",
                    "reason_code": "DEDUP_COLLISION_MERGED",
                    "detail": {"declared": declared, "oracle": stats},
                }
            if declared == 2 and collision_count is not None and collision_count >= 1:
                if merged_count == 0 and reported in ("PASS", "FAIL"):
                    return {"judge": "PASS", "reason_code": "DEDUP_COLLISION_KEPT"}
                if merged_count and merged_count > 0 and reported == "PASS":
                    return {
                        "judge": "FAIL",
                        "reason_code": "DEDUP_COLLISION_MERGED_FALSE_ZERO",
                    }
            if reported == "PASS" and (declared or 0) < 2:
                return {
                    "judge": "FAIL",
                    "reason_code": "DEDUP_COLLISION_MERGED_FALSE_ZERO",
                }
            return {"judge": "FAIL", "reason_code": "DEDUP_COLLISION_UNHANDLED", "detail": {"declared": declared, "oracle": stats}}

        # ② same key same fp → must merge
        if expect == "same_key_same_fp":
            if stats["declared"] != 1 or stats["merged_count"] < 1:
                return {
                    "judge": "FAIL",
                    "reason_code": "ORACLE_SHAPE_MISMATCH",
                    "detail": stats,
                }
            if declared == 2 or merged_count == 0:
                if reported == "PASS":
                    return {
                        "judge": "FAIL",
                        "reason_code": "DEDUP_NOOP_FALSE_ZERO",
                        "detail": {"declared": declared, "merged_count": merged_count},
                    }
                return {
                    "judge": "FAIL",
                    "reason_code": "DEDUP_NOOP",
                    "detail": {"declared": declared, "merged_count": merged_count},
                }
            if declared == 1 and merged_count == 1 and reported in ("PASS", "FAIL"):
                return {"judge": "PASS", "reason_code": "DEDUP_MERGED_OK"}
            return {"judge": "FAIL", "reason_code": "DEDUP_SAME_FP_UNHANDLED"}

        # ③ bytes-moved: trailing LF / whitespace-only payload drift
        if expect == "bytes_moved":
            if stats["bytes_moved"] < 1 or stats["declared"] != 2:
                return {
                    "judge": "FAIL",
                    "reason_code": "ORACLE_SHAPE_MISMATCH",
                    "detail": stats,
                }
            # Must NOT classify as merge or collision
            if (merged_count or 0) > 0:
                return {
                    "judge": "FAIL",
                    "reason_code": "BYTES_MOVED_COUNTED_AS_MERGE",
                    "detail": {"merged_count": merged_count},
                }
            if (collision_count or 0) > 0 and (bytes_moved or 0) == 0:
                # collision bumped but bytes_moved invisible → wrong bucket
                if reported == "PASS":
                    return {
                        "judge": "FAIL",
                        "reason_code": "BYTES_MOVED_SILENT_PASS",
                        "detail": {"collision_count": collision_count},
                    }
                return {
                    "judge": "FAIL",
                    "reason_code": "BYTES_MOVED_AS_COLLISION",
                    "detail": {"collision_count": collision_count},
                }
            if (bytes_moved or 0) < 1:
                if reported == "PASS":
                    return {"judge": "FAIL", "reason_code": "BYTES_MOVED_SILENT_PASS"}
                return {"judge": "FAIL", "reason_code": "BYTES_MOVED_INVISIBLE"}
            # Honest: both digests visible, bytes_moved ≥ 1, not folded into PASS-as-clean
            digests = receipt.get("bytes_moved_digests") or []
            if not isinstance(digests, list) or len(digests) < 2:
                return {
                    "judge": "FAIL",
                    "reason_code": "BYTES_MOVED_DIGESTS_MISSING",
                }
            if reported in ("PASS", "FAIL", "BYTES_MOVED"):
                # PASS only ok if bytes_moved visible (not silent)
                if reported == "PASS" and (bytes_moved or 0) >= 1 and len(digests) >= 2:
                    return {"judge": "PASS", "reason_code": "BYTES_MOVED_VISIBLE"}
                if reported in ("FAIL", "BYTES_MOVED"):
                    return {"judge": "PASS", "reason_code": "BYTES_MOVED_FLAGGED"}
            return {"judge": "FAIL", "reason_code": "BYTES_MOVED_UNHANDLED"}

        return {"judge": "FAIL", "reason_code": "DEDUP_EXPECT_SHAPE_UNKNOWN", "detail": {"expect": expect}}

    # --- Arm ⑨ read_source_mixup (WorkBuddy fetch≠history) ---
    if kind == "read_source_mixup":
        count_source = _norm(receipt.get("count_source"))  # fetch|history|cache
        assert_source = _norm(receipt.get("assert_source"))
        read_source_tag = _norm(receipt.get("read_source_tag"))
        distinct_ids_source = _norm(receipt.get("distinct_ids_source"))
        presence_claimed_for = _norm(receipt.get("presence_claimed_for"))
        enter_pass = receipt.get("enter_pass_numerator")

        if count_source is None or assert_source is None:
            return {"judge": "FAIL", "reason_code": "READ_SOURCE_FIELDS_MISSING"}

        mixed = count_source != assert_source
        ids_mixed = (
            distinct_ids_source is not None
            and presence_claimed_for is not None
            and distinct_ids_source != presence_claimed_for
        )
        tag_absent = read_source_tag is None
        tag_mismatch = (
            read_source_tag is not None
            and count_source is not None
            and read_source_tag != count_source
        )

        if mixed or ids_mixed:
            if reported == "PASS" or enter_pass is True:
                return {
                    "judge": "FAIL",
                    "reason_code": "READ_SOURCE_MIXUP_FALSE_ZERO",
                    "detail": {
                        "count_source": count_source,
                        "assert_source": assert_source,
                        "distinct_ids_source": distinct_ids_source,
                        "presence_claimed_for": presence_claimed_for,
                    },
                }
            if tag_absent:
                return {
                    "judge": "FAIL",
                    "reason_code": "READ_SOURCE_MIXUP_NO_TAG",
                    "detail": {"count_source": count_source, "assert_source": assert_source},
                }
            if reported in ("FAIL", "DEGRADED", "UNKNOWN", "READ_SOURCE_MIXUP"):
                return {"judge": "PASS", "reason_code": "READ_SOURCE_MIXUP_CAUGHT"}
            return {"judge": "FAIL", "reason_code": "READ_SOURCE_MIXUP_BAD_VERDICT"}

        # Honest same-source
        if count_source == assert_source and not ids_mixed:
            if tag_mismatch:
                return {"judge": "FAIL", "reason_code": "READ_SOURCE_TAG_MISMATCH"}
            if reported in ("PASS", "FAIL"):
                return {"judge": "PASS", "reason_code": "READ_SOURCE_ALIGNED"}
            return {"judge": "FAIL", "reason_code": "READ_SOURCE_ALIGNED_BAD_VERDICT"}

        return {"judge": "FAIL", "reason_code": "READ_SOURCE_UNHANDLED"}

    return {"judge": "FAIL", "reason_code": "UNKNOWN_KIND"}


def cases() -> list[dict[str, Any]]:
    return [
        # Arm ⑧-① same key, different fingerprint — must keep both
        {
            "id": "A8_mf_same_key_diff_fp_merged",
            "kind": "dedup_collision",
            "expect_shape": "same_key_diff_fp",
            "entries": [
                {"key": "k1", "fingerprint": "sha256:aaaa", "payload": '{"v":1}'},
                {"key": "k1", "fingerprint": "sha256:bbbb", "payload": '{"v":2}'},
            ],
            "declared": 1,
            "merged_count": 1,
            "collision_count": 0,
            "bytes_moved": 0,
            "merge_predicate": "key_only",
            "reported_verdict": "PASS",
            "expect_reason": "DEDUP_COLLISION_MERGED_FALSE_ZERO",
        },
        {
            "id": "A8_ok_same_key_diff_fp_kept",
            "kind": "dedup_collision",
            "expect_shape": "same_key_diff_fp",
            "entries": [
                {"key": "k1", "fingerprint": "sha256:aaaa", "payload": '{"v":1}'},
                {"key": "k1", "fingerprint": "sha256:bbbb", "payload": '{"v":2}'},
            ],
            "declared": 2,
            "merged_count": 0,
            "collision_count": 1,
            "bytes_moved": 0,
            "merge_predicate": "dual_key",
            "reported_verdict": "PASS",
            "expect_reason": "DEDUP_COLLISION_KEPT",
        },
        # Arm ⑧-② same key same fingerprint — must merge
        {
            "id": "A8_mf_same_key_same_fp_noop",
            "kind": "dedup_collision",
            "expect_shape": "same_key_same_fp",
            "entries": [
                {"key": "k2", "fingerprint": "sha256:cccc", "payload": '{"v":3}'},
                {"key": "k2", "fingerprint": "sha256:cccc", "payload": '{"v":3}'},
            ],
            "declared": 2,
            "merged_count": 0,
            "collision_count": 0,
            "bytes_moved": 0,
            "merge_predicate": "dual_key",
            "reported_verdict": "PASS",
            "expect_reason": "DEDUP_NOOP_FALSE_ZERO",
        },
        {
            "id": "A8_ok_same_key_same_fp_merged",
            "kind": "dedup_collision",
            "expect_shape": "same_key_same_fp",
            "entries": [
                {"key": "k2", "fingerprint": "sha256:cccc", "payload": '{"v":3}'},
                {"key": "k2", "fingerprint": "sha256:cccc", "payload": '{"v":3}'},
            ],
            "declared": 1,
            "merged_count": 1,
            "collision_count": 0,
            "bytes_moved": 0,
            "merge_predicate": "dual_key",
            "reported_verdict": "PASS",
            "expect_reason": "DEDUP_MERGED_OK",
        },
        # Arm ⑧-③ bytes-moved trailing LF
        {
            "id": "A8_mf_bytes_moved_silent_pass",
            "kind": "dedup_collision",
            "expect_shape": "bytes_moved",
            "entries": [
                {"key": "k3", "fingerprint": "sha256:dddd", "payload": '{"v":4}'},
                {"key": "k3", "fingerprint": "sha256:eeee", "payload": '{"v":4}\n'},
            ],
            "declared": 2,
            "merged_count": 0,
            "collision_count": 0,
            "bytes_moved": 0,
            "bytes_moved_digests": [],
            "merge_predicate": "dual_key",
            "reported_verdict": "PASS",
            "expect_reason": "BYTES_MOVED_SILENT_PASS",
        },
        {
            "id": "A8_mf_bytes_moved_as_collision",
            "kind": "dedup_collision",
            "expect_shape": "bytes_moved",
            "entries": [
                {"key": "k3", "fingerprint": "sha256:dddd", "payload": '{"v":4}'},
                {"key": "k3", "fingerprint": "sha256:eeee", "payload": '{"v":4}\n'},
            ],
            "declared": 2,
            "merged_count": 0,
            "collision_count": 1,
            "bytes_moved": 0,
            "bytes_moved_digests": ["sha256:dddd", "sha256:eeee"],
            "merge_predicate": "dual_key",
            "reported_verdict": "PASS",
            "expect_reason": "BYTES_MOVED_SILENT_PASS",
        },
        {
            "id": "A8_ok_bytes_moved_visible",
            "kind": "dedup_collision",
            "expect_shape": "bytes_moved",
            "entries": [
                {"key": "k3", "fingerprint": "sha256:dddd", "payload": '{"v":4}'},
                {"key": "k3", "fingerprint": "sha256:eeee", "payload": '{"v":4}\n'},
            ],
            "declared": 2,
            "merged_count": 0,
            "collision_count": 0,
            "bytes_moved": 1,
            "bytes_moved_digests": ["sha256:dddd", "sha256:eeee"],
            "merge_predicate": "dual_key",
            "reported_verdict": "PASS",
            "expect_reason": "BYTES_MOVED_VISIBLE",
        },
        {
            "id": "A8_mf_derived_via_diff",
            "kind": "dedup_collision",
            "expect_shape": "same_key_diff_fp",
            "entries": [
                {"key": "k1", "fingerprint": "sha256:aaaa", "payload": '{"v":1}'},
                {"key": "k1", "fingerprint": "sha256:bbbb", "payload": '{"v":2}'},
            ],
            "declared": 2,
            "merged_count": 0,
            "collision_count": 1,
            "bytes_moved": 0,
            "merge_predicate": "dual_key",
            "derived_via_declared_minus_actual": True,
            "reported_verdict": "PASS",
            "expect_reason": "DERIVED_VIA_DIFF_FALSE_ZERO",
        },
        # Arm ⑨ WorkBuddy fetch≠history
        {
            "id": "A9_mf_fetch_count_history_assert",
            "kind": "read_source_mixup",
            "count_source": "fetch",
            "assert_source": "history",
            "distinct_ids_source": "fetch",
            "presence_claimed_for": "history",
            "read_source_tag": None,
            "enter_pass_numerator": True,
            "reported_verdict": "PASS",
            "expect_reason": "READ_SOURCE_MIXUP_FALSE_ZERO",
        },
        {
            "id": "A9_mf_mixup_no_tag",
            "kind": "read_source_mixup",
            "count_source": "history",
            "assert_source": "fetch",
            "distinct_ids_source": "history",
            "presence_claimed_for": "fetch",
            "read_source_tag": None,
            "enter_pass_numerator": False,
            "reported_verdict": "FAIL",
            "expect_reason": "READ_SOURCE_MIXUP_NO_TAG",
        },
        {
            "id": "A9_ok_mixup_caught",
            "kind": "read_source_mixup",
            "count_source": "fetch",
            "assert_source": "cache",
            "distinct_ids_source": "fetch",
            "presence_claimed_for": "cache",
            "read_source_tag": "fetch",
            "enter_pass_numerator": False,
            "reported_verdict": "READ_SOURCE_MIXUP",
            "expect_reason": "READ_SOURCE_MIXUP_CAUGHT",
        },
        {
            "id": "A9_ok_aligned",
            "kind": "read_source_mixup",
            "count_source": "fetch",
            "assert_source": "fetch",
            "distinct_ids_source": "fetch",
            "presence_claimed_for": "fetch",
            "read_source_tag": "fetch",
            "enter_pass_numerator": True,
            "reported_verdict": "PASS",
            "expect_reason": "READ_SOURCE_ALIGNED",
        },
    ]


def main() -> int:
    rows = []
    ok = 0
    for c in cases():
        expect = c.get("expect_reason")
        payload = {k: v for k, v in c.items() if k not in ("id", "expect_reason")}
        result = judge(payload)
        passed = result.get("reason_code") == expect
        if passed:
            ok += 1
        rows.append(
            {
                "id": c["id"],
                "expect_reason": expect,
                "got": result,
                "pass": passed,
            }
        )
    out = {
        "fixture": "FALSE_ZERO",
        "version": "v0.3",
        "credit": ["H", "WorkBuddy"],
        "rows": len(rows),
        "passed": ok,
        "all_pass": ok == len(rows),
        "results": rows,
    }
    text = json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True)
    print(text)
    with open(__file__, "rb") as f:
        script_sha = hashlib.sha256(f.read()).hexdigest()
    run_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    meta = {
        "script_sha256": script_sha,
        "run_out_sha256": run_sha,
        "passed": f"{ok}/{len(rows)}",
    }
    print("META " + json.dumps(meta), file=sys.stderr)
    return 0 if ok == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
