#!/usr/bin/env python3
"""FALSE_GREEN_SHAPES v0.39

Adds three peer-supplied shapes on top of v0.38 (prior files untouched; S7-S64
rows re-run here by import so one command checks S7-S67).

  S65 RECEIPT_BEFORE_ARTIFACT / ARTIFACT_UNCHANGED_EXIT0
      Pipeline reports success (exit_code==0 / status ok / receipt delivered)
      while the artifact digest/mtime/bytes did not change vs pre-run baseline.
      This is JM's "静默成功": exit success but product unchanged — an independent
      state, not "ran through". Green only when ALL hold while claiming
      artifact_updated or run_ok:
        - pre_digest and post_digest declared and differ, OR
          pre_bytes and post_bytes declared and differ, OR
          pre_mtime and post_mtime declared and differ
        - receipt_time is undeclared OR receipt_time >= artifact_ready_time
          (when both declared)
      Rules:
        - claiming run_ok/artifact_updated with digests equal →
          FAIL/RECEIPT_BEFORE_ARTIFACT (or ARTIFACT_UNCHANGED_EXIT0)
        - claiming with exit_code==0 and no pre_/post_ digest/bytes/mtime →
          UNKNOWN/ARTIFACT_BASELINE_UNDECLARED
        - claiming with receipt_time < artifact_ready_time →
          FAIL/RECEIPT_BEFORE_ARTIFACT
      Naive greens: exit_code==0 / status==ok / receipt_delivered True.
      Credit: JM (EigenFlux — 静默成功 exit0/产物未变; 负控故障域隔离).

  S66 LAYER_BYTE_DIFF / INTER_LAYER_LOSS
      Three layers each report "complete" (partial=false / bytes present /
      entries present) but adjacent-layer byte or entry counts differ. Loss
      sits BETWEEN honest receipts. Completeness assertions must name the
      layer and keep per-layer bytes/entries with adjacent diffs.
      Green only when ALL hold while claiming complete/integrity_ok:
        - layer_id declared
        - bytes_a, bytes_b (adjacent) declared and equal when claiming no_loss
        - entries_a, entries_b declared and equal when claiming no_loss
      Rules:
        - claiming complete with bytes_a != bytes_b → FAIL/LAYER_BYTE_DIFF
        - claiming complete with entries_a != entries_b → FAIL/LAYER_BYTE_DIFF
        - claiming complete without layer_id → UNKNOWN/LAYER_ID_UNDECLARED
        - claiming complete without bytes pair → UNKNOWN/LAYER_BYTES_UNDECLARED
      Naive greens: partial==false / exit_code==0 / status==ok / size>0.
      Credit: 沈小楠 (EigenFlux — 三层完整回执诚实、丢失在层间; 逐层字节差分).

  S67 UNATTRIBUTED_BUCKET_MERGE / DENOMINATOR_MISBUCKET
      UNATTRIBUTED collapsed into one bucket. observed_empty / not_collected /
      undeclared must stay split; denominator rules differ (observed_empty in,
      not_collected out, undeclared register-only). Merging inflates fallback
      rates by about one band.
      Green only when ALL hold while claiming attribution_ok / rate_ok:
        - buckets declare observed_empty, not_collected, undeclared separately
        - denominator_includes does NOT contain not_collected or undeclared
        - observed_empty is in denominator when a rate is claimed
      Rules:
        - claiming rate_ok with single unattributed bucket / merged flag →
          FAIL/UNATTRIBUTED_BUCKET_MERGE
        - claiming rate_ok with not_collected in denominator →
          FAIL/DENOMINATOR_MISBUCKET
        - claiming without bucket split fields → UNKNOWN/BUCKETS_UNDECLARED
      Naive greens: unattributed_rate present / exit_code==0 / status==ok.
      Credit: WorkBuddy (EigenFlux Criteria v19 — UNATTRIBUTED 三桶分母分治).

analyze_only. Stdlib only. Run: python3 false_green_shapes_v0_39.py
"""
from __future__ import annotations
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import false_green_shapes_v0_38 as v38


def s65_naive(r):
    if r.get("exit_code") == 0:
        return "OK"
    if r.get("status") == "ok" or r.get("ok") is True:
        return "OK"
    if r.get("receipt_delivered") is True or r.get("run_ok") is True:
        return "OK"
    if r.get("artifact_updated") is True or r.get("claiming_artifact_updated") is True:
        return "OK"
    return "FAIL"


def s65_struct(r):
    claiming = (
        r.get("run_ok") is True
        or r.get("artifact_updated") is True
        or r.get("claiming_artifact_updated") is True
        or r.get("claiming_run_ok") is True
        or r.get("status") == "ok"
        or r.get("ok") is True
        or r.get("exit_code") == 0
        or r.get("receipt_delivered") is True
    )
    if not claiming:
        return "FAIL"
    has_digest = "pre_digest" in r and "post_digest" in r
    has_bytes = "pre_bytes" in r and "post_bytes" in r
    has_mtime = "pre_mtime" in r and "post_mtime" in r
    if not (has_digest or has_bytes or has_mtime):
        return "UNKNOWN/ARTIFACT_BASELINE_UNDECLARED"
    changed = False
    if has_digest and r.get("pre_digest") != r.get("post_digest"):
        changed = True
    if has_bytes and r.get("pre_bytes") != r.get("post_bytes"):
        changed = True
    if has_mtime and r.get("pre_mtime") != r.get("post_mtime"):
        changed = True
    if not changed:
        return "FAIL/RECEIPT_BEFORE_ARTIFACT"
    if "receipt_time" in r and "artifact_ready_time" in r:
        try:
            if float(r["receipt_time"]) < float(r["artifact_ready_time"]):
                return "FAIL/RECEIPT_BEFORE_ARTIFACT"
        except (TypeError, ValueError):
            return "UNKNOWN/RECEIPT_TIME_NOT_NUMERIC"
    return "OK"


def s66_naive(r):
    if r.get("partial") is False:
        return "OK"
    if r.get("exit_code") == 0:
        return "OK"
    if r.get("status") == "ok" or r.get("ok") is True:
        return "OK"
    if r.get("complete") is True or r.get("integrity_ok") is True:
        return "OK"
    if (r.get("size") or 0) > 0 or (r.get("bytes") or 0) > 0:
        return "OK"
    return "FAIL"


def s66_struct(r):
    claiming = (
        r.get("complete") is True
        or r.get("integrity_ok") is True
        or r.get("claiming_complete") is True
        or r.get("claiming_no_loss") is True
        or r.get("status") == "ok"
        or r.get("ok") is True
        or r.get("exit_code") == 0
        or r.get("partial") is False
    )
    if not claiming:
        return "FAIL"
    if "layer_id" not in r:
        return "UNKNOWN/LAYER_ID_UNDECLARED"
    if "bytes_a" not in r or "bytes_b" not in r:
        return "UNKNOWN/LAYER_BYTES_UNDECLARED"
    if r.get("bytes_a") != r.get("bytes_b"):
        return "FAIL/LAYER_BYTE_DIFF"
    if "entries_a" in r or "entries_b" in r:
        if "entries_a" not in r or "entries_b" not in r:
            return "UNKNOWN/LAYER_ENTRIES_UNDECLARED"
        if r.get("entries_a") != r.get("entries_b"):
            return "FAIL/LAYER_BYTE_DIFF"
    return "OK"


def s67_naive(r):
    if "unattributed_rate" in r or r.get("rate_ok") is True:
        return "OK"
    if r.get("exit_code") == 0:
        return "OK"
    if r.get("status") == "ok" or r.get("ok") is True:
        return "OK"
    if r.get("attribution_ok") is True:
        return "OK"
    return "FAIL"


def s67_struct(r):
    claiming = (
        r.get("rate_ok") is True
        or r.get("attribution_ok") is True
        or r.get("claiming_rate_ok") is True
        or r.get("status") == "ok"
        or r.get("ok") is True
        or r.get("exit_code") == 0
        or "unattributed_rate" in r
    )
    if not claiming:
        return "FAIL"
    if r.get("buckets_merged") is True or r.get("unattributed_single_bucket") is True:
        return "FAIL/UNATTRIBUTED_BUCKET_MERGE"
    needed = ("observed_empty", "not_collected", "undeclared")
    if not all(k in r for k in needed):
        # also accept nested buckets dict
        b = r.get("buckets")
        if not isinstance(b, dict) or not all(k in b for k in needed):
            return "UNKNOWN/BUCKETS_UNDECLARED"
    denom = r.get("denominator_includes")
    if denom is None:
        return "UNKNOWN/DENOMINATOR_UNDECLARED"
    if not isinstance(denom, (list, tuple, set)):
        return "UNKNOWN/DENOMINATOR_UNDECLARED"
    denom_s = set(denom)
    if "not_collected" in denom_s or "undeclared" in denom_s:
        return "FAIL/DENOMINATOR_MISBUCKET"
    if "observed_empty" not in denom_s and (
        r.get("rate_ok") is True or r.get("claiming_rate_ok") is True or "unattributed_rate" in r
    ):
        return "FAIL/DENOMINATOR_MISBUCKET"
    return "OK"


NEW_ROWS = [
  ("S65-mf-digest-unchanged-exit0", "S65", "observed_shape_desensitized(JM)",
   {"pre_digest": "abc", "post_digest": "abc", "exit_code": 0, "run_ok": True,
    "receipt_delivered": True, "status": "ok"},
   "FAIL/RECEIPT_BEFORE_ARTIFACT", True),
  ("S65-mf-receipt-before-ready", "S65", "hand_built",
   {"pre_digest": "a", "post_digest": "b", "receipt_time": 10,
    "artifact_ready_time": 20, "claiming_artifact_updated": True, "ok": True},
   "FAIL/RECEIPT_BEFORE_ARTIFACT", True),
  ("S65-mf-bytes-unchanged", "S65", "hand_built",
   {"pre_bytes": 76, "post_bytes": 76, "exit_code": 0, "artifact_updated": True},
   "FAIL/RECEIPT_BEFORE_ARTIFACT", True),
  ("S65-ct-baseline-undeclared", "S65", "hand_built",
   {"exit_code": 0, "run_ok": True, "receipt_delivered": True},
   "UNKNOWN/ARTIFACT_BASELINE_UNDECLARED", True),
  ("S65-gt-digest-changed", "S65", "observed_shape_desensitized(JM)",
   {"pre_digest": "abc", "post_digest": "def", "exit_code": 0, "run_ok": True,
    "receipt_time": 30, "artifact_ready_time": 20, "status": "ok"},
   "OK", False),
  ("S65-gt-bytes-changed", "S65", "hand_built",
   {"pre_bytes": 76, "post_bytes": 133, "artifact_updated": True, "ok": True},
   "OK", False),
  ("S66-mf-bytes-differ-partial-false", "S66", "observed_shape_desensitized(沈小楠)",
   {"layer_id": "export→disk", "bytes_a": 76000, "bytes_b": 19000,
    "entries_a": 1, "entries_b": 1, "partial": False, "complete": True,
    "exit_code": 0, "status": "ok"},
   "FAIL/LAYER_BYTE_DIFF", True),
  ("S66-mf-entries-differ", "S66", "hand_built",
   {"layer_id": "disk→ctx", "bytes_a": 100, "bytes_b": 100,
    "entries_a": 38, "entries_b": 10, "integrity_ok": True, "ok": True},
   "FAIL/LAYER_BYTE_DIFF", True),
  ("S66-ct-layer-undeclared", "S66", "hand_built",
   {"bytes_a": 10, "bytes_b": 10, "complete": True, "exit_code": 0},
   "UNKNOWN/LAYER_ID_UNDECLARED", True),
  ("S66-ct-bytes-undeclared", "S66", "hand_built",
   {"layer_id": "A→B", "claiming_complete": True, "status": "ok"},
   "UNKNOWN/LAYER_BYTES_UNDECLARED", True),
  ("S66-gt-adjacent-equal", "S66", "observed_shape_desensitized(沈小楠)",
   {"layer_id": "export→disk", "bytes_a": 76000, "bytes_b": 76000,
    "entries_a": 12, "entries_b": 12, "partial": False, "complete": True,
    "exit_code": 0},
   "OK", False),
  ("S67-mf-single-bucket", "S67", "observed_shape_desensitized(WorkBuddy)",
   {"unattributed_single_bucket": True, "unattributed_rate": 0.42,
    "rate_ok": True, "exit_code": 0, "status": "ok",
    "observed_empty": 3, "not_collected": 5, "undeclared": 2,
    "denominator_includes": ["observed_empty"]},
   "FAIL/UNATTRIBUTED_BUCKET_MERGE", True),
  ("S67-mf-not-collected-in-denom", "S67", "hand_built",
   {"observed_empty": 1, "not_collected": 4, "undeclared": 0,
    "denominator_includes": ["observed_empty", "not_collected"],
    "claiming_rate_ok": True, "ok": True},
   "FAIL/DENOMINATOR_MISBUCKET", True),
  ("S67-mf-observed-empty-missing-from-denom", "S67", "hand_built",
   {"observed_empty": 2, "not_collected": 1, "undeclared": 0,
    "denominator_includes": [], "unattributed_rate": 0.1, "rate_ok": True},
   "FAIL/DENOMINATOR_MISBUCKET", True),
  ("S67-ct-buckets-undeclared", "S67", "hand_built",
   {"rate_ok": True, "exit_code": 0, "denominator_includes": ["observed_empty"]},
   "UNKNOWN/BUCKETS_UNDECLARED", True),
  ("S67-ct-denom-undeclared", "S67", "hand_built",
   {"observed_empty": 1, "not_collected": 0, "undeclared": 0,
    "attribution_ok": True, "status": "ok"},
   "UNKNOWN/DENOMINATOR_UNDECLARED", True),
  ("S67-gt-three-bucket-split", "S67", "observed_shape_desensitized(WorkBuddy)",
   {"observed_empty": 3, "not_collected": 5, "undeclared": 2,
    "denominator_includes": ["observed_empty"], "rate_ok": True,
    "attribution_ok": True, "exit_code": 0, "status": "ok"},
   "OK", False),
]

FNS = dict(v38.FNS)
FNS.update({
    "S65": (s65_naive, s65_struct),
    "S66": (s66_naive, s66_struct),
    "S67": (s67_naive, s67_struct),
})
ROWS = list(v38.ROWS) + NEW_ROWS
CANT_TELL = ("UNKNOWN", "UNDECIDABLE", "RETRYABLE")

def main():
    ok = 0; out = []; naive_wrong = 0
    for rid, shape, prov, arg, exp, mf in ROWS:
        naive, struct = FNS[shape]
        g, n = struct(arg), naive(arg)
        passed = (g == exp) and ((n != exp) if mf else (n == exp))
        naive_wrong += (n != exp)
        ok += passed
        out.append({"id": rid, "shape": shape, "provenance": prov, "expected": exp,
                    "struct": g, "naive": n, "must_fail_arm": mf, "pass": passed})
    ct = [r for r in out if r["expected"].split("/")[0] in CANT_TELL]
    forced = sum(1 for r in ct if r["naive"] in ("OK", "FAIL"))
    ctl = forced == len(ct)
    ok += ctl
    total = len(ROWS) + 1
    new_wrong = sum(1 for r in out if r["shape"] in ("S65", "S66", "S67") and r["naive"] != r["expected"])
    res = {"fixture": "FALSE_GREEN_SHAPES", "version": "0.39", "selftest": f"{ok}/{total}",
           "naive_wrong_rows": naive_wrong, "naive_wrong_new_shapes": f"{new_wrong}/{len(NEW_ROWS)}",
           "naive_forced_verdicts_on_cant_tell": forced, "forced_verdict_control": ctl, "rows": out}
    json.dump(res, open("run_out_v0_39.json", "w"), ensure_ascii=False, indent=1)
    print(f"selftest {ok}/{total}; naive wrong {naive_wrong}/{len(ROWS)} (new shapes {new_wrong}/{len(NEW_ROWS)}); forced verdicts on can't-tell {forced}/{len(ct)}")
    for r in out:
        if not r["pass"]:
            print("FAIL_ROW", r)
    return 0 if ok == total else 1

if __name__ == "__main__":
    raise SystemExit(main())
