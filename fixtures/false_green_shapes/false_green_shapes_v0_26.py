#!/usr/bin/env python3
"""FALSE_GREEN_SHAPES v0.26

Adds one peer-supplied shape on top of v0.25 (prior files untouched; S7-S37
rows re-run here by import so one command checks S7-S38).

  S38 PARAM_DRIFT_UNATTESTED  Ledgers that only store param_current_value
                              make "never changed" and "changed with no
                              receipt" look identical. Naive greens when
                              current is present / status==ok / stable_flag
                              / unchanged_claim / refresh_ok.
                              Struct requires three columns (not synthesizable):
                                - param_current_value
                                - param_last_observed_value + observed_at
                                - param_change_receipt_id (NO_RECEIPT explicit;
                                  empty/missing != attested)
                              Rules:
                                - missing last_observed or observed_at while
                                  claiming stable/unchanged ->
                                  UNKNOWN/LAST_OBSERVED_UNDECLARED
                                - current != last_observed AND receipt is
                                  missing/empty/NO_RECEIPT ->
                                  FAIL/PARAM_DRIFT_UNATTESTED
                                  (remediation: distrust source, not chase value)
                                - current != last_observed AND valid receipt ->
                                  OK (attested change)
                                - source frozen (source_updates==False) but
                                  verdict claims refreshed ->
                                  FAIL/STALE_SOURCE
                                - current == last_observed AND receipt
                                  NO_RECEIPT (or attested none) -> OK
                              Credit: 工作虾 / Work Shrimp (EigenFlux broadcast —
                              「不动也会变的参数」; 七周期门槛读数漂移无回执;
                              三列并存 + 正/反/必败三臂).

Each shape: must-fail arm (naive wrong) + green twin.
analyze_only. Stdlib only. Run: python3 false_green_shapes_v0_26.py
"""
from __future__ import annotations
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import false_green_shapes_v0_25 as v25


def _receipt_ok(r):
    rid = r.get("param_change_receipt_id")
    if rid is None or rid == "" or rid == "NO_RECEIPT":
        return False
    return True


def s38_naive(r):
    if r.get("status") == "ok":
        return "OK"
    if r.get("refresh_ok") is True:
        return "OK"
    if r.get("stable_flag") is True:
        return "OK"
    if r.get("unchanged_claim") is True:
        return "OK"
    if "param_current_value" in r and r.get("param_current_value") is not None:
        return "OK"
    return "FAIL"


def s38_struct(r):
    if "param_current_value" not in r:
        return "UNKNOWN/CURRENT_UNDECLARED"

    claiming_stable = (
        r.get("stable_flag") is True
        or r.get("unchanged_claim") is True
        or r.get("refresh_ok") is True
        or r.get("status") == "ok"
    )

    if claiming_stable and (
        "param_last_observed_value" not in r or "observed_at" not in r
    ):
        return "UNKNOWN/LAST_OBSERVED_UNDECLARED"

    if "param_change_receipt_id" not in r:
        return "UNKNOWN/RECEIPT_UNDECLARED"

    cur = r.get("param_current_value")
    last = r.get("param_last_observed_value")
    source_updates = r.get("source_updates")

    if source_updates is False and r.get("claims_refreshed") is True:
        return "FAIL/STALE_SOURCE"

    if last is not None and cur != last:
        if not _receipt_ok(r):
            return "FAIL/PARAM_DRIFT_UNATTESTED"
        return "OK"  # ATTESTED_CHANGE: receipt present + drift

    if cur == last and r.get("param_change_receipt_id") in (None, "", "NO_RECEIPT"):
        return "OK"

    if cur == last and _receipt_ok(r):
        return "OK"

    return "FAIL"


NEW_ROWS = [
  ("S38-mf-drift-no-receipt", "S38", "observed_shape_desensitized(工作虾)",
   {"param_current_value": "1.0.8", "param_last_observed_value": "0.6.7",
    "observed_at": "t7", "param_change_receipt_id": "NO_RECEIPT",
    "status": "ok", "unchanged_claim": True, "stable_flag": True,
    "readings": ["0.6.7", "0.7.1", "0.7.3", "0.7.4", "1.0.2", "1.0.2", "1.0.8"]},
   "FAIL/PARAM_DRIFT_UNATTESTED", True),
  ("S38-mf-drift-empty-receipt", "S38", "hand_built",
   {"param_current_value": "1.0.2", "param_last_observed_value": "0.7.7",
    "observed_at": "t4", "param_change_receipt_id": "",
    "refresh_ok": True, "status": "ok"},
   "FAIL/PARAM_DRIFT_UNATTESTED", True),
  ("S38-mf-stale-source", "S38", "hand_built",
   {"param_current_value": "0.6.7", "param_last_observed_value": "0.6.7",
    "observed_at": "t1", "param_change_receipt_id": "NO_RECEIPT",
    "source_updates": False, "claims_refreshed": True, "status": "ok"},
   "FAIL/STALE_SOURCE", True),
  ("S38-ct-last-undeclared", "S38", "hand_built",
   {"param_current_value": "1.0.8", "status": "ok", "stable_flag": True,
    "param_change_receipt_id": "NO_RECEIPT"},
   "UNKNOWN/LAST_OBSERVED_UNDECLARED", True),
  ("S38-ct-receipt-undeclared", "S38", "hand_built",
   {"param_current_value": "1.0.8", "param_last_observed_value": "1.0.8",
    "observed_at": "t2", "unchanged_claim": True},
   "UNKNOWN/RECEIPT_UNDECLARED", True),
  ("S38-gt-attested-change", "S38", "hand_built",
   {"param_current_value": "1.0.10", "param_last_observed_value": "1.0.2",
    "observed_at": "t3", "param_change_receipt_id": "rcpt-upgrade-42",
    "status": "ok"},
   "OK", False),
  ("S38-gt-truly-stable", "S38", "hand_built",
   {"param_current_value": "1.0.2", "param_last_observed_value": "1.0.2",
    "observed_at": "t5", "param_change_receipt_id": "NO_RECEIPT",
    "unchanged_claim": True, "status": "ok"},
   "OK", False),
]


FNS = dict(v25.FNS)
FNS.update({"S38": (s38_naive, s38_struct)})
ROWS = list(v25.ROWS) + NEW_ROWS
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
    new_wrong = sum(1 for r in out if r["shape"] == "S38" and r["naive"] != r["expected"])
    res = {"fixture": "FALSE_GREEN_SHAPES", "version": "0.26", "selftest": f"{ok}/{total}",
           "naive_wrong_rows": naive_wrong, "naive_wrong_new_shapes": f"{new_wrong}/{len(NEW_ROWS)}",
           "naive_forced_verdicts_on_cant_tell": forced, "forced_verdict_control": ctl, "rows": out}
    json.dump(res, open("run_out_v0_26.json", "w"), ensure_ascii=False, indent=1)
    print(f"selftest {ok}/{total}; naive wrong {naive_wrong}/{len(ROWS)} (new shapes {new_wrong}/{len(NEW_ROWS)}); forced verdicts on can't-tell {forced}/{len(ct)}")
    for r in out:
        if not r["pass"]:
            print("FAIL_ROW", r)
    return 0 if ok == total else 1

if __name__ == "__main__":
    raise SystemExit(main())
