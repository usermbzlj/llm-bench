#!/usr/bin/env python3
"""FALSE_GREEN_SHAPES v0.29

Adds one peer-supplied shape on top of v0.28 (prior files untouched; S7-S41
rows re-run here by import so one command checks S7-S42).

  S42 SELF_ASSERTED_RUN_ID / ARTIFACT_RUN_ID_MISMATCH
      artifact_run_id must come from the scheduler/invocation (CLI arg /
      env), not from product metadata alone. Observed: product copied from
      a template that hard-coded the previous run's run_id; naive PASS on
      "run_id present in product"; scoped criterion FAIL when
      product.run_id != scheduler.run_id. Also distinguish:
        LEDGER_ROW_PRODUCT_MISSING  — ledger has row, product path gone
        PRODUCT_NO_LEDGER_ROW       — product exists, no ledger evidence
      Naive greens: run_id_present / status==ok / fingerprint_ok alone.
      Struct requires:
        - scheduler_run_id (str; authoritative)
        - product_run_id (str|None; from product metadata)
        - product_exists (bool)
        - ledger_has_row (bool)
        - fingerprint_includes_run_id (bool; must be true to claim OK)
      Rules:
        - product_exists AND product_run_id != scheduler_run_id ->
          FAIL/SELF_ASSERTED_RUN_ID
        - ledger_has_row AND not product_exists ->
          FAIL/LEDGER_ROW_PRODUCT_MISSING
        - product_exists AND not ledger_has_row ->
          FAIL/PRODUCT_NO_LEDGER_ROW
        - claiming OK without fingerprint_includes_run_id ->
          UNKNOWN/RUN_SCOPED_FP_UNDECLARED
        - all match + fp includes run_id + ledger+product -> OK
      Credit: Hermes (EigenFlux PM — observed template-copied stale
      product_run_id; requested dual codes for ledger/product asymmetry).

analyze_only. Stdlib only. Run: python3 false_green_shapes_v0_29.py
"""
from __future__ import annotations
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import false_green_shapes_v0_28 as v28


def s42_naive(r):
    if r.get("status") == "ok":
        return "OK"
    if r.get("run_id_present") is True:
        return "OK"
    if r.get("fingerprint_ok") is True:
        return "OK"
    if r.get("product_exists") is True and r.get("product_run_id"):
        return "OK"
    if r.get("ok") is True:
        return "OK"
    return "FAIL"


def s42_struct(r):
    if "scheduler_run_id" not in r:
        return "UNKNOWN/SCHEDULER_RUN_ID_UNDECLARED"
    if "product_exists" not in r or "ledger_has_row" not in r:
        return "UNKNOWN/ARTIFACT_LEDGER_UNDECLARED"
    sched = r.get("scheduler_run_id")
    prod_exists = r.get("product_exists") is True
    ledger = r.get("ledger_has_row") is True
    prod_rid = r.get("product_run_id")
    claiming_ok = (
        r.get("status") == "ok"
        or r.get("ok") is True
        or r.get("run_id_present") is True
        or r.get("fingerprint_ok") is True
    )

    if ledger and not prod_exists:
        return "FAIL/LEDGER_ROW_PRODUCT_MISSING"
    if prod_exists and not ledger:
        return "FAIL/PRODUCT_NO_LEDGER_ROW"
    if prod_exists and prod_rid is not None and prod_rid != sched:
        return "FAIL/SELF_ASSERTED_RUN_ID"
    if claiming_ok and "fingerprint_includes_run_id" not in r:
        return "UNKNOWN/RUN_SCOPED_FP_UNDECLARED"
    if (
        prod_exists
        and ledger
        and prod_rid == sched
        and r.get("fingerprint_includes_run_id") is True
    ):
        return "OK"
    if claiming_ok and r.get("fingerprint_includes_run_id") is not True:
        return "UNKNOWN/RUN_SCOPED_FP_UNDECLARED"
    return "FAIL"


NEW_ROWS = [
  ("S42-mf-stale-product-run-id", "S42", "observed_shape_desensitized(Hermes)",
   {"arm": "template_copied_prev_run_id",
    "scheduler_run_id": "run_20261107_0401",
    "product_run_id": "run_20261107_0330",
    "product_exists": True, "ledger_has_row": True,
    "run_id_present": True, "fingerprint_ok": True, "status": "ok",
    "fingerprint_includes_run_id": False},
   "FAIL/SELF_ASSERTED_RUN_ID", True),
  ("S42-mf-ledger-product-missing", "S42", "observed_shape_desensitized(Hermes)",
   {"scheduler_run_id": "run_20261107_0401", "product_run_id": None,
    "product_exists": False, "ledger_has_row": True,
    "status": "ok", "run_id_present": True},
   "FAIL/LEDGER_ROW_PRODUCT_MISSING", True),
  ("S42-mf-product-no-ledger", "S42", "hand_built",
   {"scheduler_run_id": "run_20261107_0401",
    "product_run_id": "run_20261107_0401",
    "product_exists": True, "ledger_has_row": False,
    "fingerprint_ok": True},
   "FAIL/PRODUCT_NO_LEDGER_ROW", True),
  ("S42-ct-fp-undeclared", "S42", "hand_built",
   {"scheduler_run_id": "run_20261107_0401",
    "product_run_id": "run_20261107_0401",
    "product_exists": True, "ledger_has_row": True,
    "status": "ok", "run_id_present": True},
   "UNKNOWN/RUN_SCOPED_FP_UNDECLARED", True),
  ("S42-gt-run-scoped-match", "S42", "hand_built",
   {"scheduler_run_id": "run_20261107_0401",
    "product_run_id": "run_20261107_0401",
    "product_exists": True, "ledger_has_row": True,
    "fingerprint_includes_run_id": True, "status": "ok"},
   "OK", False),
]

FNS = dict(v28.FNS)
FNS.update({"S42": (s42_naive, s42_struct)})
ROWS = list(v28.ROWS) + NEW_ROWS
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
    new_wrong = sum(1 for r in out if r["shape"] == "S42" and r["naive"] != r["expected"])
    res = {"fixture": "FALSE_GREEN_SHAPES", "version": "0.29", "selftest": f"{ok}/{total}",
           "naive_wrong_rows": naive_wrong, "naive_wrong_new_shapes": f"{new_wrong}/{len(NEW_ROWS)}",
           "naive_forced_verdicts_on_cant_tell": forced, "forced_verdict_control": ctl, "rows": out}
    json.dump(res, open("run_out_v0_29.json", "w"), ensure_ascii=False, indent=1)
    print(f"selftest {ok}/{total}; naive wrong {naive_wrong}/{len(ROWS)} (new shapes {new_wrong}/{len(NEW_ROWS)}); forced verdicts on can't-tell {forced}/{len(ct)}")
    for r in out:
        if not r["pass"]:
            print("FAIL_ROW", r)
    return 0 if ok == total else 1

if __name__ == "__main__":
    raise SystemExit(main())
