#!/usr/bin/env python3
"""EPOCH_FENCE v0.1

Structure-only fixture. Detects multi-writer ledgers that treat either
non-overlapping range pre-allocation OR epoch fencing alone as sufficient.
Either layer alone leaves a hole; both are required to close the failover
collision window.

Four machine-checkable rules (from Hermes structure, EigenFlux):
  1. Range-prealloc alone prevents ID collision but allows dual-writer
     interleave during failover — must NOT be recorded as PASS/safe.
  2. Epoch fence alone still leaves a bare window before the fence takes
     effect — that window must be marked WINDOW_BARE, never PASS.
  3. Both layers present + old-epoch write after new epoch taken MUST
     REJECT (not rely on voluntary stop). Accepting old-epoch after
     advance is EPOCH_REGRESSION.
  4. Injecting the missing layer on a single-layer input MUST flip
     PASS → FAIL; if it does not flip, the layer was never wired.

Structure source: Hermes (EigenFlux) dual-layer fencing write-up.
General fixture; no personal attribution in rows. analyze_only. Stdlib only.
"""
from __future__ import annotations

import json
import sys
from typing import Any


def judge(receipt: dict[str, Any]) -> dict[str, Any]:
    kind = receipt.get("kind")

    if kind == "layer_combo":
        range_present = bool(receipt.get("range_prealloc_present"))
        epoch_present = bool(receipt.get("epoch_fence_present"))
        dual_writers = bool(receipt.get("dual_writers_observed"))
        observed = receipt.get("observed_verdict")  # PASS|FAIL|WINDOW_BARE|INTERLEAVE
        # What the system claimed about safety
        claimed_safe = receipt.get("claimed_safe")

        if not range_present and not epoch_present:
            if observed == "PASS" or claimed_safe is True:
                return {
                    "judge": "FAIL",
                    "reason_code": "NO_LAYER_MARKED_SAFE",
                    "detail": {"observed": observed},
                }
            return {"judge": "PASS", "reason_code": "NO_LAYER_OK"}

        # Range-only: no ID collision but interleave possible
        if range_present and not epoch_present:
            if dual_writers and (observed == "PASS" or claimed_safe is True):
                return {
                    "judge": "FAIL",
                    "reason_code": "RANGE_ONLY_FALSE_SAFE",
                    "detail": {"observed": observed},
                }
            if dual_writers and observed in ("INTERLEAVE", "FAIL"):
                return {"judge": "PASS", "reason_code": "RANGE_ONLY_INTERLEAVE_OK"}
            if not dual_writers and observed == "PASS":
                # single writer, range-only is fine for collision but still incomplete for failover
                return {"judge": "PASS", "reason_code": "RANGE_ONLY_SINGLE_OK"}
            return {
                "judge": "FAIL",
                "reason_code": "RANGE_ONLY_UNEXPECTED",
                "detail": {"observed": observed, "dual_writers": dual_writers},
            }

        # Epoch-only: bare window before fence
        if epoch_present and not range_present:
            window_ms = receipt.get("pre_fence_window_ms")
            if window_ms is None:
                return {"judge": "FAIL", "reason_code": "WINDOW_UNDECLARED"}
            if window_ms > 0 and (observed == "PASS" or claimed_safe is True):
                return {
                    "judge": "FAIL",
                    "reason_code": "EPOCH_ONLY_WINDOW_BARE",
                    "detail": {"pre_fence_window_ms": window_ms},
                }
            if window_ms > 0 and observed == "WINDOW_BARE":
                return {"judge": "PASS", "reason_code": "WINDOW_BARE_OK"}
            if window_ms == 0 and observed == "PASS":
                return {"judge": "PASS", "reason_code": "EPOCH_ONLY_ZERO_WINDOW_OK"}
            return {
                "judge": "FAIL",
                "reason_code": "EPOCH_ONLY_UNEXPECTED",
                "detail": {"observed": observed, "window_ms": window_ms},
            }

        # Both layers present
        if range_present and epoch_present:
            return {"judge": "PASS", "reason_code": "BOTH_LAYERS_PRESENT"}

    if kind == "epoch_advance":
        # Old-epoch write after new epoch taken
        current_epoch = receipt.get("current_epoch")
        write_epoch = receipt.get("write_epoch")
        write_accepted = receipt.get("write_accepted")
        if current_epoch is None or write_epoch is None or write_accepted is None:
            return {"judge": "FAIL", "reason_code": "EPOCH_FIELDS_MISSING"}
        try:
            cur = int(current_epoch)
            wr = int(write_epoch)
        except (TypeError, ValueError):
            return {"judge": "FAIL", "reason_code": "EPOCH_NOT_INT"}

        if wr < cur and write_accepted is True:
            return {
                "judge": "FAIL",
                "reason_code": "EPOCH_REGRESSION",
                "detail": {"current_epoch": cur, "write_epoch": wr},
            }
        if wr < cur and write_accepted is False:
            return {"judge": "PASS", "reason_code": "OLD_EPOCH_REJECTED"}
        if wr == cur and write_accepted is True:
            return {"judge": "PASS", "reason_code": "CURRENT_EPOCH_OK"}
        if wr > cur:
            # future epoch without advance — unexpected
            return {
                "judge": "FAIL",
                "reason_code": "FUTURE_EPOCH_UNADVANCED",
                "detail": {"current_epoch": cur, "write_epoch": wr},
            }
        return {
            "judge": "FAIL",
            "reason_code": "EPOCH_ADVANCE_UNEXPECTED",
            "detail": {"write_accepted": write_accepted},
        }

    if kind == "flip_test":
        before = receipt.get("before_verdict")
        after = receipt.get("after_verdict")
        injected = receipt.get("injected_layer")
        if before is None or after is None:
            return {"judge": "FAIL", "reason_code": "FLIP_PAIR_MISSING"}
        if injected not in ("epoch_fence", "range_prealloc"):
            return {"judge": "FAIL", "reason_code": "INJECT_LAYER_WRONG"}
        if before == after:
            return {
                "judge": "FAIL",
                "reason_code": "FLIP_NOT_WIRED",
                "detail": {"injected": injected},
            }
        if before == "PASS" and after == "FAIL":
            return {"judge": "PASS", "reason_code": "FLIP_OK"}
        return {
            "judge": "FAIL",
            "reason_code": "FLIP_UNEXPECTED",
            "detail": {"before": before, "after": after},
        }

    return {"judge": "FAIL", "reason_code": "UNCLASSIFIED", "kind": kind}


FIXTURES = [
    {
        "case_id": "RANGE-ONLY-FALSE-SAFE",
        "receipt": {
            "kind": "layer_combo",
            "range_prealloc_present": True,
            "epoch_fence_present": False,
            "dual_writers_observed": True,
            "observed_verdict": "PASS",
            "claimed_safe": True,
            "note": "双写交错窗口仍被记成安全",
        },
        "expect": "RANGE_ONLY_FALSE_SAFE",
    },
    {
        "case_id": "RANGE-ONLY-INTERLEAVE-OK",
        "receipt": {
            "kind": "layer_combo",
            "range_prealloc_present": True,
            "epoch_fence_present": False,
            "dual_writers_observed": True,
            "observed_verdict": "INTERLEAVE",
            "claimed_safe": False,
        },
        "expect": "RANGE_ONLY_INTERLEAVE_OK",
    },
    {
        "case_id": "EPOCH-ONLY-WINDOW-BARE",
        "receipt": {
            "kind": "layer_combo",
            "range_prealloc_present": False,
            "epoch_fence_present": True,
            "dual_writers_observed": True,
            "pre_fence_window_ms": 50,
            "observed_verdict": "PASS",
            "claimed_safe": True,
            "note": "围栏生效前窗口仍裸",
        },
        "expect": "EPOCH_ONLY_WINDOW_BARE",
    },
    {
        "case_id": "WINDOW-BARE-OK",
        "receipt": {
            "kind": "layer_combo",
            "range_prealloc_present": False,
            "epoch_fence_present": True,
            "dual_writers_observed": True,
            "pre_fence_window_ms": 50,
            "observed_verdict": "WINDOW_BARE",
            "claimed_safe": False,
        },
        "expect": "WINDOW_BARE_OK",
    },
    {
        "case_id": "BOTH-LAYERS-PRESENT",
        "receipt": {
            "kind": "layer_combo",
            "range_prealloc_present": True,
            "epoch_fence_present": True,
            "dual_writers_observed": False,
            "observed_verdict": "PASS",
            "claimed_safe": True,
        },
        "expect": "BOTH_LAYERS_PRESENT",
    },
    {
        "case_id": "EPOCH-REGRESSION",
        "receipt": {
            "kind": "epoch_advance",
            "current_epoch": 7,
            "write_epoch": 6,
            "write_accepted": True,
            "note": "新 epoch 已取，旧写入仍被接受",
        },
        "expect": "EPOCH_REGRESSION",
    },
    {
        "case_id": "OLD-EPOCH-REJECTED",
        "receipt": {
            "kind": "epoch_advance",
            "current_epoch": 7,
            "write_epoch": 6,
            "write_accepted": False,
        },
        "expect": "OLD_EPOCH_REJECTED",
    },
    {
        "case_id": "CURRENT-EPOCH-OK",
        "receipt": {
            "kind": "epoch_advance",
            "current_epoch": 7,
            "write_epoch": 7,
            "write_accepted": True,
        },
        "expect": "CURRENT_EPOCH_OK",
    },
    {
        "case_id": "FLIP-OK",
        "receipt": {
            "kind": "flip_test",
            "injected_layer": "epoch_fence",
            "before_verdict": "PASS",
            "after_verdict": "FAIL",
        },
        "expect": "FLIP_OK",
    },
    {
        "case_id": "FLIP-NOT-WIRED",
        "receipt": {
            "kind": "flip_test",
            "injected_layer": "epoch_fence",
            "before_verdict": "PASS",
            "after_verdict": "PASS",
        },
        "expect": "FLIP_NOT_WIRED",
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
        "version": "EPOCH_FENCE/v0.1",
        "all_match": ok,
        "n": len(rows),
        "rows": rows,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
