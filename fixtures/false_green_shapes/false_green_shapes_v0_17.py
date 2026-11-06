#!/usr/bin/env python3
"""FALSE_GREEN_SHAPES v0.17

Adds one peer-supplied shape on top of v0.16 (prior files untouched; S7-S28
rows re-run here by import so one command checks S7-S29).

  S29 EXIT_CODE_PRODUCT_DIVERGENCE  exit_code alone must not decide product
                              success. Pair of complementary false verdicts:
                                - exit_code!=0 + product_present=true
                                  -> naive FAIL (false fail); struct OK
                                  (product + optional content digest decides)
                                - exit_code==0 + product_present=false
                                  -> naive OK (false green); struct
                                  FAIL/PRODUCT_MISSING
                              When platform_scoped=true, require an explicit
                              platform_scope matching the observed host
                              (e.g. windows+powershell); otherwise
                              UNKNOWN/PLATFORM_SCOPED so cross-platform
                              runners do not treat the arm as flaky green.
                              Credit: 小花花 (Windows + PowerShell + single
                              process: NativeCommandError wraps stderr success
                              tip into exit 1 while product is on disk; reverse
                              twin exit 0 with no product).

Each shape: must-fail arm (naive wrong) + green twin.
analyze_only. Stdlib only. Run: python3 false_green_shapes_v0_17.py
"""
from __future__ import annotations
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import false_green_shapes_v0_16 as v16


def s29_naive(r):
    # Naive: exit code alone
    code = r.get("exit_code")
    if code is None:
        return "FAIL"
    try:
        return "OK" if int(code) == 0 else "FAIL"
    except (TypeError, ValueError):
        return "FAIL"


def s29_struct(r):
    if r.get("platform_scoped") is True:
        scope = (r.get("platform_scope") or "").lower().replace(" ", "")
        allowed = {s.lower().replace(" ", "") for s in (r.get("allowed_scopes") or ["windows+powershell", "windows+pwsh"])}
        if not scope or scope not in allowed:
            return "UNKNOWN/PLATFORM_SCOPED"
    product = r.get("product_present")
    if product is True:
        # Optional digest / business assert: if declared, must hold
        if r.get("content_digest_ok") is False:
            return "FAIL/PRODUCT_DIGEST"
        if r.get("business_assert_ok") is False:
            return "FAIL/PRODUCT_ASSERT"
        return "OK"
    if product is False:
        return "FAIL/PRODUCT_MISSING"
    return "UNKNOWN/PRODUCT_UNDECLARED"


NEW_ROWS = [
  # Observed false-fail: exit 1 but product on disk (stderr tip -> NativeCommandError)
  ("S29-mf-falsefail-obs", "S29", "observed_shape_desensitized(小花花)",
   {"exit_code": 1, "product_present": True, "receipt_persisted": False,
    "content_digest_ok": True, "business_assert_ok": True,
    "platform_scoped": True, "platform_scope": "windows+powershell"},
   "OK", True),
  # Observed reverse twin: exit 0 but no product (false green)
  ("S29-mf-falsepass-obs", "S29", "observed_shape_desensitized(小花花)",
   {"exit_code": 0, "product_present": False, "receipt_persisted": False,
    "platform_scoped": True, "platform_scope": "windows+powershell"},
   "FAIL/PRODUCT_MISSING", True),
  # Platform-scoped without scope -> can't tell (must not force FAIL/OK)
  ("S29-ct-noscope", "S29", "hand_built",
   {"exit_code": 1, "product_present": True, "platform_scoped": True,
    "platform_scope": ""},
   "UNKNOWN/PLATFORM_SCOPED", True),
  # Digest declared false even when product present
  ("S29-mf-digest", "S29", "hand_built",
   {"exit_code": 0, "product_present": True, "content_digest_ok": False,
    "platform_scoped": False},
   "FAIL/PRODUCT_DIGEST", True),
  # Green twin: exit 0 + product present
  ("S29-gt", "S29", "hand_built",
   {"exit_code": 0, "product_present": True, "receipt_persisted": True,
    "content_digest_ok": True, "business_assert_ok": True,
    "platform_scoped": False},
   "OK", False),
]

FNS = dict(v16.FNS)
FNS.update({"S29": (s29_naive, s29_struct)})
ROWS = list(v16.ROWS) + NEW_ROWS
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
    new_wrong = sum(1 for r in out if r["shape"] == "S29" and r["naive"] != r["expected"])
    res = {"fixture": "FALSE_GREEN_SHAPES", "version": "0.17", "selftest": f"{ok}/{total}",
           "naive_wrong_rows": naive_wrong, "naive_wrong_new_shapes": f"{new_wrong}/{len(NEW_ROWS)}",
           "naive_forced_verdicts_on_cant_tell": forced, "forced_verdict_control": ctl, "rows": out}
    json.dump(res, open("run_out_v0_17.json", "w"), ensure_ascii=False, indent=1)
    print(f"selftest {ok}/{total}; naive wrong {naive_wrong}/{len(ROWS)} (new shapes {new_wrong}/{len(NEW_ROWS)}); forced verdicts on can't-tell {forced}/{len(ct)}")
    for r in out:
        if not r["pass"]:
            print("FAIL", r["id"], "struct", r["struct"], "naive", r["naive"], "exp", r["expected"])
    if not ctl:
        print("FAIL forced-verdict-control", forced, "of", len(ct))
    sys.exit(0 if ok == total else 1)

if __name__ == "__main__":
    main()
