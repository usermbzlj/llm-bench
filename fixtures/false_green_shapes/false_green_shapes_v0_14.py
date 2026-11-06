#!/usr/bin/env python3
"""FALSE_GREEN_SHAPES v0.14

Adds one peer-supplied shape on top of v0.13 (prior files untouched; S7-S25
rows re-run here by import so one command checks S7-S26).

  S26 IDEMPOTENCY_KEY_UNSTABLE  Presence of an idempotency_key field must not
                              count as aided replay if the value drifts across
                              attempts. Distinct from S21 IDEMPOTENCY_UNAIDED
                              (field absent). Struct:
                                - key field absent -> FAIL/IDEMPOTENCY_UNAIDED
                                  (reuse S21 code; keep as sibling)
                                - key present but empty/null
                                  -> FAIL/KEY_EMPTY
                                - key present but values differ across attempts
                                  -> FAIL/KEY_UNSTABLE
                                - green twin: same non-empty key across attempts
                              Credit: 码不停蹄 (key 存在但每次生成值不同; 重放被判成
                              两次不同调用; v0.9 IDEMPOTENCY_UNAIDED 只盖缺字段).

Each shape: must-fail arm (naive wrong) + green twin.
analyze_only. Stdlib only. Run: python3 false_green_shapes_v0_14.py
"""
from __future__ import annotations
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import false_green_shapes_v0_13 as v13


def s26_naive(r):
    # Naive: field present (even if values drift) -> aided / OK
    if "idempotency_key" in r or r.get("key_field_present"):
        return "OK"
    if r.get("attempts") and any("idempotency_key" in a for a in r["attempts"]):
        return "OK"
    return "FAIL"


def s26_struct(r):
    attempts = r.get("attempts")
    if attempts is not None:
        if not isinstance(attempts, list) or len(attempts) == 0:
            return "FAIL/IDEMPOTENCY_UNAIDED"
        keys = []
        for a in attempts:
            if "idempotency_key" not in a:
                return "FAIL/IDEMPOTENCY_UNAIDED"
            k = a.get("idempotency_key")
            if k is None or k == "":
                return "FAIL/KEY_EMPTY"
            keys.append(k)
        if len(set(keys)) > 1:
            return "FAIL/KEY_UNSTABLE"
        return "OK"
    # Single-shot form
    if "idempotency_key" not in r and not r.get("key_field_present"):
        return "FAIL/IDEMPOTENCY_UNAIDED"
    k = r.get("idempotency_key")
    if k is None or k == "":
        return "FAIL/KEY_EMPTY"
    if r.get("key_values") and len(set(r["key_values"])) > 1:
        return "FAIL/KEY_UNSTABLE"
    return "OK"


NEW_ROWS = [
  # Observed: key field present; value changes every attempt
  ("S26-mf-obs", "S26", "observed_shape_desensitized(码不停蹄)",
   {"key_field_present": True,
    "attempts": [
      {"idempotency_key": "k-111"},
      {"idempotency_key": "k-222"},
      {"idempotency_key": "k-333"},
    ]},
   "FAIL/KEY_UNSTABLE", True),
  # Present but empty
  ("S26-mf-empty", "S26", "hand_built",
   {"key_field_present": True, "idempotency_key": "",
    "attempts": [{"idempotency_key": ""}]},
   "FAIL/KEY_EMPTY", True),
  # Field absent (sibling of S21; keep covered here too)
  ("S26-mf-absent", "S26", "hand_built",
   {"attempts": [{"status": "ok"}, {"status": "ok"}]},
   "FAIL/IDEMPOTENCY_UNAIDED", True),
  # key_values list drifts
  ("S26-mf-values", "S26", "hand_built",
   {"key_field_present": True, "idempotency_key": "k-a",
    "key_values": ["k-a", "k-b"]},
   "FAIL/KEY_UNSTABLE", True),
  # Green twin: stable non-empty key across attempts
  ("S26-gt", "S26", "hand_built",
   {"key_field_present": True,
    "attempts": [
      {"idempotency_key": "stable-9f3"},
      {"idempotency_key": "stable-9f3"},
    ]},
   "OK", False),
]

FNS = dict(v13.FNS)
FNS.update({"S26": (s26_naive, s26_struct)})
ROWS = list(v13.ROWS) + NEW_ROWS
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
    new_wrong = sum(1 for r in out if r["shape"] == "S26" and r["naive"] != r["expected"])
    res = {"fixture": "FALSE_GREEN_SHAPES", "version": "0.14", "selftest": f"{ok}/{total}",
           "naive_wrong_rows": naive_wrong, "naive_wrong_new_shapes": f"{new_wrong}/{len(NEW_ROWS)}",
           "naive_forced_verdicts_on_cant_tell": forced, "forced_verdict_control": ctl, "rows": out}
    json.dump(res, open("run_out_v0_14.json", "w"), ensure_ascii=False, indent=1)
    print(f"selftest {ok}/{total}; naive wrong {naive_wrong}/{len(ROWS)} (new shapes {new_wrong}/{len(NEW_ROWS)}); forced verdicts on can't-tell {forced}/{len(ct)}")
    for r in out:
        if not r["pass"]:
            print("FAIL_ROW", r)
    return 0 if ok == total else 1

if __name__ == "__main__":
    sys.exit(main())
