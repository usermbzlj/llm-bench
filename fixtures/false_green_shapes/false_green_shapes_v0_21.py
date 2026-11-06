#!/usr/bin/env python3
"""FALSE_GREEN_SHAPES v0.21

Adds one peer-supplied shape on top of v0.20 (prior files untouched; S7-S32
rows re-run here by import so one command checks S7-S33).

  S33 FINGERPRINT_NOT_RUN_SCOPED  Content-hash / prior-round fingerprint match
                              must not green-wash a readback of another run's
                              artifact. Naive treats
                              (exit_code==0 && content_hash==prior_content_hash)
                              as OK. Struct:
                                - artifact_run_id undeclared ->
                                  UNKNOWN/RUN_SCOPE_UNDECLARED
                                - exit 0 + hashes match +
                                  artifact_run_id != current_run_id ->
                                  FAIL/FINGERPRINT_NOT_RUN_SCOPED
                                - exit 0 + hashes match + same run_id -> OK
                                  (honest byte-stable rewrite / no-op write
                                  inside this run)
                                - exit 0 + write_confirmed True + same run_id
                                  (even if prior hash absent) -> OK
                                - batch idempotency: completed_subitems missing
                                  while claiming full batch replay skip ->
                                  UNKNOWN/SUBITEM_COMPLETION_UNDECLARED
                                - partial prior success replayed as full batch
                                  without per-subitem skip list ->
                                  FAIL/PARTIAL_BATCH_REPLAY_UNSCOPED
                              Credit: Hermes (EigenFlux broadcast —
                              「跨轮指纹对拍：哈希对上旧文件整轮报绿；
                              指纹必须绑 run_id；批次幂等外还要已完成子项清单」).

Each shape: must-fail arm (naive wrong) + green twin.
analyze_only. Stdlib only. Run: python3 false_green_shapes_v0_21.py
"""
from __future__ import annotations
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import false_green_shapes_v0_20 as v20


def s33_naive(r):
    # Naive: exit 0 + content hash equals prior => OK (ignores run scope)
    code = r.get("exit_code")
    try:
        code_i = int(code) if code is not None else None
    except (TypeError, ValueError):
        return "FAIL"
    ch = r.get("content_hash")
    ph = r.get("prior_content_hash")
    if code_i == 0 and ch is not None and ph is not None and ch == ph:
        return "OK"
    if code_i == 0 and r.get("write_confirmed") is True:
        return "OK"
    if code_i == 0 and r.get("batch_idempotent_skip") is True:
        return "OK"
    if code_i is not None and code_i != 0:
        return "FAIL"
    return "FAIL"


def s33_struct(r):
    code = r.get("exit_code")
    try:
        code_i = int(code) if code is not None else None
    except (TypeError, ValueError):
        return "FAIL"

    # Partial-batch replay arm takes precedence when claimed
    if r.get("batch_idempotent_skip") is True:
        subs = r.get("completed_subitems")
        if subs is None:
            return "UNKNOWN/SUBITEM_COMPLETION_UNDECLARED"
        if not isinstance(subs, list):
            return "UNKNOWN/SUBITEM_COMPLETION_UNDECLARED"
        claimed = r.get("batch_claimed_complete")
        prior_done = r.get("prior_completed_count")
        total = r.get("batch_total")
        if claimed is True and prior_done is not None and total is not None:
            try:
                if int(prior_done) < int(total) and len(subs) < int(total):
                    return "FAIL/PARTIAL_BATCH_REPLAY_UNSCOPED"
            except (TypeError, ValueError):
                return "UNKNOWN/SUBITEM_COMPLETION_UNDECLARED"
        if claimed is True and len(subs) >= int(total or len(subs)):
            if code_i == 0:
                return "OK"
        if code_i == 0 and len(subs) > 0:
            return "OK"
        return "FAIL/PARTIAL_BATCH_REPLAY_UNSCOPED"

    cur = r.get("current_run_id")
    art = r.get("artifact_run_id")
    if art is None and cur is not None:
        return "UNKNOWN/RUN_SCOPE_UNDECLARED"
    if art is None and cur is None and "content_hash" in r:
        return "UNKNOWN/RUN_SCOPE_UNDECLARED"

    ch = r.get("content_hash")
    ph = r.get("prior_content_hash")

    if cur is not None and art is not None and cur != art:
        return "FAIL/FINGERPRINT_NOT_RUN_SCOPED"

    if code_i is not None and code_i != 0:
        return "FAIL"

    if cur is not None and art is not None and cur == art:
        if r.get("write_confirmed") is True:
            return "OK"
        if ch is not None and ph is not None and ch == ph:
            return "OK"
        if ch is not None and ph is None:
            return "OK"
        if ch is not None:
            return "OK"
        return "OK"

    return "UNKNOWN/RUN_SCOPE_UNDECLARED"


NEW_ROWS = [
  # Observed: hash matched prior-round file read in another execution → false green
  ("S33-mf-cross-run-hash", "S33", "observed_shape_desensitized(Hermes)",
   {"exit_code": 0, "content_hash": "abc111", "prior_content_hash": "abc111",
    "current_run_id": "run-B", "artifact_run_id": "run-A"},
   "FAIL/FINGERPRINT_NOT_RUN_SCOPED", True),
  # Exit 0 + matching hashes but run scope undeclared
  ("S33-ct-undeclared-scope", "S33", "hand_built",
   {"exit_code": 0, "content_hash": "abc111", "prior_content_hash": "abc111"},
   "UNKNOWN/RUN_SCOPE_UNDECLARED", True),
  # Partial prior success replayed as full batch skip without subitem list
  ("S33-mf-partial-batch", "S33", "observed_shape_desensitized(Hermes)",
   {"exit_code": 0, "batch_idempotent_skip": True, "batch_claimed_complete": True,
    "prior_completed_count": 2, "batch_total": 5, "completed_subitems": ["a", "b"]},
   "FAIL/PARTIAL_BATCH_REPLAY_UNSCOPED", True),
  # Batch skip claimed but completion list absent
  ("S33-ct-subitem-undeclared", "S33", "hand_built",
   {"exit_code": 0, "batch_idempotent_skip": True, "batch_claimed_complete": True,
    "batch_total": 3},
   "UNKNOWN/SUBITEM_COMPLETION_UNDECLARED", True),
  # Green: same run, byte-stable content (honest unchanged)
  ("S33-gt-same-run-stable", "S33", "hand_built",
   {"exit_code": 0, "content_hash": "abc111", "prior_content_hash": "abc111",
    "current_run_id": "run-B", "artifact_run_id": "run-B", "write_confirmed": True},
   "OK", False),
  # Green: full subitem completion list covers batch
  ("S33-gt-subitems-complete", "S33", "hand_built",
   {"exit_code": 0, "batch_idempotent_skip": True, "batch_claimed_complete": True,
    "prior_completed_count": 3, "batch_total": 3,
    "completed_subitems": ["a", "b", "c"]},
   "OK", False),
]

FNS = dict(v20.FNS)
FNS.update({"S33": (s33_naive, s33_struct)})
ROWS = list(v20.ROWS) + NEW_ROWS
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
    new_wrong = sum(1 for r in out if r["shape"] == "S33" and r["naive"] != r["expected"])
    res = {"fixture": "FALSE_GREEN_SHAPES", "version": "0.21", "selftest": f"{ok}/{total}",
           "naive_wrong_rows": naive_wrong, "naive_wrong_new_shapes": f"{new_wrong}/{len(NEW_ROWS)}",
           "naive_forced_verdicts_on_cant_tell": forced, "forced_verdict_control": ctl, "rows": out}
    json.dump(res, open("run_out_v0_21.json", "w"), ensure_ascii=False, indent=1)
    print(f"selftest {ok}/{total}; naive wrong {naive_wrong}/{len(ROWS)} (new shapes {new_wrong}/{len(NEW_ROWS)}); forced verdicts on can't-tell {forced}/{len(ct)}")
    for r in out:
        if not r["pass"]:
            print("FAIL", r["id"], "struct", r["struct"], "naive", r["naive"], "exp", r["expected"])
    if not ctl:
        print("FAIL forced-verdict-control", forced, "of", len(ct))
    sys.exit(0 if ok == total else 1)

if __name__ == "__main__":
    main()
