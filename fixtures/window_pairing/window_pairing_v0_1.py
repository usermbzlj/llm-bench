#!/usr/bin/env python3
"""WINDOW_PAIRING v0.1

Structure-only fixture. Failure shapes from EigenFlux collab with 李晨熙
(JSONL line shape + STALE three-gate + sample_set batching + REUSE triad),
cross-checked against peter's read-mode drift (cursor family vs full-set
idempotent read must declare read_family + reconciliation_anchor) and
观照's correction-chain STALE (upstream latest ≠ downstream consumed).

Arms:
  ① write_at_key_fetch — a write issued at key-fetch time must carry a
     pair_id that matches a read window; unpaired write+read reported as
     PASS is a false pass.
  ② ordered_sequence — paired windows share a strictly increasing seq;
     gap / out-of-order must not silent-pass.
  ③ write_acl_intersection — write_acl ∩ read_acl for a paired window
     must be non-empty; empty intersection is a hard fail.
  ④ unpaired_parallel — unpaired windows MUST be listed side-by-side;
     silently merging them into one track is forbidden.
  ⑤ stale_three_gate — STALE hard gates: (a) ttl exceeded, (b) downstream
     unconfirmed (last_seen != current), (c) reuse_state == STALE.
     Any gate trip + reported PASS → STALE_FALSE_PASS.
  ⑥ sample_set_batches — sample_set batches stay on separate tracks;
     merging batches into one denom/track is forbidden (分批不并轨).
  ⑦ reuse_three_state — reuse_state MUST be one of FRESH|REUSE|STALE;
     missing / unknown collapses the gate.

Honest path: every write window paired, seq monotonic, ACL ∩ non-empty,
unpaired listed (not merged), STALE gates clear, sample_set tracks
separate, reuse_state in {FRESH,REUSE,STALE} → PASS allowed.

General fixture; analyze_only. Stdlib only.
Credit: 李晨熙 (structure); peter / 观照 (adjacent shapes); Grok Bot (impl).
"""
from __future__ import annotations

import hashlib
import json
import sys
from typing import Any

REUSE_OK = frozenset({"FRESH", "REUSE", "STALE"})


def _norm(v: Any) -> str | None:
    if v is None or v == "":
        return None
    return str(v)


def _as_int(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def judge(receipt: dict[str, Any]) -> dict[str, Any]:
    kind = receipt.get("kind")
    reported = receipt.get("reported_verdict")  # PASS|FAIL

    if kind == "write_at_key_fetch":
        writes = receipt.get("writes") or []
        reads = receipt.get("reads") or []
        if not isinstance(writes, list) or not isinstance(reads, list):
            return {"judge": "FAIL", "reason_code": "WINDOWS_MISSING"}
        write_pairs = {_norm(w.get("pair_id")) for w in writes if isinstance(w, dict)}
        read_pairs = {_norm(r.get("pair_id")) for r in reads if isinstance(r, dict)}
        write_pairs.discard(None)
        read_pairs.discard(None)
        unpaired_writes = write_pairs - read_pairs
        unpaired_reads = read_pairs - write_pairs
        unpaired = bool(unpaired_writes or unpaired_reads) or (
            (writes or reads) and (not write_pairs or not read_pairs)
        )
        # Also: writes present with no pair_id at all
        bare_writes = any(isinstance(w, dict) and _norm(w.get("pair_id")) is None for w in writes)
        bare_reads = any(isinstance(r, dict) and _norm(r.get("pair_id")) is None for r in reads)
        unpaired = unpaired or bare_writes or bare_reads
        if unpaired and reported == "PASS":
            return {
                "judge": "FAIL",
                "reason_code": "WINDOW_UNPAIRED_FALSE_PASS",
                "detail": {
                    "unpaired_writes": sorted(unpaired_writes),
                    "unpaired_reads": sorted(unpaired_reads),
                    "bare_writes": bare_writes,
                    "bare_reads": bare_reads,
                },
            }
        if unpaired:
            return {
                "judge": "FAIL",
                "reason_code": "WINDOW_UNPAIRED",
                "detail": {
                    "unpaired_writes": sorted(unpaired_writes),
                    "unpaired_reads": sorted(unpaired_reads),
                },
            }
        if reported in ("PASS", "FAIL"):
            return {"judge": "PASS", "reason_code": "HONEST_PAIRING"}
        return {"judge": "FAIL", "reason_code": "REPORTED_VERDICT_MISSING"}

    if kind == "ordered_sequence":
        events = receipt.get("events") or []
        if not isinstance(events, list) or not events:
            return {"judge": "FAIL", "reason_code": "EVENTS_MISSING"}
        seqs: list[int] = []
        for e in events:
            if not isinstance(e, dict):
                continue
            s = _as_int(e.get("seq"))
            if s is None:
                return {"judge": "FAIL", "reason_code": "SEQ_ABSENT"}
            seqs.append(s)
        broken = False
        for i in range(1, len(seqs)):
            if seqs[i] <= seqs[i - 1]:
                broken = True
                break
        if broken and reported == "PASS":
            return {
                "judge": "FAIL",
                "reason_code": "SEQ_OUT_OF_ORDER_FALSE_PASS",
                "detail": {"seqs": seqs},
            }
        if broken:
            return {"judge": "FAIL", "reason_code": "SEQ_OUT_OF_ORDER", "detail": {"seqs": seqs}}
        if reported in ("PASS", "FAIL"):
            return {"judge": "PASS", "reason_code": "HONEST_ORDERED_SEQ"}
        return {"judge": "FAIL", "reason_code": "REPORTED_VERDICT_MISSING"}

    if kind == "write_acl_intersection":
        write_acl = receipt.get("write_acl") or []
        read_acl = receipt.get("read_acl") or []
        if not isinstance(write_acl, list) or not isinstance(read_acl, list):
            return {"judge": "FAIL", "reason_code": "ACL_MISSING"}
        wset = {_norm(x) for x in write_acl}
        rset = {_norm(x) for x in read_acl}
        wset.discard(None)
        rset.discard(None)
        inter = wset & rset
        if not inter and reported == "PASS":
            return {
                "judge": "FAIL",
                "reason_code": "ACL_INTERSECTION_EMPTY_FALSE_PASS",
                "detail": {"write_acl": sorted(wset), "read_acl": sorted(rset)},
            }
        if not inter:
            return {
                "judge": "FAIL",
                "reason_code": "ACL_INTERSECTION_EMPTY",
                "detail": {"write_acl": sorted(wset), "read_acl": sorted(rset)},
            }
        if reported in ("PASS", "FAIL"):
            return {
                "judge": "PASS",
                "reason_code": "HONEST_ACL_INTERSECTION",
                "detail": {"intersection": sorted(inter)},
            }
        return {"judge": "FAIL", "reason_code": "REPORTED_VERDICT_MISSING"}

    if kind == "unpaired_parallel":
        # Unpaired windows must appear in unpaired_list; silent_merge=True is fault.
        windows = receipt.get("windows") or []
        unpaired_list = receipt.get("unpaired_list")
        silent_merge = bool(receipt.get("silent_merge", False))
        if not isinstance(windows, list):
            return {"judge": "FAIL", "reason_code": "WINDOWS_MISSING"}
        pair_ids = [_norm(w.get("pair_id")) for w in windows if isinstance(w, dict)]
        has_none = any(p is None for p in pair_ids)
        # Detect merge: distinct window_ids collapsed under one pair_id count
        wids = [_norm(w.get("window_id")) for w in windows if isinstance(w, dict)]
        n_windows = len([w for w in wids if w is not None])
        n_unique_pairs = len({p for p in pair_ids if p is not None})
        merged_wrong = silent_merge or (
            has_none is False
            and n_windows > n_unique_pairs
            and unpaired_list in (None, [], ())
        )
        # Honest unpaired: unpaired_list enumerates window_ids lacking mates
        if isinstance(unpaired_list, list):
            listed = {_norm(x) for x in unpaired_list}
            listed.discard(None)
        else:
            listed = set()
        needs_list = has_none or any(
            isinstance(w, dict) and _norm(w.get("mate_window_id")) is None for w in windows
        )
        if merged_wrong and reported == "PASS":
            return {
                "judge": "FAIL",
                "reason_code": "UNPAIRED_SILENT_MERGE_FALSE_PASS",
                "detail": {
                    "silent_merge": silent_merge,
                    "n_windows": n_windows,
                    "n_unique_pairs": n_unique_pairs,
                },
            }
        if merged_wrong:
            return {
                "judge": "FAIL",
                "reason_code": "UNPAIRED_SILENT_MERGE",
                "detail": {"silent_merge": silent_merge},
            }
        if needs_list and not listed and reported == "PASS":
            return {"judge": "FAIL", "reason_code": "UNPAIRED_NOT_LISTED_FALSE_PASS"}
        if needs_list and not listed:
            return {"judge": "FAIL", "reason_code": "UNPAIRED_NOT_LISTED"}
        if reported in ("PASS", "FAIL"):
            return {"judge": "PASS", "reason_code": "HONEST_UNPAIRED_PARALLEL"}
        return {"judge": "FAIL", "reason_code": "REPORTED_VERDICT_MISSING"}

    if kind == "stale_three_gate":
        ttl_exceeded = bool(receipt.get("ttl_exceeded", False))
        current_id = _norm(receipt.get("current_correction_id"))
        last_seen = _norm(receipt.get("last_seen_correction_id"))
        reuse_state = _norm(receipt.get("reuse_state"))
        unconfirmed = (
            current_id is not None
            and last_seen is not None
            and current_id != last_seen
        ) or (current_id is not None and last_seen is None)
        stale_reuse = reuse_state == "STALE"
        tripped = ttl_exceeded or unconfirmed or stale_reuse
        detail = {
            "ttl_exceeded": ttl_exceeded,
            "unconfirmed": unconfirmed,
            "reuse_state": reuse_state,
            "current_correction_id": current_id,
            "last_seen_correction_id": last_seen,
        }
        if tripped and reported == "PASS":
            return {"judge": "FAIL", "reason_code": "STALE_FALSE_PASS", "detail": detail}
        if tripped:
            return {"judge": "FAIL", "reason_code": "STALE_GATE_TRIP", "detail": detail}
        if reported in ("PASS", "FAIL"):
            return {"judge": "PASS", "reason_code": "HONEST_STALE_CLEAR"}
        return {"judge": "FAIL", "reason_code": "REPORTED_VERDICT_MISSING"}

    if kind == "sample_set_batches":
        batches = receipt.get("batches") or []
        merged_tracks = bool(receipt.get("merged_tracks", False))
        if not isinstance(batches, list) or not batches:
            return {"judge": "FAIL", "reason_code": "BATCHES_MISSING"}
        track_ids = []
        for b in batches:
            if not isinstance(b, dict):
                continue
            track_ids.append(_norm(b.get("track_id")))
        if None in track_ids:
            return {"judge": "FAIL", "reason_code": "TRACK_ID_ABSENT"}
        # 分批不并轨: each batch keeps its own track_id; merging = one track for many batches
        n_batches = len(track_ids)
        n_tracks = len(set(track_ids))
        illegal = merged_tracks or (n_batches > 1 and n_tracks == 1)
        if illegal and reported == "PASS":
            return {
                "judge": "FAIL",
                "reason_code": "SAMPLE_SET_MERGED_FALSE_PASS",
                "detail": {"n_batches": n_batches, "n_tracks": n_tracks},
            }
        if illegal:
            return {
                "judge": "FAIL",
                "reason_code": "SAMPLE_SET_MERGED",
                "detail": {"n_batches": n_batches, "n_tracks": n_tracks},
            }
        if reported in ("PASS", "FAIL"):
            return {"judge": "PASS", "reason_code": "HONEST_SAMPLE_SET_SEPARATE"}
        return {"judge": "FAIL", "reason_code": "REPORTED_VERDICT_MISSING"}

    if kind == "reuse_three_state":
        reuse_state = _norm(receipt.get("reuse_state"))
        if reuse_state is None:
            code = "REUSE_STATE_MISSING"
            if reported == "PASS":
                return {"judge": "FAIL", "reason_code": "REUSE_STATE_MISSING_FALSE_PASS"}
            return {"judge": "FAIL", "reason_code": code}
        if reuse_state not in REUSE_OK:
            if reported == "PASS":
                return {
                    "judge": "FAIL",
                    "reason_code": "REUSE_STATE_UNKNOWN_FALSE_PASS",
                    "detail": {"reuse_state": reuse_state},
                }
            return {
                "judge": "FAIL",
                "reason_code": "REUSE_STATE_UNKNOWN",
                "detail": {"reuse_state": reuse_state},
            }
        if reported in ("PASS", "FAIL"):
            return {
                "judge": "PASS",
                "reason_code": "HONEST_REUSE_STATE",
                "detail": {"reuse_state": reuse_state},
            }
        return {"judge": "FAIL", "reason_code": "REPORTED_VERDICT_MISSING"}

    return {"judge": "FAIL", "reason_code": "UNKNOWN_KIND"}


CASES: list[dict[str, Any]] = [
    # --- ① write_at_key_fetch ---
    {
        "case_id": "wp-pair-unpaired-false-pass",
        "kind": "write_at_key_fetch",
        "reported_verdict": "PASS",
        "writes": [{"pair_id": "p1", "key": "kA"}],
        "reads": [{"pair_id": "p2", "key": "kA"}],
        "expect_judge": "FAIL",
        "expect_reason": "WINDOW_UNPAIRED_FALSE_PASS",
    },
    {
        "case_id": "wp-pair-bare-write",
        "kind": "write_at_key_fetch",
        "reported_verdict": "FAIL",
        "writes": [{"key": "kA"}],
        "reads": [{"pair_id": "p1", "key": "kA"}],
        "expect_judge": "FAIL",
        "expect_reason": "WINDOW_UNPAIRED",
    },
    {
        "case_id": "wp-pair-honest",
        "kind": "write_at_key_fetch",
        "reported_verdict": "PASS",
        "writes": [{"pair_id": "p1", "key": "kA"}],
        "reads": [{"pair_id": "p1", "key": "kA"}],
        "expect_judge": "PASS",
        "expect_reason": "HONEST_PAIRING",
    },
    # --- ② ordered_sequence ---
    {
        "case_id": "wp-seq-ooo-false-pass",
        "kind": "ordered_sequence",
        "reported_verdict": "PASS",
        "events": [{"seq": 1}, {"seq": 3}, {"seq": 2}],
        "expect_judge": "FAIL",
        "expect_reason": "SEQ_OUT_OF_ORDER_FALSE_PASS",
    },
    {
        "case_id": "wp-seq-honest",
        "kind": "ordered_sequence",
        "reported_verdict": "PASS",
        "events": [{"seq": 1}, {"seq": 2}, {"seq": 3}],
        "expect_judge": "PASS",
        "expect_reason": "HONEST_ORDERED_SEQ",
    },
    # --- ③ write_acl_intersection ---
    {
        "case_id": "wp-acl-empty-false-pass",
        "kind": "write_acl_intersection",
        "reported_verdict": "PASS",
        "write_acl": ["ops", "admin"],
        "read_acl": ["viewer"],
        "expect_judge": "FAIL",
        "expect_reason": "ACL_INTERSECTION_EMPTY_FALSE_PASS",
    },
    {
        "case_id": "wp-acl-honest",
        "kind": "write_acl_intersection",
        "reported_verdict": "PASS",
        "write_acl": ["ops", "admin"],
        "read_acl": ["ops", "viewer"],
        "expect_judge": "PASS",
        "expect_reason": "HONEST_ACL_INTERSECTION",
    },
    # --- ④ unpaired_parallel ---
    {
        "case_id": "wp-parallel-silent-merge-false-pass",
        "kind": "unpaired_parallel",
        "reported_verdict": "PASS",
        "windows": [
            {"window_id": "w1", "pair_id": "same"},
            {"window_id": "w2", "pair_id": "same"},
        ],
        "unpaired_list": [],
        "silent_merge": True,
        "expect_judge": "FAIL",
        "expect_reason": "UNPAIRED_SILENT_MERGE_FALSE_PASS",
    },
    {
        "case_id": "wp-parallel-honest-listed",
        "kind": "unpaired_parallel",
        "reported_verdict": "PASS",
        "windows": [
            {"window_id": "w1", "pair_id": "p1", "mate_window_id": "w2"},
            {"window_id": "w2", "pair_id": "p1", "mate_window_id": "w1"},
            {"window_id": "w3", "pair_id": None, "mate_window_id": None},
        ],
        "unpaired_list": ["w3"],
        "silent_merge": False,
        "expect_judge": "PASS",
        "expect_reason": "HONEST_UNPAIRED_PARALLEL",
    },
    # --- ⑤ stale_three_gate ---
    {
        "case_id": "wp-stale-unconfirmed-false-pass",
        "kind": "stale_three_gate",
        "reported_verdict": "PASS",
        "ttl_exceeded": False,
        "current_correction_id": "c-9",
        "last_seen_correction_id": "c-7",
        "reuse_state": "FRESH",
        "expect_judge": "FAIL",
        "expect_reason": "STALE_FALSE_PASS",
    },
    {
        "case_id": "wp-stale-ttl-trip",
        "kind": "stale_three_gate",
        "reported_verdict": "FAIL",
        "ttl_exceeded": True,
        "current_correction_id": "c-9",
        "last_seen_correction_id": "c-9",
        "reuse_state": "REUSE",
        "expect_judge": "FAIL",
        "expect_reason": "STALE_GATE_TRIP",
    },
    {
        "case_id": "wp-stale-honest-clear",
        "kind": "stale_three_gate",
        "reported_verdict": "PASS",
        "ttl_exceeded": False,
        "current_correction_id": "c-9",
        "last_seen_correction_id": "c-9",
        "reuse_state": "FRESH",
        "expect_judge": "PASS",
        "expect_reason": "HONEST_STALE_CLEAR",
    },
    # --- ⑥ sample_set_batches ---
    {
        "case_id": "wp-sample-merged-false-pass",
        "kind": "sample_set_batches",
        "reported_verdict": "PASS",
        "batches": [
            {"batch_id": "b1", "track_id": "t-shared"},
            {"batch_id": "b2", "track_id": "t-shared"},
        ],
        "merged_tracks": False,
        "expect_judge": "FAIL",
        "expect_reason": "SAMPLE_SET_MERGED_FALSE_PASS",
    },
    {
        "case_id": "wp-sample-honest-separate",
        "kind": "sample_set_batches",
        "reported_verdict": "PASS",
        "batches": [
            {"batch_id": "b1", "track_id": "t1"},
            {"batch_id": "b2", "track_id": "t2"},
        ],
        "merged_tracks": False,
        "expect_judge": "PASS",
        "expect_reason": "HONEST_SAMPLE_SET_SEPARATE",
    },
    # --- ⑦ reuse_three_state ---
    {
        "case_id": "wp-reuse-unknown-false-pass",
        "kind": "reuse_three_state",
        "reported_verdict": "PASS",
        "reuse_state": "CACHED",
        "expect_judge": "FAIL",
        "expect_reason": "REUSE_STATE_UNKNOWN_FALSE_PASS",
    },
    {
        "case_id": "wp-reuse-honest-fresh",
        "kind": "reuse_three_state",
        "reported_verdict": "PASS",
        "reuse_state": "FRESH",
        "expect_judge": "PASS",
        "expect_reason": "HONEST_REUSE_STATE",
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
        "fixture": "WINDOW_PAIRING",
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
